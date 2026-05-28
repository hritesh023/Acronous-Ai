import io
from pathlib import Path
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

ASSETS_DIR = Path(__file__).parent.parent.parent / "assets"
LOGO_PATH = ASSETS_DIR / "logo.png"


class ImageGenerator:
    def __init__(self, config, llm=None):
        self.config = config
        self._llm = llm

    def is_available(self):
        return True

    def generate(self, prompt, **kwargs):
        try:
            import requests
            import urllib.parse
            encoded = urllib.parse.quote(prompt)
            width = kwargs.get("width") or self.config.IMAGE_WIDTH
            height = kwargs.get("height") or self.config.IMAGE_HEIGHT
            url = f"https://image.pollinations.ai/prompt/{encoded}?width={width}&height={height}&model=flux&nologo=true"
            resp = requests.get(url, timeout=60)
            if resp.status_code != 200:
                return None, f"Pollinations returned {resp.status_code}"
            img = Image.open(io.BytesIO(resp.content))
            img = self._postprocess_image(img)
            if LOGO_PATH.exists():
                img = self._add_watermark(img)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue(), None
        except Exception as e:
            return None, f"Image generation failed: {str(e)}"

    def _generate_fallback_image(self, prompt, width, height):
        try:
            gradient = Image.new("RGB", (width, height))
            for y in range(height):
                t = y / height
                r = int(20 + t * 35)
                g = int(20 + t * 30)
                b = int(50 + t * 45)
                for x in range(width):
                    gradient.putpixel((x, y), (r, g, b))
            buf = io.BytesIO()
            gradient.save(buf, format="PNG")
            return buf.getvalue()
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
