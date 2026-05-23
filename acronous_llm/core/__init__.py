from acronous_llm.config import AcronousConfig
from acronous_llm.core.embedder import TextEmbedder
from acronous_llm.core.search import WebSearch
from acronous_llm.core.llm import LocalLLM
from acronous_llm.core.rag import RAGSystem
from acronous_llm.core.vision import VisionEngine
from acronous_llm.core.voice import VoiceEngine
from acronous_llm.core.memory import MemorySystem
from acronous_llm.core.image_generator import ImageGenerator
from acronous_llm.core.diagram_generator import DiagramGenerator

class AcronousCoreEngine:
    def __init__(self, config: AcronousConfig):
        self.config = config
        self.embedder = TextEmbedder(config)
        self.search = WebSearch(config)
        self.llm = LocalLLM(config)
        self.rag = RAGSystem(config, self.embedder)
        self.vision = VisionEngine(config) if config.ENABLE_VISION else None
        self.voice = VoiceEngine(config) if config.ENABLE_VOICE else None
        self.memory = MemorySystem(config)
        self.image_gen = ImageGenerator(config, llm=self.llm)
        self.diagram_gen = DiagramGenerator(config)
