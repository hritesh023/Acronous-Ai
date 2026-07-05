"""
Acronous AI - Image Editing Service

CPU-first image editing using:
- rembg (free CPU-based segmentation)
- Pillow + numpy (compositing, color matching, smart editing)
- Optional: diffusers + torch (GPU inpainting)

Strategies:
1. SD Inpainting (GPU) - best quality
2. rembg + Smart Compositing (CPU) - good for clothing/style changes
3. Color Palette Transfer (CPU) - works when no GPU available
"""

import io
import os
import re
import json
import base64
import logging
from typing import Optional
from urllib.parse import quote_plus

import numpy as np
import requests
from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageEnhance, ImageStat

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
HAS_TORCH_CUDA = False
try:
    import torch
    HAS_TORCH_CUDA = torch.cuda.is_available()
except ImportError:
    pass

SD_PIPE = None

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
    Apply a color palette to the masked region.
    palette: list of (r, g, b) tuples defining the target colors.
    """
    m = np.array(mask.convert("L"), dtype=np.float32) / 255.0
    img = np.array(image.convert("RGB"), dtype=np.float32)
    h, w = img.shape[:2]

    palette = np.array(palette, dtype=np.float32)
    result = img.copy()

    # Simple per-pixel nearest palette color, weighted by mask
    for y in range(h):
        for x in range(w):
            if m[y, x] > 0.3:
                pixel = img[y, x]
                dists = np.sum((palette - pixel) ** 2, axis=1)
                nearest = palette[np.argmin(dists)]
                result[y, x] = result[y, x] * (1 - m[y, x]) + nearest * m[y, x]

    return Image.fromarray(result.astype(np.uint8))

def recolor_region(image: Image.Image, mask: Image.Image, target_color: tuple) -> Image.Image:
    """
    Recolor the masked region to target_color while preserving texture/luminosity.
    """
    m = np.array(mask.convert("L"), dtype=np.float32) / 255.0
    img = np.array(image.convert("RGB"), dtype=np.float32)

    # Convert to HSL-like: preserve L, replace H and S
    gray = np.mean(img, axis=2)  # luminosity proxy
    tc = np.array(target_color, dtype=np.float32)
    tc_gray = np.mean(tc)

    for c in range(3):
        adjustment = tc[c] / (tc_gray + 1e-6)
        img[:, :, c] = img[:, :, c] * (1 - m) + (gray * adjustment) * m

    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))

def smart_recolor(
    image: Image.Image,
    mask: Image.Image,
    replacement_desc: str,
) -> Image.Image:
    """
    Smart recoloring based on replacement description.
    Maps descriptions to color palettes and applies them.
    """
    desc = replacement_desc.lower()

    # Color/style mapping
    style_map = {
        "formal suit": [(40, 40, 60), (50, 50, 75), (60, 60, 85), (35, 35, 55)],
        "suit": [(40, 40, 60), (50, 50, 75)],
        "tuxedo": [(20, 20, 25), (30, 30, 35), (15, 15, 20)],
        "blazer": [(50, 60, 100), (60, 70, 110), (45, 55, 95)],
        "navy suit": [(30, 35, 65), (40, 45, 75), (25, 30, 60)],
        "black suit": [(25, 25, 28), (35, 35, 38), (20, 20, 22)],
        "grey suit": [(100, 100, 105), (120, 120, 125), (90, 90, 95)],
        "white shirt": [(235, 235, 240), (245, 245, 248), (225, 225, 230)],
        "red dress": [(180, 40, 40), (160, 30, 30), (200, 50, 50)],
        "black dress": [(30, 30, 35), (40, 40, 45), (25, 25, 28)],
        "blue dress": [(40, 60, 140), (50, 70, 150), (35, 55, 130)],
        "jeans": [(50, 70, 120), (60, 80, 130)],
        "casual": [(100, 150, 180), (120, 160, 190)],
        "traditional": [(180, 100, 60), (190, 110, 70), (170, 90, 50)],
        "sporty": [(200, 50, 50), (50, 100, 200), (255, 255, 255)],
    }

    for key, palette in style_map.items():
        if key in desc:
            return apply_color_palette(image, mask, palette)

    # Default: try to extract color from desc
    color_patterns = [
        (r"black", (25, 25, 28)),
        (r"white", (240, 240, 245)),
        (r"red", (180, 40, 40)),
        (r"blue", (40, 60, 140)),
        (r"green", (40, 130, 60)),
        (r"navy", (30, 35, 65)),
        (r"grey|gray", (120, 120, 125)),
        (r"brown", (140, 80, 40)),
        (r"purple", (120, 40, 140)),
        (r"pink", (200, 100, 120)),
        (r"yellow", (200, 180, 40)),
        (r"gold", (200, 170, 40)),
        (r"silver", (180, 180, 190)),
    ]
    for pat, color in color_patterns:
        if re.search(pat, desc):
            return recolor_region(image, mask, color)

    # Default: formal navy suit
    return apply_color_palette(image, mask, style_map["formal suit"])

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

    # Detect action
    if any(w in p for w in ["replace", "change to", "switch", "turn into", "convert to"]):
        action = "replace"
    elif any(w in p for w in ["remove", "delete", "erase", "take off"]):
        action = "remove"
    elif any(w in p for w in ["add", "put", "insert", "place"]):
        action = "add"
    elif any(w in p for w in ["color", "recolor", "paint"]):
        action = "recolor"
    else:
        action = "edit"

    # Extract replacement description
    replacement = prompt
    for prefix in [
        r"(?:replace|change|switch|turn|convert)\s+(?:the\s+|my\s+|this\s+)?(?:\w+\s+)?(?:with|to|into)\s+",
        r"(?:make\s+(?:it|this|the)\s+)(?:\w+\s+)?",
        r"(?:edit\s+(?:the\s+|my\s+|this\s+)?(?:\w+\s+)?(?:to\s+)?)",
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
        # Ensure mask has some content
        m_arr = np.array(mask)
        if np.max(m_arr) < 10:
            mask = None

    result = None
    strategy = "none"

    # Strategy 1: GPU inpainting (best quality)
    if result is None and HAS_TORCH_CUDA and mask is not None:
        sd_prompt = f"A {info['replacement']}, high quality, detailed, realistic"
        inpainted = inpaint_sd(image, mask, sd_prompt)
        if inpainted is not None:
            result = feather_blend(image, inpainted, mask, radius=8)
            strategy = "sd_inpaint"

    # Strategy 2: CPU smart recolor (always available)
    if result is None and mask is not None:
        if info["action"] in ("replace", "recolor", "edit"):
            result = smart_recolor(image, mask, info["replacement"])
            strategy = "smart_recolor"
            # Enhance quality
            result = ImageEnhance.Sharpness(result).enhance(1.1)
            result = ImageEnhance.Contrast(result).enhance(1.05)

    # Strategy 3: Full image edit (no mask needed)
    if result is None:
        # Color the entire image based on prompt
        w, h = image.size
        full_mask = Image.new("L", (w, h), 200)
        result = smart_recolor(image, full_mask, info["replacement"])
        strategy = "full_recolor"

    # Return result
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
    return {"mask": img_to_b64(mask, "PNG"), "width": img.width, "height": img.height}

@app.post("/remove-bg")
async def api_remove_bg(file: UploadFile = File(...)):
    if not HAS_REMBG:
        raise HTTPException(500, "rembg not available")
    data = await file.read()
    out = rembg_remove(data, session=rembg_session)
    return {"edited": base64.b64encode(out).decode()}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 7860))
    uvicorn.run(app, host="0.0.0.0", port=port)
