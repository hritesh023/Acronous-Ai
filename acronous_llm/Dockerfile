FROM python:3.11-slim
WORKDIR /app
COPY . /app/acronous_llm/
RUN pip install --no-cache-dir fastapi uvicorn pydantic requests beautifulsoup4 lxml pillow numpy openai
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
ENV PYTHONPATH=/app
EXPOSE 9000
CMD ["uvicorn", "acronous_llm.server:app", "--host", "0.0.0.0", "--port", "9000", "--proxy-headers", "--forwarded-allow-ips", "*"]
