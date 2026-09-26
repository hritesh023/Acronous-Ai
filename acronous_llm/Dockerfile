FROM python:3.11-slim
WORKDIR /app
# Dependencies FIRST so a code change only invalidates the COPY layer.
# (The reverse order reinstalled torch — ~2GB — on every single brain edit.)
# httpx is required for true token streaming: the openai SDK vendors its own
# http client as `httpx2` in this image, so `import httpx` fails without it.
# numpy backs the RAG vector index.
RUN pip install --no-cache-dir fastapi uvicorn pydantic requests beautifulsoup4 lxml pillow numpy httpx openai
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
COPY . /app/acronous_llm/
ENV PYTHONPATH=/app
EXPOSE 9000
CMD ["uvicorn", "acronous_llm.server:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
