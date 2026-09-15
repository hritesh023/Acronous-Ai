# ─────────────────────────────────────────────────────────────
# Acronous AI — Automated Contabo VPS Deployment
# Run this from your Windows machine
# ─────────────────────────────────────────────────────────────
param(
    [string]$PublicIP = "167.86.104.155",

    [string]$SSHKey = "$env:USERPROFILE\.ssh\contabo_key",
    [string]$SSHUser = "root"
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Acronous AI - Contabo VPS Deployer"  -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Target: $SSHUser@$PublicIP" -ForegroundColor Yellow
Write-Host "SSH Key: $SSHKey" -ForegroundColor Yellow
Write-Host ""

# Contabo default home: root -> /root, others -> /home/<user>
$RemoteHome = if ($SSHUser -eq "root") { "/root" } else { "/home/$SSHUser" }

# ── 1. Test SSH connection (Contabo default user is root) ──
Write-Host "[1/6] Testing SSH connection..." -ForegroundColor Green
$testConn = ssh -i $SSHKey -o ConnectTimeout=10 -o StrictHostKeyChecking=no "$SSHUser@$PublicIP" "echo OK" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  SSH connection failed as $SSHUser." -ForegroundColor Red
    Write-Host "  Try manually: ssh -i $SSHKey $SSHUser@$PublicIP" -ForegroundColor Yellow
    Write-Host "  Contabo panel: VNC 5.189.136.10:63080 if locked out." -ForegroundColor Yellow
    exit 1
}
Write-Host "  Connected as $SSHUser" -ForegroundColor Green

# ── 2. Upload project files ──
Write-Host ""
Write-Host "[2/6] Uploading project to VM (this may take 2-5 minutes)..." -ForegroundColor Green

$projectRoot = Split-Path -Parent $PSScriptRoot
$contaboDir = $PSScriptRoot

# Create temp upload directory on VM
ssh -i $SSHKey "$SSHUser@$PublicIP" "mkdir -p $RemoteHome/acronous-deploy"

# Upload contabo-vps directory
Write-Host "  Uploading contabo-vps/..."
scp -i $SSHKey -r "$contaboDir" "$SSHUser@${PublicIP}:$RemoteHome/acronous-deploy/"

# Upload image-service directory
Write-Host "  Uploading image-service/..."
scp -i $SSHKey -r "$projectRoot\image-service" "$SSHUser@${PublicIP}:$RemoteHome/acronous-deploy/"

# Upload Flutter project (needed for building web)
Write-Host "  Uploading Flutter project files..."
scp -i $SSHKey "$projectRoot\pubspec.yaml" "$SSHUser@${PublicIP}:$RemoteHome/acronous-deploy/" 2>$null
scp -i $SSHKey "$projectRoot\pubspec.lock" "$SSHUser@${PublicIP}:$RemoteHome/acronous-deploy/" 2>$null

# Upload lib/ and web/ directories
scp -i $SSHKey -r "$projectRoot\lib" "$SSHUser@${PublicIP}:$RemoteHome/acronous-deploy/" 2>$null
scp -i $SSHKey -r "$projectRoot\web" "$SSHUser@${PublicIP}:$RemoteHome/acronous-deploy/" 2>$null

Write-Host "  Upload complete!" -ForegroundColor Green

# ── 3. Setup VM ──
Write-Host ""
Write-Host "[3/6] Setting up VM (installing Docker, Flutter, etc.)..." -ForegroundColor Green

$setupScript = @"
#!/bin/bash
set -e

echo "=== Installing Docker ==="
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker `$USER
fi

echo "=== Installing Docker Compose ==="
if ! docker compose version &> /dev/null; then
    sudo apt-get update -y
    sudo apt-get install -y docker-compose-plugin
fi

echo "=== Installing Flutter ==="
if ! command -v flutter &> /dev/null; then
    sudo apt-get install -y git curl unzip xz-utils zip libglu1-mesa
    cd /tmp
    git clone https://github.com/flutter/flutter.git -b stable --depth 1
    sudo mv flutter /opt/flutter
    echo 'export PATH="/opt/flutter/bin:`$PATH"' >> ~/.bashrc
    export PATH="/opt/flutter/bin:`$PATH"
    flutter precache --web
    flutter config --enable-web
fi
echo "=== Setup complete ==="
"@

$setupScript | Out-File -FilePath "$env:TEMP\vm-setup.sh" -Encoding utf8 -NoNewline
scp -i $SSHKey "$env:TEMP\vm-setup.sh" "$SSHUser@${PublicIP}:$RemoteHome/vm-setup.sh"
ssh -i $SSHKey "$SSHUser@$PublicIP" "chmod +x $RemoteHome/vm-setup.sh && bash $RemoteHome/vm-setup.sh"

# ── 4. Build Flutter web ──
Write-Host ""
Write-Host "[4/6] Building Flutter web app..." -ForegroundColor Green

$buildScript = @"
#!/bin/bash
set -e
export PATH="/opt/flutter/bin:`$PATH"

cd $RemoteHome/acronous-deploy
PUBLIC_IP=`$(curl -s ifconfig.me)

echo "Flutter: pub get..."
flutter pub get

echo "Flutter: build web..."
flutter build web --release --dart-define="API_BASE_URL=http://`$PUBLIC_IP"

mkdir -p contabo-vps/web-build
cp -r build/web/* contabo-vps/web-build/

echo "Flutter web build complete!"
"@

$buildScript | Out-File -FilePath "$env:TEMP\flutter-build.sh" -Encoding utf8 -NoNewline
scp -i $SSHKey "$env:TEMP\flutter-build.sh" "$SSHUser@${PublicIP}:$RemoteHome/flutter-build.sh"
ssh -i $SSHKey "$SSHUser@$PublicIP" "chmod +x $RemoteHome/flutter-build.sh && bash $RemoteHome/flutter-build.sh"

# ── 5. Build and start Docker services ──
Write-Host ""
Write-Host "[5/6] Building Docker images and starting services..." -ForegroundColor Green

$deployScript = @"
#!/bin/bash
set -e

cd $RemoteHome/acronous-deploy/contabo-vps

# Make sure image-service is in the right place
if [ ! -d "image-service" ]; then
    cp -r $RemoteHome/acronous-deploy/image-service . 2>/dev/null || true
fi

echo "Building Docker images..."
docker compose build

echo "Starting services..."
docker compose up -d

echo "Waiting for services to start..."
sleep 10

# Check if running
docker compose ps
"@

$deployScript | Out-File -FilePath "$env:TEMP\docker-deploy.sh" -Encoding utf8 -NoNewline
scp -i $SSHKey "$env:TEMP\docker-deploy.sh" "$SSHUser@${PublicIP}:/home/$SSHUser/docker-deploy.sh"
ssh -i $SSHKey "$SSHUser@$PublicIP" "chmod +x /home/$SSHUser/docker-deploy.sh && bash /home/$SSHUser/docker-deploy.sh"

# ── 6. Verify ──
Write-Host ""
Write-Host "[6/6] Verifying deployment..." -ForegroundColor Green

$verify = ssh -i $SSHKey "$SSHUser@$PublicIP" "curl -s http://localhost/health" 2>&1

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Deployment Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Web UI:  http://$PublicIP" -ForegroundColor Yellow
Write-Host "  API:     http://$PublicIP/v1/chat" -ForegroundColor Yellow
Write-Host "  Health:  http://$PublicIP/health" -ForegroundColor Yellow
Write-Host ""
Write-Host "  SSH:     ssh -i $SSHKey $SSHUser@$PublicIP" -ForegroundColor Yellow
Write-Host "  Logs:    ssh -i $SSHKey $SSHUser@$PublicIP 'cd $RemoteHome/acronous-deploy/contabo-vps && docker compose logs -f'" -ForegroundColor Yellow
Write-Host "  Stop:    ssh -i $SSHKey $SSHUser@$PublicIP 'cd $RemoteHome/acronous-deploy/contabo-vps && docker compose down'" -ForegroundColor Yellow
Write-Host ""
Write-Host "Open http://$PublicIP in your browser!" -ForegroundColor Green
Write-Host ""
