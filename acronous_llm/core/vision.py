import base64
import io
import logging
from PIL import Image

logger = logging.getLogger(__name__)


class VisionEngine:
    """LLM-powered vision analysis (from Acronous AI).

    Uses Acronous Oracle or OpenAI-compatible vision models for detailed image understanding.
    Falls back to local ViT classification if no API key is available.
    """
    def __init__(self, config):
        self.config = config
        self._model = None
        self._processor = None
        self._models_loaded = False
        self.ocr_reader = None
        self._llm_client = None
        self._vision_model = None
        self._init_llm_vision()

    def _init_llm_vision(self):
        """Initialize LLM-based vision via Acronous Oracle or OpenAI-compatible API."""
        import os
        api_key = os.getenv("ACRONOUS_LLM_API_KEY", "")
        provider = os.getenv("ACRONOUS_LLM_PROVIDER", "oracle").lower()
        try:
            from openai import OpenAI
            if provider == "oracle":
                base_url = os.getenv("ACRONOUS_LLM_API_URL", "https://oracle.acronous.com")
                self._vision_model = os.getenv("ACRONOUS_VISION_MODEL", "qwen2.5:14b")
            elif provider in ("openai", "groq", "together"):
                base_url = os.getenv("ACRONOUS_LLM_API_URL", "https://api.openai.com/v1")
                self._vision_model = os.getenv("ACRONOUS_VISION_MODEL", "gpt-4o-mini")
                if not api_key:
                    return
            else:
                return
            self._llm_client = OpenAI(api_key=api_key or "acronous-oracle", base_url=base_url)
            logger.info(f"[VISION] LLM vision initialized (model: {self._vision_model})")
        except Exception as e:
            logger.warning(f"[VISION] LLM vision init failed: {e}")

    def _ensure_models(self):
        if self._models_loaded:
            return
        self._models_loaded = True
        try:
            from transformers import ViTForImageClassification, ViTImageProcessor
            self._processor = ViTImageProcessor.from_pretrained(self.config.VISION_MODEL)
            self._model = ViTForImageClassification.from_pretrained(self.config.VISION_MODEL)
            self._model.eval()
        except Exception:
            pass

    def analyze_image(self, image):
        """Analyze image — uses LLM vision if available, falls back to local ViT."""
        if isinstance(image, str):
            try:
                if image.startswith("data:image"):
                    image = self._base64_to_image(image)
                else:
                    image = Image.open(image)
            except Exception:
                return {"error": "Cannot load image"}
        if not isinstance(image, Image.Image):
            image = Image.open(io.BytesIO(image))

        results = {"format": getattr(image, 'format', None), "size": image.size, "mode": image.mode}

        # Try LLM vision first (much better quality)
        if self._llm_client:
            try:
                b64 = self._image_to_base64(image)
                mime = "image/png" if getattr(image, 'format', '') == "PNG" else "image/jpeg"
                response = self._llm_client.chat.completions.create(
                    model=self._vision_model,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Describe this image in detail. Include: main subjects, people, objects, colors, composition, text visible, setting/background, and any notable details. Be thorough but concise."},
                            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                        ],
                    }],
                    max_tokens=1024,
                    temperature=0.3,
                )
                content = response.choices[0].message.content
                if content:
                    results["description"] = content
                    results["top_label"] = content.split(".")[0][:100]
                    results["llm_vision"] = True
                    return results
            except Exception as e:
                logger.warning(f"[VISION] LLM vision failed: {e}")

        # Fallback: local ViT classification
        self._ensure_models()
        if self._model is not None:
            try:
                import torch
                inputs = self._processor(image, return_tensors="pt")
                with torch.no_grad():
                    outputs = self._model(**inputs)
                probs = torch.nn.functional.softmax(outputs.logits, dim=-1)
                top_probs, top_indices = torch.topk(probs, 5)
                if hasattr(self._model.config, "id2label"):
                    labels = [self._model.config.id2label[idx.item()] for idx in top_indices[0]]
                else:
                    labels = [f"class_{idx.item()}" for idx in top_indices[0]]
                results["predictions"] = [
                    {"label": l, "confidence": round(p.item(), 4)}
                    for l, p in zip(labels, top_probs[0])
                ]
                results["top_label"] = labels[0]
                results["top_confidence"] = round(top_probs[0][0].item(), 4)
            except Exception:
                results["classification_error"] = "classification failed"

        ocr_text = self._extract_text(image)
        if ocr_text:
            results["ocr_text"] = ocr_text
        return results

    def describe_for_editing(self, image, edit_prompt=""):
        """Get image description specifically for guiding image editing (from Acronous AI)."""
        if not self._llm_client:
            return self.analyze_image(image).get("description", "")
        try:
            if isinstance(image, str) and image.startswith("data:image"):
                image = self._base64_to_image(image)
            if not isinstance(image, Image.Image):
                image = Image.open(io.BytesIO(image))
            b64 = self._image_to_base64(image)
            mime = "image/png" if getattr(image, 'format', '') == "PNG" else "image/jpeg"
            response = self._llm_client.chat.completions.create(
                model=self._vision_model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"Describe this image in detail. Focus on the subject, their clothing/attire, background, colors, and composition. The user wants to edit it: \"{edit_prompt}\""},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    ],
                }],
                max_tokens=1024,
                temperature=0.3,
            )
            return response.choices[0].message.content or ""
        except Exception:
            return ""

    def detect_objects(self, image):
        try:
            from transformers import YolosForObjectDetection, YolosImageProcessor
            detector = YolosForObjectDetection.from_pretrained("hustvl/yolos-tiny")
            det_processor = YolosImageProcessor.from_pretrained("hustvl/yolos-tiny")
            if isinstance(image, str):
                image = Image.open(image)
            inputs = det_processor(images=image, return_tensors="pt")
            import torch
            with torch.no_grad():
                outputs = detector(**inputs)
            target_sizes = torch.tensor([image.size[::-1]])
            results = det_processor.post_process_object_detection(
                outputs, threshold=0.5, target_sizes=target_sizes
            )[0]
            detections = []
            for score, label, box in zip(
                results["scores"], results["labels"], results["boxes"]
            ):
                detections.append({
                    "label": detector.config.id2label[label.item()],
                    "confidence": round(score.item(), 3),
                    "box": box.tolist()
                })
            return detections
        except Exception:
            return []

    def _extract_text(self, image):
        try:
            import easyocr
            if self.ocr_reader is None:
                self.ocr_reader = easyocr.Reader(["en"], gpu=False)
            import numpy as np
            result = self.ocr_reader.readtext(np.array(image))
            return " ".join([r[1] for r in result])
        except Exception:
            try:
                import pytesseract
                return pytesseract.image_to_string(image).strip()
            except Exception:
                return ""

    def _scan_qr(self, image):
        try:
            from pyzbar.pyzbar import decode
            decoded = decode(image)
            if decoded:
                return [{"data": d.data.decode("utf-8"), "type": d.type} for d in decoded]
        except Exception:
            pass
        try:
            import cv2
            import numpy as np
            detector = cv2.QRCodeDetector()
            img_cv = np.array(image.convert("RGB"))[:, :, ::-1]
            data, _, _ = detector.detectAndDecode(img_cv)
            if data:
                return [{"data": data, "type": "QR_CODE"}]
        except Exception:
            pass
        return None

    def _base64_to_image(self, b64_str):
        if "," in b64_str:
            b64_str = b64_str.split(",")[1]
        img_data = base64.b64decode(b64_str)
        return Image.open(io.BytesIO(img_data))

    def _image_to_base64(self, image):
        buf = io.BytesIO()
        fmt = getattr(image, 'format', None) or "PNG"
        if fmt not in ("PNG", "JPEG", "JPG"):
            fmt = "PNG"
        image.save(buf, format=fmt)
        return base64.b64encode(buf.getvalue()).decode()
