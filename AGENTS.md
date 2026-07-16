# Acronous AI — Agent Context

## Architecture

### Chat (Text)
- **Primary**: OpenRouter (`OPENROUTER_API_KEY`) — main LLM provider
- **Fallback**: Workers AI chat — secondary free fallback
- **Timeouts**: Generous (30s greeting, 90s simple, 3m moderate, 5m complex) — no hard limits
- **All responses LLM-generated** — no hardcoded fallback text
- **Web Search**: DuckDuckGo HTML search (primary) + Instant Answer API (fallback) — always-on for EVERY user query to ensure internet-aware answers
- **Chat Memory**: Full conversation history (`messages` array) is sent with every API call to ensure context awareness across the entire conversation

### Image Generation (Text-to-Image)
- **Python Image Service** (primary) — SD model running on Oracle Cloud CPU via `image-service/`. Set `EDITOR_SERVICE_URL` to your Oracle Cloud image-service URL. Photorealistic by default.
- **Workers AI FLUX 1 Schnell** (`@cf/black-forest-labs/flux-1-schnell`) — free, runs on CF GPU, instant, unlimited.
- **Workers AI SDXL** (`@cf/stabilityai/stable-diffusion-xl-base-1.0`) — free fallback.

### Image Editing (modify existing images)
**7-layer pipeline — OpenRouter FLUX replaced with Workers AI FLUX:**

1. **Python Microservice** (`image-service/`) — rembg + Pillow + CLIP vision + Real-ESRGAN upscaling + SD local generation. Set `EDITOR_SERVICE_URL`.
2. **Workers AI Inpainting** — `@cf/runwayml/stable-diffusion-v1-5-inpainting` with dimension-matched mask. Tries both `image_b64` (base64) and raw array inputs, `strength: 1.0`.
3. **Hugging Face InstructPix2Pix** — `timbrooks/instruct-pix2pix`, free, instruction-based editing (no mask required). 60s timeout for cold starts. ~30 req/hr without token, higher with `HF_API_TOKEN`.
4. **LLM-Guided Edit** — LLM vision analysis + Python service SD generation (tries Workers FLUX + Workers AI as fallbacks).
5. **LLM-Guided FLUX** — LLM vision analysis + Workers AI FLUX 1 Schnell generation.
6. **Workers AI FLUX direct** — text-to-image via `@cf/black-forest-labs/flux-1-schnell` (free, unlimited via Workers AI).
7. **Workers AI SDXL** — text-to-image via Stable Diffusion XL (free, CF GPU).

**Key rules:**
- Image dimensions detected from binary header → mask created at exact pixel size
- Python image-service is the primary edit/generation engine
- OpenRouter image models (FLUX.1-schnell-free) are DEAD — do NOT use
- Workers AI FLUX 1 Schnell (`@cf/black-forest-labs/flux-1-schnell`) is the main free fallback
- If all strategies fail, return a natural apology — never a random image

### Image Editing Endpoints in Worker
| Endpoint | Purpose |
|---|---|
| `/v1/image/edit` | Main editing endpoint (7 strategies) |
| `/v1/image/ultra-edit` | Frontend fallback 1 (6 strategies) |
| `/api/image/redesign` | Frontend fallback 2 (6 strategies with vision) |
| `/v1/image/smart-edit` | Intelligent routing (LLM classifies edit/generate/analyze) |

### Image Analysis (Vision)
- **OpenRouter** with vision models (`VISION_MODEL`, `FALLBACK_VISION_MODEL`)

### Video Generation
- **Python Image Service** — local SD model generates 8 photorealistic frames → MoviePy assembles into MP4

### Voice TTS
- **Python Image Service** — Edge-TTS (300+ Microsoft Neural TTS voices), no API key needed

### Voice Editing
- **Python Image Service** — pydub + soundfile for audio manipulation (trim, speed, volume, normalize)

### File Processing
- **OpenRouter** for file analysis/code generation

## Python Image Service (Oracle Cloud)
- **URL**: Set `EDITOR_SERVICE_URL` env var to your Oracle Cloud image-service URL
- **Capabilities**: Background removal, image upscaling, CLIP analysis, image generation, image editing, video frame generation, voice TTS, voice editing
- **Models**: rembg (background removal), Real-ESRGAN (upscaling), CLIP (analysis), Stable Diffusion (generation), Edge-TTS (voice)
- **Docker Compose**: `oracle-cloud/docker-compose.yml` — nginx (port 80), api-server (port 3000), image-service (port 7860)
- **Memory**: 14GB limit for image-service (fits SD + CLIP + rembg in 24GB RAM)

## API Setup

### Hugging Face (free tier, no key needed for inference)
- Instruct-pix2pix: POST `https://api-inference.huggingface.co/models/timbrooks/instruct-pix2pix` with base64 image + prompt. 60s timeout for cold starts.
- Inpainting: Not used directly — Workers AI handles inpainting instead

### OpenRouter (fallback only)
- **Base URL**: `https://openrouter.ai/api/v1` (env `OPENROUTER_BASE_URL`)
- **API Key**: Stored as `OPENROUTER_API_KEY` secret
- **Models**: `meta-llama/llama-3.3-70b-instruct:free`, `google/gemini-2.5-flash-lite`, `nvidia/nemotron-nano-12b-v2-vl:free`, `qwen/qwen3-next-80b-a3b-instruct:free`
- **Headers**: `HTTP-Referer: https://ai.acronous.com`, `X-Title: Acronous AI`

## Watermark
- 10px font size, positioned on the image itself (inside `InteractiveViewer`/`Stack`)
- Visible when zoomed — scales with the image

## Common Commands

### Deploy worker only
```sh
npx wrangler deploy cloudflare-worker.js --name acronous-ai
```

### Rebuild and deploy frontend
```sh
flutter build web --dart-define="API_BASE_URL=https://ai.acronous.com"
Copy-Item -LiteralPath "web/_worker.js" -Destination "build/web/_worker.js" -Force
npx wrangler pages deploy build/web --project-name=acronous-ai
```

### Set secrets
```sh
npx wrangler secret put OPENROUTER_API_KEY
# Optional: Hugging Face token for higher InstructPix2Pix rate limits (~30 req/hr without)
npx wrangler secret put HF_API_TOKEN
```

### Deploy both
```sh
npx wrangler deploy cloudflare-worker.js --name acronous-ai
flutter build web --dart-define="API_BASE_URL=https://ai.acronous.com"
Copy-Item -LiteralPath "web/_worker.js" -Destination "build/web/_worker.js" -Force
npx wrangler pages deploy build/web --project-name=acronous-ai
```

### Web Search
- All search is handled directly in the Cloudflare Worker (no external service)
- Engines: DuckDuckGo HTML/lite/API, Google, Bing, SearXNG, Wikipedia, Mojeek, Google News, Hacker News, Reddit, Guardian
- Python search-service/ has been removed — everything runs in-worker
