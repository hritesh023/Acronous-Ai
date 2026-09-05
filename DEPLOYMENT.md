# Acronous AI Deployment Guide

## Overview
This guide covers deploying Acronous AI with the enhanced image editing pipeline.

## Quick Deploy (Worker + Frontend)

```bash
cd "Acronous Ai"
npx wrangler deploy cloudflare-worker.js --name acronous-ai
flutter build web --dart-define="API_BASE_URL=https://ai.acronous.com"
Copy-Item -LiteralPath "web/_worker.js" -Destination "build/web/_worker.js" -Force
npx wrangler pages deploy build/web --project-name=acronous-ai
```

## Deploy Python Image Service (Optional, for best editing quality)

### Option 1: Oracle Cloud (Recommended)
Deploy on your Oracle Cloud VM using Docker Compose. See `oracle-cloud/DEPLOYMENT.md` for full setup.

### Option 2: Railway (Free tier)
Deploy `image-service/` as a Railway service from GitHub.

### Option 3: Render (Free tier)
Deploy `image-service/` as a Web Service. Start command: `uvicorn app:app --host 0.0.0.0 --port 10000`

## GitHub Actions (Automated)
Push to main/master triggers automatic deployment via `.github/workflows/deploy.yml`.

## Required Secrets
```bash
npx wrangler secret put EDITOR_SERVICE_URL
```

## Environment Variables (wrangler.toml)
```toml
[vars]
EDITOR_SERVICE_URL = ""  # Set via secret in production
```

## Verification
```bash
curl https://api.acronous.com/health
```
