"""PhoneClaw Telegram bot — polling-based interface to the agent."""

import os
import sys
import time

from telegram import Update, BotCommand
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ChatAction

import agent
import config
from memory import db
from memory.compaction import compact_session
from tools.registry import registry
from utils.logger import get_logger

log = get_logger("telegram")

_MAX_MESSAGE_LEN = 4096  # Telegram's limit
_start_time = time.time()

# Telegram app reference for scheduler notifications
_telegram_app = None
_notify_chat_id = None


def _is_allowed(update):
    """Check if the user is allowed to interact with the bot."""
    user_id = update.effective_user.id
    if config.ALLOWED_USER_ID and user_id != config.ALLOWED_USER_ID:
        log.warning("Unauthorized user: %d", user_id)
        return False
    return True


def _split_message(text):
    """Split a long message into chunks that fit Telegram's limit."""
    if len(text) <= _MAX_MESSAGE_LEN:
        return [text]

    chunks = []
    while text:
        if len(text) <= _MAX_MESSAGE_LEN:
            chunks.append(text)
            break
        # Try to split at a newline near the limit
        split_at = text.rfind("\n", 0, _MAX_MESSAGE_LEN)
        if split_at == -1 or split_at < _MAX_MESSAGE_LEN // 2:
            split_at = _MAX_MESSAGE_LEN
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


# ── Command Handlers ──────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    await update.message.reply_text(
        "🦞 *PhoneClaw* is ready\\!\n\n"
        "Send me any message and I'll work on it\\.\n\n"
        "*Commands:*\n"
        "/new \\- New session\n"
        "/sessions \\- List sessions\n"
        "/switch `<id>` \\- Switch session\n"
        "/reset \\- Clear current session\n"
        "/tools \\- List available tools\n"
        "/status \\- System status\n"
        "/compact \\- Compress conversation history\n"
        "/schedules \\- List scheduled tasks\n"
        "/skills \\- List loaded skills\n"
        "/approve \\- Approve a pending command\n"
        "/deny \\- Deny a pending command",
        parse_mode="MarkdownV2",
    )


async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    title = " ".join(context.args) if context.args else "New Session"
    session = db.create_session(title)
    await update.message.reply_text(
        f"Created session #{session['id']}: {session['title']}"
    )


async def cmd_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    sessions = db.list_sessions()
    if not sessions:
        await update.message.reply_text("No sessions yet. Send a message to start!")
        return

    lines = []
    for s in sessions:
        marker = "▸" if s["is_active"] else " "
        lines.append(f"{marker} #{s['id']}: {s['title']}  [{s['created_at'][:10]}]")
    await update.message.reply_text("Sessions:\n" + "\n".join(lines))


async def cmd_switch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /switch <session_id>")
        return
    try:
        sid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Session ID must be a number.")
        return

    session = db.switch_session(sid)
    if session:
        await update.message.reply_text(f"Switched to session #{session['id']}: {session['title']}")
    else:
        await update.message.reply_text(f"Session #{sid} not found.")


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    session = db.get_active_session()
    db.clear_messages(session["id"])
    await update.message.reply_text(f"Cleared session #{session['id']}: {session['title']}")


async def cmd_tools(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    tools = registry.get_all_metadata()
    lines = [f"Available tools ({len(tools)}):"]
    for t in tools:
        lines.append(f"• {t['name']}: {t['description']}")
    await update.message.reply_text("\n".join(lines))


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    uptime_secs = int(time.time() - _start_time)
    hours, remainder = divmod(uptime_secs, 3600)
    mins, secs = divmod(remainder, 60)

    session = db.get_active_session()
    sessions = db.list_sessions()
    tools_count = len(registry)

    try:
        import resource
        mem_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        mem_str = f"{mem_mb:.1f} MB"
    except ImportError:
        # Windows fallback
        try:
            import psutil
            mem_str = f"{psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024:.1f} MB"
        except ImportError:
            mem_str = "N/A"
    except Exception:
        mem_str = "N/A"

    await update.message.reply_text(
        f"PhoneClaw Status\n"
        f"Uptime: {hours}h {mins}m {secs}s\n"
        f"Active session: #{session['id']} ({session['title']})\n"
        f"Total sessions: {len(sessions)}\n"
        f"Tools loaded: {tools_count}\n"
        f"Memory usage: {mem_str}\n"
        f"LLM: {config.NVIDIA_MODEL}\n"
        f"Python: {sys.version.split()[0]}\n"
        f"Compactions: {db.get_compaction_count(session['id'])}"
    )


async def cmd_compact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    session = db.get_active_session()
    instruction = " ".join(context.args) if context.args else None

    await update.message.reply_text("Compacting conversation history...")
    stats = compact_session(session["id"], instruction=instruction)

    if stats:
        await update.message.reply_text(
            f"Compacted session #{stats['session_id']}:\n"
            f"Messages: {stats['messages_before']} → {stats['messages_after']}\n"
            f"Tokens: ~{stats['tokens_before']} → ~{stats['tokens_after']} "
            f"(saved ~{stats['tokens_saved']})"
        )
    else:
        await update.message.reply_text("No compaction needed — session is small enough.")


async def cmd_schedules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    tasks = db.list_scheduled_tasks(include_inactive=False)
    if not tasks:
        await update.message.reply_text("No active scheduled tasks.")
        return
    lines = ["Active scheduled tasks:"]
    for t in tasks:
        kind = "one-shot" if t["schedule_type"] == "at" else f"every {t['schedule_value']}"
        lines.append(f"#{t['id']}: [{kind}] {t['prompt'][:60]}\n  Next: {t['next_run']}")
    await update.message.reply_text("\n".join(lines))


async def cmd_skills(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    try:
        from skills.loader import list_skill_info
        skills = list_skill_info()
    except Exception:
        skills = []
    if not skills:
        await update.message.reply_text("No skills loaded.")
        return
    lines = [f"Skills ({len(skills)}):"]
    for s in skills:
        status = "✓" if s["eligible"] else "✗"
        desc = f" — {s['description']}" if s["description"] else ""
        lines.append(f"{status} {s['name']}{desc}")
    await update.message.reply_text("\n".join(lines))


async def cmd_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    session = db.get_active_session()
    pending = agent.get_pending_approval(session["id"])
    if not pending:
        await update.message.reply_text("No pending command to approve.")
        return
    await update.message.reply_text("Executing approved command...")
    result = agent.resolve_approval(session["id"], approved=True)
    chunks = _split_message(f"✅ Result:\n{result}")
    for chunk in chunks:
        await update.message.reply_text(chunk)


async def cmd_deny(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return
    session = db.get_active_session()
    pending = agent.get_pending_approval(session["id"])
    if not pending:
        await update.message.reply_text("No pending command to deny.")
        return
    agent.resolve_approval(session["id"], approved=False)
    await update.message.reply_text("❌ Command denied.")


# ── Message Handler ───────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update):
        return

    user_text = update.message.text
    if not user_text or not user_text.strip():
        return

    log.info("Message from %d: %s", update.effective_user.id, user_text[:80])

    # Track chat ID for scheduler notifications
    global _notify_chat_id
    _notify_chat_id = update.effective_chat.id

    # Show typing indicator
    await update.message.chat.send_action(ChatAction.TYPING)

    try:
        result = agent.run(user_text)
    except Exception as exc:
        log.error("Agent error: %s", exc, exc_info=True)
        result = f"Error: {exc}"

    # Send response (split if needed)
    chunks = _split_message(result)
    for chunk in chunks:
        await update.message.reply_text(chunk)


# ── Notifications (used by scheduler) ─────────────────────────────────────

def send_notification(text):
    """Send a notification message to the user (called by scheduler)."""
    import asyncio

    if not _telegram_app or not _notify_chat_id:
        log.warning("Cannot send notification: no chat ID or app reference")
        return

    async def _send():
        try:
            chunks = _split_message(text)
            for chunk in chunks:
                await _telegram_app.bot.send_message(
                    chat_id=_notify_chat_id,
                    text=chunk,
                )
        except Exception as exc:
            log.error("Failed to send notification: %s", exc)

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(_send())
        else:
            loop.run_until_complete(_send())
    except RuntimeError:
        asyncio.run(_send())


# ── Bot Startup ───────────────────────────────────────────────────────────

def start_bot():
    """Start the Telegram bot with polling."""
    if not config.TELEGRAM_BOT_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN not set!")
        return

    log.info("Starting Telegram bot...")

    app = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).build()

    # Store app reference for scheduler notifications
    global _telegram_app
    _telegram_app = app

    # Register commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("sessions", cmd_sessions))
    app.add_handler(CommandHandler("switch", cmd_switch))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("tools", cmd_tools))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("compact", cmd_compact))
    app.add_handler(CommandHandler("schedules", cmd_schedules))
    app.add_handler(CommandHandler("skills", cmd_skills))
    app.add_handler(CommandHandler("approve", cmd_approve))
    app.add_handler(CommandHandler("deny", cmd_deny))

    # Regular messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("Telegram bot started, polling...")
    app.run_polling(drop_pending_updates=True)