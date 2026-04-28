"""Schedule tools — create, list, and cancel scheduled tasks."""

from tools.registry import registry
from memory import db
from scheduler import parse_schedule
from utils.logger import get_logger

log = get_logger("tools.schedule")


@registry.register(
    "schedule_task",
    "Schedule a task to run later or on a recurring basis. "
    "Formats: 'in 20m', 'in 2h', 'at 2024-01-01T12:00:00Z', 'every 30m', 'every 2h', 'every 1d'.",
    {"prompt": "string (what the agent should do)", "schedule": "string (when to run)"},
)
def schedule_task(prompt, schedule):
    if not prompt or not prompt.strip():
        return "ERROR: Prompt is required"
    if not schedule or not schedule.strip():
        return "ERROR: Schedule is required"

    try:
        stype, svalue, next_run = parse_schedule(schedule)
    except ValueError as exc:
        return f"ERROR: {exc}"

    task_id = db.add_scheduled_task(prompt.strip(), stype, svalue, next_run)
    kind = "one-shot" if stype == "at" else "recurring"
    return f"Scheduled {kind} task #{task_id}: '{prompt[:60]}' — next run: {next_run}"


@registry.register(
    "list_schedules",
    "List all active scheduled tasks.",
    {},
)
def list_schedules():
    tasks = db.list_scheduled_tasks(include_inactive=False)
    if not tasks:
        return "No active scheduled tasks."
    lines = []
    for t in tasks:
        kind = "one-shot" if t["schedule_type"] == "at" else f"every {t['schedule_value']}"
        lines.append(
            f"#{t['id']}: [{kind}] {t['prompt'][:60]} — next: {t['next_run']}"
        )
    return "\n".join(lines)


@registry.register(
    "cancel_schedule",
    "Cancel a scheduled task by its ID.",
    {"task_id": "integer (the schedule ID to cancel)"},
)
def cancel_schedule(task_id):
    try:
        task_id = int(task_id)
    except (TypeError, ValueError):
        return "ERROR: task_id must be an integer"
    if db.cancel_scheduled_task(task_id):
        return f"Cancelled scheduled task #{task_id}"
    return f"ERROR: Scheduled task #{task_id} not found"
