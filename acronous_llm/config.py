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
        data_env = os.getenv("DATA_DIR", "")
        self.DATA_DIR = Path(data_env) if data_env else self.ROOT_DIR / "data"
        self.MODELS_DIR = self.DATA_DIR / "models"
        self.DB_PATH = self.DATA_DIR / "memory.db"
        self.CLUSTER_PATH = self.MODELS_DIR / "clusters.npz"
        self.CLASSIFIER_PATH = self.MODELS_DIR / "classifier.pt"
        self.EMBEDDER_PATH = self.MODELS_DIR / "embedder.pt"

        # Default chat model: qwen2.5:3b (5.7 tok/s, reliable). qwen3:8b
        # (2.35 tok/s) caused 90s-timeout 500s on the 4-core CPU box — it stays
        # available via ACRONOUS_LLM_CHAT_MODEL override for quality tasks only.
        self.LLM_MODEL = os.getenv("ACRONOUS_LLM_MODEL", "qwen3.5:2b")
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
        # Model routing — fastest reliable model per task (Contabo 4-core CPU).
        # Measured steady state (single slot, pinned 4096 ctx):
        #   qwen3.5:2b  TTFT 0.4-1.6s  ~31-34 tok/s
        #   qwen3.5:4b  TTFT 1.5-2.3s  ~15-18 tok/s
        # The 2B is the default because on a CPU box GENERATION time is what
        # the user feels; the 4B is reserved for code/depth where the extra
        # quality per token is worth the wait. Both are natively multimodal,
        # and both must be called with think=false.
        self.LLM_CHAT_MODEL = os.getenv("ACRONOUS_LLM_CHAT_MODEL", "qwen3.5:2b")
        self.LLM_CODE_MODEL = os.getenv("ACRONOUS_LLM_CODE_MODEL", "qwen3.5:4b")
        self.LLM_FAST_MODEL = os.getenv("ACRONOUS_LLM_FAST_MODEL", "qwen3.5:2b")
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
        # ── Fast-RAG + speed path (small-box accuracy without the wait) ──
        # RAG index is capped (RAM-safe) and persisted with a debounce so
        # learning never blocks a response. Retrieval is hybrid
        # (BM25 + dense cosine, RRF-fused) behind a confidence gate so the
        # brain can say "I don't know" instead of hallucinating from memory.
        self.RAG_MAX_DOCS = int(os.getenv("ACRONOUS_RAG_MAX_DOCS", "6000"))
        self.RAG_SAVE_DEBOUNCE_S = float(os.getenv("ACRONOUS_RAG_SAVE_DEBOUNCE_S", "45"))
        self.RAG_TOP_K = int(os.getenv("ACRONOUS_RAG_TOP_K", "4"))
        self.RAG_THRESHOLD = float(os.getenv("ACRONOUS_RAG_THRESHOLD", "0.35"))
        self.RAG_CHUNK_CHARS = int(os.getenv("ACRONOUS_RAG_CHUNK_CHARS", "320"))
        self.RAG_CHUNK_OVERLAP = int(os.getenv("ACRONOUS_RAG_CHUNK_OVERLAP", "60"))
        # RAG-first shortcut: confidence >= this answers from learned memory
        # with pure extraction (zero LLM calls) — instant + cannot hallucinate.
        self.RAG_DIRECT_ANSWER = float(os.getenv("ACRONOUS_RAG_DIRECT_ANSWER", "0.72"))
        self.RAG_CACHE_TTL_S = float(os.getenv("ACRONOUS_RAG_CACHE_TTL_S", "1800"))
        self.RAG_MIN_TERMS = int(os.getenv("ACRONOUS_RAG_MIN_TERMS", "2"))
        # Legacy alias kept so old env files/compose files keep working.
        self.RAG_DIRECT_ANSWER_SCORE = self.RAG_DIRECT_ANSWER
        # Hot-path guards: regex-only routing (no LLM classify call) and a
        # hard cap on the web-search phase so TTFT stays ~1s, not ~10s.
        self.ROUTER_LLM_CLASSIFY = os.getenv("ACRONOUS_ROUTER_LLM_CLASSIFY", "false").lower() == "true"
        self.SEARCH_PHASE_MS = int(os.getenv("ACRONOUS_SEARCH_PHASE_MS", "900"))
        self.SEARCH_MAX_RESULTS = int(os.getenv("ACRONOUS_SEARCH_MAX_RESULTS", "3"))
        # Memory hygiene: WAL + indexes + per-session/DB prune caps.
        self.MEMORY_MAX_PER_SESSION = int(os.getenv("ACRONOUS_MEMORY_MAX_PER_SESSION", "200"))
        self.MEMORY_MAX_ROWS = int(os.getenv("ACRONOUS_MEMORY_MAX_ROWS", "20000"))
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
        # ── Ollama runtime contract (MUST match the VPS ollama container) ──
        # Alternating num_ctx between callers forces Ollama to reallocate the
        # whole KV cache on every switch, which cost 8-15s of pure prefill per
        # request and was the single biggest source of "really slow" responses.
        # 2048 also measures ~25% faster than 4096 for decode (9.0 vs 7.2
        # tok/s) because attention cost scales with the KV cache.
        self.LLM_CONTEXT_SIZE = int(os.getenv("ACRONOUS_LLM_CONTEXT_SIZE", "2048"))
        self.LLM_NUM_PARALLEL = int(os.getenv("ACRONOUS_LLM_NUM_PARALLEL", "1"))
        # Wall-clock ceiling per generation. A small model with a runaway
        # repeat loop and a large num_predict will happily burn the whole
        # 4-core box for 50+ minutes; the deadline converts that into a fast,
        # honest partial answer instead of a frozen app.
        self.LLM_DEADLINE_S = float(os.getenv("ACRONOUS_LLM_DEADLINE_S", "75"))
        self.LLM_DEADLINE_FIRST_TOKEN_S = float(os.getenv("ACRONOUS_LLM_DEADLINE_FIRST_TOKEN_S", "30"))
        # Sampling guardrail against degenerate repetition (one such loop held
        # all 4 cores at 741% CPU for 40+ minutes). repeat_penalty is the
        # cheapest effective guard; presence/frequency penalties measured
        # within noise of it, so they are not set.
        self.LLM_REPEAT_PENALTY = float(os.getenv("ACRONOUS_LLM_REPEAT_PENALTY", "1.2"))
        self.LLM_REPEAT_LAST_N = int(os.getenv("ACRONOUS_LLM_REPEAT_LAST_N", "64"))
        self.LLM_TOP_P = float(os.getenv("ACRONOUS_LLM_TOP_P", "0.9"))
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
