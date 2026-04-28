"""Agent controller — the core reasoning loop.

Implements: plan → execute → observe → repeat (up to MAX_AGENT_STEPS).
Terminates when the LLM returns tool == "finish".
"""

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


def get_pending_approval(session_id):
    """Get pending approval for a session, if any."""
    return _pending_approvals.get(session_id)


def resolve_approval(session_id, approved):
    """Resolve a pending approval. Returns the command result or denial message."""
    pending = _pending_approvals.pop(session_id, None)
    if not pending:
        return None

    if approved:
        # Execute the command directly (bypass approval check)
        from tools.system_tools import _execute_command
        cmd = pending["args"].get("cmd", "")
        result = _execute_command(cmd)
        db.add_message(session_id, "assistant", f"✅ Command approved and executed:\n{result}")
        return result
    else:
        msg = "❌ Command denied by user."
        db.add_message(session_id, "assistant", msg)
        return msg


def run(task, session_id=None):
    """Run the agent on a task.

    Args:
        task: The user's request string.
        session_id: Optional session ID. If None, uses the active session.

    Returns:
        The agent's final response string.
    """
    # Resolve session
    if session_id is None:
        session = db.get_active_session()
        session_id = session["id"]

    # Save the user message
    db.add_message(session_id, "user", task)

    # Auto-compact if session is too long
    auto_compact_if_needed(session_id)

    # Build context from memory
    context = build_context(session_id)

    # Get tool metadata
    tools_meta = registry.get_all_metadata()

    steps = []
    final_answer = None

    for step_num in range(1, config.MAX_AGENT_STEPS + 1):
        log.info("Step %d/%d for task: %s", step_num, config.MAX_AGENT_STEPS, task[:80])

        # Build messages for the LLM
        messages = build_planner_messages(
            task=task,
            context=context,
            steps=steps if steps else None,
            tools_metadata=tools_meta,
        )

        # Call the LLM
        try:
            raw_response = chat(messages)
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
            continue

        # Execute the tool
        log.info("Executing tool: %s with args: %s", tool_name, tool_args)
        observation = registry.execute(tool_name, tool_args)

        # Handle approval-required commands
        if observation.startswith("APPROVAL_REQUIRED:"):
            log.info("Tool requires approval: %s", tool_name)
            # Store pending approval for the bot to handle
            _pending_approvals[session_id] = {
                "tool": tool_name,
                "args": tool_args,
                "step": step_num,
                "task": task,
            }
            final_answer = (
                f"⚠️ **Approval Required**\n\n"
                f"Command: `{tool_args.get('cmd', '')}`\n\n"
                f"This command needs your approval before I can run it.\n"
                f"Reply /approve to execute or /deny to cancel."
            )
            db.add_message(session_id, "assistant", final_answer)
            db.log_task(session_id, task, steps, final_answer)
            return final_answer

        # Truncate very long observations
        if len(observation) > 2000:
            observation = observation[:2000] + "\n... (truncated)"

        log.info("Observation (%d chars): %s", len(observation), observation[:200])

        steps.append({
            "step": step_num,
            "action": f"{tool_name}({tool_args})",
            "observation": observation,
        })

    # If we exhausted steps without finishing
    if final_answer is None:
        if steps:
            last_obs = steps[-1].get("observation", "")
            final_answer = (
                f"I reached the maximum number of steps ({config.MAX_AGENT_STEPS}). "
                f"Here's what I found so far:\n\n{last_obs}"
            )
        else:
            final_answer = "I wasn't able to process that request."

    # Save the assistant message
    db.add_message(session_id, "assistant", final_answer)

    # Log the task
    db.log_task(session_id, task, steps, final_answer)

    return final_answer
