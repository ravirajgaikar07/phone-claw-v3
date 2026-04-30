"""Device tools — Termux:API integration.

All tools shell out to the small `termux-*` binaries shipped by the
Termux:API addon (https://wiki.termux.com/wiki/Termux:API). They follow a
single pattern:

    out, err = _run_termux_cmd("termux-foo --bar baz")

Sensitive actions (sending an SMS, dialing, recording audio, taking a
photo) return the existing `APPROVAL_REQUIRED:` sentinel so the agent
loop can route them through the user-confirm flow already wired into
the Telegram bot.

Lightweight by design — no Java bridges, no Python wrappers, just
subprocess + the JSON the binaries emit.
"""

import json
import shlex
import subprocess

from tools.registry import registry
from utils.logger import get_logger

log = get_logger("tools.device")

_CMD_TIMEOUT = 10
_LONG_CMD_TIMEOUT = 60  # for things like termux-microphone-record


def _run_termux_cmd(cmd, timeout=_CMD_TIMEOUT):
    """Run a Termux:API command and return (stdout, error)."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            err = (result.stderr or "").strip()
            if "not found" in err.lower() or "no such" in err.lower():
                return None, "Termux:API not available. Install with: pkg install termux-api"
            return None, err or f"Command exited with code {result.returncode}"
        return (result.stdout or "").strip(), None
    except subprocess.TimeoutExpired:
        return None, "Command timed out"
    except FileNotFoundError:
        return None, "Termux:API not available"
    except Exception as exc:
        return None, str(exc)


def _approval(action):
    """Build an APPROVAL_REQUIRED sentinel for a sensitive device action."""
    return f"APPROVAL_REQUIRED: {action}"


# ── Battery / Storage / Network / Info ───────────────────────────────────────


@registry.register(
    "device_battery",
    "Get device battery status (level, charging state, temperature).",
    {},
    cacheable=True,
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
    cacheable=True,
)
def device_storage():
    output, err = _run_termux_cmd("df -h /storage/emulated/0 /data 2>/dev/null || df -h")
    if err:
        return f"ERROR: {err}"
    return output or "No storage info available"


@registry.register(
    "device_network",
    "Get current network information (IP, location, ISP, and local interfaces).",
    {},
    cacheable=True,
)
def device_network():
    # Try Termux:API first
    output, err = _run_termux_cmd("termux-wifi-connectioninfo")
    if not err:
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
            pass

    # Fallback: public IP info via curl
    output2, err2 = _run_termux_cmd("curl -s --max-time 5 ipinfo.io")
    if not err2 and output2:
        try:
            data = json.loads(output2)
            parts = [
                f"IP: {data.get('ip', '?')}",
                f"City: {data.get('city', '?')}, {data.get('region', '?')}",
                f"Country: {data.get('country', '?')}",
                f"ISP: {data.get('org', '?')}",
            ]
            return "\n".join(parts)
        except (json.JSONDecodeError, KeyError):
            return output2

    # Last resort: ifconfig
    output3, err3 = _run_termux_cmd("ifconfig 2>/dev/null || cat /proc/net/if_inet6 2>/dev/null")
    if not err3 and output3:
        return output3

    return "ERROR: Could not retrieve network info (Termux:API unavailable, no internet)"


@registry.register(
    "device_info",
    "Get combined device information: battery, storage, and network.",
    {},
    cacheable=True,
)
def device_info():
    sections = []
    sections.append("== Battery ==")
    sections.append(device_battery())
    sections.append("\n== Storage ==")
    sections.append(device_storage())
    sections.append("\n== Network ==")
    sections.append(device_network())
    return "\n".join(sections)


@registry.register(
    "device_wifi_scan",
    "Scan for nearby WiFi networks. Returns SSID + signal strength list.",
    {},
)
def device_wifi_scan():
    output, err = _run_termux_cmd("termux-wifi-scaninfo", timeout=15)
    if err:
        return f"ERROR: {err}"
    try:
        nets = json.loads(output)
    except (json.JSONDecodeError, ValueError):
        return output or "(no scan results)"
    if not nets:
        return "(no networks found)"
    nets = sorted(nets, key=lambda n: n.get("rssi", -999), reverse=True)
    lines = [f"{len(nets)} networks:"]
    for n in nets[:20]:
        lines.append(
            f"- {n.get('ssid', '?'):<25} {n.get('rssi', '?')} dBm  "
            f"{n.get('frequency_mhz', '?')} MHz"
        )
    return "\n".join(lines)


# ── Location ─────────────────────────────────────────────────────────────────


@registry.register(
    "device_location",
    "Get current GPS location (lat, lon, accuracy). "
    "Provider: gps|network|passive (default network = battery-friendly).",
    {"provider": "string?"},
)
def device_location(provider="network"):
    provider = (provider or "network").lower()
    if provider not in {"gps", "network", "passive"}:
        return "ERROR: provider must be gps, network, or passive"
    output, err = _run_termux_cmd(
        f"termux-location -p {provider} -r once",
        timeout=30,
    )
    if err:
        return f"ERROR: {err}"
    try:
        data = json.loads(output)
        return (
            f"Lat: {data.get('latitude', '?')}\n"
            f"Lon: {data.get('longitude', '?')}\n"
            f"Accuracy: {data.get('accuracy', '?')} m\n"
            f"Altitude: {data.get('altitude', '?')} m\n"
            f"Speed: {data.get('speed', '?')} m/s\n"
            f"Provider: {data.get('provider', provider)}"
        )
    except (json.JSONDecodeError, KeyError):
        return output or "ERROR: no location returned"


# ── SMS / Calls / Contacts ───────────────────────────────────────────────────


@registry.register(
    "sms_inbox",
    "Read recent SMS messages. type: inbox|sent|draft|outbox. limit defaults to 10.",
    {"type": "string?", "limit": "integer?"},
    cacheable=True,
)
def sms_inbox(type="inbox", limit=10):
    box = (type or "inbox").lower()
    if box not in {"inbox", "sent", "draft", "outbox"}:
        return "ERROR: type must be inbox|sent|draft|outbox"
    try:
        n = int(limit)
    except (TypeError, ValueError):
        n = 10
    n = max(1, min(50, n))
    output, err = _run_termux_cmd(f"termux-sms-list -t {box} -l {n}")
    if err:
        return f"ERROR: {err}"
    try:
        msgs = json.loads(output)
    except (json.JSONDecodeError, ValueError):
        return output or "(no messages)"
    if not msgs:
        return "(no messages)"
    lines = [f"{len(msgs)} messages ({box}):"]
    for m in msgs:
        body = (m.get("body") or "").replace("\n", " ")[:120]
        lines.append(
            f"- [{m.get('received', '?')}] {m.get('number', '?')}  ({m.get('type','?')})\n  {body}"
        )
    return "\n".join(lines)


@registry.register(
    "sms_send",
    "Send an SMS. Requires user approval. number = phone (with country code), text = body.",
    {"number": "string", "text": "string"},
)
def sms_send(number=None, text=None):
    if not number or not text:
        return "ERROR: number and text are required"
    cmd = f"termux-sms-send -n {shlex.quote(str(number))} {shlex.quote(str(text))}"
    return _approval(cmd)


@registry.register(
    "call_log",
    "Read recent call history. limit defaults to 10.",
    {"limit": "integer?"},
    cacheable=True,
)
def call_log(limit=10):
    try:
        n = int(limit)
    except (TypeError, ValueError):
        n = 10
    n = max(1, min(50, n))
    output, err = _run_termux_cmd(f"termux-call-log -l {n}")
    if err:
        return f"ERROR: {err}"
    try:
        calls = json.loads(output)
    except (json.JSONDecodeError, ValueError):
        return output or "(no calls)"
    if not calls:
        return "(no calls)"
    lines = [f"{len(calls)} calls:"]
    for c in calls:
        lines.append(
            f"- [{c.get('date', '?')}] {c.get('type','?'):<8} "
            f"{c.get('name') or c.get('phone_number', '?')}  ({c.get('duration', '?')}s)"
        )
    return "\n".join(lines)


@registry.register(
    "contacts_query",
    "List contacts whose name or number matches a substring. Pass empty query to list all.",
    {"query": "string?"},
    cacheable=True,
)
def contacts_query(query=""):
    output, err = _run_termux_cmd("termux-contact-list", timeout=15)
    if err:
        return f"ERROR: {err}"
    try:
        contacts = json.loads(output)
    except (json.JSONDecodeError, ValueError):
        return output or "(no contacts)"
    q = (query or "").strip().lower()
    if q:
        contacts = [
            c for c in contacts
            if q in (c.get("name") or "").lower()
            or q in (c.get("number") or "")
        ]
    if not contacts:
        return "(no contacts matched)"
    lines = [f"{len(contacts)} contacts:"]
    for c in contacts[:50]:
        lines.append(f"- {c.get('name', '?'):<25} {c.get('number', '?')}")
    if len(contacts) > 50:
        lines.append(f"... (+{len(contacts) - 50} more)")
    return "\n".join(lines)


# ── Audio I/O ────────────────────────────────────────────────────────────────


@registry.register(
    "tts_speak",
    "Speak text aloud through the device's text-to-speech engine.",
    {"text": "string", "rate": "number?", "pitch": "number?"},
)
def tts_speak(text=None, rate=None, pitch=None):
    if not text:
        return "ERROR: text is required"
    parts = ["termux-tts-speak"]
    if rate is not None:
        parts.append(f"-r {float(rate)}")
    if pitch is not None:
        parts.append(f"-p {float(pitch)}")
    parts.append(shlex.quote(str(text)))
    output, err = _run_termux_cmd(" ".join(parts))
    if err:
        return f"ERROR: {err}"
    return f"spoken ({len(text)} chars)"


@registry.register(
    "mic_record",
    "Record audio from the microphone. seconds defaults to 5; saved to path.",
    {"path": "string", "seconds": "integer?"},
)
def mic_record(path=None, seconds=5):
    if not path:
        return "ERROR: path is required"
    try:
        secs = max(1, min(120, int(seconds)))
    except (TypeError, ValueError):
        secs = 5
    cmd = (
        f"termux-microphone-record -d -l {secs} -f {shlex.quote(str(path))}"
    )
    return _approval(cmd)


# ── Clipboard ────────────────────────────────────────────────────────────────


@registry.register(
    "clipboard_get",
    "Read the system clipboard contents.",
    {},
)
def clipboard_get():
    output, err = _run_termux_cmd("termux-clipboard-get")
    if err:
        return f"ERROR: {err}"
    return output or "(clipboard empty)"


@registry.register(
    "clipboard_set",
    "Write text to the system clipboard.",
    {"text": "string"},
)
def clipboard_set(text=None):
    if text is None:
        return "ERROR: text is required"
    cmd = f"echo {shlex.quote(str(text))} | termux-clipboard-set"
    output, err = _run_termux_cmd(cmd)
    if err:
        return f"ERROR: {err}"
    return f"clipboard set ({len(str(text))} chars)"


# ── Notifications, dialogs, vibration, torch, volume, brightness ─────────────


@registry.register(
    "notification_send",
    "Show an Android notification. id lets you update/dismiss the same one later.",
    {"title": "string", "content": "string?", "id": "integer?"},
)
def notification_send(title=None, content=None, id=None):
    if not title:
        return "ERROR: title is required"
    parts = ["termux-notification", "-t", shlex.quote(str(title))]
    if content:
        parts.extend(["-c", shlex.quote(str(content))])
    if id is not None:
        try:
            parts.extend(["-i", str(int(id))])
        except (TypeError, ValueError):
            pass
    output, err = _run_termux_cmd(" ".join(parts))
    if err:
        return f"ERROR: {err}"
    return "notification sent"


@registry.register(
    "notification_remove",
    "Dismiss a previously-sent notification by its id.",
    {"id": "integer"},
)
def notification_remove(id=None):
    if id is None:
        return "ERROR: id is required"
    try:
        nid = int(id)
    except (TypeError, ValueError):
        return f"ERROR: bad id: {id!r}"
    output, err = _run_termux_cmd(f"termux-notification-remove {nid}")
    if err:
        return f"ERROR: {err}"
    return f"notification {nid} removed"


@registry.register(
    "dialog_input",
    "Show a text-input dialog and return what the user typed. "
    "kind: text|password|number (default text).",
    {"title": "string?", "hint": "string?", "kind": "string?"},
)
def dialog_input(title=None, hint=None, kind="text"):
    flag = {"text": "text", "password": "password", "number": "number"}.get(
        (kind or "text").lower(), "text"
    )
    parts = ["termux-dialog", flag]
    if title:
        parts.extend(["-t", shlex.quote(str(title))])
    if hint:
        parts.extend(["-i", shlex.quote(str(hint))])
    output, err = _run_termux_cmd(" ".join(parts), timeout=300)
    if err:
        return f"ERROR: {err}"
    try:
        data = json.loads(output)
        if data.get("code") != -1:
            return f"(cancelled, code={data.get('code')})"
        return data.get("text", "")
    except (json.JSONDecodeError, ValueError):
        return output


@registry.register(
    "dialog_confirm",
    "Show a yes/no confirm dialog. Returns 'yes' or 'no'.",
    {"title": "string?", "hint": "string?"},
)
def dialog_confirm(title=None, hint=None):
    parts = ["termux-dialog", "confirm"]
    if title:
        parts.extend(["-t", shlex.quote(str(title))])
    if hint:
        parts.extend(["-i", shlex.quote(str(hint))])
    output, err = _run_termux_cmd(" ".join(parts), timeout=300)
    if err:
        return f"ERROR: {err}"
    try:
        data = json.loads(output)
        return data.get("text", "no")
    except (json.JSONDecodeError, ValueError):
        return output


@registry.register(
    "vibrate",
    "Vibrate the device. duration_ms default 500. force=true ignores silent mode.",
    {"duration_ms": "integer?", "force": "boolean?"},
)
def vibrate(duration_ms=500, force=False):
    try:
        ms = max(1, min(10000, int(duration_ms)))
    except (TypeError, ValueError):
        ms = 500
    cmd = f"termux-vibrate -d {ms}"
    if force:
        cmd += " -f"
    output, err = _run_termux_cmd(cmd)
    if err:
        return f"ERROR: {err}"
    return f"vibrated {ms}ms"


@registry.register(
    "torch",
    "Toggle the device flashlight (torch). on=true to enable, false to disable.",
    {"on": "boolean"},
)
def torch(on=True):
    state = "on" if on else "off"
    output, err = _run_termux_cmd(f"termux-torch {state}")
    if err:
        return f"ERROR: {err}"
    return f"torch {state}"


@registry.register(
    "volume_get",
    "Read all audio stream volumes.",
    {},
    cacheable=True,
)
def volume_get():
    output, err = _run_termux_cmd("termux-volume")
    if err:
        return f"ERROR: {err}"
    try:
        streams = json.loads(output)
        lines = ["Volume:"]
        for s in streams:
            lines.append(
                f"- {s.get('stream', '?'):<12} {s.get('volume', '?')}/{s.get('max_volume', '?')}"
            )
        return "\n".join(lines)
    except (json.JSONDecodeError, ValueError):
        return output


@registry.register(
    "volume_set",
    "Set a stream's volume. stream: music|call|ring|alarm|notification|system. "
    "level is the absolute target.",
    {"stream": "string", "level": "integer"},
)
def volume_set(stream=None, level=None):
    if not stream or level is None:
        return "ERROR: stream and level are required"
    try:
        lvl = int(level)
    except (TypeError, ValueError):
        return f"ERROR: bad level: {level!r}"
    output, err = _run_termux_cmd(
        f"termux-volume {shlex.quote(str(stream))} {lvl}"
    )
    if err:
        return f"ERROR: {err}"
    return f"{stream} volume → {lvl}"


@registry.register(
    "brightness_set",
    "Set screen brightness 0..255 (or 'auto').",
    {"level": "integer|string"},
)
def brightness_set(level=None):
    if level is None:
        return "ERROR: level is required"
    if isinstance(level, str) and level.lower() == "auto":
        arg = "auto"
    else:
        try:
            arg = str(max(0, min(255, int(level))))
        except (TypeError, ValueError):
            return f"ERROR: bad level: {level!r}"
    output, err = _run_termux_cmd(f"termux-brightness {arg}")
    if err:
        return f"ERROR: {err}"
    return f"brightness → {arg}"


# ── Telephony ────────────────────────────────────────────────────────────────


@registry.register(
    "telephony_info",
    "Show SIM/cellular information (carrier, network type, phone type).",
    {},
    cacheable=True,
)
def telephony_info():
    output, err = _run_termux_cmd("termux-telephony-deviceinfo")
    if err:
        return f"ERROR: {err}"
    try:
        data = json.loads(output)
        keep = {
            "data_state", "data_activity", "network_operator_name",
            "network_type", "phone_type", "sim_country_iso",
            "sim_operator_name", "sim_state",
        }
        lines = []
        for k, v in data.items():
            if k in keep:
                lines.append(f"{k}: {v}")
        return "\n".join(lines) or output
    except (json.JSONDecodeError, ValueError):
        return output


@registry.register(
    "dial",
    "Place a phone call. Requires user approval.",
    {"number": "string"},
)
def dial(number=None):
    if not number:
        return "ERROR: number is required"
    cmd = f"termux-telephony-call {shlex.quote(str(number))}"
    return _approval(cmd)


# ── Camera (minimal) ─────────────────────────────────────────────────────────


@registry.register(
    "camera_photo",
    "Take a photo and save it to path. id=0 (back) or 1 (front). Requires approval.",
    {"path": "string", "id": "integer?"},
)
def camera_photo(path=None, id=0):
    if not path:
        return "ERROR: path is required"
    try:
        cam_id = int(id)
    except (TypeError, ValueError):
        cam_id = 0
    cmd = f"termux-camera-photo -c {cam_id} {shlex.quote(str(path))}"
    return _approval(cmd)
