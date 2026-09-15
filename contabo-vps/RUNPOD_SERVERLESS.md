# Acronous GPU fast-path — RunPod Serverless (scale-to-zero)

Architecture: Contabo VPS stays always-on ($0). The Worker tries GPU
first, falls back to Contabo CPU on any failure. Unset the GPU vars = pure CPU.

## 1. Overall infra cost (your Serverless pick)

| Layer | What | Cost |
|---|---|---|
| Contabo VPS (chat fallback, image CPU fallback, searxng, tunnel) | 4 OCPU + 24GB, 200GB boot | **$0/mo** (Always Free) |
| Cloudflare Worker + Pages + KV (`USER_MEMORY`, `AUTH_USERS`) | free tier covers ~100k req/day | **$0/mo** (Paid $5/mo only if you exceed) |
| Domain `acronous.com` | registrar | **~$12/yr (~$1/mo)** |
| RunPod Serverless LLM (Qwen2.5-7B, RTX 4090 workers, min 0) | ~$0.0002-0.0004/sec ≈ $0.69-1.44/hr *only while running* | **~$5-20/mo** at your traffic (100-500 chats/day) |
| RunPod Serverless Image (SD-Turbo, RTX 4090, min 0) | ~$0.02-0.06/image (5-15s incl. cold) | **~$5-20/mo** for 200-500 images/mo |
| RunPod storage (endpoint template, no network volume needed) | baked weights | **$0** |
| **Total** | | **~$10-40/mo + $1 domain** |

Why not Contabo GPU 24/7: A10 = $2.00/hr = **~$1,440/mo**. RunPod Pod 24/7 4090 = ~$250-500/mo.
Serverless wins because you pay per second, $0 when idle. Cold starts (15-30s LLM,
20-40s first image) are absorbed by the Worker's GPU timeout + Contabo fallback:
user still gets an answer, just from CPU that one time.

Test-weekend alternative: 1x 4090 Pod Community $0.34/hr × 20 hrs = **~$7**.
Keep $10 RunPod signup credit in mind — first test is nearly free.

## 2. Deploy LLM endpoint (no custom build needed)

Use the official vLLM template — do NOT build your own:

1. RunPod Console → Serverless → New Endpoint → from template `runpod/worker-vllm`.
2. Config: GPU RTX 4090, Min Workers 0, Max Workers 2, Idle Timeout 15s,
   Execution Timeout 90s. Model: `Qwen/Qwen2.5-7B-Instruct`, `--max-model-len 8192 --quantization awq` (fits 24GB with headroom).
3. Copy the Endpoint ID. Your URL = `https://api.runpod.ai/v2/<id>`.
4. Set Worker vars/secrets:
   `npx wrangler secret put GPU_LLM_KEY`  (your RunPod API key)
   vars: `GPU_LLM_URL=https://api.runpod.ai/v2/<id>`, `GPU_LLM_MODEL=Qwen/Qwen2.5-7B-Instruct`.
5. Redeploy: `npx wrangler deploy cloudflare-worker.js --name acronous-ai`.

The Worker's `tryGpuChat` sends `{input:{messages,model,max_tokens}}` to
`/runsync` and unwraps `{output:{choices:[...]}}`. Timeout default 60s.

## 3. Deploy image endpoint (your code)

1. Build + push (from `Acronous Ai/`):
   `docker build -f image-service/Dockerfile.gpu -t <you>/acronous-image-gpu:latest image-service`
   `docker push <you>/acronous-image-gpu:latest`
2. RunPod Serverless → New Endpoint → custom image `<you>/acronous-image-gpu:latest`,
   Start Command `python rp_handler.py`, GPU RTX 4090, Min 0 / Max 2,
   Idle 15s, Execution Timeout 120s. Env `SD_MODEL_ID=stabilityai/sd-turbo`.
3. `npx wrangler secret put GPU_IMAGE_KEY`, var
   `GPU_IMAGE_URL=https://api.runpod.ai/v2/<image-id>`, redeploy Worker.

`rp_handler.py` returns the same `{image_data,...}` shape as `/generate-image`,
so `tryGpuImageGen` needs no other change. Cold start downloads nothing
(weights baked in Dockerfile.gpu).

## 4. Local GPU smoke test (before spending)

Needs one NVIDIA GPU + nvidia-container-toolkit:
`docker compose -f contabo-vps/docker-compose.gpu.yml up --build`
`curl http://localhost:11434/api/tags` and `http://localhost:7860/capabilities`.
Expect qwen2.5:7b ≈ 40-60 tok/s, sd-turbo ≈ 2-5 s/image.

## 5. Kill-switch / rollback

Set `GPU_ENABLED=false` (var) + redeploy → pure Contabo CPU, $0 incremental.
Delete RunPod endpoints → billing stops immediately (serverless has no
always-on charge). Nothing on Contabo changes.
