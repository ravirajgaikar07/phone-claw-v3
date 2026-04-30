"""Context builder — assembles conversation context for the planner.

Memory tiers surfaced here:
  * working   — current step list (lives in agent.py, not this file)
  * session   — recent messages + recent task results
  * episodic  — top-N FTS-matched memory notes for the current task
                + most-recent failure reflection from this session
  * repo      — soul.md + skills (injected by llm/prompts.py, not here)

Episodic surfacing is opt-in: callers pass `task=...` to enable it. When
no task is given (e.g. background dream cycles), behaviour is unchanged.
"""

from memory import db
from utils.logger import get_logger

log = get_logger("memory.context")

_MAX_CONTEXT_CHARS = 4000
_EPISODIC_NOTE_LIMIT = 3
_NOTE_PREVIEW_CHARS = 240


def _episodic_notes_for(task):
    """Pull a few topical notes via FTS. Empty string on any failure."""
    if not task:
        return ""
    # Use the first ~6 meaningful words as the FTS query — keeps it cheap and
    # avoids FTS5 syntax errors from punctuation in long sentences.
    words = [w.strip(".,!?;:'\"()[]") for w in task.split()]
    keywords = [w for w in words if len(w) >= 3][:6]
    if not keywords:
        return ""
    query = " OR ".join(keywords)
    try:
        notes = db.search_notes_fts(query, limit=_EPISODIC_NOTE_LIMIT)
    except Exception as exc:
        log.debug("Episodic note lookup failed: %s", exc)
        return ""
    if not notes:
        return ""
    lines = []
    for n in notes:
        preview = (n.get("content") or "")[:_NOTE_PREVIEW_CHARS]
        if len(n.get("content") or "") > _NOTE_PREVIEW_CHARS:
            preview += "..."
        lines.append(f"- [{n.get('topic')}] {preview}")
    return "## Relevant Memory\n" + "\n".join(lines)


def _recent_reflection(session_id):
    """Most recent reflection text for this session, if any."""
    try:
        rows = db.list_reflections(session_id, limit=1)
    except Exception as exc:
        log.debug("Reflection lookup failed: %s", exc)
        return ""
    if not rows:
        return ""
    r = rows[0]
    return (
        "## Recent Reflection\n"
        f"(tool={r['tool']}) {r['reflection'][:300]}"
    )


def build_context(session_id, max_messages=10, task=None):
    """Build a context string from recent conversation history and past tasks.

    Args:
        session_id: active session.
        max_messages: how many recent messages to include.
        task: optional current task text — when given, episodic memory
            (matching notes + last reflection) is appended.

    Returns:
        Formatted string ready for prompt injection, or empty string.
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

    # Episodic tier — only when we have a task to query against.
    if task:
        notes_block = _episodic_notes_for(task)
        if notes_block:
            parts.append(notes_block)
        refl_block = _recent_reflection(session_id)
        if refl_block:
            parts.append(refl_block)

    context = "\n\n".join(parts)

    # Truncate if too long
    if len(context) > _MAX_CONTEXT_CHARS:
        context = context[:_MAX_CONTEXT_CHARS] + "\n... (context truncated)"

    return context
