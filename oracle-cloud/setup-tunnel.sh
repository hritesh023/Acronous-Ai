# Setup Named Cloudflare Tunnel on Oracle Cloud
# Run this ONCE on the Oracle Cloud server to get a persistent tunnel URL
#
# Prerequisites:
#   - cloudflared installed
#   - Cloudflare account with acronous.com domain
#
# Usage:
#   ssh ubuntu@<oracle-ip>
#   bash setup-tunnel.sh

set -e

echo "=== Setting up Named Cloudflare Tunnel ==="

# 1. Install cloudflared if not present
if ! command -v cloudflared &> /dev/null; then
    echo "[1/5] Installing cloudflared..."
    ARCH=$(uname -m)
    if [ "$ARCH" = "aarch64" ]; then
        curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64 -o /usr/local/bin/cloudflared
    else
        curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared
    fi
    chmod +x /usr/local/bin/cloudflared
    echo "  Installed cloudflared $(cloudflared --version)"
else
    echo "[1/5] cloudflared already installed"
fi

# 2. Login (opens browser — if headless, use token from dashboard)
echo "[2/5] Authenticating with Cloudflare..."
echo "  If running headless, use: cloudflared tunnel token <TOKEN>"
echo "  Or paste the URL in a browser and authorize"
cloudflared tunnel login || {
    echo "  Login failed. For headless servers:"
    echo "  1. Run this on a machine with a browser"
    echo "  2. Copy the cert.pem to /root/.cloudflared/cert.pem"
    echo "  Or use: cloudflared tunnel token acronous-oracle"
    exit 1
}

# 3. Create named tunnel
echo "[3/5] Creating named tunnel 'acronous-oracle'..."
if cloudflared tunnel list | grep -q "acronous-oracle"; then
    echo "  Tunnel 'acronous-oracle' already exists"
else
    cloudflared tunnel create acronous-oracle
    echo "  Created tunnel"
fi

# 4. Copy config
echo "[4/5] Setting up tunnel config..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/cloudflared-config.yml" ]; then
    cp "$SCRIPT_DIR/cloudflared-config.yml" /root/.cloudflared/config.yml
    echo "  Config copied to /root/.cloudflared/config.yml"
else
    echo "  WARNING: cloudflared-config.yml not found in $SCRIPT_DIR"
    echo "  Please copy it manually to /root/.cloudflared/config.yml"
fi

# 5. Route DNS
echo "[5/5] Routing DNS to tunnel..."
cloudflared tunnel route dns acronous-oracle oracle.acronous.com || echo "  DNS route may already exist"
cloudflared tunnel route dns acronous-oracle search.acronous.com || echo "  DNS route may already exist"
cloudflared tunnel route dns acronous-oracle ollama.acronous.com || echo "  DNS route may already exist"
cloudflared tunnel route dns acronous-oracle oracle-ui.acronous.com || echo "  DNS route may already exist"

echo ""
echo "=== Setup Complete ==="
echo ""
echo "To start the tunnel:"
echo "  cloudflared tunnel run --config /root/.cloudflared/config.yml"
echo ""
echo "To install as a system service (auto-restart):"
echo "  cloudflared service install"
echo "  systemctl enable cloudflared"
echo "  systemctl start cloudflared"
echo ""
echo "Tunnel URLs (permanent, won't change on restart):"
echo "  Image service: https://oracle.acronous.com"
echo "  Search:        https://search.acronous.com"
echo "  Ollama:        https://ollama.acronous.com"
echo "  Web UI:        https://oracle-ui.acronous.com"
