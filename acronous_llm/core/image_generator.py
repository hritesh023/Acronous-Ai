import io
import json
import os
from pathlib import Path
from PIL import Image, ImageEnhance, ImageFilter, ImageDraw, ImageOps
import torch
import numpy as np

ASSETS_DIR = Path(__file__).parent.parent.parent / "assets"
LOGO_PATH = ASSETS_DIR / "logo.png"


class ImageGenerator:
    def __init__(self, config, llm=None):
        self.config = config
        self._llm = llm
        self._pipe = None
        self._inpaint_pipe = None
        self._is_available = False
        self._diffusers_model = os.getenv("ACRONOUS_DIFFUSERS_MODEL")
        self._openai_api_key = os.getenv("ACRONOUS_OPENAI_API_KEY") or ""
        self._replicate_api_token = os.getenv("REPLICATE_API_TOKEN")
        self._provider = os.getenv("ACRONOUS_IMAGE_PROVIDER", "auto").lower()
        self._init_pipeline()

    def _init_pipeline(self):
        pass

    def is_available(self):
        return self._is_available

    def _get_active_provider(self):
        if self._provider != "auto":
            provider = self._provider
        else:
            provider = "openai" if self._openai_api_key else None

        if provider == "diffusers":
            provider = None
        elif provider == "openai" and not self._openai_api_key:
            provider = None
        elif provider == "replicate" and not self._replicate_api_token:
            provider = None

        if provider:
            return provider

        return ""

    def _generate_negative_prompt(self, prompt, image_type="realistic"):
        try:
            if self._llm:
                neg_prompt_text = f"""Based on this image request, generate a negative prompt (what to avoid) for image generation. 
Return ONLY a comma-separated list of undesired elements.

Request: {prompt}
Image type: {image_type}

Negative prompt:"""
                resp = self._llm.generate(
                    neg_prompt_text,
                    system_prompt="You generate negative prompts for image generation. Return only a comma-separated list."
                )
                if resp and resp.strip():
                    return resp.strip().strip('"').strip("'")
        except Exception:
            pass
        return ""

    def _get_default_negative_prompt(self):
        return os.getenv("ACRONOUS_NEGATIVE_PROMPT", "bad quality, blurry, low resolution, distorted, ugly, deformed, watermark, text, signature, extra limbs, bad anatomy, cropped, worst quality, low quality, normal quality, jpeg artifacts, ugly, duplicate, morbid, mutilated, out of frame, extra fingers, mutated hands, poorly drawn hands, poorly drawn face, mutation, deformed, bad proportions, gross proportions, bad hands, missing fingers, extra digit, fewer digits, bad feet")

    def _get_simple_negative_prompt(self):
        return os.getenv("ACRONOUS_NEGATIVE_PROMPT_SIMPLE", "")

    def generate(self, prompt, negative_prompt=None, steps=None, guidance_scale=None, height=None, width=None, image_type="realistic"):
        steps = steps if steps is not None else self.config.IMAGE_STEPS
        guidance_scale = guidance_scale if guidance_scale is not None else self.config.IMAGE_GUIDANCE_SCALE
        height = height if height is not None else self.config.IMAGE_HEIGHT
        width = width if width is not None else self.config.IMAGE_WIDTH

        if negative_prompt is None:
            negative_prompt = self._generate_negative_prompt(prompt, image_type)

        providers_to_try = []
        preferred = self._get_active_provider()
        if preferred:
            providers_to_try.append(preferred)
        all_providers = ["openai", "replicate", "diffusers"]
        for p in all_providers:
            if p not in providers_to_try:
                providers_to_try.append(p)

        last_error = ""
        for provider in providers_to_try:
            if provider == "diffusers":
                if not self._is_available:
                    continue
                result = self._generate_diffusers(prompt, negative_prompt, steps, guidance_scale, height, width, image_type)
                if result and result[0] is not None:
                    return result
                last_error = result[1] if result and result[1] else ""

            elif provider == "openai":
                if not self._openai_api_key:
                    continue
                result = self._generate_openai_image(prompt)
                if result and result[0] is not None:
                    return result
                last_error = result[1] if result and result[1] else ""

            elif provider == "replicate":
                if not self._replicate_api_token:
                    continue
                result = self._generate_replicate(prompt, negative_prompt, steps, guidance_scale, image_type)
                if result and result[0] is not None:
                    return result
                last_error = result[1] if result and result[1] else ""

        return None, self._generate_error_message(last_error, prompt)

    def _generate_fallback_image(self, prompt, width, height):
        try:
            from PIL import ImageDraw, ImageFont
            import hashlib
            hash_int = int(hashlib.md5(prompt.encode()).hexdigest()[:8], 16)
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

    def _try_redesign_providers(self, image, prompt, strength, steps, guidance_scale):
        errors = []
        if self._is_available:
            result = self._redesign_diffusers(image, prompt, strength, steps, guidance_scale)
            if result and result[0] is not None:
                return result
            errors.append(result[1] if result and result[1] else "")
        if self._openai_api_key:
            result = self._redesign_openai_image(image, prompt)
            if result and result[0] is not None:
                return result
            errors.append(result[1] if result and result[1] else "")
        err = "; ".join(e for e in errors if e)
        return None, self._generate_error_message(err or "no image provider available for redesign", prompt)

    def redesign(self, image, prompt, strength=0.7, steps=None, guidance_scale=None):
        steps = steps if steps is not None else self.config.IMAGE_STEPS
        guidance_scale = guidance_scale if guidance_scale is not None else self.config.IMAGE_GUIDANCE_SCALE
        provider = self._get_active_provider()

        if provider == "diffusers":
            if not self._is_available:
                return None, self._generate_error_message("diffusers model not available for redesign", prompt)
            return self._redesign_diffusers(image, prompt, strength, steps, guidance_scale)

        if provider == "openai":
            if not self._openai_api_key:
                return None, self._generate_error_message("OpenAI API key not configured for redesign", prompt)
            return self._redesign_openai_image(image, prompt)

        return self._try_redesign_providers(image, prompt, strength, steps, guidance_scale)

    def _generate_error_message(self, error_type, prompt):
        return error_type

    def inpaint(self, image, mask, prompt, negative_prompt=None, strength=0.85, steps=None, guidance_scale=None):
        steps = steps if steps is not None else self.config.IMAGE_STEPS
        guidance_scale = guidance_scale if guidance_scale is not None else self.config.IMAGE_GUIDANCE_SCALE
        provider = self._get_active_provider()

        if isinstance(mask, str):
            mask = self._generate_mask_from_description(image, mask)

        if provider == "diffusers":
            if not self._is_available:
                return None, self._generate_error_message("diffusers model not available for inpainting", prompt)
            return self._inpaint_diffusers(image, mask, prompt, negative_prompt, strength, steps, guidance_scale)

        if provider in ("openai", "replicate"):
            return self._inpaint_fallback(image, mask, prompt, strength, steps, guidance_scale)

        return self._inpaint_fallback(image, mask, prompt, strength, steps, guidance_scale)

    def _inpaint_diffusers(self, image, mask, prompt, negative_prompt=None, strength=0.85, steps=None, guidance_scale=None):
        steps = steps if steps is not None else self.config.IMAGE_STEPS
        guidance_scale = guidance_scale if guidance_scale is not None else self.config.IMAGE_GUIDANCE_SCALE
        try:
            if isinstance(image, str):
                image = Image.open(image)
            if image.mode != "RGB":
                image = image.convert("RGB")
            image = self._preprocess_image(image)

            if isinstance(mask, str):
                mask = self._generate_mask_from_description(image, mask)
            if mask.mode != "L":
                mask = mask.convert("L")

            if self._inpaint_pipe is None:
                return self._inpaint_fallback(image, mask, prompt, strength, steps, guidance_scale)

            target_size = (self.config.IMAGE_WIDTH, self.config.IMAGE_HEIGHT)
            init_image = image.resize(target_size, Image.LANCZOS)
            mask_image = mask.resize(target_size, Image.LANCZOS)

            if negative_prompt is None:
                negative_prompt = self._generate_negative_prompt(prompt)

            result = self._inpaint_pipe(
                prompt=prompt,
                image=init_image,
                mask_image=mask_image,
                strength=strength,
                guidance_scale=guidance_scale,
                num_inference_steps=steps,
                negative_prompt=negative_prompt,
            )
            img = result.images[0]
            img = self._postprocess_image(img, "realistic")
            if LOGO_PATH.exists():
                img = self._add_watermark(img)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue(), None
        except Exception as e:
            return None, self._generate_error_message(f"inpainting failed: {str(e)}", prompt)

    def _inpaint_fallback(self, image, mask, prompt, strength=0.85, steps=None, guidance_scale=None):
        try:
            blurred = image.filter(ImageFilter.GaussianBlur(radius=15))
            if mask.mode != "L":
                mask = mask.convert("L")
            mask_np = np.array(mask) / 255.0
            mask_np = np.stack([mask_np] * 3, axis=-1)
            img_np = np.array(image, dtype=np.float32)
            blur_np = np.array(blurred, dtype=np.float32)
            blended = (img_np * (1 - mask_np) + blur_np * mask_np).astype(np.uint8)
            result = Image.fromarray(blended)
            buf = io.BytesIO()
            result.save(buf, format="PNG")
            return buf.getvalue(), None
        except Exception as e:
            return None, self._generate_error_message(f"inpaint fallback failed: {str(e)}", prompt)

    def _generate_mask_from_description(self, image, description):
        w, h = image.size

        try:
            from acronous_llm.core.vision import VisionEngine
            config_holder = type("Config", (), {"ENABLE_VISION": True})()
            vision = VisionEngine(config_holder)
            objects = vision.detect_objects(image)
        except Exception:
            objects = []

        objects_info = []
        if objects and isinstance(objects, list):
            for obj in objects[:10]:
                label = str(obj.get("label", obj.get("name", "")))
                box = obj.get("box", {})
                if box:
                    objects_info.append({
                        "label": label,
                        "x1": box.get("x1", 0),
                        "y1": box.get("y1", 0),
                        "x2": box.get("x2", w),
                        "y2": box.get("y2", h),
                    })

        try:
            prompt = f"""Given an image of size {w}x{h} pixels and the following detected objects, determine the mask region for an inpainting operation.

User request: "{description}"

Detected objects in the image:
{json.dumps(objects_info, indent=2) if objects_info else "No objects detected"}

Return a mask specification as valid JSON with these fields:
- "type": "object" if the mask should cover a detected object, "region" for a custom rectangular region, "whole_image" for the entire image
- "label": the object label (only for type "object", pick from the detected objects list)
- "x1", "y1", "x2", "y2": normalized coordinates (0.0-1.0) for the mask region (for type "region")
- "reasoning": brief explanation

Examples for different requests:
- "remove the person on the left" -> {{"type": "object", "label": "person", "reasoning": "person detected, mask their bounding box"}}
- "change the sky to sunset" -> {{"type": "region", "x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 0.4, "reasoning": "sky is typically the top 40% of the image"}}
- "add a tree in the background" -> {{"type": "region", "x1": 0.7, "y1": 0.3, "x2": 1.0, "y2": 0.8, "reasoning": "right side background area suitable for a tree"}}
- "erase the car" -> {{"type": "object", "label": "car", "reasoning": "car detected, mask it for removal"}}
- "redesign the whole image" -> {{"type": "whole_image", "reasoning": "user wants full image redesign"}}

Return ONLY valid JSON, no markdown, no code fences:"""
            if self._llm:
                resp = self._llm.generate(prompt, system_prompt="You generate mask specifications for image inpainting. Return valid JSON only.")
            else:
                resp = None

            if resp:
                resp = resp.strip()
                if resp.startswith("```"):
                    resp = resp.split("\n", 1)[-1]
                    if "```" in resp:
                        resp = resp.split("```")[0]
                mask_spec = json.loads(resp)
                mask_type = mask_spec.get("type", "whole_image")

                mask = Image.new("L", (w, h), 0)

                if mask_type == "object":
                    target_label = mask_spec.get("label", "").lower()
                    for obj in objects_info:
                        if target_label and target_label in obj["label"].lower():
                            x1 = max(0, int(obj["x1"]) - 10)
                            y1 = max(0, int(obj["y1"]) - 10)
                            x2 = min(w, int(obj["x2"]) + 10)
                            y2 = min(h, int(obj["y2"]) + 10)
                            draw = ImageDraw.Draw(mask)
                            draw.rectangle([x1, y1, x2, y2], fill=255)
                            return mask
                    draw = ImageDraw.Draw(mask)
                    draw.rectangle([w // 4, h // 4, 3 * w // 4, 3 * h // 4], fill=255)
                    return mask

                elif mask_type == "region":
                    x1 = max(0, int(mask_spec.get("x1", 0.25) * w))
                    y1 = max(0, int(mask_spec.get("y1", 0.25) * h))
                    x2 = min(w, int(mask_spec.get("x2", 0.75) * w))
                    y2 = min(h, int(mask_spec.get("y2", 0.75) * h))
                    draw = ImageDraw.Draw(mask)
                    draw.rectangle([x1, y1, x2, y2], fill=255)
                    return mask

                else:
                    draw = ImageDraw.Draw(mask)
                    draw.rectangle([0, 0, w, h], fill=255)
                    return mask

        except Exception:
            pass

        mask = Image.new("L", (w, h), 255)
        return mask

    def _preprocess_image(self, image, target_size=None):
        if image.mode != "RGB":
            image = image.convert("RGB")

        if target_size:
            image = image.resize(target_size, Image.LANCZOS)
        elif self.config.IMAGE_WIDTH and self.config.IMAGE_HEIGHT:
            target = (self.config.IMAGE_WIDTH, self.config.IMAGE_HEIGHT)
            if image.size != target:
                image = image.resize(target, Image.LANCZOS)

        for _ in range(self.config.IMAGE_DENOISE_ITERATIONS):
            image = image.filter(ImageFilter.SMOOTH)

        return image

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

    @torch.inference_mode()
    def _generate_diffusers(self, prompt, negative_prompt=None, steps=None, guidance_scale=None, height=None, width=None, image_type="realistic"):
        steps = steps if steps is not None else self.config.IMAGE_STEPS
        guidance_scale = guidance_scale if guidance_scale is not None else self.config.IMAGE_GUIDANCE_SCALE
        height = height if height is not None else self.config.IMAGE_HEIGHT
        width = width if width is not None else self.config.IMAGE_WIDTH
        try:
            if negative_prompt is None:
                negative_prompt = self._generate_negative_prompt(prompt, image_type)

            result = self._pipe(
                prompt,
                negative_prompt=negative_prompt,
                num_inference_steps=steps,
                guidance_scale=guidance_scale,
                height=height,
                width=width,
            )
            img = result.images[0]
            img = self._postprocess_image(img, image_type)
            if LOGO_PATH.exists():
                img = self._add_watermark(img)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue(), None
        except Exception as e:
            return None, self._generate_error_message(f"diffusers generation failed: {str(e)}", prompt)

    @torch.inference_mode()
    def _redesign_diffusers(self, image, prompt, strength=0.7, steps=None, guidance_scale=None):
        steps = steps if steps is not None else self.config.IMAGE_STEPS
        guidance_scale = guidance_scale if guidance_scale is not None else self.config.IMAGE_GUIDANCE_SCALE
        try:
            if isinstance(image, str):
                image = Image.open(image)
            if image.mode != "RGB":
                image = image.convert("RGB")
            image = self._preprocess_image(image)
            init_image = image.resize((self.config.IMAGE_WIDTH, self.config.IMAGE_HEIGHT), Image.LANCZOS)
            result = self._pipe(
                prompt,
                image=init_image,
                strength=strength,
                guidance_scale=guidance_scale,
                num_inference_steps=steps,
            )
            img = result.images[0]
            img = self._postprocess_image(img, "realistic")
            if LOGO_PATH.exists():
                img = self._add_watermark(img)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue(), None
        except Exception as e:
            return None, self._generate_error_message(f"diffusers redesign failed: {str(e)}", prompt)

    def _generate_openai_image(self, prompt):
        model = os.getenv("ACRONOUS_OPENAI_IMAGE_MODEL", "dall-e-3")

        try:
            from openai import OpenAI
            client = OpenAI(api_key=self._openai_api_key)
            size = os.getenv("ACRONOUS_OPENAI_IMAGE_SIZE", "1024x1024")

            max_prompt_len = 3900
            truncated = prompt[:max_prompt_len] if len(prompt) > max_prompt_len else prompt

            resp = client.images.generate(
                model=model,
                prompt=truncated,
                n=1,
                size=size,
                quality="standard",
                response_format="b64_json",
            )
            import base64
            img_bytes = base64.b64decode(resp.data[0].b64_json)
            img = Image.open(io.BytesIO(img_bytes))
            img = self._postprocess_image(img)
            if LOGO_PATH.exists():
                img = self._add_watermark(img)
            out_buf = io.BytesIO()
            img.save(out_buf, format="PNG")
            return out_buf.getvalue(), None
        except Exception as e:
            return None, self._generate_error_message(f"OpenAI image generation failed: {str(e)}", prompt)

    def _redesign_openai_image(self, image, prompt):
        model = os.getenv("ACRONOUS_OPENAI_IMAGE_MODEL", "dall-e-2")

        try:
            from openai import OpenAI
            import base64
            if image.mode != "RGB":
                image = image.convert("RGB")
            image = self._preprocess_image(image)
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            client = OpenAI(api_key=self._openai_api_key)
            resp = client.images.edit(
                model=model,
                image=io.BytesIO(base64.b64decode(b64)),
                prompt=prompt,
                n=1,
                size="1024x1024",
            )
            img_bytes = base64.b64decode(resp.data[0].b64_json) if hasattr(resp.data[0], "b64_json") else None
            if img_bytes:
                img = Image.open(io.BytesIO(img_bytes))
                img = self._postprocess_image(img)
                if LOGO_PATH.exists():
                    img = self._add_watermark(img)
                out_buf = io.BytesIO()
                img.save(out_buf, format="PNG")
                return out_buf.getvalue(), None
            import requests
            img_resp = requests.get(resp.data[0].url)
            img = Image.open(io.BytesIO(img_resp.content))
            img = self._postprocess_image(img)
            if LOGO_PATH.exists():
                img = self._add_watermark(img)
            out_buf = io.BytesIO()
            img.save(out_buf, format="PNG")
            return out_buf.getvalue(), None
        except Exception as e:
            return None, self._generate_error_message(f"OpenAI image redesign failed: {str(e)}", prompt)

    def _generate_replicate(self, prompt, negative_prompt=None, steps=None, guidance_scale=None, image_type="realistic"):
        steps = steps if steps is not None else self.config.IMAGE_STEPS
        guidance_scale = guidance_scale if guidance_scale is not None else self.config.IMAGE_GUIDANCE_SCALE
        try:
            import replicate
            if negative_prompt is None:
                negative_prompt = self._generate_negative_prompt(prompt, image_type)
            client = replicate.Client(api_token=self._replicate_api_token)
            model = os.getenv("ACRONOUS_REPLICATE_IMAGE_MODEL", "stability-ai/stable-diffusion:db21e45d3f7023abc2a46ab38be2d2b5e8e4b45b7e0f9b9e9c9b9e9c9b9e9c9b")
            output = client.run(model, input={
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "num_outputs": 1,
                "num_inference_steps": steps,
                "guidance_scale": guidance_scale
            })
            if output and len(output) > 0:
                import requests
                resp = requests.get(output[0], timeout=60)
                img = Image.open(io.BytesIO(resp.content))
                img = self._postprocess_image(img, image_type)
                if LOGO_PATH.exists():
                    img = self._add_watermark(img)
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                return buf.getvalue(), None
            return None, self._generate_error_message("Replicate returned no output", prompt)
        except Exception as e:
            return None, self._generate_error_message(f"Replicate image generation failed: {str(e)}", prompt)



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
