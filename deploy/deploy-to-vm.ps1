# Angelina AI Financial Expert Agent - Deploy to RedHat VM
# Usage: .\deploy\deploy-to-vm.ps1
#
# Prerequisites: SSH access to the VM (password: angelina)

$VM_IP = "YOUR_ANGELINA_VM_IP"
$VM_USER = "angelina"
$REMOTE_DIR = "/opt/angelina"
$LOCAL_DIR = $PSScriptRoot | Split-Path -Parent  # workspace root

Write-Host "=== Deploying Angelina to $VM_IP ===" -ForegroundColor Cyan
Write-Host "Local source: $LOCAL_DIR"
Write-Host "Remote target: ${VM_USER}@${VM_IP}:${REMOTE_DIR}"
Write-Host ""

# Step 1: Create remote directory structure
Write-Host "[1/4] Creating remote directories..." -ForegroundColor Yellow
ssh "${VM_USER}@${VM_IP}" "sudo mkdir -p $REMOTE_DIR && sudo chown ${VM_USER}:${VM_USER} $REMOTE_DIR && mkdir -p $REMOTE_DIR/data/vector_store $REMOTE_DIR/data/notebooklm"

# Step 2: Upload application files via SCP
Write-Host "[2/4] Uploading application files..." -ForegroundColor Yellow
# Upload app/ directory
scp -r "$LOCAL_DIR\app" "${VM_USER}@${VM_IP}:${REMOTE_DIR}/"
# Upload static/ directory
scp -r "$LOCAL_DIR\static" "${VM_USER}@${VM_IP}:${REMOTE_DIR}/"
# Upload deploy/ directory
scp -r "$LOCAL_DIR\deploy" "${VM_USER}@${VM_IP}:${REMOTE_DIR}/"
# Upload requirements.txt
scp "$LOCAL_DIR\requirements.txt" "${VM_USER}@${VM_IP}:${REMOTE_DIR}/"

# Step 3: Run remote setup script
Write-Host "[3/4] Running remote setup..." -ForegroundColor Yellow
ssh "${VM_USER}@${VM_IP}" "chmod +x $REMOTE_DIR/deploy/remote-setup.sh && bash $REMOTE_DIR/deploy/remote-setup.sh"

# Step 4: Verify deployment
Write-Host ""
Write-Host "[4/4] Verifying deployment..." -ForegroundColor Yellow
Start-Sleep -Seconds 2
$health = Invoke-RestMethod -Uri "http://${VM_IP}:8080/health" -ErrorAction SilentlyContinue
if ($health.status -eq "ok") {
    Write-Host ""
    Write-Host "=== SUCCESS ===" -ForegroundColor Green
    Write-Host "Angelina is running at: http://${VM_IP}:8080/" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "=== WARNING ===" -ForegroundColor Yellow
    Write-Host "Service may still be starting. Check: ssh ${VM_USER}@${VM_IP} 'sudo systemctl status angelina'"
}
