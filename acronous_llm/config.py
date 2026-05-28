import os
import json
from pathlib import Path

class AcronousConfig:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        self.ROOT_DIR = Path(__file__).parent.parent
        self.DATA_DIR = self.ROOT_DIR / "data"
        self.MODELS_DIR = self.DATA_DIR / "models"
        self.DB_PATH = self.DATA_DIR / "memory.db"
        self.CLUSTER_PATH = self.MODELS_DIR / "clusters.npz"
        self.CLASSIFIER_PATH = self.MODELS_DIR / "classifier.pt"
        self.EMBEDDER_PATH = self.MODELS_DIR / "embedder.pt"

        self.LLM_MODEL = os.getenv("ACRONOUS_LLM_MODEL", "gpt-4o-mini")
        self.LLM_BACKEND = os.getenv("ACRONOUS_LLM_BACKEND", "auto")
        self.LLM_PROVIDER = os.getenv("ACRONOUS_LLM_PROVIDER", "openai")
        self.LLM_API_KEY = os.getenv("ACRONOUS_LLM_API_KEY", "")
        self.LLM_API_URL = os.getenv("ACRONOUS_LLM_API_URL", "")
        self.EMBED_MODEL = os.getenv("ACRONOUS_EMBED_MODEL", "all-MiniLM-L6-v2")
        self.VISION_MODEL = os.getenv("ACRONOUS_VISION_MODEL", "microsoft/resnet-50")
        self.STT_MODEL = os.getenv("ACRONOUS_STT_MODEL", "base")
        self.SEARCH_PROVIDER = os.getenv("ACRONOUS_SEARCH", "duckduckgo")
        self.SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")

        self.MAX_HISTORY = 50
        self.CLUSTER_COUNT = 8
        self.EMBED_DIM = 384
        self.LEARNING_RATE = 0.001
        self.MEMORY_MODE = os.getenv("ACRONOUS_MEMORY", "sqlite")
        self.TEMPERATURE = 0.7
        self.MAX_TOKENS = 2048
        self.ENABLE_WEB = os.getenv("ACRONOUS_ENABLE_WEB", "true").lower() == "true"
        self.ENABLE_VISION = os.getenv("ACRONOUS_ENABLE_VISION", "false").lower() == "true"
        self.ENABLE_VOICE = os.getenv("ACRONOUS_ENABLE_VOICE", "false").lower() == "true"
        self.SYSTEM_PROMPT = os.getenv("ACRONOUS_SYSTEM_PROMPT", "")

        self.DEVICE = os.getenv("ACRONOUS_DEVICE", "")
        if not self.DEVICE:
            try:
                import torch
                self.DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                self.DEVICE = "cpu"
        self.OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
        self.LANG = "en"

        self.IMAGE_STEPS = int(os.getenv("ACRONOUS_IMAGE_STEPS", "50"))
        self.IMAGE_GUIDANCE_SCALE = float(os.getenv("ACRONOUS_IMAGE_GUIDANCE_SCALE", "8.0"))
        self.IMAGE_HEIGHT = int(os.getenv("ACRONOUS_IMAGE_HEIGHT", "1024"))
        self.IMAGE_WIDTH = int(os.getenv("ACRONOUS_IMAGE_WIDTH", "1024"))
        self.IMAGE_SHARPEN_FACTOR = float(os.getenv("ACRONOUS_IMAGE_SHARPEN_FACTOR", "1.6"))
        self.IMAGE_CONTRAST_FACTOR = float(os.getenv("ACRONOUS_IMAGE_CONTRAST_FACTOR", "1.2"))
        self.IMAGE_COLOR_FACTOR = float(os.getenv("ACRONOUS_IMAGE_COLOR_FACTOR", "1.08"))

        # Postprocessing / natural image enhancement parameters
        self.IMAGE_DENOISE_ITERATIONS = int(os.getenv("ACRONOUS_IMAGE_DENOISE_ITERATIONS", "2"))
        self.IMAGE_UNSHARP_RADIUS = int(os.getenv("ACRONOUS_IMAGE_UNSHARP_RADIUS", "3"))
        self.IMAGE_UNSHARP_PERCENT = int(os.getenv("ACRONOUS_IMAGE_UNSHARP_PERCENT", "180"))
        self.IMAGE_UNSHARP_THRESHOLD = int(os.getenv("ACRONOUS_IMAGE_UNSHARP_THRESHOLD", "1"))
        self.IMAGE_AUTO_CONTRAST_CUTOFF = float(os.getenv("ACRONOUS_IMAGE_AUTO_CONTRAST_CUTOFF", "0.005"))
        self.IMAGE_DETAIL_ENHANCE_STRENGTH = float(os.getenv("ACRONOUS_IMAGE_DETAIL_ENHANCE_STRENGTH", "0.4"))

    def load_env_file(self):
        env_path = self.ROOT_DIR / ".env"
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip())
            self._init()

    def save(self):
        os.makedirs(self.MODELS_DIR, exist_ok=True)
        os.makedirs(self.DATA_DIR, exist_ok=True)
