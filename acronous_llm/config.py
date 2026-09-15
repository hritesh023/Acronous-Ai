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

        self.LLM_MODEL = os.getenv("ACRONOUS_LLM_MODEL", "qwen3:8b")
        self.LLM_BACKEND = os.getenv("ACRONOUS_LLM_BACKEND", "auto")
        self.LLM_PROVIDER = os.getenv("ACRONOUS_LLM_PROVIDER", "contabo")
        # ── Contabo VPS brain (Cloud VPS 8, EU) ──
        # Display: acronous | Host: 20010 | IP: 167.86.104.155 | user: root
        # VNC: 5.189.136.10:63080 | Disk: 300 GB | IPv6: 2a02:c207:2358:1966::1/64
        self.BRAIN_HOST = os.getenv("ACRONOUS_BRAIN_HOST", "brain.acronous.com")
        self.BRAIN_URL = os.getenv(
            "ACRONOUS_BRAIN_URL", "https://brain.acronous.com")
        self.BRAIN_DIRECT_URL = os.getenv(
            "ACRONOUS_BRAIN_DIRECT_URL", "http://167.86.104.155:11434")
        # Model routing — smartest model per task (all served by Contabo Ollama)
        self.LLM_CHAT_MODEL = os.getenv("ACRONOUS_LLM_CHAT_MODEL", "qwen3:8b")
        self.LLM_CODE_MODEL = os.getenv("ACRONOUS_LLM_CODE_MODEL", "qwen2.5-coder:7b")
        self.LLM_FAST_MODEL = os.getenv("ACRONOUS_LLM_FAST_MODEL", "qwen2.5:3b")
        # ── Self-training (auto-learn from internet + self fine-tune loop) ──
        # Resource-safe by design: 24GB RAM / 300GB disk caps are ENFORCED.
        # The brain gets smarter daily via bounded RAG/memory/JSONL growth
        # with pruning — storage never grows unbounded.
        self.SELF_TRAIN_ENABLED = os.getenv("ACRONOUS_SELF_TRAIN", "true").lower() == "true"
        self.SELF_TRAIN_INTERVAL = int(os.getenv("ACRONOUS_SELF_TRAIN_INTERVAL", "21600"))  # 6h dataset cycle
        self.SELF_TRAIN_MIN_FACTS = int(os.getenv("ACRONOUS_SELF_TRAIN_MIN_FACTS", "500"))
        self.TRAINING_DIR_NAME = "training"
        # ── Resource caps (never fill the VPS) ──
        self.SELF_TRAIN_MAX_RAM_PCT = float(os.getenv("ACRONOUS_SELF_TRAIN_MAX_RAM_PCT", "85"))  # pause if system RAM above this
        self.SELF_TRAIN_MIN_FREE_GB = float(os.getenv("ACRONOUS_SELF_TRAIN_MIN_FREE_GB", "10"))  # pause if data-disk free below this (VPS: set 40)
        self.SELF_TRAIN_MAX_TRAIN_GB = float(os.getenv("ACRONOUS_SELF_TRAIN_MAX_TRAIN_GB", "25"))  # training dir quota
        self.SELF_TRAIN_MAX_PAIRS_PER_CYCLE = int(os.getenv("ACRONOUS_SELF_TRAIN_MAX_PAIRS_PER_CYCLE", "400"))  # small CPU-friendly batches
        self.SELF_TRAIN_MAX_MERGED_PAIRS = int(os.getenv("ACRONOUS_SELF_TRAIN_MAX_MERGED_PAIRS", "20000"))  # merged file cap (~100MB)
        self.SELF_TRAIN_RETAIN_DAYS = int(os.getenv("ACRONOUS_SELF_TRAIN_RETAIN_DAYS", "14"))  # prune snapshots older than this
        self.SELF_TRAIN_RETAIN_SNAPSHOTS = int(os.getenv("ACRONOUS_SELF_TRAIN_RETAIN_SNAPSHOTS", "7"))  # keep newest N snapshots
        self.LLM_API_KEY = os.getenv("ACRONOUS_LLM_API_KEY", "")
        self.LLM_API_URL = os.getenv("ACRONOUS_LLM_API_URL", "")
        self.EMBED_MODEL = os.getenv("ACRONOUS_EMBED_MODEL", "all-MiniLM-L6-v2")
        self.VISION_MODEL = os.getenv("ACRONOUS_VISION_MODEL", "microsoft/resnet-50")
        self.STT_MODEL = os.getenv("ACRONOUS_STT_MODEL", "base")
        self.SEARCH_PROVIDER = os.getenv("ACRONOUS_SEARCH", "auto")
        self.SERPAPI_KEY = os.getenv("SERPAPI_KEY", os.getenv("ACRONOUS_SERPAPI_KEY", ""))

        self.MAX_HISTORY = 50
        self.CLUSTER_COUNT = 8
        self.EMBED_DIM = 384
        self.LEARNING_RATE = 0.001
        self.MEMORY_MODE = os.getenv("ACRONOUS_MEMORY", "sqlite")
        self.TEMPERATURE = 0.7
        self.MAX_TOKENS = int(os.getenv("ACRONOUS_MAX_TOKENS", "4096"))
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
