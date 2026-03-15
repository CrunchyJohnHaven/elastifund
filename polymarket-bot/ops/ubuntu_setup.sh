#!/usr/bin/env bash
set -euo pipefail

echo "=== Polymarket Bot - Ubuntu VPS Setup ==="
echo "Target: Ubuntu 22.04/24.04 on Hetzner CX23"

# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker $USER
    echo "Docker installed. Log out and back in for group changes."
fi

# Install Docker Compose plugin
if ! docker compose version &>/dev/null; then
    sudo apt install -y docker-compose-plugin
fi

# Install Tailscale for VPN-only dashboard access
if ! command -v tailscale &>/dev/null; then
    curl -fsSL https://tailscale.com/install.sh | sh
    echo "Run 'sudo tailscale up' to connect to your tailnet."
fi

# Security hardening
sudo apt install -y fail2ban ufw unattended-upgrades
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw --force enable
echo "Firewall enabled (SSH only). Dashboard via Tailscale."

# Setup app directory
APP_DIR="/opt/polymarket-bot"
sudo mkdir -p $APP_DIR
sudo chown $USER:$USER $APP_DIR

echo ""
echo "=== Setup Complete ==="
echo "Next steps:"
echo "  1. sudo tailscale up"
echo "  2. cp .env.example $APP_DIR/.env && nano $APP_DIR/.env"
echo "  3. cd $APP_DIR && docker compose up -d"
