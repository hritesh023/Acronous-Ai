import base64
import re
import tempfile
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"

class ChatResponse(BaseModel):
    response: str
    session_id: str
    type: str = "chat"
    image_data: str = ""
    image_type: str = ""

class ImageGenRequest(BaseModel):
    prompt: str
    session_id: str = "default"

@app.get("/")
async def root():
    return {"name": "Acronous AI API", "version": "1.0.0"}

@app.get("/v1/health")
async def health():
    return {"status": "ok"}

@app.post("/v1/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    try:
        query_embedding = core_engine.embedder.embed(req.message)
        neural_engine.learn(query_embedding, feedback=0.5)

        result = agent_engine.process(req.message, req.session_id)

        if result and isinstance(result, dict):
            content = result.get("content", "")
            neural_engine.learn(query_embedding, feedback=1.0)
            resp_type = result.get("type", "chat")
            image_data = result.get("image_data", "")
            image_type = result.get("image_type", "")
            return ChatResponse(
                response=content,
                session_id=req.session_id,
                type=resp_type,
                image_data=image_data,
                image_type=image_type,
            )

        return ChatResponse(
            response=str(result) if result else "",
            session_id=req.session_id,
        )
    except Exception as e:
        return ChatResponse(
            response=f"{e!s}",
            session_id=req.session_id,
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
        return ChatResponse(
            response=f"{e!s}",
            session_id=session_id,
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
        return ChatResponse(
            response=f"{e!s}",
            session_id=session_id,
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
    result = agent_engine.generate_image(prompt)
    if result.get("type") == "error":
        return JSONResponse(
            content={
                "response": result.get("content", ""),
                "session_id": session_id,
                "type": "error",
            },
            status_code=500,
        )
    image_data = result.get("image_data", "")
    if not image_data:
        return JSONResponse(
            content={"response": "", "session_id": session_id, "type": "error"},
            status_code=500,
        )
    image_bytes = base64.b64decode(image_data)
    return Response(content=image_bytes, media_type="image/png")

@app.post("/v1/image/generate")
async def generate_image_post(req: ImageGenRequest):
    if not req.prompt:
        return JSONResponse(
            content={"response": "", "session_id": req.session_id, "type": "error"},
            status_code=400,
        )
    result = agent_engine.generate_image(req.prompt)
    if result.get("type") == "error":
        return JSONResponse(
            content={
                "response": result.get("content", ""),
                "session_id": req.session_id,
                "type": "error",
            },
            status_code=500,
        )
    image_data = result.get("image_data", "")
    if not image_data:
        return JSONResponse(
            content={"response": "", "session_id": req.session_id, "type": "error"},
            status_code=500,
        )
    image_bytes = base64.b64decode(image_data)
    return Response(content=image_bytes, media_type="image/png")

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

        query = core_engine.llm.generate(
            f"The user wants to edit an uploaded image. Describe what edit they want in a concise way for the image editing system.\n\nUser request: {message}\n\nIf the user just says 'edit this image' or similar generic request without specifics, respond with exactly: 'edit this image'\nOtherwise, extract the specific edit request concisely.\n\nEdit description:",
            system_prompt="You extract image edit descriptions. Be concise.",
        )
        edit_query = query.strip().strip('"').strip("'")

        result = agent_engine.modify_image(edit_query, str(temp_path))
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
        return ChatResponse(
            response=f"{e!s}",
            session_id=session_id,
        )
    finally:
        if temp_path.exists():
            temp_path.unlink()

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

    base_url = f"http://{args.host}:{port}"
    print("=" * 50)
    print("  Acronous AI Server")
    print(f"  URL: {base_url}")
    print(f"  Health: {base_url}/v1/health")
    print(f"  Chat:   {base_url}/v1/chat")
    print(f"  Image:  {base_url}/v1/image/generate")
    print("=" * 50)
    uvicorn.run(app, host=args.host, port=port, log_level="info")
