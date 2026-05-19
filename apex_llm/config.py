import os
import json
from pathlib import Path

class ApexConfig:
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

        self.LLM_MODEL = os.getenv("APEX_LLM_MODEL", "gpt-4o-mini")
        self.LLM_BACKEND = os.getenv("APEX_LLM_BACKEND", "auto")
        self.LLM_PROVIDER = os.getenv("APEX_LLM_PROVIDER", "openai")
        self.LLM_API_KEY = os.getenv("APEX_LLM_API_KEY", "")
        self.LLM_API_URL = os.getenv("APEX_LLM_API_URL", "")
        self.EMBED_MODEL = os.getenv("APEX_EMBED_MODEL", "all-MiniLM-L6-v2")
        self.VISION_MODEL = os.getenv("APEX_VISION_MODEL", "google/vit-base-patch16-224")
        self.STT_MODEL = os.getenv("APEX_STT_MODEL", "base")
        self.SEARCH_PROVIDER = os.getenv("APEX_SEARCH", "duckduckgo")
        self.SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")

        self.MAX_HISTORY = 50
        self.CLUSTER_COUNT = 8
        self.EMBED_DIM = 384
        self.LEARNING_RATE = 0.001
        self.MEMORY_MODE = os.getenv("APEX_MEMORY", "sqlite")
        self.TEMPERATURE = 0.7
        self.MAX_TOKENS = 2048
        self.ENABLE_WEB = os.getenv("APEX_ENABLE_WEB", "true").lower() == "true"
        self.ENABLE_VISION = os.getenv("APEX_ENABLE_VISION", "true").lower() == "true"
        self.ENABLE_VOICE = os.getenv("APEX_ENABLE_VOICE", "false").lower() == "true"

        self.DEVICE = "cpu"
        self.OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
        self.LANG = "en"

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
