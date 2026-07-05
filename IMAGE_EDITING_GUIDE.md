# Acronous AI Image Editing Guide

## Architecture Overview

```
User uploads image + edit prompt
  │
  ├─► Flutter Frontend (chat_provider.dart)
  │   ├─ Detects edit intent via keyword matching
  │   └─ Calls /v1/image/edit (120s timeout)
  │
  └─► Cloudflare Worker (cloudflare-worker.js)
      │
      ├─ Strategy 1: Python Service (if EDITOR_SERVICE_URL set)
      │   └─ image-service/app.py (rembg + Pillow + optional SD GPU)
      │
      ├─ Strategy 2: Vision-Guided Editing
      │   ├─ Analyze image with OpenRouter vision model
      │   ├─ Craft edit prompt with LLM
      │   └─ Send enhanced prompt to Pollinations
      │
      ├─ Strategy 3: Better Pollinations
      │   └─ POST with enhanced prompt + image context
      │
      ├─ Strategy 4: Workers AI img2img
      │   └─ CF AI SDXL with image input + strength params
      │
      ├─ Strategy 5: Standard Pollinations
      │   └─ Original img2img POST
      │
      └─ Strategy 6: Workers AI text-to-image
          └─ Last resort fallback
```

## Python Microservice (`image-service/`)

A FastAPI service that provides:
- **rembg segmentation** (CPU) — clothing/person/foreground masks
- **Smart recoloring** (CPU) — color palette transfer based on edit description
- **SD Inpainting** (GPU, optional) — Stable Diffusion 2 inpainting pipeline

### Deploy to Hugging Face Spaces (Free)

```bash
cd image-service
git init && git add . && git commit -m "init"
git remote add space https://huggingface.co/spaces/YOUR_USER/acronous-image-service
git push space main
```

Then set Cloudflare Worker secret:
```bash
npx wrangler secret put EDITOR_SERVICE_URL
# Value: https://YOUR_USER-acronous-image-service.hf.space
```

### API Endpoints
| Endpoint | Method | Description |
|---|---|---|
| `/edit` | POST | Edit image with prompt (multipart) |
| `/segment` | POST | Get segmentation mask |
| `/remove-bg` | POST | Remove background |
| `/health` | GET | Health check |

## Helper Functions (cloudflare-worker.js)

| Function | Purpose |
|---|---|
| `tryEditorService()` | Calls Python microservice |
| `analyzeImageWithVision()` | Uses vision model to describe image |
| `craftEditPrompt()` | Uses LLM to create optimal edit prompt |
| `tryBetterPollinationsEdit()` | Enhanced Pollinations with context |
| `tryWorkersAIEdit()` | CF Workers AI img2img |
| `tryPollinationsImageEdit()` | Standard Pollinations img2img |

## Working Edit Examples

- "edit this image to replace the dress with a formal suit"
- "change the background to a beach sunset"
- "make this look like a cartoon"
- "change the shirt to blue"
- "remove the person in the background"
- "add a hat to the person"
- "convert to oil painting style"
