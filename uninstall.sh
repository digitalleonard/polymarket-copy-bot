#!/bin/bash
# ============================================================
#  Polymarket Copy Bot — Uninstaller
#  Usage: bash uninstall.sh
# ============================================================

echo "⚠️  This will stop and remove the copy trading bot and dashboard."
read -p "Are you sure? (y/N) " confirm
[[ "$confirm" != "y" && "$confirm" != "Y" ]] && echo "Cancelled." && exit 0

echo "Stopping services..."
launchctl unload ~/Library/LaunchAgents/fi.bullpen.bot2.plist 2>/dev/null && echo "✅ Bot stopped"
launchctl unload ~/Library/LaunchAgents/fi.bullpen.dashboard.plist 2>/dev/null && echo "✅ Dashboard stopped"
launchctl unload ~/Library/LaunchAgents/fi.bullpen.rotate.plist 2>/dev/null && echo "✅ Auto-rotate stopped"

echo "Removing LaunchAgent plists..."
rm -f ~/Library/LaunchAgents/fi.bullpen.bot2.plist
rm -f ~/Library/LaunchAgents/fi.bullpen.dashboard.plist
rm -f ~/Library/LaunchAgents/fi.bullpen.rotate.plist

echo "Removing symlink..."
rm -f ~/polymarket-bot

echo ""
echo "✅ Uninstall complete."
echo "   Your trades.json data is still in this folder."
echo "   To cancel Bullpen copy subscriptions: bullpen tracker copy list"
