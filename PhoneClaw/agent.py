"""Agent controller — the core reasoning loop.

Implements: plan → execute → observe → repeat (up to MAX_AGENT_STEPS).
Terminates when the LLM returns tool == "finish".

Phase 0 hardening:
- Reflexion: after REFLEXION_AFTER_ERRORS consecutive errors on the same tool,
  spend one extra LLM call to generate a reflection that's stored and injected
  into the next attempt (deduped by error hash so we don't burn tokens).
- Stuck counter: bail with an "ask user" answer after STUCK_ERROR_LIMIT
  consecutive ERROR observations.
- Checkpoints: snapshot the steps list to SQLite after each iteration so the
  user can inspect / restore later.
"""

import hashlib

import config
from llm.client import chat, LLMError
from llm.json_parser import extract_json
from llm.prompts import build_planner_messages
from memory import db
from memory.context import build_context
from memory.compaction import auto_compact_if_needed
from tools.registry import registry
from tools import session_tools
from utils.logger import get_logger

log = get_logger("agent")

# Wire session tools to the database module
session_tools.set_db(db)

# Pending command approvals: session_id -> {tool, args, step, task}
_pending_approvals = {}

# Subagent recursion depth (per-thread). The `task` tool reads & increments
# this so nested agent loops can be bounded by SUBAGENT_MAX_DEPTH.
import threading
_subagent_local = threading.local()


def _current_depth():
    return getattr(_subagent_local, "depth", 0)


def _push_depth():
    _subagent_local.depth = _current_depth() + 1


def _pop_depth():
    d = _current_depth()
    _subagent_local.depth = max(0, d - 1)


def _error_hash(error_text):
    """Stable short hash of an error string for reflection dedup."""
    return hashlib.sha1(error_text.encode("utf-8", errors="replace")).hexdigest()[:12]


def _generate_reflection(task, tool_name, tool_args, error):
    """One cheap LLM call: 'what went wrong, what to try differently'."""
    prompt = (
        "You just attempted a tool call that failed. In 2-3 short sentences, "
        "diagnose the likely cause and suggest a concrete different approach "
        "for the next attempt. Be specific. No preamble.\n\n"
        f"Task: {task}\n"
        f"Tool: {tool_name}\n"
        f"Args: {tool_args}\n"
        f"Error: {error[:600]}"
    )
    try:
        text = chat(
            [{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=config.REFLEXION_MAX_TOKENS,
        )
        return text.strip()
    except LLMError as exc:
        log.warning("Reflection generation failed: %s", exc)
        return ""


def get_pending_approval(session_id):
    """Get pending approval for a session, if any."""
    return _pending_approvals.get(session_id)


def resolve_approval(session_id, approved):
    """Resolve a pending approval. Returns the command result or denial message."""
    pending = _pending_approvals.pop(session_id, None)
    if not pending:
        return None

    if approved:
        # Execute the resolved command from the pending approval. Falls back
        # to the legacy 'cmd' arg if nothing was extracted (older flow).
        from tools.system_tools import _execute_command
        cmd = pending.get("cmd") or pending["args"].get("cmd", "")
        if not cmd:
            return "❌ No command stored for approval."
        result = _execute_command(cmd)
        db.add_message(session_id, "assistant", f"✅ Command approved and executed:\n{result}")
        return result
    else:
        msg = "❌ Command denied by user."
        db.add_message(session_id, "assistant", msg)
        return msg


def run(task, session_id=None, mode=None, think_level=None):
    """Run the agent on a task.

    Args:
        task: The user's request string.
        session_id: Optional session ID. If None, uses the active session.
        mode: Optional role override — 'planner', 'reviewer', 'qa',
            'interrogator', or None (default behaviour). Loaded from
            skills/roles/<mode>.md and appended to the system prompt.
        think_level: Optional reasoning depth — 'quick' (fast, fewer steps,
            no reflexion), 'think' (deeper, more steps, reflexion on),
            or None (default config).

    Returns:
        The agent's final response string.
    """
    # Resolve reasoning preset for this run
    preset = config.THINK_LEVELS.get(think_level) if think_level else None
    max_steps   = preset["max_steps"]   if preset else config.MAX_AGENT_STEPS
    llm_temp    = preset["temperature"] if preset else None  # None = client default
    llm_max_tok = preset["max_tokens"]  if preset else None
    use_reflexion = preset["reflexion"] if preset else True

    # Resolve session
    if session_id is None:
        session = db.get_active_session()
        session_id = session["id"]

    # Save the user message
    db.add_message(session_id, "user", task)

    # Auto-compact if session is too long
    auto_compact_if_needed(session_id)

    # Build context from memory (with episodic tier seeded by current task)
    context = build_context(session_id, task=task)

    # Get tool metadata
    tools_meta = registry.get_all_metadata()

    steps = []
    final_answer = None

    # Reflexion / stuck tracking
    consecutive_errors = 0
    last_failed_tool = None
    last_failed_tool_errors = 0  # consecutive errors on the *same* tool
    pending_reflection = None  # injected into the next step's observation

    for step_num in range(1, max_steps + 1):
        log.info("Step %d/%d for task: %s", step_num, max_steps, task[:80])

        # Build messages for the LLM
        messages = build_planner_messages(
            task=task,
            context=context,
            steps=steps if steps else None,
            tools_metadata=tools_meta,
            role=mode,
            think_level=think_level,
        )

        # Call the LLM
        try:
            raw_response = chat(messages, temperature=llm_temp, max_tokens=llm_max_tok)
        except LLMError as exc:
            log.error("LLM error at step %d: %s", step_num, exc)
            final_answer = f"Sorry, I encountered an error communicating with the AI: {exc}"
            break

        # Parse the JSON response
        parsed = extract_json(raw_response)

        if parsed is None:
            log.warning("Failed to parse LLM response, asking for retry")
            # Feed error back as an observation and try again
            steps.append({
                "step": step_num,
                "action": "(parse error)",
                "observation": (
                    "Your previous response was not valid JSON. "
                    "Please respond with ONLY a JSON object."
                ),
            })
            continue

        tool_name = parsed.get("tool", "")
        tool_args = parsed.get("args", {})
        thought = parsed.get("thought", "")

        if thought:
            log.info("Thought: %s", thought)

        # Check for finish
        if tool_name == "finish":
            final_answer = tool_args.get("output", "Done.")
            log.info("Agent finished: %s", final_answer[:100])
            break

        # Check if tool exists
        if tool_name not in registry:
            log.warning("Unknown tool: %s", tool_name)
            steps.append({
                "step": step_num,
                "action": f"{tool_name}({tool_args})",
                "observation": (
                    f"ERROR: Unknown tool '{tool_name}'. "
                    f"Available tools: {', '.join(registry.list_names())}"
                ),
            })
            consecutive_errors += 1
            continue

        # Execute the tool
        log.info("Executing tool: %s with args: %s", tool_name, tool_args)
        observation = registry.execute(tool_name, tool_args)

        # Handle approval-required commands
        if observation.startswith("APPROVAL_REQUIRED:"):
            log.info("Tool requires approval: %s", tool_name)
            # Extract the actual shell command from the sentinel payload.
            # Tools may emit either:
            #   APPROVAL_REQUIRED: <cmd>
            #   APPROVAL_REQUIRED: This command needs ... : <cmd>
            payload = observation[len("APPROVAL_REQUIRED:"):].strip()
            if ":" in payload and not payload.lstrip().startswith(("termux-", "am ", "/")):
                _, _, payload = payload.partition(":")
            cmd_for_approval = (payload or tool_args.get("cmd", "")).strip()
            _pending_approvals[session_id] = {
                "tool": tool_name,
                "args": tool_args,
                "cmd": cmd_for_approval,
                "step": step_num,
                "task": task,
            }
            final_answer = (
                f"⚠️ **Approval Required**\n\n"
                f"Tool: `{tool_name}`\n"
                f"Command: `{cmd_for_approval}`\n\n"
                f"Reply /approve to execute or /deny to cancel."
            )
            db.add_message(session_id, "assistant", final_answer)
            db.log_task(session_id, task, steps, final_answer)
            return final_answer

        # Truncate very long observations
        if len(observation) > 2000:
            observation = observation[:2000] + "\n... (truncated)"

        log.info("Observation (%d chars): %s", len(observation), observation[:200])

        # Reflexion: track per-tool failure streak; on threshold, generate or
        # reuse a stored reflection and prepend it to the observation so the
        # LLM sees it on the next planning round.
        is_error = observation.startswith("ERROR:")
        if is_error:
            consecutive_errors += 1
            if tool_name == last_failed_tool:
                last_failed_tool_errors += 1
            else:
                last_failed_tool = tool_name
                last_failed_tool_errors = 1

            if last_failed_tool_errors >= config.REFLEXION_AFTER_ERRORS and use_reflexion:
                err_hash = _error_hash(observation)
                cached = db.find_reflection(session_id, tool_name, err_hash)
                if cached:
                    pending_reflection = cached
                    log.info("Reused cached reflection for %s/%s", tool_name, err_hash)
                else:
                    reflection = _generate_reflection(
                        task, tool_name, tool_args, observation
                    )
                    if reflection:
                        db.save_reflection(
                            session_id, task, tool_name, err_hash,
                            observation[:500], reflection,
                        )
                        pending_reflection = reflection
                        log.info("Generated reflection: %s", reflection[:120])
        else:
            consecutive_errors = 0
            last_failed_tool = None
            last_failed_tool_errors = 0

        # Inject any pending reflection into this observation
        if pending_reflection:
            observation = (
                f"[Reflection on prior failures]\n{pending_reflection}\n\n"
                f"[Latest observation]\n{observation}"
            )
            pending_reflection = None

        steps.append({
            "step": step_num,
            "action": f"{tool_name}({tool_args})",
            "observation": observation,
        })

        # Persist a checkpoint after each step
        try:
            db.save_checkpoint(session_id, task, step_num, steps)
        except Exception as exc:
            log.debug("Checkpoint save failed: %s", exc)

        # Stuck-out: too many consecutive errors → bail and ask the user
        if consecutive_errors >= config.STUCK_ERROR_LIMIT:
            log.warning(
                "Agent stuck after %d consecutive errors, bailing out",
                consecutive_errors,
            )
            final_answer = (
                f"I hit {consecutive_errors} consecutive errors and don't want to "
                f"keep guessing. Last error:\n\n{observation[-800:]}\n\n"
                f"Could you give me more detail or try a different angle?"
            )
            break

    # If we exhausted steps without finishing
    if final_answer is None:
        if steps:
            last_obs = steps[-1].get("observation", "")
            final_answer = (
                f"I reached the maximum number of steps ({max_steps}). "
                f"Here's what I found so far:\n\n{last_obs}"
            )
        else:
            final_answer = "I wasn't able to process that request."

    # Save the assistant message
    db.add_message(session_id, "assistant", final_answer)

    # Log the task
    db.log_task(session_id, task, steps, final_answer)

    # Trim old checkpoints so the table stays small
    try:
        db.prune_checkpoints(session_id, keep=20)
    except Exception as exc:
        log.debug("Checkpoint prune failed: %s", exc)

    return final_answer
