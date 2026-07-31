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
      │   └─ image-service/app.py (rembg + Pillow + CLIP + SD + Real-ESRGAN)
      │
      ├─ Strategy 2: Workers AI Inpainting (dimension-matched mask)
      │   ├─ Reads image dimensions from binary header (JPEG/PNG/WebP)
      │   ├─ Creates pixel-level mask at exact image dimensions
      │   └─ Uses @cf/runwayml/stable-diffusion-v1-5-inpainting
      │
      ├─ Strategy 3: Vision-Guided Python Service
      │   ├─ Ollama vision analyzes image + intent
      │   ├─ Python service applies intelligent edits
      │   ├─ Craft edit prompt with LLM
      │   └─ Send enhanced prompt + image to Python service
      │
      └─ Strategy 4: Apology
          └─ If all strategies fail, return natural apology text
```

## Python Microservice (`image-service/`)

A FastAPI service that provides:
- **rembg segmentation** (CPU) — clothing/person/foreground masks
- **Smart recoloring** (CPU) — color palette transfer based on edit description
- **SD Inpainting** (CPU) — Stable Diffusion local model
- **Image generation** (CPU) — photorealistic by default
- **Real-ESRGAN upscaling** (CPU)
- **CLIP analysis** (CPU)
- **Voice TTS** — Edge-TTS (300+ Microsoft Neural TTS voices)
- **Voice editing** — pydub + soundfile (trim, speed, volume)
- **Video frames** — MoviePy assembly from SD-generated frames

### Deploy to Oracle Cloud

```bash
cd oracle-cloud
# Set EDITOR_SERVICE_URL in .env
cp .env.example .env
nano .env
# Set EDITOR_SERVICE_URL=http://localhost:7860

# Start all services
docker compose up -d --build
```

### API Endpoints
| Endpoint | Method | Description |
|---|---|---|
| `/edit` | POST | Edit image with prompt (multipart) |
| `/generate` | POST | Generate image from prompt |
| `/generate-photorealistic` | POST | Generate photorealistic image |
| `/segment` | POST | Get segmentation mask |
| `/remove-bg` | POST | Remove background |
| `/upscale` | POST | Upscale image with Real-ESRGAN |
| `/analyze` | POST | Analyze image with CLIP |
| `/generate-video` | POST | Generate video from prompt |
| `/tts` | POST | Text-to-speech |
| `/voice/edit` | POST | Edit voice/audio |
| `/health` | GET | Health check |
| `/capabilities` | GET | List capabilities |

## Key Functions (cloudflare-worker.js)

| Function | Purpose |
|---|---|
| `getImageDimensions()` | Reads JPEG/PNG/WebP pixel dimensions from binary header |
| `createEditMask()` | Creates pixel-level grayscale mask at exact image dimensions |
| `tryEditorService()` | Calls Python microservice (rembg + Pillow + SD) |
| `analyzeImageWithVision()` | Uses OpenRouter vision model to describe image |
| `buildEditPrompt()` | Crafts precise edit instruction with vision context |
| `parseEditTarget()` | Classifies prompt into clothing/background/face/hair/color/auto |
| `tryWorkersAIInpaint()` | CF Workers AI inpainting with dimension-matched mask |
| `tryOpenRouterEdit()` | OpenRouter-based image editing |

## Working Edit Examples

- "edit this image to replace the dress with a formal suit"
- "change the background to a beach sunset"
- "make this look like a cartoon"
- "change the shirt to blue"
- "remove the person in the background"
- "add a hat to the person"
- "convert to oil painting style"
