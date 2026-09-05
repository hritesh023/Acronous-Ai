import io
import base64
import urllib.parse
import logging
from pathlib import Path
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

logger = logging.getLogger(__name__)

ASSETS_DIR = Path(__file__).parent.parent.parent / "assets"
LOGO_PATH = ASSETS_DIR / "logo.png"


class ImageGenerator:
    def __init__(self, config, llm=None):
        self.config = config
        self._llm = llm

    def is_available(self):
        return True

    def generate(self, prompt, **kwargs):
        import requests
        import time

        width = kwargs.get("width") or self.config.IMAGE_WIDTH
        height = kwargs.get("height") or self.config.IMAGE_HEIGHT

        urls_and_descriptions = [
            (f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}?width={width}&height={height}&model=flux&nologo=true", "flux"),
            (f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}?width={width}&height={height}&nologo=true", "default"),
        ]

        max_retries = 3
        last_error = None
        for url, model_name in urls_and_descriptions:
            for attempt in range(max_retries + 1):
                try:
                    resp = requests.get(url, timeout=90)
                    if resp.status_code != 200:
                        last_error = None
                        if attempt < max_retries:
                            time.sleep(2 * (attempt + 1))
                            continue
                        break
                    img = Image.open(io.BytesIO(resp.content))
                    img = self._postprocess_image(img)
                    if LOGO_PATH.exists():
                        img = self._add_watermark(img)
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    return buf.getvalue(), None
                except requests.exceptions.Timeout:
                    last_error = None
                    if attempt < max_retries:
                        time.sleep(3 * (attempt + 1))
                        continue
                except Exception as e:
                    last_error = str(e)
                    if attempt < max_retries:
                        time.sleep(2 * (attempt + 1))
                        continue
        return None, last_error

    def edit_image(self, image_bytes, prompt, **kwargs):
        """Multi-strategy image editing pipeline (from Acronous AI)."""
        import requests
        import time

        strategies = [
            self._edit_pollinations_kontext,
            self._edit_pollinations_img2img,
            self._edit_llm_guided,
        ]

        for strategy in strategies:
            try:
                result = strategy(image_bytes, prompt, **kwargs)
                if result:
                    return result, None
            except Exception as e:
                logger.warning(f"Edit strategy {strategy.__name__} failed: {e}")
                continue

        return None, "All editing strategies failed"

    def _edit_pollinations_kontext(self, image_bytes, prompt, **kwargs):
        """Pollinations OpenAI-compatible edit endpoint with kontext model."""
        import requests
        try:
            ct = "image/png" if image_bytes[:4] == b'\x89PNG' else "image/jpeg"
            ext = "png" if "png" in ct else "jpg"
            files = {"image": (f"image.{ext}", image_bytes, ct)}
            data = {"prompt": prompt, "model": "kontext"}
            resp = requests.post("https://gen.pollinations.ai/v1/images/edits", files=files, data=data, timeout=60)
            if resp.status_code != 200:
                return None
            ct_resp = resp.headers.get("content-type", "")
            if "application/json" in ct_resp:
                j = resp.json()
                b64 = j.get("data", [{}])[0].get("b64_json")
                if b64:
                    return base64.b64decode(b64)
                return None
            if resp.content and len(resp.content) > 200:
                return resp.content
            return None
        except Exception:
            return None

    def _edit_pollinations_img2img(self, image_bytes, prompt, **kwargs):
        """Pollinations img2img with original dimensions."""
        import requests
        try:
            img = Image.open(io.BytesIO(image_bytes))
            w, h = img.size
            b64 = base64.b64encode(image_bytes).decode()
            resp = requests.post(
                f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}",
                json={"img": b64, "width": w, "height": h, "nofeed": True},
                timeout=60,
            )
            if resp.status_code != 200:
                return None
            if resp.content and len(resp.content) > 200:
                return resp.content
            return None
        except Exception:
            return None

    def _edit_llm_guided(self, image_bytes, prompt, **kwargs):
        """LLM analyzes image context, generates a text-to-image prompt for the edited version."""
        if not self._llm:
            return None
        try:
            b64 = base64.b64encode(image_bytes).decode()
            desc_prompt = f"""Describe this image in detail (subject, clothing, background, colors, composition).
The user wants to edit it: "{prompt}"
Write a prompt for generating the EDITED version. Include key details plus the change. Return ONLY the prompt, 1-2 sentences."""
            gen_prompt = self._llm.generate(desc_prompt, system_prompt="You create image generation prompts. Return ONLY the prompt.")
            if not gen_prompt or len(gen_prompt.strip()) < 15:
                return None
            gen_prompt = gen_prompt.strip().strip('"').strip("'")
            img_bytes, _ = self.generate(gen_prompt)
            return img_bytes
        except Exception:
            return None

    def _postprocess_image(self, image, image_type="realistic"):
        try:
            if image_type == "realistic":
                for _ in range(self.config.IMAGE_DENOISE_ITERATIONS):
                    image = image.filter(ImageFilter.SMOOTH)

                detail_strength = self.config.IMAGE_DETAIL_ENHANCE_STRENGTH
                if detail_strength > 0:
                    detail = image.filter(ImageFilter.DETAIL)
                    image = Image.blend(image, detail, detail_strength)

                image = image.filter(ImageFilter.UnsharpMask(
                    radius=self.config.IMAGE_UNSHARP_RADIUS,
                    percent=self.config.IMAGE_UNSHARP_PERCENT,
                    threshold=self.config.IMAGE_UNSHARP_THRESHOLD,
                ))

                cutoff = self.config.IMAGE_AUTO_CONTRAST_CUTOFF
                if cutoff > 0:
                    image = ImageOps.autocontrast(image, cutoff=int(cutoff * 255))

                sharpener = ImageEnhance.Sharpness(image)
                image = sharpener.enhance(self.config.IMAGE_SHARPEN_FACTOR)
                contrast = ImageEnhance.Contrast(image)
                image = contrast.enhance(self.config.IMAGE_CONTRAST_FACTOR)
                color = ImageEnhance.Color(image)
                image = color.enhance(self.config.IMAGE_COLOR_FACTOR)

            return image
        except Exception:
            return image

    def _add_watermark(self, img):
        try:
            if not LOGO_PATH.exists():
                return img
            logo = Image.open(LOGO_PATH).convert("RGBA")
            logo_size = max(img.width, img.height) // 60
            if logo_size < 12:
                logo_size = 12
            if logo_size > 20:
                logo_size = 20
            logo.thumbnail((logo_size, logo_size), Image.LANCZOS)
            l_w, l_h = logo.size
            margin = 4
            pos_x = img.width - l_w - margin
            pos_y = img.height - l_h - margin
            logo_alpha = logo.split()[3]
            alpha = logo_alpha.point(lambda p: int(p * 0.20))
            logo.putalpha(alpha)
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            img.paste(logo, (pos_x, pos_y), logo)
            return img.convert("RGB")
        except Exception:
            return img

    def redesign(self, image, prompt, **kwargs):
        return self.generate(prompt, **kwargs)

    def inpaint(self, image, mask, prompt, **kwargs):
        return self.generate(prompt, **kwargs)

    def img2img(self, image_b64, prompt, strength=0.7, mask_description=None):
        try:
            img_data = base64.b64decode(image_b64)
            img = Image.open(io.BytesIO(img_data))
            img.thumbnail((512, 512), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            result, error = self.edit_image(buf.getvalue(), prompt)
            if result:
                return {"image_data": base64.b64encode(result).decode("utf-8"), "image_type": "png"}
            return None
        except Exception:
            return None
