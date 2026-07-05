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
**5-layer pipeline — NO text-to-image fallback (produces broken/random images):**

1. **Python Microservice** (`image-service/`) — rembg + Pillow + optional SD GPU. Set `EDITOR_SERVICE_URL`.
2. **Hugging Face InstructPix2Pix** — `timbrooks/instruct-pix2pix`, free, no API key needed, instruction-based editing (no mask required). ~30 req/hr without token, higher with `HF_API_TOKEN` secret.
3. **Workers AI Inpainting** — `@cf/runwayml/stable-diffusion-v1-5-inpainting` with dimension-matched mask (reads JPEG/PNG/WebP headers to get pixel dimensions).
4. **Better Pollinations** — Enhanced prompt with vision context, tries turbo/flux/sdxl models.
5. **Standard Pollinations POST** — Original img2img fallback. If all fail, returns text error — never regenerates from scratch.

**Key rules:**
- Image dimensions detected from binary header (no canvas needed) → mask created at exact pixel size
- InstructPix2Pix is instruction-based: "change the dress to red" works without parsing edit targets
- NEVER use SDXL text-to-image as edit fallback (generates unrelated image)
- If all strategies fail, return a natural apology text — never a random image

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
