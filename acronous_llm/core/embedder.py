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
        # Zero-RAM default: improved hash embeddings (unigram + bigram).
        # If `sentence-transformers` is installed on the VPS it is used
        # lazily (better recall, ~90MB RAM) — otherwise the hash path keeps
        # the 3GB brain container lean. Never crash the hot path on this.
        self._model_loaded = True
        self._model = None
        try:
            if os.getenv("ACRONOUS_EMBED_ST", "auto") in ("auto", "1", "true"):
                from sentence_transformers import SentenceTransformer  # optional
                name = os.getenv("ACRONOUS_EMBED_MODEL", "all-MiniLM-L6-v2")
                self._model = SentenceTransformer(name)
        except Exception:
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
        # Unigram + bigram hashed TF with length-norm. Bigrams sharply cut
        # hash-collision false positives (the old unigram-only vector is why
        # RAG recall felt random) at zero extra RAM or dependency cost.
        text = (text or "").lower().strip()
        tokens = re.findall(r'[a-z0-9]+', text)
        vec = torch.zeros(self.config.EMBED_DIM)
        if not tokens:
            return vec
        feats = set(tokens)
        for a, b in zip(tokens, tokens[1:]):
            feats.add(a + "_" + b)
        for t in feats:
            # stable hash (python hash() is salted per-process → non-deterministic
            # across restarts; md5 keeps the persisted index consistent).
            import hashlib as _h
            idx = int(_h.md5(t.encode()).hexdigest(), 16) % self.config.EMBED_DIM
            vec[idx] += 1.0 if "_" not in t else 1.5  # bigrams carry more signal
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
