"""System command execution tools with safety measures."""

import subprocess

from tools.registry import registry
from utils.logger import get_logger

log = get_logger("tools.system")

_CMD_TIMEOUT = 30  # seconds
_MAX_OUTPUT = 3000  # chars

# Commands that should never be run
_BLOCKED_PATTERNS = [
    "rm -rf /",
    "mkfs.",
    "> /dev/sd",
    "dd if=",
    ":(){",
    "fork bomb",
]

# Commands that require user approval before execution
_APPROVAL_PATTERNS = [
    "rm -r",
    "rm -f",
    "rmdir",
    "apt install",
    "apt remove",
    "apt purge",
    "pkg install",
    "pkg uninstall",
    "pip install",
    "pip uninstall",
    "chmod",
    "chown",
    "kill ",
    "killall",
    "reboot",
    "shutdown",
    "poweroff",
    "systemctl",
    "service ",
    "crontab",
    "passwd",
    "useradd",
    "userdel",
    "mount",
    "umount",
    "iptables",
]


def needs_approval(cmd):
    """Check if a command requires user approval."""
    cmd_lower = cmd.lower().strip()
    for pattern in _APPROVAL_PATTERNS:
        if pattern in cmd_lower:
            return True
    return False


@registry.register(
    "run_command",
    "Run a shell command and return the output. Use for system tasks, package management, etc.",
    {"cmd": "string (shell command)"},
)
def run_command(cmd):
    if not cmd or not cmd.strip():
        return "ERROR: Empty command"

    cmd_lower = cmd.lower().strip()
    for pattern in _BLOCKED_PATTERNS:
        if pattern in cmd_lower:
            log.warning("Blocked dangerous command: %s", cmd)
            return f"ERROR: Command blocked for safety: contains '{pattern}'"

    # Check if approval is needed
    if needs_approval(cmd):
        return f"APPROVAL_REQUIRED: This command needs user approval before executing: {cmd}"

    return _execute_command(cmd)


def _execute_command(cmd):
    """Actually execute a shell command. Called directly for approved commands."""
    try:
        log.info("Executing: %s", cmd)
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=_CMD_TIMEOUT,
        )

        output = result.stdout
        if result.stderr:
            output += ("\n--- stderr ---\n" + result.stderr) if output else result.stderr

        if not output.strip():
            output = f"(command exited with code {result.returncode})"

        if len(output) > _MAX_OUTPUT:
            output = output[:_MAX_OUTPUT] + f"\n... (truncated, {len(output)} total chars)"

        return output

    except subprocess.TimeoutExpired:
        log.warning("Command timed out: %s", cmd)
        return f"ERROR: Command timed out after {_CMD_TIMEOUT}s"
    except Exception as exc:
        log.error("Command failed: %s — %s", cmd, exc)
        return f"ERROR: {exc}"