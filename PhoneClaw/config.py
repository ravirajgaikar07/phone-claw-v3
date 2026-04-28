"""PhoneClaw configuration — loaded from environment / .env file."""

import os
from pathlib import Path

# Load .env file if present (python-dotenv)
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    pass  # dotenv is optional; rely on real env vars

# ---------------------------------------------------------------------------
# LLM Provider (NVIDIA NIM)
# ---------------------------------------------------------------------------
NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "")
NVIDIA_API_URL = os.environ.get(
    "NVIDIA_API_URL", "https://integrate.api.nvidia.com/v1/chat/completions"
)
NVIDIA_MODEL = os.environ.get("NVIDIA_MODEL", "moonshotai/kimi-k2-thinking")

# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ALLOWED_USER_ID = int(os.environ.get("ALLOWED_USER_ID", "0"))

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_PATH = os.environ.get("BASE_PATH", "/storage/emulated/0/Download")

# ---------------------------------------------------------------------------
# FastAPI server
# ---------------------------------------------------------------------------
API_HOST = os.environ.get("API_HOST", "0.0.0.0")
API_PORT = int(os.environ.get("API_PORT", "8001"))

# ---------------------------------------------------------------------------
# Agent behaviour
# ---------------------------------------------------------------------------
MAX_AGENT_STEPS = int(os.environ.get("MAX_AGENT_STEPS", "5"))
LLM_TEMPERATURE = float(os.environ.get("LLM_TEMPERATURE", "0.2"))
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "2048"))
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "120"))

# ---------------------------------------------------------------------------
# Context compaction
# ---------------------------------------------------------------------------
COMPACTION_THRESHOLD_TOKENS = int(os.environ.get("COMPACTION_THRESHOLD_TOKENS", "6000"))
POST_COMPACTION_KEEP_MESSAGES = int(os.environ.get("POST_COMPACTION_KEEP_MESSAGES", "4"))

# ---------------------------------------------------------------------------
# Memory notes
# ---------------------------------------------------------------------------
MEMORY_NOTES_DIR = os.environ.get(
    "MEMORY_NOTES_DIR", str(Path(__file__).parent / "memory" / "notes")
)

# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
SCHEDULER_CHECK_INTERVAL = int(os.environ.get("SCHEDULER_CHECK_INTERVAL", "60"))

# ---------------------------------------------------------------------------
# Tool approval
# ---------------------------------------------------------------------------
APPROVAL_TIMEOUT = int(os.environ.get("APPROVAL_TIMEOUT", "300"))  # 5 minutes

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DB_PATH = os.environ.get("DB_PATH", "phoneclaw.db")

# ---------------------------------------------------------------------------
# Soul / persona file
# ---------------------------------------------------------------------------
SOUL_PATH = os.environ.get("SOUL_PATH", str(Path(__file__).parent / "soul.md"))

# ---------------------------------------------------------------------------
# Code execution
# ---------------------------------------------------------------------------
CODE_EXEC_TIMEOUT = int(os.environ.get("CODE_EXEC_TIMEOUT", "30"))

# ---------------------------------------------------------------------------
# Dreaming
# ---------------------------------------------------------------------------
DREAM_INTERVAL_HOURS = int(os.environ.get("DREAM_INTERVAL_HOURS", "6"))
DREAM_MIN_SCORE = float(os.environ.get("DREAM_MIN_SCORE", "0.3"))