import os, sys
from huggingface_hub import snapshot_download

models = [
    "TinyLlama/TinyLlama-1.1B-Chat-v1.0",
    "sentence-transformers/all-MiniLM-L6-v2",
    os.getenv("ACRONOUS_DIFFUSERS_MODEL", "Lykon/dreamshaper-8"),
    os.getenv("ACRONOUS_VISION_MODEL", "google/vit-base-patch16-224"),
]

for model in models:
    if model:
        print(f"Downloading {model}...")
        try:
            snapshot_download(repo_id=model, ignore_patterns=["*.safetensors", "*.bin", "*.onnx"])
        except Exception:
            pass

print("Models cached")
