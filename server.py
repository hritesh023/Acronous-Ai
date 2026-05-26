import asyncio
import base64
import json
import logging
import os
import re
import tempfile
import uuid
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from acronous_llm.agents import AcronousAgentEngine
from acronous_llm.config import AcronousConfig
from acronous_llm.core import AcronousCoreEngine
from acronous_llm.neural import AcronousNeuralEngine

config = AcronousConfig()
config.load_env_file()

neural_engine = AcronousNeuralEngine(config)
core_engine = AcronousCoreEngine(config)
agent_engine = AcronousAgentEngine(neural_engine, core_engine)

app = FastAPI(title="Acronous AI API", version="1.0.0")

LLM_ERROR_MSG = "I'm having trouble connecting to my language model backend. Please make sure Ollama is running (check 'ollama serve') or that your API key is configured correctly."
LLM_EMPTY_MSG = "The AI model returned an empty response. This can happen if the model is still loading, or if there's a configuration issue. Please try again in a moment, or check your LLM backend settings."
GENERIC_ERROR_MSG = "I'm sorry, I encountered an issue while processing your request. Please try again, and if the problem persists, check that your server is running properly."

def _safe_error(e: Exception, fallback: str = "") -> str:
    """Return a safe, user-friendly error message without leaking backend internals."""
    if fallback:
        return fallback
    
    err_str = str(e).lower()
    err_full = str(e)
    
    if any(kw in err_str for kw in ["ollama", "connect", "refused", "connection", "no language model", "no model", "backend"]):
        return LLM_ERROR_MSG
    
    if any(kw in err_str for kw in ["empty", "no response", "none", "returned empty"]):
        return LLM_EMPTY_MSG
    
    if any(kw in err_str for kw in ["timeout", "timed out", "too long", "timedout"]):
        return "The request took too long to process. Please try again with a simpler query, or check if your server and LLM backend are responding."
    
    if any(kw in err_str for kw in ["api key", "apikey", "authentication", "unauthorized", "auth"]):
        return "There's an issue with your API key configuration. Please check that your LLM provider API key is correctly set in the environment variables."
    
    if any(kw in err_str for kw in ["not found", "404", "model not found"]):
        return "The specified AI model was not found. Please check your model configuration and ensure the model is available (e.g., pulled in Ollama or accessible via your API provider)."
    
    if any(kw in err_str for kw in ["cuda", "gpu", "memory", "out of memory", "ram"]):
        return "There was a resource issue. The AI model may need more memory. Please try a smaller model or reduce the query complexity."
    
    if any(kw in err_str for kw in ["import", "module", "dependency", "no module"]):
        return "A required software component is missing. Please ensure all Python dependencies are installed correctly."
    
    user_msg = err_full[:150] if len(err_full) > 150 else err_full
    if user_msg.strip():
        return f"I encountered an issue: {user_msg}. Please try again, or check your server configuration and LLM backend."
    
    return GENERIC_ERROR_MSG

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_KEEP_ALIVE_URL = os.getenv("ACRONOUS_KEEP_ALIVE_URL", "")

async def _keep_alive_loop():
    """Self-ping to prevent HF Space idle sleep."""
    if not _KEEP_ALIVE_URL:
        return
    import requests
    while True:
        try:
            await asyncio.to_thread(requests.get, f"{_KEEP_ALIVE_URL}/v1/health", timeout=10)
        except Exception:
            pass
        await asyncio.sleep(240)

@app.on_event("startup")
async def startup_check():
    logger.info(f"LLM backend: {config.LLM_BACKEND}, model: {config.LLM_MODEL}")
    if _KEEP_ALIVE_URL:
        asyncio.create_task(_keep_alive_loop())
        logger.info(f"Keep-alive pinging {_KEEP_ALIVE_URL} every 4 minutes")
    if config.LLM_BACKEND == "ollama":
        try:
            import requests
            resp = requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=3)
            if resp.status_code == 200:
                models = [m["name"] for m in resp.json().get("models", [])]
                logger.info(f"Ollama available at {config.OLLAMA_URL}, models: {models}")
                if config.LLM_MODEL not in models:
                    logger.warning(f"Configured model '{config.LLM_MODEL}' not found in Ollama. Available: {models}")
            else:
                logger.warning(f"Ollama responded with status {resp.status_code}")
        except Exception as e:
            logger.warning(f"Ollama not reachable at {config.OLLAMA_URL}: {e}")
            logger.warning("Make sure Ollama is running. Chat requests will fail until it's available.")
    elif config.LLM_BACKEND in ("openai", "groq", "together", "anthropic"):
        if not config.LLM_API_KEY:
            logger.warning(f"LLM backend set to '{config.LLM_BACKEND}' but no API key configured. Set ACRONOUS_LLM_API_KEY in .env.")
        logger.info(f"Using cloud LLM provider: {config.LLM_BACKEND}, model: {config.LLM_MODEL}")
    else:
        logger.info(f"LLM backend: {config.LLM_BACKEND} (no startup check available)")

class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"

class ChatResponse(BaseModel):
    response: str
    session_id: str
    type: str = "chat"
    image_data: str = ""
    image_type: str = ""
    complexity: int = 0
    complexity_label: str = "simple"

class ImageGenRequest(BaseModel):
    prompt: str
    session_id: str = "default"

@app.get("/")
async def root():
    return {"name": "Acronous AI API", "version": "1.0.0"}

@app.get("/v1/health")
async def health():
    return {"status": "ok"}

@app.get("/v1/health/llm")
async def health_llm():
    """Check if LLM backend is available."""
    llm = core_engine.llm
    available = (
        llm._model_loaded or
        (hasattr(llm, 'ollama_session') and llm.ollama_session is not None) or
        (hasattr(llm, '_openai_client') and llm._openai_client is not None) or
        (hasattr(llm, '_anthropic_client') and llm._anthropic_client is not None)
    )
    if available:
        return {"status": "ok"}
    return JSONResponse(
        content={"status": "unavailable"},
        status_code=503,
    )

@app.post("/v1/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    try:
        result = await asyncio.to_thread(agent_engine.process, req.message, req.session_id)

        if result and isinstance(result, dict):
            content = result.get("content", "") or ""
            resp_type = result.get("type", "chat")
            image_data = result.get("image_data", "")
            image_type = result.get("image_type", "")
            if not content and not image_data and resp_type != "error":
                resp_type = "error"
                content = _safe_error(RuntimeError("Empty response from agent"))
            return ChatResponse(
                response=content,
                session_id=req.session_id,
                type=resp_type,
                image_data=image_data,
                image_type=image_type,
                complexity=result.get("complexity", 0),
                complexity_label=result.get("complexity_label", "simple"),
            )

        return ChatResponse(
            response=str(result) if result else "",
            session_id=req.session_id,
            type="error",
        )
    except Exception as e:
        logger.error(f"Error processing chat for session {req.session_id}: {type(e).__name__}: {e}", exc_info=True)
        return ChatResponse(
            response=_safe_error(e),
            session_id=req.session_id,
            type="error",
        )

@app.post("/v1/chat/stream")
async def chat_stream(req: ChatRequest):
    import queue
    import threading

    q = queue.Queue()

    def _produce():
        try:
            for chunk in agent_engine.process_stream(req.message, req.session_id):
                q.put(chunk)
        except Exception as e:
            logger.error(f"Stream produce error: {type(e).__name__}: {e}", exc_info=True)
            q.put(e)
        finally:
            q.put(None)

    thread = threading.Thread(target=_produce, daemon=True)
    thread.start()

    async def event_stream():
        try:
            loop = asyncio.get_event_loop()
            while True:
                item = await loop.run_in_executor(None, q.get)
                if item is None:
                    break
                if isinstance(item, Exception):
                    raise item
                yield f"data: {json.dumps({'content': item})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            logger.error(f"Stream event error: {type(e).__name__}: {e}", exc_info=True)
            yield f"data: {json.dumps({'error': _safe_error(e), 'done': True})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

def _safe_filename(filename: str | None) -> str:
    if not filename:
        return "upload"
    name = Path(filename).name
    name = re.sub(r"[^\w\.\-]", "_", name)
    return name or "upload"

@app.post("/v1/chat/image", response_model=ChatResponse)
async def chat_with_image(
    message: str = Form(""),
    session_id: str = Form("default"),
    file: UploadFile = File(...),
):
    tmp_dir = Path(tempfile.gettempdir())
    safe_name = _safe_filename(file.filename)
    temp_path = tmp_dir / f"acronous_{uuid.uuid4()}_{safe_name}"
    try:
        content = await file.read()
        temp_path.write_bytes(content)
        result = agent_engine.process_with_image(
            message, str(temp_path), session_id,
        )
        if result and isinstance(result, dict):
            response_text = result.get("content", "") or ""
            resp_type = result.get("type", "chat")
            image_data = result.get("image_data", "") or ""
            image_type = result.get("image_type", "") or ""
        else:
            response_text = ""
            resp_type = "error"
            image_data = ""
            image_type = ""
        return ChatResponse(
            response=response_text,
            session_id=session_id,
            type=resp_type,
            image_data=image_data,
            image_type=image_type,
        )
    except Exception as e:
        logger.error(f"Error processing image chat: {type(e).__name__}: {e}", exc_info=True)
        return ChatResponse(
            response=_safe_error(e),
            session_id=session_id,
            type="error",
        )
    finally:
        if temp_path.exists():
            temp_path.unlink()

@app.post("/v1/chat/file", response_model=ChatResponse)
async def chat_with_file(
    message: str = Form(""),
    session_id: str = Form("default"),
    file: UploadFile = File(...),
):
    tmp_dir = Path(tempfile.gettempdir())
    safe_name = _safe_filename(file.filename)
    temp_path = tmp_dir / f"acronous_{uuid.uuid4()}_{safe_name}"
    try:
        content = await file.read()
        temp_path.write_bytes(content)
        result = agent_engine.process_with_file(
            message, str(temp_path), session_id,
        )
        response_text = result.get("content", "")
        resp_type = result.get("type", "chat")
        image_data = result.get("image_data", "")
        image_type = result.get("image_type", "")
        return ChatResponse(
            response=response_text,
            session_id=session_id,
            type=resp_type,
            image_data=image_data,
            image_type=image_type,
        )
    except Exception as e:
        logger.error(f"Error processing file chat: {type(e).__name__}: {e}", exc_info=True)
        return ChatResponse(
            response=_safe_error(e),
            session_id=session_id,
            type="error",
        )
    finally:
        if temp_path.exists():
            temp_path.unlink()

@app.get("/v1/image/generate")
async def generate_image_get(prompt: str = "", session_id: str = "default"):
    if not prompt:
        return JSONResponse(
            content={"response": "", "session_id": session_id, "type": "error"},
            status_code=400,
        )
    try:
        result = agent_engine.generate_image(prompt, session_id)
    except Exception as e:
        logger.error(f"Image generation error: {type(e).__name__}: {e}", exc_info=True)
        return JSONResponse(
            content={"response": "", "session_id": session_id, "type": "error"},
            status_code=500,
        )
    if result.get("type") == "error":
        content = result.get("content", "")
        return JSONResponse(
            content={"response": content, "session_id": session_id, "type": "error"},
            status_code=500 if not content else 200,
        )
    image_data = result.get("image_data", "")
    if not image_data:
        content = result.get("content", "")
        return JSONResponse(
            content={"response": content, "session_id": session_id, "type": "error"},
            status_code=500,
        )
    image_bytes = base64.b64decode(image_data)
    return Response(content=image_bytes, media_type="image/png")

@app.post("/v1/image/generate")
async def generate_image_post(req: ImageGenRequest):
    if not req.prompt:
        return {
            "response": "",
            "session_id": req.session_id,
            "type": "error",
            "image_data": "",
        }
    result = await asyncio.to_thread(agent_engine.generate_image, req.prompt, req.session_id)
    content = result.get("content", "") or ""
    if result.get("type") == "error":
        return {
            "response": content,
            "session_id": req.session_id,
            "type": "error",
            "image_data": "",
        }
    image_data = result.get("image_data", "")
    if not image_data:
        return {
            "response": content,
            "session_id": req.session_id,
            "type": "error",
            "image_data": "",
        }
    return {
        "response": content,
        "image_data": image_data,
        "session_id": req.session_id,
        "type": "image_gen",
    }

@app.post("/v1/image/edit", response_model=ChatResponse)
async def edit_image(
    message: str = Form(""),
    session_id: str = Form("default"),
    file: UploadFile = File(...),
):
    tmp_dir = Path(tempfile.gettempdir())
    safe_name = _safe_filename(file.filename)
    temp_path = tmp_dir / f"acronous_edit_{uuid.uuid4()}_{safe_name}"
    try:
        content = await file.read()
        temp_path.write_bytes(content)

        if message and message.strip():
            query = core_engine.llm.generate(
                f"The user wants to edit an uploaded image. Describe what edit they want in a concise way for the image editing system.\n\nUser request: {message}\n\nIf the user just says 'edit this image' or similar generic request without specifics, respond with exactly: 'edit this image'\nOtherwise, extract the specific edit request concisely.\n\nEdit description:",
                system_prompt="You extract image edit descriptions. Be concise.",
            )
            edit_query = query.strip().strip('"').strip("'")
        else:
            edit_query = "edit this image"

        result = agent_engine.modify_image(edit_query, str(temp_path))
        response_text = result.get("content", "") or ""
        resp_type = result.get("type", "chat")
        image_data = result.get("image_data", "") or ""
        image_type = result.get("image_type", "") or ""

        return ChatResponse(
            response=response_text,
            session_id=session_id,
            type=resp_type,
            image_data=image_data,
            image_type=image_type,
        )
    except Exception as e:
        logger.error(f"Error editing image: {type(e).__name__}: {e}", exc_info=True)
        return ChatResponse(
            response=_safe_error(e),
            session_id=session_id,
            type="error",
        )
    finally:
        if temp_path.exists():
            temp_path.unlink()

# ── Additional API endpoints for Flutter client compatibility ─────────────

@app.get("/health")
async def health_legacy():
    return {"status": "ok"}

# ── /api/chat (alternative chat endpoint used by some Flutter methods) ──────

class ApiChatRequest(BaseModel):
    query: str
    session_id: str = "default"
    context: dict | None = None
    messages: list | None = None
    web_search_enabled: bool | None = None
    model: str | None = None

@app.post("/api/chat")
async def api_chat(req: ApiChatRequest):
    try:
        result = await asyncio.to_thread(agent_engine.process, req.query, req.session_id)
        if result and isinstance(result, dict):
            content = result.get("content", "") or ""
            resp_type = result.get("type", "chat")
            sources = result.get("sources", [])
            analysis = result.get("analysis")
            if not content and resp_type != "error":
                resp_type = "error"
                content = _safe_error(RuntimeError("Empty response from AI engine"))
            return {
                "content": content,
                "type": resp_type,
                "session_id": req.session_id,
                "sources": sources,
                "analysis": analysis,
            }
        return {"content": str(result) if result else _safe_error(RuntimeError("No response from server")), 
                "type": "error" if not result else "chat", 
                "session_id": req.session_id}
    except Exception as e:
        logger.error(f"Error in API chat for session {req.session_id}: {type(e).__name__}: {e}", exc_info=True)
        return {"content": _safe_error(e), "type": "error", "session_id": req.session_id}

# ── /api/image/qr-code ──────────────────────────────────────────────────────

class QRCodeRequest(BaseModel):
    data: str
    size: int = 256

@app.post("/api/image/qr-code")
async def generate_qr_code(req: QRCodeRequest):
    try:
        import qrcode
        from io import BytesIO
        qr = qrcode.QRCode(box_size=10, border=4)
        qr.add_data(req.data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        return {"image": b64, "format": "png"}
    except Exception as e:
        logger.error(f"QR generation failed: {e}")
        return JSONResponse(content={"error": "QR code generation failed. Please try again."}, status_code=500)

# ── /api/image/redesign ─────────────────────────────────────────────────────

@app.post("/api/image/redesign")
async def redesign_image(
    file: UploadFile = File(...),
    prompt: str = Form(""),
):
    tmp_dir = Path(tempfile.gettempdir())
    safe_name = _safe_filename(file.filename)
    temp_path = tmp_dir / f"acronous_redesign_{uuid.uuid4()}_{safe_name}"
    try:
        content = await file.read()
        temp_path.write_bytes(content)
        from PIL import Image
        image = Image.open(temp_path)
        img_bytes, error = core_engine.image_gen.redesign(image, prompt)
        if error:
            return {"content": None, "error": error}
        b64 = base64.b64encode(img_bytes).decode()
        return {"content": b64, "error": None, "prompt": prompt}
    except Exception as e:
        logger.error(f"Image redesign failed: {e}")
        return JSONResponse(content={"content": None, "error": "Image redesign failed. Please try again."}, status_code=500)
    finally:
        if temp_path.exists():
            temp_path.unlink()

# ── /api/image/analyze ──────────────────────────────────────────────────────

@app.post("/api/image/analyze")
async def analyze_image(
    file: UploadFile = File(...),
    session_id: str = Form("default"),
    messages: str = Form(""),
    analysis_type: str = Form(""),
):
    tmp_dir = Path(tempfile.gettempdir())
    safe_name = _safe_filename(file.filename)
    temp_path = tmp_dir / f"acronous_analyze_{uuid.uuid4()}_{safe_name}"
    try:
        content = await file.read()
        temp_path.write_bytes(content)
        from PIL import Image
        image = Image.open(temp_path)
        if core_engine.vision is not None:
            result = core_engine.vision.analyze_image(image)
            return {
                "content": json.dumps(result),
                "type": "analysis",
                "session_id": session_id,
            }
        return {
            "content": "I can't analyze this image right now — the vision system isn't loaded.",
            "type": "error",
            "session_id": session_id,
        }
    except Exception as e:
        logger.error(f"Image analysis failed: {e}")
        return {
            "content": "",
            "type": "error",
            "session_id": session_id,
        }
    finally:
        if temp_path.exists():
            temp_path.unlink()

# ── /api/tools/search ───────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str
    max_results: int = 5

@app.post("/api/tools/search")
async def web_search(req: SearchRequest):
    try:
        results = core_engine.search.search_with_content(req.query, req.max_results)
        return {"results": results}
    except Exception as e:
        logger.error(f"Web search failed: {e}")
        return JSONResponse(content={"error": "Search failed. Please try again.", "results": []}, status_code=500)

# ── /api/voice/transcribe ───────────────────────────────────────────────────

@app.post("/api/voice/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    tmp_dir = Path(tempfile.gettempdir())
    safe_name = _safe_filename(file.filename)
    temp_path = tmp_dir / f"acronous_audio_{uuid.uuid4()}_{safe_name}"
    try:
        content = await file.read()
        temp_path.write_bytes(content)
        if core_engine.voice is not None:
            text = core_engine.voice.transcribe(str(temp_path))
            return {"text": text}
        return {"text": "", "error": "Speech recognition isn't available right now."}
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        return {"text": "", "error": "Transcription failed. Please try again."}
    finally:
        if temp_path.exists():
            temp_path.unlink()

# ── /api/tools/process-document ─────────────────────────────────────────────

@app.post("/api/tools/process-document")
async def process_document(file: UploadFile = File(...)):
    tmp_dir = Path(tempfile.gettempdir())
    safe_name = _safe_filename(file.filename)
    temp_path = tmp_dir / f"acronous_doc_{uuid.uuid4()}_{safe_name}"
    try:
        content = await file.read()
        temp_path.write_bytes(content)
        ext = Path(file.filename or "").suffix.lower()
        text = ""
        if ext in (".txt", ".md", ".py", ".js", ".ts", ".html", ".css", ".json", ".xml", ".yaml", ".yml", ".csv"):
            text = content.decode("utf-8", errors="replace")
        elif ext == ".pdf":
            try:
                import pypdf
                reader = pypdf.PdfReader(str(temp_path))
                text = "\n".join(page.extract_text() or "" for page in reader.pages)
            except ImportError:
                text = "PDF processing requires pypdf library"
        elif ext in (".docx", ".doc"):
            try:
                import docx
                doc = docx.Document(str(temp_path))
                text = "\n".join(p.text for p in doc.paragraphs)
            except ImportError:
                text = "DOCX processing requires python-docx library"
        else:
            text = content.decode("utf-8", errors="replace")
        return {"text": text, "filename": file.filename, "size": len(content)}
    except Exception as e:
        logger.error(f"Document processing failed: {e}")
        return {"text": "", "error": "Document processing failed. Please try again."}
    finally:
        if temp_path.exists():
            temp_path.unlink()

# ── /api/models/list ────────────────────────────────────────────────────────

@app.get("/api/models/list")
async def list_models():
    models = [
        {"id": "default", "name": "Default", "provider": config.LLM_BACKEND or "auto", "backend": config.LLM_BACKEND or "auto"},
    ]
    if config.LLM_BACKEND == "ollama":
        try:
            import requests
            resp = requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=5)
            if resp.status_code == 200:
                ollama_models = resp.json().get("models", [])
                for m in ollama_models:
                    models.append({
                        "id": m["name"],
                        "name": m["name"],
                        "provider": "ollama",
                        "backend": "ollama",
                    })
        except Exception:
            pass
    return {"models": models}

# ── /api/status ─────────────────────────────────────────────────────────────

@app.get("/api/status")
async def api_status():
    return {
        "status": "running",
        "vision_enabled": core_engine.vision is not None,
        "voice_enabled": core_engine.voice is not None,
        "web_search_enabled": config.ENABLE_WEB,
    }

# ── /api/config ─────────────────────────────────────────────────────────────

@app.get("/api/config")
async def api_config():
    return {
        "enable_web": config.ENABLE_WEB,
        "enable_vision": config.ENABLE_VISION,
        "enable_voice": config.ENABLE_VOICE,
        "suggestions": [
            {"icon": "book", "title": "Learn Something", "desc": "Explain ML simply", "query": "Explain machine learning in simple terms"},
            {"icon": "code", "title": "Write Code", "desc": "Create a Python script", "query": "Write a Python script that scrapes a website"},
            {"icon": "image", "title": "Generate Art", "desc": "Draw a landscape", "query": "Draw a serene mountain landscape at sunset"},
            {"icon": "search", "title": "Research", "desc": "Latest AI news", "query": "What are the latest developments in artificial intelligence?"},
        ],
    }

@app.post("/api/config/llm")
async def update_llm_config(body: dict):
    provider = body.get("provider")
    api_key = body.get("api_key")
    model = body.get("model")
    api_url = body.get("api_url")
    if provider:
        os.environ["ACRONOUS_LLM_BACKEND"] = provider
        config.LLM_BACKEND = provider
    if api_key:
        os.environ["ACRONOUS_LLM_API_KEY"] = api_key
        config.LLM_API_KEY = api_key
    if model:
        os.environ["ACRONOUS_LLM_MODEL"] = model
        config.LLM_MODEL = model
    if api_url:
        os.environ["ACRONOUS_LLM_API_URL"] = api_url
        config.LLM_API_URL = api_url
    return {"status": "ok"}

@app.get("/api/config/llm")
async def get_llm_config():
    return {"status": "ok"}

# ── /api/auth/me ────────────────────────────────────────────────────────────

@app.get("/api/auth/me")
async def auth_me():
    return {
        "id": "local",
        "email": "local@acronous.ai",
        "name": "Local User",
        "provider": "local",
    }

# ── /api/conversations ──────────────────────────────────────────────────────

@app.get("/api/conversations")
async def list_conversations():
    try:
        sessions = core_engine.memory.get_all_sessions()
        convs = []
        for sid in sessions:
            convs.append({
                "id": sid,
                "title": f"Conversation {sid[:8]}",
                "created_at": "",
                "updated_at": "",
                "message_count": 0,
            })
        return {"conversations": convs}
    except Exception:
        return {"conversations": []}

@app.post("/api/conversations")
async def create_conversation(body: dict):
    session_id = str(uuid.uuid4())
    title = body.get("title", "New Conversation")
    return {
        "id": session_id,
        "title": title,
        "created_at": "",
        "updated_at": "",
    }

@app.delete("/api/conversations/{conv_id}")
async def delete_conversation(conv_id: str):
    try:
        core_engine.memory.clear_session(conv_id)
    except Exception:
        pass
    return {"status": "ok"}

@app.put("/api/conversations/{conv_id}")
async def update_conversation(conv_id: str, body: dict):
    title = body.get("title", "Conversation")
    return {"id": conv_id, "title": title, "status": "ok"}

@app.get("/api/conversations/{conv_id}/export")
async def export_conversation(conv_id: str, fmt: str = "markdown"):
    try:
        history = core_engine.memory.get_session_history(conv_id)
        lines = []
        for entry in history:
            role = entry.get("role", "user")
            content = entry.get("content", "")
            lines.append(f"**{role}**: {content}\n")
        return Response(content="\n".join(lines), media_type="text/markdown")
    except Exception:
        return Response(content="No messages", media_type="text/plain")

@app.get("/api/conversations/{conv_id}/messages")
async def list_messages(conv_id: str):
    try:
        history = core_engine.memory.get_session_history(conv_id)
        messages = []
        for i, entry in enumerate(history):
            messages.append({
                "id": f"msg_{i}",
                "role": entry.get("role", "user"),
                "content": entry.get("content", ""),
                "msg_type": "text",
                "created_at": entry.get("timestamp", ""),
            })
        return {"messages": messages}
    except Exception:
        return {"messages": []}

@app.post("/api/conversations/{conv_id}/messages")
async def add_message(conv_id: str, body: dict):
    role = body.get("role", "user")
    content = body.get("content", "")
    core_engine.memory.add(conv_id, role, content)
    return {"status": "ok", "id": f"msg_{uuid.uuid4().hex[:8]}"}

@app.post("/api/conversations/sync")
async def sync_conversations(body: dict):
    conversations = body.get("conversations", [])
    return {"status": "ok", "synced": len(conversations)}

# ── Main entry point ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import socket

    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    port = args.port
    while port < args.port + 100:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((args.host, port))
                break
            except OSError:
                port += 1
    else:
        print("Could not find an available port.")
        exit(1)

    display_host = "localhost" if args.host in ("0.0.0.0", "127.0.0.1") else args.host
    base_url = f"http://{display_host}:{port}"
    print("=" * 50)
    print("  Acronous AI Server")
    print(f"  URL: {base_url}")
    print(f"  Health: {base_url}/v1/health")
    print(f"  Chat:   {base_url}/v1/chat")
    print(f"  Image:  {base_url}/v1/image/generate")
    print(f"  API:    {base_url}/api/chat")
    print("=" * 50)
    uvicorn.run(app, host=args.host, port=port, log_level="info")
