#!/data/data/com.termux/files/usr/bin/env bash
# PhoneClaw — one-shot installer for Termux on Android.
#
# Usage (in a fresh Termux):
#   curl -fsSL https://raw.githubusercontent.com/<you>/PhoneClaw/main/install.sh | bash
#   # or, after cloning manually:
#   bash install.sh
#
# What it does:
#   1. Installs system packages: python, git, curl, termux-api
#   2. Sets up storage access (termux-setup-storage)
#   3. Clones this repo into ~/PhoneClaw if not already present
#   4. Installs Python dependencies into ~/.local
#   5. Writes a starter .env if one doesn't exist
#   6. Prints the final commands to start the bot
#
# Idempotent — safe to re-run.

set -euo pipefail

REPO_URL="${PHONECLAW_REPO:-https://github.com/yourname/PhoneClaw.git}"
TARGET_DIR="${PHONECLAW_DIR:-$HOME/PhoneClaw}"

say() { printf '\n\033[1;36m▶ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m! %s\033[0m\n' "$*" >&2; }

if [ ! -d "/data/data/com.termux" ]; then
  warn "This installer is meant for Termux on Android. Continuing anyway."
fi

say "Refreshing Termux package index"
pkg update -y >/dev/null
pkg upgrade -y >/dev/null || true

say "Installing system packages: python git curl termux-api"
pkg install -y python git curl termux-api

if command -v termux-setup-storage >/dev/null 2>&1; then
  say "Requesting storage access (allow the dialog if it pops up)"
  termux-setup-storage || warn "Storage permission not granted — file tools may fail"
fi

if [ ! -d "$TARGET_DIR/.git" ] && [ ! -f "$TARGET_DIR/main.py" ]; then
  say "Cloning $REPO_URL → $TARGET_DIR"
  git clone --depth=1 "$REPO_URL" "$TARGET_DIR"
else
  say "PhoneClaw already at $TARGET_DIR — pulling latest"
  (cd "$TARGET_DIR" && git pull --ff-only) || warn "git pull skipped"
fi

cd "$TARGET_DIR"

if [ -f requirements.txt ]; then
  say "Installing Python dependencies"
  pip install --user -r requirements.txt
else
  warn "requirements.txt not found — skipping pip install"
fi

# ── MCP servers — bundled, no external SDK needed ──
# PhoneClaw ships its own MCP-compatible servers in mcp_servers/ that use
# only stdlib + requests.  No mcp SDK, no pydantic 2, no Rust toolchain.
# The official reference servers (mcp-server-fetch etc.) won't install on
# Termux because pydantic>=2 needs a Rust compiler.
if [ ! -f mcp_servers.json ]; then
  say "Writing default mcp_servers.json (uses bundled fetch server)"
  cat > mcp_servers.json <<'MCPEOF'
{
  "servers": {
    "fetch": {
      "transport": "stdio",
      "command": "python",
      "args": ["-m", "mcp_servers.fetch_server"]
    }
  }
}
MCPEOF
else
  say "mcp_servers.json exists — leaving it untouched"
fi

if [ ! -f .env ]; then
  say "Writing starter .env (edit before first run!)"
  cat > .env <<'EOF'
# === PhoneClaw configuration ===
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
ALLOWED_USER_ID=your_telegram_numeric_id_here
NIM_API_KEY=your_nvidia_nim_key_here
EOF
else
  say ".env exists — leaving it untouched"
fi

say "Done."
cat <<EOF

────────────────────────────────────────────────────────
Next steps:

  1. Edit ~/PhoneClaw/.env and fill in:
       TELEGRAM_BOT_TOKEN, ALLOWED_USER_ID, NIM_API_KEY

  2. Start the bot:
       cd $TARGET_DIR
       python run.py

  3. (Optional) Run as a service via supervisord:
       pkg install supervisor
       supervisord -c $TARGET_DIR/supervisord.conf

  4. From Telegram, install community skills with:
       /skill install https://github.com/<user>/<skill-repo>
────────────────────────────────────────────────────────
EOF
