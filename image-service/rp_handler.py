"""RunPod Serverless handler for Acronous image generation.

Deployed from the Dockerfile.gpu image with START_CMD `python rp_handler.py`.
Request shape (matches what cloudflare-worker.js sends):
    {"input": {"prompt": "...", "width": 1024, "height": 1024, "style": ""}}

Response shape (matches POST /generate-image so the Worker parses unchanged):
    {"image_data": "<b64 png>", "format": "png",
     "width": W, "height": H, "description": "AI-generated image."}

Cold start loads SD-Turbo to CUDA once (~10-20s on 4090, then warm = 2-5s).
No procedural fallback here: on GPU failure we return {"error": ...} and the
Worker falls back to the Contabo CPU box (procedural engine).
"""

import base64
import io
import logging
import os

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("acronous.rp-image")

_pipe = None
_device = "cuda"


def _load_pipe():
    global _pipe
    if _pipe is not None:
        return _pipe
    import torch
    from diffusers import StableDiffusionPipeline, DPMSolverMultistepScheduler

    model_id = os.getenv("SD_MODEL_ID", "stabilityai/sd-turbo")
    log.info("loading %s on %s ...", model_id, _device)
    _pipe = StableDiffusionPipeline.from_pretrained(
        model_id,
        torch_dtype=torch.float16,
        safety_checker=None,
        requires_safety_checker=False,
    )
    _pipe.scheduler = DPMSolverMultistepScheduler.from_config(
        _pipe.scheduler.config
    )
    _pipe = _pipe.to(_device)
    try:
        _pipe.enable_xformers_memory_efficient_attention()
    except Exception as exc:  # xformers optional
        log.warning("xformers not enabled: %s", exc)
    try:
        _pipe.enable_model_cpu_offload()
    except Exception:
        pass
    log.info("SD pipeline ready")
    return _pipe


def _clamp(v, lo, hi, default):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def handler(job):
    """RunPod entry point: job = {"input": {...}}."""
    job_input = (job or {}).get("input", {}) or {}
    prompt = str(job_input.get("prompt", "")).strip()[:2000]
    if not prompt:
        return {"error": "No prompt provided"}
    width = _clamp(job_input.get("width", 1024), 256, 1536, 1024)
    height = _clamp(job_input.get("height", 1024), 256, 1536, 1024)

    try:
        pipe = _load_pipe()
    except Exception as exc:
        log.exception("model load failed")
        return {"error": f"model load failed: {exc}"}

    try:
        # SD-Turbo is a 1-4 step distilled model: 2 steps is the sweet spot.
        image = pipe(
            prompt,
            height=512,
            width=512,
            num_inference_steps=2,
            guidance_scale=0.0,
        ).images[0]
        # Upscale to requested size with the same Lanczos helper as app.py.
        try:
            from app import upscale_image

            target = min(max(max(width, height), 512), 1024)
            while image.width < target or image.height < target:
                image = upscale_image(image, 2)
                if image.width > 2048 or image.height > 2048:
                    break
        except Exception:
            pass
        buf = io.BytesIO()
        image.save(buf, format="PNG", optimize=True)
        return {
            "image_data": base64.b64encode(buf.getvalue()).decode(),
            "format": "png",
            "width": image.width,
            "height": image.height,
            "description": "AI-generated image.",
        }
    except Exception as exc:
        log.exception("generation failed")
        return {"error": f"generation failed: {exc}"}


if __name__ == "__main__":
    import runpod

    runpod.serverless.start({"handler": handler})
