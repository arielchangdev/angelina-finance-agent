#!/usr/bin/env bash
set -euo pipefail

# Angelina AI Financial Expert Agent - Installation Script
# This script installs the systemd service and enables it for auto-start.

echo "=== Angelina Service Installer ==="

# Create log directory
echo "Creating /var/log/angelina/ directory..."
mkdir -p /var/log/angelina/
chmod 755 /var/log/angelina/

# Copy systemd unit file
echo "Installing systemd service unit..."
cp "$(dirname "$0")/angelina.service" /etc/systemd/system/angelina.service
chmod 644 /etc/systemd/system/angelina.service

# Reload systemd daemon to pick up new unit file
echo "Reloading systemd daemon..."
systemctl daemon-reload

# Enable and start the service
echo "Enabling and starting angelina service..."
systemctl enable --now angelina

echo "=== Installation complete ==="
echo "Service status:"
systemctl status angelina --no-pager || true
