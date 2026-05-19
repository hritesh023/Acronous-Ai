import logging
import os
import httpx
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database.db import init_db
from routers import chat, image, voice, conversations, tools

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OLLAMA_BASE = os.environ.get("OLLAMA_BASE", "http://localhost:11434")
CHAT_MODEL = os.environ.get("OLLAMA_CHAT_MODEL", "llama3.2:1b")
VISION_MODEL = os.environ.get("OLLAMA_VISION_MODEL", "moondream")
POLLINATIONS_ENABLED = os.environ.get("POLLINATIONS_ENABLED", "true").lower() == "true"


async def check_ollama() -> bool:
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{OLLAMA_BASE}/api/tags")
            return r.status_code == 200
    except Exception:
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Apex AI backend server...")
    init_db()
    logger.info("Database initialized")
    yield
    logger.info("Shutting down...")


app = FastAPI(
    title="Apex AI Backend",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router, prefix="/api", tags=["Chat"])
app.include_router(image.router, prefix="/api", tags=["Image"])
app.include_router(voice.router, prefix="/api", tags=["Voice"])
app.include_router(conversations.router, prefix="/api", tags=["Conversations"])
app.include_router(tools.router, prefix="/api", tags=["Tools"])


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "version": "1.0.0"}


@app.get("/api/status")
async def get_status():
    ollama_ok = await check_ollama()
    return {
        "status": "running",
        "ollama_available": ollama_ok,
        "ollama_models": [CHAT_MODEL, VISION_MODEL] if ollama_ok else [],
        "chat_available": ollama_ok,
        "image_generation_available": POLLINATIONS_ENABLED,
        "voice_available": True,
        "image_analysis_available": ollama_ok,
        "provider": "ollama" if ollama_ok else "none",
    }


@app.get("/api/models/list")
async def list_models():
    ollama_ok = await check_ollama()
    models = []
    if ollama_ok:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"{OLLAMA_BASE}/api/tags")
                if r.status_code == 200:
                    data = r.json()
                    for m in data.get("models", []):
                        name = m.get("name", "")
                        size_bytes = m.get("size", 0)
                        size_gb = size_bytes / (1024**3)
                        size_str = f"{size_gb:.1f}GB" if size_gb > 1 else f"{size_gb*1024:.0f}MB"
                        model_type = "vision" if any(k in name.lower() for k in ("vision", "llava", "moondream", "bakllava")) else "chat"
                        models.append({"name": name, "type": model_type, "size": size_str})
        except Exception:
            models.extend([
                {"name": CHAT_MODEL, "type": "chat", "size": "local"},
                {"name": VISION_MODEL, "type": "vision", "size": "local"},
            ])
    if POLLINATIONS_ENABLED:
        models.append({"name": "Pollinations.ai", "type": "image", "size": "free"})
    return models


@app.get("/api/config")
async def get_config():
    ollama_ok = await check_ollama()
    return {
        "status": "running",
        "configured": ollama_ok or POLLINATIONS_ENABLED,
        "ollama_available": ollama_ok,
        "chat": ollama_ok,
        "image_generation": POLLINATIONS_ENABLED,
        "voice": True,
        "image_analysis": ollama_ok,
        "provider": "ollama" if ollama_ok else ("pollinations" if POLLINATIONS_ENABLED else "none"),
        "tools": {
            "web_search": ollama_ok,
            "code_execution": True,
            "document_processing": True,
            "tts": True,
            "qr_code": True,
        },
        "suggestions": [
            {"query": "Explain quantum computing in simple terms", "title": "Explain", "desc": "Learn anything", "icon": "book"},
            {"query": "Write a Python function to merge two sorted lists", "title": "Write Code", "desc": "Generate code", "icon": "code"},
            {"query": "What is the difference between REST and GraphQL?", "title": "Compare", "desc": "Get comparisons", "icon": "search"},
            {"query": "Create a serene mountain landscape at sunset with vibrant colors", "title": "Create Image", "desc": "Generate AI images", "icon": "image"},

        ],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
