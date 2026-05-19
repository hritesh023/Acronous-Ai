from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import uuid

from services.llm_service import chat_completion
from services.memory import memory
from database.db import get_conversation_context, add_message as db_add_message

router = APIRouter()


class ChatRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    context: Optional[dict] = None
    messages: Optional[list[dict]] = None
    web_search_enabled: bool = True
    model: Optional[str] = None


class ChatResponse(BaseModel):
    content: str
    type: str
    sources: list[dict] = []
    analysis: Optional[dict] = None
    session_id: str = ""
    image_url: Optional[str] = None
    image_base64: Optional[str] = None
    video_url: Optional[str] = None
    audio_url: Optional[str] = None


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    session_id = request.session_id or f"session_{uuid.uuid4().hex[:8]}"

    conv_messages = list(request.messages) if request.messages else []

    if not conv_messages and session_id:
        try:
            conv_messages = get_conversation_context(session_id)
        except Exception:
            conv_messages = memory.get_context(session_id)

    result = await chat_completion(
        query=request.query,
        messages=conv_messages,
        session_id=session_id,
        web_search_enabled=request.web_search_enabled,
        model=request.model,
    )

    if session_id:
        memory.add_message(session_id, "user", request.query)
        memory.add_message(session_id, "assistant", result.get("content", ""))

    return ChatResponse(
        content=result.get("content", ""),
        type=result.get("type", "text"),
        sources=result.get("sources", []),
        analysis=result.get("analysis"),
        session_id=session_id,
        image_url=result.get("image_url"),
        image_base64=result.get("image_base64"),
        video_url=result.get("video_url"),
        audio_url=result.get("audio_url"),
    )


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    from fastapi.responses import StreamingResponse
    import asyncio

    session_id = request.session_id or f"session_{uuid.uuid4().hex[:8]}"

    conv_messages = request.messages or []
    if session_id and not conv_messages:
        conv_messages = memory.get_context(session_id)

    result = await chat_completion(
        query=request.query,
        messages=conv_messages,
        session_id=session_id,
        web_search_enabled=request.web_search_enabled,
        model=request.model,
    )

    content = result.get("content", "")

    async def generate():
        words = content.split(" ")
        for i, word in enumerate(words):
            yield f"data: {word} "
            if i < len(words) - 1:
                yield " "
            await asyncio.sleep(0.02)
        yield "\ndata: [DONE]"

    return StreamingResponse(generate(), media_type="text/event-stream")
