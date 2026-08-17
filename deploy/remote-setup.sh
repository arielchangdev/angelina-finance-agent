#!/usr/bin/env bash
set -euo pipefail

echo "=== Angelina AI Financial Expert Agent - Remote Setup ==="
echo "Running on: $(hostname) as $(whoami)"

APP_DIR="/opt/angelina"
VENV_DIR="$APP_DIR/venv"
LOG_DIR="/var/log/angelina"

# Step 1: Create directories
echo "[1/7] Creating directories..."
sudo mkdir -p "$APP_DIR"
sudo mkdir -p "$LOG_DIR"
sudo mkdir -p "$APP_DIR/data/vector_store"
sudo mkdir -p "$APP_DIR/data/notebooklm"
sudo chown -R $(whoami):$(whoami) "$APP_DIR"
sudo chown -R $(whoami):$(whoami) "$LOG_DIR"

# Step 2: Verify application files
echo "[2/7] Verifying application files..."
ls -la "$APP_DIR/app/" 2>/dev/null || { echo "ERROR: app/ not found in $APP_DIR"; exit 1; }

# Step 3: Create Python virtual environment
echo "[3/7] Creating Python virtual environment..."
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

# Step 4: Install dependencies
echo "[4/7] Installing Python dependencies..."
pip install --upgrade pip
pip install -r "$APP_DIR/requirements.txt"

# Step 5: Set up environment file
echo "[5/7] Setting up environment variables..."
if [ -f "$APP_DIR/deploy/.env.production" ]; then
    cp "$APP_DIR/deploy/.env.production" "$APP_DIR/.env"
    echo "  .env file configured."
fi

# Step 6: Install systemd service
echo "[6/7] Installing systemd service..."
sudo cp "$APP_DIR/deploy/angelina.service" /etc/systemd/system/angelina.service
sudo systemctl daemon-reload
sudo systemctl enable angelina

# Step 7: Start the service
echo "[7/7] Starting Angelina service..."
sudo systemctl start angelina
sleep 3

echo ""
echo "=== Deployment Complete ==="
sudo systemctl status angelina --no-pager || true
echo ""
echo "Testing health endpoint..."
curl -s http://localhost:8080/health || echo "  (Service may still be starting...)"
echo ""
echo "Access Angelina at: http://$(hostname -I | awk '{print $1}'):8080/"
