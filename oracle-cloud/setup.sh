#!/bin/bash
# ─────────────────────────────────────────────────────────────
# Acronous AI — Oracle Cloud Deployment Script
# Run this ON the Oracle Cloud VM after SSH-ing in
# ─────────────────────────────────────────────────────────────
set -e

echo "═══════════════════════════════════════════════════"
echo "  Acronous AI — Oracle Cloud Setup"
echo "═══════════════════════════════════════════════════"

# ── 1. System updates ──
echo ""
echo "[1/8] Updating system..."
sudo apt-get update -y
sudo apt-get upgrade -y

# ── 2. Install Docker ──
echo ""
echo "[2/8] Installing Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker $USER
    echo "Docker installed. You may need to log out and back in for group changes."
else
    echo "Docker already installed."
fi

# ── 3. Install Docker Compose ──
echo ""
echo "[3/8] Installing Docker Compose..."
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    sudo apt-get install -y docker-compose-plugin
else
    echo "Docker Compose already installed."
fi

# ── 4. Install Flutter (for building web) ──
echo ""
echo "[4/8] Installing Flutter..."
if ! command -v flutter &> /dev/null; then
    sudo apt-get install -y curl git unzip xz-utils zip libglu1-mesa
    cd /tmp
    git clone https://github.com/flutter/flutter.git -b stable --depth 1
    sudo mv flutter /opt/flutter
    echo 'export PATH="/opt/flutter/bin:$PATH"' >> ~/.bashrc
    export PATH="/opt/flutter/bin:$PATH"
    flutter precache --web
    flutter config --enable-web
else
    echo "Flutter already installed."
fi

# ── 5. Ensure image-service is in oracle-cloud ──
echo ""
echo "[5/8] Checking project structure..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

if [ ! -d "oracle-cloud/image-service" ]; then
    if [ -d "image-service" ]; then
        echo "Copying image-service into oracle-cloud..."
        cp -r image-service oracle-cloud/image-service
    else
        echo "WARNING: image-service directory not found!"
    fi
fi

# ── 6. Build Flutter web ──
echo ""
echo "[6/8] Building Flutter web..."
export PATH="/opt/flutter/bin:$PATH"

if [ -f "pubspec.yaml" ]; then
    flutter pub get
    flutter build web --release --dart-define="API_BASE_URL=http://$(hostname -I | awk '{print $1}')"
    
    # Copy build to oracle-cloud
    mkdir -p oracle-cloud/web-build
    cp -r build/web/* oracle-cloud/web-build/
    echo "Flutter web build complete!"
else
    echo "pubspec.yaml not found. Skipping Flutter build."
    echo "Make sure to upload the Flutter project files."
fi

# ── 7. Build Docker images ──
echo ""
echo "[7/8] Building Docker images..."
cd "$SCRIPT_DIR"
docker compose build

# ── 8. Start services ──
echo ""
echo "[8/8] Starting services..."
docker compose up -d

# ── Done ──
echo ""
echo "═══════════════════════════════════════════════════"
echo "  Acronous AI is now running!"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  Web UI:    http://$(hostname -I | awk '{print $1}')"
echo "  API:       http://$(hostname -I | awk '{print $1}')/v1/chat"
echo "  Health:    http://$(hostname -I | awk '{print $1}')/health"
echo ""
echo "  Logs:      docker compose logs -f"
echo "  Stop:      docker compose down"
echo "  Restart:   docker compose restart"
echo ""
