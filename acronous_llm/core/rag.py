import torch
import numpy as np
from collections import deque
import json
import os
import hashlib

class RAGSystem:
    def __init__(self, config, embedder):
        self.config = config
        self.embedder = embedder
        self.documents = []
        self.embeddings = None
        self.index_path = config.MODELS_DIR / "rag_index.pt"
        self._load_index()

    def add_document(self, text, metadata=None):
        doc_id = hashlib.md5(text.encode()).hexdigest()[:12]
        self.documents.append({
            "id": doc_id,
            "text": text,
            "metadata": metadata or {}
        })

    def build_index(self, texts, metadatas=None):
        self.documents = []
        for i, text in enumerate(texts):
            meta = metadatas[i] if metadatas else {}
            self.add_document(text, meta)
        if self.documents:
            self.embeddings = self.embedder.embed_batch(
                [d["text"] for d in self.documents]
            )
            self._save_index()

    def add_and_index(self, text, metadata=None):
        self.add_document(text, metadata)
        emb = self.embedder.embed(text)
        if self.embeddings is None:
            self.embeddings = emb.unsqueeze(0)
        else:
            self.embeddings = torch.cat([self.embeddings, emb.unsqueeze(0)])
        self._save_index()

    def retrieve(self, query, k=3, threshold=0.3):
        if self.embeddings is None or len(self.documents) == 0:
            return []
        query_emb = self.embedder.embed(query)
        if query_emb.dim() == 1:
            query_emb = query_emb.unsqueeze(0)
        similarities = torch.nn.functional.cosine_similarity(
            query_emb, self.embeddings
        )
        top_k = min(k, len(similarities))
        values, indices = torch.topk(similarities, top_k)
        results = []
        for i, idx in enumerate(indices):
            if values[i].item() >= threshold:
                results.append({
                    "text": self.documents[idx]["text"],
                    "score": values[i].item(),
                    "metadata": self.documents[idx]["metadata"]
                })
        return sorted(results, key=lambda x: x["score"], reverse=True)

    def retrieve_with_context(self, query, k=3):
        results = self.retrieve(query, k)
        if not results:
            return "", []
        context = "\n\n".join([
            f"[Source {i+1}]: {r['text']}"
            for i, r in enumerate(results)
        ])
        return context, results

    def clear(self):
        self.documents = []
        self.embeddings = None

    def _save_index(self):
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
        if self.embeddings is not None:
            torch.save({
                "embeddings": self.embeddings,
                "documents": self.documents
            }, self.index_path)

    def _load_index(self):
        if os.path.exists(self.index_path):
            try:
                data = torch.load(self.index_path, map_location="cpu")
                self.embeddings = data["embeddings"]
                self.documents = data["documents"]
            except Exception:
                pass
