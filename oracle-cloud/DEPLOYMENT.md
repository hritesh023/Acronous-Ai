# Acronous AI — Oracle Cloud Deployment Guide

## Prerequisites
- Oracle Cloud Free Tier account (activated)
- SSH key pair generated

---

## STEP 1: Create VM Instance in Oracle Cloud Console

1. Go to **Oracle Cloud Console** → https://cloud.oracle.com
2. Click **Create a VM instance** (or Compute → Instances → Create Instance)
3. Configure:
   - **Name**: `acronous-ai`
   - **Image**: Oracle Linux 8 or Ubuntu 22.04 (Canonical)
   - **Shape**: `VM.Standard.A1.Flex` (Burstable, up to 4 OCPUs, 24 GB RAM)
     - Click **Change shape** → Select **Ampere** → Set **4 OCPUs** and **24 GB RAM**
   - **VPU**: 50 (for boot volume, gives ~200GB storage)
4. **Networking**:
   - Select your VCN (or create new)
   - Select a subnet (or create new public subnet)
   - Assign **Public IP**: Yes
5. **Add SSH keys**: Paste your public key
6. Click **Create**

---

## STEP 2: Open Ports in Security List

1. Go to **Networking** → **Virtual Cloud Networks** → click your VCN
2. Click your **public subnet**
3. Under **Security Lists**, click the default security list
4. **Add Ingress Rules**:

| Port | Protocol | Source | Purpose |
|------|----------|--------|---------|
| 22 | TCP | Your IP/32 | SSH |
| 80 | TCP | 0.0.0.0/0 | HTTP |
| 443 | TCP | 0.0.0.0/0 | HTTPS |

---

## STEP 3: Connect via SSH

```bash
# From your local machine
ssh -i ~/.ssh/your_private_key.pem opc@<PUBLIC_IP>

# Or for Ubuntu:
ssh -i ~/.ssh/your_private_key.pem ubuntu@<PUBLIC_IP>
```

---

## STEP 4: Deploy Acronous AI

### Option A: Upload project files (recommended)

```bash
# On your LOCAL machine, from the project root:
scp -i ~/.ssh/your_private_key.pem -r "Acronous Ai/oracle-cloud" opc@<PUBLIC_IP>:/tmp/acronous-deploy

# On the VM:
ssh opc@<PUBLIC_IP>
sudo cp -r /tmp/acronous-deploy/* /opt/
cd /opt
```

### Option B: Git clone (if repo is on GitHub)

```bash
ssh opc@<PUBLIC_IP>
sudo mkdir -p /opt/acronous-ai && cd /opt/acronous-ai
git clone https://github.com/YOUR_USER/Hritesh-apps.git .
cd "Acronous Ai/oracle-cloud"
```

---

## STEP 5: Run Setup Script

```bash
# On the VM
cd /opt/oracle-cloud

# Make script executable
chmod +x setup.sh

# Create .env with your API key
cp .env.example .env
nano .env
# Set OPENROUTER_API_KEY=sk-or-v1-your_actual_key

# Run setup (installs Docker, builds Flutter, starts services)
sudo ./setup.sh
```

---

## STEP 6: Verify Deployment

```bash
# Check services are running
docker compose ps

# Check logs
docker compose logs -f

# Test API
curl http://localhost/health
curl -X POST http://localhost/v1/chat -H "Content-Type: application/json" -d '{"message": "Hello!"}'
```

---

## STEP 7: (Optional) Point Your Domain

1. Go to your domain registrar (e.g., Namecheap, GoDaddy)
2. Add DNS record:
   - **Type**: A
   - **Host**: `ai` (for ai.acronous.com)
   - **Value**: `<PUBLIC_IP>`
   - **TTL**: 300

---

## STEP 8: (Optional) Setup SSL with Let's Encrypt

```bash
# Install certbot
sudo apt-get install -y certbot

# Stop nginx temporarily
docker compose stop nginx

# Get certificate (standalone mode)
sudo certbot certonly --standalone -d ai.acronous.com

# Copy certs to project
sudo cp /etc/letsencrypt/live/ai.acronous.com/fullchain.pem /opt/oracle-cloud/data/certbot/conf/
sudo cp /etc/letsencrypt/live/ai.acronous.com/privkey.pem /opt/oracle-cloud/data/certbot/conf/

# Update nginx config for SSL (add 443 server block)
# Restart
docker compose up -d
```

---

## Service Architecture

```
┌─────────────────────────────────────────┐
│            Oracle Cloud VM              │
│            (24GB RAM)                   │
│                                         │
│  ┌─────────┐  ┌──────────┐  ┌────────┐ │
│  │  Nginx   │  │  Node.js  │  │ Python │ │
│  │  :80     │──│  :3000    │──│ :7860  │ │
│  │ (static  │  │ (API)     │  │(image) │ │
│  │  +proxy) │  │           │  │        │ │
│  └─────────┘  └──────────┘  └────────┘ │
│       │              │            │      │
│   Flutter Web    OpenRouter   rembg     │
│   build          Pollinations  Pillow   │
│                  HuggingFace           │
└─────────────────────────────────────────┘
```

## Memory Allocation (24GB total)

| Service | RAM |
|---------|-----|
| Node.js API | ~512MB |
| Python Image Service | ~2-4GB (with rembg models) |
| Nginx | ~50MB |
| OS + Docker | ~1GB |
| **Available for growth** | **~18GB** |

## Quick Commands

```bash
# View logs
docker compose logs -f api-server
docker compose logs -f image-service

# Restart services
docker compose restart

# Stop all
docker compose down

# Update and rebuild
docker compose build --no-cache && docker compose up -d

# Check resource usage
docker stats
free -h
df -h
```
