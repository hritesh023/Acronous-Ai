import torch
import numpy as np
import re
import os

class TextEmbedder:
    def __init__(self, config):
        self.config = config
        self._model = None
        self._model_loaded = False
        self._load_model()

    @property
    def model(self):
        if not self._model_loaded:
            self._load_model()
        return self._model

    def _load_model(self):
        self._model_loaded = True
        self._model = None

    def embed(self, text):
        if self.model is not None:
            try:
                emb = self.model.encode(text, normalize_embeddings=True)
                return torch.from_numpy(emb).float()
            except Exception:
                pass
        return self._fallback_embed(text)

    def embed_batch(self, texts):
        if self.model is not None:
            try:
                embs = self.model.encode(texts, normalize_embeddings=True)
                return torch.from_numpy(embs).float()
            except Exception:
                pass
        return torch.stack([self._fallback_embed(t) for t in texts])

    def _fallback_embed(self, text):
        text = text.lower().strip()
        tokens = re.findall(r'\w+', text)
        vec = torch.zeros(self.config.EMBED_DIM)
        if not tokens:
            return vec
        for i, t in enumerate(set(tokens)):
            idx = hash(t) % self.config.EMBED_DIM
            vec[idx] += 1.0
        if vec.norm() > 0:
            vec = vec / vec.norm()
        return vec

    def cosine_similarity(self, a, b):
        if isinstance(a, np.ndarray):
            a = torch.from_numpy(a)
        if isinstance(b, np.ndarray):
            b = torch.from_numpy(b)
        return torch.nn.functional.cosine_similarity(
            a.unsqueeze(0), b.unsqueeze(0)
        ).item()

    def similarity_matrix(self, embeddings):
        if isinstance(embeddings, np.ndarray):
            embeddings = torch.from_numpy(embeddings)
        norms = embeddings.norm(dim=1, keepdim=True)
        normalized = embeddings / (norms + 1e-8)
        return (normalized @ normalized.T).numpy()
