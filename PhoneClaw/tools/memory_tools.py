"""Memory tools — save, search, and retrieve long-term agent memory."""

from tools.registry import registry
from memory import db
from utils.logger import get_logger

log = get_logger("tools.memory")


@registry.register(
    "memory_save",
    "Save a note to long-term memory. Use to remember facts, preferences, or important information.",
    {"topic": "string (category/topic name)", "content": "string (the information to remember)"},
)
def memory_save(topic, content):
    if not topic or not topic.strip():
        return "ERROR: Topic is required"
    if not content or not content.strip():
        return "ERROR: Content is required"
    topic = topic.strip().lower().replace(" ", "-")
    db.save_note(topic, content.strip())
    return f"Saved to memory under topic '{topic}'"


@registry.register(
    "memory_search",
    "Search long-term memory for relevant notes. Returns matching notes ranked by relevance.",
    {"query": "string (search keywords)"},
)
def memory_search(query):
    if not query or not query.strip():
        return "ERROR: Query is required"
    results = db.search_notes_fts(query.strip(), limit=5)
    if not results:
        return "No matching memories found."
    lines = []
    for r in results:
        content = r["content"]
        if len(content) > 400:
            content = content[:400] + "..."
        lines.append(f"[{r['topic']}] (updated {r['updated_at'][:10]})\n{content}")
    return "\n\n".join(lines)


@registry.register(
    "memory_get",
    "Get a specific memory note by topic name.",
    {"topic": "string (exact topic name)"},
)
def memory_get(topic):
    if not topic or not topic.strip():
        return "ERROR: Topic is required"
    topic = topic.strip().lower().replace(" ", "-")
    note = db.get_note(topic)
    if not note:
        # Try search as fallback
        results = db.search_notes_fts(topic, limit=1)
        if results:
            note = results[0]
        else:
            return f"No memory found for topic '{topic}'"
    return f"Topic: {note['topic']}\nUpdated: {note['updated_at']}\n\n{note['content']}"
