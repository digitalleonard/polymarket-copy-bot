#!/bin/bash
# ============================================================
#  Polymarket Copy Bot — One-Command Installer
#  Usage: bash setup.sh
# ============================================================

set -e

BOLD="\033[1m"
GREEN="\033[0;32m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
RESET="\033[0m"

log()   { echo -e "${BOLD}▶ $1${RESET}"; }
ok()    { echo -e "${GREEN}✅ $1${RESET}"; }
warn()  { echo -e "${YELLOW}⚠️  $1${RESET}"; }
fail()  { echo -e "${RED}❌ $1${RESET}"; exit 1; }

echo ""
echo -e "${BOLD}============================================${RESET}"
echo -e "${BOLD}   Polymarket Copy Bot — Setup${RESET}"
echo -e "${BOLD}============================================${RESET}"
echo ""

# ── Detect install directory ──────────────────────────────────
INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYMLINK="$HOME/polymarket-bot"
BOT_LOG="/tmp/bot2.log"
DASHBOARD_LOG="/tmp/dashboard.log"
BOT_PLIST="$HOME/Library/LaunchAgents/fi.bullpen.bot2.plist"
DASHBOARD_PLIST="$HOME/Library/LaunchAgents/fi.bullpen.dashboard.plist"

log "Install directory: $INSTALL_DIR"

# ── Check macOS ───────────────────────────────────────────────
if [[ "$(uname)" != "Darwin" ]]; then
  fail "This setup script is for macOS only."
fi

# ── Check Python 3 ───────────────────────────────────────────
log "Checking Python 3..."
PYTHON=""
for p in /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
  if command -v "$p" &>/dev/null; then PYTHON="$p"; break; fi
done
[[ -z "$PYTHON" ]] && fail "Python 3 not found. Install it with: brew install python3"
ok "Python 3 found at: $PYTHON"

# ── Install Flask ─────────────────────────────────────────────
log "Installing Python dependencies..."
"$PYTHON" -m pip install flask --quiet --break-system-packages 2>/dev/null || \
"$PYTHON" -m pip install flask --quiet 2>/dev/null || \
warn "Could not auto-install Flask. Run: pip3 install flask"
ok "Flask ready"

# ── Check Bullpen CLI ─────────────────────────────────────────
log "Checking Bullpen CLI..."
if ! command -v bullpen &>/dev/null; then
  echo ""
  warn "Bullpen CLI not found. Install it first:"
  echo "   brew install BullpenFi/tap/bullpen"
  echo "   bullpen login"
  echo "   bullpen skill install"
  echo ""
  fail "Re-run setup.sh after installing Bullpen."
fi
BULLPEN_PATH="$(which bullpen)"
ok "Bullpen found at: $BULLPEN_PATH"

# ── Create symlink (avoids spaces-in-path issues) ────────────
log "Creating symlink ~/polymarket-bot → $INSTALL_DIR"
if [[ -L "$SYMLINK" ]]; then
  rm "$SYMLINK"
fi
ln -s "$INSTALL_DIR" "$SYMLINK"
ok "Symlink created"

# ── Write LaunchAgent plists ──────────────────────────────────
PYTHON_BIN="$PYTHON"
# Prefer homebrew python for LaunchAgent
[[ -f "/opt/homebrew/bin/python3" ]] && PYTHON_BIN="/opt/homebrew/bin/python3"

log "Writing LaunchAgent plists..."

cat > "$BOT_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>fi.bullpen.bot2</string>

  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON_BIN}</string>
    <string>${SYMLINK}/bot.py</string>
  </array>

  <key>WorkingDirectory</key>
  <string>${SYMLINK}</string>

  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>HOME</key>
    <string>${HOME}</string>
  </dict>

  <key>RunAtLoad</key>
  <true/>

  <key>KeepAlive</key>
  <true/>

  <key>ThrottleInterval</key>
  <integer>10</integer>

  <key>StandardOutPath</key>
  <string>${BOT_LOG}</string>

  <key>StandardErrorPath</key>
  <string>${BOT_LOG}</string>
</dict>
</plist>
PLIST

cat > "$DASHBOARD_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>fi.bullpen.dashboard</string>

  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON_BIN}</string>
    <string>${SYMLINK}/dashboard.py</string>
  </array>

  <key>WorkingDirectory</key>
  <string>${SYMLINK}</string>

  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>HOME</key>
    <string>${HOME}</string>
  </dict>

  <key>RunAtLoad</key>
  <true/>

  <key>KeepAlive</key>
  <true/>

  <key>ThrottleInterval</key>
  <integer>10</integer>

  <key>StandardOutPath</key>
  <string>${DASHBOARD_LOG}</string>

  <key>StandardErrorPath</key>
  <string>${DASHBOARD_LOG}</string>
</dict>
</plist>
PLIST

ok "LaunchAgent plists written"

# ── Load LaunchAgents ─────────────────────────────────────────
log "Loading LaunchAgents (bot + dashboard)..."
launchctl unload "$BOT_PLIST" 2>/dev/null || true
launchctl unload "$DASHBOARD_PLIST" 2>/dev/null || true
sleep 1
launchctl load "$BOT_PLIST"
launchctl load "$DASHBOARD_PLIST"
sleep 3

BOT_PID=$(launchctl list fi.bullpen.bot2 2>/dev/null | grep '"PID"' | awk '{print $3}' | tr -d ';')
DASH_PID=$(launchctl list fi.bullpen.dashboard 2>/dev/null | grep '"PID"' | awk '{print $3}' | tr -d ';')

[[ -n "$BOT_PID" ]]  && ok "Bot running (PID $BOT_PID)"  || warn "Bot did not start — check: tail -20 $BOT_LOG"
[[ -n "$DASH_PID" ]] && ok "Dashboard running (PID $DASH_PID)" || warn "Dashboard did not start — check: tail -20 $DASHBOARD_LOG"

# ── Bullpen login & skill install ────────────────────────────
echo ""
log "Setting up Bullpen authentication..."
bullpen login

log "Installing Bullpen AI skills..."
bullpen skill install

# ── Done ──────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}============================================${RESET}"
echo -e "${GREEN}${BOLD}   ✅ Setup complete!${RESET}"
echo -e "${BOLD}============================================${RESET}"
echo ""
echo "  Dashboard → http://localhost:5050"
echo "  Bot log   → tail -f $BOT_LOG"
echo ""
echo "  Next steps:"
echo "  1. Open http://localhost:5050 in your browser"
echo "  2. The bot is copying 10 top Polymarket traders at \$1/trade"
echo "  3. Deposit USDC.e to your Polymarket wallet to start copying"
echo "     (run 'bullpen portfolio balances' to see your wallet address)"
echo ""
echo "  To check status anytime, open this folder in Claude Code."
echo ""
