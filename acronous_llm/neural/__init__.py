from .network import NeuralNetwork
from .clustering import QueryClusterer
from .classifier import IntentClassifier
from .learner import OnlineLearner, FeedbackCollector

class AcronousNeuralEngine:
    """The learning "brain" of the Acronous agent ecosystem.

    Learns continuously from every user interaction:
      - Intent classifier accumulates real examples (add_example) so routing
        grows more accurate over time without the LLM.
      - The online learner (network) nudges weights based on implicit feedback.
      - A persistent example store lets state survive restarts.
    """
    def __init__(self, config):
        self.config = config
        self.network = NeuralNetwork(
            input_dim=config.EMBED_DIM,
            hidden_dims=[512, 256, 128],
            output_dim=config.CLUSTER_COUNT
        )
        self.clusterer = QueryClusterer(n_clusters=config.CLUSTER_COUNT)
        self.classifier = IntentClassifier(
            embed_dim=config.EMBED_DIM,
            num_intents=9
        )
        self.learner = OnlineLearner(
            model=self.network,
            lr=config.LEARNING_RATE
        )
        # Explicit feedback collector persisted to disk so ratings survive.
        self.feedback = FeedbackCollector(
            storage_path=str(config.MODELS_DIR / "feedback.json")
        )
        self.training_data = []
        # Learned preferences / topics keyed by session for quick recall.
        self._preferences = {}
        self._learned_facts = []
        self._load_persisted()

    def _load_persisted(self):
        import os, json
        try:
            # Example store (per-intent) for the classifier to grow on.
            ex_path = self.config.MODELS_DIR / "classifier_examples.json"
            if ex_path.exists():
                with open(ex_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for intent_str, items in data.items():
                    try:
                        intent_id = int(intent_str)
                    except Exception:
                        continue
                    for it in items:
                        emb = None
                        try:
                            import numpy as np
                            import torch
                            emb = torch.from_numpy(np.asarray(it, dtype=np.float32))
                        except Exception:
                            continue
                        if emb is not None:
                            self.classifier.add_example(emb, intent_id)
        except Exception:
            pass
        try:
            prefs_path = self.config.MODELS_DIR / "preferences.json"
            if prefs_path.exists():
                with open(prefs_path, "r", encoding="utf-8") as f:
                    self._preferences = json.load(f)
        except Exception:
            pass
        try:
            facts_path = self.config.MODELS_DIR / "learned_facts.json"
            if facts_path.exists():
                with open(facts_path, "r", encoding="utf-8") as f:
                    self._learned_facts = json.load(f)
        except Exception:
            pass

    def forward(self, x):
        return self.network(x)

    def learn(self, query_embedding, feedback, intent=None):
        self.training_data.append((query_embedding, feedback, intent))
        self.learner.update(query_embedding, feedback)
        if intent is not None:
            self.classifier.add_example(query_embedding, intent)

    def learn_from_interaction(self, query, response, route_type="general_chat", session_id="default", feedback_score=None):
        """Autonomously learn from a completed user interaction.

        Called after EVERY user turn so the brain improves continuously:
          1. Feed the query embedding + a neutral/implicit feedback score to the
             online learner (nudges the network toward the routed category).
          2. Add the route type as a labelled example for the classifier.
          3. Persist the classifier example store + feedback to disk.
        """
        try:
            emb = self.core_embedder.embed(query) if self.core_embedder else self._plain_embed(query)
            score = float(feedback_score) if feedback_score is not None else 0.5
            normalized = self._normalize_route(route_type)
            intent_id = self.classifier.intent_labels.index(normalized) if normalized in self.classifier.intent_labels else None
            self.learn(emb, score, intent_id)
            self.feedback.record(query, response, score, {"type": route_type, "session": session_id})
            self._persist_examples()
        except Exception:
            pass

    @staticmethod
    def _normalize_route(route_type):
        """Map router route types onto the classifier's intent label set so
        more interactions produce a labelled training example."""
        r = (route_type or "").lower()
        mapping = {
            "web_search": "web_search", "factual": "web_search", "news": "web_search",
            "image_analysis": "image_analysis", "image_edit": "image_analysis",
            "image_generation": "image_generation", "file_generation": "data_analysis",
            "code_generation": "code_generation", "translation": "translation",
            "planning": "planning_task", "planning_task": "planning_task",
            "general_chat": "general_chat", "chat": "general_chat",
            "voice": "voice_command", "voice_command": "voice_command",
        }
        return mapping.get(r, "general_chat")

    def set_embedder(self, embedder):
        """Allow wiring in the core embedder for real embeddings."""
        self.core_embedder = embedder

    def _plain_embed(self, text):
        import re
        import torch
        tokens = re.findall(r'\w+', (text or "").lower())
        vec = torch.zeros(self.config.EMBED_DIM)
        for t in set(tokens):
            vec[hash(t) % self.config.EMBED_DIM] += 1.0
        if vec.norm() > 0:
            vec = vec / vec.norm()
        return vec

    def remember_preference(self, session_id, key, value):
        """Store a learned preference for a session (e.g. 'language: Hindi').
        Autonomous — extracted from user interactions."""
        if not self._preferences.get(session_id):
            self._preferences[session_id] = {}
        self._preferences[session_id][key] = value
        self._persist_preferences()

    def get_preferences(self, session_id):
        return self._preferences.get(session_id, {})

    def remember_fact(self, fact, value):
        """Store a reusable learned fact (e.g. 'user is a developer')."""
        if not fact or not value:
            return
        self._learned_facts = [f for f in self._learned_facts if f.get("fact") != fact]
        self._learned_facts.append({"fact": fact, "value": value})
        self._learned_facts = self._learned_facts[-500:]
        self._persist_facts()

    def get_facts(self):
        return self._learned_facts

    def serve_memory_context(self, session_id):
        """Build a compact 'what I learned about this user' context block."""
        parts = []
        prefs = self.get_preferences(session_id)
        if prefs:
            prefs_str = "; ".join(f"{k}: {v}" for k, v in list(prefs.items())[:5])
            parts.append("User preferences: " + prefs_str)
        return " | ".join(parts)

    def _persist_examples(self):
        import json
        try:
            ex_path = self.config.MODELS_DIR / "classifier_examples.json"
            out = {}
            for intent_id, items in self.classifier.examples.items():
                ser = []
                for e in items[-200:]:
                    if hasattr(e, "tolist"):
                        ser.append(e.tolist())
                    else:
                        try:
                            ser.append(e.detach().cpu().tolist())
                        except Exception:
                            ser.append(list(e))
                if ser:
                    out[str(intent_id)] = ser
            with open(ex_path, "w", encoding="utf-8") as f:
                json.dump(out, f)
        except Exception:
            pass

    def _persist_preferences(self):
        import json
        try:
            p = self.config.MODELS_DIR / "preferences.json"
            with open(p, "w", encoding="utf-8") as f:
                json.dump(self._preferences, f)
        except Exception:
            pass

    def _persist_facts(self):
        import json
        try:
            p = self.config.MODELS_DIR / "learned_facts.json"
            with open(p, "w", encoding="utf-8") as f:
                json.dump(self._learned_facts, f)
        except Exception:
            pass

    def cluster_queries(self, embeddings):
        return self.clusterer.fit_predict(embeddings)

    def predict_intent(self, embedding, return_probs=False):
        return self.classifier.predict(embedding, return_probs=return_probs)

    def get_cluster_info(self, embedding):
        return self.clusterer.predict(embedding)

    def save_state(self, path):
        import torch
        torch.save({
            "network": self.network.state_dict(),
            "classifier": self.classifier.state_dict(),
        }, path)
        self._persist_examples()
        self._persist_preferences()
        self._persist_facts()

    def load_state(self, path):
        import torch
        import os
        if os.path.exists(path):
            data = torch.load(path, map_location="cpu")
            self.network.load_state_dict(data["network"])
            self.classifier.load_state_dict(data["classifier"])

    # Default embedder is set lazily; wire the real one from the core engine.
    core_embedder = None
