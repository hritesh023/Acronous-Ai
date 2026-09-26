"""Fast capped RAG for the Acronous brain (Contabo VPS: 24GB RAM / 300GB disk).

Design goals — fast + accurate on a small box:
  * RAG-FIRST answering: high-confidence hits let the brain answer from its
    own learned memory without a slow LLM + web-search round trip.
  * BOUNDED memory: MAX_DOCS cap + LRU-ish prune so RAM/disk never grow
    unbounded (the old code appended forever and rewrote a torch file on
    EVERY turn — the #1 latency + OOM source).
  * NON-BLOCKING persistence: debounced background save (default 30s), never
    on the request hot path.
  * HYBRID recall: dense cosine (hash/bigram embeddings, pre-normalized) +
    lightweight keyword overlap, blended. Pure-hash cosine alone hallucinates;
    the keyword gate keeps precision high with zero extra RAM.
  * THREAD-SAFE: all mutations under a lock; retrieve never blocks writes long.

Env knobs (see config.py):
  ACRONOUS_RAG_MAX_DOCS=5000, ACRONOUS_RAG_SAVE_DEBOUNCE_S=30,
  ACRONOUS_RAG_TOP_K=3, ACRONOUS_RAG_THRESHOLD=0.35
"""
import hashlib
import os
import re
import threading
import time

_TOKEN_RE = re.compile(r"[a-z0-9]+")

try:
    import torch
except Exception:  # pragma: no cover - torch always present on VPS
    torch = None


def _tokens(text):
    return _TOKEN_RE.findall((text or "").lower())


class RAGSystem:
    def __init__(self, config, embedder):
        self.config = config
        self.embedder = embedder
        self.documents = []
        self.embeddings = None
        self._ids = set()
        self._lock = threading.RLock()
        self._save_timer = None
        self._last_save = 0.0
        self.max_docs = int(os.getenv("ACRONOUS_RAG_MAX_DOCS", "5000"))
        self.save_debounce_s = float(os.getenv("ACRONOUS_RAG_SAVE_DEBOUNCE_S", "30"))
        self.index_path = config.MODELS_DIR / "rag_index.pt"
        self._load_index()

    # ── writes (never block the request path on disk I/O) ──
    def add_document(self, text, metadata=None):
        text = (text or "").strip()
        if not text:
            return None
        # Cap absurd single docs (keeps index + prompts small → faster prefill).
        if len(text) > 1500:
            text = text[:1500]
        doc_id = hashlib.md5(text.encode()).hexdigest()[:12]
        with self._lock:
            if doc_id in self._ids:
                return doc_id
            try:
                emb = self.embedder.embed(text)
                if torch is not None and not hasattr(emb, "unsqueeze"):
                    import torch as _t
                    emb = _t.tensor(list(emb), dtype=_t.float32)
                if torch is not None:
                    n = emb.norm()
                    if float(n) > 0:
                        emb = emb / n
            except Exception:
                return doc_id
            self.documents.append({
                "id": doc_id,
                "text": text,
                "metadata": metadata or {},
                "ts": time.time(),
                "tokens": set(_tokens(text)),
            })
            self._ids.add(doc_id)
            if torch is not None:
                try:
                    if self.embeddings is None:
                        self.embeddings = emb.unsqueeze(0)
                    else:
                        self.embeddings = torch.cat([self.embeddings, emb.unsqueeze(0)])
                except Exception:
                    pass
            self._prune_if_needed_locked()
        self._schedule_save()
        return doc_id

    def build_index(self, texts, metadatas=None):
        with self._lock:
            self.documents = []
            self._ids = set()
            self.embeddings = None
        for i, text in enumerate(texts or []):
            meta = metadatas[i] if metadatas and i < len(metadatas) else {}
            self.add_document(text, meta)
        self._save_now()

    def add_and_index(self, text, metadata=None):
        """Hot-path entry: memory-only write + debounced background persist.

        The old implementation did a full torch.save() synchronously on every
        turn (~50-200ms + disk wear). This returns in <2ms; the save happens
        at most once per `save_debounce_s`.
        """
        return self.add_document(text, metadata)

    def _prune_if_needed_locked(self):
        """Keep the index bounded: drop oldest docs beyond MAX_DOCS.

        Keeps newest 80% + highest-value 20% heuristic simple: newest win,
        because internet-learner + recent human-eval turns are the freshest
        signal. Runs O(1) amortized.
        """
        overflow = len(self.documents) - self.max_docs
        if overflow <= 0:
            return
        # Drop oldest first (documents appended chronologically).
        drop_ids = set()
        for _ in range(overflow):
            old = self.documents.pop(0)
            drop_ids.add(old["id"])
            self._ids.discard(old["id"])
        if torch is not None and self.embeddings is not None:
            try:
                keep = self.embeddings[overflow:]
                self.embeddings = keep.clone()
            except Exception:
                pass

    # ── reads ──
    def retrieve(self, query, k=3, threshold=0.35):
        """Hybrid retrieve: 0.7 * cosine + 0.3 * keyword overlap.

        The keyword gate is what kills hallucinations from hash-collision
        cosine: a doc must share at least one content token OR clear cosine.
        """
        with self._lock:
            docs = self.documents
            embs = self.embeddings
        if embs is None or not docs:
            return []
        try:
            k = max(1, min(int(k or 3), len(docs)))
            query_emb = self.embedder.embed(query)
            if torch is not None:
                if query_emb.dim() == 1:
                    query_emb = query_emb.unsqueeze(0)
                n = query_emb.norm()
                if float(n) > 0:
                    query_emb = query_emb / n
                sims = torch.nn.functional.cosine_similarity(query_emb, embs)
                values, indices = torch.topk(sims, k)
                values = values.tolist() if hasattr(values, "tolist") else list(values)
                indices = indices.tolist() if hasattr(indices, "tolist") else list(indices)
            else:
                return self._keyword_fallback(query, k)
        except Exception:
            return self._keyword_fallback(query, k)
        qtokens = set(_tokens(query)) - {"what", "when", "where", "which", "who",
                                         "does", "have", "with", "from", "that",
                                         "this", "about", "there", "their", "your"}
        results = []
        for score, idx in zip(values, indices):
            try:
                doc = docs[int(idx)]
            except Exception:
                continue
            overlap = len(qtokens & doc.get("tokens", set()))
            kw_score = min(1.0, overlap / 3.0) if qtokens else 0.0
            blended = 0.7 * float(score) + 0.3 * kw_score
            # Precision gate: accept on blended threshold OR strong cosine
            # with at least one shared token (kills hash-collision ghosts).
            if blended >= threshold or (float(score) >= 0.75 and overlap >= 1):
                results.append({
                    "text": doc["text"],
                    "score": round(blended, 3),
                    "cosine": round(float(score), 3),
                    "metadata": doc.get("metadata", {}),
                })
        return sorted(results, key=lambda x: x["score"], reverse=True)

    def _keyword_fallback(self, query, k=3):
        qtokens = set(_tokens(query))
        if not qtokens:
            return []
        scored = []
        with self._lock:
            docs = list(self.documents[-self.max_docs:])
        for d in docs:
            overlap = len(qtokens & d.get("tokens", set()))
            if overlap:
                scored.append({"text": d["text"], "score": round(min(1.0, overlap / 4.0), 3),
                               "cosine": 0.0, "metadata": d.get("metadata", {})})
        return sorted(scored, key=lambda x: x["score"], reverse=True)[:k]

    def retrieve_with_context(self, query, k=3):
        results = self.retrieve(query, k)
        if not results:
            return "", []
        context = "\n\n".join(
            f"[Memory {i+1} · score {r['score']}]: {r['text']}"
            for i, r in enumerate(results)
        )
        return context, results

    def stats(self):
        with self._lock:
            n = len(self.documents)
        try:
            size = os.path.getsize(self.index_path) if os.path.exists(self.index_path) else 0
        except Exception:
            size = 0
        return {"docs": n, "max_docs": self.max_docs, "index_bytes": size}

    def clear(self):
        with self._lock:
            self.documents = []
            self._ids = set()
            self.embeddings = None
        self._save_now()

    # ── persistence (debounced, atomic) ──
    def _schedule_save(self):
        if self.save_debounce_s <= 0:
            return
        with self._lock:
            if self._save_timer is not None and self._save_timer.is_alive():
                return
            t = threading.Timer(self.save_debounce_s, self._save_now)
            t.daemon = True
            self._save_timer = t
        try:
            t.start()
        except Exception:
            pass

    def flush(self):
        """Force persist now (call on shutdown / explicit learn endpoints)."""
        self._save_now()

    def _save_now(self):
        if torch is None:
            return
        with self._lock:
            if self.embeddings is None or not self.documents:
                return
            docs = [{"id": d["id"], "text": d["text"],
                     "metadata": d.get("metadata", {}), "ts": d.get("ts", 0)}
                    for d in self.documents]
            embs = self.embeddings
        try:
            os.makedirs(os.path.dirname(os.fspath(self.index_path)), exist_ok=True)
            tmp = os.fspath(self.index_path) + ".tmp"
            torch.save({"embeddings": embs, "documents": docs}, tmp)
            os.replace(tmp, os.fspath(self.index_path))
            self._last_save = time.time()
        except Exception:
            pass

    def _save_index(self):
        self._schedule_save()

    def _load_index(self):
        if torch is None or not os.path.exists(os.fspath(self.index_path)):
            return
        try:
            data = torch.load(os.fspath(self.index_path), map_location="cpu", weights_only=False)
            docs = data.get("documents", [])
            # Cap on load too (protects RAM after unclean growth).
            if len(docs) > self.max_docs:
                docs = docs[-self.max_docs:]
            with self._lock:
                self.documents = []
                self._ids = set()
                for d in docs:
                    text = d.get("text", "")
                    self.documents.append({
                        "id": d.get("id") or hashlib.md5(text.encode()).hexdigest()[:12],
                        "text": text,
                        "metadata": d.get("metadata", {}),
                        "ts": d.get("ts", 0),
                        "tokens": set(_tokens(text)),
                    })
                    self._ids.add(self.documents[-1]["id"])
                embs = data.get("embeddings")
                if embs is not None and len(embs) > len(self.documents):
                    embs = embs[-len(self.documents):]
                self.embeddings = embs
        except Exception:
            pass
