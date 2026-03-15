#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/polymarket-bot}"
COMPOSE_FILE="$APP_DIR/docker-compose.yml"

echo "=== Deploying Polymarket Bot ==="

# Check prerequisites
if [ ! -f "$APP_DIR/.env" ]; then
    echo "ERROR: $APP_DIR/.env not found. Copy .env.example and configure it."
    exit 1
fi

# Build and deploy
cd "$APP_DIR"
docker compose pull 2>/dev/null || true
docker compose build --no-cache
docker compose down
docker compose up -d

# Wait for health
echo "Waiting for services..."
sleep 10

# Health check
if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
    echo "API: HEALTHY"
    curl -s http://localhost:8000/health | python3 -m json.tool
else
    echo "WARNING: API health check failed"
    docker compose logs --tail=20 api
fi

echo ""
echo "=== Deployment Complete ==="
echo "Dashboard: http://$(tailscale ip -4 2>/dev/null || echo 'localhost'):8000"
echo "Logs: docker compose logs -f"
