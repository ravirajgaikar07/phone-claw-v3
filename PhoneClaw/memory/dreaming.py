"""Background Dreaming — periodic subconscious reflection and memory consolidation."""

import os
import datetime

import config
from memory import db
from llm.client import chat
from utils.logger import get_logger

log = get_logger("dreaming")

DREAMS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "DREAMS.md")

_DREAM_SYSTEM_PROMPT = """You are PhoneClaw's subconscious dreaming process.
Your job is to review recent memories and conversations, find patterns, 
connections, and insights, then produce a short reflective "dream" entry.

Guidelines:
- Be concise (2-5 sentences per dream)
- Focus on patterns, recurring themes, unresolved questions, or creative connections
- Write in first person as PhoneClaw
- If nothing interesting stands out, say so briefly
- Do NOT fabricate facts — only reflect on what you're given"""

_DREAM_USER_TEMPLATE = """Here are my recent memories and conversations from the last {hours} hours.
Reflect on them and produce a dream entry.

## Recent Memory Notes
{notes_section}

## Recent Conversations
{messages_section}

Write a short dream reflection (2-5 sentences). Start directly with the reflection."""


def _score_material(notes, messages):
    """Score how interesting the available material is (0.0 to 1.0)."""
    score = 0.0
    # More notes = more to reflect on
    score += min(len(notes) * 0.1, 0.4)
    # More messages = more activity
    score += min(len(messages) * 0.02, 0.3)
    # Variety of topics
    topics = {n["topic"] for n in notes}
    score += min(len(topics) * 0.05, 0.2)
    # Recency bonus: notes updated very recently
    now = datetime.datetime.utcnow()
    for n in notes[:3]:
        try:
            updated = datetime.datetime.fromisoformat(n["updated_at"].replace("Z", "+00:00"))
            age_hours = (now.replace(tzinfo=updated.tzinfo) - updated).total_seconds() / 3600
            if age_hours < 2:
                score += 0.05
        except (ValueError, TypeError):
            pass
    return min(score, 1.0)


def _format_notes(notes):
    if not notes:
        return "(no recent notes)"
    lines = []
    for n in notes[:15]:
        content = n["content"]
        if len(content) > 300:
            content = content[:300] + "..."
        lines.append(f"- **{n['topic']}**: {content}")
    return "\n".join(lines)


def _format_messages(messages):
    if not messages:
        return "(no recent conversations)"
    lines = []
    for m in messages[:30]:
        role = m["role"].upper()
        content = m["content"]
        if len(content) > 200:
            content = content[:200] + "..."
        session = m.get("session_title", "?")
        lines.append(f"[{session}/{role}] {content}")
    return "\n".join(lines)


def dream_cycle(hours=24):
    """Run one dream cycle: gather material, score, generate dream, save.

    Returns the dream text or None if material was too thin.
    """
    log.info("Dream cycle starting (looking back %dh)", hours)

    notes = db.get_recent_notes(hours=hours)
    messages = db.get_recent_messages_all(hours=hours)

    score = _score_material(notes, messages)
    log.info("Dream material score: %.2f (min: %.2f)", score, config.DREAM_MIN_SCORE)

    if score < config.DREAM_MIN_SCORE:
        log.info("Not enough material to dream — skipping")
        return None

    prompt = _DREAM_USER_TEMPLATE.format(
        hours=hours,
        notes_section=_format_notes(notes),
        messages_section=_format_messages(messages),
    )

    try:
        dream_text = chat(
            messages=[
                {"role": "system", "content": _DREAM_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.9,  # More creative for dreaming
            max_tokens=300,
        )
    except Exception as exc:
        log.error("Dream LLM call failed: %s", exc)
        return None

    if not dream_text or not dream_text.strip():
        log.warning("Dream produced empty output")
        return None

    dream_text = dream_text.strip()

    # Save to database
    source_topics = ", ".join(n["topic"] for n in notes[:5])
    db.save_dream(dream_text, source_topics, len(messages), score)

    # Append to DREAMS.md
    _append_to_dreams_file(dream_text, score)

    log.info("Dream saved (score=%.2f): %s", score, dream_text[:80])
    return dream_text


def _append_to_dreams_file(dream_text, score):
    """Append a dream entry to DREAMS.md."""
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    entry = f"\n## {now} (score: {score:.2f})\n{dream_text}\n"

    if not os.path.exists(DREAMS_PATH):
        with open(DREAMS_PATH, "w", encoding="utf-8") as f:
            f.write("# PhoneClaw Dreams\n\nSubconscious reflections and pattern recognition.\n")

    with open(DREAMS_PATH, "a", encoding="utf-8") as f:
        f.write(entry)
