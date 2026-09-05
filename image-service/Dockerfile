FROM python:3.11-slim

WORKDIR /app

# Install ffmpeg for audio/video processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Install the CPU-only torch wheel (no CUDA) first; diffusers needs it.
RUN pip install --no-cache-dir torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

# Bake the distilled (1-2 step) Stable Diffusion Turbo weights into the image
# so generation is a few seconds on CPU, with NO runtime download. Pre-warmed
# at startup — never sleeps.
ENV HF_HOME=/app/.cache/huggingface
RUN python -c "from diffusers import StableDiffusionPipeline, StableDiffusionImg2ImgPipeline; StableDiffusionPipeline.from_pretrained('stabilityai/sd-turbo', safety_checker=None, requires_safety_checker=False); StableDiffusionImg2ImgPipeline.from_pretrained('stabilityai/sd-turbo', safety_checker=None, requires_safety_checker=False); print('SD weights cached')"

COPY . .

EXPOSE 7860

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
