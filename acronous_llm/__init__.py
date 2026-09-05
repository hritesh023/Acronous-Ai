from acronous_llm.config import AcronousConfig
from acronous_llm.neural import AcronousNeuralEngine
from acronous_llm.core import AcronousCoreEngine
from acronous_llm.agents import AcronousAgentEngine
from acronous_llm.core.internet_learner import KnowledgeGraph

__all__ = [
    "AcronousConfig",
    "AcronousNeuralEngine",
    "AcronousCoreEngine",
    "AcronousAgentEngine",
    "KnowledgeGraph",
]

# Lazily import the autonomous entry point so importing this package never
# requires network/CLI deps that aren't available in every embedder.
def start_autonomous_learning(interval_seconds=300, run_on_start=True):
    from acronous_llm.autonomous import start_autonomous_learning as _start
    return _start(interval_seconds=interval_seconds, run_on_start=run_on_start)
