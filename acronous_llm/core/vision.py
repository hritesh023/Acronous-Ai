import torch
import numpy as np
from PIL import Image
import io
import base64
import re

class VisionEngine:
    def __init__(self, config):
        self.config = config
        self._model = None
        self._processor = None
        self._models_loaded = False
        self.ocr_reader = None

    def _ensure_models(self):
        if self._models_loaded:
            return
        self._models_loaded = True
        try:
            from transformers import ViTForImageClassification, ViTImageProcessor
            self._processor = ViTImageProcessor.from_pretrained(
                self.config.VISION_MODEL
            )
            self._model = ViTForImageClassification.from_pretrained(
                self.config.VISION_MODEL
            )
            self._model.eval()
        except Exception:
            pass

    @property
    def model(self):
        self._ensure_models()
        return self._model

    @property
    def processor(self):
        self._ensure_models()
        return self._processor

    def analyze_image(self, image):
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
        results = {"format": image.format, "size": image.size, "mode": image.mode}

        qr_data = self._scan_qr(image)
        if qr_data:
            results["qr_code"] = qr_data

        self._ensure_models()
        if self._model is not None:
            try:
                inputs = self._processor(image, return_tensors="pt")
                with torch.no_grad():
                    outputs = self._model(**inputs)
                probs = torch.nn.functional.softmax(outputs.logits, dim=-1)
                top_probs, top_indices = torch.topk(probs, 5)
                if hasattr(self._model.config, "id2label"):
                    labels = [
                        self._model.config.id2label[idx.item()]
                        for idx in top_indices[0]
                    ]
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

    def _extract_text(self, image):
        try:
            import easyocr
            if self.ocr_reader is None:
                self.ocr_reader = easyocr.Reader(["en"], gpu=False)
            result = self.ocr_reader.readtext(np.array(image))
            return " ".join([r[1] for r in result])
        except Exception:
            try:
                import pytesseract
                return pytesseract.image_to_string(image).strip()
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
