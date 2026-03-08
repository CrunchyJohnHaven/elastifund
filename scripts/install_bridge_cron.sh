#!/bin/bash
# INSTALL_BRIDGE_CRON.SH — Sets up automatic bidirectional sync on your Mac
# Run this ONCE on your Mac. It installs a launchd agent that runs bridge.sh
# every 30 minutes, keeping VPS data fresh for Cowork scheduled tasks and
# pushing code improvements back to the VPS.
#
# Usage: ./scripts/install_bridge_cron.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PLIST_NAME="com.elastifund.bridge"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"
LOG_DIR="$HOME/Library/Logs/Elastifund"
RUNNER_DIR="$HOME/.elastifund"
RUNNER_PATH="$RUNNER_DIR/bridge.sh"
RUNNER_KEY_PATH="$RUNNER_DIR/lightsail.pem"

mkdir -p "$LOG_DIR"
mkdir -p "$RUNNER_DIR"
cp "$SCRIPT_DIR/bridge.sh" "$RUNNER_PATH"
chmod +x "$RUNNER_PATH"

KEY_SOURCE=""
for candidate in \
    "$PROJECT_DIR/LightsailDefaultKey-eu-west-1.pem" \
    "$HOME/Downloads/LightsailDefaultKey-eu-west-1.pem" \
    "$HOME/.ssh/lightsail.pem" \
    "$HOME/.ssh/LightsailDefaultKey-eu-west-1.pem" \
    "$HOME/Desktop/LightsailDefaultKey-eu-west-1.pem"; do
    if [ -f "$candidate" ]; then
        KEY_SOURCE="$candidate"
        break
    fi
done

if [ -n "$KEY_SOURCE" ]; then
    cp "$KEY_SOURCE" "$RUNNER_KEY_PATH"
    chmod 600 "$RUNNER_KEY_PATH"
fi

echo "Installing Elastifund bridge sync..."
echo "  Project: $PROJECT_DIR"
echo "  Sync interval: 30 minutes"
echo "  Logs: $LOG_DIR/bridge.log"
echo "  Runner: $RUNNER_PATH"
if [ -n "$KEY_SOURCE" ]; then
    echo "  Key: $RUNNER_KEY_PATH"
else
    echo "  Key: NOT FOUND (bridge will rely on runtime discovery)"
fi

cat > "$PLIST_PATH" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_NAME}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${RUNNER_PATH}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${RUNNER_DIR}</string>
    <key>StartInterval</key>
    <integer>1800</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${LOG_DIR}/bridge.log</string>
    <key>StandardErrorPath</key>
    <string>${LOG_DIR}/bridge_error.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
        <key>ELASTIFUND_PROJECT_DIR</key>
        <string>${PROJECT_DIR}</string>
        <key>ELASTIFUND_BRIDGE_KEY</key>
        <string>${RUNNER_KEY_PATH}</string>
    </dict>
</dict>
</plist>
PLIST

# Load it
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo ""
echo "========================================="
echo "  Bridge sync installed and running"
echo "========================================="
echo ""
echo "  Syncs every 30 minutes + on boot"
echo "  VPS → Mac: data, logs, state"
echo "  Mac → VPS: code, configs, improvements"
echo ""
echo "  View logs:    tail -f ~/Library/Logs/Elastifund/bridge.log"
echo "  Manual sync:  ./scripts/bridge.sh"
echo "  Stop:         launchctl unload $PLIST_PATH"
echo "  Uninstall:    rm $PLIST_PATH"
echo "========================================="
