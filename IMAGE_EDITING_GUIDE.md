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
      ├─ Strategy 2: Hugging Face InstructPix2Pix (free, no key, no mask)
      │   └─ timbrooks/instruct-pix2pix — instruction-based image editing
      │
      ├─ Strategy 3: Workers AI Inpainting (dimension-matched mask)
      │   ├─ Reads image dimensions from binary header (JPEG/PNG/WebP)
      │   ├─ Creates pixel-level mask at exact image dimensions
      │   └─ Uses @cf/runwayml/stable-diffusion-v1-5-inpainting
      │
      ├─ Strategy 4: Vision-Guided Pollinations
      │   ├─ Analyze image with OpenRouter vision model
      │   ├─ Craft edit prompt with LLM
      │   └─ Send enhanced prompt + image to Pollinations
      │
      └─ Strategy 5: Standard Pollinations img2img
          └─ POST with image + prompt (no text-to-image fallback)
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

## Key Functions (cloudflare-worker.js)

| Function | Purpose |
|---|---|
| `getImageDimensions()` | Reads JPEG/PNG/WebP pixel dimensions from binary header |
| `createEditMask()` | Creates pixel-level grayscale mask at exact image dimensions |
| `tryEditorService()` | Calls Python microservice (rembg + Pillow + optional SD) |
| `analyzeImageWithVision()` | Uses OpenRouter vision model to describe image |
| `buildEditPrompt()` | Crafts precise edit instruction with vision context |
| `parseEditTarget()` | Classifies prompt into clothing/background/face/hair/color/auto |
| `tryWorkersAIInpaint()` | CF Workers AI inpainting with dimension-matched mask |
| `tryBetterPollinationsEdit()` | Enhanced Pollinations with vision context (tries turbo/flux/sdxl) |
| `tryPollinationsImageEdit()` | Standard Pollinations img2img |
| `tryHuggingFaceEdit()` | Hugging Face InstructPix2Pix (free, instruction-based, no mask) |
| `tryWorkersAIInpaint()` | CF Workers AI inpainting with dimension-matched mask |
| `tryBetterPollinationsEdit()` | Enhanced Pollinates with vision context |
| `tryPollinationsImageEdit()` | Standard Pollinates img2img |

## Working Edit Examples

- "edit this image to replace the dress with a formal suit"
- "change the background to a beach sunset"
- "make this look like a cartoon"
- "change the shirt to blue"
- "remove the person in the background"
- "add a hat to the person"
- "convert to oil painting style"
