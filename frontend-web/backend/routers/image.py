from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional
import logging

from services.llm_service import generate_image, redesign_image, analyze_image, generate_qr_code

logger = logging.getLogger(__name__)
router = APIRouter()

ANALYSIS_OPTIONS = [
    {"id": "analyze", "label": "Analyze", "icon": "eye", "desc": "General image analysis"},
    {"id": "search", "label": "Search", "icon": "search", "desc": "Identify objects, plants, landmarks"},
    {"id": "detect", "label": "Detect", "icon": "scan", "desc": "Object detection"},
    {"id": "translate", "label": "Translate", "icon": "languages", "desc": "Extract & translate text"},
    {"id": "health", "label": "Health Scan", "icon": "heart", "desc": "Analyze health indicators"},
    {"id": "text", "label": "Extract Text", "icon": "file-text", "desc": "OCR text extraction"},
    {"id": "product", "label": "Product", "icon": "shopping-bag", "desc": "Identify products & details"},
]


@router.get("/image/analysis-options")
async def get_analysis_options():
    return {"options": ANALYSIS_OPTIONS}


class ImageGenerateRequest(BaseModel):
    prompt: str
    style: Optional[str] = None


class ImageGenerateResponse(BaseModel):
    image_base64: Optional[str] = None
    image_url: Optional[str] = None
    error: Optional[str] = None
    prompt: str
    type: str = "image_generated"


@router.post("/image/generate", response_model=ImageGenerateResponse)
async def image_generate(request: ImageGenerateRequest):
    try:
        result = await generate_image(request.prompt, request.style)
        return ImageGenerateResponse(
            image_base64=result.get("image_base64"),
            image_url=result.get("image_url"),
            prompt=result.get("prompt", request.prompt),
            type=result.get("type", "image_generated"),
        )
    except Exception as e:
        logger.error(f"Image generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/image/redesign", response_model=ImageGenerateResponse)
async def image_redesign(
    file: UploadFile = File(...),
    prompt: str = Form(...),
):
    try:
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Empty file")

        result = await redesign_image(file_bytes, prompt, file.filename or "image.jpg")
        return ImageGenerateResponse(
            image_base64=result.get("image_base64"),
            image_url=result.get("image_url"),
            prompt=result.get("prompt", prompt),
            type="image_redesign",
        )
    except Exception as e:
        logger.error(f"Image redesign failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class QRCodeGenerateRequest(BaseModel):
    data: str
    size: Optional[int] = 300


@router.post("/image/qr-code", response_model=ImageGenerateResponse)
async def generate_qrcode(request: QRCodeGenerateRequest):
    try:
        result = await generate_qr_code(request.data, request.size)
        return ImageGenerateResponse(
            image_base64=result.get("image_base64"),
            image_url=result.get("image_url"),
            prompt=result.get("prompt", ""),
            type=result.get("type", "qr_code"),
        )
    except Exception as e:
        logger.error(f"QR code generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/image/analyze")
async def image_analyze(
    file: UploadFile = File(...),
    session_id: Optional[str] = Form(None),
    messages: Optional[str] = Form(None),
    analysis_type: Optional[str] = Form(None),
):
    try:
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Empty file")

        import json
        parsed_messages = json.loads(messages) if messages else None

        result = await analyze_image(
            file_bytes,
            session_id=session_id,
            messages=parsed_messages,
            analysis_type=analysis_type,
        )
        return result
    except Exception as e:
        logger.error(f"Image analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
