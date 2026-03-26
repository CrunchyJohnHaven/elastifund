#!/bin/bash
# Expose local JJ Console backend via Cloudflare Tunnel (no account needed)
# The tunnel URL will be printed -- paste it into Replit's VITE_API_URL secret
set -e

PORT=${1:-8000}

echo "=== JJ Console Tunnel ==="
echo ""
echo "Starting Cloudflare Tunnel to localhost:$PORT..."
echo "The tunnel URL will appear below. Copy it and set as VITE_API_URL in Replit."
echo ""

# Check if cloudflared is installed
if command -v cloudflared &> /dev/null; then
    cloudflared tunnel --url http://localhost:$PORT
elif command -v ngrok &> /dev/null; then
    echo "cloudflared not found, using ngrok instead..."
    ngrok http $PORT
else
    echo "Neither cloudflared nor ngrok found."
    echo ""
    echo "Install one:"
    echo "  brew install cloudflared    (recommended, free, no signup)"
    echo "  brew install ngrok          (free tier, requires signup)"
    echo ""
    echo "Or use SSH tunnel to a server you control:"
    echo "  ssh -R 80:localhost:$PORT serveo.net"
    exit 1
fi
