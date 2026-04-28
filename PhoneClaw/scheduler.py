"""Scheduler — background thread that fires scheduled agent tasks."""

import re
import threading
import datetime

import config
from memory import db
from utils.logger import get_logger

log = get_logger("scheduler")

_scheduler_instance = None


class Scheduler:
    """Simple cron-lite scheduler with one-shot and recurring tasks."""

    def __init__(self, agent_run_fn, notify_fn=None):
        """
        Args:
            agent_run_fn: callable(prompt) -> result string
            notify_fn: callable(result) -> None, for sending results (e.g. Telegram)
        """
        self._agent_run = agent_run_fn
        self._notify = notify_fn
        self._timer = None
        self._running = False

    def start(self):
        self._running = True
        log.info("Scheduler started (check every %ds)", config.SCHEDULER_CHECK_INTERVAL)
        self._tick()

    def stop(self):
        self._running = False
        if self._timer:
            self._timer.cancel()
        log.info("Scheduler stopped")

    def _tick(self):
        if not self._running:
            return
        try:
            self._check_due_tasks()
        except Exception as exc:
            log.error("Scheduler tick error: %s", exc, exc_info=True)
        # Schedule next tick
        self._timer = threading.Timer(config.SCHEDULER_CHECK_INTERVAL, self._tick)
        self._timer.daemon = True
        self._timer.start()

    def _check_due_tasks(self):
        now = datetime.datetime.utcnow()
        now_iso = now.isoformat(timespec="seconds") + "Z"
        due = db.get_due_tasks(now_iso)

        for task in due:
            log.info("Running scheduled task #%d: %s", task["id"], task["prompt"][:60])
            try:
                result = self._agent_run(task["prompt"])
            except Exception as exc:
                log.error("Scheduled task #%d failed: %s", task["id"], exc)
                result = f"Scheduled task error: {exc}"

            # Update task state
            db.update_scheduled_task(task["id"], last_run=now_iso)

            if task["schedule_type"] == "at":
                # One-shot: mark completed
                db.update_scheduled_task(task["id"], status="completed")
                log.info("One-shot task #%d completed", task["id"])
            elif task["schedule_type"] == "every":
                # Recurring: calculate next run
                next_run = _calc_next_run(task["schedule_value"], now)
                db.update_scheduled_task(task["id"], next_run=next_run)
                log.info("Recurring task #%d next run: %s", task["id"], next_run)

            # Notify user
            if self._notify:
                try:
                    header = f"⏰ Scheduled task #{task['id']}:\n{task['prompt'][:100]}\n\n"
                    self._notify(header + result)
                except Exception as exc:
                    log.error("Notify failed for task #%d: %s", task["id"], exc)


def parse_schedule(schedule_str):
    """Parse a schedule string into (type, value, next_run_iso).

    Supported formats:
        "at 2024-01-01T12:00:00Z"  — one-shot at ISO timestamp
        "in 20m"                   — one-shot in N minutes/hours/days
        "every 30m"               — recurring every N minutes
        "every 2h"                — recurring every N hours
        "every 1d"                — recurring every N days

    Returns (schedule_type, schedule_value, next_run_iso) or raises ValueError.
    """
    schedule_str = schedule_str.strip()
    now = datetime.datetime.utcnow()

    # "in Xm/Xh/Xd" — one-shot relative
    m = re.match(r"^in\s+(\d+)\s*(m|min|h|hr|hour|d|day)s?$", schedule_str, re.I)
    if m:
        amount = int(m.group(1))
        unit = m.group(2)[0].lower()
        delta = _unit_to_delta(amount, unit)
        next_run = (now + delta).isoformat(timespec="seconds") + "Z"
        return "at", schedule_str, next_run

    # "at <ISO timestamp>"
    m = re.match(r"^at\s+(.+)$", schedule_str, re.I)
    if m:
        ts = m.group(1).strip()
        # Validate ISO format
        try:
            parsed = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
            next_run = parsed.strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            raise ValueError(f"Invalid timestamp: {ts}")
        return "at", ts, next_run

    # "every Xm/Xh/Xd" — recurring
    m = re.match(r"^every\s+(\d+)\s*(m|min|h|hr|hour|d|day)s?$", schedule_str, re.I)
    if m:
        amount = int(m.group(1))
        unit = m.group(2)[0].lower()
        delta = _unit_to_delta(amount, unit)
        next_run = (now + delta).isoformat(timespec="seconds") + "Z"
        return "every", f"{amount}{unit}", next_run

    raise ValueError(
        f"Invalid schedule: '{schedule_str}'. "
        "Use: 'in 20m', 'at 2024-01-01T12:00:00Z', 'every 30m', 'every 2h', 'every 1d'"
    )


def _unit_to_delta(amount, unit):
    if unit == "m":
        return datetime.timedelta(minutes=amount)
    elif unit == "h":
        return datetime.timedelta(hours=amount)
    elif unit == "d":
        return datetime.timedelta(days=amount)
    raise ValueError(f"Unknown time unit: {unit}")


def _calc_next_run(schedule_value, from_time):
    """Calculate the next run time for a recurring schedule."""
    m = re.match(r"^(\d+)([mhd])$", schedule_value)
    if not m:
        # Fallback: 1 hour
        delta = datetime.timedelta(hours=1)
    else:
        amount = int(m.group(1))
        unit = m.group(2)
        delta = _unit_to_delta(amount, unit)
    return (from_time + delta).isoformat(timespec="seconds") + "Z"


def get_scheduler():
    return _scheduler_instance


def set_scheduler(instance):
    global _scheduler_instance
    _scheduler_instance = instance
