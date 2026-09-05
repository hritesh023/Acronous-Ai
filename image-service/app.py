"""
Acronous AI — Multimedia Service

Fully self-hosted processing on Oracle Cloud (24GB RAM). No external model
services, no HuggingFace, no rate-limited APIs — every output is produced by
deterministic local processing or the self-hosted Ollama server:
- Image Editing: rembg + Pillow + OpenCV (recolor, content-aware removal,
  background removal / named-color replacement / supplied-image composite)
- Image Analysis: Ollama LLaVA (self-hosted vision)
- Upscaling: Pillow Lanczos
- Voice TTS: edge-tts (Microsoft Neural TTS, 300+ voices)
- Voice Editing: pydub (trim, speed, volume, fade, reverse)
- Web Search: DuckDuckGo HTML scraping
- Image Generation: self-hosted procedural scene engine (prompt → layered
  artwork, deterministic per prompt)
- Video Generation: multi-shot scene synthesis + Ken Burns + edge-tts narration

Generative output is produced entirely by local processing — no external
model services are involved.
"""

import io
import os
import re
import json
import base64
import shutil
import functools
import logging
import tempfile
import asyncio as _asyncio
from typing import Optional, List
from urllib.parse import quote_plus

import numpy as np
import requests
import aiohttp
from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageEnhance, ImageStat, ImageFont

# Local diffusion model (free, UNLIMITED, runs on CPU) — optional dependency.
# When torch+diffusers are installed this becomes the primary image generator,
# replacing the procedural scene engine. No external/rate-limited API involved.
try:
    import torch
    from diffusers import (
        StableDiffusionPipeline,
        StableDiffusionImg2ImgPipeline,
        DPMSolverMultistepScheduler,
    )
    HAS_DIFFUSERS = True
except Exception as _diff_err:
    HAS_DIFFUSERS = False
    logging.warning(f"[diffusers] unavailable (local SD disabled): {_diff_err}")

# MoviePy — proper cinematic video: transitions, 3D camera moves, easing.
try:
    from moviepy.editor import (
        ImageClip, CompositeVideoClip, concatenate_videoclips,
        ColorClip, TextClip, AudioFileClip,
    )
    from moviepy.video.fx.all import fadein, fadeout, resize
    HAS_MOVIEPY = True
except Exception as _mp_err:
    HAS_MOVIEPY = False
    logging.warning(f"[moviepy] unavailable (Ken Burns fallback): {_mp_err}")

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

def call_ollama_vision_sync(image_base64, prompt, timeout=30):
    """Blocking vision call (uses requests) so it can run inside the sync edit
    pipeline / worker threads without an event loop."""
    url = f"{OLLAMA_BASE_URL}/api/chat"
    payload = {
        "model": OLLAMA_VISION_MODEL,
        "messages": [
            {"role": "system", "content": "You are a precise image-editing localizer."},
            {"role": "user", "content": prompt, "images": [image_base64]},
        ],
        "stream": False,
        "options": {"num_predict": 400, "temperature": 0.0},
    }
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("message", {}).get("content", "")
    except Exception as e:
        logging.warning(f"sync vision call failed: {e}")
    return ""


# ---------------------------------------------------------------------------
# Region vocabulary — used to decide safe fallbacks when vision can't locate
# the referenced object.
# ---------------------------------------------------------------------------
_REGION_KEYWORDS = {
    "clothing": ["shirt", "t-shirt", "tee", "top", "dress", "gown", "frock", "pants",
                 "jeans", "trousers", "shorts", "outfit", "clothes", "clothing",
                 "attire", "wear", "garment", "suit", "jacket", "coat", "skirt",
                 "hoodie", "sweater", "blouse", "vest"],
    "hair": ["hair", "hairstyle", "haircut", "beard", "mustache", "moustache"],
    "face": ["face", "skin", "complexion", "cheeks", "forehead"],
    "background": ["background", "backdrop", "scene", "setting", "surroundings", "environment"],
}

def _detect_region_keyword(prompt: str):
    p = prompt.lower()
    for region, kws in _REGION_KEYWORDS.items():
        if any(re.search(rf"\b{re.escape(k)}\b", p) for k in kws):
            return region
    return None


def localize_region_via_vision(image_b64: str, prompt: str, timeout: int = 25):
    """Ask the self-hosted vision model to locate the object the user wants to
    edit. Returns a dict {bbox: (x,y,w,h) in 0..1 or None, scope, target}.

    Best-effort: any failure returns bbox=None and the caller falls back to
    deterministic heuristics. This is what keeps edits scoped to the exact
    referenced region instead of a broad default mask.
    """
    if not image_b64:
        return {"bbox": None, "scope": "region", "target": None}
    vision_prompt = (
        "You are a precise image-editing localizer. The user wants to edit this image with the request: "
        f'"{prompt}".\n'
        "Respond with ONLY a JSON object, no other text:\n"
        "- 'scope': one of 'region' (edit a specific object/area), 'whole' (change the entire image), "
        "'background' (change only the backdrop behind the subject).\n"
        "- 'bbox': if scope is 'region', a list [x, y, w, h] of the bounding box of the object to edit, "
        "where x,y is the TOP-LEFT corner and w,h the size, ALL as fractions of the image "
        "width/height in 0..1. If you cannot locate it, use null.\n"
        "Example: {\"scope\":\"region\",\"bbox\":[0.35,0.45,0.3,0.35]}"
    )
    out = {"bbox": None, "scope": "region", "target": None}
    try:
        raw = call_ollama_vision_sync(image_b64, vision_prompt, timeout=timeout)
        if not raw:
            return out
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            return out
        parsed = json.loads(m.group())
        if not isinstance(parsed, dict):
            return out
        scope = str(parsed.get("scope", "region")).lower()
        bbox = parsed.get("bbox")
        if isinstance(bbox, list) and len(bbox) == 4:
            try:
                bx, by, bw, bh = [float(v) for v in bbox]
                # Clamp into valid normalized ranges.
                bx = min(max(bx, 0.0), 1.0)
                by = min(max(by, 0.0), 1.0)
                bw = min(max(bw, 0.02), 1.0 - bx)
                bh = min(max(bh, 0.02), 1.0 - by)
                out["bbox"] = (bx, by, bw, bh)
            except Exception:
                out["bbox"] = None
        if scope in ("whole", "background", "region"):
            out["scope"] = scope
    except Exception as e:
        logging.warning(f"vision localization parse failed: {e}")
    return out


def mask_from_bbox(image: Image.Image, bbox, feather_radius: int = 10) -> Image.Image:
    """Build a feathered L mask from a normalized bounding box (x,y,w,h)."""
    w, h = image.size
    bx, by, bw, bh = bbox
    x0, y0 = int(bx * w), int(by * h)
    x1, y1 = int((bx + bw) * w), int((by + bh) * h)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    if x1 <= x0 or y1 <= y0:
        return Image.new("L", (w, h), 0)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rectangle([x0, y0, x1, y1], fill=255)
    # Feather so the edit blends naturally into untouched pixels.
    mask = mask.filter(ImageFilter.GaussianBlur(radius=feather_radius))
    return mask


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
# Fully self-hosted policy: NO external model services (no HuggingFace, no
# rate-limited APIs). All editing is deterministic local processing —
# rembg (ONNX, bundled), Pillow, numpy and OpenCV. Understanding runs on
# the self-hosted Ollama server only.
# ---------------------------------------------------------------------------

def upscale_image(image: Image.Image, scale: int = 2) -> Image.Image:
    """High-quality Lanczos upscale (pure Pillow, unlimited) with a light
    unsharp pass so heavily upscaled SD frames stay crisp instead of
    dissolving into soft colour texture."""
    scale = max(2, min(int(scale), 4))
    w, h = image.size
    out = image.resize((w * scale, h * scale), Image.LANCZOS)
    try:
        out = out.filter(ImageFilter.UnsharpMask(radius=1.2, percent=70, threshold=2))
    except Exception:
        pass
    return out

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

# ---------------------------------------------------------------------------
# Image helpers
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

def orig_image_format(data: bytes) -> str:
    """Return the original image format (PNG/JPEG/GIF/BMP/WEBP...), default JPEG."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            return (im.format or "JPEG").upper()
    except Exception:
        return "JPEG"

def estimate_jpeg_quality(img: Image.Image):
    """Estimate a JPEG's saved quality (0-100) from its luminance quantization table.

    Uses the IJG scale-factor inversion: scale = table[0] * 100 / 16, then
    quality = (200 - scale) / 2 for quality >= 50, else 5000 / scale.
    """
    try:
        qt = getattr(img, "quantization", None)
        if not qt:
            return None
        table = qt[0] if isinstance(qt, (list, tuple)) else qt
        if not table:
            return None
        dc = float(table[0])
        if dc <= 0:
            return None
        scale = dc * 100.0 / 16.0
        if scale >= 100:
            q = int(5000 / scale)
        else:
            q = int((200 - scale) / 2)
        return max(1, min(100, q))
    except Exception:
        return None

def encode_edited(edited_img: Image.Image, orig_bytes: bytes) -> bytes:
    """Encode an edit result preserving the ORIGINAL file format and quality.

    - Lossless originals (PNG/GIF/BMP) stay lossless, so unedited pixels are
      byte-identical to the source.
    - JPEG originals are re-encoded at the original quality (min 88) with the
      original chroma subsampling, so the untouched rest of the image keeps its
      original quality instead of being recompressed at a generic setting.
    """
    fmt = orig_image_format(orig_bytes)
    if fmt in ("PNG", "GIF", "BMP"):
        buf = io.BytesIO()
        edited_img.save(buf, format=fmt)
        return buf.getvalue()
    if fmt == "WEBP":
        buf = io.BytesIO()
        edited_img.save(buf, format="WEBP", quality=95)
        return buf.getvalue()
    # JPEG path — match original quality & subsampling
    subsampling = -1
    quality = None
    try:
        with Image.open(io.BytesIO(orig_bytes)) as orig:
            subsampling = orig.info.get("subsampling", -1)
            quality = estimate_jpeg_quality(orig)
    except Exception:
        pass
    if quality is None or quality < 88:
        quality = 95
    if quality > 95:
        quality = 95
    buf = io.BytesIO()
    kwargs = {"format": "JPEG", "quality": quality, "optimize": True}
    if subsampling != -1:
        kwargs["subsampling"] = subsampling
    edited_img.save(buf, **kwargs)
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
        m_arr = np.array(mask)
        # Empty/blank cloth masks must not shadow the person-based fallback
        if np.max(m_arr) > 10:
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


def _garment_region_mask(image: Image.Image, tgt: str) -> Image.Image:
    """Full-coverage clothing mask so the ENTIRE garment (e.g. a full-length
    dress) is recoloured — not just the upper body. Uses the person silhouette
    intersected with a garment-specific vertical band, falling back to the band
    alone when rembg only detects part of the subject (which previously left the
    lower dress untouched → 'half normal, half black-and-white')."""
    w, h = image.size
    if tgt in ("dress", "outfit"):
        band = [int(w * 0.12), int(h * 0.30), int(w * 0.88), int(h * 0.98)]
    elif tgt == "shirt":
        band = [int(w * 0.20), int(h * 0.28), int(w * 0.80), int(h * 0.60)]
    elif tgt == "pants":
        band = [int(w * 0.22), int(h * 0.56), int(w * 0.78), int(h * 0.98)]
    else:
        band = [int(w * 0.16), int(h * 0.30), int(w * 0.84), int(h * 0.96)]
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rectangle(band, fill=255)
    person = segment_person(image) or segment_foreground(image)
    if person is not None:
        pa = np.array(person.convert("L"))
        ma = np.array(m)
        combined = np.where(pa > 100, ma, 0).astype(np.uint8)
        if combined.max() > 30:  # only use intersection if it actually covers cloth
            m = Image.fromarray(combined)
        # otherwise keep the geometric band so the whole garment is touched
    # NEVER touch the face: hard-exclude the upper frame and the top of the
    # detected person so a garment swap can never paint over the user's face.
    m_arr = np.array(m)
    m_arr[: int(h * 0.27), :] = 0
    if person is not None:
        pa = np.array(person.convert("L"))
        ys = np.where(pa > 80)[0]
        if len(ys):
            head_bottom = int(ys.min() + (ys.max() - ys.min()) * 0.32)
            m_arr[:head_bottom, :] = 0
    m = Image.fromarray(m_arr)
    return m.filter(ImageFilter.GaussianBlur(radius=5))


def _suit_detail_mask(mask: Image.Image, x0: int, x1: int, y0: int, y1: int, alpha: float) -> Image.Image:
    """Restrict `mask` to a bounding sub-window (in mask coords) at `alpha`."""
    m = np.array(mask.convert("L"), dtype=np.float32) / 255.0
    region = np.zeros_like(m)
    region[y0:y1, x0:x1] = alpha
    combined = np.clip(m * region, 0, 1) * 255
    return Image.fromarray(combined.astype(np.uint8))


def _add_suit_details(image: Image.Image, mask: Image.Image, suit_color: tuple) -> Image.Image:
    """Add OPAQUE tailoring cues so a recoloured garment reads as a real suit.

    Every detail layer is drawn at FULL opacity (restricted to the garment mask
    and given a soft 1-2px edge) — there is never a translucent alpha overlay.
    The result is flat fabric shading that looks like a jacket, not a glassy
    ghost painted on top of the photo.
    """
    m = np.array(mask.convert("L"))
    ys, xs = np.where(m > 60)
    if len(xs) == 0 or len(ys) == 0:
        return image
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    w, h = image.size
    out = image.copy().convert("RGB")
    draw = ImageDraw.Draw(out)

    cx = (x0 + x1) // 2
    collar_y = y0 + int((y1 - y0) * 0.10)
    chest_y = y0 + int((y1 - y0) * 0.42)
    lap_w = int((x1 - x0) * 0.20)

    # Light/shadow shade pair derived from the suit tone so the lapels read as
    # the SAME fabric, only folded.
    base_tone = tuple(int(c) for c in suit_color)
    light_tone = tuple(min(255, int(c * 1.35)) for c in base_tone)
    dark_tone = tuple(max(0, int(c * 0.65)) for c in base_tone)

    # Left + right notched lapels — opaque shaded facets.
    draw.polygon(
        [(cx - int((x1 - x0) * 0.045), collar_y),
         (cx - lap_w * 3, collar_y + int((chest_y - collar_y) * 0.35)),
         (cx - lap_w * 2, chest_y),
         (cx - lap_w, chest_y)],
        fill=light_tone,
    )
    draw.polygon(
        [(cx + int((x1 - x0) * 0.045), collar_y),
         (cx + lap_w * 3, collar_y + int((chest_y - collar_y) * 0.35)),
         (cx + lap_w * 2, chest_y),
         (cx + lap_w, chest_y)],
        fill=light_tone,
    )
    # Lapel outline (dark fold shadow) for definition.
    draw.line(
        [(cx - int((x1 - x0) * 0.045), collar_y),
         (cx - lap_w * 2, chest_y)],
        fill=dark_tone, width=max(1, int((y1 - y0) * 0.012)),
    )
    draw.line(
        [(cx + int((x1 - x0) * 0.045), collar_y),
         (cx + lap_w * 2, chest_y)],
        fill=dark_tone, width=max(1, int((y1 - y0) * 0.012)),
    )

    # Shirt front — opaque narrow centre column (white-ish), masked to garment.
    sx0 = int(x0 + (x1 - x0) * 0.44)
    sx1 = int(x0 + (x1 - x0) * 0.56)
    draw.rectangle([sx0, collar_y, sx1, chest_y], fill=(238, 238, 243))

    # Tie — opaque darker column, skipped for tiny masks.
    if (x1 - x0) > 40 and (y1 - y0) > 60:
        tx0 = int(cx - (x1 - x0) * 0.022)
        tx1 = int(cx + (x1 - x0) * 0.022)
        ty0 = collar_y + int((y1 - y0) * 0.06)
        ty1 = collar_y + int((y1 - y0) * 0.34)
        draw.rectangle([tx0, ty0, tx1, ty1], fill=(48, 48, 62))

    # Jacket sleeves — shade the outer bands so the garment reads as a jacket
    # with sleeves instead of a flat painted torso.
    sleeve_w = int((x1 - x0) * 0.14)
    draw.rectangle([x0, y0, x0 + sleeve_w, y1], fill=dark_tone)
    draw.rectangle([x1 - sleeve_w, y0, x1, y1], fill=dark_tone)
    # Single-breasted button line down the chest centre, below the tie.
    if (x1 - x0) > 40 and (y1 - y0) > 80:
        btn_rad = max(1, int((y1 - y0) * 0.012))
        bx = cx
        by = chest_y + int((y1 - y0) * 0.10)
        for k in range(3):
            yy = by + k * int((y1 - y0) * 0.075)
            if yy < y1 - int((y1 - y0) * 0.12):
                draw.ellipse([bx - btn_rad, yy - btn_rad, bx + btn_rad, yy + btn_rad], fill=dark_tone)

    # Feather the detail layer's edges so it doesn't look pasted, then keep only
    # the part that lies inside the garment mask (never bleeds outside).
    out = out.filter(ImageFilter.GaussianBlur(radius=1))
    out_np = np.asarray(out, dtype=np.uint8)
    base_np = np.asarray(image.convert("RGB"), dtype=np.uint8)
    am = (m > 60).astype(np.uint8)[:, :, None]
    out_np = np.where(am == 1, out_np, base_np)
    return Image.fromarray(out_np)


def _restrict_to_mask(light_mask: "Image.Image", base_mask: np.ndarray, coef: float) -> "Image.Image":
    """Multiply a mask (0..255) by the garment mask * coef so detail never bleeds
    outside the clothing region."""
    a = np.array(light_mask.convert("L"), dtype=np.float32) / 255.0
    b = np.asarray(base_mask, dtype=np.float32) / 255.0
    out = np.clip(a * b * coef, 0, 1) * 255
    return Image.fromarray(out.astype(np.uint8))


def _lift(img: "Image.Image", factor: float) -> "Image.Image":
    return ImageEnhance.Brightness(img).enhance(factor)


def _build_garment_swap_prompt(prompt, region, tgt):
    """Craft a photorealistic inpainting prompt for a garment swap so the local SD
    model regenerates the referenced clothing as the requested garment (e.g. a
    real suit) instead of a recoloured overlay."""
    p = (prompt or "").lower()
    garments = [
        "tuxedo", "suit", "blazer", "jacket", "gown", "dress", "shirt",
        "tshirt", "t-shirt", "skirt", "pants", "trousers", "jeans", "shorts",
        "hoodie", "sweater", "coat", "kurta", "saree", "sari", "kimono",
        "tunic", "vest", "uniform", "robe", "frock",
    ]
    target = None
    for g in garments:
        if g in p:
            target = g
            break
    if target is None:
        target = (region or tgt or "clothing").strip()
    subject = "a person" if tgt in ("outfit", "shirt", "pants", "dress") else "the subject"
    return (
        f"photograph of {subject} wearing a {target}, highly detailed realistic "
        f"fabric, proper tailoring, professional studio lighting, sharp focus"
    )


_GARMENT_SWAP_WORDS = re.compile(
    r"\b(suit|blazer|tuxedo|tux|jacket|formal|outfit|gown|coat|hoodie|"
    r"sweater|trousers|saree|sari|kurti|kurta|lehenga|uniform|costume|"
    r"three-piece|dinner jacket)\b"
)


def _garment_swap_intent(prompt):
    """True when the prompt asks to replace a garment with a DIFFERENT garment
    type (suit/blazer/formal/...). Such requests must be a real SD regeneration
    rather than a flat recolour — even if a colour word (e.g. 'black suit') is
    present in the prompt."""
    return bool(_GARMENT_SWAP_WORDS.search((prompt or "").lower()))


def _person_part_mask(image: Image.Image, part: str) -> Optional[Image.Image]:
    """Reliable clothing-region mask: the person silhouette intersected with a
    vertical band for the named garment, then EXCLUDING the head/face area.
    Avoids the (often empty/poor) dedicated cloth-segmentation model on
    synthetic photos, while still excluding the face and background so only
    the referenced outfit area is touched."""
    person = segment_person(image) or segment_foreground(image)
    head = _head_region_mask(image)
    w, h = image.size
    m = Image.new("L", (w, h), 0)
    if part in ("dress", "outfit"):
        y0, y1 = int(h * 0.32), int(h * 0.96)
    elif part == "shirt":
        y0, y1 = int(h * 0.24), int(h * 0.58)
    elif part == "pants":
        y0, y1 = int(h * 0.52), int(h * 0.96)
    else:
        y0, y1 = int(h * 0.28), int(h * 0.92)
    ImageDraw.Draw(m).rectangle([0, y0, w, y1], fill=255)
    if person is not None:
        pa = np.array(person.convert("L"))
        ma = np.array(m)
        combined = np.where(pa > 128, ma, 0).astype(np.uint8)
        m = Image.fromarray(combined)
    # Exclude head/face region so garment swaps never touch it.
    if head is not None:
        ha = np.array(head.convert("L"))
        ma2 = np.array(m)
        combined2 = np.where(ha > 40, 0, ma2).astype(np.uint8)
        m = Image.fromarray(combined2)
    return m.filter(ImageFilter.GaussianBlur(radius=5))


def _head_region_mask(image: Image.Image) -> Image.Image:
    """Mask covering the head/face area (used for face/hair edits) so the body
    and the background are never touched."""
    w, h = image.size
    m = Image.new("L", (w, h), 0)
    # The head typically occupies the top-centre ~30% of a portrait frame.
    x0, x1 = int(w * 0.26), int(w * 0.74)
    y0, y1 = int(h * 0.04), int(h * 0.36)
    ImageDraw.Draw(m).ellipse([x0, y0, x1, y1], fill=255)
    return m.filter(ImageFilter.GaussianBlur(radius=6))


def _hair_region_mask(image: Image.Image) -> Image.Image:
    """Mask covering the HAIR band only (top of the head, plus side locks for
    long hair) so a hair-colour change never tints the face/skin. Used for
    'hair to blonde' style edits."""
    w, h = image.size
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    # Crown / top hair
    x0, x1 = int(w * 0.24), int(w * 0.76)
    y0, y1 = int(h * 0.02), int(h * 0.30)
    d.ellipse([x0, y0, x1, y1], fill=255)
    # Side locks (long hair)
    d.rectangle([int(w * 0.18), int(h * 0.06), int(w * 0.30), int(h * 0.38)], fill=255)
    d.rectangle([int(w * 0.70), int(h * 0.06), int(w * 0.82), int(h * 0.38)], fill=255)
    return m.filter(ImageFilter.GaussianBlur(radius=5))


def _face_neck_protection_mask(image: Image.Image) -> Image.Image:
    """Keep-region that must NEVER be touched by a garment swap: the face/head
    PLUS a modest neck/shoulder band just below the chin.

    Uses the real person silhouette to locate the head when available (rembg),
    so the protection lines up with the actual subject rather than a fixed
    proportional ellipse. Falls back to a centred portrait ellipse otherwise.
    Extending slightly below the chin prevents SD from painting a 'ghost chin /
    second face' just under the head when it regenerates the garment crop."""
    w, h = image.size
    m = Image.new("L", (w, h), 0)
    person = segment_person(image) or segment_foreground(image)
    if person is not None:
        pa = np.array(person.convert("L"))
        ys, xs = np.where(pa > 80)
        if len(ys) and len(xs):
            top = int(ys.min())
            bottom = int(ys.max())
            head_h = max(8, int((bottom - top) * 0.40))
            left = int(xs.min())
            right = int(xs.max())
            # Head zone: top of the person down ~40% of their height.
            y0 = max(0, top - int((bottom - top) * 0.04))
            y1 = min(h, top + head_h)
            x0 = max(0, left - int((right - left) * 0.04))
            x1 = min(w, right + int((right - left) * 0.04))
            # Neck/shoulder band: a short region just below the head zone so the
            # SD garment patch never reaches the chin / upper collar seam.
            neck_band = int((bottom - top) * 0.09)
            y1n = min(h, y1 + neck_band)
            ImageDraw.Draw(m).rectangle([x0, y0, x1, y1n], fill=255)
            return m.filter(ImageFilter.GaussianBlur(radius=7))
    # Fallback: centred portrait ellipse covering the head + upper neck.
    x0, x1 = int(w * 0.22), int(w * 0.78)
    y0, y1 = int(h * 0.02), int(h * 0.42)
    ImageDraw.Draw(m).ellipse([x0, y0, x1, y1], fill=255)
    return m.filter(ImageFilter.GaussianBlur(radius=7))


def _garment_default_tone(desc: str) -> tuple:
    """Pick a sensible default garment colour for a colour-less swap request
    (e.g. 'dress to a sundress', 'shirt to a tuxedo') so the change is clearly
    visible while staying a real photo (no generative regeneration)."""
    d = (desc or "").lower()
    if any(w in d for w in ["tuxedo", "black", "evening"]):
        return (30, 30, 40)
    if any(w in d for w in ["suit", "blazer", "formal", "jacket"]):
        return (40, 46, 74)  # navy suit — clearly coloured, not grey
    if any(w in d for w in ["dark"]):
        return (45, 48, 62)
    if any(w in d for w in ["white", "bridal", "wedding", "sundress", "summer", "linen", "beach"]):
        return (238, 238, 240)
    if any(w in d for w in ["red", "crimson", "scarlet"]):
        return (200, 40, 50)
    if any(w in d for w in ["blue", "navy", "denim"]):
        return (60, 90, 200)
    if any(w in d for w in ["green", "emerald"]):
        return (40, 160, 80)
    if any(w in d for w in ["gold", "yellow", "mustard"]):
        return (225, 190, 60)
    if any(w in d for w in ["pink", "rose"]):
        return (225, 130, 160)
    if any(w in d for w in ["leather"]):
        return (70, 55, 45)
    if any(w in d for w in ["purple", "violet"]):
        return (150, 70, 190)
    return (150, 150, 165)  # neutral fabric

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

    Careful not to flatten the photo: the mask values only determine HOW MUCH of
    the hue shift is applied (the luminance channel V is always kept exactly),
    and the interior blend keeps 30% of the original saturation/texture so the
    fabric or skin still reads as the same material in a new color — never a
    flat painted-over overlay.
    """
    if mask is None:
        mask = Image.new("L", image.size, 255)
    elif mask.size != image.size:
        mask = mask.resize(image.size, Image.NEAREST)

    img = np.array(image.convert("RGB"), dtype=np.float32) / 255.0
    m = np.array(mask.convert("L"), dtype=np.float32) / 255.0

    mask_bool = m > 0.25
    if not np.any(mask_bool):
        return image

    tc = np.array(target_color, dtype=np.float32) / 255.0
    th, ts, tv = rgb_to_hsv_single(tc[0], tc[1], tc[2])

    pixels = img[mask_bool]
    h_pix, s_pix, v_pix = rgb_to_hsv_vectorized_simple(pixels)

    # Keep original luminance (V); rotate hue toward target but never fall off a
    # cliff — the largest sensible hue rotation prevents neon shifts on neutral
    # fabric. Saturation leans toward the target while the original saturation
    # (texture) is partially retained so material folds stay visible.
    hue_diff = (th - h_pix + 0.5) % 1.0 - 0.5
    # Rotate 90% along the SHORTEST signed arc — the sign is always preserved so
    # the new hue can never wrap the wrong way around and land in a foreign
    # colour; near-target pixels settle just short of it, far pixels come most
    # of the way while keeping a trace of the original fabric tint.
    hue_rot = hue_diff * 0.9
    h_new = (h_pix + hue_rot + 1.0) % 1.0
    s_new = s_pix * 0.3 + ts * 0.7

    edited_pixels = hsv_to_rgb_vectorized_simple(h_new, s_new, v_pix)

    # Mask-scaled blend: full-strength recolor in the body, feathered falloff at
    # the edges so the new region melts into the untouched photo.
    m_vals = m[mask_bool, np.newaxis]
    blended = pixels * (1 - m_vals) + edited_pixels * m_vals
    # Re-inject 12% of the original pixels globally so detail/fabric grain is
    # always preserved even where the mask is at full strength.
    blended = blended * 0.88 + pixels * 0.12

    result = img.copy()
    result[mask_bool] = blended
    return Image.fromarray((result * 255).astype(np.uint8))

def apply_fabric_texture(image: Image.Image, mask: Image.Image, desc: str) -> Image.Image:
    """
    Simulate fabric texture on the masked region WITHOUT destroying detail.

    The old implementation Gaussian-blurred the whole garment then feathered it
    back — that produced the cartoonish blur/scatter look. Now we:
      1. keep the original pixels 100% (no blur of the photo),
      2. apply a gentle unsharp (micro-contrast) boost inside the region so the
         existing folds, stitching and lighting LOOK more pronounced,
      3. add a very subtle deterministic fabric-weave luminance pattern
         (wool = fine horizontal hatch, denim = diagonal twill, etc.) so the
         region reads as real material rather than a flat fill.
    """
    d = desc.lower()
    m = np.array(mask.convert("L"), dtype=np.float32) / 255.0
    mask_bool = m > 0.12
    if not np.any(mask_bool):
        return image

    mode = None
    if any(w in d for w in ["suit", "formal", "tuxedo", "blazer", "wool"]):
        mode = "wool"          # fine horizontal hatch
        contrast = 1.10
    elif any(w in d for w in ["denim", "jean"]):
        mode = "denim"         # diagonal twill
        contrast = 1.16
    elif any(w in d for w in ["silk", "satin"]):
        mode = "silk"          # soft sheen bands
        contrast = 1.14
    elif any(w in d for w in ["cotton", "casual", "t-shirt", "linen"]):
        mode = "cotton"        # light random grain
        contrast = 1.06
    else:
        mode = "generic"
        contrast = 1.08

    # 1) Micro-contrast (unsharp) inside the mask — sharpens existing detail.
    sharp = image.filter(ImageFilter.UnsharpMask(radius=2, percent=55, threshold=3))
    base = np.array(image, dtype=np.float32)
    shp = np.array(sharp, dtype=np.float32)
    w, h = image.size

    # 2) Deterministic weave luminance pattern inside the mask.
    arr = base.copy()
    rng = np.random.RandomState(int(np.sum(mask_bool)) % (2 ** 31))
    yy, xx = np.mgrid[0:h, 0:w]

    if mode == "wool":
        hatch = (yy % 5) < 1
        weave = np.where(hatch, -4.0, 2.5)
    elif mode == "denim":
        diag = ((xx * 0.5 + yy) % 7) < 1
        weave = np.where(diag, -3.5, 2.0)
    elif mode == "silk":
        sheen = np.sin(xx / (max(w, 1) * 0.16) + yy / (max(h, 1) * 0.31)) > 0.0
        weave = np.where(sheen, 3.2, -1.8)
    elif mode == "cotton":
        grain = rng.normal(0, 2.4, (h, w))
        weave = grain * 0.35
    else:
        grain = rng.normal(0, 2.8, (h, w))
        weave = grain * 0.5

    # 3) Compose: accent the sharpened detail, tint slightly with the weave
    # luminance pattern, weighted by the mask so edges stay clean.
    detail = base * 0.62 + shp * 0.38
    out = detail.copy()
    out[:, :, 0] += weave * 0.55
    out[:, :, 1] += weave * 0.45
    out[:, :, 2] += weave * 0.35
    out = np.clip(out, 0, 255)

    # Per-pixel contrast applied only through the mask (luminance preserving).
    lum = 0.299 * out[:, :, 0] + 0.587 * out[:, :, 1] + 0.114 * out[:, :, 2]
    delta = (contrast - 1.0) * (lum - 128.0) * 0.5
    out = np.clip(out + delta[:, :, None], 0, 255)

    blend = np.where(mask_bool[:, :, None], out, base)
    # Feathered seam: 3px blend so the textured region melts back into the photo.
    seam = _feather_channel(mask, radius=3)
    result = (base * (1 - seam[:, :, None]) + blend * seam[:, :, None])
    return Image.fromarray(result.astype(np.uint8))


def _feather_channel(mask_arr, radius=3):
    """Feather an L-array mask (0..255 float) into a seamless 0..1 blend.
    Accepts either a PIL L-mode Image or a 0..255 ndarray."""
    from PIL import Image as _Im
    import numpy as _np
    if not isinstance(mask_arr, _Im.Image):
        mask_arr = _Im.fromarray(mask_arr.astype(_np.uint8))
    return _np.asarray(mask_arr.convert("L").filter(ImageFilter.GaussianBlur(radius=radius)),
                       dtype=_np.float32) / 255.0

COLOR_MAP = {
    "red": (235, 30, 40), "blue": (25, 65, 240), "green": (25, 215, 50),
    "white": (245, 245, 248), "black": (50, 50, 55), "navy": (35, 40, 160),
    "grey": (175, 175, 180), "gray": (175, 175, 180),     "brown": (180, 100, 50), "blonde": (245, 225, 150), "blond": (245, 225, 150),
    "ginger": (200, 110, 50),
    "purple": (160, 45, 195), "pink": (235, 100, 140), "yellow": (245, 225, 50),
    "gold": (240, 200, 40), "silver": (215, 215, 225), "orange": (240, 130, 35),
    "teal": (30, 185, 180), "magenta": (220, 35, 160), "cyan": (35, 220, 230),
    "beige": (220, 205, 170), "maroon": (180, 35, 50), "coral": (240, 120, 100),
    "lavender": (205, 160, 235), "mint": (110, 220, 160), "peach": (245, 185, 140),
    "turquoise": (35, 200, 200), "indigo": (70, 30, 170), "violet": (165, 50, 210),
    "rust": (185, 75, 35), "burgundy": (135, 25, 60), "charcoal": (70, 70, 75),
    "olive": (110, 115, 45), "aqua": (40, 200, 200), "cream": (250, 240, 215),
}

def find_color(prompt: str) -> Optional[tuple]:
    """Return the RGB color tuple for the first color word found in the prompt."""
    desc = prompt.lower().strip()
    for name, color in COLOR_MAP.items():
        if re.search(rf"\b{re.escape(name)}\b", desc):
            return color
    return None

def smart_recolor(
    image: Image.Image,
    mask: Image.Image,
    replacement_desc: str,
) -> Optional[Image.Image]:
    """
    Recolor masked region ONLY if an explicit color is mentioned.
    Returns None for non-color prompts (so caller falls through to other strategies).
    """
    color = find_color(replacement_desc)
    if color is not None:
        return recolor_region(image, mask, color)

    # No explicit color found — return None so caller falls through to other strategies
    return None

# ---------------------------------------------------------------------------
# Content-aware fill (OpenCV)
# ---------------------------------------------------------------------------

def inpaint_region(image: Image.Image, mask: Image.Image) -> Image.Image:
    """Content-aware fill of the masked region using OpenCV (Telea).

    Pure deterministic processing: pixels are reconstructed from surrounding
    content — nothing is generated. Pixels outside the mask stay untouched.
    """
    import cv2
    W, H = image.size
    m = mask.convert("L")
    if m.size != (W, H):
        m = m.resize((W, H), Image.NEAREST)
    m_arr = np.array(m)
    binary = (m_arr > 96).astype(np.uint8) * 255
    # Slight dilation so mask edges are healed too
    kernel = np.ones((7, 7), np.uint8)
    binary = cv2.dilate(binary, kernel, iterations=1)
    bgr = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)
    filled = cv2.inpaint(bgr, binary, inpaintRadius=6, flags=cv2.INPAINT_TELEA)
    rgb = cv2.cvtColor(filled, cv2.COLOR_BGR2RGB)
    out = Image.fromarray(rgb)
    # Feather the seam so the filled area blends smoothly with untouched pixels
    feather = Image.fromarray(binary).filter(ImageFilter.GaussianBlur(radius=4))
    return Image.composite(out, image.convert("RGB"), feather)

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
    elif target == "background" and any(w in p for w in ["change", "replace", "remove", "erase", "delete", "edit", "set", "put", "turn", "make", "swap", "switch", "give", "convert", "transform", "into", "become"]):
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

def is_visually_unchanged(orig: "Image.Image", edited: "Image.Image", threshold: float = 1.0, mask=None) -> bool:
    """Pixel-level check: True when the edited image is essentially identical to the original.

    For REGION edits a `mask` is supplied and only the masked area is compared
    (a small region change must not be judged against the whole, unchanged
    photo). For whole-image edits `mask` is None and the full frame is compared.
    A tiny threshold tolerates JPEG re-encode noise while catching genuine
    no-ops (e.g. recoloring with the same color).
    """
    try:
        a = orig.convert("RGB")
        b = edited.convert("RGB")
        if a.size != b.size:
            return False
        if mask is not None:
            m = mask.convert("L").resize(a.size, Image.NEAREST)
            ma = np.array(m, dtype=np.float32) / 255.0
            if ma.max() < 0.05:
                return False
            pa = np.asarray(a, dtype=np.int16)
            pb = np.asarray(b, dtype=np.int16)
            diff = np.abs(pa - pb)
            # mean absolute diff only inside the masked area
            mean_diff = float(np.mean(diff * ma[:, :, None]) / max(ma.mean(), 1e-6))
            return mean_diff < threshold
        sa = a.copy()
        sb = b.copy()
        sa.thumbnail((96, 96))
        sb.thumbnail((96, 96))
        pa = np.asarray(sa, dtype=np.int16)
        pb = np.asarray(sb, dtype=np.int16)
        return float(np.mean(np.abs(pa - pb))) < threshold
    except Exception:
        return False


def guard_edited(orig: "Image.Image", edited: "Image.Image", prompt: str, mask=None):
    """Raise 422 when an edit left the image effectively unchanged (never echo the original)."""
    if edited is not None and is_visually_unchanged(orig, edited, mask=mask):
        raise HTTPException(
            422,
            f"The edit request '{prompt}' did not change the image. Please describe a more specific change (e.g., a color, style, or region).",
        )


def _region_mean_diff(orig: "Image.Image", edited: "Image.Image", mask: "Image.Image") -> float:
    """Mean absolute per-channel pixel difference WITHIN the masked region.

    Used to cross-verify that a generative edit actually applied (a near-copy with
    only a faint seam would read as an ugly translucent overlay and must be
    rejected/fallen-through rather than returned to the user)."""
    try:
        a = np.asarray(orig.convert("RGB").resize(mask.size, Image.LANCZOS), dtype=np.int16)
        b = np.asarray(edited.convert("RGB").resize(mask.size, Image.LANCZOS), dtype=np.int16)
        m = np.asarray(mask.convert("L"), dtype=np.float32) / 255.0
        if m.max() < 0.05:
            return 0.0
        diff = np.abs(a - b).astype(np.float32)
        return float(np.mean(diff * m[:, :, None]) / max(m.mean(), 1e-6))
    except Exception:
        return 0.0


def _guard_unchanged(fn):
    """Decorator: run an edit pipeline, then reject results that leave the image unchanged.

    Also re-encodes true-color results using the ORIGINAL file format and
    quality, so region edits preserve the untouched parts of the image at their
    original quality (lossless originals stay lossless). Images with alpha
    (e.g. transparent background removal) are returned as produced.
    """
    @functools.wraps(fn)
    def wrapper(image_bytes, prompt, *args, **kwargs):
        result = fn(image_bytes, prompt, *args, **kwargs)
        try:
            orig = bytes_to_img(image_bytes).convert("RGB")
            edited_raw = Image.open(io.BytesIO(base64.b64decode(result["edited"])))
            edited = edited_raw.convert("RGB")
            # Region edits only change part of the image, so compare WITHIN the
            # returned mask (never judge a small region change against the whole,
            # untouched photo). Whole-image edits return no mask and are compared
            # in full.
            mask = None
            if result.get("mask"):
                try:
                    mask = Image.open(io.BytesIO(base64.b64decode(result["mask"]))).convert("L")
                except Exception:
                    mask = None
            guard_edited(orig, edited, prompt, mask)
            if edited_raw.mode == "RGB":
                result["edited"] = base64.b64encode(encode_edited(edited, image_bytes)).decode()
        except HTTPException:
            raise
        except Exception:
            pass
        return result
    return wrapper


@_guard_unchanged
def edit_image(image_bytes: bytes, prompt: str, precomputed_mask=None, edit_scope=None) -> dict:
    """Run full editing pipeline: interpret -> segment -> edit -> return.

    `precomputed_mask`/`edit_scope` let a vision step (or caller) pin the exact
    region to edit so only the user-referenced area is touched.
    """
    image = bytes_to_img(image_bytes).convert("RGB")
    orig = image.copy()
    info = interpret_prompt(prompt)
    p_lower = prompt.lower().strip()
    # Define `style` up front so every edit branch (incl. the SD garment-swap
    # branch, which runs before the old assignment point) can reference it
    # without hitting Python's "local variable 'style' unbound" error.
    style = detect_explicit_art_style(prompt)
    logging.info(f"Edit info: {info}")

    # Create mask for the target region
    tgt = info["target"]
    mask = None

    person_target = tgt in ("outfit", "shirt", "pants", "dress", "face", "hair") or \
        _detect_region_keyword(prompt) in ("clothing", "face", "hair")
    # Backend photo analysis FIRST: keep any vision-localized mask supplied by the
    # caller. Only discard it when the segmentation pipeline can produce a more
    # precise garment mask. Never ignore a valid vision bbox for a person edit.
    has_vision_mask = precomputed_mask is not None and np.max(np.array(precomputed_mask)) > 15
    if person_target:
        whole_image = False
        edit_scope = "region"
        # Preserve vision mask; the segmented masks below will only replace it
        # when they yield higher coverage/precision.
        if not has_vision_mask:
            precomputed_mask = None
    else:
        # Whole-image intent: user asked to change the entire image (not a specific object)
        whole_image = (edit_scope == "whole") or (
            tgt == "auto" and any(
                w in p_lower for w in ["image", "photo", "picture", "entire", "whole", "full"]
            )
        )

    if edit_scope == "background":
        # Vision pinned this as a backdrop-only edit — trust it, but keep any
        # vision-provided mask (subject-aware) over a crude foreground invert.
        info = dict(info)
        info["action"] = "change_background"
        info["target"] = "background"
        if precomputed_mask is not None:
            mask = precomputed_mask
        else:
            fg = segment_foreground(image)
            if fg is not None:
                mask = ImageOps.invert(fg)
    elif precomputed_mask is not None:
        mask = precomputed_mask
    elif tgt == "background":
        fg = segment_foreground(image)
        if fg is not None:
            mask = ImageOps.invert(fg)
    elif whole_image:
        mask = None
    else:
        # Scope edits to the ACTUAL subject the user referenced. Prefer precise
        # segmentation; only fall back to the geometric upper-body box when the
        # request clearly targets a person's clothing/face/hair. Never apply a
        # broad default mask to an ambiguous image (e.g. a landscape) — that
        # would change parts the user never mentioned.
        seg = None
        if tgt in ("outfit", "shirt", "pants", "dress"):
            seg = _garment_region_mask(image, tgt)
        elif tgt == "hair":
            seg = _hair_region_mask(image)
        elif tgt == "face":
            seg = _head_region_mask(image)
        if seg is None:
            seg = segment_person(image) or segment_foreground(image)
        known_body = tgt in ("outfit", "shirt", "pants", "dress", "face", "hair") or \
            _detect_region_keyword(prompt) in ("clothing", "face", "hair")
        if seg is not None:
            mask = seg
        elif known_body:
            mask = create_upper_body_mask(image)
        elif re.search(r"\b(sky|clouds?|horizon|sunset|daylight)\b", p_lower):
            # Sky/clouds live in the upper region — edit only that band so the
            # rest of the photo is left untouched.
            m = Image.new("L", image.size, 0)
            ImageDraw.Draw(m).rectangle([0, 0, image.width, int(image.height * 0.6)], fill=255)
            mask = m.filter(ImageFilter.GaussianBlur(radius=12))
        else:
            # No confident localization — decline rather than risk altering
            # unrequested areas of the image.
            raise HTTPException(
                422,
                f"The edit '{prompt}' needs a specific subject that could not be located in the image. "
                f"Try naming the exact object or region (e.g. 'change my shirt to red', 'remove the person').",
            )

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
            "changed": True,
        }

    # ── Background Changes ──
    if info["action"] == "change_background":
        # Remove background: make background transparent
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
                    "changed": True,
                }
        # Named-color backgrounds (e.g. "white/blue/pink background").
        bg_color = find_color(info.get("replacement", "")) or find_color(prompt)
        if bg_color is not None and HAS_REMBG:
            cut = rembg_remove(img_to_bytes(image), session=rembg_session)
            fg_rgba = Image.open(io.BytesIO(cut)).convert("RGBA")
            if fg_rgba.size != image.size:
                fg_rgba = fg_rgba.resize(image.size, Image.LANCZOS)
            # Subtle vertical gradient of the SAME hue (top ~8% lighter) so the
            # backdrop reads as a surface, not a flat fill.
            r, g, b = bg_color
            top = tuple(min(255, int(c * 1.08)) for c in (r, g, b))
            grad = np.zeros((image.height, image.width, 3), dtype=np.uint8)
            t = np.linspace(0.0, 1.0, image.height)[:, None, None]
            top_arr = np.array(top, dtype=np.float32)[None, None, :]
            base_arr = np.array((r, g, b), dtype=np.float32)[None, None, :]
            grad[:] = (top_arr * (1.0 - t) + base_arr * t).astype(np.uint8)
            backdrop = Image.fromarray(grad, "RGB").convert("RGBA")
            # Feather the subject's alpha edge for clean compositing
            alpha = fg_rgba.getchannel("A").filter(ImageFilter.GaussianBlur(radius=1))
            fg_rgba.putalpha(alpha)
            result = _composite_subject_realistic(fg_rgba, backdrop.convert("RGB"))
            guard_edited(image, result, prompt)
            edited_bytes = img_to_bytes(result)
            return {
                "edited": base64.b64encode(edited_bytes).decode(),
                "mask": "",
                "strategy": "bg_color_replace",
                "interpretation": info,
                "width": result.width,
                "height": result.height,
                "changed": True,
            }
        # Scene-based background replacement — preserve subject, generate new backdrop from prompt
        if HAS_REMBG:
            try:
                bg_desc = (info.get("replacement", "") or "").strip()
                # Fallback to extracting background phrase from prompt
                if not bg_desc or len(bg_desc) < 3:
                    bg_desc = prompt
                # Strip edit verbs to leave pure scene description
                bg_prompt = re.sub(r'^\s*(change|replace|set|make|turn|convert|swap|switch|put|give)\s+(the\s+)?(background|backdrop|scene|setting|surroundings|environment)\s*(to|into|with|as|for)?\s*', '', bg_desc, flags=re.IGNORECASE).strip()
                if not bg_prompt:
                    bg_prompt = prompt
                bg_prompt = bg_prompt[:400].strip()
                cut = rembg_remove(img_to_bytes(image), session=rembg_session)
                fg_rgba = Image.open(io.BytesIO(cut)).convert("RGBA")
                if fg_rgba.size != image.size:
                    fg_rgba = fg_rgba.resize(image.size, Image.LANCZOS)
                # Generate a photorealistic backdrop from the local SD model so the
                # new background looks like a real photo, not a flat illustration.
                # Stylized only when the user explicitly asked for it; falls back to
                # the procedural engine solely when SD is unavailable.
                style = detect_explicit_art_style(bg_prompt) or detect_explicit_art_style(prompt)
                backdrop_img = _generate_sd_backdrop(bg_prompt, style, image.width, image.height)
                if backdrop_img is None:
                    backdrop_img, _ = _render_generated_scene(bg_prompt, image.width, image.height, 0)
                backdrop = backdrop_img.convert("RGBA")
                alpha = fg_rgba.getchannel("A").filter(ImageFilter.GaussianBlur(radius=1))
                fg_rgba.putalpha(alpha)
                result = _composite_subject_realistic(fg_rgba, backdrop.convert("RGB"))
                guard_edited(image, result, prompt)
                edited_bytes = img_to_bytes(result)
                return {
                    "edited": base64.b64encode(edited_bytes).decode(),
                    "mask": "",
                    "strategy": "bg_scene_replace",
                    "interpretation": info,
                    "width": result.width,
                    "height": result.height,
                    "changed": True,
                }
            except HTTPException:
                raise
            except Exception as e:
                logging.warning(f"Scene background replacement failed: {e}")
        raise HTTPException(
            422,
            f"Background replacement requires either a supplied background image or a named plain color. This deployment does not generate new scenes.",
        )

    # ── Removals ──
    if info["action"] == "remove" and mask is not None:
        # Content-aware fill from surrounding pixels (OpenCV Telea) — the
        # removed area is reconstructed, never hallucinated.
        result = inpaint_region(image, mask)
        guard_edited(image, result, prompt)
        strategy = "remove_inpaint"
        edited_bytes = img_to_bytes(result)
        mask_bytes = img_to_bytes(mask, "PNG") if mask else b""
        return {
            "edited": base64.b64encode(edited_bytes).decode(),
            "mask": base64.b64encode(mask_bytes).decode() if mask_bytes else "",
            "strategy": strategy,
            "interpretation": info,
            "width": result.width,
            "height": result.height,
            "changed": True,
        }

    # ── Person / subject edits: deterministic, photorealistic, region-only ──
    # Hair, face, skin and clothing MUST NEVER go through generative SD — at high
    # strength it cartoon-ifies the backdrop and wrecks the face. We recolor /
    # retexture / retone ONLY the precisely-segmented subject region so the photo
    # stays a real photograph and everything else (including the background) is
    # left completely untouched.
    if mask is not None and not whole_image and (
        person_target or _detect_region_keyword(prompt) in ("clothing", "face", "hair")
    ):
        region = info.get("replacement", "") or prompt
        target_color = find_color(region) or find_color(prompt)
        cloth = tgt in ("outfit", "shirt", "pants", "dress") or \
            _detect_region_keyword(prompt) in ("clothing",)
        hair_face = tgt in ("face", "hair") or \
            _detect_region_keyword(prompt) in ("face", "hair")

        # ── Skin / complexion tone (lighter, darker, tanned, bronze) ──
        if (tgt == "face" or _detect_region_keyword(prompt) == "face") and target_color is None:
            if re.search(r"\b(lighter|fair|pale|brighter|whiten)\b", p_lower):
                factor = 1.16
            elif re.search(r"\b(darker|tan|tanned|bronze|sun[- ]?kissed)\b", p_lower):
                factor = 0.88
            else:
                factor = 1.06
            bright = ImageEnhance.Brightness(image).enhance(factor)
            result = feather_blend(image, bright, mask, radius=12)
            strategy = "skin_tone"
            edited_bytes = img_to_bytes(result)
            mask_bytes = img_to_bytes(mask, "PNG")
            return {
                "edited": base64.b64encode(edited_bytes).decode(),
                "mask": base64.b64encode(mask_bytes).decode(),
                "strategy": strategy,
                "interpretation": info,
                "width": result.width,
                "height": result.height,
                "changed": True,
            }

        # ── Hair colour change (e.g. hair to blonde/red) ──
        if hair_face and target_color is not None:
            rec = recolor_region(image, mask, target_color)
            rec = rec.filter(ImageFilter.GaussianBlur(radius=0.5))
            result = rec
            strategy = "hair_recolor"
            edited_bytes = img_to_bytes(result)
            mask_bytes = img_to_bytes(mask, "PNG")
            return {
                "edited": base64.b64encode(edited_bytes).decode(),
                "mask": base64.b64encode(mask_bytes).decode(),
                "strategy": strategy,
                "interpretation": info,
                "width": result.width,
                "height": result.height,
                "changed": True,
            }

        # ── Hair STYLE change (curly / short / long / straight) — realistic best
        # effort: retexture the hair band and add gentle contrast so the request
        # visibly takes effect while the face stays intact (no regeneration). ──
        if hair_face and target_color is None:
            styled = apply_fabric_texture(image, mask, region or "hair")
            styled = ImageEnhance.Contrast(styled).enhance(1.08)
            result = styled
            strategy = "hair_style"
            edited_bytes = img_to_bytes(result)
            mask_bytes = img_to_bytes(mask, "PNG")
            return {
                "edited": base64.b64encode(edited_bytes).decode(),
                "mask": base64.b64encode(mask_bytes).decode(),
                "strategy": strategy,
                "interpretation": info,
                "width": result.width,
                "height": result.height,
                "changed": True,
            }

        # ── Clothing colour change (explicit colour, NOT a different garment) ──
        # A different garment type (suit/blazer/formal/...) always falls through to
        # the real SD garment-swap branch below, even when a colour word is present.
        if cloth and target_color is not None and not _garment_swap_intent(prompt):
            rec = smart_recolor(image, mask, region) or recolor_region(image, mask, target_color)
            result = rec
            strategy = "smart_recolor"
            edited_bytes = img_to_bytes(result)
            mask_bytes = img_to_bytes(mask, "PNG")
            return {
                "edited": base64.b64encode(edited_bytes).decode(),
                "mask": base64.b64encode(mask_bytes).decode(),
                "strategy": strategy,
                "interpretation": info,
                "width": result.width,
                "height": result.height,
                "changed": True,
            }

        # ── Garment swap (dress→suit, shirt→tuxedo, "black suit", ...) ──
        # Prefer REAL regeneration: inpaint the referenced garment region with the
        # local SD model so a genuine suit/blazer actually appears (not a flat
        # recolour or a shirt+tie overlay painted on top). Only the masked region
        # is taken from the regeneration and composited over the untouched photo,
        # so the face/background stay exactly as the user uploaded them. A colour
        # word (e.g. "black suit") no longer forces a flat recolor — a different
        # garment type is always a real swap. Falls back to the deterministic
        # recolour+texture path when SD is unavailable.
        if cloth and (target_color is None or _garment_swap_intent(prompt)):
            swap_prompt = _build_garment_swap_prompt(prompt, region, tgt)
            # Protect the face/head AND the neck/shoulder band below the chin so it
            # is NEVER touched by garment regeneration: carve the protection zone
            # out of the garment mask. Neck protection (not just the face) stops SD
            # from painting a 'ghost chin' just under the head when it regenerates
            # the garment crop.
            face_mask = _face_neck_protection_mask(image)
            if face_mask is not None and mask is not None:
                face_arr = np.array(face_mask.convert("L"))
                mask_arr = np.array(mask.convert("L"))
                # Zero out mask pixels where the face/neck is (protect it)
                mask_arr = np.where(face_arr > 40, 0, mask_arr).astype(np.uint8)
                mask = Image.fromarray(mask_arr)
            # Formal suits are rendered by the deterministic two-piece painter below:
            # sd-turbo's single denoise step can't regenerate a believable suit, and
            # remapping colours onto the OLD garment would wash a "black suit" back
            # to the original dress tone. Everything else tries real SD first, then
            # falls back to the painter.
            suit_word = re.search(
                r"\b(black|charcoal|navy|dark|grey|gray|blue|brown)?\s*(tuxedo|tux|suit|blazer|formal|dinner\s+jacket|three-piece)\b",
                p_lower,
            )
            formal_suit = bool(suit_word)
            if suit_word:
                tone_desc = f"{suit_word.group(1)} {suit_word.group(2)}" if suit_word.group(1) else suit_word.group(0)
            else:
                tone_desc = region or tgt or "outfit"
            suit_tone = _garment_default_tone(tone_desc)
            if HAS_DIFFUSERS and not formal_suit:
                try:
                    # Lower strength (0.5) so only the garment region regenerates
                    # without pulling in face, hands, or background details. Higher
                    # values smeared the fabric and bled into the neck/chin.
                    sd = _apply_masked_sd_edit(image, mask, swap_prompt, style, strength=0.5, match_original=False, seam=20)
                    if sd is not None:
                        # Cross-verify: the edit must change the GARMENT region
                        # significantly (not a faint ghost), AND the FACE must be
                        # preserved (not altered by SD).
                        score = _region_mean_diff(image, sd, mask)
                        # Face preservation check: face region should be nearly identical.
                        face_score = _region_mean_diff(image, sd, face_mask) if face_mask is not None else 0.0
                        logging.info(f"garment_swap sd garment_score={score:.2f} face_score={face_score:.2f}")
                        if score >= 4.0 and face_score < 3.0:
                            result = sd
                            strategy = "garment_swap_sd"
                            edited_bytes = img_to_bytes(result)
                            mask_bytes = img_to_bytes(mask, "PNG")
                            return {
                                "edited": base64.b64encode(edited_bytes).decode(),
                                "mask": base64.b64encode(mask_bytes).decode(),
                                "strategy": strategy,
                                "interpretation": info,
                                "width": result.width,
                                "height": result.height,
                                "changed": True,
                            }
                except Exception as e:
                    logging.warning(f"SD garment swap failed, using fallback: {e}")
            # Deterministic painter (primary for formal suits, fallback otherwise):
            # recolor the garment to the requested tone with real fabric texture and
            # OPAQUE tailoring (no translucent overlay). `_garment_default_tone` is
            # fed the exact garment word from the prompt so a "black suit" stays
            # black and a "navy suit" stays navy.
            rec = recolor_region(image, mask, suit_tone)
            rec = apply_fabric_texture(rec, mask, tone_desc)
            if formal_suit:
                rec = _add_suit_details(rec, mask, suit_tone)
            result = rec
            strategy = "garment_swap"
            edited_bytes = img_to_bytes(result)
            mask_bytes = img_to_bytes(mask, "PNG")
            return {
                "edited": base64.b64encode(edited_bytes).decode(),
                "mask": base64.b64encode(mask_bytes).decode(),
                "strategy": strategy,
                "interpretation": info,
                "width": result.width,
                "height": result.height,
                "changed": True,
            }

        # ── Generic region recolor with a named colour (safety net) ──
        if target_color is not None:
            result = recolor_region(image, mask, target_color)
            strategy = "smart_recolor"
            edited_bytes = img_to_bytes(result)
            mask_bytes = img_to_bytes(mask, "PNG")
            return {
                "edited": base64.b64encode(edited_bytes).decode(),
                "mask": base64.b64encode(mask_bytes).decode(),
                "strategy": strategy,
                "interpretation": info,
                "width": result.width,
                "height": result.height,
                "changed": True,
            }

    # ── Whole-image color change ──
    # ONLY when the user explicitly asked to change the entire image (mentions the
    # image/photo itself, or names no specific region/object at all). If the user
    # asked for a REGION (e.g. "the shirt") but region detection failed, we must
    # NOT recolor everything — that would destroy the rest of the image.
    if info["action"] in ("edit", "recolor", "replace", "add"):
        whole_color = find_color(prompt)
        if whole_color is not None and (whole_image or tgt == "auto"):
            result = recolor_region(image, Image.new("L", image.size, 255), whole_color)
            strategy = "recolor_all"
            edited_bytes = img_to_bytes(result)
            return {
                "edited": base64.b64encode(edited_bytes).decode(),
                "mask": "",
                "strategy": strategy,
                "interpretation": info,
                "width": result.width,
                "height": result.height,
                "changed": True,
            }

    # ── Generative region edit (photorealistic by default) ──
    # For "turn X into Y" / "change the [region] to [thing]" requests the
    # deterministic pipelines can't fulfil, regenerate with SD img2img and keep
    # ONLY the masked region, so the rest of the photo stays exactly as-is.
    # Stylized looks apply solely when the user explicitly requested one.
    # For named person subjects we NEVER fall back to a whole-image edit (that
    # would cartoon-ify the background / worsen the face) — always pin a region
    # mask so only the referenced subject is touched.
    if mask is None and person_target:
        mask = _head_region_mask(image) if tgt in ("face", "hair") else create_upper_body_mask(image)
    # Person / subject edits are handled deterministically above (region-only,
    # photorealistic). Generative SD is intentionally NOT used for people — at
    # high strength it cartoon-ifies the backdrop and wrecks the face. Only
    # non-person edits may fall back to SD.
    if HAS_DIFFUSERS and info["action"] in ("replace", "add", "edit") and not person_target:
        style = detect_explicit_art_style(prompt)
        result = _apply_masked_sd_edit(image, mask, prompt, style)
        if result is not None:
            guard_edited(image, result, prompt, mask)
            edited_bytes = img_to_bytes(result)
            mask_bytes = img_to_bytes(mask, "PNG") if mask else b""
            return {
                "edited": base64.b64encode(edited_bytes).decode(),
                "mask": base64.b64encode(mask_bytes).decode() if mask_bytes else "",
                "strategy": "sd_masked_region" if mask is not None else "sd_whole_edit",
                "interpretation": info,
                "width": result.width,
                "height": result.height,
                "changed": True,
            }

    # Nothing deterministic matches this request. Decline honestly — never echo
    # the original image and never substitute a different effect.
    raise HTTPException(
        422,
        f"The request '{prompt}' needs generative processing that this self-hosted deployment does not perform. Supported edits: recoloring, object removal, background removal or named-color/supplied-image replacement, brightness/contrast, filters.",
    )

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

            title = title_el.get_text(" ", strip=True) if title_el else ""
            link = title_el.get("href", "") if title_el else ""
            # DuckDuckGo wraps links in redirect
            if "uddg=" in link:
                from urllib.parse import parse_qs, urlparse
                parsed = urlparse(link)
                qs = parse_qs(parsed.query)
                link = qs.get("uddg", [""])[0]
            snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""

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
            title = title_el.get_text(" ", strip=True) if title_el else ""
            snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""
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
            snippet = re.sub(r"<[^>]+>", " ", r.get("snippet", ""))
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
        "gpu": False,
        "clip": False,
        "upscaler": True,
        "voice_tts": HAS_EDGE_TTS,
        "voice_edit": HAS_PYDUB,
    }

# ---------------------------------------------------------------------------
# Async edit jobs — Cloudflare's edge terminates proxied/tunneled requests at
# ~100s (524). Long edits therefore run as background jobs: POST with
# async_mode=1 returns {job_id}, and the caller polls GET /jobs/{job_id}
# until status is done/error.
# ---------------------------------------------------------------------------
import time as _time
import uuid as _uuid
import threading as _threading

_EDIT_JOBS = {}
_EDIT_JOBS_LOCK = _threading.Lock()
_JOB_TTL = 1800
# Jobs are mirrored to disk so a container restart never loses a running edit.
_JOB_DIR = os.path.join(tempfile.gettempdir(), "acronous_edit_jobs")
os.makedirs(_JOB_DIR, exist_ok=True)

def _job_path(job_id: str) -> str:
    return os.path.join(_JOB_DIR, f"{job_id}.json")

def _persist_job(job_id: str, payload: dict):
    try:
        with open(_job_path(job_id), "w") as f:
            json.dump(payload, f)
    except Exception:
        pass

def _load_persisted_job(job_id: str):
    try:
        if os.path.exists(_job_path(job_id)):
            with open(_job_path(job_id)) as f:
                return json.load(f)
    except Exception:
        pass
    return None

def _start_edit_job(fn, args):
    job_id = _uuid.uuid4().hex
    _persist_job(job_id, {"status": "queued", "ts": _time.time()})
    def runner():
        try:
            result = fn(*args)
            payload = {"status": "done", "result": result, "ts": _time.time()}
        except HTTPException as e:
            payload = {"status": "error", "code": e.status_code, "detail": str(e.detail)[:300], "ts": _time.time()}
        except Exception as e:
            payload = {"status": "error", "code": 500, "detail": str(e)[:300], "ts": _time.time()}
        with _EDIT_JOBS_LOCK:
            _EDIT_JOBS[job_id] = payload
        _persist_job(job_id, payload)
        now = _time.time()
        with _EDIT_JOBS_LOCK:
            for k in [k for k, v in _EDIT_JOBS.items() if v.get("ts", 0) < now - _JOB_TTL]:
                _EDIT_JOBS.pop(k, None)
        try:
            for f in os.listdir(_JOB_DIR):
                fp = os.path.join(_JOB_DIR, f)
                try:
                    if f.endswith(".json") and _time.time() - os.path.getmtime(fp) > _JOB_TTL:
                        os.remove(fp)
                except Exception:
                    pass
        except Exception:
            pass
    _threading.Thread(target=runner, daemon=True).start()
    return {"job_id": job_id, "status": "queued"}

@app.get("/jobs/{job_id}")
async def api_job_status(job_id: str):
    with _EDIT_JOBS_LOCK:
        job = _EDIT_JOBS.get(job_id)
    if job is None:
        job = _load_persisted_job(job_id)
    if not job:
        raise HTTPException(404, "Unknown or expired job")
    out = dict(job)
    if job["status"] in ("done", "error"):
        with _EDIT_JOBS_LOCK:
            _EDIT_JOBS.pop(job_id, None)
        try:
            os.remove(_job_path(job_id))
        except Exception:
            pass
    return out

def _preload_edit_models():
    """Warm rembg sessions in the background so first edits aren't slow."""
    try:
        if HAS_REMBG:
            tiny = Image.new("RGB", (64, 64), (120, 120, 120))
            rembg_remove(img_to_bytes(tiny), session=rembg_session)
            logging.info("rembg session warmed")
    except Exception as e:
        logging.warning(f"rembg preload failed: {e}")

_threading.Thread(target=_preload_edit_models, daemon=True).start()

@app.post("/edit")
async def api_edit(
    file: UploadFile = File(...),
    prompt: str = Form(...),
    async_mode: str = Form(""),
):
    """Edit image using natural language prompt."""
    data = await file.read()
    if not data:
        raise HTTPException(400, "No image data")
    if not prompt.strip():
        raise HTTPException(400, "No prompt")
    if async_mode:
        return _start_edit_job(edit_image, (data, prompt))
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

async def _resolve_vision_edit(image, image_b64, prompt):
    """Localize the exact region the user wants to change via the self-hosted
    vision model. Returns (scope, mask) where mask is a feathered L mask for the
    referenced region (or None to let the canonical pipeline decide)."""
    scope, mask = "region", None
    try:
        ok = await is_ollama_available(timeout=2)
        if not ok:
            return scope, mask
        loc = await _asyncio.to_thread(localize_region_via_vision, image_b64, prompt, 25)
        scope = loc.get("scope", "region")
        bbox = loc.get("bbox")
        if scope == "region" and bbox:
            m = mask_from_bbox(image, bbox)
            if m is not None:
                arr = np.array(m)
                cover = float(np.mean(arr > 30)) / 255.0
                # Reject degenerate localizations (empty or ~whole image).
                if 0.01 <= cover <= 0.95:
                    mask = m
                else:
                    mask = None
        elif scope in ("background", "whole"):
            mask = None
    except Exception as e:
        logging.warning(f"vision locate failed: {e}")
        scope, mask = "region", None
    return scope, mask


def _resolve_vision_edit_sync(image, image_b64, prompt):
    """Synchronous twin of _resolve_vision_edit for use inside worker threads."""
    scope, mask = "region", None
    try:
        loc = localize_region_via_vision(image_b64, prompt, 25)
        scope = loc.get("scope", "region")
        bbox = loc.get("bbox")
        if scope == "region" and bbox:
            m = mask_from_bbox(image, bbox)
            if m is not None:
                arr = np.array(m)
                cover = float(np.mean(arr > 30)) / 255.0
                if 0.01 <= cover <= 0.95:
                    mask = m
                else:
                    mask = None
        elif scope in ("background", "whole"):
            mask = None
    except Exception as e:
        logging.warning(f"sync vision locate failed: {e}")
        scope, mask = "region", None
    return scope, mask


def _vision_edit_job(data, prompt):
    """Ran as a background job: localize the region, then edit only it."""
    image = bytes_to_img(data).convert("RGB")
    image_b64 = img_to_b64(image, "JPEG")
    scope, mask = _resolve_vision_edit_sync(image, image_b64, prompt)
    return edit_image(data, prompt, precomputed_mask=mask, edit_scope=scope)


@app.post("/vision/edit")
async def api_vision_edit(
    file: UploadFile = File(...),
    prompt: str = Form(...),
    async_mode: str = Form(""),
):
    """
    Ollama vision-guided image editing.
    Uses LLaVA to analyze the image and generate structured edit instructions,
    then applies the canonical editing pipeline. With async_mode=1 the request
    returns a job_id immediately and skips the (slow) LLaVA hint step — the
    deterministic keyword pipeline handles targeting on its own.
    """
    data = await file.read()
    if not data:
        raise HTTPException(400, "No image data")
    if not prompt.strip():
        raise HTTPException(400, "No prompt")

    image = bytes_to_img(data).convert("RGB")
    image_b64 = img_to_b64(image, "JPEG")

    # Async mode: run the vision-localized edit as a background job so the
    # exact referenced region is still targeted (never the whole image).
    if async_mode:
        return _start_edit_job(_vision_edit_job, (data, prompt))

    # Localize the exact region the user referenced so only that area is edited;
    # everything else in the image is preserved untouched.
    scope, mask = await _resolve_vision_edit(image, image_b64, prompt)
    try:
        return edit_image(data, prompt, precomputed_mask=mask, edit_scope=scope)
    except HTTPException:
        raise
    except Exception as e:
        logging.warning(f"vision edit failed: {e}")
        if mask is not None:
            raise HTTPException(422, f"The edit '{prompt}' could not be applied reliably. Please describe a more specific change.")
        raise HTTPException(422, f"The edit '{prompt}' could not be localized to a specific region. Name the exact object or area to change.")

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

    # Localize the exact region the user referenced so only that area is edited;
    # everything else in the image is preserved untouched.
    scope, mask = await _resolve_vision_edit(image, image_b64, prompt)
    try:
        return edit_image(data, prompt, precomputed_mask=mask, edit_scope=scope)
    except HTTPException:
        raise
    except Exception as e:
        logging.warning(f"vision edit json failed: {e}")
        if mask is not None:
            raise HTTPException(422, f"The edit '{prompt}' could not be applied reliably. Please describe a more specific change.")
        raise HTTPException(422, f"The edit '{prompt}' could not be localized to a specific region. Name the exact object or area to change.")

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

def _cover_resize(bg: "Image.Image", width: int, height: int) -> "Image.Image":
    """Scale-and-crop bg so it fully covers a width×height canvas (centered)."""
    scale = max(width / max(bg.width, 1), height / max(bg.height, 1))
    new_w = max(width, int(bg.width * scale + 0.5))
    new_h = max(height, int(bg.height * scale + 0.5))
    resized = bg.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - width) // 2
    top = (new_h - height) // 2
    return resized.crop((left, top, left + width, top + height))

@app.post("/composite")
async def api_composite(
    foreground: UploadFile = File(...),
    background: UploadFile = File(...),
):
    """
    Alpha-composite a transparent-PNG foreground over a cover-resized background.
    Pure Pillow — no SD/diffusers dependency.
    """
    fg_data = await foreground.read()
    bg_data = await background.read()
    if not fg_data:
        raise HTTPException(400, "No foreground data")
    if not bg_data:
        raise HTTPException(400, "No background data")
    try:
        fg = Image.open(io.BytesIO(fg_data)).convert("RGBA")
        bg = Image.open(io.BytesIO(bg_data)).convert("RGB")
        bg = _cover_resize(bg, fg.width, fg.height)
        result = Image.alpha_composite(bg.convert("RGBA"), fg).convert("RGB")
        edited_bytes = img_to_bytes(result)
        return {
            "edited": base64.b64encode(edited_bytes).decode(),
            "strategy": "composite",
            "width": result.width,
            "height": result.height,
            "changed": True,
        }
    except HTTPException:
        raise
    except Exception as e:
        logging.warning(f"Composite failed: {e}")
        raise HTTPException(500, f"Composite failed: {e}")

def _composite_subject_realistic(subject, bg):
    """Composite a rembg cutout (RGBA) onto a background so it reads as one real
    photograph: photometric harmonization (LAB mean/std match) + contact shadow
    + depth-of-field + film-grain match.

    The subject's lighting, colour temperature, sharpness and edge transition
    are matched to the backdrop so the composite looks like it was shot in
    front of the new scene — never a pasted AI cutout.

    Anti-translucency measures:
      - Binary alpha threshold: any pixel above 30% opacity is forced to 100%
        opaque, so the subject body NEVER appears washed-out or see-through.
      - Only a 1.5px feather at the very rim softens the anti-aliased edge.
      - Color temperature is matched from the ORIGINAL photo (not the background
        edit) so the subject's skin/clothing tones stay natural.
    """
    from PIL import ImageFilter as _IF
    bg = bg.convert("RGB")
    subject = subject.convert("RGBA").resize(bg.size, Image.LANCZOS)
    sarr = np.array(subject, dtype=np.float32)

    # HARD ALPHA: threshold at 30% to eliminate translucent regions entirely.
    alpha_raw = np.array(subject.split()[3], dtype=np.float32) / 255.0
    # Interior: fully opaque where any significant alpha exists
    alpha_binary = np.where(alpha_raw > 0.30, 1.0, 0.0).astype(np.float32)
    # Edge: narrow feather only at the transition (1.5px blur)
    alpha_edge = np.array(subject.split()[3].filter(_IF.GaussianBlur(1.5)), dtype=np.float32) / 255.0
    alpha_edge = np.where(alpha_edge > 0.30, 1.0, np.clip(alpha_edge * 2.0, 0, 1))
    # Alpha used for compositing
    alpha = np.clip(alpha_edge[:, :, None], 0, 1)
    alpha_2d = alpha_edge
    subj = sarr[:, :, :3]
    bg_arr = np.array(bg, dtype=np.float32)

    # ── 1. Photometric harmonization (LAB mean + std match) — match to the
    # original photo's colour temperature, not the new background, so skin
    # tones and fabric remain natural.
    bg_mean = bg_arr.reshape(-1, 3).mean(0)
    bg_std = bg_arr.reshape(-1, 3).std(0) + 1e-4
    mask_sum = float(np.sum(alpha_binary)) + 1e-3
    subj_mean = (subj * alpha_binary[:, :, None]).reshape(-1, 3).sum(0) / mask_sum
    subj_std = np.sqrt((((subj - subj_mean) ** 2) * alpha_binary[:, :, None]).reshape(-1, 3).sum(0) / mask_sum) + 1e-4
    # Gentle pull toward bg (20%) — enough to kill green-screen cast but
    # keeps the subject's own lighting and skin tones intact.
    gain = np.clip(bg_std / subj_std, 0.92, 1.15)
    shift = (bg_mean - subj_mean) * 0.20
    subj_n = (subj - subj_mean) * gain + subj_mean + shift
    subj_n = np.clip(subj_n, 0, 255)

    # ── 2. Contact shadow — soft, directional-bias-free grounding shadow
    # beneath the subject silhouette.
    amask = subject.split()[3].filter(_IF.GaussianBlur(12))
    a2 = np.array(amask, dtype=np.float32) / 255.0
    a2_hard = np.where(a2 > 0.30, 1.0, a2).astype(np.float32)
    edge_shadow = np.clip(a2_hard - alpha_edge, 0, 1)[:, :, None] * 0.18
    bg_comp = bg_arr * (1 - edge_shadow * 0.6)

    # ── 3. Depth-of-field: subtle background blur outside the subject.
    bg_blur = np.array(bg.filter(_IF.GaussianBlur(1.5)), dtype=np.float32)
    dof_t = np.clip((0.50 - alpha_edge) / 0.35, 0, 1)[:, :, None]
    bg_comp = bg_comp * (1 - dof_t) + bg_blur * dof_t

    # ── 4. Composite with hard interior + feathered edge.
    out = subj_n * alpha + bg_comp * (1 - alpha)

    # ── 5. Edge light wrap — thin highlight along the rim to prevent dark halo.
    light_wrap = np.clip((a2_hard - alpha_edge)[:, :, None] * 0.08, 0, 1)
    out = out * (1 - light_wrap) + bg_comp * light_wrap * 0.6 + out * light_wrap * 0.4

    # ── 6. Film-grain match: transfer backdrop's local noise onto subject.
    grain_mask = np.clip((alpha_edge - 0.1) / 0.9, 0, 1)[:, :, None]
    hi_bg = bg_arr - bg_blur
    out = np.where(grain_mask > 0, out + hi_bg * 0.30 * grain_mask, out)
    out = np.clip(out, 0, 255).astype(np.uint8)

    # ── 7. Final anti-translucency: force subject interior fully opaque.
    # Any pixel that was >30% in the raw alpha is now 100% opaque.
    comp_alpha = alpha_binary[:, :, None]
    out = out * comp_alpha + bg_comp * (1 - comp_alpha)
    out = np.clip(out, 0, 255).astype(np.uint8)
    return Image.fromarray(out)


@app.post("/background/edit")
async def api_background_edit(
    file: UploadFile = File(...),
    prompt: str = Form(...),
    bg_image: str = Form(""),
):
    """
    Replace the image background with a caller-supplied generated background
    or, when no background is supplied, synthesize one from the prompt scene.
    The subject is cut out with rembg and composited over the new background —
    every original subject pixel is preserved exactly.
    """
    data = await file.read()
    if not data:
        raise HTTPException(400, "No image data")
    # bg_image optional — generate scene backdrop when not supplied
    try:
        orig = bytes_to_img(data)
        cut = None
        if HAS_REMBG:
            try:
                out = rembg_remove(img_to_bytes(orig), session=rembg_session)
                cut = Image.open(io.BytesIO(out)).convert("RGBA")
            except Exception as e:
                logging.warning(f"Background cutout failed: {e}")
        if cut is None:
            alpha = segment_foreground(orig.convert("RGB"))
            if alpha is not None:
                cut = orig.convert("RGBA")
                cut.putalpha(alpha)
        if cut is None:
            raise HTTPException(422, "Could not isolate the subject for background replacement.")

        if bg_image and bg_image.strip():
            bg_raw = Image.open(io.BytesIO(base64.b64decode(bg_image))).convert("RGB")
            bg = _cover_resize(bg_raw, cut.width, cut.height)
        else:
            # Generate backdrop scene from the prompt (e.g., "beach sunset" → ocean at sunset)
            bg_prompt = re.sub(r'^\s*(change|replace|set|make|turn|convert|swap|switch|put|give)\s+(the\s+)?(background|backdrop|scene|setting|surroundings|environment)\s*(to|into|with|as|for)?\s*', '', prompt, flags=re.IGNORECASE).strip() or prompt
            bg_prompt = bg_prompt[:500].strip() or "scenic landscape"
            # Photorealistic SD backdrop by default; stylized only on explicit ask.
            bg_style = detect_explicit_art_style(bg_prompt) or detect_explicit_art_style(prompt)
            bg_raw = _generate_sd_backdrop(bg_prompt, bg_style, cut.width, cut.height)
            if bg_raw is None:
                bg_raw, _ = _render_generated_scene(bg_prompt, cut.width, cut.height, 0)
            bg = _cover_resize(bg_raw, cut.width, cut.height)

        # Feather the cutout edge slightly so the composite looks natural
        alpha_ch = cut.split()[3].filter(ImageFilter.GaussianBlur(radius=2))
        cut.putalpha(alpha_ch)

        # Composite with real-photo lighting/colour matching + contact shadow so
        # the subject sits naturally in the new backdrop (not a flat cutout).
        result = _composite_subject_realistic(cut, bg).convert("RGB")
        guard_edited(orig.convert("RGB"), result, prompt)
        edited_bytes = img_to_bytes(result)
        return {
            "edited": base64.b64encode(edited_bytes).decode(),
            "strategy": "background_replace",
            "width": result.width,
            "height": result.height,
            "changed": True,
        }
    except HTTPException:
        raise
    except Exception as e:
        logging.warning(f"Background edit failed: {e}")
        raise HTTPException(500, f"Background edit failed: {e}")

@app.post("/generate")
async def api_generate(
    prompt: str = Form(...),
    width: int = Form(1024),
    height: int = Form(1024),
    enhance: bool = Form(True),
):
    raise HTTPException(
        501,
        "Text-to-image generation requires a generative model and is not performed in this fully self-hosted deployment.",
    )

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

@app.post("/vision/analyze")
async def api_vision_analyze(
    file: UploadFile = File(...),
    prompt: str = Form("Describe this image in detail."),
):
    """Analyze an image with the self-hosted Ollama vision model (LLaVA)."""
    data = await file.read()
    if not data:
        raise HTTPException(400, "No image data")
    img = bytes_to_img(data).convert("RGB")
    if max(img.size) > 1024:
        img = resize_max(img, 1024)
    analysis = await call_ollama_vision(img_to_b64(img, "JPEG"), prompt, timeout=90)
    if not analysis:
        raise HTTPException(503, "Vision model unavailable")
    return {"analysis": analysis}


@app.post("/upscale")
async def api_upscale(
    file: UploadFile = File(...),
    scale: int = Query(2, description="Upscale factor (2 or 4)"),
):
    """High-quality Lanczos upscale (pure local processing)."""
    data = await file.read()
    img = bytes_to_img(data).convert("RGB")
    result = upscale_image(img, scale)
    return {
        "edited": img_to_b64(result, "PNG"),
        "width": result.width,
        "height": result.height,
        "scale": max(2, min(int(scale), 4)),
    }

@app.get("/capabilities")
async def capabilities():
    """Return available capabilities."""
    return {
        "rembg": HAS_REMBG,
        "gpu": False,
        "clip": False,
        "upscaler": True,
        "video": shutil.which("ffmpeg") is not None,
        "voice_tts": HAS_EDGE_TTS,
        "voice_edit": HAS_PYDUB,
        "image_gen": True,
        "video_narration": HAS_EDGE_TTS,
    }

# ---------------------------------------------------------------------------
# Video Generation — fully self-hosted, DETERMINISTIC renderer.
# No generative model: videos are rendered locally (Pillow frames -> ffmpeg
# h264). Synthetic requests are turned into multi-shot scenes by the scene
# engine (parsed from the prompt), with optional edge-tts narration muxed in.
# ---------------------------------------------------------------------------

def _video_font(size):
    for p in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, int(size))
            except Exception:
                pass
    return ImageFont.load_default()


_LOGO_MARK_CACHE = {}

def _load_logo_mark(frame_w, frame_h):
    """App logo (RGBA) resized for a very tiny bottom-right watermark, visible only on zoom."""
    target_h = max(5, int(frame_h * 0.009))
    cached = _LOGO_MARK_CACHE.get(target_h)
    if cached is not None:
        return cached
    for p in ("/app/assets/logo.png", "assets/logo.png", "/app/logo.png"):
        if os.path.exists(p):
            try:
                logo = Image.open(p).convert("RGBA")
                ratio = logo.width / max(1, logo.height)
                logo = logo.resize((max(8, int(target_h * ratio)), target_h), Image.LANCZOS)
                if len(_LOGO_MARK_CACHE) > 8:
                    _LOGO_MARK_CACHE.clear()
                _LOGO_MARK_CACHE[target_h] = logo
                return logo
            except Exception:
                break
    return None


def _stamp_logo(img):
    """Paste the app logo bottom-right on a very tiny translucent pill — visible only when zoomed."""
    logo = _load_logo_mark(img.width, img.height)
    if logo is None:
        return img
    # Very subtle: low opacity so it does not dominate the frame
    alpha = logo.split()[3]
    alpha = alpha.point(lambda v: int(v * 0.30))
    logo.putalpha(alpha)
    pad_lg = max(1, int(img.width * 0.0025))
    margin = max(3, int(img.width * 0.006))
    lw, lh = logo.size
    pill_w, pill_h = lw + pad_lg * 2, lh + pad_lg * 2
    x0, y0 = img.width - pill_w - margin, img.height - pill_h - margin
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rounded_rectangle(
        [x0, y0, x0 + pill_w, y0 + pill_h],
        radius=int(pill_h * 0.32),
        fill=(10, 10, 14, 22),
        outline=(255, 255, 255, 8),
        width=1,
    )
    overlay.paste(logo, (x0 + pad_lg, y0 + pad_lg), logo)
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def _wrap_text_for_video(draw, text, font, max_w):
    lines = []
    for para in (text or "").splitlines() or [""]:
        words = para.split()
        if not words:
            lines.append("")
            continue
        cur = words[0]
        for w in words[1:]:
            trial = cur + " " + w
            if draw.textlength(trial, font=font) <= max_w:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines

def _gradient_frame(w, h, top_rgb, bottom_rgb):
    base = Image.new("RGB", (1, h))
    px = base.load()
    for y in range(h):
        t = y / max(1, h - 1)
        px[0, y] = tuple(int(top_rgb[i] + (bottom_rgb[i] - top_rgb[i]) * t) for i in range(3))
    return base.resize((w, h))

def _hls_to_rgb255(h, l, s):
    import colorsys
    r, g, b = colorsys.hls_to_rgb((h % 360) / 360.0,
                                  min(1.0, max(0.0, l)),
                                  min(1.0, max(0.0, s)))
    return (int(r * 255), int(g * 255), int(b * 255))

def _cover_fit(im, w, h, zoom):
    scale = max((w * zoom) / im.width, (h * zoom) / im.height)
    nw = max(2, int(im.width * scale))
    nh = max(2, int(im.height * scale))
    canvas = Image.new("RGB", (nw, nh))
    canvas.paste(im.convert("RGB"), ((nw - im.width) // 2, (nh - im.height) // 2))
    left = max(0, (nw - w) // 2)
    top = max(0, (nh - h) // 2)
    return canvas.crop((left, top, left + w, top + h))

def _draw_caption(frame_img, caption, font):
    if not caption:
        return frame_img
    W, H = frame_img.size
    overlay = Image.new("RGBA", frame_img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    lines = _wrap_text_for_video(od, caption, font, int(W * 0.82))
    lh = max(1, int(font.size * 1.35))
    block_h = lh * len(lines)
    y0 = min(H - block_h - 8, int(H * 0.86) - block_h // 2)
    od.rectangle([0, max(0, y0 - int(lh * 0.55)), W,
                  min(H, y0 + block_h + int(lh * 0.55))], fill=(8, 8, 12, 150))
    y = y0
    for ln in lines:
        tw = od.textlength(ln, font=font)
        od.text(((W - tw) // 2, y), ln, font=font, fill=(245, 245, 250, 255))
        y += lh
    return Image.alpha_composite(frame_img.convert("RGBA"), overlay).convert("RGB")

# ---------------------------------------------------------------------------
# Scene Engine — self-hosted procedural text→image synthesis (torch-free).
# Parses the user's prompt into a structured scene (time of day, terrain,
# weather, elements, palette, style) and renders layered artwork with
# Pillow + numpy. Fully deterministic per prompt; no external model service.
# ---------------------------------------------------------------------------

_SCENE_TIME_KEYWORDS = [
    ('sunset', ['sunset', 'dusk', 'twilight', 'golden hour', 'evening', 'sundown']),
    ('sunrise', ['sunrise', 'dawn', 'daybreak', 'early morning']),
    ('night', ['night', 'midnight', 'moonlit', 'moonlight', 'starry', 'stargazing',
               'nocturnal', 'aurora', 'fireflies']),
    ('day', ['noon', 'midday', 'afternoon', 'daylight', 'bright day', 'sunny day']),
]

_SCENE_TERRAIN_KEYWORDS = {
    'ocean': ['ocean', 'sea', 'beach', 'coast', 'coastline', 'shore', 'wave', 'seaside',
              'island', 'tropical', 'bay', 'harbor', 'cliff over water'],
    'lake': ['lake', 'river', 'pond', 'waterfall', 'creek', 'stream', 'reflection'],
    'mountains': ['mountain', 'mountains', 'peak', 'peaks', 'alps', 'himalaya', 'summit',
                  'valley', 'canyon', 'highland', 'fjord', 'ridge'],
    'forest': ['forest', 'jungle', 'woods', 'pine', 'pines', 'trees', 'tree', 'woodland',
               'bamboo', 'redwood', 'rainforest'],
    'city': ['city', 'skyline', 'urban', 'building', 'buildings', 'skyscraper',
             'skyscrapers', 'downtown', 'metropolis', 'town', 'street'],
    'desert': ['desert', 'dune', 'dunes', 'sahara', 'oasis', 'cactus', 'sand dunes'],
    'meadow': ['meadow', 'field', 'fields', 'grassland', 'prairie', 'flower field',
               'lavender', 'tulip', 'sunflower', 'garden', 'pasture', 'countryside'],
    'space': ['space', 'galaxy', 'nebula', 'cosmos', 'planet', 'universe', 'outer space',
              'asteroid', 'saturn', 'milky way'],
}

_SCENE_ELEMENT_KEYWORDS = {
    'birds': ['bird', 'birds', 'flock', 'seagull', 'eagle'],
    'boat': ['boat', 'ship', 'sailboat', 'sail', 'yacht', 'canoe', 'fishing boat'],
    'moon': ['moon', 'full moon', 'crescent', 'lunar'],
    'lighthouse': ['lighthouse'],
    'cabin': ['cabin', 'cottage', 'hut', 'house', 'home', 'farmhouse', 'chalet'],
    'snow': ['snow', 'snowy', 'winter', 'ice', 'arctic', 'frozen', 'glacier'],
}

# Explicit art-style requests ONLY — anything else renders photorealistic.
_STYLE_KEYWORDS = [
    ('neon', ['neon', 'cyberpunk', 'synthwave', 'retrowave', 'vaporwave']),
    ('watercolor', ['watercolor', 'watercolour', 'aquarelle']),
    ('pixel', ['pixel art', '8-bit', '8 bit', '16-bit']),
    ('anime', ['anime', 'manga', 'ghibli', 'cartoon', 'comic book', 'comic style']),
    ('painterly', ['oil paint', 'oil on canvas', 'acrylic paint', 'painted', 'painterly',
                   'drawing', 'drawn', 'sketch', 'sketched', 'illustration', 'illustrated',
                   'hand-drawn', 'hand drawn', 'in the style of a painting']),
    ('minimal', ['minimal', 'minimalist', 'flat design', 'simple flat']),
    ('vivid', ['vivid', 'vibrant', 'saturated', 'colorful', 'colourful']),
    ('moody', ['moody', 'melancholic', 'somber', 'noir']),
]

_PALETTE_HUE_KEYWORDS = [
    ('pink', ['pink', 'rose', 'blossom', 'cherry blossom']),
    ('purple', ['purple', 'violet', 'lavender', 'lilac', 'mauve']),
    ('blue', ['blue', 'azure', 'cobalt', 'cyan']),
    ('green', ['green', 'emerald', 'jade', 'mint']),
    ('orange', ['orange', 'amber', 'tangerine', 'peach']),
    ('gold', ['gold', 'golden', 'honey', 'yellow']),
    ('red', ['red', 'crimson', 'scarlet', 'ruby']),
]


def _scene_rng(seed_text, salt=0):
    import hashlib as _hl
    digest = _hl.sha256(f"{seed_text}::{salt}".encode("utf-8")).hexdigest()
    return np.random.RandomState(int(digest[:12], 16) % (2 ** 32))


def _parse_scene(prompt, style_override=None):
    """Turn free text into a structured scene the renderer can draw."""
    p = (prompt or "").lower()

    time_of_day = None
    for key, words in _SCENE_TIME_KEYWORDS:
        if any(w in p for w in words):
            time_of_day = key
            break

    terrain = []
    for key, words in _SCENE_TERRAIN_KEYWORDS.items():
        if any(w in p for w in words):
            terrain.append(key)
    if not terrain:
        # No explicit terrain — derive a tasteful default from the prompt hash.
        rng = _scene_rng(p, 'terrain')
        terrain = [str(rng.choice(['mountains', 'ocean', 'forest', 'meadow']))]
    if 'space' in terrain:
        time_of_day = 'space'

    if time_of_day is None:
        defaults = {
            'city': 'night',      # lit windows read best at night
            'ocean': 'sunset',
            'lake': 'sunset',
            'space': 'space',
        }
        for t in terrain:
            if t in defaults:
                time_of_day = defaults[t]
                break
        if time_of_day is None:
            time_of_day = 'day'
        if time_of_day == 'day':
            rng = _scene_rng(p, 'time')
            time_of_day = str(rng.choice(['day', 'sunset', 'day']))

    weather = 'clear'
    if any(w in p for w in ['storm', 'thunder', 'lightning', 'tempest']):
        weather = 'storm'
    elif any(w in p for w in ['rain', 'rainy', 'drizzle', 'monsoon', 'downpour']):
        weather = 'rain'
    elif any(w in p for w in ['fog', 'foggy', 'mist', 'misty', 'haze', 'hazy']):
        weather = 'fog'
    elif any(w in p for w in ['cloud', 'cloudy', 'overcast']):
        weather = 'cloudy'
    if weather != 'clear' and time_of_day in (None, 'day') and 'snow' not in p:
        pass  # keep chosen weather even in daytime

    elements = set()
    for key, words in _SCENE_ELEMENT_KEYWORDS.items():
        if any(w in p for w in words):
            elements.add(key)
    if 'moon' in elements and time_of_day not in ('night', 'space'):
        time_of_day = 'night'
    if time_of_day == 'night' and 'space' not in terrain:
        elements.add('stars')
    if time_of_day == 'night' and 'forest' in terrain:
        elements.add('fireflies')

    hue_key = None
    for key, words in _PALETTE_HUE_KEYWORDS:
        if any(w in p for w in words):
            hue_key = key
            break

    style = 'realistic'  # photorealistic unless an art style is explicitly asked
    if style_override:
        style = str(style_override).strip().lower()
        if style not in {'realistic', 'neon', 'watercolor', 'minimal', 'pixel',
                         'anime', 'painterly', 'vivid', 'moody'}:
            style = 'realistic'
    else:
        for key, words in _STYLE_KEYWORDS:
            if any(w in p for w in words):
                style = key
                break
    if style == 'neon' and time_of_day != 'night' and 'space' not in terrain:
        time_of_day = 'night'  # neon needs darkness to glow

    return {
        'prompt': prompt or '',
        'time': time_of_day,
        'weather': weather,
        'terrain': terrain,
        'elements': sorted(elements),
        'hue': hue_key,
        'style': style,
    }


def _scene_palette(scene):
    """Return (sky_stops, light_color, ground_tint, accent) for the scene."""
    t = scene['time']
    hue = scene['hue']
    palettes = {
        'day':     [(0.0, (58, 128, 205)), (0.62, (126, 182, 233)), (1.0, (214, 235, 246))],
        'sunrise': [(0.0, (86, 84, 158)), (0.55, (232, 148, 140)), (1.0, (255, 208, 150))],
        'sunset':  [(0.0, (44, 42, 92)), (0.52, (180, 82, 122)), (0.80, (255, 138, 94)), (1.0, (255, 190, 120))],
        'night':   [(0.0, (7, 11, 32)), (0.65, (18, 30, 66)), (1.0, (38, 56, 104))],
        'space':   [(0.0, (4, 4, 14)), (0.5, (16, 10, 40)), (1.0, (34, 20, 68))],
    }
    sky = [tuple(s) for s in palettes.get(t, palettes['day'])]
    light = {'day': (255, 244, 214), 'sunrise': (255, 214, 170), 'sunset': (255, 176, 110),
             'night': (226, 233, 255), 'space': (210, 200, 255)}.get(t, (255, 244, 214))
    ground = {'day': (74, 122, 78), 'sunrise': (96, 96, 88), 'sunset': (60, 62, 70),
              'night': (16, 26, 34), 'space': (10, 8, 24)}.get(t, (74, 122, 78))
    accent = (255, 196, 120) if t in ('sunset', 'sunrise') else \
             ((170, 200, 255) if t in ('night', 'space') else (255, 255, 240))
    if hue:
        hue_map = {'pink': 340, 'purple': 275, 'blue': 215, 'green': 130,
                   'orange': 28, 'gold': 45, 'red': 358}
        h = hue_map.get(hue, 28)
        sky[-1] = (1.0, _hls_to_rgb255(h, 0.72, 0.55))
        accent = _hls_to_rgb255(h + 15, 0.66, 0.75)
    if scene['weather'] == 'storm':
        sky = [(pos, tuple(int(c * 0.45) for c in col)) for pos, col in sky]
    elif scene['weather'] in ('rain', 'fog'):
        sky = [(pos, tuple(int(c * 0.72 + 40) for c in col)) for pos, col in sky]
    if scene.get('style') == 'realistic':
        # Photographic palettes: pull saturation toward luminance so skies and
        # terrain read naturally instead of flat cartoon color.
        def _naturalize(col, k):
            lum = 0.299 * col[0] + 0.587 * col[1] + 0.114 * col[2]
            return tuple(int(c * (1 - k) + lum * k) for c in col)
        sky = [(pos, _naturalize(col, 0.16)) for pos, col in sky]
        light = _naturalize(light, 0.10)
        ground = _naturalize(ground, 0.12)
    return sky, light, ground, accent


def _vertical_gradient(w, h, stops):
    """stops: [(pos 0..1, rgb)] — returns an RGB PIL image of w×h."""
    ys = np.linspace(0.0, 1.0, h)
    positions = np.array([p for p, _ in stops])
    channels = []
    for ci in range(3):
        values = np.array([col[ci] for _, col in stops], dtype=float)
        channels.append(np.interp(ys, positions, values))
    column = np.clip(np.stack(channels, axis=1), 0, 255).astype(np.uint8)
    arr = np.repeat(column[:, None, :], w, axis=1)
    return Image.fromarray(arr, 'RGB')


def _ridge_line(width, base_y, amplitude, roughness, rng, steps=14, smooth=False):
    if smooth:
        steps = 44
        roughness = roughness * 0.35
    xs = np.linspace(0, width, steps)
    ys = base_y + np.cumsum(rng.uniform(-roughness, roughness, steps))
    ys[0] = base_y + rng.uniform(-amplitude * 0.2, amplitude * 0.2)
    ys[-1] = base_y + rng.uniform(-amplitude * 0.2, amplitude * 0.2)
    ys -= (ys.mean() - base_y)
    peak = ys.min() - amplitude * 0.4
    valley = ys.max() + amplitude * 0.25
    ys = np.clip(ys, peak, min(valley, base_y + amplitude * 0.6))
    fine_x = np.arange(0, width, 4 if smooth else 3)
    fine_y = np.interp(fine_x, xs, ys)
    # organic micro-jitter — heavily damped for photoreal silhouettes
    jit = amplitude * (0.015 if smooth else 0.06)
    fine_y += np.convolve(rng.uniform(-jit, jit, len(fine_x)),
                          np.ones(9) / 9.0, mode='same')
    return list(zip(fine_x.tolist(), fine_y.tolist()))


def _value_noise(w, h, rng, cells=6, octaves=5):
    """Fractal value noise in [0,1] — photographic clouds and surface texture."""
    acc = np.zeros((h, w), dtype=float)
    amp, total = 1.0, 0.0
    base = max(2, int(cells))
    for o in range(int(octaves)):
        gw = base * (2 ** o) + 2
        gh = max(3, int(gw * h / max(1, w)) + 2)
        grid = rng.rand(gh, gw)
        xs = np.linspace(0, gw - 1.001, w)
        ys = np.linspace(0, gh - 1.001, h)
        x0 = np.floor(xs).astype(int)
        x1 = np.minimum(x0 + 1, gw - 1)
        fx = (xs - x0)[None, :]
        y0 = np.floor(ys).astype(int)
        y1 = np.minimum(y0 + 1, gh - 1)
        fy = (ys - y0)[:, None]
        v00 = grid[np.ix_(y0, x0)]
        v01 = grid[np.ix_(y0, x1)]
        v10 = grid[np.ix_(y1, x0)]
        v11 = grid[np.ix_(y1, x1)]
        top = v00 * (1 - fx) + v01 * fx
        bot = v10 * (1 - fx) + v11 * fx
        acc += (top * (1 - fy) + bot * fy) * amp
        total += amp
        amp *= 0.55
    return acc / max(total, 1e-6)


def _haze_band(img, horizon_y, haze_color):
    """Atmospheric perspective: soft band of horizon-colored haze fading
    downward from the horizon line — the single biggest realism cue."""
    W, H = img.size
    band_h = max(8, int(H * 0.10))
    y_start = max(0, int(horizon_y - band_h * 0.55))
    y_end = min(H, horizon_y + band_h)
    seg = max(2, y_end - y_start)
    alphas = np.zeros(seg, dtype=float)
    rise = int(seg * 0.45)
    alphas[:rise] = np.linspace(0, 120, rise)
    alphas[rise:] = np.linspace(120, 0, seg - rise)
    rgba = np.zeros((seg, W, 4), dtype=np.uint8)
    rgba[..., 0], rgba[..., 1], rgba[..., 2] = haze_color
    rgba[..., 3] = np.broadcast_to(alphas[:, None].astype(np.uint8), (seg, W))
    overlay = Image.fromarray(rgba, 'RGBA').filter(ImageFilter.GaussianBlur(max(4, seg // 6)))
    region = img.crop((0, y_start, W, y_end)).convert('RGBA')
    blended = Image.alpha_composite(region, overlay).convert('RGB')
    img.paste(blended, (0, y_start))
    return img


def _draw_ridge(draw_obj, points, color):
    poly = points + [(points[-1][0] + 10, 10000), (-10, 10000)]
    draw_obj.polygon(poly, fill=color)


def _glow_circle(base, cx, cy, radius, color, glow_alpha=90, core_alpha=255):
    """Soft radial glow + solid core composited onto an RGB image."""
    overlay = Image.new('RGBA', base.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for r, a in ((radius * 2.6, int(glow_alpha * 0.18)),
                 (radius * 1.9, int(glow_alpha * 0.3)),
                 (radius * 1.35, int(glow_alpha * 0.55)),
                 (radius, core_alpha)):
        od.ellipse([cx - r, cy - r, cx + r, cy + r],
                   fill=(*color, a if r > radius else core_alpha))
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius * 0.22))
    return Image.alpha_composite(base.convert('RGBA'), overlay).convert('RGB')


def _stars_layer(img, rng, density=220, big_star_chance=0.04):
    W, H = img.size
    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for _ in range(density):
        x = float(rng.uniform(0, W))
        y = float(rng.uniform(0, H * 0.72))
        r = float(rng.uniform(0.6, 1.8))
        a = int(rng.uniform(90, 230))
        od.ellipse([x - r, y - r, x + r, y + r], fill=(245, 245, 255, a))
        if rng.random() < big_star_chance:
            r2 = r * rng.uniform(3.2, 5.0)
            od.line([x - r2, y, x + r2, y], fill=(250, 250, 255, 140), width=1)
            od.line([x, y - r2, x, y + r2], fill=(250, 250, 255, 140), width=1)
    return Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')


def _clouds_layer(img, rng, count=7, tint=(255, 255, 255), alpha=70, photoreal=False):
    W, H = img.size
    if photoreal:
        # Fractal-noise cloud field — soft cumulative tops, sun-lit tint.
        noise = _value_noise(W, H, rng, cells=5, octaves=6)
        yy = np.linspace(0, 1, H)[:, None]
        band = np.clip(1.0 - yy / 0.60, 0, 1) ** 1.15
        density = np.clip((noise - 0.50) * 3.0, 0, 1) * band
        # vertical light gradient inside clouds (brighter tops)
        shade = (0.86 + 0.14 * (1 - yy))
        rgba = np.zeros((H, W, 4), dtype=np.uint8)
        for ci in range(3):
            rgba[..., ci] = np.clip(np.array(tint[ci]) * shade, 0, 255).astype(np.uint8)
        rgba[..., 3] = np.clip(density * alpha * 1.45, 0, 255).astype(np.uint8)
        overlay = Image.fromarray(rgba, 'RGBA').filter(ImageFilter.GaussianBlur(max(2, W // 300)))
        return Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')
    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for _ in range(count):
        cw = float(rng.uniform(W * 0.16, W * 0.4))
        ch = cw * float(rng.uniform(0.22, 0.36))
        cx = float(rng.uniform(-W * 0.05, W * 1.05))
        cy = float(rng.uniform(H * 0.08, H * 0.5))
        blobs = int(rng.randint(4, 8))
        for b in range(blobs):
            bx = cx + (b - blobs / 2) * cw * 0.22
            br = ch * float(rng.uniform(0.5, 0.85))
            by = cy + float(rng.uniform(-ch * 0.25, ch * 0.25))
            od.ellipse([bx - br, by - br * 0.62, bx + br, by + br * 0.62],
                       fill=(*tint, int(alpha * rng.uniform(0.6, 1.0))))
    overlay = overlay.filter(ImageFilter.GaussianBlur(ch * 0.18 + 2))
    return Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')


def _nebula_layer(img, rng):
    W, H = img.size
    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    hues = [(168, 90, 220), (90, 120, 235), (225, 95, 160), (80, 200, 210)]
    for _ in range(int(rng.randint(3, 6))):
        c = hues[int(rng.randint(0, len(hues)))]
        cw, ch = float(rng.uniform(W * 0.25, W * 0.65)), float(rng.uniform(H * 0.18, H * 0.5))
        cx, cy = float(rng.uniform(0, W)), float(rng.uniform(0, H))
        a = int(rng.uniform(26, 60))
        for _ in range(9):
            bx = cx + rng.uniform(-cw * 0.3, cw * 0.3)
            by = cy + rng.uniform(-ch * 0.3, ch * 0.3)
            br = min(cw, ch) * rng.uniform(0.18, 0.4)
            od.ellipse([bx - br, by - br, bx + br, by + br], fill=(*c, a))
    overlay = overlay.filter(ImageFilter.GaussianBlur(min(W, H) // 22))
    return Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')


def _water_band(img, horizon_y, deep_color, shimmer_color, sun_x=None, sun_reflect=True,
                reflection_light=None):
    """Fill below horizon with gradient water + horizontal shimmer strokes."""
    W, H = img.size
    water_h = max(2, H - horizon_y)
    top = np.array(deep_color, dtype=float)
    bottom = top * 0.55
    column = np.stack([np.interp(np.linspace(0, 1, water_h), [0, 1], [top[ci], bottom[ci]])
                       for ci in range(3)], axis=1)
    arr = np.array(img, dtype=np.uint8)
    grad = np.repeat(column[:, None, :], W, axis=1).astype(np.uint8)
    arr[horizon_y:, :, :] = grad
    img = Image.fromarray(arr, 'RGB')

    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    rng = _scene_rng(f"shimmer-{W}-{horizon_y}", int(sun_x or 0))
    for i in range(90):
        y = int(horizon_y + (i / 90.0) ** 1.4 * water_h)
        seg_w = float(rng.uniform(W * 0.02, W * 0.12)) * (1 + i / 40.0)
        x0 = float(rng.uniform(0, W - seg_w))
        a = int(max(14, 70 - i * 0.6))
        od.line([x0, y, x0 + seg_w, y], fill=(*shimmer_color, a), width=1)
    if sun_reflect and sun_x is not None:
        lc = reflection_light or (255, 210, 150)
        for i in range(46):
            t = i / 46.0
            y = int(horizon_y + t * water_h)
            spread = W * 0.02 + t * W * 0.09
            seg = float(rng.uniform(spread * 0.35, spread))
            x0 = sun_x - seg / 2 + rng.uniform(-spread * 0.2, spread * 0.2)
            a = int(120 * (1 - t * 0.75))
            od.line([x0, y, x0 + seg, y], fill=(*lc, a), width=max(1, int(2 + t * 2)))
    return Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')


def _pine_tree(od, x, base_y, height, color):
    """Silhouette pine: stacked triangles + trunk."""
    w = height * 0.46
    od.rectangle([x - height * 0.045, base_y - height * 0.16,
                  x + height * 0.045, base_y], fill=color)
    tiers = 3
    for tier in range(tiers):
        ty = base_y - height * (0.12 + tier * 0.26)
        tw = w * (1 - tier * 0.26)
        th = height * 0.42
        od.polygon([(x - tw, ty), (x + tw, ty), (x, ty - th)], fill=color)


def _round_tree(od, x, base_y, height, canopy_color, trunk_color):
    od.rectangle([x - height * 0.05, base_y - height * 0.34,
                  x + height * 0.05, base_y], fill=trunk_color)
    r = height * 0.30
    for dx, dy, rr in ((-r * 0.55, -height * 0.48, r * 0.8),
                       (r * 0.55, -height * 0.48, r * 0.8),
                       (0, -height * 0.68, r)):
        od.ellipse([x + dx - rr, base_y + dy - rr, x + dx + rr, base_y + dy + rr],
                   fill=canopy_color)


def _city_skyline(img, rng, baseline_y, building_color, night, accent):
    W, H = img.size
    layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(layer)
    x = -int(W * 0.02)
    while x < W * 1.02:
        bw = float(rng.uniform(W * 0.035, W * 0.10))
        bh = float(rng.uniform((baseline_y) * 0.18, baseline_y * 0.62))
        top = baseline_y - bh
        od.rectangle([x, top, x + bw, baseline_y], fill=(*building_color, 255))
        if night:
            win_w, win_h = max(2.0, bw * 0.09), max(3.0, bh * 0.03)
            cols = max(1, int(bw / (win_w * 2.4)))
            rows = max(1, int(bh / (win_h * 2.6)))
            for wc in range(cols):
                for wr in range(rows):
                    if rng.random() < 0.34:
                        wx = x + bw * 0.12 + wc * bw * 0.76 / cols
                        wy = top + bh * 0.07 + wr * bh * 0.9 / rows
                        od.rectangle([wx, wy, wx + win_w, wy + win_h],
                                     fill=(*accent, int(rng.uniform(120, 235))))
        else:
            od.rectangle([x, top, x + bw * 0.08, baseline_y],
                         fill=tuple(min(255, int(c * 1.15)) for c in building_color))
        if rng.random() < 0.18:
            ax = x + bw * 0.5
            od.line([ax, top, ax, top - bh * 0.18], fill=(*building_color, 255), width=2)
        x += bw + float(rng.uniform(W * 0.004, W * 0.02))
    return Image.alpha_composite(img.convert('RGBA'), layer).convert('RGB')


def _foreground_vegetation(img, rng, base_color, dark_color, trees=True):
    W, H = img.size
    layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(layer)
    hill_pts = _ridge_line(W, H * 0.97, H * 0.05, H * 0.012, rng)
    _draw_ridge(od, hill_pts, (*base_color, 255))
    if trees:
        for _ in range(int(rng.randint(3, 7))):
            tx = float(rng.uniform(0, W))
            th = float(rng.uniform(H * 0.10, H * 0.2))
            _pine_tree(od, tx, H * 0.985, th, (*dark_color, 255))
    return Image.alpha_composite(img.convert('RGBA'), layer).convert('RGB')


def _weather_overlay(img, scene, rng):
    W, H = img.size
    out = img
    if scene['weather'] == 'rain':
        layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(layer)
        for _ in range(int(W * H / 2600)):
            x = float(rng.uniform(0, W))
            y = float(rng.uniform(0, H))
            ln = float(rng.uniform(H * 0.02, H * 0.055))
            od.line([x, y, x - ln * 0.18, y + ln], fill=(200, 215, 240, 70), width=1)
        out = Image.alpha_composite(out.convert('RGBA'), layer).convert('RGB')
    elif scene['weather'] == 'storm':
        layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(layer)
        x, y = float(rng.uniform(W * 0.3, W * 0.7)), 0.0
        pts = [(x, y)]
        while y < H * 0.55:
            x += float(rng.uniform(-W * 0.05, W * 0.05))
            y += float(rng.uniform(H * 0.05, H * 0.1))
            pts.append((x, y))
        od.line(pts, fill=(255, 255, 235, 235), width=3)
        glow = Image.alpha_composite(out.convert('RGBA'), layer).convert('RGB')
        glow = _glow_circle(glow, pts[-1][0], pts[-1][1], min(W, H) * 0.06, (255, 255, 230), 60, 0)
        out = Image.blend(out, glow, 0.5)
        rain = _scene_rng('stormrain')
        out = _weather_overlay(out, {**scene, 'weather': 'rain'}, rain)
    elif scene['weather'] in ('fog', 'cloudy'):
        for band in range(3):
            layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
            od = ImageDraw.Draw(layer)
            y0 = H * (0.45 + band * 0.16)
            od.rectangle([-4, y0, W + 4, y0 + H * 0.14],
                         fill=(225, 228, 235, int(52 - band * 10)))
            layer = layer.filter(ImageFilter.GaussianBlur(H * 0.03))
            out = Image.alpha_composite(out.convert('RGBA'), layer).convert('RGB')
    return out


def _elements_overlay(img, scene, rng, horizon_y, light, silhouette_color):
    W, H = img.size
    layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(layer)
    sil = (*silhouette_color, 255)

    if 'birds' in scene['elements']:
        for _ in range(int(rng.randint(3, 6))):
            bx = float(rng.uniform(W * 0.15, W * 0.85))
            by = float(rng.uniform(H * 0.12, max(H * 0.2, horizon_y * 0.5)))
            s = float(rng.uniform(6, 14))
            span, lift = s, s * 0.55
            od.arc([bx - span, by - lift, bx, by + lift], 200, 330, fill=sil, width=2)
            od.arc([bx, by - lift, bx + span, by + lift], 210, 340, fill=sil, width=2)

    if 'boat' in scene['elements'] and scene['time'] != 'space':
        bx = float(W * rng.uniform(0.3, 0.7))
        by = horizon_y + (H - horizon_y) * 0.16
        bs = min(W, H) * 0.045
        od.polygon([(bx - bs, by), (bx + bs, by), (bx + bs * 0.55, by + bs * 0.32),
                    (bx - bs * 0.55, by + bs * 0.32)], fill=sil)
        od.polygon([(bx, by - bs * 1.5), (bx, by - bs * 0.05), (bx + bs * 0.75, by - bs * 0.05)],
                   fill=sil)

    if 'lighthouse' in scene['elements']:
        lx = float(W * 0.82)
        ly = horizon_y
        lh_ = (H - horizon_y) * 0.5
        lw = lh_ * 0.16
        od.rectangle([lx - lw, ly - lh_, lx + lw, ly], fill=sil)
        od.rectangle([lx - lw * 1.5, ly - lh_ - lw, lx + lw * 1.5, ly - lh_], fill=sil)
    if 'cabin' in scene['elements']:
        cx_ = float(W * rng.uniform(0.2, 0.42))
        cb = H * 0.985
        cs = (H - horizon_y) * 0.22
        od.rectangle([cx_ - cs, cb - cs * 0.9, cx_ + cs, cb], fill=sil)
        od.polygon([(cx_ - cs * 1.15, cb - cs * 0.9), (cx_ + cs * 1.15, cb - cs * 0.9),
                    (cx_, cb - cs * 1.5)], fill=sil)
        warm = (255, 200, 120, 230)
        od.rectangle([cx_ - cs * 0.28, cb - cs * 0.62, cx_ + cs * 0.05, cb - cs * 0.3], fill=warm)
        od.rectangle([cx_ + cs * 0.3, cb - cs * 0.62, cx_ + cs * 0.6, cb - cs * 0.3], fill=warm)

    out = Image.alpha_composite(img.convert('RGBA'), layer).convert('RGB')
    if 'lighthouse' in scene['elements'] and scene['time'] in ('night', 'sunset', 'sunrise'):
        lx = float(W * 0.82)
        lh_ = (H - horizon_y) * 0.5
        beam = Image.new('RGBA', img.size, (0, 0, 0, 0))
        bd = ImageDraw.Draw(beam)
        bd.polygon([(lx, H * 0.98 - lh_), (lx - W, H * 0.55), (lx - W, H * 0.72)],
                   fill=(255, 240, 190, 46))
        beam = beam.filter(ImageFilter.GaussianBlur(10))
        out = Image.alpha_composite(out.convert('RGBA'), beam).convert('RGB')

    if 'fireflies' in scene['elements']:
        fl = Image.new('RGBA', img.size, (0, 0, 0, 0))
        fd = ImageDraw.Draw(fl)
        for _ in range(26):
            fx = float(rng.uniform(0, W))
            fy = float(rng.uniform(H * 0.6, H * 0.95))
            fr = float(rng.uniform(1.5, 3.2))
            fd.ellipse([fx - fr, fy - fr, fx + fr, fy + fr],
                       fill=(255, 240, 150, int(rng.uniform(140, 230))))
        fl = fl.filter(ImageFilter.GaussianBlur(1.4))
        out = Image.alpha_composite(out.convert('RGBA'), fl).convert('RGB')
    return out


def _finish_image(img, rng, style='realistic'):
    W, H = img.size
    if style == 'watercolor':
        img = img.filter(ImageFilter.GaussianBlur(1.6))
        edge = img.filter(ImageFilter.CONTOUR if False else ImageFilter.SMOOTH_MORE)
        img = Image.blend(img, edge, 0.18)
    elif style == 'vivid':
        img = ImageEnhance.Color(img).enhance(1.35)
        img = ImageEnhance.Contrast(img).enhance(1.08)
    elif style == 'moody':
        img = ImageEnhance.Brightness(img).enhance(0.82)
        img = ImageEnhance.Contrast(img).enhance(1.12)
    elif style == 'anime':
        img = ImageEnhance.Color(img).enhance(1.45)
    elif style == 'pixel':
        small = img.resize((max(24, W // 14), max(24, H // 14)), Image.NEAREST)
        img = small.resize((W, H), Image.NEAREST)
    elif style == 'realistic':
        # Photographic grade: natural saturation, gentle S-contrast, soft
        # lens bloom — reads like a photo instead of flat digital art.
        img = ImageEnhance.Color(img).enhance(0.90)
        img = ImageEnhance.Contrast(img).enhance(1.07)
        # Highlight bloom: blur only the bright regions and screen-blend.
        arr = np.asarray(img, dtype=float)
        lum_mask = np.clip((arr.mean(axis=2) - 190) / 65.0, 0, 1)[..., None]
        blurred = np.asarray(img.filter(ImageFilter.GaussianBlur(max(3, min(W, H) // 90))), dtype=float)
        img = Image.fromarray(np.clip(arr * (1 - lum_mask * 0.22) + blurred * (lum_mask * 0.22), 0, 255).astype(np.uint8), 'RGB')

    # vignette (much gentler for photorealistic output)
    soft_edge = 196 if style == 'realistic' else 150
    mask = Image.new('L', (W, H), 0)
    md = ImageDraw.Draw(mask)
    md.ellipse([-W * 0.25, -H * 0.25, W * 1.25, H * 1.25], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(min(W, H) // 8))
    black = Image.new('RGB', (W, H), (4, 4, 10))
    img = Image.composite(img, black, mask.point(lambda v: soft_edge + v * (255 - soft_edge) * 105 // 255))

    # film grain (fine for realistic, visible for stylized work)
    grain_sigma = 2.2 if style == 'realistic' else 4.0
    noise = rng.normal(0, grain_sigma, size=(H, W, 1)).repeat(3, axis=2)
    arr = np.clip(np.asarray(img, dtype=float) + noise, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr, 'RGB')
    return img


def _describe_scene(scene):
    """Natural-language explanation of exactly what was rendered."""
    t = scene['time']
    terrain_names = {
        'ocean': 'the open ocean', 'lake': 'calm lake waters', 'mountains': 'layered mountain ridges',
        'forest': 'a deep evergreen forest', 'city': 'a city skyline', 'desert': 'rolling desert dunes',
        'meadow': 'an open flowering meadow', 'space': 'deep space with a glowing nebula',
    }
    time_phrases = {
        'day': 'under bright daylight skies', 'sunrise': 'at sunrise, with soft pink-gold light',
        'sunset': 'at sunset, bathed in warm amber tones', 'night': 'at night beneath a star-filled sky',
        'space': 'drifting through the cosmos',
    }
    weather_phrases = {
        'storm': 'as a dramatic storm rolls through with lightning on the horizon',
        'rain': 'while gentle rain streaks across the view',
        'fog': 'with soft fog drifting between the layers',
        'cloudy': 'under soft, cloud-covered skies',
    }
    element_phrases = {
        'birds': 'birds gliding across the sky', 'boat': 'a quiet boat resting on the water',
        'moon': 'the moon hanging overhead', 'lighthouse': 'a lighthouse sweeping its beam',
        'cabin': 'a cozy cabin with warmly lit windows', 'snow': 'snow dusting the landscape',
        'fireflies': 'fireflies glowing near the ground', 'stars': 'countless stars overhead',
    }
    style_phrases = {
        'neon': 'in a glowing neon cyberpunk style', 'watercolor': 'painted in a soft watercolor style',
        'minimal': 'composed with clean minimalist shapes', 'pixel': 'rendered as pixel art',
        'anime': 'drawn in a vivid anime style', 'vivid': 'with rich, vibrant colors',
        'moody': 'carrying a dark, moody atmosphere', 'painterly': 'rendered in a painterly digital-art style',
        'realistic': 'captured with natural lighting, atmospheric depth and true-to-life colors',
    }
    parts = [terrain_names.get(scene['terrain'][0], 'a scenic landscape')]
    extra_terrain = [terrain_names[x] for x in scene['terrain'][1:] if x in terrain_names]
    if extra_terrain:
        parts.append('beside ' + ' and '.join(extra_terrain))
    if scene['style'] == 'realistic':
        sentence = f"A photorealistic landscape of {parts[0]}"
    else:
        sentence = f"An original artwork of {parts[0]}"
    if len(parts) > 1:
        sentence += f" {parts[1]}"
    sentence += f", {time_phrases.get(t, '')}"
    if scene['weather'] != 'clear':
        sentence += f" {weather_phrases.get(scene['weather'], '')}"
    elems = [element_phrases[e] for e in scene['elements'] if e in element_phrases]
    if elems:
        sentence += ", featuring " + ", ".join(elems[:-1]) + (" and " + elems[-1] if len(elems) > 1 else elems[0])
    sentence += f". The piece is {style_phrases.get(scene['style'], '')}, composed with layered depth, atmospheric lighting and a custom palette."
    return sentence[0].upper() + sentence[1:]


def _render_generated_scene(prompt, width=1024, height=1024, shot=0, style_override=None):
    """Render one frame of procedurally generated art for `prompt`.
    `shot` varies composition slightly so video scenes evolve across cuts."""
    scene = _parse_scene(prompt, style_override)
    rng = _scene_rng(prompt or 'acronous', f'shot{shot}')
    W, H = int(width), int(height)
    sky_stops, light, ground, accent = _scene_palette(scene)
    if shot > 0:
        # subtle evolution between shots: hue shift + light drift
        shift = shot * 8
        sky_stops = [(p, tuple(int(c * (1 - 0.05 * shot)) + shift * 0.2 for c in col))
                     for p, col in sky_stops]
    img = _vertical_gradient(W, H, sky_stops)

    horizon = int(H * float(rng.uniform(0.56, 0.66)))
    night_like = scene['time'] in ('night', 'space')

    if scene['time'] == 'space':
        img = _nebula_layer(img, rng)
        img = _stars_layer(img, rng, density=int(W * H / 4200))
        # planet with terminator shading + optional ring
        pr = min(W, H) * float(rng.uniform(0.16, 0.3))
        px, py = W * float(rng.uniform(0.55, 0.8)), H * float(rng.uniform(0.3, 0.55))
        pc = _hls_to_rgb255(float(rng.uniform(0, 360)), 0.42, 0.5)
        img = _glow_circle(img, px, py, pr, pc, glow_alpha=40, core_alpha=255)
        shade = Image.new('RGBA', img.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(shade)
        sd.ellipse([px - pr, py - pr, px + pr, py + pr], fill=(2, 2, 8, 165))
        cut = Image.new('RGBA', img.size, (0, 0, 0, 0))
        cd = ImageDraw.Draw(cut)
        cd.ellipse([px - pr * 1.55, py - pr * 1.7, px + pr * 0.55, py + pr * 0.5], fill=(0, 0, 0, 255))
        shade = Image.composite(shade, Image.new('RGBA', img.size, (0, 0, 0, 0)),
                                cut.split()[3].point(lambda v: 255 - v))
        img = Image.alpha_composite(img.convert('RGBA'), shade).convert('RGB')
        ring = Image.new('RGBA', img.size, (0, 0, 0, 0))
        rd = ImageDraw.Draw(ring)
        rw, rh = pr * 1.75, pr * 0.5
        rd.ellipse([px - rw, py - rh, px + rw, py + rh], outline=(230, 220, 255, 150), width=max(2, int(pr * 0.05)))
        ring = ring.rotate(-18)
        img = Image.alpha_composite(img.convert('RGBA'), ring).convert('RGB')
        img = _finish_image(img, rng, scene['style'])
        return img, scene

    if scene['time'] == 'night':
        img = _stars_layer(img, rng, density=int(W * H / 6500))

    # celestial body
    sun_x = W * float(rng.uniform(0.22, 0.78))
    if scene['time'] in ('day', 'sunset', 'sunrise'):
        sun_y = horizon - H * (0.30 if scene['time'] == 'day' else 0.10)
        img = _glow_circle(img, sun_x, sun_y, min(W, H) * (0.075 if scene['time'] == 'day' else 0.10),
                           light, glow_alpha=120)
    if scene['time'] == 'night' and ('moon' in scene['elements'] or rng.random() < 0.7):
        mx = W * float(rng.uniform(0.6, 0.85))
        my = H * float(rng.uniform(0.12, 0.3))
        mr = min(W, H) * 0.06
        img = _glow_circle(img, mx, my, mr, (235, 238, 255), glow_alpha=110)

    if scene['weather'] in ('cloudy', 'rain', 'storm', 'fog') or rng.random() < 0.75:
        cloud_tint = (235, 228, 222) if scene['time'] in ('sunset', 'sunrise') else \
                     ((200, 205, 220) if night_like else (255, 255, 255))
        img = _clouds_layer(img, rng, count=int(rng.randint(4, 8)),
                            tint=cloud_tint, alpha=64 if night_like else 84,
                            photoreal=(scene['style'] == 'realistic'))

    sil = tuple(int(c * (0.32 if night_like else 0.55)) for c in ground)

    terrains = scene['terrain']

    def far_ridge(color_mix=0.5):
        col = tuple(int(sil[ci] * color_mix + sky_stops[-1][1][ci] * (1 - color_mix)) for ci in range(3))
        pts = _ridge_line(W, horizon - H * 0.02, H * 0.16, H * 0.02, rng,
                          smooth=(scene['style'] == 'realistic'))
        layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        _draw_ridge(ld, pts, (*col, 235))
        nonlocal_dummy = Image.alpha_composite(img.convert('RGBA'), layer).convert('RGB')
        return nonlocal_dummy

    if 'mountains' in terrains:
        img = far_ridge(0.35)
        pts = _ridge_line(W, horizon + H * 0.01, H * 0.20, H * 0.025, rng,
                          smooth=(scene['style'] == 'realistic'))
        layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        col = tuple(int(sil[ci] * 0.75 + ground[ci] * 0.25) for ci in range(3))
        _draw_ridge(ld, pts, (*col, 255))
        if 'snow' in scene['elements']:
            snow_pts = [(x, y) for x, y in pts if y < horizon - H * 0.06]
            for x, y in snow_pts:
                ld.ellipse([x - 6, y - 3, x + 6, y + 3], fill=(240, 244, 252, 220))
        img = Image.alpha_composite(img.convert('RGBA'), layer).convert('RGB')

    water_scenes = [t for t in ('ocean', 'lake') if t in terrains]
    if water_scenes:
        reflect_col = sky_stops[-2][1] if len(sky_stops) > 1 else sky_stops[-1][1]
        img = _water_band(img, horizon, deep_color=reflect_col if night_like else
                          tuple(int(c * 0.62) for c in reflect_col),
                          shimmer_color=tuple(min(255, int(c + 60)) for c in reflect_col),
                          sun_x=sun_x if scene['time'] in ('sunset', 'sunrise', 'day', 'night') else None,
                          reflection_light=light)
        horizon_water = horizon
    elif 'space' in terrains:
        horizon_water = horizon
    else:
        # land horizon strip
        layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        land_col = tuple(int(sil[ci] * 0.6 + ground[ci] * 0.4) for ci in range(3))
        pts = _ridge_line(W, horizon, H * 0.05, H * 0.008, rng)
        _draw_ridge(ld, pts, (*land_col, 255))
        img = Image.alpha_composite(img.convert('RGBA'), layer).convert('RGB')
        horizon_water = horizon

    if 'desert' in terrains:
        layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        sand_a = (206, 168, 116, 235)
        sand_b = (172, 128, 84, 255)
        for li in range(3):
            yy = horizon + (H - horizon) * li * 0.28
            amp = (H - horizon) * 0.08
            xs = np.arange(0, W, 6)
            ys = yy + amp * np.sin(xs / (W * 0.08) + li * 2.1 + rng.uniform(0, 3)) \
                 + amp * 0.5 * np.sin(xs / (W * 0.031) + li)
            ld.polygon([(x, y) for x, y in zip(xs.tolist(), ys.tolist())]
                       + [(W + 8, H + 8), (-8, H + 8)], fill=sand_b if li == 2 else sand_a)
        img = Image.alpha_composite(img.convert('RGBA'), layer).convert('RGB')

    if 'city' in terrains:
        far = tuple(int(sil[ci] * 0.55 + sky_stops[-1][1][ci] * 0.45) for ci in range(3))
        img = _city_skyline(img, rng, horizon + 2, far, night=False, accent=accent)
        img = _city_skyline(img, rng, H, sil, night=night_like, accent=(255, 208, 130))

    if 'forest' in terrains:
        layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(layer)
        back = tuple(int(sil[ci] * 0.6 + sky_stops[-1][1][ci] * 0.4) for ci in range(3))
        for _ in range(int(rng.randint(16, 26))):
            tx = float(rng.uniform(-W * 0.02, W * 1.02))
            th = float(rng.uniform(H * 0.05, H * 0.11))
            _pine_tree(od, tx, horizon + H * 0.012, th, (*back, 235))
        img = Image.alpha_composite(img.convert('RGBA'), layer).convert('RGB')
        img = _foreground_vegetation(img, rng, ground, sil, trees=True)

    if 'meadow' in terrains:
        layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(layer)
        meadow_cols = [(96, 142, 82), (118, 164, 92), (140, 186, 106)] if not night_like \
            else [(30, 46, 40), (38, 58, 48), (48, 70, 56)]
        for li, mc in enumerate(meadow_cols):
            yy = horizon + (H - horizon) * (0.12 + li * 0.3)
            pts = _ridge_line(W, yy, (H - horizon) * 0.06, (H - horizon) * 0.012, rng)
            _draw_ridge(od, pts, (*mc, 255))
        img = Image.alpha_composite(img.convert('RGBA'), layer).convert('RGB')
        flower_cols = [(245, 168, 190), (250, 220, 130), (235, 245, 250), (200, 160, 240)]
        fl = Image.new('RGBA', img.size, (0, 0, 0, 0))
        fd = ImageDraw.Draw(fl)
        for _ in range(int(W * H / 9000)):
            fx = float(rng.uniform(0, W))
            fy = float(rng.uniform(horizon + H * 0.08, H * 0.98))
            fr = float(rng.uniform(1.4, 3.4)) * (fy / H)
            fc = flower_cols[int(rng.randint(0, len(flower_cols)))]
            fd.ellipse([fx - fr, fy - fr, fx + fr, fy + fr], fill=(*fc, 235))
        img = Image.alpha_composite(img.convert('RGBA'), fl).convert('RGB')

    if 'road' in ' '.join(terrains) or 'road' in scene['prompt'].lower():
        layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(layer)
        vx, vy = W * float(rng.uniform(0.42, 0.58)), horizon + 2
        road_col = (52, 54, 60, 255) if not night_like else (26, 28, 36, 255)
        od.polygon([(vx - W * 0.012, vy), (vx + W * 0.012, vy), (W * 0.98, H), (W * 0.02, H)],
                   fill=road_col)
        dash_n = 7
        for i in range(dash_n):
            t0, t1 = i / dash_n, (i + 0.45) / dash_n
            yt0, yt1 = vy + (H - vy) * t0 ** 2, vy + (H - vy) * t1 ** 2
            wt0, wt1 = W * 0.004 + t0 * W * 0.02, W * 0.004 + t1 * W * 0.02
            xc0 = vx + (0 - vx) * t0 ** 2 + (W * 0.5 - 0) * 0
            x0 = vx + (W * 0.5 - vx) * t0 ** 2
            x1 = vx + (W * 0.5 - vx) * t1 ** 2
            od.polygon([(x0 - wt0, yt0), (x0 + wt0, yt0), (x1 + wt1, yt1), (x1 - wt1, yt1)],
                       fill=(235, 228, 190, 230))
        img = Image.alpha_composite(img.convert('RGBA'), layer).convert('RGB')

    img = _weather_overlay(img, scene, rng)
    img = _elements_overlay(img, scene, rng, horizon_water, light, sil)

    if scene['style'] == 'realistic' and 'space' not in terrains:
        # Atmospheric perspective — haze toward the horizon color.
        img = _haze_band(img, horizon_water, sky_stops[-1][1])
        # Ground texture: faint fractal luminance variation below the horizon.
        ground_h = max(4, H - horizon_water)
        tex = _value_noise(W, min(ground_h, 512), rng, cells=10, octaves=5)
        if tex.shape[0] != ground_h:
            tex = np.array(Image.fromarray((tex * 255).astype(np.uint8)).resize((W, ground_h)), dtype=float) / 255.0
        arr = np.asarray(img, dtype=float)
        region = arr[horizon_water:, :, :]
        lum = (region.mean(axis=2, keepdims=True)) / 255.0
        delta = (tex[..., None] - tex.mean()) * (14.0 * (0.35 + 0.65 * lum))
        arr[horizon_water:, :, :] = np.clip(region + delta, 0, 255)
        img = Image.fromarray(arr.astype(np.uint8), 'RGB')

    if 'space' not in terrains and scene['time'] in ('sunset', 'sunrise'):
        haze = Image.new('RGBA', img.size, (0, 0, 0, 0))
        hd = ImageDraw.Draw(haze)
        hd.rectangle([-4, horizon - H * 0.05, W + 4, horizon + H * 0.04],
                     fill=(*light, 70))
        haze = haze.filter(ImageFilter.GaussianBlur(H * 0.03))
        img = Image.alpha_composite(img.convert('RGBA'), haze).convert('RGB')

    img = _finish_image(img, rng, scene['style'])
    return img, scene


# ---------------------------------------------------------------------------
# Local Stable Diffusion (free, unlimited, CPU) — primary image generator.
# ---------------------------------------------------------------------------
SD_MODEL_ID = "stabilityai/sd-turbo"
_SD_PIPE = None
_SD_IMG2IMG = None
_SD_NEG = (
    "ugly, deformed, disfigured, low quality, lowres, blurry, bad anatomy, "
    "extra limbs, missing limbs, mutated, watermark, signature, text, words, "
    "painting, cartoon, illustration, sketch, anime, drawing, 3d render, "
    "oversaturated, overexposed, jpeg artifacts, double image"
)


def _load_sd():
    global _SD_PIPE
    if _SD_PIPE is not None:
        return _SD_PIPE
    if not HAS_DIFFUSERS:
        return None
    import os as _os
    import torch as _torch
    # Use every CPU core for the matmuls — default thread count is often 1 on
    # some runtimes, which makes generation 4-8x slower.
    _torch.set_num_threads(max(1, _os.cpu_count() or 4))
    pipe = StableDiffusionPipeline.from_pretrained(
        SD_MODEL_ID, safety_checker=None, requires_safety_checker=False
    )
    # sd-turbo ships its own (distilled) scheduler — do NOT override it.
    pipe = pipe.to("cpu")
    pipe.enable_attention_slicing()
    _SD_PIPE = pipe
    return _SD_PIPE


def _load_sd_img2img():
    global _SD_IMG2IMG
    if _SD_IMG2IMG is not None:
        return _SD_IMG2IMG
    if not HAS_DIFFUSERS:
        return None
    pipe = StableDiffusionImg2ImgPipeline.from_pretrained(
        SD_MODEL_ID, safety_checker=None, requires_safety_checker=False
    )
    pipe = pipe.to("cpu")
    pipe.enable_attention_slicing()
    _SD_IMG2IMG = pipe
    return _SD_IMG2IMG


def _build_sd_prompt(prompt, style):
    p = (prompt or "").strip()
    if not style or style == "realistic":
        if not re.search(r"photorealistic|photo|8k|ultra.?detailed", p, re.I):
            p = f"{p}, photorealistic, ultra-detailed, 8k, professional photography, sharp focus, natural lighting, highly detailed"
    else:
        p = f"{p}, {style} style"
    return p


def generate_sd_image(prompt, style=None, steps=1, size=256):
    pipe = _load_sd()
    if pipe is None:
        return None
    p = _build_sd_prompt(prompt, style)
    last_err = None
    # sd-turbo is a 1-step distilled model: text2img MUST run exactly one
    # denoise step. (Its scheduler raises an indexing error at >1 step, so the
    # 1-step call below is the only stable path.) Retries absorb the occasional
    # transient scheduler glitch so generated images/video frames always come
    # from the real model instead of the procedural fallback.
    for attempt in range(3):
        try:
            img = pipe(
                p,
                negative_prompt=_SD_NEG,
                num_inference_steps=1,
                guidance_scale=0.0,
                width=size,
                height=size,
                num_images_per_prompt=1,
            ).images[0]
            return img.convert("RGB")
        except Exception as e:
            last_err = e
            logging.warning(f"[SD] text2img attempt {attempt + 1} failed: {e}")
    logging.error(f"[SD] text2img failed after retries: {last_err}")
    return None


def edit_sd_img2img(init_image, prompt, style=None, strength=0.6, steps=2, size=512):
    pipe = _load_sd_img2img()
    if pipe is None:
        return None
    p = _build_sd_prompt(prompt, style)
    try:
        # sd-turbo img2img: with steps=2 and strength>=0.5 the pipeline runs
        # exactly ONE denoise step (steps=1 yields 0 steps and returns None).
        # The strength is clamped to <=0.75 so the single denoise step applies
        # the requested change WITHOUT re-inventing the rest of the frame —
        # higher values (0.9+) is what previously produced the cartoonish,
        # blurred 'scatter' overlay over user photos.
        #
        # size default 512 (was hardcoded 256): 256 was the single worst quality
        # killer for region swaps — it crushed the garment crop to a tiny tile,
        # then the upscale back to the crop size dilated every SD artifact into
        # smeary, low-detail distortion (especially around the face/neck).
        s = max(0.40, min(0.75, float(strength)))
        init = init_image.convert("RGB").resize((size, size))
        out = pipe(
            p,
            image=init,
            strength=s,
            num_inference_steps=steps,
            guidance_scale=0.0,
            negative_prompt=_SD_NEG,
        ).images[0]
        return out.convert("RGB")
    except Exception as e:
        logging.error(f"[SD] img2img failed: {e}")
        return None


def detect_explicit_art_style(prompt):
    """Return an SD style key ONLY when the user explicitly asked for a non-photo
    look (cartoon, anime, oil painting, watercolor, sketch, 3d render, pixel, neon,
    etc.). Returns None for everything else so edits stay photorealistic by default
    and the rest of the image is never stylized unless the user requested it."""
    if not prompt:
        return None
    p = prompt.lower()
    explicit = [
        ('anime', ['anime', 'manga', 'ghibli', 'comic book', 'comic style', 'comic-book']),
        ('painterly', ['oil painting', 'oil paint', 'acrylic', 'painted', 'painterly',
                       'watercolor', 'watercolour', 'aquarelle', 'sketch', 'sketched',
                       'drawing', 'drawn', 'illustration', 'illustrated', 'hand-drawn',
                       'hand drawn', 'in the style of a painting', 'in the style of',
                       'pop art', 'impressionist', 'impressionism', 'surreal', 'abstract',
                       'cartoon', 'cartoon style', 'cartoon look', 'disney', 'pixar']),
        ('pixel', ['pixel art', '8-bit', '8 bit', '16-bit', '16 bit']),
        ('neon', ['neon', 'cyberpunk', 'synthwave', 'vaporwave']),
        ('minimal', ['minimalist', 'flat design', 'minimal']),
        ('vivid', ['vibrant', 'saturated', 'colourful', 'colorful']),
        ('moody', ['moody', 'noir', 'melancholic', 'somber']),
        ('3d', ['3d render', '3d model', '3d rendered', 'cinematic 3d']),
    ]
    for style, words in explicit:
        if any(w in p for w in words):
            return style
    return None


def _generate_sd_backdrop(prompt, style, w, h):
    """Photorealistic backdrop from the local SD model (real by default; stylized
    only when `style` is set by an explicit user request). Returns None so the
    caller keeps its procedural fallback only when SD is genuinely unavailable."""
    if not HAS_DIFFUSERS:
        return None
    sd = generate_sd_image(prompt, style, 1, 256)
    if sd is None:
        return None
    sd = enhance_photorealistic(sd)
    return _cover_resize(sd, w, h).convert("RGB")


def _sd_scene_image(prompt, W, H, style_override=None):
    """Photorealistic keyframe for the video engine: a real SD render of the
    requested scene (not the procedural painterly engine), used as a moving
    shot. Returns None if SD is unavailable so the caller keeps its fallback."""
    if not HAS_DIFFUSERS:
        return None
    sp = f"cinematic photograph, {prompt}, realistic, natural lighting, high detail"
    img = generate_sd_image(sp, style=None, steps=1, size=512)
    if img is None:
        return None
    img = enhance_photorealistic(img)
    return _cover_resize(img, W, H).convert("RGB")


def _apply_masked_sd_edit(orig, mask, prompt, style=None, strength=0.55, match_original=True, seam=12):
    """Regenerate ONLY the asked-for region with SD img2img, then composite it
    opaquely over the untouched original so the rest of the photo is preserved
    exactly. The edited region fully replaces the original inside the mask (no
    translucent alpha overlay) — only a short feathered seam blends the edges so
    the garment reads as one continuous photograph.

    Photorealistic by default (stylized only when the user explicitly asked).

    Why this preserves quality:
      - The edit runs ONLY on the tight bounding box of the mask (never the
        whole image) so the background/face are never re-rendered.
      - Lower strength (0.55) keeps the original pose, fabric folds, shadows and
        colour temperature — a gentler edit that reads as "the same photo with
        the garment swapped", not a regen.
      - Histogram matching (per-channel) re-aligns the edited patch colour
        distribution to the original so there is no visible colour cast.
      - Luminance matching + wide feathered seam + edge-light wrap remove any
        hard rim at the boundary.
    When no mask could be localized, falls back to a whole-image edit so the
    user always gets a real edit, never an apology.

    `match_original=False` skips the colour-histogram remap: used for garment
    swaps where the requested garment has a DIFFERENT colour than the original
    (e.g. a white dress -> black suit). Matching to the old garment there would
    wash the new suit back toward the dress colour and destroy the edit.
    """
    if not HAS_DIFFUSERS:
        return None

    import math as _math

    def _patch_sd(crop, s):
        return edit_sd_img2img(crop, prompt, style=style, strength=s, steps=2, size=512)

    # Region-cropped (structure-preserving) edit.
    if mask is not None and np.any(np.asarray(mask.convert("L")) > 40):
        m_arr = np.asarray(mask.convert("L"))
        ys, xs = np.where(m_arr > 40)
        if len(xs) and len(ys):
            pad = 24
            x0 = max(0, int(xs.min()) - pad)
            y0 = max(0, int(ys.min()) - pad)
            x1 = min(orig.width, int(xs.max()) + pad)
            y1 = min(orig.height, int(ys.max()) + pad)
            bw, bh = x1 - x0, y1 - y0
            if bw >= 64 and bh >= 64:
                crop = orig.crop((x0, y0, x1, y1)).resize((512, 512), Image.LANCZOS)
                sd = _patch_sd(crop, strength)
                if sd is not None:
                    sd = sd.resize((bw, bh), Image.LANCZOS)
                    sd = enhance_photorealistic(sd)
                    # Luminance-match the patch to the original region so colour
                    # temperature stays consistent with the rest of the photo.
                    region_orig = np.asarray(orig.crop((x0, y0, x1, y1)).convert("RGB"), dtype=np.float32)
                    region_new = np.asarray(sd, dtype=np.float32)
                    o_lum = (0.299 * region_orig[:, :, 0] + 0.587 * region_orig[:, :, 1] + 0.114 * region_orig[:, :, 2]).mean()
                    n_lum = (0.299 * region_new[:, :, 0] + 0.587 * region_new[:, :, 1] + 0.114 * region_new[:, :, 2]).mean() + 1e-4
                    factor = float(_math.pow(o_lum / n_lum, 0.5))
                    # For a garment swap the patch colour is the whole point — keep
                    # the new tone (extra-tight luminance band). For other edits
                    # allow a wider match so the region re-blends with the photo.
                    factor = max(0.90, min(1.10, factor)) if not match_original else max(0.85, min(1.18, factor))
                    sd = Image.fromarray(np.clip(region_new * factor, 0, 255).astype(np.uint8))
                    # Per-channel histogram matching — forces the edited region's
                    # colour distribution to match the original. SKIPPED for garment
                    # swaps (would revert a black suit back to the old dress colour).
                    if match_original:
                        try:
                            import numpy as _np
                            def _hist_match(src_ch, ref_ch):
                                # Source pixel values -> 0..255, build CDF maps
                                src_flat = src_ch.ravel().astype(_np.float32)
                                ref_flat = ref_ch.ravel().astype(_np.float32)
                                src_hist, _ = _np.histogram(src_flat, bins=256, range=(0, 255))
                                ref_hist, _ = _np.histogram(ref_flat, bins=256, range=(0, 255))
                                src_cdf = src_hist.cumsum()
                                src_cdf = src_cdf / (src_cdf[-1] + 1e-9)
                                ref_cdf = ref_hist.cumsum()
                                ref_cdf = ref_cdf / (ref_cdf[-1] + 1e-9)
                                # For each source value, find the reference value with
                                # the closest CDF (standard histogram equalization match)
                                lut = _np.interp(ref_cdf, src_cdf, _np.arange(256))
                                return lut[src_ch.astype(_np.int32)].reshape(src_ch.shape).astype(_np.float32)
                            rm = _np.asarray(sd, dtype=_np.float32)
                            orig_f = region_orig
                            for ch in range(3):
                                rm[:, :, ch] = _hist_match(rm[:, :, ch], orig_f[:, :, ch])
                            sd = Image.fromarray(_np.clip(rm, 0, 255).astype(_np.uint8))
                        except Exception:
                            pass
                    crop_mask = mask.crop((x0, y0, x1, y1)).resize((bw, bh), Image.NEAREST)
                    # Composite the edited crop only within the crop region (all
                    # three tensors share bw x bh), then paste back onto the full
                    # image so the garment edge never shows a translucent halo.
                    base_crop = orig.crop((x0, y0, x1, y1)).convert("RGB")
                    comp = _composite_patch_sharp(base_crop, sd, crop_mask, seam=seam)
                    if match_original:
                        comp = _edge_light_wrap(comp, crop_mask, radius=10)
                    full = orig.convert("RGB").copy()
                    full.paste(comp, (x0, y0))
                    return full
    # Whole-image fallback (no usable mask).
    sd = _patch_sd(orig.convert("RGB").resize((512, 512)), 0.4)
    if sd is None:
        return None
    sd = enhance_photorealistic(sd).resize(orig.size, Image.LANCZOS)
    if mask is None:
        return sd
    return feather_blend(orig, sd, mask, radius=12)


def _edge_light_wrap(img: "Image.Image", mask: "Image.Image", radius: int = 10) -> "Image.Image":
    """Add a thin highlight along the inner edge of a mask so a composited region
    blends into the surrounding photo instead of showing a hard/translucent rim.
    Only lightens a 1-2px band; never translucent."""
    try:
        m = np.asarray(mask.convert("L").resize(img.size, Image.LANCZOS), dtype=np.float32) / 255.0
        if m.max() < 0.05:
            return img
        inner = _feather_channel((m * 255).astype(np.uint8), radius=radius)
        outer = _feather_channel((m * 255).astype(np.uint8), radius=radius + 2)
        rim = np.clip(inner - outer, 0, 1)
        a = np.asarray(img.convert("RGB"), dtype=np.float32)
        lift = a + rim[:, :, None] * 14.0  # subtle highlight
        return Image.fromarray(np.clip(lift, 0, 255).astype(np.uint8))
    except Exception:
        return img


def _composite_patch_sharp(orig, edited, mask, seam=4):
    """Blend `edited` into `orig` using `mask`, keeping the interior at full
    strength and feathering only a narrow `seam` band at the boundary."""
    # Feather only the transition band of the mask (inside stays full-strength).
    binary = mask.convert("L").point(lambda v: 255 if v > 30 else 0)
    feathered = _feather_channel(binary, radius=seam)
    amt = np.clip(feathered, 0, 1)
    a = np.asarray(orig, dtype=np.float32)
    b = np.asarray(edited, dtype=np.float32)
    out = a * (1 - amt[:, :, None]) + b * amt[:, :, None]
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


# Pre-warm the diffusion model at startup so it is ready (never sleeps) on the
# first user request. Runs in a background thread so import stays fast.
if HAS_DIFFUSERS:
    try:
        import threading
        def _warm_sd():
            try:
                _load_sd()
                _load_sd_img2img()
                logging.info("[SD] model warmed and ready")
            except Exception as e:
                logging.error(f"[SD] warm failed: {e}")
        threading.Thread(target=_warm_sd, daemon=True).start()
    except Exception:
        pass


@app.post("/generate-image")
async def api_generate_image(
    prompt: str = Form(...),
    width: int = Form(1024),
    height: int = Form(1024),
    style: str = Form(""),
):
    """Self-hosted image generation.

    Primary: local Stable Diffusion (free, unlimited). Falls back to the
    deterministic procedural scene engine if the diffusion model is unavailable.
    Photorealistic by default; a stylized look only when the client detected
    an explicit art-style ask.
    """
    if not prompt.strip():
        raise HTTPException(400, "No prompt provided")
    prompt = prompt.strip()[:2000]
    try:
        w = max(256, min(1536, int(width)))
        h = max(256, min(1536, int(height)))
        style = (style or "").strip() or None
        img = None
        if HAS_DIFFUSERS:
            try:
                img = await _asyncio.to_thread(generate_sd_image, prompt, style, 1, 256)
            except Exception as e:
                logging.error(f"generate-image SD error: {e}")
                img = None
        if img is None:
            # No silent "painting" fallback: never substitute an unrelated
            # generic image for the user's specific request. If the diffusion
            # model genuinely isn't installed we keep a deterministic engine as
            # the last resort, but when a model exists we fail honestly.
            if not HAS_DIFFUSERS:
                img, scene = await _asyncio.to_thread(
                    _render_generated_scene, prompt, w, h, 0, style)
                description = _describe_scene(scene)
            else:
                raise HTTPException(
                    503,
                    "Image generation is temporarily unavailable. Please try again in a moment.",
                )
        else:
            description = "AI-generated image."
        # Upscale to the requested resolution (free, local Lanczos)
        target = min(max(w, h), 1024)
        while img.width < target or img.height < target:
            img = upscale_image(img, 2)
            if img.width >= target and img.height >= target:
                break
            if img.width > 2048 or img.height > 2048:
                break
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return {
            "image_data": base64.b64encode(buf.getvalue()).decode(),
            "format": "png",
            "width": img.width,
            "height": img.height,
            "description": description,
        }
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"generate-image error: {e}")
        raise HTTPException(500, f"Image generation failed: {str(e)}")


@app.post("/edit-diffusion")
async def api_edit_diffusion(
    file: UploadFile = File(...),
    prompt: str = Form(...),
    style: str = Form(""),
    strength: float = Form(0.45),
):
    """Local SD img2img edit — preserves the original composition and applies
    only the requested change. Free and unlimited (no external API)."""
    if not HAS_DIFFUSERS:
        raise HTTPException(503, "Local diffusion model unavailable")
    data = await file.read()
    try:
        init = bytes_to_img(data).convert("RGB").resize((256, 256))
    except Exception:
        raise HTTPException(400, "Invalid image")
    style = (style or "").strip() or None
    try:
        out = await _asyncio.to_thread(
            edit_sd_img2img, init, (prompt or "")[:2000], style, float(strength)
        )
    except Exception as e:
        logging.error(f"edit-diffusion error: {e}")
        raise HTTPException(500, f"Edit failed: {str(e)}")
    if out is None:
        raise HTTPException(500, "Edit failed")
    buf = io.BytesIO()
    out.save(buf, format="PNG", optimize=True)
    return {
        "edited": base64.b64encode(buf.getvalue()).decode(),
        "width": out.width,
        "height": out.height,
    }


def _clean_topic(prompt):
    """Strip command scaffolding ('make a video about...') leaving pure topic."""
    t = (prompt or "").strip()
    patterns = [
        r'^\s*(?:please\s+)?(?:can|could|would|will)\s+you\s+(?:please\s+)?',
        r'^\s*(?:please\s+)?(?:generate|create|make|render|produce|build|give\s+me|show\s+me|draw|do)\s+(?:me\s+)?(?:a\s+|an\s+|the\s+)?',
        r'^\s*(?:a\s+|an\s+|the\s+|my\s+)?(?:short\s+)?\d+\s*(?:sec(?:ond)?s?|secs?|mins?|minutes?)\s+',
        r'^(?:\s*)(?:short\s+)?(?:video|animation|animated\s+video|clip|mp4)\b\s*',
        r'^\s*(?:video|animation|clip|mp4)\s+(?:about|of|on|showing|featuring|depicting)\s+',
        r'^\s*(?:about|of|on|showing|featuring|depicting|for)\s+',
        r'\s+for\s+me\s*$', r'\s+please\s*$', r'\s+now\s*$',
    ]
    changed = True
    while changed:
        changed = False
        for pat in patterns:
            new = re.sub(pat, '', t, flags=re.IGNORECASE)
            if new != t:
                t = new.strip()
                changed = True
    return t if t else (prompt or '').strip()


def split_prompt_into_shots(prompt, max_shots=6):
    """Break a user's video request into a sequence of distinct scene beats so
    the rendered video is a genuine multi-shot story about what was asked — not
    a single repeated frame. Deterministic, no network calls."""
    p = (prompt or "").strip()
    if not p:
        return ["acronous landscape"]
    # Split on sentence / clause boundaries that imply a sequence.
    raw = re.split(r'(?:[.;]|(?:\s*,?\s*(?:then|after\s+that|next|and\s+then|followed\s+by|afterwards|meanwhile|then\s+a|now\s+show)\s+))', p, flags=re.IGNORECASE)
    beats = [b.strip(" ,.;-") for b in raw if b and b.strip(" ,.;-")]
    # Drop pure command scaffolding leftovers.
    beats = [b for b in beats if len(b) > 2]
    if len(beats) < 2:
        # No explicit sequence — derive beats from the single description by
        # varying camera/composition so the video still has multiple frames.
        base = beats[0] if beats else p
        beats = [base, f"{base}, wide establishing shot", f"{base}, closer detail", f"{base}, different angle"]
    beats = beats[:max_shots]
    if len(beats) < 2:
        beats = [beats[0], beats[0]]
    return beats


def _narration_script(topic, description):
    """Voice-over speaks ONLY about the subject — no meta lines ('here is
    your video'), no branding, no style chatter."""
    desc = (description or '').strip()
    # Drop the trailing style sentence ("The piece is ...") if present.
    idx = desc.find('The piece is')
    if idx > 0:
        desc = desc[:idx].strip()
    if not desc and topic:
        desc = f"A scenic view of {topic}."
    sentences = re.split(r'(?<=[.!?])\s+', desc)
    return ' '.join(sentences[:3])


async def _synthesize_narration(text):
    """edge-tts narration → mp3 bytes, or None when TTS is unavailable."""
    if not HAS_EDGE_TTS or not text.strip():
        return None
    tmp_path = os.path.join(tempfile.gettempdir(), f"vid_narr_{os.getpid()}_{id(text) & 0xffff}.mp3")
    try:
        communicate = edge_tts.Communicate(text, "en-US-AriaNeural", rate="+6%")
        await _asyncio.wait_for(communicate.save(tmp_path), timeout=30)
        with open(tmp_path, "rb") as f:
            data = f.read()
        return data if len(data) > 512 else None
    except Exception as e:
        logging.warning(f"narration tts failed: {e}")
        return None
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def _ambient_subtype(topic_text):
    """Pick a gentle ambient flavour from the scene description so the
    soundtrack matches the VIDEO content rather than being a fixed clip."""
    t = (topic_text or '').lower()
    if any(k in t for k in ('rain', 'storm', 'thunder', 'drop')):
        return 'rain'
    if any(k in t for k in ('ocean', 'sea', 'beach', 'wave', 'water', 'river', 'stream', 'lake', 'pond', 'waterfall')):
        return 'water'
    if any(k in t for k in ('wind', 'storm', 'leaf', 'tree', 'forest', 'wood', 'jungle', 'grass', 'field', 'meadow')):
        return 'wind'
    if any(k in t for k in ('fire', 'campfire', 'candle', 'flame', 'spark')):
        return 'fire'
    if any(k in t for k in ('bird', 'animal', 'wildlife', 'insect', 'nature', 'forest')):
        return 'wind'
    return 'nature'


def _synthesize_ambient(sound_type, topic_text, duration_seconds):
    """Generate a soft, type-appropriate ambient bed (WAV) procedurally from
    the scene type. No hardcoded audio file is ever reused — each video gets a
    freshly synthesized bed matched to its content (waves for water scenes,
    wind for forests, etc.). Returns WAV bytes or None if numpy is missing."""
    try:
        import numpy as np
        import wave as _wave
        import io as _io
        sr = 22050
        n = int(sr * float(duration_seconds))
        if n <= 0:
            return None
        rng = np.random.default_rng(1234)
        subtype = _ambient_subtype(topic_text) if sound_type == 'ambient' else 'nature'
        white = rng.standard_normal(n).astype(np.float32)
        # brown-ish noise (low-frequency bias) for a natural rumble
        brown = np.cumsum(white) / np.sqrt(n)
        brown -= brown.mean()
        t = np.arange(n) / sr
        if subtype == 'water':
            swell = 0.5 + 0.5 * np.abs(np.sin(2 * np.pi * 0.12 * t))
            shimmer = rng.standard_normal(n).astype(np.float32) * 0.12
            sig = brown * 0.55 * swell + shimmer * swell
        elif subtype == 'rain':
            sig = brown * 0.35 + rng.standard_normal(n).astype(np.float32) * 0.22
        elif subtype == 'wind':
            slow = np.sin(2 * np.pi * 0.06 * t) * 0.5 + np.sin(2 * np.pi * 0.13 * t) * 0.25
            sig = brown * (0.55 + 0.35 * slow)
        elif subtype == 'fire':
            crackle = (rng.standard_random(n) < 0.002).astype(np.float32) * rng.standard_normal(n).astype(np.float32) * 0.5
            sig = brown * 0.4 + crackle + rng.standard_normal(n).astype(np.float32) * 0.05
        else:  # generic nature
            slow = np.sin(2 * np.pi * 0.05 * t)
            sig = brown * (0.5 + 0.25 * slow)
        fade = int(sr * 1.0)
        if fade < n:
            sig[:fade] *= np.linspace(0, 1, fade)
            sig[-fade:] *= np.linspace(1, 0, fade)
        peak = np.max(np.abs(sig)) + 1e-6
        sig = sig / peak * 0.22
        pcm = (sig * 32767).astype('<i2')
        buf = _io.BytesIO()
        wf = _wave.open(buf, 'wb')
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
        wf.close()
        return buf.getvalue()
    except Exception as e:
        logging.warning(f'ambient synth failed: {e}')
        return None


def _fit_audio_duration(mp3_bytes, target_seconds):
    """Trim/pad narration mp3 to exactly match the video duration."""
    if not HAS_PYDUB or not mp3_bytes:
        return None
    try:
        audio = AudioSegment.from_file(io.BytesIO(mp3_bytes))
        target_ms = int(target_seconds * 1000)
        if len(audio) > target_ms:
            audio = audio[:target_ms].fade_out(700)
        else:
            audio = audio + AudioSegment.silent(duration=target_ms - len(audio))
        buf = io.BytesIO()
        audio.export(buf, format="mp3", bitrate="128k")
        return buf.getvalue()
    except Exception as e:
        logging.warning(f"audio fit failed: {e}")
        return None


def _render_video_moviepy(prompt, images=None, duration=6.0, fps=24,
                           width=1280, height=720, narration_mp3=None,
                           topic=None, caption=None, style_override=None,
                           sound_type=None, text_mode=False):
    """Cinematic video renderer using MoviePy for proper 3D camera movements,
    smooth transitions, and easing curves. Falls back to the frame-based
    renderer if MoviePy is unavailable or fails.

    When images are attached: applies 3D perspective zoom/pan with crossfade.
    When no images: multi-shot SD scene keyframes with cinematic transitions.
    """
    if not HAS_MOVIEPY:
        return None

    try:
        W, H = int(width), int(height)
        fps = max(10, min(30, int(fps)))
        duration = max(2.0, min(20.0, float(duration)))
        import math

        def _ease_in_out_cubic(t):
            """Smooth ease-in-out cubic for natural camera movement."""
            if t < 0.5:
                return 4 * t * t * t
            else:
                return 1 - pow(-2 * t + 2, 3) / 2

        def _make_cinematic_clip(img_pil, shot_idx, total_shots, per_duration):
            """Create a cinematic clip from a single image with 3D perspective
            zoom and smooth pan, plus subtle drift for realism."""
            rnd = random.Random(shot_idx * 917 + 13)
            img_arr = np.array(img_pil.convert("RGB"))
            # Oversize the image for pan/zoom room
            scale = 1.4
            ow = int(W * scale)
            oh = int(H * scale)
            img_big = Image.fromarray(img_arr).resize((ow, oh), Image.LANCZOS)

            # Randomize motion: zoom-in or zoom-out, pan direction
            zoom_in = rnd.random() > 0.5
            pan_x = rnd.uniform(-0.15, 0.15)
            pan_y = rnd.uniform(-0.10, 0.10)

            def make_frame(t):
                prog = t / max(per_duration, 0.01)
                eased = _ease_in_out_cubic(min(prog, 1.0))
                # Zoom factor
                if zoom_in:
                    z = 1.0 + 0.18 * eased
                else:
                    z = 1.18 - 0.18 * eased
                # Pan offset
                ox = pan_x * eased * ow
                oy = pan_y * eased * oh
                # Crop window
                cw = int(W / z)
                ch = int(H / z)
                cx = int((ow - cw) / 2 + ox)
                cy = int((oh - ch) / 2 + oy)
                cx = max(0, min(ow - cw, cx))
                cy = max(0, min(oh - ch, cy))
                cropped = img_big.crop((cx, cy, cx + cw, cy + ch))
                frame = cropped.resize((W, H), Image.LANCZOS)
                return np.array(frame)

            clip = ImageClip(img_big.convert("RGB")).set_duration(per_duration)
            clip = clip.fl(make_frame)
            return clip

        # Build clips from images
        clips = []
        if images and len(images) >= 1:
            imgs = [im.convert("RGB") for im in images[:8]]
            n = len(imgs)
            per_dur = duration if n == 1 else duration / n
            for idx, im in enumerate(imgs):
                clip = _make_cinematic_clip(im, idx, n, per_dur)
                clips.append(clip)
        else:
            # Generate scene keyframes via SD or procedural engine
            beats = split_prompt_into_shots(topic or prompt, max_shots=3)
            per_dur = duration / max(len(beats), 1)
            for idx, beat in enumerate(beats):
                img = _sd_scene_image(beat, W, H, style_override)
                if img is None:
                    try:
                        img, _ = _render_generated_scene(beat, W, H, 0, style_override)
                    except Exception:
                        img = _gradient_frame(W, H, (26, 36, 70), (54, 82, 146))
                clip = _make_cinematic_clip(img, idx, len(beats), per_dur)
                clips.append(clip)

        if not clips:
            return None

        # Concatenate with crossfade transitions
        if len(clips) > 1:
            fade_dur = min(0.5, duration * 0.08)
            for i in range(1, len(clips)):
                clips[i] = clips[i].crossfadein(fade_dur)
            final = concatenate_videoclips(clips, method="compose",
                                           padding=-fade_dur)
        else:
            final = clips[0]

        # Fade in/out
        fade_in_dur = min(0.4, duration * 0.07)
        fade_out_dur = min(0.4, duration * 0.07)
        final = fadein(final, fade_in_dur)
        final = fadeout(final, fade_out_dur)

        # Add audio if narration provided
        audio_clip = None
        audio_path = None
        if narration_mp3:
            try:
                audio_path = os.path.join(tempfile.gettempdir(),
                                          f"mpy_audio_{os.getpid()}.mp3")
                with open(audio_path, "wb") as af:
                    af.write(narration_mp3)
                audio_clip = AudioFileClip(audio_path)
                final = final.set_audio(audio_clip)
            except Exception as e:
                logging.warning(f"MoviePy audio failed: {e}")

        # Render to temp file
        out_path = os.path.join(tempfile.gettempdir(),
                                f"mpy_render_{os.getpid()}.mp4")
        final.write_videofile(out_path, fps=fps, codec="libx264",
                              audio_codec="aac" if audio_clip else None,
                              preset="ultrafast", bitrate="2000k",
                              logger=None, threads=2)

        with open(out_path, "rb") as f:
            video_bytes = f.read()

        # Build thumbnail
        thumbnail = None
        try:
            src = images[0].convert("RGB") if images else (
                clips[0].get_frame(0) if clips else None)
            if src is not None:
                if isinstance(src, np.ndarray):
                    src = Image.fromarray(src)
                thumb = _cover_resize(src, 640, 360)
                tb = io.BytesIO()
                thumb.save(tb, format="JPEG", quality=85)
                thumbnail = base64.b64encode(tb.getvalue()).decode()
        except Exception:
            pass

        # Cleanup
        try:
            if os.path.exists(out_path):
                os.remove(out_path)
            if audio_path and os.path.exists(audio_path):
                os.remove(audio_path)
            final.close()
            for c in clips:
                c.close()
        except Exception:
            pass

        return video_bytes, thumbnail

    except Exception as e:
        logging.warning(f"MoviePy renderer failed, falling back to frame-based: {e}")
        return None


def _render_video_bytes(prompt, images=None, duration=6.0, fps=24,
                        width=1280, height=720, narration_mp3=None,
                        topic=None, caption=None, style_override=None,
                        sound_type=None, text_mode=False):
    """Render an mp4 deterministically.

    With attached images: Ken Burns slideshow of those images. Without: a
    multi-shot animated scene SYNTHESIZED from the parsed prompt by the
    local scene engine — real visuals derived from what was asked for, not
    an echo of the request text. `narration_mp3` (optional) is muxed as the
    audio track; `caption` overlays only the opening shot.
    """
    import subprocess as _sp
    import hashlib as _hashlib

    W, H = int(width), int(height)
    fps = max(10, min(30, int(fps)))
    duration = max(2.0, min(20.0, float(duration)))

    import math, random
    TAU = 2.0 * math.pi

    def _clamp(x, a=0.0, b=1.0):
        return max(a, min(b, x))

    def _split_subject_bg(base):
        """Isolate the subject (rembg) from its background so the two can be
        moved at different rates (2.5D parallax) — the core of a real 'video'
        feel without any generative model. Returns (fg_rgba, bg_rgb). rembg runs
        on a downscaled frame for speed; the mask is upscaled back to full res."""
        if not HAS_REMBG:
            return None, None
        try:
            small = base.resize((768, 432), Image.LANCZOS)
            out = rembg_remove(img_to_bytes(small), session=rembg_session)
            fg_small = Image.open(io.BytesIO(out)).convert("RGBA")
            alpha = np.array(fg_small.split()[3])
            if alpha.max() < 12:
                return None, None
            mask_full = fg_small.split()[3].resize(base.size, Image.LANCZOS)
            bg = base.convert("RGB").filter(ImageFilter.GaussianBlur(22))
            fg = base.convert("RGBA")
            fg.putalpha(mask_full)
            return fg, bg
        except Exception:
            return None, None

    def _sample(base, W, H, zoom, ox, oy):
        """Crop a W×H window from an (oversized) base with zoom + fractional pan.

        Always returns exactly W×H so downstream Image.blend / ffmpeg never see a
        size mismatch. `zoom` (>1) pulls in tighter (a Ken Burns push-in): the
        sampled region is shrunk and then upscaled back to W×H, so the output
        frame stays constant size while the content appears to zoom."""
        bw, bh = base.width, base.height
        if bw < W or bh < H:
            base = _cover_resize(base, int(W * 1.6), int(H * 1.6))
            bw, bh = base.width, base.height
        # Base pan: choose a W×H window somewhere inside the oversized base.
        cx = int((bw - W) * (0.5 + ox * 0.5))
        cy = int((bh - H) * (0.5 + oy * 0.5))
        cx = max(0, min(bw - W, cx))
        cy = max(0, min(bh - H, cy))
        if abs(zoom - 1.0) < 1e-3:
            return base.crop((cx, cy, cx + W, cy + H))
        # Zoomed push-in: sample a smaller region, then upscale to W×H.
        nw = max(2, int(round(W / zoom)))
        nh = max(2, int(round(H / zoom)))
        nw = min(nw, bw)
        nh = min(nh, bh)
        zx = max(0, min(bw - nw, cx + (W - nw) // 2))
        zy = max(0, min(bh - nh, cy + (H - nh) // 2))
        return base.crop((zx, zy, zx + nw, zy + nh)).resize((W, H), Image.LANCZOS)

    def _drift_particles(frame, t, seed):
        """Subtle floating light motes so the frame is alive, not a still."""
        W, H = frame.size
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        rnd = random.Random(seed)
        for i in range(22):
            ph = rnd.uniform(0, TAU)
            sp = rnd.uniform(0.06, 0.22)
            x = (0.5 + 0.5 * math.sin(ph + t * sp * TAU)) * W
            yy = (((1 - ((t * sp + ph / TAU) % 1)) % 1)) * H
            r = rnd.uniform(1.5, 4.0)
            a = int(50 * (0.4 + 0.6 * (0.5 + 0.5 * math.sin(ph + t * 3))))
            try:
                d.ellipse([x - r, yy - r, x + r, yy + r],
                          fill=(255, 255, 255, max(0, min(95, a))))
            except Exception:
                pass
        return Image.alpha_composite(frame.convert("RGBA"), ov).convert("RGB")

    def _put_text(frame, xy, text, font, color, alpha):
        ov = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        d.text((xy[0] + 2, xy[1] + 2), text, font=font,
                fill=(0, 0, 0, int(130 * alpha)))
        d.text(xy, text, font=font,
                fill=(color[0], color[1], color[2], int(255 * alpha)))
        return Image.alpha_composite(frame.convert("RGBA"), ov).convert("RGB")

    def _apply_motion_blur(frame, strength):
        """Simulate camera-motion blur by smearing the frame along the dominant
        movement direction. `strength` 0..1 (0 = none). This is the single most
        effective cue that makes footage read as 'real video' rather than a
        stiff Ken Burns pan — real cameras blur the scene during movement."""
        if strength <= 0.02 or strength > 0.35:
            return frame
        from PIL import ImageFilter as _MK
        # Light blur blend conveys camera motion without a soap-opera look.
        # 60% of the detected strength, damped near colour edges handled by blend.
        try:
            bl = frame.filter(_MK.GaussianBlur(strength * 2.4))
            return Image.blend(frame, bl, strength * 0.6)
        except Exception:
            return frame

    def _parallax_frame(base, fg, bg, W, H, t, shot_idx=0):
        """Cinematic motion: per-shot randomized eased zoom + 2.5D parallax +
        micro camera shake so the footage reads as real handheld video rather than
        a single still rotated in a circle."""
        # Per-shot variation: each shot gets distinct drift direction/speed
        rnd = random.Random(shot_idx * 917 + 13)
        drift_phase = rnd.uniform(0, TAU)
        drift_speed = rnd.uniform(0.85, 1.25)
        zoom_phase = rnd.uniform(-0.3, 0.3)
        # Eased cubic zoom (push-in with ease-in-out, not linear sinusoid)
        e = 0.5 - 0.5 * math.cos(TAU * t * drift_speed + zoom_phase)
        e = e * e * (3 - 2 * e)  # smoothstep
        z = 1.0 + 0.14 * e + 0.04 * math.sin(TAU * t * 0.7 + drift_phase)
        # Layered drift: background slow, subject faster (parallax)
        ox = 0.07 * math.sin(TAU * t * 0.9 * drift_speed + drift_phase) + 0.015 * math.sin(TAU * t * 2.3)
        oy = 0.04 * math.sin(TAU * t * 0.85 * drift_speed + drift_phase + 1.1) + 0.01 * math.cos(TAU * t * 1.7)
        # Micro shake (±1px) for realism, only after 15% into shot
        shake = 0.002 if t > 0.15 else 0
        sx = shake * math.sin(t * 47) * W
        sy = shake * math.cos(t * 53) * H
        if fg is not None and bg is not None:
            bf = _sample(bg, W, H, z * 0.88, ox * 0.45 + sx/W, oy * 0.45 + sy/H)
            ff = _sample(fg, W, H, z * 1.06, ox * 1.55 + sx/W, oy * 1.55 + sy/H)
            fr = Image.alpha_composite(bf.convert("RGBA"), ff).convert("RGB")
        else:
            fr = _sample(base, W, H, z, ox + sx/W, oy + sy/H)
        fr = _drift_particles(fr, t, 7 + shot_idx * 11)
        # Camera-motion blur: strongest mid-motion (when t≈0.5), weakest at
        # the pan's turnaround points (t≈0 or t≈1) — mirrors a real camera.
        motion = abs(0.5 - t) * 2.0  # 0 at start/end, 1 in middle
        fr = _apply_motion_blur(fr, 0.12 * motion)
        return _stamp_logo(fr)

    def _animate_scene(frame, scene, t, seed):
        """Object-level animation so footage is genuinely ALIVE (this is what
        separates a 'video' from a slideshow-with-camera-movement): rain and
        snow falling, storm lightning, clouds drifting, birds crossing the sky,
        water shimmering, stars twinkling, shooting stars, fireflies bobbing,
        city traffic light trails, a pulsing moon and campfire glow. All effects
        are deterministic per seed and drawn into ONE translucent overlay that is
        composited a single time, so rendering stays cheap at 24fps."""
        W, H = frame.size
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        rnd = random.Random(seed)
        tm = scene.get('time', 'day')
        weather = scene.get('weather', 'clear')
        _terrain_val = scene.get('terrain', 'meadow')
        terrain = _terrain_val if isinstance(_terrain_val, (list, tuple, set)) else [_terrain_val]
        terrain = set(terrain)
        elems = set(scene.get('elements', []) or [])
        prompt_l = str(scene.get('prompt', '')).lower()

        # ─ Rain / storm ─
        if weather in ('rain', 'storm'):
            n = 90 if weather == 'storm' else 60
            for i in range(n):
                ph = rnd.uniform(0, 1)
                row = ((t * rnd.uniform(0.5, 0.8)) + ph) % 1.0
                yy0 = int(row * H * 1.2) - int(H * 0.1)
                x0 = (ph * W + t * 26) % W
                a = int(45 * (0.5 + 0.5 * math.sin(ph * 31 + t * 6)))
                try:
                    d.line([x0, yy0, x0 + int(H * 0.014), yy0 + int(H * 0.05)],
                           fill=(178, 194, 216, max(0, min(a, 70))), width=1)
                except Exception:
                    pass
            if weather == 'storm':
                flash = (t * 0.5) % 1.0
                if flash < 0.05:
                    a = int(95 * (1 - flash / 0.05))
                    d.rectangle([0, 0, W, int(H * 0.6)], fill=(226, 238, 255, max(0, min(a, 75))))

        # ─ Snow ─
        if 'snow' in elems or any(w in prompt_l for w in ['snow', 'winter', 'ice', 'snowy']):
            for i in range(70):
                ph = rnd.uniform(0, 1)
                yy = int((H * 1.1) * ((t * rnd.uniform(0.12, 0.22)) + ph) % 1.0) - int(H * 0.06)
                x = (ph * W + t * rnd.uniform(4, 10) * math.sin(ph * 7)) % W
                r = rnd.uniform(1.2, 3.0)
                a = int(140 * (0.6 + 0.4 * math.sin(ph * 23 + t * 3)))
                d.ellipse([x - r, yy - r, x + r, yy + r], fill=(255, 255, 255, max(0, min(a, 160))))

        # ─ Stars + shooting stars ─
        if 'stars' in elems or tm in ('night', 'space') or 'space' in terrain:
            for i in range(60):
                tw = 0.5 + 0.5 * math.sin(rnd.uniform(0, 1) * 7 + t * rnd.uniform(2, 6))
                r = rnd.uniform(0.8, 2.0)
                x = int(rnd.uniform(0.02, 0.98) * W)
                y = int(rnd.uniform(0.02, 0.55) * H)
                d.ellipse([x - r, y - r, x + r, y + r],
                          fill=(255, 255, 255, int(max(0, min(160 * tw, 165)))))
            if 'space' in terrain:
                ss = (t * 0.12) % 1.0
                sx = int((0.15 + 0.7 * ss) * W)
                sy = int((0.05 + 0.35 * ss) * H)
                d.line([sx, sy, sx + 26, sy + 14], fill=(255, 255, 255, 170), width=2)
                d.line([sx + 26, sy + 14, sx + 40, sy + 22], fill=(255, 255, 255, 55), width=2)

        # ─ Fireflies (night forest) ─
        if 'fireflies' in elems:
            for i in range(26):
                ph = rnd.uniform(0, 1)
                x = (0.1 + 0.8 * ((ph * 13 + t * 0.03) % 1.0)) * W
                y = (0.45 + 0.3 * math.sin(ph * 9 + t * 1.1) + 0.2 * ph) * H
                glow = 0.5 + 0.5 * math.sin(ph * 29 + t * 4)
                r = rnd.uniform(1.0, 2.4)
                d.ellipse([x - r, y - r, x + r, y + r], fill=(246, 236, 140, int(190 * glow)))

        # ─ Drifting clouds (upper sky) ─
        if weather == 'cloudy' or (weather == 'clear' and tm in ('day', 'sunrise', 'sunset')):
            for i in range(4):
                ph = rnd.uniform(0, 1)
                xc = ((t * rnd.uniform(0.02, 0.05) + ph) % 1.2 - 0.1) * W
                yc = H * rnd.uniform(0.06, 0.24)
                rw = rnd.uniform(W * 0.12, W * 0.22)
                rh = rnd.uniform(H * 0.02, H * 0.045)
                a = int(40 * (0.5 + 0.5 * math.sin(ph * 31 + t)))
                a = max(0, min(a, 60))
                d.ellipse([xc - rw, yc - rh, xc + rw, yc + rh], fill=(255, 255, 255, a))
                d.ellipse([xc - rw * 0.5, yc - rh * 1.7, xc + rw * 0.5, yc + rh * 0.4],
                          fill=(255, 255, 255, int(a * 0.7)))

        # ─ Birds crossing the sky ─
        if 'birds' in elems:
            for i in range(3):
                ph = rnd.uniform(0, 1)
                x = ((t * rnd.uniform(0.04, 0.08) + ph) % 1.25 - 0.12) * W
                y = H * rnd.uniform(0.14, 0.36)
                flap = 1 + 0.25 * math.sin(t * rnd.uniform(6, 10) + ph * 9)
                s = rnd.uniform(3.0, 5.0)
                d.arc([x - s, y - s, x, y], 200, 370, fill=(18, 18, 22, 150), width=2)
                d.arc([x, y - s * 0.9 * flap, x + s, y], 170, 340, fill=(18, 18, 22, 150), width=2)

        # ─ Water shimmer (ocean / lake / river / beach) ─
        if ('ocean' in terrain or 'lake' in terrain) or any(w in prompt_l for w in ['sea', 'lake', 'river', 'waterfall', 'beach', 'ocean']):
            for i in range(50):
                ph = rnd.uniform(0, 1)
                x = ((t * rnd.uniform(0.05, 0.12)) + ph) % 1.0 * W
                y = H * (0.55 + 0.42 * ph)
                a = int(70 * (0.4 + 0.6 * (0.5 + 0.5 * math.sin(ph * 41 + t * 5))))
                r = rnd.uniform(1.0, 2.6)
                d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 250, 215, max(0, min(a, 90))))
            for i in range(8):
                x = ((t * rnd.uniform(0.05, 0.1)) + rnd.uniform(0, 1)) % 1.0 * W
                y = H * 0.5 + (rnd.uniform(-0.02, 0.02) * H)
                d.line([x, y, x + 14, y],
                       fill=(235, 245, 255, int(70 * (0.5 + 0.5 * math.sin(rnd.uniform(0, 1) * 17 + t * 6)))),
                       width=2)

        # ─ City traffic light trails (night) ─
        if 'city' in terrain and tm in ('night', 'sunset'):
            for i in range(34):
                ph = rnd.uniform(0, 1)
                x = ((t * rnd.uniform(0.03, 0.07) + ph) % 1.3 - 0.15) * W
                lane_y = H * (0.72 + 0.24 * rnd.uniform(0, 1))
                r = rnd.uniform(1.2, 2.2)
                warm = rnd.random() < 0.6
                col = (255, 130, 90) if warm else (170, 200, 255)
                a = int(150 * (0.5 + 0.5 * math.sin(ph * 13 + t * 4)))
                d.ellipse([x - r, lane_y - r, x + r, lane_y + r], fill=(col[0], col[1], col[2], max(0, min(a, 170))))

        # ─ Moon glow pulse ─
        if 'moon' in elems:
            glow_a = int(55 * (0.75 + 0.25 * math.sin(t * 0.8)))
            d.ellipse([W * 0.72 - W * 0.07, H * 0.10 - H * 0.07,
                       W * 0.72 + W * 0.07, H * 0.10 + H * 0.07],
                      fill=(255, 250, 225, glow_a))

        # ─ Campfire glow (night cabin) ─
        if 'cabin' in elems and tm == 'night':
            cx, cy = W * 0.5, H * 0.72
            flick = 0.6 + 0.4 * math.sin(t * 7) * math.sin(t * 3.1)
            d.ellipse([cx - W * 0.20, cy - W * 0.14, cx + W * 0.20, cy + W * 0.08],
                      fill=(255, 170, 80, int(40 * flick)))

        return Image.alpha_composite(frame.convert('RGBA'), ov).convert('RGB')

    def _text_scene_frame(scene, W, H, t):
        """Animated motion-graphics frame for text/topic videos: flowing gradient,
        a travelling light band, drifting motes, and kinetic title + bullets that
        fade in sequentially — a genuine animated clip, not a frozen slide. All
        overlays are drawn into ONE RGBA layer and composited once for speed."""
        c1, c2, accent = scene["palette"]
        base = _gradient_frame(W, H, c1, c2)
        arr = np.array(base, dtype=np.float32)
        band = int((0.5 + 0.5 * math.sin(TAU * t)) * W)
        xs = np.arange(W)[None, :]
        glow = np.exp(-((xs - band) ** 2) / (2 * (W * 0.13) ** 2))
        arr = np.clip(arr + glow[:, :, None] * 38, 0, 255).astype(np.uint8)
        fr = Image.fromarray(arr)
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        # drifting motes
        rnd = random.Random(scene["seed"])
        for i in range(22):
            ph = rnd.uniform(0, TAU)
            sp = rnd.uniform(0.06, 0.22)
            x = (0.5 + 0.5 * math.sin(ph + t * sp * TAU)) * W
            yy = (((1 - ((t * sp + ph / TAU) % 1)) % 1)) * H
            r = rnd.uniform(1.5, 4.0)
            a = int(50 * (0.4 + 0.6 * (0.5 + 0.5 * math.sin(ph + t * 3))))
            try:
                d.ellipse([x - r, yy - r, x + r, yy + r],
                          fill=(255, 255, 255, max(0, min(95, a))))
            except Exception:
                pass
        # kinetic title
        ftitle = _video_font(max(22, int(H * 0.078)))
        title = scene["title"]
        ta = _clamp((0.4 - t) / 0.4) if t < 0.4 else 1.0
        tw = d.textlength(title, font=ftitle)
        tx = (W - tw) // 2
        ty = int(H * 0.26) - int((1 - ta) * 34)
        d.text((tx + 2, ty + 2), title, font=ftitle, fill=(0, 0, 0, int(130 * ta)))
        d.text((tx, ty), title, font=ftitle, fill=(248, 249, 252, int(255 * ta)))
        # sequential bullets
        fbul = _video_font(max(16, int(H * 0.046)))
        for i, b in enumerate(scene["bullets"]):
            bt = 0.26 + i * 0.18
            if t < bt:
                continue
            ba = _clamp((t - bt) / 0.12)
            by = int(H * 0.44) + i * int(H * 0.11)
            bx = int(W * 0.16)
            d.text((bx + 2, by + 2), "• " + b, font=fbul, fill=(0, 0, 0, int(120 * ba)))
            d.text((bx, by), "• " + b, font=fbul, fill=(222, 228, 240, int(255 * ba)))
        fr = Image.alpha_composite(fr.convert("RGBA"), ov).convert("RGB")
        return _stamp_logo(fr)

    def _build_text_scenes(topic, W, H):
        topic = (topic or "Acronous Ai").strip()
        title = topic[0].upper() + topic[1:]
        if len(title) > 46:
            title = title[:43] + "..."
        try:
            shots = split_prompt_into_shots(topic, max_shots=4)
        except Exception:
            shots = [topic]
        probe = ImageDraw.Draw(Image.new("RGB", (W, H)))
        fbul = _video_font(max(16, int(H * 0.046)))
        bullets_all = []
        for s in shots:
            bullets_all.extend(_wrap_text_for_video(probe, s, fbul, int(W * 0.68)))
        bullets_all = bullets_all[:6]
        palettes = [
            ((26, 36, 70), (54, 82, 146), (255, 210, 120)),
            ((58, 30, 70), (150, 60, 132), (255, 200, 150)),
            ((18, 58, 58), (38, 128, 118), (200, 255, 220)),
            ((70, 40, 30), (168, 88, 60), (255, 220, 160)),
        ]
        scenes = [{"title": title, "bullets": [], "palette": palettes[0], "seed": 3}]
        step = max(1, (len(bullets_all) + 2) // 3)
        shown = 0
        for si in range(1, 4):
            shown = min(len(bullets_all), shown + step)
            scenes.append({"title": title, "bullets": bullets_all[:shown],
                            "palette": palettes[si % len(palettes)], "seed": 3 + si * 5})
        return scenes

    # ── Build the clip frames (real motion, not a slideshow of stills) ──
    total_frames = max(fps, int(round(duration * fps)))
    clips = []
    scene_imgs = []
    if images and len(images) >= 1:
        imgs = [im.convert("RGB") for im in images[:8]]
        n = len(imgs)
        per_frames = total_frames if n == 1 else max(fps, total_frames // n)
        for idx, im in enumerate(imgs):
            base = _cover_resize(im, int(W * 1.6), int(H * 1.6))
            fg, bg = _split_subject_bg(base)
            cf = [(_parallax_frame(base, fg, bg, W, H, i / max(1, per_frames - 1), shot_idx=idx))
                  for i in range(per_frames)]
            clips.append(cf)
    elif text_mode:
        # Explicit request for a motion-graphics / explainer / text video.
        scenes = _build_text_scenes(topic or prompt, W, H)
        n = len(scenes)
        per_frames = max(fps, total_frames // n)
        for sc in scenes:
            cf = [(_text_scene_frame(sc, W, H, i / max(1, per_frames - 1)))
                  for i in range(per_frames)]
            clips.append(cf)
    else:
        # Default: a REAL, photorealistic scene video about what was asked —
        # moving camera + drifting particles + cross-dissolves between distinct
        # shots. Keyframes are genuine SD renders (not the painterly procedural
        # engine) so the footage reads as a real photograph, never an illustration.
        # text_mode (motion-graphics card) is reserved for explicit text requests.
        beats = split_prompt_into_shots(topic or prompt, max_shots=3)
        for b in beats:
            img = _sd_scene_image(b, W, H, style_override)
            if img is None:
                try:
                    img, _ = _render_generated_scene(b, W, H, 0, style_override)
                except Exception:
                    try:
                        img, _ = _render_generated_scene(b, W, H, 0)
                    except Exception:
                        img = _gradient_frame(W, H, (26, 36, 70), (54, 82, 146))
            scene_imgs.append(img)
        beat_scenes = []
        for b in beats:
            try:
                beat_scenes.append(_parse_scene(b, style_override))
            except Exception:
                beat_scenes.append(_parse_scene(b) if callable(_parse_scene) else {"style": "realistic"})
        n = len(scene_imgs)
        per_frames = max(fps, total_frames // n)
        for idx, im in enumerate(scene_imgs):
            base = _cover_resize(im, int(W * 1.6), int(H * 1.6))
            fg, bg = _split_subject_bg(base)
            bs = beat_scenes[idx] if idx < len(beat_scenes) else {"style": "realistic"}
            # Vary shot index so each beat has distinct motion path
            cf = []
            for i in range(per_frames):
                ti = i / max(1, per_frames - 1)
                fr = _parallax_frame(base, fg, bg, W, H, ti, shot_idx=idx)
                # Object-level motion on top: rain, clouds, birds, shimmer, etc.
                fr = _animate_scene(fr, bs, ti, seed=1000 + idx * 77)
                cf.append(fr)
            clips.append(cf)

    # Poster/thumbnail for the chat bubble — ALWAYS generate so the chat shows
    # a still preview; never leave the bubble empty (was perceived as missing
    # thumbnail). Falls back to a gradient if nothing else available.
    thumbnail = None
    try:
        src = None
        if images:
            src = images[0].convert("RGB")
        elif scene_imgs:
            src = scene_imgs[0].convert("RGB")
        if src is not None:
            thumb = _cover_resize(src, 640, 360)
            tb = io.BytesIO()
            thumb.save(tb, format="JPEG", quality=85)
            thumbnail = base64.b64encode(tb.getvalue()).decode()
        else:
            # Fallback gradient thumbnail so bubble never appears blank
            thumb = _gradient_frame(640, 360, (26, 36, 70), (54, 82, 146))
            tb = io.BytesIO()
            thumb.save(tb, format="JPEG", quality=80)
            thumbnail = base64.b64encode(tb.getvalue()).decode()
    except Exception:
        thumbnail = None

    # Cross-dissolve between consecutive clips so the movie flows shot-to-shot.
    blend = max(4, int(fps * 0.4))
    rendered_imgs = []
    for i, cf in enumerate(clips):
        if i == 0:
            rendered_imgs += cf
            continue
        prev = rendered_imgs[-blend:] if len(rendered_imgs) >= blend else rendered_imgs
        cut = rendered_imgs[:-blend] if len(rendered_imgs) >= blend else []
        rendered_imgs = cut
        for b in range(blend):
            a = (b + 1) / (blend + 1)
            f1 = prev[b] if b < len(prev) else cf[0]
            rendered_imgs.append(Image.blend(f1, cf[b], a))
        rendered_imgs += cf[blend:]

    if len(rendered_imgs) > total_frames:
        rendered_imgs = rendered_imgs[:total_frames]
    while len(rendered_imgs) < total_frames:
        rendered_imgs.append(rendered_imgs[-1] if rendered_imgs
                             else Image.new("RGB", (W, H), (0, 0, 0)))

    # Fade in / out at the very edges + optional opening caption.
    fade = max(4, int(fps * 0.45))
    black = Image.new("RGB", (W, H), (0, 0, 0))
    for g in range(total_frames):
        fr = rendered_imgs[g]
        if g < fade:
            fr = Image.blend(black, fr, (g + 1) / float(fade + 1))
        elif g >= total_frames - fade:
            fr = Image.blend(black, fr, (total_frames - g) / float(fade + 1))
        rendered_imgs[g] = fr
    if caption:
        font_cap = _video_font(max(18, int(H * 0.048)))
        for g in range(min(int(fps * 1.2), total_frames)):
            rendered_imgs[g] = _draw_caption(rendered_imgs[g], caption, font_cap)

    rendered = [fr.tobytes() for fr in rendered_imgs]

    # MP4 muxer requires a seekable output — write to a temp file, not a pipe.
    out_path = os.path.join(tempfile.gettempdir(), f"render_{os.getpid()}_{id(prompt) & 0xffff}.mp4")
    audio_path = None
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
    ]
    if narration_mp3:
        audio_path = os.path.join(tempfile.gettempdir(), f"narr_{os.getpid()}_{id(prompt) & 0xffff}.mp3")
        try:
            with open(audio_path, "wb") as af:
                af.write(narration_mp3)
            cmd += ["-i", audio_path, "-map", "0:v", "-map", "1:a",
                    "-c:a", "aac", "-b:a", "128k", "-shortest"]
        except Exception:
            audio_path = None
    elif sound_type == 'ambient':
        wav = _synthesize_ambient('ambient', topic or prompt, duration)
        if wav:
            audio_path = os.path.join(tempfile.gettempdir(), f"amb_{os.getpid()}_{id(prompt) & 0xffff}.wav")
            try:
                with open(audio_path, "wb") as af:
                    af.write(wav)
                cmd += ["-i", audio_path, "-map", "0:v", "-map", "1:a",
                        "-c:a", "aac", "-b:a", "128k", "-shortest"]
            except Exception:
                audio_path = None
    cmd += [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        out_path,
    ]
    proc = _sp.Popen(cmd, stdin=_sp.PIPE, stdout=_sp.PIPE, stderr=_sp.PIPE)

    import threading as _threading

    def _feed(pipe, chunks):
        try:
            for c in chunks:
                pipe.write(c)
            pipe.close()
        except BrokenPipeError:
            pass

    try:
        chunks = rendered[:total_frames] if len(rendered) > total_frames else rendered
        feeder = _threading.Thread(target=_feed, args=(proc.stdin, chunks))
        feeder.start()
        err = proc.stderr.read()
        rc = proc.wait()
        feeder.join(timeout=30)
        if rc != 0:
            raise RuntimeError(f"ffmpeg failed: {err.decode('utf-8', 'ignore')[:400]}")
        with open(out_path, "rb") as f:
            out = f.read()
        return out, thumbnail
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
        raise
    finally:
        try:
            if os.path.exists(out_path):
                os.remove(out_path)
            if audio_path and os.path.exists(audio_path):
                os.remove(audio_path)
        except Exception:
            pass

@app.post("/generate-video")
async def api_generate_video(
    prompt: str = Form(...),
    duration: float = Form(6.0),
    fps: int = Form(24),
    width: int = Form(1280),
    height: int = Form(720),
    narrate: bool = Form(True),
    sound_type: str = Form(""),
    topic: str = Form(""),
    style: str = Form(""),
    text_mode: bool = Form(False),
    async_mode: bool = Form(False),
    images: List[UploadFile] = File(None),
):
    """Render a context-aware video from the request.

    With attached images: Ken Burns slideshow of those exact images. Without:
    a real, synthesized multi-shot scene video (moving camera + animated
    objects + transitions) by default. `text_mode` switches to a motion-graphics
    / explainer card (only when the user explicitly asked for a text/summary/
    explainer video).

    `async_mode=1` starts the render in a background job and returns
    `{job_id, status: "queued"}` so long renders (narration + SD keyframes +
    ffmpeg, which can exceed a proxy/edge idle timeout) complete without a
    synchronous response; the caller polls GET /jobs/{job_id} until done.
    """
    if not prompt.strip():
        raise HTTPException(400, "No prompt provided")
    prompt = prompt.strip()[:2000]
    topic = (topic or "")[:300]
    try:
        pil_images = []
        for f in (images or []):
            data = await f.read()
            if not data:
                continue
            fname = (f.filename or "").lower()
            try:
                # PDF: convert first page(s) to images for video frames
                if fname.endswith(".pdf") or data[:4] == b"%PDF":
                    try:
                        import fitz  # PyMuPDF
                        pdf_doc = fitz.open(stream=data, filetype="pdf")
                        for page_idx in range(min(len(pdf_doc), 6)):
                            page = pdf_doc[page_idx]
                            mat = fitz.Matrix(2.0, 2.0)  # 2x upscale
                            pix = page.get_pixmap(matrix=mat)
                            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                            pil_images.append(img)
                        pdf_doc.close()
                    except ImportError:
                        # Fallback: try pdf2image if PyMuPDF unavailable
                        try:
                            from pdf2image import convert_from_bytes
                            pdf_imgs = convert_from_bytes(data, dpi=200, first_page=1, last_page=6)
                            pil_images.extend(pdf_imgs)
                        except Exception:
                            logging.warning("PDF conversion failed — no PDF library available")
                    continue
                # Regular images (PNG, JPG, etc.)
                im = Image.open(io.BytesIO(data))
                im.load()
                pil_images.append(im)
            except Exception:
                logging.warning(f"generate-video: skipping unreadable image {f.filename}")

        def _render_all():
            narration = None
            caption = None
            narrated = False
            if not pil_images and narrate:
                clean_topic = (topic or "").strip() or _clean_topic(prompt)
                _img, scene_meta = _render_generated_scene(clean_topic or prompt.strip(), 320, 180, 0)
                description = _describe_scene(scene_meta)
                script = _narration_script(clean_topic, description)
                raw_audio = _asyncio.run(_synthesize_narration(script))
                if raw_audio:
                    narration = _fit_audio_duration(raw_audio, float(duration))
                    narrated = narration is not None
            # CAPTION: only when user explicitly asked for a text/explainer/caption
            # video (text_mode). Never auto-overlay the prompt as text on a
            # realistic scene video — that was perceived as a "text video of my message".
            if text_mode and (topic or "").strip() and len((topic or "").strip()) <= 90:
                caption = (topic or "").strip()

            video_bytes, thumbnail = None, None
            # Try MoviePy cinematic renderer first (proper 3D camera moves,
            # smooth crossfade transitions, eased movements).
            if HAS_MOVIEPY:
                try:
                    result = _render_video_moviepy(
                        prompt.strip(), pil_images or None, duration, fps,
                        width, height, narration,
                        (topic or "").strip() or None, caption,
                        (style or "").strip() or None,
                        sound_type=(sound_type or "").strip() or None,
                        text_mode=text_mode,
                    )
                    if result is not None:
                        video_bytes, thumbnail = result
                except Exception as e:
                    logging.warning(f"MoviePy cinematic render failed: {e}")
            # Fallback to frame-based Ken Burns renderer
            if video_bytes is None:
                video_bytes, thumbnail = _render_video_bytes(
                    prompt.strip(), pil_images or None, duration, fps, width, height,
                    narration, (topic or "").strip() or None, caption, (style or "").strip() or None,
                    sound_type=(sound_type or "").strip() or None, text_mode=text_mode,
                )
            payload = {
                "video_data": base64.b64encode(video_bytes).decode(),
                "format": "mp4",
                "fps": fps,
                "duration": duration,
                "width": width,
                "height": height,
                "narrated": narrated,
            }
            if thumbnail:
                payload["thumbnail"] = thumbnail
            return payload

        if bool(async_mode):
            return _start_edit_job(_render_all, ())
        return await _asyncio.to_thread(_render_all)
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Video render error: {e}")
        raise HTTPException(500, f"Video rendering failed: {str(e)}")

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
