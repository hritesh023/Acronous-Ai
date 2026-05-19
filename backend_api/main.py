"""
Apex AI REST API — optimized backend serving web + mobile
"""

import os, sys, json, uuid, base64, time, hashlib, re
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any, List
from io import BytesIO
from collections import defaultdict
from datetime import datetime

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apex_llm import ApexConfig, ApexNeuralEngine, ApexCoreEngine, ApexAgentEngine
from supabase_client import get_supabase, verify_token

config = neural = core = agent = None

# ── Simple in-memory rate limiter ──
class RateLimiter:
    def __init__(self, max_per_minute: int = 60):
        self.max_per_minute = max_per_minute
        self.buckets: Dict[str, list] = defaultdict(list)

    def check(self, key: str) -> bool:
        now = time.time()
        self.buckets[key] = [t for t in self.buckets.get(key, []) if now - t < 60]
        if len(self.buckets[key]) >= self.max_per_minute:
            return False
        self.buckets[key].append(now)
        return True

rate_limiter = RateLimiter()

# ── Simple response cache ──
response_cache: Dict[str, Dict] = {}
CACHE_TTL = 300

def get_cache_key(query: str, session_id: str) -> str:
    return hashlib.md5(f"{query}:{session_id}".encode()).hexdigest()

def get_cached(key: str) -> Optional[Dict]:
    entry = response_cache.get(key)
    if entry and time.time() - entry["ts"] < CACHE_TTL:
        return entry["data"]
    return None

def set_cache(key: str, data: Dict):
    response_cache[key] = {"data": data, "ts": time.time()}
    if len(response_cache) > 500:
        stale = [k for k, v in response_cache.items() if time.time() - v["ts"] > CACHE_TTL]
        for k in stale:
            del response_cache[k]

@asynccontextmanager
async def lifespan(app: FastAPI):
    global config, neural, core, agent
    print("\n[APEX] Initializing Apex AI backend...")
    try:
        config = ApexConfig()
        config.load_env_file()
        config.save()
        neural = ApexNeuralEngine(config)
        core = ApexCoreEngine(config)
        agent = ApexAgentEngine(neural, core)
        print(f"[APEX] Backend ready | Model: {config.LLM_MODEL} | Search: {config.SEARCH_PROVIDER}")
    except Exception as e:
        print(f"[APEX] Init error (non-fatal): {e}")
    yield
    print("\n[APEX] Shutting down.")

app = FastAPI(title="Apex AI Backend", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Models ──
class ChatRequest(BaseModel):
    query: str
    session_id: str = "default"
    context: Optional[Dict[str, Any]] = None
    messages: Optional[List[Dict[str, Any]]] = None

class ChatResponse(BaseModel):
    content: str
    type: str = "chat"
    sources: List[Dict[str, Any]] = []
    analysis: Optional[Dict[str, Any]] = None
    session_id: str
    image_url: Optional[str] = None
    image_base64: Optional[str] = None
    video_url: Optional[str] = None
    audio_url: Optional[str] = None

class ImageGenerateRequest(BaseModel):
    prompt: str
    style: str = "Auto"

class ImageGenerateResponse(BaseModel):
    image_base64: Optional[str] = None
    image_url: Optional[str] = None
    error: Optional[str] = None
    prompt: str
    type: str = "image_gen"

class ConversationData(BaseModel):
    id: str
    title: str
    created_at: str
    messages_count: int

class ModelInfo(BaseModel):
    name: str
    type: str
    size: Optional[str] = None

# ── Auth helper ──
async def resolve_user(authorization: str | None = None) -> str | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ")
    user = verify_token(token)
    return user.get("id") if user else None

# ── Health ──
@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

@app.get("/")
async def root():
    return {"name": "Apex AI Backend", "version": "2.0.0", "docs": "/docs"}

# ── Auth ──
@app.get("/api/auth/me")
async def get_me(authorization: str = Header(None)):
    user_id = await resolve_user(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        sb = get_supabase()
        profile = sb.table("profiles").select("*").eq("id", user_id).execute()
        return {"id": user_id, "profile": profile.data[0] if profile.data else {"id": user_id}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/auth/signup")
async def sign_up(email: str = Form(...), password: str = Form(...)):
    try:
        sb = get_supabase()
        resp = sb.auth.sign_up({"email": email, "password": password})
        return {"user": resp.user.model_dump() if resp.user else None, "session": resp.session.model_dump() if resp.session else None}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/auth/signin")
async def sign_in(email: str = Form(...), password: str = Form(...)):
    try:
        sb = get_supabase()
        resp = sb.auth.sign_in_with_password({"email": email, "password": password})
        return {"user": resp.user.model_dump() if resp.user else None, "session": resp.session.model_dump() if resp.session else None}
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))

# ── Conversations ──
@app.get("/api/conversations")
async def list_conversations(authorization: str = Header(None), search: Optional[str] = None):
    user_id = await resolve_user(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        sb = get_supabase()
        query = sb.table("conversations").select("*").eq("user_id", user_id)
        if search:
            query = query.ilike("title", f"%{search}%")
        resp = query.order("updated_at", desc=True).execute()
        return resp.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/conversations")
async def create_conversation(title: str = "New Conversation", authorization: str = Header(None)):
    user_id = await resolve_user(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        sb = get_supabase()
        resp = sb.table("conversations").insert({"user_id": user_id, "title": title}).execute()
        return resp.data[0] if resp.data else None
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/conversations/{conv_id}")
async def delete_conversation(conv_id: str, authorization: str = Header(None)):
    user_id = await resolve_user(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        sb = get_supabase()
        sb.table("conversations").delete().eq("id", conv_id).eq("user_id", user_id).execute()
        return {"deleted": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/conversations/{conv_id}")
async def update_conversation(conv_id: str, title: str, authorization: str = Header(None)):
    user_id = await resolve_user(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        sb = get_supabase()
        resp = sb.table("conversations").update({"title": title, "updated_at": "now()"}).eq("id", conv_id).eq("user_id", user_id).execute()
        return resp.data[0] if resp.data else None
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Export conversation ──
@app.get("/api/conversations/{conv_id}/export")
async def export_conversation(conv_id: str, fmt: str = "json", authorization: str = Header(None)):
    user_id = await resolve_user(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        sb = get_supabase()
        conv = sb.table("conversations").select("*").eq("id", conv_id).eq("user_id", user_id).execute()
        if not conv.data:
            raise HTTPException(status_code=404, detail="Conversation not found")
        msgs = sb.table("messages").select("*").eq("conversation_id", conv_id).order("created_at").execute()
        if fmt == "json":
            return JSONResponse({"conversation": conv.data[0], "messages": msgs.data})
        else:
            lines = [f"# {conv.data[0]['title']}\n"]
            for m in msgs.data:
                role = "You" if m["role"] == "user" else "Apex AI"
                lines.append(f"## {role}\n{m['content']}\n")
            return PlainTextResponse("\n".join(lines), media_type="text/markdown")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Messages ──
@app.get("/api/conversations/{conv_id}/messages")
async def list_messages(conv_id: str, authorization: str = Header(None)):
    user_id = await resolve_user(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        sb = get_supabase()
        resp = sb.table("messages").select("*").eq("conversation_id", conv_id).eq("user_id", user_id).order("created_at").execute()
        return resp.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/conversations/{conv_id}/messages")
async def add_message(conv_id: str, role: str = Form(...), content: str = Form(...), msg_type: str = "text", sources: Optional[str] = Form(None), authorization: str = Header(None)):
    user_id = await resolve_user(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        sb = get_supabase()
        payload = {"conversation_id": conv_id, "user_id": user_id, "role": role, "content": content, "type": msg_type}
        if sources:
            payload["sources"] = sources
        resp = sb.table("messages").insert(payload).execute()
        sb.table("conversations").update({"updated_at": "now()"}).eq("id", conv_id).execute()
        return resp.data[0] if resp.data else None
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Sync ──
class SyncConversation(BaseModel):
    id: str
    title: str
    messages: List[Dict[str, Any]]

@app.post("/api/conversations/sync")
async def sync_conversations(conversations: List[SyncConversation], authorization: str = Header(None)):
    user_id = await resolve_user(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        sb = get_supabase()
        for conv in conversations:
            existing = sb.table("conversations").select("id").eq("id", conv.id).eq("user_id", user_id).execute()
            if existing.data:
                sb.table("conversations").update({"title": conv.title, "updated_at": "now()"}).eq("id", conv.id).execute()
            else:
                sb.table("conversations").insert({"id": conv.id, "user_id": user_id, "title": conv.title}).execute()
            for msg in conv.messages:
                sb.table("messages").insert({"conversation_id": conv.id, "user_id": user_id, "role": msg.get("role", "user"), "content": msg.get("content", ""), "type": msg.get("type", "text")}).execute()
        return {"synced": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Chat ──
@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    if not rate_limiter.check(f"chat:{request.session_id}"):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again shortly.")
    try:
        if not agent:
            raise HTTPException(status_code=503, detail="Backend not initialized")

        cache_key = get_cache_key(request.query, request.session_id)
        cached = get_cached(cache_key)
        if cached and not request.messages:
            return ChatResponse(**cached, session_id=request.session_id)

        result = agent.process(request.query, request.session_id, request.context, request.messages)
        resp = ChatResponse(
            content=result.get("content", ""),
            type=result.get("type", "chat"),
            sources=result.get("sources", []),
            analysis=result.get("analysis"),
            session_id=request.session_id,
            image_url=result.get("image_url"),
            image_base64=result.get("image_base64"),
            video_url=result.get("video_url"),
            audio_url=result.get("audio_url"),
        )
        if not request.messages:
            set_cache(cache_key, resp.model_dump())
        return resp
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    if not rate_limiter.check(f"stream:{request.session_id}"):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    try:
        if not agent:
            raise HTTPException(status_code=503, detail="Backend not initialized")

        result = agent.process(request.query, request.session_id, request.context, request.messages)
        content = result.get("content", "")

        async def event_generator():
            try:
                chunk_size = 20
                for i in range(0, len(content), chunk_size):
                    chunk = content[i:i + chunk_size]
                    yield f"data: {json.dumps({'chunk': chunk, 'type': result.get('type', 'chat')})}\n\n"
                yield f"data: {json.dumps({'complete': True, 'result': {'content': content, 'type': result.get('type', 'chat'), 'sources': result.get('sources', []), 'analysis': result.get('analysis')}})}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
        return StreamingResponse(event_generator(), media_type="text/event-stream")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Feedback ──
class FeedbackRequest(BaseModel):
    message_id: str
    rating: int
    comment: Optional[str] = None

@app.post("/api/feedback")
async def submit_feedback(fb: FeedbackRequest, authorization: str = Header(None)):
    user_id = await resolve_user(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        sb = get_supabase()
        sb.table("feedback").insert({"user_id": user_id, "message_id": fb.message_id, "rating": fb.rating, "comment": fb.comment}).execute()
        return {"submitted": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Images ──
ANALYSIS_PROMPTS = {
    "analyze": "Analyze this image in detail. Describe what you see including objects, people, scenes, colors, composition, and any notable features.",
    "search": "Identify what is shown in this image. If it's an object, plant, animal, landmark, product, or place, name it and provide detailed information.",
    "detect": "Detect and list all objects visible in this image. For each object, describe its approximate location and attributes.",
    "translate": "Extract all text visible in this image and translate it to English. Show both the original text and the translation.",
    "health": "Analyze this image for any health-related indicators. Describe what you see from a medical perspective. WARNING: This is not medical advice.",
    "text": "Extract all text visible in this image with high accuracy. Preserve the original formatting as much as possible.",
    "product": "Identify this product in detail. Describe its brand, type, packaging, and any visible labels or ingredients.",
}

@app.post("/api/image/generate", response_model=ImageGenerateResponse)
async def generate_image(request: ImageGenerateRequest):
    try:
        if not agent:
            raise HTTPException(status_code=503, detail="Backend not initialized")
        final_prompt = request.prompt
        if request.style and request.style != "Auto":
            final_prompt = f"{request.prompt}, {request.style} style"
        result = agent.generate_image(final_prompt)
        image_base64 = None
        if result.get("content"):
            image_base64 = base64.b64encode(result["content"]).decode("utf-8")
        return ImageGenerateResponse(image_base64=image_base64, error=result.get("error"), prompt=final_prompt)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/image/qr-code")
async def generate_qr_code(request: dict):
    try:
        import qrcode
        data = request.get("data", "")
        size = request.get("size", 10)
        if not data:
            raise HTTPException(status_code=400, detail="No data provided for QR code")
        qr = qrcode.QRCode(version=1, box_size=size, border=4)
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        img_bytes = buf.getvalue()
        image_base64 = base64.b64encode(img_bytes).decode("utf-8")
        return JSONResponse({"image_base64": f"data:image/png;base64,{image_base64}", "prompt": data, "type": "qr_code"})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/image/redesign")
async def redesign_image(prompt: str = Form(...), file: UploadFile = File(...)):
    try:
        if not agent:
            raise HTTPException(status_code=503, detail="Backend not initialized")
        contents = await file.read()
        if len(contents) < 100:
            raise HTTPException(status_code=400, detail="Invalid or empty image")
        pil_image = Image.open(BytesIO(contents)).convert("RGB")
        result = agent.redesign_image(pil_image, prompt)
        image_base64 = base64.b64encode(result["content"]).decode("utf-8") if result.get("content") else None
        return JSONResponse({"image_base64": image_base64, "error": result.get("error"), "prompt": prompt, "type": "image_redesign"})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/image/analyze")
async def analyze_image(file: UploadFile = File(...), session_id: str = "default", analysis_type: str = "analyze", messages: Optional[str] = Form(None)):
    try:
        if not agent:
            raise HTTPException(status_code=503, detail="Backend not initialized")
        contents = await file.read()
        pil_image = Image.open(BytesIO(contents))
        prompt = ANALYSIS_PROMPTS.get(analysis_type, ANALYSIS_PROMPTS["analyze"])
        parsed_messages = json.loads(messages) if messages else None
        qr_result = core.vision._scan_qr(pil_image) if core and core.vision else None
        result = agent.process_with_image(prompt, pil_image, session_id, messages=parsed_messages)
        response = {"content": result.get("content", ""), "type": result.get("type", "image_analysis"), "sources": result.get("sources", []), "analysis": result.get("analysis"), "objects": result.get("objects", [])}
        if qr_result:
            response["qr_code"] = qr_result
        return JSONResponse(response)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/image/analysis-options")
async def image_analysis_options():
    return {"options": [{"id": k, "label": v.split(".")[0].replace("_", " ").title(), "icon": "eye", "desc": v.split(".")[0][:60]} for k, v in ANALYSIS_PROMPTS.items()]}

# ── Voice ──
@app.post("/api/voice/transcribe")
async def transcribe_voice(file: UploadFile = File(...)):
    try:
        if not core or not core.voice:
            raise HTTPException(status_code=503, detail="Voice service not available")
        contents = await file.read()
        if len(contents) < 100:
            raise HTTPException(status_code=400, detail="Audio file too small or empty")
        filename = file.filename or "recording.wav"
        ext = os.path.splitext(filename)[1].lower()
        if ext not in (".wav", ".mp3", ".mp4", ".m4a", ".ogg", ".webm", ".flac"):
            ext = ".wav"
        print(f"[APEX] Transcribing audio: {len(contents)} bytes, format: {ext}")
        text = core.voice.transcribe_bytes(contents, ext)
        if not text:
            return JSONResponse({"text": "", "type": "voice_input", "warning": "Could not transcribe audio. Please speak clearly and try again."})
        print(f"[APEX] Transcription result: {text[:100]}...")
        return JSONResponse({"text": text, "type": "voice_input"})
    except HTTPException:
        raise
    except Exception as e:
        print(f"[APEX] Voice transcription error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ── Models / Status ──
@app.get("/api/models/list", response_model=List[ModelInfo])
async def list_models():
    try:
        if not core:
            return []
        models = core.llm.list_models() or []
        return [ModelInfo(name=m, type="llm") for m in models]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/status")
async def get_status():
    try:
        llm_ok = core and core.llm and (
            core.llm.ollama_session is not None
            or core.llm._openai_client is not None
            or core.llm._anthropic_client is not None
        )
        return JSONResponse({
            "status": "ready", "llm_connected": llm_ok,
            "voice_available": core and core.voice is not None,
            "models": core.llm.list_models() if core else []
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/config")
async def get_config():
    llm_ok = core and core.llm and (
        core.llm.ollama_session is not None
        or core.llm._openai_client is not None
        or core.llm._anthropic_client is not None
    )
    return {
        "status": "running", "configured": llm_ok or neural is not None,
        "chat": llm_ok, "image_generation": True, "voice": False,
        "image_analysis": llm_ok,
        "suggestions": [
            {"query": "Explain quantum computing in simple terms", "title": "Explain", "desc": "Learn anything", "icon": "book"},
            {"query": "Write a Python function to merge two sorted lists", "title": "Write Code", "desc": "Generate code", "icon": "code"},
            {"query": "What is SaaS and how do startups build it?", "title": "Compare", "desc": "Get explanations", "icon": "search"},
            {"query": "Create a serene mountain landscape at sunset with vibrant colors", "title": "Create Image", "desc": "Generate AI images", "icon": "image"},
        ] if llm_ok else [],
        "tools": {"web_search": llm_ok, "code_execution": True, "document_processing": True, "tts": False},
        "version": "2.0.0",
    }

# ── Runtime LLM Configuration ──
class LLMConfigUpdate(BaseModel):
    provider: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    api_url: Optional[str] = None

@app.post("/api/config/llm")
async def update_llm_config(cfg: LLMConfigUpdate):
    try:
        if not core:
            raise HTTPException(status_code=503, detail="Backend not initialized")
        if cfg.api_key:
            os.environ["APEX_LLM_API_KEY"] = cfg.api_key
            core.config.LLM_API_KEY = cfg.api_key
        if cfg.provider:
            os.environ["APEX_LLM_PROVIDER"] = cfg.provider
            core.config.LLM_PROVIDER = cfg.provider
        if cfg.model:
            os.environ["APEX_LLM_MODEL"] = cfg.model
            core.config.LLM_MODEL = cfg.model
        if cfg.api_url:
            os.environ["APEX_LLM_API_URL"] = cfg.api_url
            core.config.LLM_API_URL = cfg.api_url
        core.llm._init_cloud()
        return {"status": "ok", "provider": core.config.LLM_PROVIDER, "model": core.config.LLM_MODEL, "available_models": core.llm.list_models()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/config/llm")
async def get_llm_config():
    try:
        if not core:
            raise HTTPException(status_code=503, detail="Backend not initialized")
        return {
            "provider": core.config.LLM_PROVIDER,
            "model": core.config.LLM_MODEL,
            "api_key_set": bool(core.config.LLM_API_KEY),
            "api_url": core.config.LLM_API_URL or "",
            "available_models": core.llm.list_models(),
            "backend": core.llm.backend,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Tools ──
@app.post("/api/tools/search")
async def tool_search(query: str = Form(...), max_results: int = 5):
    try:
        if not core or not core.search:
            raise HTTPException(status_code=503, detail="Search not available")
        results = core.search.search_with_content(query, max_results)
        return {"results": results, "query": query}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/tools/process-document")
async def tool_process_document(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        text = contents.decode("utf-8", errors="replace")
        return {"text": text, "type": "text", "filename": file.filename or "document", "total_chars": len(text)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── Error handlers ──
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    print(f"[APEX] Unhandled error: {exc}")
    import traceback
    traceback.print_exc()
    return JSONResponse(status_code=500, content={"error": f"Internal server error: {str(exc)}"})

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("APEX_API_PORT", 8000))
    print(f"\n[APEX] Server: http://localhost:{port} | Docs: http://localhost:{port}/docs\n")
    uvicorn.run(app, host="0.0.0.0", port=port)
