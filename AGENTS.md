# Acronous AI — Agent Context

## Policy: FULLY SELF-HOSTED
- **Zero external/rate-limited model services.** No Workers AI, no Gemini, no OpenRouter in any request path.
- All LLM inference → Oracle Cloud Ollama (`OLLAMA_BASE_URL` secret). All image ops → Oracle image-service (`EDITOR_SERVICE_URL`), including `/generate-image` (procedural scene engine) and `/generate-video` (multi-shot scenes + narration).
- Internet data is fine (DuckDuckGo/Wikipedia search runs in-worker) — that's data fetching, not a model service.
- The Workers AI `[ai]` binding has been REMOVED from wrangler.toml; never re-add it.

## Models (Oracle 24GB, 4-core Ampere CPU — measured)
| Model | tok/s | Use |
|---|---|---|
| qwen2.5:1.5b | 10.5 | too weak — refuses despite system prompt; avoid |
| qwen2.5:3b | 5.7 | chat default (`OLLAMA_MODEL`) |
| qwen3:4b | 4.5 | burns tokens on hidden `<think>` — empty content; avoid |
| qwen2.5-coder:7b | 2.6 | code queries (`OLLAMA_CODE_MODEL`) |
| qwen3:8b | 2.35 | caused 90s-timeout 500s; do not use |

- `keep_alive: '24h'` everywhere — cold model load costs ~20s, warm prefill ~0.2s.
- Warm chat round-trip ≈ 5–7s total; cold ≈ 25–40s until model loads once.

## Speed architecture (do not regress)
- `buildEnhancedSystemPrompt()` is **STATIC and COMPRESSED** (~150 tokens; every token costs CPU prefill) → Ollama prefix KV-cache stays warm. Per-request context goes through `buildDynamicContextBlock(tz, location, webData, userMemory)` injected as a system message AFTER stable history: `[sys(static)] + history + [sys(dynamic)] + [user]`.
- Prompt length rule: simple questions get 2-4 sentences, no preamble — cuts generation time ~5x on casual asks. Long answers reserved for explanations/how-tos/research/code.
- `classifyQuery()` skips the search phase for greetings/code/math/creative/advice.
- Search phase hard-capped at **900ms** (`settleWithCap`). Wikipedia infobox lookup is gated to role queries only ("X of Y" pattern), 800ms cap — it used to add up to 1.5s to EVERY message.
- Measured warm TTFC ≈ **2.9s** (search 0.9s + fetch/prefill ~1.7s); first request after idle pays connection+cache cost (~6-17s if a long generation overlaps). Direct Ollama TTFT: 0.45s warm / 1.8s cold-cache with full prompt.
- Never race tryWorkersAIChat against callOllama — same box, doubles CPU load, halves throughput for zero benefit.
- callOllama uses stream:true internally and accumulates (see Chat endpoints).
- System prompt requires COMPLETE answers (no truncation; depth matched to the question). Old <80-words brevity rule removed — it caused cutoff complaints.

## Critical runtime landmines
- **Never reference try-scoped variables inside catch blocks** — hoist above try. This bit twice: tz/location/webData/message/history AND `sessionId` in BOTH `/v1/chat` and `/v1/chat/stream` (sessionId in catch caused `error code: 1101` on malformed JSON). Violation = opaque CF `1101`.
- **Register `ctx.waitUntil` BEFORE returning the Response.** Calling it inside a ReadableStream `start()` after `controller.close()` races worker shutdown and silently drops KV writes (this broke cross-chat memory once). Pattern: deferred promise resolved at stream end, `ctx.waitUntil(promise.then(...))` before return.
- Both handlers log real errors: `console.error('[/v1/chat...] original error:', ...)` — check `wrangler tail` when smoke tests fail fast.
- KV writes are eventual-consistent (~seconds); test harnesses should sleep ≥15–20s between write and recall.
- PowerShell 5.1 (`powershell -File`) mangles curl `-d $json` with spaces/quotes → always POST via temp file + `--data-binary "@file"`.

## Cross-chat memory
- KV namespace USER_MEMORY (`245e81f7...`), key `memory:<userId>` from JWT `sub` (no signature check needed for memory keying).
- `updateAndStoreUserMemory` stores QA pairs (capped `MEMORY_MAX_ENTRIES`, sanitized 250/400 chars). `formatMemoryForPrompt` injects last 20 entries with relative timestamps.
- Streaming path uses `num_ctx: 8192` (doubled from 4096) — model can see ~4x more conversation history, directly fixing mid-chat context loss.
- Dynamic context block now includes current date+time (UTC) with stronger "always use CURRENT info" instruction.
- `buildEnhancedSystemPrompt` includes explicit follow-up handling: "For follow-up messages like 'try again', 'what about the other one', 'tell me more' — use conversation history to understand context."
- Verified working end-to-end (write in session A → recall in session B).

## Image endpoints (all wired to real engines — no decline stubs)
- `/v1/image/generate` → `generateImageForChat()` + one retry; returns `{response: explanation, image_data, type: 'image_gen'}`.
- `/v1/image/smart-edit` → deterministic pre-check `isExplicitGenerateRequest()` (keyword classifier + detectImageGenerationIntent — both exclude edit/change/recolor phrasing) routes creation requests to generation BEFORE the LLM intent classifier runs; the 3B classifier otherwise misroutes "create X" to edit. Edit/redesign/recreate still go through `tryEditWithFallback`.
- `/v1/image/edit` + `/v1/image/ultra-edit` (legacy fallbacks the app also calls) share the same helpers: `tryGenerateEndpoint()` for explicit creation, clean failure wording without engine/infrastructure mentions.
- Failure text is always `IMAGE_GEN_UNAVAILABLE` ("couldn't create that image right now") — never mention deployment/backend/engine internals.
- Verified: creation phrases on all 3 edit endpoints return ~1.4MB generated images in 5-13s; genuine edit phrases return small edited files.

## Input hardening (all request payloads are untrusted)
- `safeText(v, max)` coerces any JSON type to a bounded string (message cap 16k chars); used for message/session_id/timezone/location/gps in both chat handlers and image endpoints.
- `sanitizeHistory()` — client-supplied `messages` arrays lose everything except user/assistant roles (fake "system" turns can't hijack the persona), each turn capped 4000 chars. Applied at ALL history parse sites (2 chat handlers + 6 multipart endpoints).
- `parseMultipartForm` rejects bodies > 12MB (`MAX_UPLOAD_BYTES`) via Content-Length pre-check + post-buffer check.
- `isHarmfulEditRequest` guards `/v1/image/generate`, `tryGenerateEndpoint` (explicit guideline refusal) and `renderVideoForChat` (falls back to chat path). List includes violence/gore/drugs/bomb terms + 'violence' spelling.
- Verified abuse matrix: malformed JSON → graceful 200 apology (was 1101); non-string message types coerced; 13MB upload → graceful error; harmful gen prompt → refusal; identity/chat regression unaffected.

## Chat endpoints
- `/v1/chat` (JSON), `/v1/chat/stream` (SSE). SSE done event may carry `file_data`/`file_name`/`file_type` (video) or `image_data` (generated image) — Flutter client persists into the message as attachment.
- Video intent (`detectVideoGenerationIntent`) → self-hosted renderer with synthesized scenes + edge-tts narration; caption uses the parsed topic. Image-gen intent (`detectImageGenerationIntent`) → `generateImageForChat()` (Oracle scene engine) returning explanation + image; on failure returns type 'chat' with IMAGE_GEN_UNAVAILABLE (never type 'image_gen' with empty data).
- Identity queries (`detectIdentityQuery`) answered deterministically via IDENTITY_ANSWER — checked BEFORE greeting regex in BOTH handlers.
- callOllama uses stream:true internally and accumulates (non-streaming sends zero bytes → CF edge/nginx idle-kill long generations, which caused response:null). Never race tryWorkersAIChat against callOllama — same box, doubles CPU load.
- Non-streaming chat num_predict capped at 2048 (~6 min @5.7 tok/s < client's 10-min timeout); streaming path uses full OLLAMA_CHAT_MAX_TOKENS=8192 since chunks flow.
- Anti-refusal: cleanResponse strips "As an AI..." openers and apology lead-ins; system prompt forbids refusals.

## Generation UX (Flutter)
- Image gen / video gen / file gen / attached-image edit requests show a skeleton preview bubble with context-aware cycling status labels ("Changing background…", "Recording narration…", "Applying final touches…") derived from the user's text (`_buildProgressSteps`). Fields: ChatMessage.progressLabel/progressKind (transient). Widget: lib/widgets/generation_skeleton.dart. Engine: _startGenerationProgress/_finishGenerationProgress in ChatProvider.

## Python Image Service (Oracle Cloud)
- URL: `EDITOR_SERVICE_URL=https://image-service.acronous.com`; compose dir `~/oracle-cloud`, build context `~/image-service/`.
- Torch-free image (rembg onnx + Pillow + OpenCV + edge-tts). rembg models re-download on fresh container start (~minutes) — consider baking into image/volume later.
- `/generate-video`: multipart prompt/duration(6, clamp 2–20)/fps/width/height/images[] → Ken Burns slideshow or animated gradient title card (Pillow frames → ffmpeg h264). Returns `{video_data b64 mp4,...}`. `/capabilities.video = ffmpeg present`.
- **ffmpeg quirks**: pipe output needs `-f mp4` BUT mp4 muxer needs seekable output → write temp file, read bytes, delete in `finally`. Never `stdin.close()` then `communicate()` ("flush of closed file") → feeder thread pattern.
- `/tts`: edge-tts MP3. Voice playback also available fully on-device via flutter_tts (lib/services/tts_service.dart).
- Live-verified: video render (both modes), TTS, background replace (response key is `edited`), honest edit declines.

## Web Search
- In-worker only: DuckDuckGo HTML/lite/API, Wikipedia (+role/location infobox), capped 1500ms, relevance-validated then focused.

## Watermark / branding on generated media
- NO "Acronous AI" text watermark is drawn onto generated images/videos (`_finish_image` has no text block — user explicitly declined text watermarks).
- Images: `LogoWatermark` widget (lib/widgets/logo_watermark.dart — translucent dark pill + border around the logo) at 22px in chat preview (`chat_message.dart` `_buildGeneratedImage`) and 26px in `image_viewer.dart`, both bottom-right. Do not remove these.
- Videos: `_stamp_logo()` in app.py bakes a ~7%-height logo on a translucent dark rounded pill into EVERY frame of `_render_video_bytes` (bottom-right, margin ~1.8% width); asset at `/app/assets/logo.png` in the container. Verified visible via pixel probe.
- CAUTION: when adding Positioned overlays back into chat_message.dart, match the EXACT nesting — a previous edit landed a `Positioned` inside the user bubble's Row (renders as a white box). Verify with flutter analyze before deploy.
- Video narration speaks ONLY about the subject (`_narration_script`) — no "here is your video" meta lines, no branding; style sentence ("The piece is…") stripped.

## Photorealistic default (scene engine)
- `_parse_scene(prompt, style_override=None)` defaults `style='realistic'`; explicit art-style words only (neon/watercolor/pixel/anime/painterly/minimal/vivid/moody + cartoon/anime/comic/drawing/sketch/oil/illustration) switch styles. Worker sends `style` hint from RAW message via `detectArtStyleHint`.
- Realistic rendering: fractal value-noise cloud field (`_value_noise`, photoreal branch of `_clouds_layer`), smooth ridges (`_ridge_line(smooth=True)`), atmospheric haze band (`_haze_band`), ground texture noise, highlight bloom in `_finish_image`. NOTE: `rgba[..., 3] = np.broadcast_to(alphas[:, None], ...)` — assigning a 1-D array to a 2-D slice raises broadcast errors; keep the [:, None].

## Autonomous Learning (acronous_llm — shared brain)
- **3-phase learning cycle** runs continuously in background (even with zero user interaction):
  - Phase 1 — **Quick Scan** (every 5 min): Rotates through 32 knowledge domains (AI, science, tech, economics, etc.) + 7 real-time RSS feeds (Google News AI/Tech/Space/Health). Searches 6 engines, stores facts to SQLite + RAG + neural classifier.
  - Phase 2 — **Deep Dive** (every 30 min): Picks topics with most new facts, fetches full article content (not just snippets), extracts concepts, builds knowledge graph edges (co-occurrence relationships).
  - Phase 3 — **Self-Evaluation** (every 2 hours): Detects stale concepts (>14 days), underverified facts (single-source), prunes old seen-set entries, decays confidence on stale knowledge.
- **KnowledgeGraph**: In `core/internet_learner.py` — tracks concepts, relationships, freshness. Persisted to `data/models/knowledge_graph.json`.
- **32 Knowledge Domains**: AI news, ML breakthroughs, LLM updates, cybersecurity, quantum computing, space, medical, climate, physics, biology, economics, geopolitics, crypto, startups, energy, software engineering, history, philosophy, psychology, edtech, developer tools, NLP, computer vision, IoT, and more.
- **7 Real-time RSS Feeds**: Google News for AI, Tech, Science, AI/LLM specific, Breaking Tech, Space, Health.
- **Memory temporal awareness**: `memory.py` now tracks `fresh_knowledge_24h`, `total_knowledge`, `avg_confidence`. Confidence decays on facts >30 days old. `verify_knowledge()` boosts confidence when multiple sources confirm.
- **Endpoints**: `POST /v1/internet/learn` (quick scan), `POST /v1/internet/deep-dive`, `POST /v1/internet/self-evaluate`, `GET /v1/knowledge/graph`, `GET /v1/knowledge/gaps`, `GET /v1/knowledge/fresh`.
- Run standalone: `python -m acronous_llm.autonomous --interval 300`
- Default interval: 300s (5 min). Set `ACRONOUS_INTERNET_LEARN_INTERVAL` to override.
- **Key files**: `acronous_llm/core/internet_learner.py` (InternetLearner + KnowledgeGraph), `acronous_llm/core/memory.py` (MemorySystem), `acronous_llm/autonomous.py` (standalone runner), `acronous_llm/server.py` (FastAPI endpoints).

## Common Commands
```sh
# Worker only
npx wrangler deploy cloudflare-worker.js --name acronous-ai

# Full ship (worker + pages)
powershell -ExecutionPolicy Bypass -File deploy-acronous.ps1

# Frontend rebuild
flutter build web --dart-define="API_BASE_URL=https://ai.acronous.com"
Copy-Item -LiteralPath "web/_worker.js" -Destination "build/web/_worker.js" -Force
npx wrangler pages deploy build/web --project-name=acronous-ai

# Oracle hot-patch app.py
scp -i "$env:USERPROFILE\.ssh\oracle_key" image-service/app.py ubuntu@140.245.224.36:~/image-service/app.py
ssh -i "$env:USERPROFILE\.ssh\oracle_key" ubuntu@140.245.224.36 "docker cp ~/image-service/app.py oracle-cloud-image-service-1:/app/app.py && docker restart oracle-cloud-image-service-1"

# Oracle full rebuild (slow; loses /root/.rembg cache)
scp -i "$env:USERPROFILE\.ssh\oracle_key" -r image-service/* ubuntu@140.245.224.36:~/image-service/
ssh -i "$env:USERPROFILE\.ssh\oracle_key" ubuntu@140.245.224.36 "cd ~/oracle-cloud && docker compose build image-service && docker compose up -d image-service"

# Logs / KV / tail
npx wrangler tail acronous-ai --format json
npx wrangler kv key get --namespace-id 245e81f7a70c448d840cc399be821633 "memory:<userId>"
```

## Known analyzer noise (pre-existing, ignore)
- `dart:js_util` import (chat_provider.dart:3), unused `lang` (markdown_renderer.dart:78).
