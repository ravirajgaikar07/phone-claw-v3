"""Context builder — assembles conversation context for the planner."""

from memory import db
from utils.logger import get_logger

log = get_logger("memory.context")

_MAX_CONTEXT_CHARS = 4000


def build_context(session_id, max_messages=10):
    """Build a context string from recent conversation history and past tasks.

    Returns a formatted string ready for prompt injection, or empty string.
    """
    parts = []

    # Recent conversation messages
    messages = db.get_messages(session_id, limit=max_messages)
    if messages:
        conv_lines = []
        for m in messages:
            role = m["role"].capitalize()
            content = m["content"]
            if len(content) > 500:
                content = content[:500] + "..."
            conv_lines.append(f"{role}: {content}")
        parts.append("## Recent Conversation\n" + "\n".join(conv_lines))

    # Recent task results (for richer context)
    tasks = db.get_recent_tasks(session_id, limit=3)
    if tasks:
        task_lines = []
        for t in tasks:
            result_preview = t["result"] or ""
            if len(result_preview) > 300:
                result_preview = result_preview[:300] + "..."
            task_lines.append(f"- Task: {t['task']}\n  Result: {result_preview}")
        parts.append("## Recent Task Results\n" + "\n".join(task_lines))

    context = "\n\n".join(parts)

    # Truncate if too long
    if len(context) > _MAX_CONTEXT_CHARS:
        context = context[:_MAX_CONTEXT_CHARS] + "\n... (context truncated)"

    return context
