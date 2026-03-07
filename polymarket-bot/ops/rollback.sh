#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/polymarket-bot}"

echo "=== Rolling Back Polymarket Bot ==="

cd "$APP_DIR"

# Stop current
docker compose down

# If we have a backup tag
PREVIOUS_TAG="${1:-}"
if [ -n "$PREVIOUS_TAG" ]; then
    echo "Rolling back to tag: $PREVIOUS_TAG"
    # Update compose to use previous tag
    sed -i "s/image:.*bot.*/image: polymarket-bot:$PREVIOUS_TAG/" docker-compose.yml
    docker compose up -d
else
    echo "No tag specified. Restarting with current images..."
    docker compose up -d
fi

sleep 5
if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
    echo "Rollback SUCCESSFUL - API healthy"
else
    echo "WARNING: Health check failed after rollback"
    docker compose logs --tail=30
fi

echo ""
echo "Manual rollback steps if needed:"
echo "  1. docker compose down"
echo "  2. git checkout <previous-commit>"
echo "  3. docker compose build && docker compose up -d"
