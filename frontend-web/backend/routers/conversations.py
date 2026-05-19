from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import uuid
from datetime import datetime

from database.db import (
    create_conversation,
    get_conversations,
    get_conversation,
    update_conversation,
    delete_conversation,
    add_message,
    get_messages,
)

router = APIRouter()


class CreateConversationRequest(BaseModel):
    title: str = "New Conversation"


class UpdateConversationRequest(BaseModel):
    title: str


class AddMessageRequest(BaseModel):
    role: str
    content: str
    msg_type: str = "text"
    sources: Optional[str] = None
    label: Optional[str] = None
    image: Optional[str] = None
    media_url: Optional[str] = None
    video_url: Optional[str] = None
    audio_url: Optional[str] = None


class ConversationResponse(BaseModel):
    id: str
    user_id: str
    title: str
    created_at: str
    updated_at: str


class MessageResponse(BaseModel):
    id: str
    conversation_id: str
    user_id: str
    role: str
    content: str
    type: str
    sources: Optional[str] = None
    analysis: Optional[str] = None
    label: Optional[str] = None
    image: Optional[str] = None
    media_url: Optional[str] = None
    video_url: Optional[str] = None
    audio_url: Optional[str] = None
    created_at: str


@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations():
    convs = get_conversations()
    return [ConversationResponse(**c) for c in convs]


@router.post("/conversations", response_model=ConversationResponse)
async def create_conversation_endpoint(request: CreateConversationRequest):
    conv_id = f"conv_{uuid.uuid4().hex[:12]}"
    conv = create_conversation(conv_id, request.title)
    return ConversationResponse(**conv)


@router.delete("/conversations/{conv_id}")
async def delete_conversation_endpoint(conv_id: str):
    success = delete_conversation(conv_id)
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "ok"}


@router.put("/conversations/{conv_id}", response_model=ConversationResponse)
async def update_conversation_endpoint(conv_id: str, request: UpdateConversationRequest):
    conv = update_conversation(conv_id, request.title)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return ConversationResponse(**conv)


@router.get("/conversations/{conv_id}/messages", response_model=list[MessageResponse])
async def list_messages(conv_id: str):
    conv = get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    msgs = get_messages(conv_id)
    return [MessageResponse(**m) for m in msgs]


@router.post("/conversations/{conv_id}/messages", response_model=MessageResponse)
async def add_message_endpoint(conv_id: str, request: AddMessageRequest):
    conv = get_conversation(conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    msg_id = f"msg_{uuid.uuid4().hex[:12]}"
    msg = add_message(
        msg_id=msg_id,
        conv_id=conv_id,
        role=request.role,
        content=request.content,
        msg_type=request.msg_type,
        sources=request.sources,
        label=request.label,
        image=request.image,
        media_url=request.media_url,
        video_url=request.video_url,
        audio_url=request.audio_url,
    )
    return MessageResponse(**msg)


@router.post("/conversations/sync")
async def sync_conversations(conversations: list[dict]):
    results = []
    for conv_data in conversations:
        conv_id = conv_data.get("id", f"conv_{uuid.uuid4().hex[:12]}")
        title = conv_data.get("title", "Synced Conversation")
        existing = get_conversation(conv_id)
        if existing:
            update_conversation(conv_id, title)
        else:
            create_conversation(conv_id, title)

        messages = conv_data.get("messages", [])
        for msg in messages:
            msg_id = f"msg_{uuid.uuid4().hex[:12]}"
            add_message(
                msg_id=msg_id,
                conv_id=conv_id,
                role=msg.get("role", "user"),
                content=msg.get("content", ""),
                msg_type=msg.get("type", "text"),
                label=msg.get("label"),
                image=msg.get("image"),
                media_url=msg.get("media_url"),
                video_url=msg.get("video_url"),
                audio_url=msg.get("audio_url"),
            )
        results.append({"id": conv_id, "status": "synced"})
    return {"synced": results}
