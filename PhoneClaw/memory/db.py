"""SQLite database — sessions, messages, and task logs."""

import sqlite3
import json
import datetime

import config
from utils.logger import get_logger

log = get_logger("memory.db")

_conn = None


def _get_conn():
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _init_tables(_conn)
        log.info("Database opened: %s", config.DB_PATH)
    return _conn


def _init_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL DEFAULT 'New Session',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 0,
            compaction_count INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );

        CREATE TABLE IF NOT EXISTS task_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            task TEXT NOT NULL,
            steps_json TEXT,
            result TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS memory_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            content TEXT NOT NULL,
            source TEXT DEFAULT 'agent',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS scheduled_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prompt TEXT NOT NULL,
            schedule_type TEXT NOT NULL,
            schedule_value TEXT NOT NULL,
            next_run TEXT NOT NULL,
            last_run TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_messages_session
            ON messages(session_id, timestamp);
        CREATE INDEX IF NOT EXISTS idx_task_logs_session
            ON task_logs(session_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_memory_notes_topic
            ON memory_notes(topic);
        CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_status
            ON scheduled_tasks(status, next_run);

        CREATE TABLE IF NOT EXISTS dream_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dream_text TEXT NOT NULL,
            source_notes TEXT,
            source_messages INTEGER DEFAULT 0,
            score REAL DEFAULT 0.0,
            created_at TEXT NOT NULL
        );
    """)
    # FTS5 for memory search (keyword search across notes)
    try:
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts
            USING fts5(topic, content)
        """)
    except Exception as exc:
        log.warning("FTS5 not available: %s (keyword search will fall back to LIKE)", exc)
    # Add compaction_count column if migrating from older schema
    try:
        conn.execute("ALTER TABLE sessions ADD COLUMN compaction_count INTEGER NOT NULL DEFAULT 0")
    except Exception:
        pass  # Column already exists
    conn.commit()


def _now():
    return datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"


# ── Sessions ──────────────────────────────────────────────────────────────

def create_session(title="New Session"):
    conn = _get_conn()
    now = _now()
    # Deactivate all other sessions
    conn.execute("UPDATE sessions SET is_active = 0")
    cur = conn.execute(
        "INSERT INTO sessions (title, created_at, updated_at, is_active) VALUES (?, ?, ?, 1)",
        (title, now, now),
    )
    conn.commit()
    session_id = cur.lastrowid
    log.info("Created session #%d: %s", session_id, title)
    return {"id": session_id, "title": title, "created_at": now, "is_active": True}


def get_active_session():
    conn = _get_conn()
    row = conn.execute("SELECT * FROM sessions WHERE is_active = 1 LIMIT 1").fetchone()
    if row:
        return dict(row)
    # Auto-create a default session if none exists
    return create_session("Default Session")


def list_sessions():
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM sessions ORDER BY updated_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def switch_session(session_id):
    conn = _get_conn()
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not row:
        return None
    conn.execute("UPDATE sessions SET is_active = 0")
    conn.execute(
        "UPDATE sessions SET is_active = 1, updated_at = ? WHERE id = ?",
        (_now(), session_id),
    )
    conn.commit()
    log.info("Switched to session #%d", session_id)
    return dict(conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone())


def delete_session(session_id):
    conn = _get_conn()
    conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM task_logs WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()
    log.info("Deleted session #%d", session_id)


# ── Messages ──────────────────────────────────────────────────────────────

def add_message(session_id, role, content):
    conn = _get_conn()
    now = _now()
    conn.execute(
        "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
        (session_id, role, content, now),
    )
    conn.execute(
        "UPDATE sessions SET updated_at = ? WHERE id = ?",
        (now, session_id),
    )
    conn.commit()


def get_messages(session_id, limit=20):
    conn = _get_conn()
    rows = conn.execute(
        "SELECT role, content, timestamp FROM messages "
        "WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?",
        (session_id, limit),
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


def clear_messages(session_id):
    conn = _get_conn()
    conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    conn.commit()
    log.info("Cleared messages for session #%d", session_id)


# ── Task Logs ─────────────────────────────────────────────────────────────

def log_task(session_id, task, steps, result):
    conn = _get_conn()
    conn.execute(
        "INSERT INTO task_logs (session_id, task, steps_json, result, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (session_id, task, json.dumps(steps), result, _now()),
    )
    conn.commit()


def get_recent_tasks(session_id, limit=5):
    conn = _get_conn()
    rows = conn.execute(
        "SELECT task, result, created_at FROM task_logs "
        "WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
        (session_id, limit),
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


def get_session_history(session_id):
    """Get full session data including messages and tasks."""
    conn = _get_conn()
    session = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not session:
        return None
    messages = get_messages(session_id, limit=100)
    tasks = get_recent_tasks(session_id, limit=20)
    return {
        "session": dict(session),
        "messages": messages,
        "tasks": tasks,
    }


# ── Compaction ────────────────────────────────────────────────────────────

def replace_messages_with_summary(session_id, summary, keep_recent):
    """Replace old messages with a summary, keeping the most recent ones."""
    conn = _get_conn()
    # Get IDs of messages to keep (most recent N)
    keep_rows = conn.execute(
        "SELECT id FROM messages WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?",
        (session_id, keep_recent),
    ).fetchall()
    keep_ids = {r["id"] for r in keep_rows}

    if keep_ids:
        placeholders = ",".join("?" for _ in keep_ids)
        conn.execute(
            f"DELETE FROM messages WHERE session_id = ? AND id NOT IN ({placeholders})",
            (session_id, *keep_ids),
        )
    else:
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))

    # Insert summary as a system message at the beginning
    # Use a timestamp just before the oldest remaining message
    oldest = conn.execute(
        "SELECT MIN(timestamp) as ts FROM messages WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    summary_ts = oldest["ts"] if oldest and oldest["ts"] else _now()
    # Make it slightly earlier
    summary_ts = summary_ts.replace("Z", "") + "Z" if summary_ts.endswith("Z") else summary_ts

    conn.execute(
        "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
        (session_id, "system", f"[Conversation Summary]\n{summary}", summary_ts),
    )
    conn.commit()
    log.info("Replaced old messages with summary for session #%d", session_id)


def increment_compaction_count(session_id):
    conn = _get_conn()
    conn.execute(
        "UPDATE sessions SET compaction_count = compaction_count + 1 WHERE id = ?",
        (session_id,),
    )
    conn.commit()


def get_compaction_count(session_id):
    conn = _get_conn()
    row = conn.execute(
        "SELECT compaction_count FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    return row["compaction_count"] if row else 0


# ── Memory Notes ──────────────────────────────────────────────────────────

def save_note(topic, content, source="agent"):
    """Save or append a memory note for a topic."""
    conn = _get_conn()
    now = _now()
    # Check if topic already exists
    existing = conn.execute(
        "SELECT id, content FROM memory_notes WHERE topic = ?", (topic,)
    ).fetchone()

    if existing:
        new_content = existing["content"] + "\n" + content
        conn.execute(
            "UPDATE memory_notes SET content = ?, updated_at = ? WHERE id = ?",
            (new_content, now, existing["id"]),
        )
        note_id = existing["id"]
    else:
        cur = conn.execute(
            "INSERT INTO memory_notes (topic, content, source, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (topic, content, source, now, now),
        )
        note_id = cur.lastrowid

    # Update FTS index
    _index_note_fts(conn, note_id, topic, content if not existing else new_content)
    conn.commit()
    log.info("Saved note for topic '%s'", topic)
    return note_id


def search_notes_fts(query, limit=5):
    """Search notes using FTS5 full-text search."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT topic, content, rank FROM notes_fts "
            "WHERE notes_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, limit),
        ).fetchall()
        # FTS table doesn't have updated_at, so fetch from main table
        results = []
        for r in rows:
            note = conn.execute(
                "SELECT topic, content, updated_at FROM memory_notes WHERE topic = ?",
                (r["topic"],),
            ).fetchone()
            if note:
                results.append(dict(note))
        return results
    except Exception:
        # Fallback to LIKE search if FTS5 not available
        return search_notes_like(query, limit)


def search_notes_like(query, limit=5):
    """Fallback keyword search using LIKE."""
    conn = _get_conn()
    pattern = f"%{query}%"
    rows = conn.execute(
        "SELECT topic, content, updated_at FROM memory_notes "
        "WHERE topic LIKE ? OR content LIKE ? "
        "ORDER BY updated_at DESC LIMIT ?",
        (pattern, pattern, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_note(topic):
    """Get a specific note by topic."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT topic, content, source, created_at, updated_at FROM memory_notes WHERE topic = ?",
        (topic,),
    ).fetchone()
    return dict(row) if row else None


def list_notes():
    """List all memory note topics."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT topic, substr(content, 1, 100) as preview, updated_at "
        "FROM memory_notes ORDER BY updated_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def _index_note_fts(conn, note_id, topic, content):
    """Update the FTS5 index for a note."""
    try:
        # Delete old entry if exists
        conn.execute("DELETE FROM notes_fts WHERE rowid = ?", (note_id,))
        # Insert new
        conn.execute(
            "INSERT INTO notes_fts(rowid, topic, content) VALUES (?, ?, ?)",
            (note_id, topic, content),
        )
    except Exception as exc:
        log.debug("FTS index update skipped: %s", exc)


# ── Scheduled Tasks ───────────────────────────────────────────────────────

def add_scheduled_task(prompt, schedule_type, schedule_value, next_run):
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO scheduled_tasks (prompt, schedule_type, schedule_value, next_run, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (prompt, schedule_type, schedule_value, next_run, _now()),
    )
    conn.commit()
    return cur.lastrowid


def get_due_tasks(now_iso):
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM scheduled_tasks WHERE status = 'active' AND next_run <= ?",
        (now_iso,),
    ).fetchall()
    return [dict(r) for r in rows]


def update_scheduled_task(task_id, next_run=None, last_run=None, status=None):
    conn = _get_conn()
    parts, vals = [], []
    if next_run is not None:
        parts.append("next_run = ?")
        vals.append(next_run)
    if last_run is not None:
        parts.append("last_run = ?")
        vals.append(last_run)
    if status is not None:
        parts.append("status = ?")
        vals.append(status)
    if parts:
        vals.append(task_id)
        conn.execute(f"UPDATE scheduled_tasks SET {', '.join(parts)} WHERE id = ?", vals)
        conn.commit()


def list_scheduled_tasks(include_inactive=False):
    conn = _get_conn()
    if include_inactive:
        rows = conn.execute("SELECT * FROM scheduled_tasks ORDER BY next_run").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM scheduled_tasks WHERE status = 'active' ORDER BY next_run"
        ).fetchall()
    return [dict(r) for r in rows]


def cancel_scheduled_task(task_id):
    conn = _get_conn()
    row = conn.execute("SELECT id FROM scheduled_tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        return False
    conn.execute("UPDATE scheduled_tasks SET status = 'cancelled' WHERE id = ?", (task_id,))
    conn.commit()
    return True


# ── Dreaming ──────────────────────────────────────────────────────────────

def get_recent_notes(hours=24, limit=20):
    """Get memory notes updated within the last N hours."""
    conn = _get_conn()
    cutoff = (
        datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
    ).isoformat(timespec="seconds") + "Z"
    rows = conn.execute(
        "SELECT topic, content, updated_at FROM memory_notes "
        "WHERE updated_at >= ? ORDER BY updated_at DESC LIMIT ?",
        (cutoff, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_recent_messages_all(hours=24, limit=50):
    """Get recent messages across all sessions for dreaming."""
    conn = _get_conn()
    cutoff = (
        datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
    ).isoformat(timespec="seconds") + "Z"
    rows = conn.execute(
        "SELECT m.role, m.content, m.timestamp, s.title as session_title "
        "FROM messages m JOIN sessions s ON m.session_id = s.id "
        "WHERE m.timestamp >= ? ORDER BY m.timestamp DESC LIMIT ?",
        (cutoff, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def save_dream(dream_text, source_notes, source_messages, score):
    """Save a dream entry."""
    conn = _get_conn()
    conn.execute(
        "INSERT INTO dream_log (dream_text, source_notes, source_messages, score, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (dream_text, source_notes, source_messages, score, _now()),
    )
    conn.commit()


def get_recent_dreams(limit=5):
    """Get recent dreams."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT dream_text, score, created_at FROM dream_log "
        "ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]