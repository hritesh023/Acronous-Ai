# Acronous AI — Agent Context

## Current API Setup (OpenRouter Free)
- **Base URL**: `https://openrouter.ai/api/v1` (set via `OPENROUTER_BASE_URL`)
- **API Key**: OpenRouter key stored as `OPENROUTER_API_KEY` secret
- **Models**: `openrouter/free` for all (auto-selects best free model per request)
- **Headers**: `HTTP-Referer: https://ai.acronous.com`, `X-Title: Acronous AI`

## If OpenRouter Causes Problems → Revert to OpenAI

Change these files:

### 1. `cloudflare-worker.js`
- `OPENROUTER_BASE_URL` default: `https://openrouter.ai/api/v1` → `https://api.openai.com/v1`
- `OPENROUTER_MODEL` default: `openrouter/free` → `gpt-4o`
- `VISION_MODEL` default: `openrouter/free` → `gpt-4o`
- `FALLBACK_VISION_MODEL` default: `openrouter/free` → `gpt-4o-mini`
- `FAST_MODEL` default: `openrouter/free` → `gpt-4o-mini`
- In `callOpenRouter()` function: remove the `HTTP-Referer` and `X-Title` headers.

### 2. `wrangler.toml`
```toml
OPENROUTER_MODEL = "gpt-4o"
VISION_MODEL = "gpt-4o"
FALLBACK_VISION_MODEL = "gpt-4o-mini"
FAST_MODEL = "gpt-4o-mini"
OPENROUTER_BASE_URL = "https://api.openai.com/v1"
```

### 3. Set the OpenAI key
```sh
npx wrangler secret put OPENROUTER_API_KEY
```
Enter the OpenAI key.

### 4. Redeploy
```sh
npx wrangler deploy cloudflare-worker.js --name acronous-ai
```

## Build & Deploy
```sh
flutter build web --dart-define="API_BASE_URL=https://ai.acronous.com"
Copy-Item -LiteralPath "web/_worker.js" -Destination "build/web/_worker.js" -Force
npx wrangler pages deploy build/web --project-name=acronous-ai
npx wrangler deploy cloudflare-worker.js --name acronous-ai
```
