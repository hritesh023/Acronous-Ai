import io
import os
import math
import random
import colorsys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance, ImageOps, ImageChops
import numpy as np
import torch

ASSETS_DIR = Path(__file__).parent.parent.parent / "assets"
LOGO_PATH = ASSETS_DIR / "logo.png"


class ImageGenerator:
    def __init__(self, config):
        self.config = config
        self._pipe = None
        self._is_available = False
        self._hf_api_token = os.getenv("HF_API_TOKEN", "")
        self._hf_model_id = os.getenv("APEX_HF_IMAGE_MODEL", "black-forest-labs/FLUX.1-dev")
        self._init_pipeline()

    def _init_pipeline(self):
        models_to_try = [
            "runwayml/stable-diffusion-v1-5",
            "prompthero/openjourney-v4",
            "dreamshaper/dreamshaper-8",
        ]
        for model in models_to_try:
            try:
                from diffusers import StableDiffusionPipeline, DPMSolverMultistepScheduler
                self._pipe = StableDiffusionPipeline.from_pretrained(
                    model, torch_dtype=torch.float32, safety_checker=None
                )
                self._pipe.scheduler = DPMSolverMultistepScheduler.from_config(
                    self._pipe.scheduler.config
                )
                self._pipe = self._pipe.to("cpu")
                if hasattr(self._pipe, "enable_attention_slicing"):
                    self._pipe.enable_attention_slicing()
                self._is_available = True
                break
            except Exception:
                continue

    def is_available(self):
        return self._is_available

    def generate(self, prompt, negative_prompt=None, steps=20):
        if self._is_available and self._pipe is not None:
            return self._generate_diffusers(prompt, negative_prompt, steps)
        if self._hf_api_token:
            return self._generate_hf_api(prompt)
        api_key = os.getenv("APEX_LLM_API_KEY", "")
        provider = os.getenv("APEX_IMAGE_PROVIDER", "auto").lower()
        if provider == "openai" or (provider == "auto" and os.getenv("APEX_LLM_PROVIDER", "").lower() == "openai"):
            if api_key:
                return self._generate_openai_image(prompt)
        if provider == "replicate" or provider == "auto":
            repl_key = os.getenv("REPLICATE_API_TOKEN", "")
            if repl_key:
                return self._generate_replicate(prompt)
        return self._generate_pil(prompt)

    def redesign(self, image, prompt, strength=0.7):
        if self._is_available and self._pipe is not None:
            return self._redesign_diffusers(image, prompt, strength)
        if self._hf_api_token:
            return self._redesign_hf_api(image, prompt)
        api_key = os.getenv("APEX_LLM_API_KEY", "")
        provider = os.getenv("APEX_IMAGE_PROVIDER", "auto").lower()
        if provider == "openai" or (provider == "auto" and os.getenv("APEX_LLM_PROVIDER", "").lower() == "openai"):
            if api_key:
                return self._redesign_openai_image(image, prompt)
        return self._redesign_pil(image, prompt)

    def _generate_diffusers(self, prompt, negative_prompt=None, steps=20):
        try:
            neg = negative_prompt or "blurry, bad quality, distorted"
            result = self._pipe(
                prompt,
                negative_prompt=neg,
                num_inference_steps=min(steps, 25),
                guidance_scale=7.5,
                height=512,
                width=512,
            )
            img = result.images[0]
            img = img.resize((768, 768), Image.LANCZOS)
            img = self._add_watermark(img)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue(), None
        except Exception as e:
            return None, str(e)

    def _redesign_diffusers(self, image, prompt, strength=0.7):
        try:
            if isinstance(image, str):
                image = Image.open(image)
            if image.mode != "RGB":
                image = image.convert("RGB")
            init_image = image.resize((512, 512))
            result = self._pipe(
                prompt,
                image=init_image,
                strength=min(strength, 0.9),
                guidance_scale=7.5,
                num_inference_steps=25,
            )
            img = result.images[0]
            img = img.resize((768, 768), Image.LANCZOS)
            img = self._add_watermark(img)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue(), None
        except Exception as e:
            return None, str(e)

    def _generate_hf_api(self, prompt):
        models_fallback = [
            self._hf_model_id,
            "black-forest-labs/FLUX.1-dev",
            "stabilityai/stable-diffusion-xl-base-1.0",
            "runwayml/stable-diffusion-v1-5",
            "prompthero/openjourney-v4",
        ]
        seen = set()
        for model in models_fallback:
            if model in seen:
                continue
            seen.add(model)
            try:
                import requests
                payload = {
                    "inputs": prompt,
                    "parameters": {
                        "negative_prompt": "blurry, low quality, distorted, ugly, deformed",
                        "num_inference_steps": 30,
                        "guidance_scale": 7.5,
                    }
                }
                headers = {"Authorization": f"Bearer {self._hf_api_token}"}
                resp = requests.post(
                    f"https://api-inference.huggingface.co/models/{model}",
                    headers=headers, json=payload, timeout=120
                )
                if resp.status_code == 200:
                    content_type = resp.headers.get("content-type", "")
                    if "image" in content_type or len(resp.content) > 1000:
                        return resp.content, None
                if resp.status_code == 503:
                    continue
            except Exception:
                continue
        return None, "All HuggingFace models failed"

    def _redesign_hf_api(self, image, prompt):
        try:
            import requests
            buf = io.BytesIO()
            image.save(buf, format="JPEG")
            payload = {"inputs": prompt, "parameters": {"strength": 0.7}}
            headers = {"Authorization": f"Bearer {self._hf_api_token}"}
            files = {"image": buf.getvalue()}
            resp = requests.post(
                f"https://api-inference.huggingface.co/models/{self._hf_model_id}",
                headers=headers, data=payload, files=files, timeout=60
            )
            if resp.status_code == 200:
                return resp.content, None
            return None, f"API error: {resp.status_code}"
        except Exception as e:
            return None, str(e)

    def _generate_openai_image(self, prompt):
        try:
            from openai import OpenAI
            client = OpenAI(api_key=os.getenv("APEX_LLM_API_KEY", ""))
            resp = client.images.generate(
                model=os.getenv("APEX_OPENAI_IMAGE_MODEL", "dall-e-3"),
                prompt=prompt,
                n=1,
                size=os.getenv("APEX_OPENAI_IMAGE_SIZE", "1024x1024"),
                response_format="b64_json",
            )
            import base64
            img_bytes = base64.b64decode(resp.data[0].b64_json)
            return img_bytes, None
        except Exception as e:
            return None, str(e)

    def _redesign_openai_image(self, image, prompt):
        try:
            from openai import OpenAI
            import base64
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            client = OpenAI(api_key=os.getenv("APEX_LLM_API_KEY", ""))
            resp = client.images.edit(
                model=os.getenv("APEX_OPENAI_IMAGE_MODEL", "dall-e-2"),
                image=io.BytesIO(base64.b64decode(b64)),
                prompt=prompt,
                n=1,
                size="512x512",
            )
            img_bytes = base64.b64decode(resp.data[0].b64_json) if hasattr(resp.data[0], "b64_json") else None
            if img_bytes:
                return img_bytes, None
            import requests
            img_resp = requests.get(resp.data[0].url)
            return img_resp.content, None
        except Exception as e:
            return None, str(e)

    def _generate_replicate(self, prompt):
        try:
            import replicate
            output = replicate.run(
                os.getenv("APEX_REPLICATE_MODEL", "black-forest-labs/flux-dev"),
                input={"prompt": prompt, "num_outputs": 1, "aspect_ratio": "1:1"},
            )
            if output and len(output) > 0:
                import requests
                img_resp = requests.get(str(output[0]))
                return img_resp.content, None
            return None, "Replicate returned no output"
        except Exception as e:
            return None, str(e)

    def _add_watermark(self, img):
        try:
            if not LOGO_PATH.exists():
                return img
            logo = Image.open(LOGO_PATH).convert("RGBA")
            logo_size = max(img.width, img.height) // 10
            logo.thumbnail((logo_size, logo_size), Image.LANCZOS)
            l_w, l_h = logo.size
            margin = max(img.width, img.height) // 40
            pos_x = img.width - l_w - margin
            pos_y = img.height - l_h - margin
            logo_alpha = logo.split()[3]
            alpha = logo_alpha.point(lambda p: int(p * 0.5))
            logo.putalpha(alpha)
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            img.paste(logo, (pos_x, pos_y), logo)
            return img.convert("RGB")
        except Exception:
            return img

    # ─────────────────────────────────────────────────
    #  PIL-BASED GENERATION (no diffusers)
    # ─────────────────────────────────────────────────

    def _generate_pil(self, prompt):
        try:
            w, h = 768, 768
            img = self._render_scene(prompt, w, h)
            img = self._add_watermark(img)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue(), None
        except Exception as e:
            return None, str(e)

    def _redesign_pil(self, image, prompt):
        try:
            if isinstance(image, str):
                image = Image.open(image)
            if image.mode != "RGB":
                image = image.convert("RGB")
            image = image.resize((768, 768))
            img = self._apply_artistic_effect(image, prompt)
            img = self._add_watermark(img)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue(), None
        except Exception as e:
            return None, str(e)

    # ═════════════════════════════════════════════════
    #  SCENE RENDERER
    # ═════════════════════════════════════════════════

    def _enhance_composition(self, img):
        img = ImageEnhance.Contrast(img).enhance(1.1)
        img = ImageEnhance.Color(img).enhance(1.15)
        img = img.filter(ImageFilter.SMOOTH)
        overlay = Image.new("RGB", img.size, (0, 0, 0))
        overlay = ImageEnhance.Brightness(overlay).enhance(0.03)
        img = Image.blend(img, overlay, 0.08)
        return img

    def _render_scene(self, prompt, w, h):
        kw = prompt.lower()
        img = Image.new("RGB", (w, h), (240, 240, 245))
        draw = ImageDraw.Draw(img)
        seed = abs(hash(prompt)) & 0x7FFFFFFF
        rng = random.Random(seed)

        if any(w in kw for w in ["sunset", "sunrise", "dusk", "dawn"]):
            return self._render_sunset(w, h, rng, kw)
        elif any(w in kw for w in ["mountain", "landscape", "valley", "hill", "wilderness"]):
            return self._render_mountains(w, h, rng, kw)
        elif any(w in kw for w in ["ocean", "sea", "water", "wave", "underwater", "beach", "coast"]):
            return self._render_ocean(w, h, rng, kw)
        elif any(w in kw for w in ["space", "galaxy", "cosmos", "universe", "nebula", "planet"]):
            return self._render_space(w, h, rng, kw)
        elif any(w in kw for w in ["city", "urban", "building", "skyline"]):
            return self._render_city(w, h, rng, kw)
        elif any(w in kw for w in ["cyberpunk", "neon"]):
            return self._render_cyberpunk(w, h, rng, kw)
        elif any(w in kw for w in ["abstract", "modern", "art", "geometric", "psychedelic", "vibrant"]):
            return self._render_abstract(w, h, rng, kw)
        elif any(w in kw for w in ["cat", "dog", "animal", "pet", "cute", "puppy", "kitten", "wildlife"]):
            return self._render_animal(w, h, rng, kw)
        elif any(w in kw for w in ["flower", "garden", "plant", "botanical", "floral", "rose", "bloom", "meadow"]):
            return self._render_floral(w, h, rng, kw)
        elif any(w in kw for w in ["portrait", "person", "face", "human", "woman", "man", "people"]):
            return self._render_portrait(w, h, rng, kw)
        elif any(w in kw for w in ["fantasy", "magic", "castle", "dragon", "medieval", "mythical", "enchanted", "ethereal"]):
            return self._render_fantasy(w, h, rng, kw)
        elif any(w in kw for w in ["food", "meal", "dish", "cuisine", "fruit", "vegetable", "delicious", "cake", "pizza", "pasta", "burger"]):
            return self._render_food(w, h, rng, kw)
        elif any(w in kw for w in ["snow", "winter", "ice", "cold", "frost", "arctic", "blizzard"]):
            return self._render_winter(w, h, rng, kw)
        elif any(w in kw for w in ["fire", "flame", "lava", "volcano", "heat", "blaze", "inferno"]):
            return self._render_fire(w, h, rng, kw)
        elif any(w in kw for w in ["rain", "rainy", "storm", "thunder", "lightning", "cloud", "fog", "mist"]):
            return self._render_storm(w, h, rng, kw)
        elif any(w in kw for w in ["desert", "sahara", "dune", "cactus", "arid", "dry"]):
            return self._render_desert(w, h, rng, kw)
        elif any(w in kw for w in ["aurora", "borealis", "northern", "lights", "polar"]):
            return self._render_aurora(w, h, rng, kw)
        elif any(w in kw for w in ["waterfall", "river", "stream", "lake", "pond", "creek", "water body"]):
            return self._render_waterfall(w, h, rng, kw)
        elif any(w in kw for w in ["crystal", "gem", "diamond", "jewel", "sparkle", "shiny"]):
            return self._render_crystal(w, h, rng, kw)
        elif any(w in kw for w in ["autumn", "fall", "foliage", "maple", "harvest", "pumpkin"]):
            return self._render_autumn(w, h, rng, kw)
        elif any(w in kw for w in ["temple", "pagoda", "japanese", "oriental", "cherry blossom", "bamboo"]):
            return self._render_japanese(w, h, rng, kw)
        elif any(w in kw for w in ["steampunk", "victorian", "clockwork", "gear", "brass", "airship"]):
            return self._render_steampunk(w, h, rng, kw)
        elif any(w in kw for w in ["pattern", "wallpaper", "mandala", "ornate", "decorative", "tile"]):
            return self._render_pattern(w, h, rng, kw)
        else:
            return self._render_generic(w, h, rng, kw)

    # ═════════════════════════════════════════════════
    #  HELPERS
    # ═════════════════════════════════════════════════

    def _gradient(self, w, h, colors):
        img = Image.new("RGB", (w, h))
        draw = ImageDraw.Draw(img)
        n = len(colors)
        for y in range(h):
            t = y / max(h - 1, 1)
            idx = t * (n - 1)
            i = int(idx)
            f = idx - i
            if i >= n - 1:
                c = colors[-1]
            else:
                c1, c2 = colors[i], colors[i + 1]
                c = tuple(int(a + (b - a) * f) for a, b in zip(c1, c2))
            draw.line([(0, y), (w, y)], fill=c)
        return img

    def _gradient_horizontal(self, w, h, colors):
        img = Image.new("RGB", (w, h))
        draw = ImageDraw.Draw(img)
        n = len(colors)
        for x in range(w):
            t = x / max(w - 1, 1)
            idx = t * (n - 1)
            i = int(idx)
            f = idx - i
            if i >= n - 1:
                c = colors[-1]
            else:
                c1, c2 = colors[i], colors[i + 1]
                c = tuple(int(a + (b - a) * f) for a, b in zip(c1, c2))
            draw.line([(x, 0), (x, h)], fill=c)
        return img

    def _radial_gradient(self, w, h, cx, cy, inner_color, outer_color):
        img = Image.new("RGB", (w, h))
        draw = ImageDraw.Draw(img)
        max_r = math.sqrt(max(cx, w - cx) ** 2 + max(cy, h - cy) ** 2)
        for x in range(w):
            for y in range(h):
                d = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
                t = min(d / max_r, 1.0)
                c = tuple(int(a + (b - a) * t) for a, b in zip(inner_color, outer_color))
                draw.point((x, y), fill=c)
        return img

    def _diagonal_gradient(self, w, h, colors):
        img = Image.new("RGB", (w, h))
        draw = ImageDraw.Draw(img)
        max_d = math.sqrt(w * w + h * h)
        n = len(colors)
        for x in range(w):
            for y in range(h):
                d = (x + y) / max_d
                idx = d * (n - 1)
                i = int(idx)
                f = idx - i
                if i >= n - 1:
                    c = colors[-1]
                else:
                    c1, c2 = colors[i], colors[i + 1]
                    c = tuple(int(a + (b - a) * f) for a, b in zip(c1, c2))
                draw.point((x, y), fill=c)
        return img

    def _cloud_texture(self, w, h, rng=None):
        if rng is None:
            rng = random
        base = Image.new("L", (w, h), 0)
        for _ in range(rng.randint(3, 6)):
            cx, cy = rng.randint(0, w), rng.randint(0, h)
            cr = rng.randint(50, 200)
            layer = Image.new("L", (w, h), 0)
            ld = ImageDraw.Draw(layer)
            br = rng.randint(80, 180)
            ld.ellipse([cx - cr, cy - cr // 2, cx + cr, cy + cr // 2], fill=br)
            layer = layer.filter(ImageFilter.GaussianBlur(radius=rng.randint(20, 60)))
            base = ImageChops.screen(base, layer)
        return base

    def _perlin_noise(self, w, h, scale=30, rng=None):
        if rng is None:
            rng = random
        g = np.random.default_rng(rng.randint(0, 2**31))
        gradients = g.uniform(-1, 1, (h // scale + 2, w // scale + 2, 2))
        noise = np.zeros((h, w))
        for y in range(h):
            for x in range(w):
                ix, iy = x // scale, y // scale
                fx, fy = (x % scale) / scale, (y % scale) / scale
                g00 = gradients[iy, ix]
                g10 = gradients[iy, ix + 1]
                g01 = gradients[iy + 1, ix]
                g11 = gradients[iy + 1, ix + 1]
                n00 = g00[0] * fx + g00[1] * fy
                n10 = g10[0] * (fx - 1) + g10[1] * fy
                n01 = g01[0] * fx + g01[1] * (fy - 1)
                n11 = g11[0] * (fx - 1) + g11[1] * (fy - 1)
                u = fx * fx * (3 - 2 * fx)
                v = fy * fy * (3 - 2 * fy)
                nx0 = n00 + (n10 - n00) * u
                nx1 = n01 + (n11 - n01) * u
                noise[y, x] = nx0 + (nx1 - nx0) * v
        noise = ((noise - noise.min()) / (noise.max() - noise.min() + 1e-8) * 255).astype(np.uint8)
        return Image.fromarray(noise, mode="L")

    def _noise_texture(self, w, h, alpha=0.15, rng=None):
        if rng is None:
            rng = random
        noise = np.random.default_rng(rng.randint(0, 2**31)).random((h, w)) * 255 * alpha
        return Image.fromarray(noise.astype(np.uint8)).convert("L")

    def _add_noise(self, img, alpha=0.1, rng=None):
        noise = self._noise_texture(*img.size, alpha, rng)
        noise = noise.convert("RGB")
        return ImageChops.soft_light(img, noise)

    def _blend(self, base, overlay, alpha):
        return Image.blend(base, overlay, alpha)

    def _clamp(self, v, lo=0, hi=255):
        return max(lo, min(hi, int(v)))

    def _soft_glow(self, img, radius=20):
        blur = img.filter(ImageFilter.GaussianBlur(radius=radius))
        return ImageChops.screen(img, blur)

    def _add_sunlight_rays(self, img, w, h, rng):
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        sx, sy = rng.randint(w // 3, 2 * w // 3), rng.randint(0, h // 4)
        for _ in range(rng.randint(8, 16)):
            angle = rng.uniform(-0.6, 0.6)
            length = rng.randint(h // 2, h)
            for t in range(0, length, 5):
                x = int(sx + t * math.sin(angle))
                y = sy + t
                if 0 <= x < w and 0 <= y < h:
                    a = max(0, int(40 * (1 - t / length) * rng.uniform(0.3, 1.0)))
                    od.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(255, 255, 200, a))
        overlay = overlay.filter(ImageFilter.GaussianBlur(radius=6))
        return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    def _draw_stars(self, draw, w, h, rng, count=200, max_bright=255):
        for _ in range(count):
            x, y = rng.randint(0, w - 1), rng.randint(0, h - 1)
            b = rng.randint(100, max_bright)
            r = rng.choice([1, 1, 1, 2])
            draw.ellipse([x - r, y - r, x + r, y + r], fill=(b, b, b))
            if rng.random() > 0.96:
                r2 = r + 1
                draw.ellipse([x - r2, y - r2, x + r2, y + r2],
                             fill=(b, b, rng.randint(150, 255)))

    def _draw_moons(self, draw, w, h, rng):
        mx, my = rng.randint(w // 4, 3 * w // 4), rng.randint(h // 6, h // 3)
        mr = rng.randint(25, 45)
        moon_color = (rng.randint(230, 255), rng.randint(230, 255), rng.randint(210, 240))
        draw.ellipse([mx - mr, my - mr, mx + mr, my + mr], fill=moon_color)
        shadow_offset = rng.randint(5, 12)
        draw.ellipse([mx - mr + shadow_offset, my - mr, mx + mr + shadow_offset, my + mr],
                     fill=(rng.randint(5, 20), rng.randint(5, 20), rng.randint(15, 35)))
        glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.ellipse([mx - mr * 3, my - mr * 3, mx + mr * 3, my + mr * 3],
                   fill=(moon_color[0], moon_color[1], moon_color[2], 20))
        return glow.filter(ImageFilter.GaussianBlur(radius=20)), mx, my, mr

    def _color_palette(self, theme):
        palettes = {
            "sunset": [(25, 10, 50), (80, 20, 60), (180, 60, 80), (240, 120, 60), (255, 180, 50)],
            "ocean": [(5, 30, 60), (10, 50, 90), (20, 80, 140), (30, 100, 170), (40, 130, 200)],
            "forest": [(10, 30, 10), (20, 50, 20), (30, 70, 30), (50, 100, 40), (70, 130, 50)],
            "desert": [(100, 160, 200), (180, 200, 210), (210, 190, 150), (180, 160, 100)],
            "space": [(2, 1, 10), (5, 2, 25), (10, 3, 40), (5, 2, 30)],
            "aurora": [(5, 10, 30), (10, 20, 50), (5, 15, 40), (3, 5, 25)],
            "fantasy": [(15, 5, 40), (30, 10, 60), (50, 20, 80), (30, 15, 60)],
            "winter": [(180, 200, 230), (200, 215, 240), (220, 230, 245), (230, 235, 245)],
            "cyberpunk": [(5, 1, 20), (15, 5, 40), (30, 10, 60), (20, 5, 50)],
            "autumn": [(40, 20, 10), (80, 40, 15), (140, 70, 20), (180, 100, 30), (200, 130, 50)],
            "dawn": [(30, 20, 50), (60, 40, 60), (120, 80, 70), (180, 140, 80), (220, 190, 120)],
            "neon": [(5, 1, 20), (15, 5, 40), (5, 1, 30), (20, 5, 50)],
        }
        return palettes.get(theme, palettes["ocean"])

    # ═════════════════════════════════════════════════
    #  SCENE: SUNSET
    # ═════════════════════════════════════════════════

    def _render_sunset(self, w, h, rng, kw):
        img = self._gradient(w, h, [
            (15, 5, 40), (40, 10, 50), (100, 30, 60),
            (200, 80, 50), (250, 160, 40), (255, 210, 80),
            (255, 230, 150), (200, 180, 130)
        ])
        draw = ImageDraw.Draw(img)

        cx, cy = w // 2 + rng.randint(-30, 30), int(h * 0.35) + rng.randint(0, 20)
        for r in range(60, 0, -1):
            a = int(180 * (1 - r / 60))
            rcol = (255, 180 - a // 3, max(30, 80 - a // 2))
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=rcol)

        glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.ellipse([cx - 120, cy - 120, cx + 120, cy + 120],
                     fill=(255, 200, 100, 30))
        glow = glow.filter(ImageFilter.GaussianBlur(radius=25))
        img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")

        horizon_y = int(h * 0.55) + rng.randint(0, 20)
        for i in range(3):
            layer_h = 30 + i * 20
            lo = rng.randint(10, 30) + i * 5
            pts = [(0, horizon_y + i * 15)]
            segs = rng.randint(8, 14)
            for s in range(segs + 1):
                mx = s * w // segs
                my = horizon_y + layer_h - rng.randint(5, 25)
                pts.append((mx, my))
            pts.append((w, h))
            pts.append((0, h))
            draw.polygon(pts, fill=(lo, lo + 3, lo + 8))

        if "water" in kw or "lake" in kw or "sea" in kw or "ocean" in kw or "reflection" in kw:
            water_h = int(h * 0.4)
            water = img.crop((0, horizon_y, w, horizon_y + min(water_h, h - horizon_y)))
            water = water.transpose(Image.FLIP_TOP_BOTTOM)
            water = ImageEnhance.Color(water).enhance(0.7)
            water = ImageEnhance.Brightness(water).enhance(0.6)
            water = water.filter(ImageFilter.GaussianBlur(radius=2))
            img.paste(water, (0, horizon_y))
            for _ in range(20):
                wy = horizon_y + rng.randint(0, water_h)
                walpha = max(0, int(60 * (1 - (wy - horizon_y) / water_h)))
                draw.line([(0, wy), (w, wy)], fill=(255, 200, 100, walpha), width=1)

        img = self._add_sunlight_rays(img, w, h, rng)
        img = self._soft_glow(img, radius=5)
        img = self._add_noise(img, 0.03, rng)
        return img

    # ═════════════════════════════════════════════════
    #  SCENE: MOUNTAINS
    # ═════════════════════════════════════════════════

    def _render_mountains(self, w, h, rng, kw):
        has_sun = any(w in kw for w in ["sun", "sunset", "sunrise", "dusk", "dawn"])
        if has_sun:
            return self._render_sunset(w, h, rng, kw)

        is_forest = "forest" in kw or "tree" in kw or "wood" in kw
        if is_forest:
            sky = self._gradient(w, h, [
                (60, 100, 160), (80, 130, 190), (110, 160, 210), (140, 190, 230)
            ])
        else:
            sky = self._gradient(w, h, [
                (70, 110, 180), (100, 150, 210), (140, 180, 230),
                (180, 210, 245), (210, 230, 250)
            ])
        img = sky.copy()
        draw = ImageDraw.Draw(img)

        cloud_layer = self._cloud_texture(w, h, rng)
        cloud_rgb = Image.merge("RGB", [cloud_layer, cloud_layer, cloud_layer])
        cloud_rgb = ImageEnhance.Brightness(cloud_rgb).enhance(0.3)
        img = Image.blend(img, cloud_rgb, 0.15)

        layers = [
            (int(h * 0.50), 35, 55, 5),
            (int(h * 0.60), 55, 85, 10),
            (int(h * 0.72), 85, 125, 15),
            (int(h * 0.82), 120, 160, 20),
        ]
        for base_y, lo, hi, offset in layers:
            pts = []
            segments = rng.randint(10, 16)
            for i in range(segments + 1):
                mx = i * w // segments
                my = base_y - rng.randint(15 + offset, 60 + offset)
                pts.append((mx, my))
            pts.append((w, h))
            pts.append((0, h))
            draw.polygon(pts, fill=(lo, hi - 10, lo + 15))

            if rng.random() > 0.5:
                snow_pts = []
                snow_y = base_y - rng.randint(20 + offset, 40 + offset)
                for i in range(segments + 1):
                    mx = i * w // segments
                    my = snow_y - rng.randint(5, 15)
                    snow_pts.append((mx, my))
                snow_pts.append((w, snow_y + 30))
                snow_pts.append((0, snow_y + 30))
                snow_c = rng.randint(220, 255)
                draw.polygon(snow_pts, fill=(snow_c, snow_c, snow_c))

        if is_forest:
            for _ in range(rng.randint(20, 40)):
                tx = rng.randint(0, w)
                ty = h - rng.randint(30, 120)
                th = rng.randint(30, 70)
                tw = rng.randint(8, 16)
                tree_col = (rng.randint(15, 40), rng.randint(40, 80), rng.randint(15, 35))
                draw.polygon([(tx, ty), (tx + tw // 2, ty - th), (tx + tw, ty)], fill=tree_col)
        else:
            fg = Image.new("RGB", (w, int(h * 0.15)), (25, 45, 25))
            img.paste(fg, (0, h - int(h * 0.15)))

        img = self._add_noise(img, 0.04, rng)
        img = img.filter(ImageFilter.SMOOTH)
        return img

    def _mountain_pts(self, w, h, base_y, rng, lo, hi):
        pts = []
        segments = rng.randint(6, 12)
        for i in range(segments + 1):
            x = i * w // segments
            y = base_y - rng.randint(20, 80)
            pts.append((x, y))
        pts.append((w, h))
        pts.append((0, h))
        return pts

    # ═════════════════════════════════════════════════
    #  SCENE: OCEAN / BEACH / UNDERWATER
    # ═════════════════════════════════════════════════

    def _render_ocean(self, w, h, rng, kw):
        if "beach" in kw or "coast" in kw:
            sky = self._gradient(w, h, [
                (120, 180, 230), (180, 210, 240), (230, 230, 200),
                (210, 190, 150), (180, 160, 100)
            ])
            img = sky.copy()
            draw = ImageDraw.Draw(img)
            for _ in range(15):
                y = int(h * 0.45) + rng.randint(0, int(h * 0.15))
                wave_color = (rng.randint(30, 60), rng.randint(60, 100), rng.randint(120, 180))
                draw.line([(0, y), (w, y)], fill=wave_color, width=rng.randint(1, 3))
            return img

        if "underwater" in kw or "deep" in kw:
            img = self._gradient(w, h, [
                (5, 20, 50), (10, 40, 80), (15, 60, 110), (10, 50, 90), (5, 30, 60)
            ])
            draw = ImageDraw.Draw(img)
            for _ in range(rng.randint(5, 12)):
                x = rng.randint(0, w)
                y = rng.randint(0, h)
                r = rng.randint(3, 12)
                col = (rng.randint(0, 50), rng.randint(100, 200), rng.randint(100, 200))
                draw.ellipse([x - r, y - r, x + r, y + r], fill=col, outline=None)
            for _ in range(rng.randint(3, 8)):
                x = rng.randint(50, w - 50)
                y = rng.randint(int(h * 0.3), int(h * 0.8))
                draw.polygon([
                    (x, y), (x + 20, y - 30), (x + 40, y),
                    (x + 25, y + 5), (x + 15, y + 5)
                ], fill=(rng.randint(20, 60), rng.randint(80, 140), rng.randint(80, 130)))
            light_rays = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            rd = ImageDraw.Draw(light_rays)
            for _ in range(rng.randint(3, 7)):
                lx = rng.randint(0, w)
                for y in range(0, h, 3):
                    alpha = max(0, int(40 * (1 - y / h) * (0.5 + 0.5 * math.sin(y * 0.02 + lx))))
                    if alpha > 5:
                        rd.line([(lx + rng.randint(-2, 2), y), (lx + rng.randint(-2, 2), y + 10)],
                                fill=(200, 230, 255, alpha))
            img = Image.alpha_composite(img.convert("RGBA"), light_rays).convert("RGB")
            return img

        img = self._gradient(w, h, [
            (30, 80, 150), (40, 100, 180), (50, 120, 200),
            (40, 100, 170), (30, 70, 130)
        ])
        draw = ImageDraw.Draw(img)
        for _ in range(30):
            y = int(h * 0.4) + rng.randint(0, int(h * 0.5))
            amp = rng.randint(3, 8)
            col = (rng.randint(20, 60), rng.randint(80, 150), rng.randint(150, 220))
            pts = []
            for x in range(0, w, 4):
                pts.append((x, y + int(amp * math.sin(x * 0.02 + rng.random() * 6.28))))
            if len(pts) > 1:
                draw.line(pts, fill=col, width=rng.randint(1, 2))
        img = self._soft_glow(img, 5)
        return img

    # ═════════════════════════════════════════════════
    #  SCENE: SPACE
    # ═════════════════════════════════════════════════

    def _render_space(self, w, h, rng, kw):
        img = self._gradient(w, h, [
            (1, 0, 8), (3, 1, 18), (8, 3, 35), (15, 5, 50),
            (8, 3, 40), (3, 1, 25), (1, 0, 12)
        ])

        for _ in range(rng.randint(2, 4)):
            cx, cy = rng.randint(w // 5, 4 * w // 5), rng.randint(h // 5, 4 * h // 5)
            nebula_r = rng.randint(100, 250)
            nebula = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            nd = ImageDraw.Draw(nebula)
            nebula_colors = [
                (rng.randint(150, 255), rng.randint(30, 80), rng.randint(100, 200), 25),
                (rng.randint(30, 80), rng.randint(80, 180), rng.randint(180, 255), 20),
                (rng.randint(200, 255), rng.randint(50, 150), rng.randint(200, 255), 15),
            ]
            nc = rng.choice(nebula_colors)
            for _r in range(nebula_r, 0, -2):
                a = max(0, int(nc[3] * (1 - _r / nebula_r)))
                nd.ellipse([cx - _r, cy - _r, cx + _r, cy + _r],
                           fill=(nc[0], nc[1], nc[2], a))
            nebula = nebula.filter(ImageFilter.GaussianBlur(radius=rng.randint(25, 60)))
            img = Image.alpha_composite(img.convert("RGBA"), nebula).convert("RGB")

        draw = ImageDraw.Draw(img)
        self._draw_stars(draw, w, h, rng, count=400, max_bright=255)

        if "planet" in kw:
            for _ in range(rng.randint(1, 3)):
                px, py = rng.randint(80, w - 80), rng.randint(60, h - 60)
                pr = rng.randint(20, 55)
                hues = [(150, 220, 100), (100, 150, 220), (220, 180, 100), (180, 100, 220)]
                pcol = rng.choice(hues)
                pcol = (pcol[0] + rng.randint(-20, 20), pcol[1] + rng.randint(-20, 20), pcol[2] + rng.randint(-20, 20))
                draw.ellipse([px - pr, py - pr, px + pr, py + pr], fill=pcol)
                ring = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                rd = ImageDraw.Draw(ring)
                for i in range(3):
                    rr = pr + 10 + i * 8
                    ra = max(10, 30 - i * 8)
                    rd.ellipse([px - rr, py - rr // 3, px + rr, py + rr // 3],
                               outline=(pcol[0] + 30, pcol[1] + 30, pcol[2] + 30, ra), width=2)
                ring = ring.filter(ImageFilter.GaussianBlur(radius=2))
                img = Image.alpha_composite(img.convert("RGBA"), ring).convert("RGB")

        if "galaxy" in kw:
            gcx, gcy = w // 2, h // 2
            for a in range(0, 360, 5):
                rad = math.radians(a)
                for d in range(20, 120, 5):
                    spiral = d + a * 0.5
                    sx = gcx + int(d * math.cos(rad + spiral * 0.02))
                    sy = gcy + int(d * 0.3 * math.sin(rad + spiral * 0.02))
                    if 0 <= sx < w and 0 <= sy < h:
                        b = max(0, int(150 * (1 - d / 120)))
                        draw.point((sx, sy), fill=(b, b // 2, b))

        return img

    # ═════════════════════════════════════════════════
    #  SCENE: CITY / CYBERPUNK
    # ═════════════════════════════════════════════════

    def _render_city(self, w, h, rng, kw):
        is_cyberpunk = "cyberpunk" in kw or "neon" in kw
        if is_cyberpunk:
            sky = self._gradient(w, h, [
                (5, 1, 20), (15, 5, 40), (30, 10, 60), (20, 5, 50), (10, 3, 35)
            ])
        else:
            sky = self._gradient(w, h, [
                (20, 25, 60), (40, 50, 100), (60, 80, 140),
                (80, 110, 170), (100, 140, 200)
            ])
        img = sky.copy()
        draw = ImageDraw.Draw(img)

        buildings = []
        bw_list = []
        for _ in range(rng.randint(12, 22)):
            bw = rng.randint(18, 50)
            bw_list.append(bw)
        total = sum(bw_list)
        spacing = (w - total) // (len(bw_list) + 1)
        x = spacing
        for bw in bw_list:
            bh = rng.randint(80, 280)
            by = h - bh
            gray = rng.randint(15, 50) if is_cyberpunk else rng.randint(30, 70)
            draw.rectangle([x, by, x + bw, h], fill=(gray, gray, gray + 10))
            buildings.append((x, by, bw, bh))
            for _ in range(rng.randint(2, 6)):
                wy = by + rng.randint(5, bh - 10)
                wx = x + rng.randint(3, bw - 8)
                if is_cyberpunk:
                    nc = (rng.randint(0, 255), rng.randint(0, 200), rng.randint(150, 255))
                else:
                    nc = (rng.randint(200, 255), rng.randint(200, 255), rng.randint(180, 255))
                draw.rectangle([wx, wy, wx + 4, wy + 4], fill=nc)
            x += bw + spacing

        if is_cyberpunk:
            overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            od = ImageDraw.Draw(overlay)
            for _ in range(rng.randint(3, 8)):
                lx = rng.randint(0, w)
                lc = (rng.randint(0, 255), rng.randint(0, 100), rng.randint(150, 255), 20)
                od.line([(lx, 0), (lx + rng.randint(-10, 10), h)], fill=lc, width=rng.randint(1, 3))
            overlay = overlay.filter(ImageFilter.GaussianBlur(radius=4))
            img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

        return img

    # ═════════════════════════════════════════════════
    #  SCENE: ABSTRACT
    # ═════════════════════════════════════════════════

    def _render_abstract(self, w, h, rng, kw):
        bg_colors = [
            (rng.randint(5, 30), rng.randint(5, 30), rng.randint(20, 50)),
            (rng.randint(30, 60), rng.randint(5, 30), rng.randint(40, 80)),
            (rng.randint(5, 30), rng.randint(30, 60), rng.randint(40, 70)),
        ]
        img = self._gradient(w, h, bg_colors)
        draw = ImageDraw.Draw(img)

        for _ in range(rng.randint(20, 50)):
            x1, y1 = rng.randint(0, w), rng.randint(0, h)
            x2, y2 = rng.randint(0, w), rng.randint(0, h)
            c = (rng.randint(50, 255), rng.randint(50, 255), rng.randint(50, 255))
            width = rng.randint(1, 5)
            draw.line([(x1, y1), (x2, y2)], fill=c, width=width)

        for _ in range(rng.randint(5, 15)):
            cx, cy = rng.randint(0, w), rng.randint(0, h)
            r = rng.randint(10, 80)
            c = (rng.randint(50, 255), rng.randint(50, 255), rng.randint(50, 255))
            draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                         fill=None, outline=c, width=rng.randint(2, 6))

        for _ in range(rng.randint(3, 10)):
            pts = []
            cx2, cy2 = rng.randint(0, w), rng.randint(0, h)
            sides = rng.randint(3, 8)
            rad = rng.randint(20, 80)
            for i in range(sides):
                angle = 2 * math.pi * i / sides - math.pi / 2
                pts.append((cx2 + rad * math.cos(angle), cy2 + rad * math.sin(angle)))
            c = (rng.randint(50, 255), rng.randint(50, 255), rng.randint(50, 255))
            draw.polygon(pts, fill=None, outline=c, width=rng.randint(2, 4))

        img = self._add_noise(img, 0.08, rng)
        return img

    # ═════════════════════════════════════════════════
    #  SCENE: ANIMAL
    # ═════════════════════════════════════════════════

    def _render_animal(self, w, h, rng, kw):
        is_wildlife = any(w in kw for w in ["wildlife", "safari", "lion", "tiger", "bear", "wolf", "fox", "deer", "elephant"])
        if is_wildlife:
            bg = self._gradient(w, h, [
                (rng.randint(30, 80), rng.randint(40, 90), rng.randint(10, 40)),
                (rng.randint(60, 120), rng.randint(80, 140), rng.randint(30, 70)),
                (rng.randint(40, 80), rng.randint(60, 110), rng.randint(20, 50)),
            ])
        else:
            bg = self._gradient(w, h, [
                (rng.randint(100, 200), rng.randint(100, 180), rng.randint(80, 150)),
                (rng.randint(50, 120), rng.randint(40, 100), rng.randint(30, 80)),
            ])
        img = bg.copy()
        draw = ImageDraw.Draw(img)

        cx, cy = w // 2, h // 2 + 20
        face_r = 60 + rng.randint(0, 30)

        fur_color = (rng.randint(120, 220), rng.randint(80, 180), rng.randint(40, 140))
        ear_color = (rng.randint(150, 220), rng.randint(120, 180), rng.randint(60, 130))
        eye_color = (rng.randint(20, 40), rng.randint(20, 40), rng.randint(20, 40))

        draw.ellipse([cx - face_r, cy - face_r + 10, cx + face_r, cy + face_r + 10],
                     fill=fur_color)

        draw.ellipse([cx - face_r - 20, cy - face_r - 10, cx - face_r // 3, cy - face_r // 2],
                     fill=ear_color)
        draw.ellipse([cx + face_r // 3, cy - face_r - 10, cx + face_r + 20, cy - face_r // 2],
                     fill=ear_color)

        eye_spacing = face_r // 3
        eye_y = cy - 5
        draw.ellipse([cx - eye_spacing - 12, eye_y - 10, cx - eye_spacing + 2, eye_y + 10],
                     fill=eye_color)
        draw.ellipse([cx + eye_spacing - 2, eye_y - 10, cx + eye_spacing + 12, eye_y + 10],
                     fill=eye_color)

        draw.ellipse([cx - eye_spacing - 6, eye_y - 4, cx - eye_spacing - 2, eye_y],
                     fill=(255, 255, 255, 200))
        draw.ellipse([cx + eye_spacing + 2, eye_y - 4, cx + eye_spacing + 6, eye_y],
                     fill=(255, 255, 255, 200))

        nose_y = cy + 15
        draw.ellipse([cx - 8, nose_y - 4, cx + 8, nose_y + 6],
                     fill=(30, 30, 30))
        draw.ellipse([cx - 15, nose_y + 2, cx - 5, nose_y + 10],
                     fill=(200, 100, 100))
        draw.ellipse([cx + 5, nose_y + 2, cx + 15, nose_y + 10],
                     fill=(200, 100, 100))

        return img

    # ═════════════════════════════════════════════════
    #  SCENE: FLORAL
    # ═════════════════════════════════════════════════

    def _render_floral(self, w, h, rng, kw):
        sky = self._gradient(w, h, [
            (60, 140, 60), (80, 160, 80), (100, 180, 100),
            (80, 160, 80), (60, 140, 60)
        ])
        img = sky.copy()
        draw = ImageDraw.Draw(img)

        for _ in range(rng.randint(8, 16)):
            fx = rng.randint(40, w - 40)
            fy = rng.randint(40, h - 40)
            fr = rng.randint(12, 35)
            fc = (rng.randint(150, 255), rng.randint(30, 180), rng.randint(30, 200))
            for a in range(0, 360, 30):
                rad = math.radians(a)
                px = fx + int(math.cos(rad) * fr)
                py = fy + int(math.sin(rad) * fr)
                pr = fr // 3 + rng.randint(1, 5)
                draw.ellipse([px - pr, py - pr, px + pr, py + pr], fill=fc)
            draw.ellipse([fx - 6, fy - 6, fx + 6, fy + 6], fill=(255, 220, 50))

        for _ in range(rng.randint(20, 40)):
            sx = rng.randint(0, w)
            sy = rng.randint(int(h * 0.6), h)
            sw = rng.randint(1, 2)
            draw.line([(sx, sy), (sx, sy + rng.randint(20, 60))],
                      fill=(rng.randint(20, 60), rng.randint(80, 140), rng.randint(20, 60)),
                      width=sw)

        return img

    # ═════════════════════════════════════════════════
    #  SCENE: PORTRAIT
    # ═════════════════════════════════════════════════

    def _render_portrait(self, w, h, rng, kw):
        bg = self._gradient(w, h, [
            (rng.randint(30, 80), rng.randint(30, 70), rng.randint(60, 120)),
            (rng.randint(60, 120), rng.randint(50, 100), rng.randint(90, 160)),
        ])
        img = bg.copy()
        draw = ImageDraw.Draw(img)

        cx, cy = w // 2, h // 2
        skin = (rng.randint(180, 240), rng.randint(140, 200), rng.randint(100, 170))
        head_r = 60 + rng.randint(0, 20)
        draw.ellipse([cx - head_r, cy - head_r - 10, cx + head_r, cy + head_r + 10], fill=skin)

        hair_col = (rng.randint(20, 50), rng.randint(15, 40), rng.randint(10, 30))
        draw.ellipse([cx - head_r - 5, cy - head_r - 30, cx + head_r + 5, cy - head_r // 3],
                     fill=hair_col)

        eye_y = cy - 5
        es = head_r // 3
        draw.ellipse([cx - es - 10, eye_y - 8, cx - es + 2, eye_y + 8], fill=(40, 35, 30))
        draw.ellipse([cx + es - 2, eye_y - 8, cx + es + 10, eye_y + 8], fill=(40, 35, 30))
        draw.ellipse([cx - es - 6, eye_y - 3, cx - es - 3, eye_y], fill=(255, 255, 255))
        draw.ellipse([cx + es + 3, eye_y - 3, cx + es + 6, eye_y], fill=(255, 255, 255))

        draw.arc([cx - 20, cy + 10, cx + 20, cy + 35], start=0, end=180,
                 fill=(rng.randint(80, 120), rng.randint(30, 60), rng.randint(30, 60)), width=3)

        neck = (cx - 15, cy + head_r + 5, cx + 15, cy + head_r + 40)
        draw.rectangle(neck, fill=skin)

        return img

    # ═════════════════════════════════════════════════
    #  SCENE: FANTASY
    # ═════════════════════════════════════════════════

    def _render_fantasy(self, w, h, rng, kw):
        img = self._gradient(w, h, [
            (15, 5, 40), (30, 10, 60), (50, 20, 80), (30, 15, 60), (20, 10, 50)
        ])
        draw = ImageDraw.Draw(img)
        self._draw_stars(draw, w, h, rng, count=100, max_bright=200)

        if "castle" in kw:
            cx = w // 2
            cy = h // 2 + 40
            for i in range(-2, 3):
                tw = 30 + 10 * abs(i)
                th = 80 + rng.randint(20, 60)
                tx = cx + i * 50 - tw // 2
                ty = cy - th
                draw.rectangle([tx, ty, tx + tw, cy],
                               fill=(rng.randint(40, 70), rng.randint(35, 60), rng.randint(50, 80)))
                draw.polygon([(tx - 5, ty), (tx + tw // 2, ty - 25), (tx + tw + 5, ty)],
                             fill=(rng.randint(60, 90), rng.randint(50, 80), rng.randint(70, 100)))

        glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gx, gy = w // 2, h // 3
        for r in range(60, 0, -2):
            a = max(0, int(30 * (1 - r / 60)))
            gd.ellipse([gx - r, gy - r, gx + r, gy + r],
                       fill=(rng.randint(150, 255), rng.randint(100, 200), rng.randint(200, 255), a))
        glow = glow.filter(ImageFilter.GaussianBlur(radius=15))
        img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")

        return img

    # ═════════════════════════════════════════════════
    #  SCENE: FOOD
    # ═════════════════════════════════════════════════

    def _render_food(self, w, h, rng, kw):
        img = self._gradient(w, h, [
            (rng.randint(200, 240), rng.randint(180, 220), rng.randint(160, 200)),
            (rng.randint(220, 250), rng.randint(200, 240), rng.randint(180, 220)),
        ])
        draw = ImageDraw.Draw(img)

        cx, cy = w // 2, h // 2
        plate_r = 100 + rng.randint(0, 30)
        draw.ellipse([cx - plate_r, cy - plate_r, cx + plate_r, cy + plate_r],
                     fill=(rng.randint(200, 240), rng.randint(200, 240), rng.randint(200, 240)),
                     outline=(rng.randint(160, 200), rng.randint(160, 200), rng.randint(160, 200)),
                     width=4)
        draw.ellipse([cx - plate_r + 8, cy - plate_r + 8, cx + plate_r - 8, cy + plate_r - 8],
                     fill=(rng.randint(215, 245), rng.randint(215, 245), rng.randint(215, 245)))

        if any(w in kw for w in ["fruit", "salad", "vegetable"]):
            for _ in range(rng.randint(5, 10)):
                fx = cx + rng.randint(-60, 60)
                fy = cy + rng.randint(-60, 60)
                fr = rng.randint(10, 25)
                fc = (rng.randint(50, 255), rng.randint(50, 200), rng.randint(50, 150))
                draw.ellipse([fx - fr, fy - fr, fx + fr, fy + fr], fill=fc)
        elif "cake" in kw or "dessert" in kw:
            draw.rectangle([cx - 50, cy - 30, cx + 50, cy + 30],
                           fill=(rng.randint(180, 220), rng.randint(120, 160), rng.randint(60, 100)))
            draw.rectangle([cx - 45, cy - 35, cx + 45, cy - 30],
                           fill=(rng.randint(230, 255), rng.randint(230, 255), rng.randint(230, 255)))
        else:
            main_c = (rng.randint(150, 200), rng.randint(80, 140), rng.randint(30, 80))
            draw.ellipse([cx - 50, cy - 30, cx + 50, cy + 30], fill=main_c)

        return img

    # ═════════════════════════════════════════════════
    #  SCENE: WINTER
    # ═════════════════════════════════════════════════

    def _render_winter(self, w, h, rng, kw):
        img = self._gradient(w, h, [
            (180, 200, 230), (200, 215, 240), (220, 230, 245),
            (230, 235, 245), (240, 240, 250)
        ])
        draw = ImageDraw.Draw(img)

        ground = Image.new("RGB", (w, int(h * 0.3)), (235, 240, 250))
        img.paste(ground, (0, h - int(h * 0.3)))

        for _ in range(rng.randint(5, 12)):
            x = rng.randint(-10, w + 10)
            y = h - int(h * 0.3) - rng.randint(0, 20)
            r = rng.randint(10, 30)
            draw.ellipse([x - r, y - r // 2, x + r, y + r // 2],
                         fill=(rng.randint(230, 250), rng.randint(235, 250), rng.randint(245, 255)))

        self._draw_stars(draw, w, h - int(h * 0.3), rng, count=60, max_bright=200)

        for _ in range(rng.randint(40, 80)):
            sx = rng.randint(0, w)
            sy = rng.randint(0, h)
            sr = rng.randint(1, 3)
            draw.ellipse([sx - sr, sy - sr, sx + sr, sy + sr],
                         fill=(rng.randint(220, 255), rng.randint(230, 255), rng.randint(240, 255)))

        img = self._soft_glow(img, 4)
        return img

    # ═════════════════════════════════════════════════
    #  SCENE: FIRE / LAVA
    # ═════════════════════════════════════════════════

    def _render_fire(self, w, h, rng, kw):
        img = self._gradient(w, h, [
            (5, 5, 10), (20, 5, 5), (60, 10, 5), (40, 5, 10), (20, 5, 5)
        ])
        draw = ImageDraw.Draw(img)

        for _ in range(rng.randint(20, 40)):
            fx = rng.randint(0, w)
            fy = rng.randint(0, h)
            fh = rng.randint(30, 150)
            cols = [(rng.randint(200, 255), rng.randint(100, 200), rng.randint(0, 50)),
                    (rng.randint(255, 255), rng.randint(150, 220), rng.randint(0, 80)),
                    (rng.randint(200, 255), rng.randint(200, 255), rng.randint(50, 100))]
            draw.polygon([
                (fx - fh // 4, fy + fh // 2),
                (fx + rng.randint(-10, 10), fy - fh // 2),
                (fx + fh // 4, fy + fh // 2)
            ], fill=cols[rng.randint(0, len(cols) - 1)])

        glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        for _ in range(3):
            gx, gy = rng.randint(0, w), rng.randint(int(h * 0.5), h)
            for r in range(80, 0, -5):
                a = max(0, int(20 * (1 - r / 80)))
                gd.ellipse([gx - r, gy - r, gx + r, gy + r],
                           fill=(rng.randint(200, 255), rng.randint(50, 150), 0, a))
        glow = glow.filter(ImageFilter.GaussianBlur(radius=20))
        img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")

        return img

    # ═════════════════════════════════════════════════
    #  SCENE: STORM / RAIN / CLOUDS
    # ═════════════════════════════════════════════════

    def _render_storm(self, w, h, rng, kw):
        img = self._gradient(w, h, [
            (30, 35, 45), (50, 55, 70), (70, 75, 90),
            (60, 65, 80), (40, 45, 55)
        ])
        draw = ImageDraw.Draw(img)

        for _ in range(rng.randint(5, 10)):
            cx = rng.randint(0, w)
            cy = rng.randint(0, h // 2)
            cr = rng.randint(40, 120)
            shade = rng.randint(40, 80)
            draw.ellipse([cx - cr, cy - cr // 2, cx + cr, cy + cr // 2],
                         fill=(shade, shade + 5, shade + 15))

        if "lightning" in kw or "thunder" in kw:
            lx = rng.randint(100, w - 100)
            ly = rng.randint(0, h // 3)
            lcol = (rng.randint(200, 255), rng.randint(200, 255), rng.randint(200, 255))
            pts = [(lx, ly)]
            for _ in range(rng.randint(5, 10)):
                lx += rng.randint(-30, 30)
                ly += rng.randint(20, 50)
                pts.append((lx, ly))
            draw.line(pts, fill=lcol, width=rng.randint(2, 4))
            glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            gd = ImageDraw.Draw(glow)
            gd.line(pts, fill=(200, 200, 255, 60), width=12)
            glow = glow.filter(ImageFilter.GaussianBlur(radius=8))
            img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")

        if "rain" in kw or "rainy" in kw or "storm" in kw:
            for _ in range(rng.randint(80, 150)):
                rx = rng.randint(0, w)
                ry = rng.randint(0, h)
                draw.line([(rx, ry), (rx - 3, ry + 10)],
                          fill=(rng.randint(150, 200), rng.randint(180, 220), rng.randint(220, 255), 80),
                          width=1)

        return img

    # ═════════════════════════════════════════════════
    #  SCENE: DESERT
    # ═════════════════════════════════════════════════

    def _render_desert(self, w, h, rng, kw):
        img = self._gradient(w, h, [
            (100, 160, 200), (180, 200, 210), (210, 190, 150),
            (180, 160, 100), (160, 130, 70)
        ])
        draw = ImageDraw.Draw(img)

        for _ in range(rng.randint(3, 7)):
            dx = rng.randint(-50, w + 50)
            dy = h * 0.5 + rng.randint(0, int(h * 0.3))
            dw = rng.randint(100, 250)
            dh = rng.randint(20, 50)
            shade = rng.randint(130, 180)
            draw.ellipse([dx - dw // 2, dy - dh // 2, dx + dw // 2, dy + dh // 2],
                         fill=(shade, shade - 20, shade - 40))

        if "cactus" in kw:
            for _ in range(rng.randint(3, 6)):
                cex = rng.randint(20, w - 20)
                cey = h - rng.randint(40, 100)
                draw.rectangle([cex - 4, cey - 40, cex + 4, cey],
                               fill=(rng.randint(30, 60), rng.randint(80, 120), rng.randint(20, 50)))
                draw.rectangle([cex + 4, cey - 30, cex + 18, cey - 22],
                               fill=(rng.randint(30, 60), rng.randint(80, 120), rng.randint(20, 50)))
                draw.rectangle([cex - 18, cey - 28, cex - 4, cey - 20],
                               fill=(rng.randint(30, 60), rng.randint(80, 120), rng.randint(20, 50)))

        img = ImageEnhance.Color(img).enhance(0.8)
        return img

    # ═════════════════════════════════════════════════
    #  SCENE: AURORA
    # ═════════════════════════════════════════════════

    def _render_aurora(self, w, h, rng, kw):
        img = self._gradient(w, h, [
            (5, 10, 30), (10, 15, 40), (5, 10, 35), (3, 5, 25), (2, 3, 15)
        ])
        draw = ImageDraw.Draw(img)
        self._draw_stars(draw, w, h, rng, count=250, max_bright=255)

        aurora = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ad = ImageDraw.Draw(aurora)
        for _ in range(rng.randint(2, 4)):
            ax = rng.randint(0, w)
            aw = rng.randint(150, 400)
            for y in range(0, h // 2, 5):
                t = y / max(h // 2, 1)
                alpha = max(0, int(60 * (1 - t) * (0.3 + 0.7 * math.sin(y * 0.01 + rng.random() * 3))))
                if alpha > 5:
                    x_offset = int(20 * math.sin(y * 0.008 + ax * 0.01))
                    for x in range(ax - aw // 2 + x_offset, ax + aw // 2 + x_offset, 3):
                        dist = abs(x - ax) / (aw // 2)
                        a2 = max(0, int(alpha * (1 - dist)))
                        c = (rng.randint(0, 100), rng.randint(150, 255), rng.randint(100, 255), a2)
                        ad.point((x, y), fill=c)
        aurora = aurora.filter(ImageFilter.GaussianBlur(radius=8))
        img = Image.alpha_composite(img.convert("RGBA"), aurora).convert("RGB")

        return img

    # ═════════════════════════════════════════════════
    #  SCENE: WATERFALL / RIVER
    # ═════════════════════════════════════════════════

    def _render_waterfall(self, w, h, rng, kw):
        img = self._gradient(w, h, [
            (50, 80, 60), (60, 100, 80), (70, 120, 100),
            (50, 100, 90), (40, 80, 70)
        ])
        draw = ImageDraw.Draw(img)

        cliff_x = rng.randint(w // 3, 2 * w // 3)
        cliff_h = rng.randint(h // 4, h // 3)
        draw.rectangle([0, 0, cliff_x, h], fill=(rng.randint(40, 70), rng.randint(60, 90), rng.randint(30, 60)))
        draw.rectangle([cliff_x, 0, w, h], fill=(rng.randint(60, 90), rng.randint(80, 110), rng.randint(40, 70)))

        wf_x = cliff_x + rng.randint(-10, 10)
        for y in range(cliff_h, h, 3):
            alpha = max(0, int(200 * (1 - y / h)))
            sway = int(5 * math.sin(y * 0.05))
            draw.line([(wf_x + sway, y), (wf_x + sway + rng.randint(8, 20), y)],
                      fill=(rng.randint(180, 230), rng.randint(210, 245), rng.randint(230, 255), alpha),
                      width=rng.randint(1, 3))

        splash = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sd = ImageDraw.Draw(splash)
        for _ in range(rng.randint(20, 40)):
            sx = cliff_x + rng.randint(-20, 20)
            sy = cliff_h + rng.randint(0, 20)
            sr = rng.randint(1, 6)
            sd.ellipse([sx - sr, sy - sr, sx + sr, sy + sr],
                       fill=(200, 230, 255, rng.randint(30, 80)))
        splash = splash.filter(ImageFilter.GaussianBlur(radius=3))
        img = Image.alpha_composite(img.convert("RGBA"), splash).convert("RGB")

        return img

    # ═════════════════════════════════════════════════
    #  SCENE: CRYSTAL / GEM
    # ═════════════════════════════════════════════════

    def _render_crystal(self, w, h, rng, kw):
        img = self._gradient(w, h, [
            (rng.randint(5, 15), rng.randint(5, 15), rng.randint(20, 40)),
            (rng.randint(15, 30), rng.randint(10, 25), rng.randint(40, 70)),
            (rng.randint(10, 20), rng.randint(10, 20), rng.randint(30, 60)),
        ])
        draw = ImageDraw.Draw(img)

        cx, cy = w // 2, h // 2
        crystal_col = (rng.randint(100, 255), rng.randint(50, 200), rng.randint(150, 255))
        pts = [
            (cx, cy - 80),
            (cx - 40, cy + 10),
            (cx - 25, cy + 60),
            (cx + 25, cy + 60),
            (cx + 40, cy + 10),
        ]
        draw.polygon(pts, fill=None, outline=crystal_col, width=3)

        inner_pts = [
            (cx, cy - 60),
            (cx - 25, cy + 5),
            (cx, cy + 40),
            (cx + 25, cy + 5),
        ]
        draw.polygon(inner_pts, fill=(crystal_col[0], crystal_col[1], crystal_col[2], 60))

        glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.ellipse([cx - 80, cy - 80, cx + 80, cy + 80],
                   fill=(crystal_col[0], crystal_col[1], crystal_col[2], 20))
        glow = glow.filter(ImageFilter.GaussianBlur(radius=15))
        img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")

        for _ in range(rng.randint(5, 12)):
            sx = rng.randint(0, w)
            sy = rng.randint(0, h)
            draw.point((sx, sy), fill=(rng.randint(180, 255), rng.randint(180, 255), rng.randint(200, 255)))

        return img

    # ═════════════════════════════════════════════════
    #  SCENE: CYBERPUNK
    # ═════════════════════════════════════════════════

    def _render_cyberpunk(self, w, h, rng, kw):
        img = self._gradient(w, h, [
            (5, 1, 20), (15, 5, 40), (30, 10, 60), (20, 5, 50), (10, 3, 35)
        ])
        draw = ImageDraw.Draw(img)

        buildings = []
        bw_list = [rng.randint(18, 50) for _ in range(rng.randint(14, 24))]
        total = sum(bw_list)
        spacing = (w - total) // (len(bw_list) + 1)
        x = spacing
        for bw in bw_list:
            bh = rng.randint(80, 300)
            by = h - bh
            gray = rng.randint(10, 35)
            draw.rectangle([x, by, x + bw, h], fill=(gray, gray, gray + 5))
            for _ in range(rng.randint(3, 8)):
                wy = by + rng.randint(5, bh - 10)
                wx = x + rng.randint(3, bw - 8)
                neon_colors = [
                    (rng.randint(0, 255), rng.randint(0, 100), rng.randint(150, 255)),
                    (rng.randint(0, 150), rng.randint(200, 255), rng.randint(200, 255)),
                    (rng.randint(200, 255), rng.randint(0, 100), rng.randint(150, 255)),
                ]
                draw.rectangle([wx, wy, wx + 3, wy + 6], fill=rng.choice(neon_colors))
            x += bw + spacing

        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        for _ in range(rng.randint(5, 12)):
            lx = rng.randint(0, w)
            lc = (rng.randint(0, 255), rng.randint(0, 100), rng.randint(150, 255), 15)
            od.line([(lx, 0), (lx + rng.randint(-15, 15), h)], fill=lc, width=1)
        overlay = overlay.filter(ImageFilter.GaussianBlur(radius=5))
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

        overlay2 = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        od2 = ImageDraw.Draw(overlay2)
        for _ in range(rng.randint(3, 6)):
            gx, gy = rng.randint(0, w), rng.randint(0, h)
            gc = (rng.randint(150, 255), rng.randint(0, 150), rng.randint(200, 255), 40)
            od2.ellipse([gx - 30, gy - 30, gx + 30, gy + 30], fill=gc)
        overlay2 = overlay2.filter(ImageFilter.GaussianBlur(radius=20))
        img = Image.alpha_composite(img.convert("RGBA"), overlay2).convert("RGB")

        scanlines = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sd = ImageDraw.Draw(scanlines)
        for y in range(0, h, 3):
            sd.line([(0, y), (w, y)], fill=(0, 0, 0, 15))
        img = Image.alpha_composite(img.convert("RGBA"), scanlines).convert("RGB")
        return img

    # ═════════════════════════════════════════════════
    #  SCENE: AUTUMN
    # ═════════════════════════════════════════════════

    def _render_autumn(self, w, h, rng, kw):
        img = self._gradient(w, h, [
            (40, 20, 10), (80, 40, 15), (140, 70, 20), (180, 100, 30), (200, 130, 50)
        ])
        draw = ImageDraw.Draw(img)

        for _ in range(rng.randint(15, 25)):
            tx = rng.randint(0, w)
            ty = rng.randint(0, h)
            tr = rng.randint(20, 60)
            leaf_color = (
                rng.randint(150, 220),
                rng.randint(40, 120),
                rng.randint(10, 60)
            )
            draw.ellipse([tx - tr, ty - tr // 2, tx + tr, ty + tr // 2], fill=leaf_color)

        for _ in range(rng.randint(3, 6)):
            bx = rng.randint(w // 4, 3 * w // 4)
            bh = rng.randint(60, 150)
            bark = (rng.randint(30, 50), rng.randint(20, 40), rng.randint(10, 25))
            draw.rectangle([bx - 4, h - bh, bx + 4, h], fill=bark)

        for _ in range(rng.randint(30, 60)):
            fx, fy = rng.randint(0, w), rng.randint(0, h)
            fr = rng.randint(1, 3)
            fc = (rng.randint(180, 230), rng.randint(60, 120), rng.randint(10, 40))
            draw.ellipse([fx - fr, fy - fr, fx + fr, fy + fr], fill=fc)

        img = self._soft_glow(img, 5)
        img = self._add_noise(img, 0.04, rng)
        return img

    # ═════════════════════════════════════════════════
    #  SCENE: JAPANESE / ORIENTAL
    # ═════════════════════════════════════════════════

    def _render_japanese(self, w, h, rng, kw):
        img = self._gradient(w, h, [
            (200, 180, 220), (210, 190, 230), (220, 200, 240), (200, 180, 220)
        ])
        draw = ImageDraw.Draw(img)

        for _ in range(rng.randint(8, 16)):
            bx = rng.randint(0, w)
            by = rng.randint(0, h // 2)
            br = rng.randint(8, 20)
            cherry = (
                rng.randint(220, 255),
                rng.randint(140, 200),
                rng.randint(180, 230)
            )
            draw.ellipse([bx - br, by - br, bx + br, by + br], fill=cherry)

        for _ in range(rng.randint(30, 60)):
            px, py = rng.randint(0, w), rng.randint(0, h)
            pr = rng.randint(1, 2)
            draw.ellipse([px - pr, py - pr, px + pr, py + pr],
                         fill=(rng.randint(230, 255), rng.randint(150, 220), rng.randint(190, 240)))

        mountain_base = h // 2 + rng.randint(30, 80)
        for i in range(3):
            mt_color = (
                rng.randint(40, 80) + i * 20,
                rng.randint(50, 90) + i * 20,
                rng.randint(60, 100) + i * 20
            )
            mt_h = 100 + i * 40
            pts = [(0, mountain_base + i * 20)]
            segs = 8
            for s in range(segs + 1):
                mx = s * w // segs
                my = mountain_base - mt_h + rng.randint(-20, 20)
                pts.append((mx, my))
            pts.append((w, h))
            pts.append((0, h))
            draw.polygon(pts, fill=mt_color)

        if "pagoda" in kw or "temple" in kw:
            for t in range(rng.randint(3, 5)):
                tx = rng.randint(100, w - 100)
                ty = h // 2 - rng.randint(20, 60)
                roof_color = (rng.randint(120, 160), rng.randint(30, 50), rng.randint(30, 50))
                draw.polygon([(tx - 40, ty), (tx, ty - 40), (tx + 40, ty)], fill=roof_color)
                draw.rectangle([tx - 8, ty, tx + 8, ty + 40], fill=(rng.randint(140, 180), rng.randint(120, 160), rng.randint(80, 110)))

        img = self._add_noise(img, 0.03, rng)
        return img

    # ═════════════════════════════════════════════════
    #  SCENE: STEAMPUNK
    # ═════════════════════════════════════════════════

    def _render_steampunk(self, w, h, rng, kw):
        img = self._gradient(w, h, [
            (40, 30, 20), (60, 45, 30), (80, 60, 40), (60, 45, 30), (40, 30, 20)
        ])
        draw = ImageDraw.Draw(img)

        for _ in range(rng.randint(3, 6)):
            gx, gy = rng.randint(50, w - 50), rng.randint(50, h - 50)
            gr = rng.randint(20, 50)
            gold = (rng.randint(160, 200), rng.randint(120, 160), rng.randint(40, 80))
            draw.ellipse([gx - gr, gy - gr, gx + gr, gy + gr], outline=gold, width=3)
            for _ in range(8):
                a = rng.randint(0, 360)
                rad = math.radians(a)
                sx = gx + int(math.cos(rad) * gr)
                sy = gy + int(math.sin(rad) * gr)
                draw.line([(gx, gy), (sx, sy)], fill=gold, width=1)

        for _ in range(rng.randint(8, 14)):
            px, py = rng.randint(0, w), rng.randint(0, h)
            pl = rng.randint(20, 80)
            pa = rng.uniform(0, math.pi * 2)
            pipe_color = (rng.randint(50, 80), rng.randint(40, 65), rng.randint(25, 45))
            draw.line([
                (px, py),
                (px + int(pl * math.cos(pa)), py + int(pl * math.sin(pa)))
            ], fill=pipe_color, width=rng.randint(2, 5))

        clouds = Image.new("L", (w, h), 0)
        cd = ImageDraw.Draw(clouds)
        for _ in range(rng.randint(3, 6)):
            cx, cy = rng.randint(0, w), rng.randint(0, h // 3)
            cr = rng.randint(30, 80)
            cd.ellipse([cx - cr, cy - cr // 2, cx + cr, cy + cr // 2], fill=100)
        clouds = clouds.filter(ImageFilter.GaussianBlur(radius=15))
        cloud_rgb = Image.merge("RGB", [clouds, clouds, clouds])
        img = Image.blend(img, cloud_rgb, 0.3)

        img = self._add_noise(img, 0.06, rng)
        return img

    # ═════════════════════════════════════════════════
    #  SCENE: PATTERN / WALLPAPER
    # ═════════════════════════════════════════════════

    def _render_pattern(self, w, h, rng, kw):
        bg_color = (rng.randint(10, 40), rng.randint(10, 40), rng.randint(20, 50))
        img = Image.new("RGB", (w, h), bg_color)
        draw = ImageDraw.Draw(img)

        colors = [
            (rng.randint(150, 255), rng.randint(100, 200), rng.randint(100, 200)),
            (rng.randint(100, 200), rng.randint(150, 255), rng.randint(100, 200)),
            (rng.randint(100, 200), rng.randint(100, 200), rng.randint(150, 255)),
            (rng.randint(200, 255), rng.randint(200, 255), rng.randint(100, 200)),
        ]

        pattern_size = rng.choice([20, 30, 40, 50])
        for px in range(0, w, pattern_size):
            for py in range(0, h, pattern_size):
                c = rng.choice(colors)
                if rng.random() > 0.5:
                    draw.ellipse([px + 2, py + 2, px + pattern_size - 2, py + pattern_size - 2],
                                 fill=None, outline=c, width=2)
                else:
                    cx = px + pattern_size // 2
                    cy = py + pattern_size // 2
                    for i in range(4):
                        a = math.radians(i * 90 + 45)
                        r = pattern_size // 3
                        draw.line([
                            (cx, cy),
                            (cx + int(r * math.cos(a)), cy + int(r * math.sin(a)))
                        ], fill=c, width=1)

        return img

    # ═════════════════════════════════════════════════
    #  SCENE: GENERIC (FALLBACK)
    # ═════════════════════════════════════════════════

    def _render_generic(self, w, h, rng, kw):
        img = self._gradient(w, h, [
            (rng.randint(20, 60), rng.randint(20, 60), rng.randint(50, 100)),
            (rng.randint(40, 80), rng.randint(40, 80), rng.randint(70, 130)),
            (rng.randint(60, 100), rng.randint(50, 90), rng.randint(90, 150)),
        ])
        draw = ImageDraw.Draw(img)

        for _ in range(rng.randint(3, 8)):
            x1, y1 = rng.randint(0, w), rng.randint(0, h)
            x2, y2 = rng.randint(0, w), rng.randint(0, h)
            c = (rng.randint(50, 255), rng.randint(50, 255), rng.randint(50, 255))
            draw.line([(x1, y1), (x2, y2)], fill=c, width=rng.randint(1, 3))

        for _ in range(rng.randint(5, 12)):
            cx, cy = rng.randint(0, w), rng.randint(0, h)
            r = rng.randint(5, 40)
            c = (rng.randint(100, 255), rng.randint(100, 255), rng.randint(100, 255))
            draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                         fill=None, outline=c, width=rng.randint(1, 3))

        img = self._add_noise(img, 0.05, rng)
        img = self._soft_glow(img, 5)
        return img

    # ═════════════════════════════════════════════════
    #  REDESIGN EFFECTS
    # ═════════════════════════════════════════════════

    def _apply_artistic_effect(self, image, prompt):
        kw = prompt.lower()
        img = image.copy()

        if "vintage" in kw or "retro" in kw or "old" in kw:
            img = ImageOps.posterize(img, 4)
            img = ImageEnhance.Color(img).enhance(0.5)
            img = ImageEnhance.Contrast(img).enhance(0.85)
            r, g, b = img.split()
            r_arr = np.array(r, dtype=np.float32)
            g_arr = np.array(g, dtype=np.float32)
            b_arr = np.array(b, dtype=np.float32)
            nr = np.clip(r_arr * 0.393 + g_arr * 0.769 + b_arr * 0.189, 0, 255).astype(np.uint8)
            ng = np.clip(r_arr * 0.349 + g_arr * 0.686 + b_arr * 0.168, 0, 255).astype(np.uint8)
            nb = np.clip(r_arr * 0.272 + g_arr * 0.534 + b_arr * 0.131, 0, 255).astype(np.uint8)
            img = Image.merge("RGB", [
                Image.fromarray(nr), Image.fromarray(ng), Image.fromarray(nb)
            ])
            vignette = Image.new("RGBA", img.size, (0, 0, 0, 0))
            vd = ImageDraw.Draw(vignette)
            w, h = img.size
            for i in range(200, 0, -1):
                a = max(0, min(80, int(80 * (1 - i / 200))))
                vd.ellipse([-i, -i, w + i, h + i], fill=(0, 0, 0, a))
            vignette = vignette.filter(ImageFilter.GaussianBlur(radius=30))
            img = Image.alpha_composite(img.convert("RGBA"), vignette).convert("RGB")

        elif "oil" in kw or "painting" in kw or "impressionist" in kw:
            img = img.filter(ImageFilter.SMOOTH_MORE)
            img = img.filter(ImageFilter.SMOOTH_MORE)
            img = ImageEnhance.Contrast(img).enhance(1.2)
            img = ImageEnhance.Color(img).enhance(1.3)
            img = ImageEnhance.Sharpness(img).enhance(0.6)
            for _ in range(2):
                img = img.filter(ImageFilter.MedianFilter(size=3))

        elif "sketch" in kw or "drawing" in kw or "pencil" in kw:
            gray = img.convert("L")
            inv = ImageOps.invert(gray)
            blur = inv.filter(ImageFilter.GaussianBlur(radius=4))
            img = ImageOps.colorize(blur, black="white", white="black").convert("RGB")
            img = ImageEnhance.Contrast(img).enhance(1.5)

        elif "watercolor" in kw or "aquarelle" in kw:
            for _ in range(3):
                img = img.filter(ImageFilter.SMOOTH)
            img = ImageEnhance.Color(img).enhance(0.8)
            texture = Image.new("RGB", img.size, (240, 240, 240))
            img = Image.blend(img, texture, 0.15)
            img = img.filter(ImageFilter.GaussianBlur(radius=1))

        elif "neon" in kw or "cyber" in kw or "glow" in kw:
            img = ImageEnhance.Color(img).enhance(2.0)
            img = ImageEnhance.Contrast(img).enhance(1.4)
            img = img.filter(ImageFilter.MaxFilter(3))
            overlay = img.copy()
            overlay = overlay.filter(ImageFilter.GaussianBlur(radius=6))
            img = ImageChops.screen(img, overlay)

        elif "blur" in kw or "soft" in kw or "dreamy" in kw or "bokeh" in kw:
            img = img.filter(ImageFilter.GaussianBlur(radius=4))
            overlay = img.copy()
            draw = ImageDraw.Draw(overlay)
            w, h = img.size
            for _ in range(30):
                bx, by = random.randint(0, w), random.randint(0, h)
                br = random.randint(5, 15)
                bc = (random.randint(200, 255), random.randint(200, 255), random.randint(200, 255))
                draw.ellipse([bx - br, by - br, bx + br, by + br],
                             fill=bc + (40,))
            overlay = overlay.filter(ImageFilter.GaussianBlur(radius=5))
            img = Image.alpha_composite(img.convert("RGBA"), overlay.convert("RGBA")).convert("RGB")

        elif "pixel" in kw or "8bit" in kw or "retro game" in kw:
            w, h = img.size
            s = 16
            img = img.resize((w // s, h // s), Image.NEAREST)
            img = img.resize((w, h), Image.NEAREST)

        elif "cartoon" in kw or "anime" in kw or "comic" in kw:
            img = img.filter(ImageFilter.SMOOTH)
            img = ImageEnhance.Color(img).enhance(1.6)
            img = ImageEnhance.Contrast(img).enhance(1.2)
            img = img.filter(ImageFilter.MedianFilter(size=3))

        elif "sepia" in kw or "warm" in kw:
            r, g, b = img.split()
            r_arr = np.array(r, dtype=np.float32)
            g_arr = np.array(g, dtype=np.float32)
            b_arr = np.array(b, dtype=np.float32)
            nr = np.clip(r_arr * 0.393 + g_arr * 0.769 + b_arr * 0.189, 0, 255).astype(np.uint8)
            ng = np.clip(r_arr * 0.349 + g_arr * 0.686 + b_arr * 0.168, 0, 255).astype(np.uint8)
            nb = np.clip(r_arr * 0.272 + g_arr * 0.534 + b_arr * 0.131, 0, 255).astype(np.uint8)
            img = Image.merge("RGB", [
                Image.fromarray(nr), Image.fromarray(ng), Image.fromarray(nb)
            ])

        elif "noir" in kw or "dark" in kw or "monochrome" in kw or "bw" in kw or "black and white" in kw:
            img = img.convert("L").convert("RGB")
            img = ImageEnhance.Contrast(img).enhance(1.3)
            grain = np.random.default_rng().random(img.size[::-1]) * 30
            grain_arr = np.stack([grain] * 3, axis=-1).astype(np.uint8)
            grain_img = Image.fromarray(grain_arr)
            img = ImageChops.add(img, grain_img)

        elif "pastel" in kw or "soft color" in kw:
            img = ImageEnhance.Color(img).enhance(0.6)
            img = ImageEnhance.Brightness(img).enhance(1.1)
            img = img.filter(ImageFilter.SMOOTH)

        elif "hdr" in kw or "dramatic" in kw:
            img = ImageEnhance.Contrast(img).enhance(1.5)
            img = ImageEnhance.Sharpness(img).enhance(2.0)
            img = ImageEnhance.Color(img).enhance(1.3)

        elif "mosaic" in kw or "stained" in kw or "glass" in kw:
            w, h = img.size
            s = 20
            small = img.resize((w // s, h // s), Image.NEAREST)
            img = small.resize((w, h), Image.NEAREST)

        elif "glitch" in kw:
            w, h = img.size
            arr = np.array(img)
            for _ in range(5):
                y = random.randint(0, h - 10)
                hh = random.randint(3, 15)
                shift = random.randint(5, 30)
                arr[y:y + hh, :, 0] = np.roll(arr[y:y + hh, :, 0], shift, axis=1)
                arr[y:y + hh, :, 1] = np.roll(arr[y:y + hh, :, 1], -shift, axis=1)
            img = Image.fromarray(arr)

        elif "pop art" in kw or "warhol" in kw:
            img = ImageOps.posterize(img, 3)
            img = ImageEnhance.Color(img).enhance(2.0)
            img = ImageEnhance.Contrast(img).enhance(1.3)

        else:
            img = img.filter(ImageFilter.SMOOTH)
            img = ImageEnhance.Color(img).enhance(1.15)
            img = ImageEnhance.Contrast(img).enhance(1.05)

        return img
