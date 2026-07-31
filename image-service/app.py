"""
Acronous AI — Multimedia Service

Local-first processing on Oracle Cloud (24GB RAM):
- Image Generation: SD models (no external API dependency)
- Image Editing: rembg + Pillow + CLIP + Real-ESRGAN
- Video Generation: moviepy + local SD frames
- Voice TTS: edge-tts (Microsoft Neural TTS, 300+ voices)
- Voice Editing: pydub (trim, speed, volume, fade, reverse)
- Web Search: DuckDuckGo HTML scraping
"""

import io
import os
import re
import json
import base64
import logging
import tempfile
import asyncio as _asyncio
from typing import Optional
from urllib.parse import quote_plus

import numpy as np
import requests
import aiohttp
from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageEnhance, ImageStat

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:4b")
OLLAMA_VISION_MODEL = os.environ.get("OLLAMA_VISION_MODEL", "llava:7b")

async def is_ollama_available(timeout=3):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                return resp.status == 200
    except:
        return False

async def call_ollama(messages, model=None, timeout=30):
    url = f"{OLLAMA_BASE_URL}/api/chat"
    payload = {
        "model": model or OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("message", {}).get("content", "")
    except Exception as e:
        logging.warning(f"Ollama call failed: {e}")
    return ""

async def call_ollama_vision(image_base64, prompt, timeout=60):
    url = f"{OLLAMA_BASE_URL}/api/chat"
    payload = {
        "model": OLLAMA_VISION_MODEL,
        "messages": [
            {"role": "system", "content": "You are an expert image analyst. Describe the image in detail, focusing on elements relevant to the user's request."},
            {"role": "user", "content": prompt, "images": [image_base64]},
        ],
        "stream": False,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("message", {}).get("content", "")
    except Exception as e:
        logging.warning(f"Ollama vision call failed: {e}")
    return ""

app = FastAPI(title="Acronous AI Image Service", version="2.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# REMBG (CPU-based segmentation, always available)
# ---------------------------------------------------------------------------
HAS_REMBG = False
rembg_session = None
rembg_cloth_session = None

try:
    from rembg import remove as rembg_remove, new_session
    rembg_session = new_session("u2net")
    rembg_cloth_session = new_session("u2net_cloth_seg")
    HAS_REMBG = True
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Diffusers / torch (optional GPU)
# ---------------------------------------------------------------------------
import torch
HAS_TORCH_CUDA = False
try:
    HAS_TORCH_CUDA = torch.cuda.is_available()
except Exception:
    pass

# ---------------------------------------------------------------------------
# CLIP Vision (CPU)
# ---------------------------------------------------------------------------
HAS_CLIP = False
clip_model = None
clip_preprocess = None

def _load_clip():
    global clip_model, clip_preprocess, HAS_CLIP
    if clip_model is not None:
        return
    try:
        import open_clip
        clip_model, _, clip_preprocess = open_clip.create_model_and_transforms(
            'ViT-B-32', pretrained='laion2b_s34b_b79k', device='cpu'
        )
        clip_model.eval()
        HAS_CLIP = True
        logging.info("CLIP model loaded successfully")
    except Exception as e:
        logging.warning(f"CLIP load failed: {e}")
        HAS_CLIP = False

def analyze_with_clip(image: Image.Image, candidate_labels: list = None) -> dict:
    """Analyze image using CLIP — zero-shot classification + feature extraction."""
    if not HAS_CLIP:
        _load_clip()
    if not HAS_CLIP or clip_model is None:
        return {"labels": [], "error": "CLIP not available"}
    try:
        import open_clip
        image_input = clip_preprocess(image).unsqueeze(0)
        with torch.no_grad():
            image_features = clip_model.encode_image(image_input)
            image_features = image_features / image_features.norm(dim=-1, keepdim=True)

        if not candidate_labels:
            candidate_labels = [
                "photo", "illustration", "painting", "drawing", "sketch",
                "person", "animal", "landscape", "city", "building",
                "food", "car", "nature", "sky", "water",
                "text", "document", "screenshot", "meme", "logo",
                "indoor", "outdoor", "portrait", "group photo", "selfie",
            ]

        text_inputs = open_clip.tokenize([f"a photo of {l}" for l in candidate_labels])
        with torch.no_grad():
            text_features = clip_model.encode_text(text_inputs)
            text_features = text_features / text_features.norm(dim=-1, keepdim=True)
            similarities = (100.0 * image_features @ text_features.T).softmax(dim=-1)

        scores, indices = similarities[0].topk(min(5, len(candidate_labels)))
        labels = []
        for score, idx in zip(scores.tolist(), indices.tolist()):
            labels.append({"label": candidate_labels[idx], "score": round(score, 4)})
        return {"labels": labels}
    except Exception as e:
        logging.warning(f"CLIP analysis error: {e}")
        return {"labels": [], "error": str(e)}

# ---------------------------------------------------------------------------
# Real-ESRGAN upscaling (CPU)
# ---------------------------------------------------------------------------
HAS_UPSCALER = False
upscaler_model = None

def _load_upscaler():
    global upscaler_model, HAS_UPSCALER
    if upscaler_model is not None:
        return
    try:
        from realesrgan import RealESRGANer
        from basicsr.archs.rrdbnet_arch import RRDBNet
        model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=4)
        # Download weights on first run
        import urllib.request
        weights_url = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth"
        weights_path = "/tmp/RealESRGAN_x4plus.pth"
        if not os.path.exists(weights_path):
            urllib.request.urlretrieve(weights_url, weights_path)
        upscaler_model = RealESRGANer(
            scale=4, model_path=weights_path, model=model,
            tile=256, tile_pad=10, pre_pad=0, half=False,
        )
        HAS_UPSCALER = True
        logging.info("Real-ESRGAN upscaler loaded")
    except Exception as e:
        logging.warning(f"Upscaler load failed: {e}")
        HAS_UPSCALER = False

def upscale_image(image: Image.Image, scale: int = 4) -> Optional[Image.Image]:
    """Upscale image using Real-ESRGAN."""
    if not HAS_UPSCALER:
        _load_upscaler()
    if not HAS_UPSCALER or upscaler_model is None:
        return None
    try:
        import cv2
        img_array = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)
        output, _ = upscaler_model.enhance(img_array, outscale=scale)
        result = cv2.cvtColor(output, cv2.COLOR_BGR2RGB)
        return Image.fromarray(result)
    except Exception as e:
        logging.warning(f"Upscale error: {e}")
        return None

SD_PIPE = None
LOCAL_GEN_PIPE = None
LOCAL_IMG2IMG_PIPE = None

HAS_EDGE_TTS = False
try:
    import edge_tts
    HAS_EDGE_TTS = True
except ImportError:
    pass

HAS_SOUNDFILE = False
try:
    import soundfile as sf
    HAS_SOUNDFILE = True
except ImportError:
    pass

HAS_PYDUB = False
try:
    from pydub import AudioSegment
    HAS_PYDUB = True
except ImportError:
    pass

def _load_sd_pipe():
    global SD_PIPE
    if SD_PIPE is not None:
        return SD_PIPE
    if not HAS_TORCH_CUDA:
        return None
    try:
        from diffusers import StableDiffusionInpaintPipeline
        SD_PIPE = StableDiffusionInpaintPipeline.from_pretrained(
            "stabilityai/stable-diffusion-2-inpainting",
            torch_dtype=torch.float16,
        )
        SD_PIPE = SD_PIPE.to("cuda")
        SD_PIPE.enable_attention_slicing()
        return SD_PIPE
    except Exception as e:
        logging.warning(f"SD init failed: {e}")
        return None

def _load_local_gen_pipe():
    """Load a tiny SD model for CPU text-to-image generation."""
    global LOCAL_GEN_PIPE
    if LOCAL_GEN_PIPE is not None:
        return LOCAL_GEN_PIPE
    try:
        from diffusers import AutoPipelineForText2Image
        # segmind/small-1.0 is ~500MB, works on CPU with 24GB RAM
        # Uses ~4GB RAM during inference, ~30-60s per image on CPU
        LOCAL_GEN_PIPE = AutoPipelineForText2Image.from_pretrained(
            "segmind/small-1.0",
            torch_dtype=torch.float32,
        )
        LOCAL_GEN_PIPE.enable_attention_slicing()
        # NO enable_model_cpu_offload — that requires CUDA, we're CPU-only
        logging.info("Acronous AI local image generation pipeline loaded")
        return LOCAL_GEN_PIPE
    except Exception as e:
        logging.warning(f"Local gen pipeline load failed: {e}")
        # Fallback to even smaller model
        try:
            from diffusers import AutoPipelineForText2Image
            LOCAL_GEN_PIPE = AutoPipelineForText2Image.from_pretrained(
                "segmind/tiny",
                torch_dtype=torch.float32,
            )
            LOCAL_GEN_PIPE.enable_attention_slicing()
            logging.info("Local image generation pipeline loaded (segmind/tiny fallback)")
            return LOCAL_GEN_PIPE
        except Exception as e2:
            logging.warning(f"Local gen pipeline fallback failed: {e2}")
            return None

def _load_local_img2img_pipe():
    """Load SD model for CPU image-to-image editing — preserves original structure."""
    global LOCAL_IMG2IMG_PIPE
    if LOCAL_IMG2IMG_PIPE is not None:
        return LOCAL_IMG2IMG_PIPE
    try:
        from diffusers import AutoPipelineForImage2Image
        LOCAL_IMG2IMG_PIPE = AutoPipelineForImage2Image.from_pretrained(
            "segmind/small-1.0",
            torch_dtype=torch.float32,
        )
        LOCAL_IMG2IMG_PIPE.enable_attention_slicing()
        logging.info("Acronous AI img2img pipeline loaded")
        return LOCAL_IMG2IMG_PIPE
    except Exception as e:
        logging.warning(f"img2img pipeline load failed: {e}")
        return None

def generate_local(prompt: str, width: int = 1024, height: int = 1024) -> Optional[Image.Image]:
    """Generate image locally using tiny SD model on CPU."""
    pipe = _load_local_gen_pipe()
    if pipe is None:
        logging.warning("Local gen pipeline not available — model failed to load")
        return None
    try:
        enhanced = f"{prompt}, photorealistic, high quality, detailed, sharp, well-lit"
        # Use fewer steps on CPU for speed (15 steps instead of 20)
        result = pipe(
            enhanced,
            width=width,
            height=height,
            num_inference_steps=15,
            guidance_scale=7.5,
        )
        return result.images[0].convert("RGB")
    except Exception as e:
        logging.warning(f"Local generation error: {e}")
        return None

# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def img_to_b64(img: Image.Image, fmt: str = "PNG") -> str:
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode()

def b64_to_img(data: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(data)))

def bytes_to_img(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))

def img_to_bytes(img: Image.Image, fmt: str = "JPEG") -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt, quality=92)
    return buf.getvalue()

def resize_max(img: Image.Image, max_sz: int = 1024) -> Image.Image:
    w, h = img.size
    if max(w, h) <= max_sz:
        return img
    ratio = max_sz / max(w, h)
    return img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

# ---------------------------------------------------------------------------
# Segmentation
# ---------------------------------------------------------------------------

def segment_clothing(image: Image.Image) -> Optional[Image.Image]:
    """Extract clothing region mask using rembg cloth model."""
    if not HAS_REMBG or rembg_cloth_session is None:
        return None
    try:
        data = rembg_remove(img_to_bytes(image), session=rembg_cloth_session, only_mask=True)
        mask = Image.open(io.BytesIO(data)).convert("L")
        return mask
    except Exception as e:
        logging.warning(f"Cloth seg failed: {e}")
        return None

def segment_person(image: Image.Image) -> Optional[Image.Image]:
    """Extract person mask."""
    if not HAS_REMBG:
        return None
    try:
        data = rembg_remove(img_to_bytes(image), session=rembg_session, only_mask=True)
        return Image.open(io.BytesIO(data)).convert("L")
    except Exception:
        return None

def segment_foreground(image: Image.Image) -> Optional[Image.Image]:
    """Extract foreground alpha mask."""
    if not HAS_REMBG:
        return None
    try:
        output = rembg_remove(img_to_bytes(image), session=rembg_session)
        result = Image.open(io.BytesIO(output)).convert("RGBA")
        return result.split()[3]
    except Exception:
        return None

def create_upper_body_mask(image: Image.Image) -> Image.Image:
    """
    Create mask for upper-body clothing region.
    Uses person mask + geometric heuristics when cloth model unavailable.
    Returns a mask image.
    """
    mask = segment_clothing(image)
    if mask is not None:
        if mask.size != image.size:
            mask = mask.resize(image.size, Image.NEAREST)
        return mask

    person = segment_person(image) or segment_foreground(image)
    w, h = image.size

    if person is None:
        m = Image.new("L", (w, h), 0)
        y0, y1 = int(h * 0.25), int(h * 0.70)
        x0, x1 = int(w * 0.1), int(w * 0.9)
        ImageDraw.Draw(m).rectangle([x0, y0, x1, y1], fill=255)
        return m.filter(ImageFilter.GaussianBlur(radius=5))

    person_arr = np.array(person)
    cy = int(h * 0.30)
    body_region = np.zeros((h, w), dtype=np.uint8)
    body_region[cy:int(h * 0.75), int(w * 0.08):int(w * 0.92)] = 255
    combined = np.where(person_arr > 128, body_region, 0).astype(np.uint8)
    return Image.fromarray(combined).filter(ImageFilter.GaussianBlur(radius=4))

# ---------------------------------------------------------------------------
# Smart compositing
# ---------------------------------------------------------------------------

def feather_blend(orig: Image.Image, edit: Image.Image, mask: Image.Image, radius: int = 6) -> Image.Image:
    """Blend edited region into original with feathered mask."""
    m = mask.convert("L").resize(orig.size, Image.NEAREST)
    e = edit.resize(orig.size, Image.LANCZOS)
    m = m.filter(ImageFilter.GaussianBlur(radius=radius))
    mf = np.array(m, dtype=np.float32) / 255.0
    oa = np.array(orig, dtype=np.float32)
    ea = np.array(e, dtype=np.float32)
    for c in range(3):
        oa[:, :, c] = oa[:, :, c] * (1 - mf) + ea[:, :, c] * mf
    return Image.fromarray(oa.astype(np.uint8))

def match_color(target: np.ndarray, source: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Match color stats of target to source within mask region."""
    mf = mask.astype(np.float32) / 255.0
    result = target.astype(np.float32)
    for c in range(3):
        t_mean = np.average(target[:, :, c], weights=mf)
        s_mean = np.average(source[:, :, c], weights=mf)
        t_std = np.sqrt(np.average((target[:, :, c] - t_mean) ** 2, weights=mf)) + 1e-6
        s_std = np.sqrt(np.average((source[:, :, c] - s_mean) ** 2, weights=mf)) + 1e-6
        result[:, :, c] = (target[:, :, c] - t_mean) * (s_std / t_std) + s_mean
    return np.clip(result, 0, 255).astype(np.uint8)

# ---------------------------------------------------------------------------
# CPU editing strategies (no GPU needed)
# ---------------------------------------------------------------------------

def apply_color_palette(image: Image.Image, mask: Image.Image, palette: list) -> Image.Image:
    """
    Apply a color palette to the masked region using HSV-based color transfer.
    Preserves luminance/texture of the original — shifts hue toward palette colors.
    palette: list of (r, g, b) tuples defining the target colors.
    """
    if mask is None:
        mask = Image.new("L", image.size, 255)
    elif mask.size != image.size:
        mask = mask.resize(image.size, Image.NEAREST)
    m = np.array(mask.convert("L"), dtype=np.float32) / 255.0
    img = np.array(image.convert("RGB"), dtype=np.float32)

    mask_bool = m > 0.3
    if not np.any(mask_bool):
        return image

    palette_arr = np.array(palette, dtype=np.float32) / 255.0

    # Convert image to HSV
    pixels = img[mask_bool].astype(np.float32) / 255.0
    h, s, v = rgb_to_hsv_vectorized_simple(pixels)

    # Compute target hue from palette (weighted centroid)
    palette_hsv = np.array([rgb_to_hsv_single(*p) for p in palette_arr])
    target_h = np.mean(palette_hsv[:, 0])
    target_s = np.mean(palette_hsv[:, 1])

    # Shift hue toward target (interpolate, don't replace)
    hue_diff = (target_h - h + 0.5) % 1.0 - 0.5
    h_new = (h + hue_diff * 0.6 + 1.0) % 1.0

    # Blend saturation: preserve some original, pull toward target
    s_new = s * 0.3 + target_s * 0.7

    # Reconstruct RGB, then blend with original by mask weight
    edited_pixels = hsv_to_rgb_vectorized_simple(h_new, s_new, v)

    m_vals = m[mask_bool, np.newaxis]
    blended = pixels * (1 - m_vals * 0.75) + edited_pixels * (m_vals * 0.75)

    result = img.copy().astype(np.float32) / 255.0
    result[mask_bool] = blended

    return Image.fromarray((result * 255).astype(np.uint8))

def rgb_to_hsv_vectorized_simple(rgb):
    """Vectorized RGB→HSV for (N,3) arrays. Returns h,s,v each in [0,1]."""
    r, g, b = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    diff = mx - mn + 1e-10
    h = np.zeros_like(mx)
    s = diff / (mx + 1e-10)
    v = mx
    rc = (mx - r) / diff
    gc = (mx - g) / diff
    bc = (mx - b) / diff
    h = np.where(mx == r, (bc - gc) % 6, h)
    h = np.where(mx == g, (rc - bc) + 2, h)
    h = np.where(mx == b, (gc - rc) + 4, h)
    h = h / 6.0
    return h, s, v

def hsv_to_rgb_vectorized_simple(h, s, v):
    """Vectorized HSV→RGB for (N,) arrays. h,s,v each in [0,1]."""
    hi = (h * 6).astype(np.int32) % 6
    f = h * 6 - np.floor(h * 6)
    p = v * (1 - s)
    q = v * (1 - f * s)
    t = v * (1 - (1 - f) * s)
    r = np.zeros_like(v)
    g = np.zeros_like(v)
    b = np.zeros_like(v)
    m0 = hi == 0; r = np.where(m0, v, r); g = np.where(m0, t, g); b = np.where(m0, p, b)
    m1 = hi == 1; r = np.where(m1, q, r); g = np.where(m1, v, g); b = np.where(m1, p, b)
    m2 = hi == 2; r = np.where(m2, p, r); g = np.where(m2, v, g); b = np.where(m2, t, b)
    m3 = hi == 3; r = np.where(m3, p, r); g = np.where(m3, q, g); b = np.where(m3, v, b)
    m4 = hi == 4; r = np.where(m4, t, r); g = np.where(m4, p, g); b = np.where(m4, v, b)
    m5 = hi == 5; r = np.where(m5, v, r); g = np.where(m5, p, g); b = np.where(m5, q, b)
    return np.stack([r, g, b], axis=1)

def rgb_to_hsv_single(r, g, b):
    """Single-pixel RGB→HSV returning h in [0,1], s in [0,1], v in [0,1]."""
    mx = max(r, g, b)
    mn = min(r, g, b)
    diff = mx - mn
    if diff < 1e-8:
        return 0.0, 0.0, mx
    h = 0.0
    if mx == r:
        h = ((g - b) / diff) % 6
    elif mx == g:
        h = (b - r) / diff + 2
    else:
        h = (r - g) / diff + 4
    h = h / 6.0
    s = diff / mx
    return h, s, mx

def rgb_to_hsv_vectorized(rgb):
    """Vectorized RGB to HSV conversion using numpy."""
    r, g, b = rgb[:,:,0], rgb[:,:,1], rgb[:,:,2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    diff = mx - mn

    h = np.zeros_like(mx)
    s = np.where(mx != 0, diff / (mx + 1e-8), 0)
    v = mx

    mask = diff != 0
    if np.any(mask):
        r_mask = mask & (mx == r)
        h[r_mask] = (60 * ((g[r_mask] - b[r_mask]) / diff[r_mask]) + 360) % 360
        g_mask = mask & (mx == g)
        h[g_mask] = (60 * ((b[g_mask] - r[g_mask]) / diff[g_mask]) + 120) % 360
        b_mask = mask & (mx == b)
        h[b_mask] = (60 * ((r[b_mask] - g[b_mask]) / diff[b_mask]) + 240) % 360

    return h, s, v

def hsv_to_rgb_vectorized(h, s, v):
    """Vectorized HSV to RGB conversion using numpy."""
    hi = np.floor(h / 60).astype(np.int32) % 6
    f = h / 60 - np.floor(h / 60)
    p = v * (1 - s)
    q = v * (1 - f * s)
    t = v * (1 - (1 - f) * s)

    r = np.zeros_like(v)
    g = np.zeros_like(v)
    b = np.zeros_like(v)

    m0 = hi == 0; r[m0] = v[m0]; g[m0] = t[m0]; b[m0] = p[m0]
    m1 = hi == 1; r[m1] = q[m1]; g[m1] = v[m1]; b[m1] = p[m1]
    m2 = hi == 2; r[m2] = p[m2]; g[m2] = v[m2]; b[m2] = t[m2]
    m3 = hi == 3; r[m3] = p[m3]; g[m3] = q[m3]; b[m3] = v[m3]
    m4 = hi == 4; r[m4] = t[m4]; g[m4] = p[m4]; b[m4] = v[m4]
    m5 = hi == 5; r[m5] = v[m5]; g[m5] = p[m5]; b[m5] = q[m5]

    return np.stack([r, g, b], axis=2)

def recolor_region(image: Image.Image, mask: Image.Image, target_color: tuple) -> Image.Image:
    """
    Recolor the masked region to target_color while preserving luminance/texture.
    Uses HSV shift so folds, shadows, and highlights remain visible.
    """
    if mask is None:
        mask = Image.new("L", image.size, 255)
    elif mask.size != image.size:
        mask = mask.resize(image.size, Image.NEAREST)

    img = np.array(image.convert("RGB"), dtype=np.float32) / 255.0
    m = np.array(mask.convert("L"), dtype=np.float32) / 255.0

    mask_bool = m > 0.3
    if not np.any(mask_bool):
        return image

    tc = np.array(target_color, dtype=np.float32) / 255.0
    th, ts, tv = rgb_to_hsv_single(tc[0], tc[1], tc[2])

    pixels = img[mask_bool]
    h_pix, s_pix, v_pix = rgb_to_hsv_vectorized_simple(pixels)

    # Keep original luminance (V), shift hue and saturation toward target
    hue_diff = (th - h_pix + 0.5) % 1.0 - 0.5
    h_new = (h_pix + hue_diff + 1.0) % 1.0
    s_new = s_pix * 0.2 + ts * 0.8

    edited_pixels = hsv_to_rgb_vectorized_simple(h_new, s_new, v_pix)

    m_vals = m[mask_bool, np.newaxis]
    blended = pixels * (1 - m_vals * 0.85) + edited_pixels * (m_vals * 0.85)

    result = img.copy()
    result[mask_bool] = blended
    return Image.fromarray((result * 255).astype(np.uint8))

def apply_fabric_texture(image: Image.Image, mask: Image.Image, desc: str) -> Image.Image:
    """
    Simulate fabric texture on the masked region using Pillow filters.
    Different fabric types (wool, silk, cotton, denim) get different textures.
    """
    d = desc.lower()
    m = np.array(mask.convert("L"), dtype=np.float32) / 255.0
    img = np.array(image, dtype=np.float32)

    if "suit" in d or "formal" in d or "tuxedo" in d or "blazer" in d:
        smooth_radius = 1.5
        contrast_boost = 1.15
    elif "denim" in d or "jean" in d:
        smooth_radius = 0.5
        contrast_boost = 1.2
    elif "silk" in d or "satin" in d:
        smooth_radius = 2.0
        contrast_boost = 1.3
    elif "cotton" in d or "casual" in d or "t-shirt" in d:
        smooth_radius = 1.0
        contrast_boost = 1.05
    else:
        smooth_radius = 1.0
        contrast_boost = 1.1

    result = Image.fromarray(img.astype(np.uint8))
    smoothed = result.filter(ImageFilter.GaussianBlur(radius=smooth_radius))
    smoothed = ImageEnhance.Contrast(smoothed).enhance(contrast_boost)
    smoothed = ImageEnhance.Sharpness(smoothed).enhance(1.3)

    blended = feather_blend(result, smoothed, mask, radius=3)
    return blended

def smart_recolor(
    image: Image.Image,
    mask: Image.Image,
    replacement_desc: str,
) -> Optional[Image.Image]:
    """
    Recolor masked region ONLY if an explicit color is mentioned.
    Returns None for non-color prompts (so caller falls through to other strategies).
    """
    desc = replacement_desc.lower().strip()

    color_map = {
        "red": (235, 30, 40), "blue": (25, 65, 240), "green": (25, 215, 50),
        "white": (245, 245, 248), "black": (50, 50, 55), "navy": (35, 40, 160),
        "grey": (175, 175, 180), "gray": (175, 175, 180), "brown": (180, 100, 50),
        "purple": (160, 45, 195), "pink": (235, 100, 140), "yellow": (245, 225, 50),
        "gold": (240, 200, 40), "silver": (215, 215, 225), "orange": (240, 130, 35),
        "teal": (30, 185, 180), "magenta": (220, 35, 160), "cyan": (35, 220, 230),
        "beige": (220, 205, 170), "maroon": (180, 35, 50), "coral": (240, 120, 100),
        "lavender": (205, 160, 235), "mint": (110, 220, 160), "peach": (245, 185, 140),
        "turquoise": (35, 200, 200), "indigo": (70, 30, 170), "violet": (165, 50, 210),
    }
    for name, color in color_map.items():
        if re.search(rf"\b{re.escape(name)}\b", desc):
            return recolor_region(image, mask, color)

    # No explicit color found — return None so caller falls through to other strategies
    return None

# ---------------------------------------------------------------------------
# GPU inpainting (optional)
# ---------------------------------------------------------------------------

def inpaint_sd(image: Image.Image, mask: Image.Image, prompt: str) -> Optional[Image.Image]:
    """Stable Diffusion inpainting (GPU only)."""
    pipe = _load_sd_pipe()
    if pipe is None:
        return None
    try:
        img = resize_max(image, 768)
        m = mask.resize(img.size, Image.NEAREST)
        result = pipe(
            prompt=prompt,
            image=img,
            mask_image=m,
            height=img.height,
            width=img.width,
            num_inference_steps=25,
            guidance_scale=7.0,
        ).images[0]
        return result
    except Exception as e:
        logging.warning(f"SD inpaint error: {e}")
        return None

# ---------------------------------------------------------------------------
# Prompt interpreter
# ---------------------------------------------------------------------------

def interpret_prompt(prompt: str) -> dict:
    """Parse natural language edit prompt into structured edit command."""
    p = prompt.lower().strip()

    # Detect edit targets
    targets = {
        "dress": ["dress", "gown", "frock"],
        "shirt": ["shirt", "t-shirt", "tee", "top"],
        "pants": ["pants", "jeans", "trousers", "shorts"],
        "outfit": ["outfit", "clothes", "clothing", "attire", "wear", "garment"],
        "background": ["background", "bg", "backdrop", "scene", "setting"],
        "hair": ["hair", "hairstyle"],
        "face": ["face", "skin", "complexion"],
    }

    target = "auto"
    for t, keywords in targets.items():
        if any(k in p for k in keywords):
            target = t
            break

    # Detect lighting/brightness adjustments
    lighting_kw = ["brightness", "brighten", "brighter", "darken", "darker", "lighten", "lighter",
                   "contrast", "exposure", "illuminate", "dim", "shine", "glow", "shadow"]
    if any(w in p for w in lighting_kw):
        action = "adjust_lighting"
    # Detect background changes
    elif target == "background" and any(w in p for w in ["change", "replace", "remove", "erase", "delete", "edit", "set", "put"]):
        action = "change_background"
    # Detect replace actions (clothing transformation)
    elif any(w in p for w in ["replace", "change to", "switch", "turn into", "convert to",
                               "change into", "transform", "turn to"]):
        action = "replace"
    elif any(w in p for w in ["remove", "delete", "erase", "take off", "cut out"]):
        action = "remove"
    elif any(w in p for w in ["add", "put", "insert", "place"]):
        action = "add"
    elif any(w in p for w in ["color", "recolor", "paint", "colour"]):
        action = "recolor"
    else:
        action = "edit"

    # Extract replacement description
    replacement = prompt
    for prefix in [
        r"(?:replace|change|switch|turn|convert|transform)\s+(?:the\s+|my\s+|this\s+|that\s+|his\s+|her\s+)?(?:\w+\s+)?(?:into|to|with)\s+",
        r"(?:make\s+(?:it|this|the|that|my|his|her)\s+)(?:\w+\s+)?",
        r"(?:edit\s+(?:the\s+|my\s+|this\s+|that\s+)?(?:\w+\s+)?(?:to\s+)?)",
        r"(?:recolor|colour|color)\s+(?:the\s+|this\s+|that\s+|my\s+|his\s+|her\s+)?(?:\w+\s+)?(?:to\s+)?",
        r"(?:paint)\s+(?:the\s+|this\s+|that\s+|my\s+)?(?:\w+\s+)?",
    ]:
        m = re.search(prefix + r"(.+)", p, re.IGNORECASE)
        if m:
            replacement = m.group(1).strip()
            if replacement.endswith("."):
                replacement = replacement[:-1]
            break

    return {"target": target, "action": action, "replacement": replacement}

# ---------------------------------------------------------------------------
# Main editing pipeline
# ---------------------------------------------------------------------------

def edit_image(image_bytes: bytes, prompt: str) -> dict:
    """Run full editing pipeline: interpret -> segment -> edit -> return."""
    image = bytes_to_img(image_bytes).convert("RGB")
    orig = image.copy()
    info = interpret_prompt(prompt)
    p_lower = prompt.lower().strip()
    logging.info(f"Edit info: {info}")

    # Create mask for the target region
    tgt = info["target"]
    mask = None

    if tgt == "background":
        fg = segment_foreground(image)
        if fg is not None:
            mask = ImageOps.invert(fg)
    elif tgt in ("dress", "shirt", "pants", "outfit", "auto"):
        mask = create_upper_body_mask(image)
    else:
        mask = create_upper_body_mask(image)

    if mask is not None:
        m_arr = np.array(mask)
        if np.max(m_arr) < 10:
            mask = None

    result = None
    strategy = "none"

    # ── Brightness / Lighting Adjustments ──
    if info["action"] == "adjust_lighting":
        result = image.copy()
        if any(w in p_lower for w in ["brighten", "brighter", "lighten", "lighter", "brightness", "shine", "glow", "illuminate"]):
            factor = 1.3
            if "a lot" in p_lower or "very" in p_lower:
                factor = 1.6
            elif "little" in p_lower or "slightly" in p_lower or "bit" in p_lower:
                factor = 1.15
            result = ImageEnhance.Brightness(result).enhance(factor)
            strategy = "brighten"
        if any(w in p_lower for w in ["darken", "darker", "dim"]):
            factor = 0.7
            if "a lot" in p_lower or "very" in p_lower:
                factor = 0.5
            elif "little" in p_lower or "slightly" in p_lower or "bit" in p_lower:
                factor = 0.85
            result = ImageEnhance.Brightness(result).enhance(factor)
            strategy = "darken"
        if "contrast" in p_lower:
            factor = 1.3
            if "less" in p_lower or "lower" in p_lower:
                factor = 0.7
            result = ImageEnhance.Contrast(result).enhance(factor)
            strategy = "contrast"
        # Blend with mask if we have one (only affect masked region)
        if mask is not None and strategy != "none":
            result = feather_blend(orig, result, mask, radius=6)
        else:
            result = feather_blend(orig, result, Image.new("L", image.size, 255), radius=0)
        edited_bytes = img_to_bytes(result)
        mask_bytes = img_to_bytes(mask, "PNG") if mask else b""
        return {
            "edited": base64.b64encode(edited_bytes).decode(),
            "mask": base64.b64encode(mask_bytes).decode() if mask_bytes else "",
            "strategy": strategy,
            "interpretation": info,
            "width": result.width,
            "height": result.height,
        }

    # ── Background Changes ──
    if info["action"] == "change_background":
        # Remove background: make background transparent/white
        if any(w in p_lower for w in ["remove", "erase", "delete", "cut", "transparent"]):
            if HAS_REMBG:
                data = rembg_remove(img_to_bytes(image), session=rembg_session)
                result = Image.open(io.BytesIO(data)).convert("RGBA")
                strategy = "remove_bg"
                edited_bytes = img_to_bytes(result, "PNG")
                return {
                    "edited": base64.b64encode(edited_bytes).decode(),
                    "mask": "",
                    "strategy": strategy,
                    "interpretation": info,
                    "width": result.width,
                    "height": result.height,
                }
        # Change background: recolor the background area
        if mask is not None:
            result = smart_recolor(image, mask, info["replacement"])
            strategy = "change_background"
            result = ImageEnhance.Sharpness(result).enhance(1.2)
            edited_bytes = img_to_bytes(result)
            mask_bytes = img_to_bytes(mask, "PNG") if mask else b""
            return {
                "edited": base64.b64encode(edited_bytes).decode(),
                "mask": base64.b64encode(mask_bytes).decode() if mask_bytes else "",
                "strategy": strategy,
                "interpretation": info,
                "width": result.width,
                "height": result.height,
            }

    # ── Removals ──
    if info["action"] == "remove" and mask is not None:
        # Fill masked region with surrounding content (blur/heal approximation)
        result = image.copy()
        m = mask.convert("L").filter(ImageFilter.GaussianBlur(radius=15))
        # Inpaint by blurring the masked region
        blurred = result.filter(ImageFilter.GaussianBlur(radius=20))
        result = feather_blend(result, blurred, m, radius=10)
        strategy = "remove"
        edited_bytes = img_to_bytes(result)
        mask_bytes = img_to_bytes(mask, "PNG") if mask else b""
        return {
            "edited": base64.b64encode(edited_bytes).decode(),
            "mask": base64.b64encode(mask_bytes).decode() if mask_bytes else "",
            "strategy": strategy,
            "interpretation": info,
            "width": result.width,
            "height": result.height,
        }

    # ── Clothing / Object Recolor or Replace ──
    # Strategy 1: GPU inpainting (best quality, requires CUDA)
    if result is None and HAS_TORCH_CUDA and mask is not None:
        sd_prompt = f"A {info['replacement']}, high quality, detailed, realistic"
        inpainted = inpaint_sd(image, mask, sd_prompt)
        if inpainted is not None:
            result = feather_blend(image, inpainted, mask, radius=8)
            strategy = "sd_inpaint"

    # Strategy 2: Pillow recolor — only edit the masked region, leave everything else untouched
    if result is None and mask is not None:
        if info["action"] in ("replace", "recolor", "edit", "add"):
            result = smart_recolor(image, mask, info["replacement"])
            if result is not None:
                strategy = "smart_recolor"
                edited_bytes = img_to_bytes(result)
                mask_bytes = img_to_bytes(mask, "PNG") if mask else b""
                return {
                    "edited": base64.b64encode(edited_bytes).decode(),
                    "mask": base64.b64encode(mask_bytes).decode() if mask_bytes else "",
                    "strategy": strategy,
                    "interpretation": info,
                    "width": result.width,
                    "height": result.height,
                }

    # If nothing could be done, return original image unchanged (worker will detect via isImageUnchanged)
    if result is None:
        edited_bytes = img_to_bytes(orig)
        return {
            "edited": base64.b64encode(edited_bytes).decode(),
            "mask": "",
            "strategy": "unchanged",
            "interpretation": info,
            "width": orig.width,
            "height": orig.height,
        }

# ---------------------------------------------------------------------------
# Web Search (free, unlimited via DuckDuckGo HTML scraping)
# ---------------------------------------------------------------------------

SEARCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "DNT": "1",
}

def search_duckduckgo(query: str, max_results: int = 5) -> str:
    """Scrape DuckDuckGo HTML search results — free, unlimited, no API key needed."""
    try:
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        resp = requests.get(url, headers=SEARCH_HEADERS, timeout=15)
        if resp.status_code != 200:
            return ""

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []

        for result in soup.select(".result")[:max_results]:
            title_el = result.select_one(".result__title a")
            snippet_el = result.select_one(".result__snippet")

            title = title_el.get_text(strip=True) if title_el else ""
            link = title_el.get("href", "") if title_el else ""
            # DuckDuckGo wraps links in redirect
            if "uddg=" in link:
                from urllib.parse import parse_qs, urlparse
                parsed = urlparse(link)
                qs = parse_qs(parsed.query)
                link = qs.get("uddg", [""])[0]
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""

            if title:
                results.append(f"- {title}: {snippet}" if snippet else f"- {title}")

        return "\n".join(results) if results else ""
    except Exception as e:
        logging.warning(f"Python search error: {e}")
        return ""

def search_google(query: str, max_results: int = 5) -> str:
    """Scrape Google search results as fallback."""
    try:
        url = f"https://www.google.com/search?q={quote_plus(query)}&hl=en"
        resp = requests.get(url, headers=SEARCH_HEADERS, timeout=10)
        if resp.status_code != 200:
            return ""

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []

        for g in soup.select("div.g")[:max_results]:
            title_el = g.select_one("h3")
            snippet_el = g.select_one("div[data-sncf], span.aCOpRe, div.VwiC3b")
            title = title_el.get_text(strip=True) if title_el else ""
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""
            if title:
                results.append(f"- {title}: {snippet}" if snippet else f"- {title}")

        return "\n".join(results) if results else ""
    except Exception as e:
        logging.warning(f"Google search error: {e}")
        return ""

def search_wikipedia(query: str, max_results: int = 3) -> str:
    """Search Wikipedia via its API."""
    try:
        url = "https://en.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "format": "json",
            "srlimit": max_results,
            "srprop": "snippet",
        }
        resp = requests.get(url, params=params, headers=SEARCH_HEADERS, timeout=10)
        if resp.status_code != 200:
            return ""
        data = resp.json()
        results = []
        for r in data.get("query", {}).get("search", []):
            title = r.get("title", "")
            snippet = re.sub(r"<[^>]+>", "", r.get("snippet", ""))
            if title:
                results.append(f"- {title}: {snippet}" if snippet else f"- {title}")
        return "\n".join(results) if results else ""
    except Exception as e:
        logging.warning(f"Wikipedia search error: {e}")
        return ""

@app.get("/search")
async def api_search(
    q: str = Query(..., description="Search query"),
    max_results: int = Query(5, description="Maximum results"),
):
    """Unlimited free web search via DuckDuckGo HTML scraping + fallbacks."""
    # Try primary engines in parallel
    import asyncio
    loop = asyncio.get_event_loop()
    ddg = await loop.run_in_executor(None, search_duckduckgo, q, max_results)
    if ddg:
        return {"query": q, "results": ddg, "source": "duckduckgo"}

    wiki = await loop.run_in_executor(None, search_wikipedia, q, max_results)
    if wiki:
        return {"query": q, "results": wiki, "source": "wikipedia"}

    google = await loop.run_in_executor(None, search_google, q, max_results)
    if google:
        return {"query": q, "results": google, "source": "google"}

    return {"query": q, "results": "", "source": "none"}

# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "acronous-image-service",
        "rembg": HAS_REMBG,
        "gpu": HAS_TORCH_CUDA,
        "clip": HAS_CLIP,
        "upscaler": HAS_UPSCALER,
        "voice_tts": HAS_EDGE_TTS,
        "voice_edit": HAS_PYDUB,
    }

@app.post("/edit")
async def api_edit(
    file: UploadFile = File(...),
    prompt: str = Form(...),
):
    """Edit image using natural language prompt."""
    data = await file.read()
    if not data:
        raise HTTPException(400, "No image data")
    if not prompt.strip():
        raise HTTPException(400, "No prompt")
    return edit_image(data, prompt)

@app.post("/edit-json")
async def api_edit_json(body: dict):
    """Edit image using JSON body (base64 image + prompt)."""
    image_b64 = body.get("image", "")
    prompt = body.get("prompt", "")
    if not image_b64:
        raise HTTPException(400, "No image data")
    if not prompt.strip():
        raise HTTPException(400, "No prompt")
    try:
        data = base64.b64decode(image_b64)
    except Exception:
        raise HTTPException(400, "Invalid base64 image")
    return edit_image(data, prompt)

@app.post("/vision/edit")
async def api_vision_edit(
    file: UploadFile = File(...),
    prompt: str = Form(...),
):
    """
    Ollama vision-guided image editing.
    Uses LLaVA to analyze the image and generate structured edit instructions,
    then applies enhanced Pillow-based edits.
    """
    data = await file.read()
    if not data:
        raise HTTPException(400, "No image data")
    if not prompt.strip():
        raise HTTPException(400, "No prompt")

    image = bytes_to_img(data).convert("RGB")
    image_b64 = img_to_b64(image, "JPEG")

    loop = _asyncio.get_event_loop()

    edit_params = {"target": "auto", "colors": None, "style_keywords": "", "texture_type": "smooth"}

    # Step 1: Quick Ollama health check — skip vision analysis if unavailable
    ollama_ok = await is_ollama_available(timeout=3)
    if ollama_ok:
        vision_prompt = (
            f"You are an image editing assistant. Analyze this image and the edit request below. "
            f"Return a JSON object with these fields:\n"
            f"- 'target': one of 'clothing','background','face','hair','color','object','auto'\n"
            f"- 'colors': a list of 3-4 RGB color tuples (0-255) that best match the desired style\n"
            f"- 'style_keywords': comma-separated style descriptors (e.g. 'formal, dark, classic')\n"
            f"- 'texture_type': one of 'suit','silk','cotton','denim','casual','smooth'\n"
            f"Edit request: {prompt}\n\n"
            f"Respond with ONLY valid JSON, no other text."
        )
        vision_result = await call_ollama_vision(image_b64, vision_prompt, timeout=30)

        # Parse JSON from vision result
        try:
            json_match = re.search(r"\{[\s\S]*\}", vision_result)
            if json_match:
                parsed = json.loads(json_match.group())
                if isinstance(parsed, dict):
                    edit_params.update(parsed)
        except (json.JSONDecodeError, Exception):
            pass

    # Step 2: Create mask based on detected target
    tgt = edit_params.get("target", "auto")
    mask = None
    if tgt == "background":
        fg = segment_foreground(image)
        if fg is not None:
            mask = ImageOps.invert(fg)
    elif tgt in ("clothing", "dress", "shirt", "pants", "outfit", "auto"):
        mask = create_upper_body_mask(image)
    elif tgt in ("face", "hair"):
        mask = create_upper_body_mask(image)
    else:
        mask = create_upper_body_mask(image)

    if mask is not None:
        m_arr = np.array(mask)
        if np.max(m_arr) < 10:
            mask = None

    # Step 3: Apply enhanced Pillow editing
    result = None
    if mask is not None:
        colors = edit_params.get("colors")
        if colors and isinstance(colors, list) and len(colors) >= 3:
            palette = [tuple(c) for c in colors[:4]]
            result = apply_color_palette(image, mask, palette)
        else:
            result = smart_recolor(image, mask, prompt)

        if result is not None:
            texture = edit_params.get("texture_type", "smooth")
            result = apply_fabric_texture(result, mask, texture)
            result = ImageEnhance.Sharpness(result).enhance(1.2)
            result = ImageEnhance.Contrast(result).enhance(1.06)

    # Step 4: Fall back to regular edit
    if result is None:
        return edit_image(data, prompt)

    edited_bytes = img_to_bytes(result)
    mask_bytes = img_to_bytes(mask, "PNG") if mask else b""
    return {
        "edited": base64.b64encode(edited_bytes).decode(),
        "mask": base64.b64encode(mask_bytes).decode() if mask_bytes else "",
        "strategy": "vision_pillow",
        "width": result.width,
        "height": result.height,
    }

@app.post("/vision/edit-json")
async def api_vision_edit_json(body: dict):
    """Vision-guided edit using JSON body (base64 image + prompt)."""
    image_b64 = body.get("image", "")
    prompt = body.get("prompt", "")
    if not image_b64:
        raise HTTPException(400, "No image data")
    if not prompt.strip():
        raise HTTPException(400, "No prompt")
    try:
        data = base64.b64decode(image_b64)
    except Exception:
        raise HTTPException(400, "Invalid base64 image")

    image = bytes_to_img(data).convert("RGB")
    image_b64 = img_to_b64(image, "JPEG")

    loop = _asyncio.get_event_loop()
    edit_params = {"target": "auto", "colors": None, "style_keywords": "", "texture_type": "smooth"}
    ollama_ok = await is_ollama_available(timeout=3)
    if ollama_ok:
        vision_prompt = (
            f"You are an image editing assistant. Analyze this image and the edit request below. "
            f"Return a JSON object with these fields:\n"
            f"- 'target': one of 'clothing','background','face','hair','color','object','auto'\n"
            f"- 'colors': a list of 3-4 RGB color tuples (0-255) that best match the desired style\n"
            f"- 'style_keywords': comma-separated style descriptors (e.g. 'formal, dark, classic')\n"
            f"- 'texture_type': one of 'suit','silk','cotton','denim','casual','smooth'\n"
            f"Edit request: {prompt}\n\n"
            f"Respond with ONLY valid JSON, no other text."
        )
        vision_result = await call_ollama_vision(image_b64, vision_prompt, timeout=30)
        try:
            json_match = re.search(r"\{[\s\S]*\}", vision_result)
            if json_match:
                parsed = json.loads(json_match.group())
                if isinstance(parsed, dict):
                    edit_params.update(parsed)
        except (json.JSONDecodeError, Exception):
            pass

    tgt = edit_params.get("target", "auto")
    mask = None
    if tgt == "background":
        fg = segment_foreground(image)
        if fg is not None:
            mask = ImageOps.invert(fg)
    elif tgt in ("clothing", "dress", "shirt", "pants", "outfit", "auto"):
        mask = create_upper_body_mask(image)
    elif tgt in ("face", "hair"):
        mask = create_upper_body_mask(image)
    else:
        mask = create_upper_body_mask(image)

    if mask is not None:
        m_arr = np.array(mask)
        if np.max(m_arr) < 10:
            mask = None

    result = None
    if mask is not None:
        colors = edit_params.get("colors")
        if colors and isinstance(colors, list) and len(colors) >= 3:
            palette = [tuple(c) for c in colors[:4]]
            result = apply_color_palette(image, mask, palette)
        else:
            result = smart_recolor(image, mask, prompt)

        if result is not None:
            texture = edit_params.get("texture_type", "smooth")
            result = apply_fabric_texture(result, mask, texture)
            result = ImageEnhance.Sharpness(result).enhance(1.2)
            result = ImageEnhance.Contrast(result).enhance(1.06)

    if result is None:
        return edit_image(data, prompt)

    edited_bytes = img_to_bytes(result)
    mask_bytes = img_to_bytes(mask, "PNG") if mask else b""
    return {
        "edited": base64.b64encode(edited_bytes).decode(),
        "mask": base64.b64encode(mask_bytes).decode() if mask_bytes else "",
        "strategy": "vision_pillow_json",
        "width": result.width,
        "height": result.height,
    }

# ---------------------------------------------------------------------------
# Photorealistic Image Generation — local SD + post-processing
# ---------------------------------------------------------------------------

def enhance_photorealistic(image: Image.Image) -> Image.Image:
    """
    Apply photorealistic post-processing to a generated image.
    Makes AI-generated images look more like real photos.
    """
    img = image.copy()

    # 1. Subtle noise reduction (remove AI artifacts)
    img = img.filter(ImageFilter.GaussianBlur(radius=0.5))

    # 2. Unsharp mask — sharpen edges while keeping natural look
    img = ImageEnhance.Sharpness(img).enhance(1.3)

    # 3. Slight contrast boost for depth
    img = ImageEnhance.Contrast(img).enhance(1.08)

    # 4. Color vibrancy — make colors pop without oversaturation
    img = ImageEnhance.Color(img).enhance(1.05)

    # 5. Subtle brightness adjustment for natural lighting
    img = ImageEnhance.Brightness(img).enhance(1.02)

    # 6. Apply slight film grain for photo-realism
    img_arr = np.array(img, dtype=np.float32)
    noise = np.random.normal(0, 2.5, img_arr.shape).astype(np.float32)
    img_arr = np.clip(img_arr + noise, 0, 255).astype(np.uint8)
    img = Image.fromarray(img_arr)

    return img

@app.post("/generate")
async def api_generate(
    prompt: str = Form(...),
    width: int = Form(1024),
    height: int = Form(1024),
    enhance: bool = Form(True),
):
    """
    Generate a photorealistic image from a text prompt.
    Uses local SD model + Pillow post-processing for realism.
    """
    if not prompt.strip():
        raise HTTPException(400, "No prompt provided")

    # Clamp dimensions
    width = max(256, min(width, 2048))
    height = max(256, min(height, 2048))

    import asyncio
    loop = asyncio.get_event_loop()

    # Local generation using tiny SD model (no API dependency)
    image = await loop.run_in_executor(None, generate_local, prompt, width, height)

    if image is None:
        raise HTTPException(500, "Image generation failed — local model error")

    # Resize to requested dimensions
    if image.size != (width, height):
        image = image.resize((width, height), Image.LANCZOS)

    # Post-process for photorealism
    if enhance:
        image = await loop.run_in_executor(None, enhance_photorealistic, image)

    # Try Real-ESRGAN upscaling if available and image is small
    if HAS_UPSCALER and max(width, height) < 1024:
        upscaled = await loop.run_in_executor(None, upscale_image, image, 2)
        if upscaled is not None:
            image = upscaled

    return {
        "edited": img_to_b64(image, "PNG"),
        "width": image.width,
        "height": image.height,
        "strategy": "local sd + photorealistic enhance",
    }

@app.post("/segment")
async def api_segment(
    file: UploadFile = File(...),
    target: str = Form("clothing"),
):
    """Return segmentation mask."""
    data = await file.read()
    img = bytes_to_img(data).convert("RGB")
    if target == "clothing":
        mask = create_upper_body_mask(img)
    elif target == "person":
        mask = segment_person(img)
    elif target == "foreground":
        mask = segment_foreground(img)
    else:
        mask = create_upper_body_mask(img)
    if mask is None:
        raise HTTPException(500, "Segmentation failed")
    mask_raw = base64.b64encode(np.array(mask).tobytes()).decode()
    return {"mask": img_to_b64(mask, "PNG"), "mask_raw": mask_raw, "width": img.width, "height": img.height}

@app.post("/remove-bg")
async def api_remove_bg(file: UploadFile = File(...)):
    if not HAS_REMBG:
        raise HTTPException(500, "rembg not available")
    data = await file.read()
    out = rembg_remove(data, session=rembg_session)
    return {"edited": base64.b64encode(out).decode()}

@app.post("/analyze")
async def api_analyze(
    file: UploadFile = File(...),
    labels: str = Query(None, description="Comma-separated candidate labels (optional)"),
):
    """Analyze image using CLIP vision — returns labels with confidence scores."""
    data = await file.read()
    img = bytes_to_img(data).convert("RGB")
    candidate_labels = [l.strip() for l in labels.split(",")] if labels else None
    result = analyze_with_clip(img, candidate_labels)
    return result

@app.post("/upscale")
async def api_upscale(
    file: UploadFile = File(...),
    scale: int = Query(4, description="Upscale factor (2 or 4)"),
):
    """Upscale image using Real-ESRGAN."""
    data = await file.read()
    img = bytes_to_img(data).convert("RGB")
    scale = max(2, min(scale, 4))
    result = upscale_image(img, scale)
    if result is None:
        raise HTTPException(500, "Upscaling failed — model not loaded or error occurred")
    return {
        "edited": img_to_b64(result, "PNG"),
        "width": result.width,
        "height": result.height,
        "scale": scale,
    }

@app.get("/capabilities")
async def capabilities():
    """Return available capabilities."""
    return {
        "rembg": HAS_REMBG,
        "gpu": HAS_TORCH_CUDA,
        "clip": HAS_CLIP,
        "upscaler": HAS_UPSCALER,
        "video": True,
        "voice_tts": HAS_EDGE_TTS,
        "voice_edit": HAS_PYDUB,
        "image_gen": True,
    }

# ---------------------------------------------------------------------------
# Video Generation — moviepy + local SD frames
# ---------------------------------------------------------------------------

HAS_MOVIEPY = False
try:
    from moviepy.editor import ImageClip, concatenate_videoclips
    HAS_MOVIEPY = True
except ImportError:
    try:
        from moviepy import ImageClip, concatenate_videoclips
        HAS_MOVIEPY = True
    except ImportError:
        pass

def generate_video_frames(prompt: str, num_frames: int = 4) -> list:
    """Generate multiple image frames from a prompt with slight variations using local SD model."""
    frames = []
    # Fewer, simpler variations for CPU speed
    variations = [
        f"{prompt}, photorealistic, high quality, detailed, sharp, well-lit",
        f"{prompt}, slightly different angle, cinematic, golden hour lighting",
        f"{prompt}, different warm lighting, atmospheric, photorealistic",
        f"{prompt}, close-up detail shot, professional photography, shallow depth of field",
        f"{prompt}, wide angle, dramatic sky, epic composition",
        f"{prompt}, soft natural lighting, intimate mood",
        f"{prompt}, backlit, lens flare, ethereal atmosphere",
        f"{prompt}, overhead view, geometric composition, striking perspective",
    ]
    # Limit to 4 frames max on CPU for reasonable generation time
    num_frames = min(num_frames, 4)
    for i, var in enumerate(variations[:num_frames]):
        try:
            # Use smaller resolution for video frames (512x512) for speed
            img = generate_local(var, width=512, height=512)
            if img is not None:
                img = enhance_photorealistic(img)
                frames.append(img)
            else:
                logging.warning(f"Frame {i} local generation returned None")
        except Exception as e:
            logging.warning(f"Frame {i} generation error: {e}")
    return frames

def frames_to_video(frames: list, fps: int = 2, duration: float = 2.0) -> bytes:
    """Convert PIL images to MP4 video using moviepy."""
    if not HAS_MOVIEPY:
        raise RuntimeError("moviepy not available")
    clips = []
    for frame in frames:
        arr = np.array(frame)
        clip = ImageClip(arr).set_duration(duration)
        clips.append(clip)
    if len(clips) < 2:
        # Duplicate single frame for minimum viable video
        clips.append(clips[0].set_duration(duration))
    video = concatenate_videoclips(clips, method="compose")
    buf = io.BytesIO()
    video.write_videofile(buf, fps=fps, codec="libx264", audio=False, logger=None)
    video.close()
    for clip in clips:
        clip.close()
    buf.seek(0)
    return buf.getvalue()

@app.post("/generate-video")
async def api_generate_video(
    prompt: str = Form(...),
    num_frames: int = Form(4),
    frame_duration: float = Form(2.0),
    fps: int = Form(2),
):
    """
    Generate a video from a text prompt.
    Creates multiple AI-generated frames and stitches them into an MP4.
    """
    if not HAS_MOVIEPY:
        raise HTTPException(500, "moviepy not installed — video generation unavailable")
    if not prompt.strip():
        raise HTTPException(400, "No prompt provided")

    num_frames = max(2, min(num_frames, 8))
    fps = max(1, min(fps, 4))
    frame_duration = max(1.0, min(frame_duration, 5.0))

    import asyncio
    loop = asyncio.get_event_loop()
    frames = await loop.run_in_executor(None, generate_video_frames, prompt, num_frames)

    if len(frames) < 2:
        raise HTTPException(500, "Could not generate enough frames for video")

    try:
        video_bytes = await loop.run_in_executor(
            None, frames_to_video, frames, fps, frame_duration
        )
        video_b64 = base64.b64encode(video_bytes).decode()
        return {
            "video_data": video_b64,
            "frame_count": len(frames),
            "fps": fps,
            "duration": len(frames) * frame_duration,
        }
    except Exception as e:
        logging.error(f"Video creation error: {e}")
        raise HTTPException(500, f"Video creation failed: {str(e)}")

# ---------------------------------------------------------------------------
# Voice Services — TTS + Voice Editing
# ---------------------------------------------------------------------------

@app.post("/tts")
async def api_tts(
    text: str = Form(...),
    voice: str = Form("en-US-AriaNeural"),
    rate: str = Form("+0%"),
    pitch: str = Form("+0Hz"),
):
    """Generate speech from text using edge-tts (Microsoft Neural TTS)."""
    if not HAS_EDGE_TTS:
        raise HTTPException(500, "edge-tts not available")
    if not text.strip():
        raise HTTPException(400, "No text provided")
    try:
        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        tmp_path = os.path.join(tempfile.gettempdir(), f"tts_{os.getpid()}.mp3")
        await communicate.save(tmp_path)
        with open(tmp_path, "rb") as f:
            audio_bytes = f.read()
        os.remove(tmp_path)
        return {
            "audio_data": base64.b64encode(audio_bytes).decode(),
            "format": "mp3",
            "voice": voice,
            "text": text,
        }
    except Exception as e:
        logging.error(f"TTS error: {e}")
        raise HTTPException(500, f"TTS failed: {str(e)}")

@app.get("/voices")
async def api_voices():
    """List available TTS voices."""
    if not HAS_EDGE_TTS:
        return {"voices": [], "error": "edge-tts not available"}
    try:
        voices = await edge_tts.list_voices()
        return {"voices": voices}
    except Exception as e:
        return {"voices": [], "error": str(e)}

@app.get("/tts/voices")
async def api_tts_voices():
    return await api_voices()

@app.post("/voice/edit")
async def api_voice_edit(
    file: UploadFile = File(...),
    action: str = Form("trim"),
    start_ms: int = Form(0),
    end_ms: int = Form(-1),
    speed: float = Form(1.0),
    pitch_shift: float = Form(0),
    volume: float = Form(1.0),
    fade_in: int = Form(0),
    fade_out: int = Form(0),
):
    """Edit audio: trim, speed change, pitch shift, volume, fade."""
    data = await file.read()
    if not data:
        raise HTTPException(400, "No audio data")
    if not HAS_PYDUB:
        raise HTTPException(500, "pydub not available")
    try:
        audio = AudioSegment.from_file(io.BytesIO(data))
        if action == "trim":
            if end_ms == -1:
                end_ms = len(audio)
            audio = audio[start_ms:end_ms]
        elif action == "speed":
            new_frame_rate = int(audio.frame_rate * speed)
            audio = audio._spawn(audio.raw_data, overrides={"frame_rate": new_frame_rate}).set_frame_rate(audio.frame_rate)
        elif action == "volume":
            audio = audio + (20 * (volume - 1.0))  # dB change
        elif action == "fade":
            if fade_in > 0:
                audio = audio.fade_in(fade_in)
            if fade_out > 0:
                audio = audio.fade_out(fade_out)
        elif action == "reverse":
            audio = audio.reverse()
        elif action == "normalize":
            audio = audio.apply_gain(-audio.max_dBFS)
        buf = io.BytesIO()
        audio.export(buf, format="mp3", bitrate="192k")
        buf.seek(0)
        return {
            "audio_data": base64.b64encode(buf.getvalue()).decode(),
            "format": "mp3",
            "duration_ms": len(audio),
            "action": action,
        }
    except Exception as e:
        logging.error(f"Voice edit error: {e}")
        raise HTTPException(500, f"Voice edit failed: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 7860))
    uvicorn.run(app, host="0.0.0.0", port=port)
