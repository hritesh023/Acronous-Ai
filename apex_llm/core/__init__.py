from apex_llm.config import ApexConfig
from apex_llm.core.embedder import TextEmbedder
from apex_llm.core.search import WebSearch
from apex_llm.core.llm import LocalLLM
from apex_llm.core.rag import RAGSystem
from apex_llm.core.vision import VisionEngine
from apex_llm.core.voice import VoiceEngine
from apex_llm.core.memory import MemorySystem
from apex_llm.core.image_generator import ImageGenerator

class ApexCoreEngine:
    def __init__(self, config: ApexConfig):
        self.config = config
        self.embedder = TextEmbedder(config)
        self.search = WebSearch(config)
        self.llm = LocalLLM(config)
        self.rag = RAGSystem(config, self.embedder)
        self.vision = VisionEngine(config) if config.ENABLE_VISION else None
        self.voice = VoiceEngine(config) if config.ENABLE_VOICE else None
        self.memory = MemorySystem(config)
        self.image_gen = ImageGenerator(config)
