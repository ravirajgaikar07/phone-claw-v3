"""Device information tools — Termux API integration."""

import json
import subprocess

from tools.registry import registry
from utils.logger import get_logger

log = get_logger("tools.device")

_CMD_TIMEOUT = 10


def _run_termux_cmd(cmd):
    """Run a Termux API command and return its output."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=_CMD_TIMEOUT,
        )
        if result.returncode != 0:
            err = result.stderr.strip()
            if "not found" in err.lower() or "no such" in err.lower():
                return None, "Termux API not available. Install with: pkg install termux-api"
            return None, err or f"Command exited with code {result.returncode}"
        return result.stdout.strip(), None
    except subprocess.TimeoutExpired:
        return None, "Command timed out"
    except FileNotFoundError:
        return None, "Termux API not available"
    except Exception as exc:
        return None, str(exc)


@registry.register(
    "device_battery",
    "Get device battery status (level, charging state, temperature).",
    {},
)
def device_battery():
    output, err = _run_termux_cmd("termux-battery-status")
    if err:
        return f"ERROR: {err}"
    try:
        data = json.loads(output)
        return (
            f"Battery: {data.get('percentage', '?')}%\n"
            f"Status: {data.get('status', '?')}\n"
            f"Plugged: {data.get('plugged', '?')}\n"
            f"Temperature: {data.get('temperature', '?')}°C"
        )
    except (json.JSONDecodeError, KeyError):
        return output or "ERROR: Could not parse battery info"


@registry.register(
    "device_storage",
    "Get device storage usage information.",
    {},
)
def device_storage():
    output, err = _run_termux_cmd("df -h /storage/emulated/0 /data 2>/dev/null || df -h")
    if err:
        return f"ERROR: {err}"
    return output or "No storage info available"


@registry.register(
    "device_network",
    "Get current WiFi connection information.",
    {},
)
def device_network():
    output, err = _run_termux_cmd("termux-wifi-connectioninfo")
    if err:
        # Fallback: try ip command
        output2, err2 = _run_termux_cmd("ip addr show 2>/dev/null | head -30")
        if err2:
            return f"ERROR: {err}"
        return output2

    try:
        data = json.loads(output)
        return (
            f"SSID: {data.get('ssid', '?')}\n"
            f"BSSID: {data.get('bssid', '?')}\n"
            f"IP: {data.get('ip', '?')}\n"
            f"Link Speed: {data.get('link_speed_mbps', '?')} Mbps\n"
            f"Signal: {data.get('rssi', '?')} dBm\n"
            f"Frequency: {data.get('frequency_mhz', '?')} MHz"
        )
    except (json.JSONDecodeError, KeyError):
        return output


@registry.register(
    "device_info",
    "Get combined device information: battery, storage, and network.",
    {},
)
def device_info():
    sections = []

    sections.append("== Battery ==")
    sections.append(device_battery())
    sections.append("")

    sections.append("== Storage ==")
    sections.append(device_storage())
    sections.append("")

    sections.append("== Network ==")
    sections.append(device_network())

    return "\n".join(sections)
