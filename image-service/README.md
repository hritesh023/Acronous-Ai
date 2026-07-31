# Acronous AI Image Editing Service

## Deploy to Oracle Cloud (Recommended)

See `oracle-cloud/DEPLOYMENT.md` for full Docker Compose setup on Oracle Cloud.

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
