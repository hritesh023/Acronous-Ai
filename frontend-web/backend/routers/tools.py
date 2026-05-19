from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query
from pydantic import BaseModel
from typing import Optional
import logging

from services.tools import web_search, format_search_results, execute_code, format_code_result, process_document

logger = logging.getLogger(__name__)
router = APIRouter()


class SearchRequest(BaseModel):
    query: str
    max_results: int = 5


class SearchResult(BaseModel):
    title: str
    link: str
    snippet: str


class SearchResponse(BaseModel):
    results: list[SearchResult]
    formatted: str
    query: str


@router.post("/tools/search", response_model=SearchResponse)
async def search_web(request: SearchRequest):
    try:
        results = await web_search(request.query, request.max_results)
        formatted = format_search_results(results)
        return SearchResponse(
            results=[SearchResult(**r) for r in results],
            formatted=formatted,
            query=request.query,
        )
    except Exception as e:
        logger.error(f"Search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class ExecuteRequest(BaseModel):
    code: str
    language: str = "python"
    timeout: int = 15


class ExecuteResponse(BaseModel):
    output: str
    error: Optional[str] = None
    exit_code: int


@router.post("/tools/execute", response_model=ExecuteResponse)
async def run_code(request: ExecuteRequest):
    try:
        result = await execute_code(request.code, request.language, request.timeout)
        return ExecuteResponse(
            output=result.get("output", ""),
            error=result.get("error"),
            exit_code=result.get("exit_code", 0),
        )
    except Exception as e:
        logger.error(f"Code execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class DocumentResponse(BaseModel):
    text: str
    type: str
    filename: str
    total_chars: Optional[int] = None


@router.post("/tools/process-document", response_model=DocumentResponse)
async def process_document_endpoint(file: UploadFile = File(...)):
    try:
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Empty file")
        result = await process_document(file_bytes, file.filename or "document")
        return DocumentResponse(
            text=result.get("text", ""),
            type=result.get("type", "document"),
            filename=result.get("filename", file.filename or "document"),
            total_chars=result.get("total_chars"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Document processing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
