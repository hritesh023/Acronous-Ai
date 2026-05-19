from fastapi import APIRouter, UploadFile, File
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


class TranscriptionResponse(BaseModel):
    text: str
    type: str = "text"


@router.post("/voice/transcribe", response_model=TranscriptionResponse)
async def voice_transcribe(file: UploadFile = File(...)):
    return TranscriptionResponse(
        text="",
        type="text",
    )
