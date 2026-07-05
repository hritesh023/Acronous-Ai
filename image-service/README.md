# Acronous AI Image Editing Service

## Deploy to Hugging Face Spaces (Free GPU)

1. Go to https://huggingface.co/new-space
2. Set Space name: `acronous-image-service`
3. Set License: `mit`
4. Set SDK: `Docker`
5. Set Space hardware: `CPU basic` (free) or `T4 small` (for GPU, ~$0.60/hr)

### Option A: Deploy via Git
```bash
cd image-service
git init
git add .
git commit -m "Initial"
git remote add space https://huggingface.co/spaces/YOUR_USER/acronous-image-service
git push space main
```

### Option B: Deploy via HF API
```bash
# Install huggingface-hub
pip install huggingface-hub

# Upload
huggingface-cli upload YOUR_USER/acronous-image-service .
```

## Environment Variables
- `HF_API_TOKEN` - Optional, for higher rate limits on HF Inference API
- No other vars needed for CPU mode

## Local Test
```bash
pip install -r requirements.txt
python app.py
# Server runs on http://localhost:7860
# Test: curl http://localhost:7860/health
```

## API Endpoints
- `GET /health` - Health check
- `POST /edit` - Edit image with prompt (multipart: file + prompt)
- `POST /segment` - Get segmentation mask (multipart: file + target)
- `POST /remove-bg` - Remove background
