import os
from huggingface_hub import snapshot_download

models = [
    "TinyLlama/TinyLlama-1.1B-Chat-v1.0",
    "sentence-transformers/all-MiniLM-L6-v2",
    os.getenv("ACRONOUS_DIFFUSERS_MODEL", "Lykon/dreamshaper-8"),
    os.getenv("ACRONOUS_VISION_MODEL", "microsoft/resnet-50"),
]

for model in models:
    if model:
        print(f"Downloading {model}...")
        try:
            snapshot_download(repo_id=model)
            print(f"  {model} downloaded")
        except Exception as e:
            print(f"  Failed to download {model}: {e}")

print("Models cached")
