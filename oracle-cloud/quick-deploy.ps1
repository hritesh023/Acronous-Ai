# ─────────────────────────────────────────────────────────────
# Quick Deploy - Run this after getting your VM's Public IP
# ─────────────────────────────────────────────────────────────
param(
    [Parameter(Mandatory=$true)]
    [string]$IP
)

$KEY = "$env:USERPROFILE\.ssh\oracle_acronous"
$USER = "ubuntu"
$REMOTE = "$USER@$IP"

Write-Host "`nDeploying Acronous AI to $IP...`n" -ForegroundColor Cyan

# Test connection
Write-Host "Testing SSH..." -ForegroundColor Yellow
ssh -i $KEY -o ConnectTimeout=10 $REMOTE "echo 'Connected!'" 2>$null
if ($LASTEXITCODE -ne 0) {
    $USER = "opc"
    $REMOTE = "$USER@$IP"
    ssh -i $KEY -o ConnectTimeout=10 $REMOTE "echo 'Connected!'" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Cannot connect. Check IP and SSH key." -ForegroundColor Red
        exit 1
    }
}

# Upload project
Write-Host "Uploading files..." -ForegroundColor Yellow
$root = "C:\Users\Hritesh\Hritesh-apps\Acronous Ai"
$deploy = "$root\oracle-cloud"

scp -i $KEY -r "$deploy" "${REMOTE}:/home/$USER/" 2>$null
scp -i $KEY -r "$root\image-service" "${REMOTE}:/home/$USER/" 2>$null
scp -i $KEY "$root\pubspec.yaml" "${REMOTE}:/home/$USER/" 2>$null
scp -i $KEY "$root\pubspec.lock" "${REMOTE}:/home/$USER/" 2>$null
scp -i $KEY -r "$root\lib" "${REMOTE}:/home/$USER/" 2>$null
scp -i $KEY -r "$root\web" "${REMOTE}:/home/$USER/" 2>$null

# Setup and deploy
Write-Host "Installing Docker + Flutter on VM..." -ForegroundColor Yellow
ssh -i $KEY $REMOTE "bash -c '
set -e
export DEBIAN_FRONTEND=noninteractive

# Docker
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker \$USER
fi
sudo apt-get update -y && sudo apt-get install -y docker-compose-plugin

# Flutter
if ! command -v flutter &>/dev/null; then
    sudo apt-get install -y git curl unzip xz-utils zip libglu1-mesa
    git clone https://github.com/flutter/flutter.git -b stable --depth 1 /opt/flutter 2>/dev/null || true
    echo \"export PATH=/opt/flutter/bin:\\\$PATH\" >> ~/.bashrc
fi
'"

Write-Host "Building Flutter web..." -ForegroundColor Yellow
ssh -i $KEY $REMOTE "bash -c '
export PATH=/opt/flutter/bin:\$PATH
cd /home/$USER
flutter pub get
flutter build web --release --dart-define=\"API_BASE_URL=http://\$(curl -s ifconfig.me)\"
mkdir -p oracle-cloud/web-build
cp -r build/web/* oracle-cloud/web-build/
'"

Write-Host "Building Docker images..." -ForegroundColor Yellow
ssh -i $KEY $REMOTE "bash -c '
cd /home/$USER/oracle-cloud
if [ ! -d image-service ]; then cp -r /home/$USER/image-service .; fi
docker compose build
docker compose up -d
sleep 5
docker compose ps
'"

Write-Host "`nDone!" -ForegroundColor Green
Write-Host "Open: http://$IP" -ForegroundColor Cyan
Write-Host "SSH:  ssh -i $KEY $REMOTE" -ForegroundColor Cyan
