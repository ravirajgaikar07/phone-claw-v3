"""Prompt templates for the PhoneClaw agent planner."""

import json
from pathlib import Path

import config
from utils.logger import get_logger

log = get_logger("llm.prompts")

_soul_cache = None


def _load_soul():
    global _soul_cache
    if _soul_cache is not None:
        return _soul_cache
    try:
        path = Path(config.SOUL_PATH)
        if path.exists():
            _soul_cache = path.read_text(encoding="utf-8").strip()
            log.info("Loaded soul from %s (%d chars)", path, len(_soul_cache))
        else:
            _soul_cache = ""
            log.warning("Soul file not found: %s", path)
    except Exception as exc:
        log.warning("Failed to load soul: %s", exc)
        _soul_cache = ""
    return _soul_cache


def format_tools_for_prompt(tools_metadata):
    """Format tool metadata list into a string for the system prompt."""
    lines = []
    for tool in tools_metadata:
        args_str = json.dumps(tool.get("args", {}))
        lines.append(f'- {tool["name"]}: {tool["description"]}  args={args_str}')
    return "\n".join(lines)


def build_system_prompt(tools_metadata):
    """Build the full system prompt including persona, skills, and tool descriptions."""
    soul = _load_soul()
    tools_text = format_tools_for_prompt(tools_metadata)

    parts = []

    if soul:
        parts.append(soul)
        parts.append("")

    # Inject skills if available
    try:
        from skills.loader import build_skills_prompt
        skills_prompt = build_skills_prompt()
        if skills_prompt:
            parts.append(skills_prompt)
            parts.append("")
    except Exception as exc:
        log.debug("Skills not loaded: %s", exc)

    parts.append("# Available Tools")
    parts.append(tools_text)
    parts.append("")
    parts.append("# Response Format")
    parts.append(
        "You MUST respond with ONLY a valid JSON object. No extra text.\n"
        "To call a tool:\n"
        '{"tool": "tool_name", "args": {<arguments>}, "thought": "brief reasoning"}\n\n'
        "To give a final answer (when done or no tool needed):\n"
        '{"tool": "finish", "args": {"output": "your answer"}, "thought": "brief reasoning"}\n\n'
        "IMPORTANT RULES:\n"
        "- Always respond with a single JSON object\n"
        "- Use the exact tool names and argument names shown above\n"
        "- If a tool returns an error, you may retry with different args or finish with an explanation\n"
        "- When the task is complete, you MUST use the finish tool\n"
        "- Keep thoughts concise\n"
        "- Use memory_save to remember important facts, user preferences, or key findings\n"
        "- Use memory_search to recall previously saved information"
    )

    return "\n".join(parts)


def build_planner_messages(task, context=None, steps=None, tools_metadata=None):
    """Build the full message list for the planner LLM call.

    Args:
        task: The user's task/question.
        context: Optional context string (memory/history).
        steps: List of previous step dicts [{"step": N, "action": ..., "observation": ...}].
        tools_metadata: List of tool metadata dicts.

    Returns:
        List of message dicts for the LLM.
    """
    if tools_metadata is None:
        tools_metadata = []

    messages = [{"role": "system", "content": build_system_prompt(tools_metadata)}]

    # Build the user message with context and step history
    user_parts = []

    if context:
        user_parts.append(f"# Context\n{context}")

    user_parts.append(f"# Task\n{task}")

    if steps:
        user_parts.append("# Previous Steps")
        for s in steps:
            user_parts.append(
                f"Step {s['step']}: Called {s['action']}\n"
                f"Observation: {s['observation']}"
            )
        user_parts.append(
            "\nBased on the above, decide the next step or finish."
        )

    messages.append({"role": "user", "content": "\n\n".join(user_parts)})

    return messages
