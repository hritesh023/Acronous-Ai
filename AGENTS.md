# Acronous AI — Agent Context

## Architecture

### Chat (Text)
- **Primary**: OpenRouter (`OPENROUTER_API_KEY`) — main LLM provider
- **Fallback**: Pollinations Text API (`https://text.pollinations.ai`) — free, no API key needed, used when OpenRouter fails
- **Timeouts**: Generous (30s greeting, 90s simple, 3m moderate, 5m complex) — no hard limits
- **All responses LLM-generated** — no hardcoded fallback text
- **Web Search**: DuckDuckGo HTML search (primary) + Instant Answer API (fallback) — always-on for EVERY user query to ensure internet-aware answers
- **Chat Memory**: Full conversation history (`messages` array) is sent with every API call to both OpenRouter and Pollinations, ensuring context awareness across the entire conversation

### Image Generation (Text-to-Image)
- **Pollinations.ai** image generation (`https://image.pollinations.ai/prompt/...`) — free, no API key needed
- **OpenRouter** flux models for fallback

### Image Editing (modify existing images)
**6-layer priority pipeline for maximum quality:**

1. **Python Microservice** (`image-service/`) — Uses rembg (CPU segmentation) + Pillow compositing + optional GPU SD inpainting. Deployed on Hugging Face Spaces or any host. Set `EDITOR_SERVICE_URL` env var.
2. **Vision-Guided Editing** — Uses OpenRouter vision model to analyze image content, then LLM to craft precise edit instructions before sending to image engine.
3. **Better Pollinations** — Enhanced prompt engineering with image context for higher quality img2img.
4. **Workers AI with Image Input** — CF Workers AI img2img with tuned parameters (strength, guidance).
5. **Standard Pollinations POST** — Original img2img fallback.
6. **Workers AI Text-to-Image** — Last resort, regenerates from scratch.

**Key Improvements:**
- Vision model analyzes image first → understands exact region to edit
- LLM crafts optimal edit prompt based on actual image content
- Python service does precise segmentation (rembg CPU) for targeted edits
- Optional GPU path with Stable Diffusion inpainting

**Hard rules:**
- NEVER respond with "I cannot edit images" — always attempt all 6 strategies first
- If all strategies fail, return empty so the chat LLM generates a natural apology
- No hardcoded response templates

### Image Editing Endpoints in Worker
| Endpoint | Purpose |
|---|---|
| `/v1/image/edit` | Main editing endpoint (6 strategies) |
| `/v1/image/ultra-edit` | Frontend fallback 1 (3 strategies) |
| `/api/image/redesign` | Frontend fallback 2 (vision + Pollinations) |

### Image Analysis (Vision)
- **OpenRouter** with vision models (`VISION_MODEL`, `FALLBACK_VISION_MODEL`)

### File Processing
- **OpenRouter** for file analysis/code generation

## API Setup

### Pollinations (always free, no key, fallback for chat)
- Chat: POST `https://text.pollinations.ai` with `{ messages: [...], model: "openai", private: true }`
- Images: GET `https://image.pollinations.ai/prompt/{encoded}`
- Img2img: GET with `&img=` parameter for image-to-image editing

### Hugging Face (free tier, no key needed for inference)
- Instruct-pix2pix: POST `https://api-inference.huggingface.co/models/timbrooks/instruct-pix2pix?prompt={instruction}` with raw image bytes
- Inpainting: POST to `stabilityai/stable-diffusion-2-inpainting` or `runwayml/stable-diffusion-inpainting`

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
