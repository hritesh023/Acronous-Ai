# Deployment Guide for Acronous AI Enhanced Image Editing

## Overview
This document provides deployment instructions for the enhanced Acronous AI application with unlimited image editing capabilities and guaranteed non-empty responses.

## Project Structure
- `cloudflare-worker.js` - Enhanced Cloudflare Worker (API layer)
- `wrangler.toml` - Cloudflare Workers configuration
- `lib/` - Flutter frontend source code
- `web/_worker.js` - Web worker for Flutter web build

## Deployment Methods

### 1. Cloudflare Wrangler Deployment

#### Prerequisites
```bash
# Install wrangler if not already installed
npm install -g wrangler

# Login to Cloudflare
wrangler login

# Set required secrets (if not already set)
npx wrangler secret put OPENROUTER_API_KEY
```

#### Deploy Worker Only
```bash
# Deploy enhanced worker with all improvements
cd "C:\Users\Hritesh\Hritesh-apps\Acronous Ai"
npx wrangler deploy cloudflare-worker.js --name acronous-ai
```

#### Deploy Full Stack (Worker + Frontend)
```bash
# Deploy frontend first
cd "C:\Users\Hritesh\Hritesh-apps\Acronous Ai"
flutter build web --dart-define="API_BASE_URL=https://ai.acronous.com"

# Set web worker
copy "web/_worker.js" "build/web/_worker.js" -Force

# Deploy frontend pages
npx wrangler pages deploy build/web --project-name=acronous-ai

# Deploy enhanced worker
npx wrangler deploy cloudflare-worker.js --name acronous-ai
```

### 2. GitHub Actions Deployment

#### Create GitHub Workflow
Create `.github/workflows/deploy.yml`:

```yaml
name: Deploy to Cloudflare

on:
  push:
    branches: [main]
    paths:
      - 'cloudflare-worker.js'
      - 'wrangler.toml'
      - 'lib/**'

jobs:
  deploy-worker:
    runs-on: ubuntu-latest
    name: Deploy to Cloudflare Workers
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '18'
          cache: 'npm'

      - name: Install dependencies
        run: npm install

      - name: Deploy to Cloudflare Workers
        run: npx wrangler deploy cloudflare-worker.js --name acronous-ai
        env:
          CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}

  deploy-frontend:
    runs-on: ubuntu-latest
    name: Deploy Frontend to Cloudflare Pages
    needs: deploy-worker
    if: github.event_name == 'push'
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Setup Flutter
        uses: subosito/flutter-action@v2
        with:
          flutter-version: '3.19.6'

      - name: Build Flutter web app
        run: flutter build web --dart-define="API_BASE_URL=https://ai.acronous.com"

      - name: Setup Pages
        uses: cloudflare/pages/action@v1
        with:
          apiToken: ${{ secrets.CLOUDFLARE_API_TOKEN }}
          accountId: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
          repository: ${{ github.repository }}
          projectName: acronous-ai
          directory: build/web
```

#### Create GitHub Secrets
In your GitHub repository settings, add the following secrets:
- `CLOUDFLARE_API_TOKEN` - Your Cloudflare API token with Workers and Pages permissions
- `CLOUDFLARE_ACCOUNT_ID` - Your Cloudflare account ID

### 3. Local Testing and Validation

#### Test Worker Locally
```bash
# Test the worker locally (if supported)
npx wrangler dev cloudflare-worker.js

# Or start local development server
npm run dev
```

#### Validate Deployment
After deployment, verify the changes:

```bash
# Test endpoint
curl -X POST https://ai.acronous.com/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello, how are you?"}'

# Test image generation endpoint
# Requires proper API key in headers and body structure
```

### 4. Environment Configuration

#### Required Environment Variables
Set these variables in your Cloudflare Workers dashboard or wrangler.toml:

```toml
# wrangler.toml
name = "acronous-ai"
compatibility_date = "2026-05-30"
main = "cloudflare-worker.js"

[vars]
OPENROUTER_MODEL = "meta-llama/llama-3.3-70b-instruct:free"
VISION_MODEL = "google/gemini-2.5-flash-lite"
FALLBACK_VISION_MODEL = "nvidia/nemotron-nano-12b-v2-vl:free"
FAST_MODEL = "qwen/qwen3-next-80b-a3b-instruct:free"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
ENABLE_WEB = "true"
ENABLE_VISION = "true"
ENABLE_VOICE = "true"
PAGES_ORIGIN = "https://acronous-ai.pages.dev"
```

#### Secrets
Required secrets (set via `wrangler secret put <NAME>`):
- `OPENROUTER_API_KEY` - OpenRouter API key for AI model access

Optional secrets:
- `POLLINATIONS_API_KEY` - Pollinations API key for img2img capabilities
- `WHISPER_API_KEY` - Whisper API key for voice transcription

## Deployment Verification

### Post-Deployment Checklist
After deploying, verify:

1. **Response Generation**:
   - Chat responses are non-empty and natural
   - Image editing returns successful responses
   - Error handling works properly

2. **Image Editing Capabilities**:
   - `cut a part and replace with X` functionality works
   - Web search integration for editing techniques
   - Multiple AI editing strategies are applied

3. **Frontend Access**:
   - `https://ai.acronous.com` loads correctly
   - Chat interface functions properly
   - Image upload and editing features work

4. **Backend Health**:
   ```bash
   # Check worker health
   curl https://ai.acronous.com/health
   
   # Check worker ready status
   curl https://ai.acronous.com/ready
   ```

### Testing Script

Create a test script to verify functionality:

```bash
#!/bin/bash

# Test basic chat functionality
echo "Testing basic chat..."
curl -s -X POST https://ai.acronous.com/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello"}' | jq -r '.response'

# Test image generation request
echo "Testing image generation..."
curl -s -X POST https://ai.acronous.com/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Draw a cat sitting on a mat"}' | jq -r '.image_data'

# Test image editing functionality (requires image upload)
# This would need to be tested manually with the web UI

echo "Deployment tests completed."
```

## Rollback Instructions

If issues occur during deployment:

```bash
# Rollback to previous version
npx wrangler versions acronous-ai
npx wrangler rollback <version_id>
```

## Monitoring and Maintenance

### Set Up Monitoring
1. **Cloudflare Analytics**: Monitor request counts, response times, error rates
2. **Worker Logs**: Review Cloudflare Workers logs in the dashboard
3. **Frontend Performance**: Monitor Core Web Vitals and custom metrics

### Maintenance Checks
- Daily: Check for empty responses or errors
- Weekly: Review deployment logs and error rates
- Monthly: Test image editing capabilities with various requests

## Key Features in This Deployment

This deployment includes:

1. **Enhanced Response Generation**: Guaranteed non-empty responses with multi-phase fallbacks
2. **Unlimited Image Editing**: Multiple parallel AI editing strategies with web search integration
3. **Cutting-Edge Edit Requests**: Proper handling of "cut a part and replace with X" and similar requests
4. **Optimized Performance**: Simplified timeouts and parallel processing for faster responses
5. **Robust Error Handling**: Comprehensive error recovery and fallback mechanisms

## Troubleshooting

### Common Issues and Solutions

1. **Empty Responses**:
   - Check worker logs for errors
   - Verify OPENROUTER_API_KEY secret is properly set
   - Ensure all model endpoints are reachable

2. **Image Editing Failures**:
   - Test with simpler edit requests first
   - Verify the edit detection patterns
   - Check web search integration

3. **Deployment Errors**:
   - Verify wrangler configuration
   - Check for syntax errors in cloudflare-worker.js
   - Ensure all required secrets are set

4. **Performance Issues**:
   - Monitor API response times
   - Check for memory leaks in the worker
   - Consider adjusting timeout values

## Support

For deployment issues:
1. Check Cloudflare Workers dashboard for logs
2. Review GitHub Actions workflow logs if using automated deployment
3. Contact support if issues persist after troubleshooting

The enhanced Acronous AI application is now ready for production deployment with unlimited image editing capabilities and guaranteed non-empty responses!
