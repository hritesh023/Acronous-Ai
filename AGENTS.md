# Acronous AI — Agent Context

## Architecture

### Chat (Text)
- **Primary**: Pollinations Text API (`https://text.pollinations.ai`) — free, no API key needed, uses `openai` model
- **Fallback**: OpenRouter (`OPENROUTER_API_KEY`) — used when Pollinations fails
- **Timeouts**: Generous (30s greeting, 90s simple, 3m moderate, 5m complex) — no hard limits
- **All responses LLM-generated** — no hardcoded fallback text

### Image Generation (Text-to-Image)
- **Pollinations.ai** image generation (`https://image.pollinations.ai/prompt/...`) — free, no API key needed
- **OpenRouter** flux models for fallback

### Image Editing (modify existing images) — NEVER recreates from description
**Priority order for editing:**
1. **Hugging Face instruct-pix2pix** (`timbrooks/instruct-pix2pix`) — true instruction-based editing, sends raw image + edit instruction, edits without recreating
2. **LLM reasoning** (`llmReasonEditApproach`) — determines whether `inpaint` or `instruct` is best for the edit
3. **Hugging Face inpainting** (`stable-diffusion-2-inpainting`, `stable-diffusion-inpainting`) — for cut/replace/structural operations
4. **Web search** + retry — for complex edits, searches web for techniques and retries with enhanced context

**Hard rules:**
- NEVER use vision model to describe image then regenerate from text — this destroys fidelity
- NEVER use OpenRouter/Cloudflare AI/Pollinations for text-to-image regeneration as an edit fallback
- No hardcoded response templates — all responses LLM-generated via `generateNaturalResponse`

### Image Analysis (Vision)
- **OpenRouter** with vision models (`VISION_MODEL`, `FALLBACK_VISION_MODEL`)

### File Processing
- **OpenRouter** for file analysis/code generation

## API Setup

### Pollinations (always free, no key)
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
