"""Acronous LLM — RAG v2 for the Contabo brain (24GB RAM / 300GB disk, 4-core CPU).

Why v2 exists
-------------
v1 hashed unigrams+bigrams into a 384-d vector and scored `0.7*cosine +
0.3*keyword`. On a 3B model that produced three failures at once:

  1. **Low precision** — hash collisions surfaced unrelated chunks, and the
     0.35 blended threshold let them through, which is exactly how a small
     model ends up *confidently* hallucinating from "memory".
  2. **No answerability signal** — every query got *something* back, so the
     caller could never tell "I know this" from "this is noise".
  3. **Whole-document chunks** — a 1500-char doc scored as a unit, so one
     relevant sentence out of ten was diluted below threshold.

v2 fixes all three with a classic, boring, fast pipeline:

    query ──▶ normalize + content terms
          ├─▶ BM25 over an inverted index        (lexical precision, IDF-weighted)
          └─▶ dense cosine over a float32 matrix  (semantic recall)
                     │
                  RRF fusion (rank-based, no score-scale guessing)
                     │
              confidence gate  ──▶ answerable?  ← the anti-hallucination switch
                     │
          ├─ extractive answer (0 LLM calls, ~5-20ms)
          └─ grounded context for the LLM (verbatim, source-tagged)

Everything is bounded: `max_chunks` cap, score-aware eviction, quantized
float32 embeddings, debounced atomic saves. RAM/disk cannot grow unbounded on
the 300GB box, and retrieval never blocks a response.

Env knobs (config.py):
  ACRONOUS_RAG_MAX_CHUNKS=6000      hard cap on indexed chunks
  ACRONOUS_RAG_CHUNK_CHARS=320      chunk size (smaller = more precise)
  ACRONOUS_RAG_SAVE_DEBOUNCE_S=45   background persist debounce
  ACRONOUS_RAG_TOP_K=4              passages returned
  ACRONOUS_RAG_DIRECT_ANSWER=0.72   confidence needed to answer WITHOUT the LLM
  ACRONOUS_RAG_CACHE_TTL_S=1800     answer cache TTL
  ACRONOUS_RAG_MIN_TERMS=2          below this, never answer from memory
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import threading
import time
from collections import OrderedDict

try:
    import numpy as _np
except Exception:  # pragma: no cover
    _np = None

try:
    import torch
except Exception:  # pragma: no cover
    torch = None


# ── tokenisation ───────────────────────────────────────────────────────────
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9'\-]*")
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n{2,}")

# Stop words removed from queries. Kept short on purpose: aggressive stop-word
# lists throw away the content terms ("who", "when") that carry the question.
STOPWORDS = frozenset("""
a an the and or but if then than that this these those of in on at to for from by with
about into over after before between during is are was were be been being am do does did
doing have has had having i me my we us our you your he him his she her it its they them their
what which who whom whose when where why how all any both each few more most other some such
no nor not only own same so too very can will just should now as s t don should ve ll re m d
""".split())

_BM25_K1 = 1.4
_BM25_B = 0.72
_RRF_K = 60.0
_CANDIDATE_POOL = 64

# Answers that must never enter the corpus. A RAG system that learns from its
# own replies will happily re-serve a bad answer forever: one truncated "That."
# was stored, then recalled with full confidence, then taught back again. The
# learn path is gated on these.
_MIN_ANSWER_CHARS = 25
_JUNK_ANSWER_RE = re.compile(
    r"^(?:that\.?|this\.?|yes\.?|no\.?|ok(?:ay)?\.?|sure\.?|thanks?\.?|"
    r"i (?:do not|don't) know\.?|unknown\.?|n/?a\.?|\W+)$",
    re.I,
)


def answer_is_learnable(text: str) -> bool:
    """Reject junk before it can poison the corpus."""
    t = re.sub(r"\s+", " ", (text or "")).strip()
    if len(t) < _MIN_ANSWER_CHARS:
        return False
    if _JUNK_ANSWER_RE.match(t):
        return False
    # Needs some real substance, not pure punctuation/emoji.
    return len(re.findall(r"[A-Za-z0-9]", t)) >= 20


def _norm_tokens(text: str):
    """Lowercase word tokens with stop words removed."""
    return [t for t in _WORD_RE.findall((text or "").lower()) if t not in STOPWORDS and len(t) > 1]


def _content_terms(text: str):
    """Query-side content terms: unigrams + adjacent bigrams (phrase signal)."""
    toks = _norm_tokens(text)
    terms = set(toks)
    for a, b in zip(toks, toks[1:]):
        terms.add(f"{a}_{b}")
    return terms


def _split_chunks(text: str, size: int, overlap: int):
    """Sentence-aware chunking.

    Sentences first (so we never cut mid-clause), then merged up to `size`
    chars with `overlap` chars of carry-over. Far more precise than fixed
    slicing: a chunk is a self-contained answer unit.
    """
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    pieces = [p.strip() for p in _SENT_SPLIT_RE.split(text) if p and p.strip()]
    chunks, buf = [], ""
    for piece in pieces:
        # A single monster sentence (no punctuation) still gets hard-split.
        while len(piece) > size:
            if buf:
                chunks.append(buf.strip())
                buf = ""
            chunks.append(piece[:size].strip())
            piece = piece[size - overlap:]
        if not buf:
            buf = piece
        elif len(buf) + 1 + len(piece) <= size:
            buf = f"{buf} {piece}"
        else:
            chunks.append(buf.strip())
            tail = buf[-overlap:].strip() if overlap else ""
            buf = f"{tail} {piece}".strip() if tail else piece
    if buf.strip():
        chunks.append(buf.strip())
    return [c for c in chunks if c]


def _innermost_answer(text, _depth=0):
    """Peel repeated Q:/A: wrappers and return just the real answer.

    A chunk learned from an already-prefixed chunk reads
    "Q: q? A: Q: q? A: the answer." Each layer is removed until only the
    answer remains, so the user never sees the question echoed back.
    """
    t = (text or "").strip()
    if not t or _depth > 4:
        return t
    t = re.sub(r"(?im)^\s*(?:Q|Question)\s*:\s*", "", t, count=1).strip()
    m = re.search(r"(?is)\bA\s*[:.\)]\s*", t)
    if not m:
        return t
    before, after = t[: m.start()].strip(), t[m.end():].strip()
    if not after:
        return t
    if before:
        # A question preceded this answer: remember the innermost question.
        return _innermost_answer(after, _depth + 1)
    return _innermost_answer(after, _depth + 1)


def _normalize_qa(text, _depth=0):
    """Canonicalise learned Q/A text to `Q: <q>\\nA: <a>`.

    Workers learn from chat turns, and the same exchange can arrive as
    "Q: who? A: Sam", "Q: who?\\nA: Sam", or "A: Sam". Retrieval scores better
    and extraction is far more reliable on one canonical shape, so the inline
    form is rewritten on the way in.
    """
    t = (text or "").strip()
    if not t:
        return t
    t = re.sub(r"(?im)^\s*(?:Q|Question)\s*:\s*", "", t, count=1).strip()
    m = re.search(r"(?is)\bA\s*[:.\)]\s*", t)
    if not m:
        return t
    question, answer = t[: m.start()].strip(), t[m.end():].strip()
    if not question or not answer:
        return t
    if _depth < 3 and re.search(r"(?is)\b(?:Q|Question)\s*:|\bA\s*[:.\)]", answer):
        answer = _innermost_answer(answer)
    question = _innermost_question(answer, question)
    if len(question) > 700:
        question = question[:700]
    if len(answer) > 1200:
        answer = answer[:1200]
    return f"Q: {question}\nA: {answer}"


def _innermost_question(answer, fallback):
    """Recover the question from an answer that still carries a Q: prefix."""
    m = re.search(r"(?is)(?:^|\n)\s*Q(?:uestion)?\s*[:.\)]\s*(.+?)(?:\n\s*A\s*[:.\)]|$)", answer)
    if m and m.group(1).strip():
        return m.group(1).strip()
    return fallback


def _jaccard(a: str, b: str) -> float:
    ta, tb = set(a.lower().split()), set(b.lower().split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


class RAGSystem:
    """Bounded hybrid-retrieval memory with an answerability gate."""

    def __init__(self, config, embedder):
        self.config = config
        self.embedder = embedder

        # chunk store
        self.chunks = []            # list[dict]: text, meta, ts, tf, len, terms
        self.embeddings = None      # np.float32 [n, dim] L2-normalised
        self._ids = set()
        self._lock = threading.RLock()

        # lexical index
        self._postings = {}         # term -> list[chunk_idx]
        self._df = {}               # term -> document frequency
        self._avg_len = 1.0

        # answer cache (instant repeats, zero LLM)
        self._cache = OrderedDict()
        self._cache_lock = threading.Lock()

        self._save_timer = None
        self._last_save = 0.0
        self._dirty = False
        self._seq = 0

        def _cfg(name, default, cast=float):
            try:
                return cast(getattr(config, name, default))
            except Exception:
                return cast(default)

        self.max_chunks = int(_cfg("RAG_MAX_DOCS", 6000, int))
        self.chunk_chars = int(_cfg("RAG_CHUNK_CHARS", 320, int))
        self.chunk_overlap = int(_cfg("RAG_CHUNK_OVERLAP", 60, int))
        self.save_debounce_s = float(_cfg("RAG_SAVE_DEBOUNCE_S", 45, float))
        self.top_k = int(_cfg("RAG_TOP_K", 4, int))
        self.direct_threshold = float(_cfg("RAG_DIRECT_ANSWER", 0.72, float))
        self.cache_ttl_s = float(_cfg("RAG_CACHE_TTL_S", 1800, float))
        self.min_terms = int(_cfg("RAG_MIN_TERMS", 2, int))
        self.dim = int(_cfg("EMBED_DIM", 384, int))

        self.index_path = os.path.join(str(config.MODELS_DIR), "rag_index_v2.npz")
        self._load_index()

    # ══════════════════════════════════════════════════════════════════════
    # writes
    # ══════════════════════════════════════════════════════════════════════
    def add_document(self, text, metadata=None):
        """Index one source document. Returns the number of chunks added.

        Memory-only + debounced persist: <2ms on the request path.
        """
        chunks = _split_chunks(_normalize_qa(text), self.chunk_chars, self.chunk_overlap)
        if not chunks:
            return 0
        added, vectors = 0, []
        meta = metadata or {}
        with self._lock:
            for chunk in chunks:
                key = hashlib.md5(chunk.encode("utf-8")).hexdigest()[:16]
                if key in self._ids:
                    continue
                toks = _norm_tokens(chunk)
                if not toks:
                    continue
                idx = len(self.chunks)
                tf = {}
                for t in toks:
                    tf[t] = tf.get(t, 0) + 1
                rec = {
                    "id": key,
                    "text": chunk,
                    "metadata": meta,
                    "ts": time.time(),
                    "tf": tf,
                    "len": len(toks),
                    "terms": set(tf),
                    "hits": 0,          # retrieval hit counter (drives eviction)
                    "good": 0,          # human-approved counter
                }
                self.chunks.append(rec)
                self._ids.add(key)
                for term in tf:
                    self._postings.setdefault(term, []).append(idx)
                    self._df[term] = self._df.get(term, 0) + 1
                added += 1
                vec = self._embed(chunk)
                if vec is not None:
                    vectors.append(vec)
            if added:
                self._recompute_avg_len()
                self._append_embeddings(vectors)
                self._dirty = True
        if added:
            self._prune_locked()
            self._schedule_save()
        return added

    # Back-compat alias used across the codebase / hot path.
    def add_and_index(self, text, metadata=None):
        return self.add_document(text, metadata)

    def build_index(self, texts, metadatas=None):
        with self._lock:
            self._reset_locked()
        for i, text in enumerate(texts or []):
            meta = metadatas[i] if metadatas and i < len(metadatas) else {}
            self.add_document(text, meta)
        self._save_now()
        return len(self.chunks)

    def _embed(self, text):
        if self.embedder is None:
            return None
        try:
            if _np is not None:
                return _np.asarray(self.embedder.embed(text), dtype=_np.float32)
            t = self.embedder.embed(text)
            return t.detach().cpu().numpy().astype("float32") if t is not None else None
        except Exception:
            return None

    def _append_embeddings(self, vectors):
        if not vectors or _np is None:
            return
        mat = _np.vstack(vectors)
        norms = _np.linalg.norm(mat, axis=1, keepdims=True)
        _np.divide(mat, norms, out=mat, where=norms > 0)
        self.embeddings = mat if self.embeddings is None else _np.vstack([self.embeddings, mat])

    def _reset_locked(self):
        self.chunks = []
        self.embeddings = None
        self._ids = set()
        self._postings = {}
        self._df = {}
        self._avg_len = 1.0

    def _recompute_avg_len(self):
        if not self.chunks:
            self._avg_len = 1.0
            return
        self._avg_len = sum(c["len"] for c in self.chunks) / float(len(self.chunks))

    def _prune_locked(self):
        """Score-aware eviction: keep recent + retrieval-proven chunks.

        v1 dropped the oldest N, which silently deleted exactly the facts the
        internet learner had verified. Now we evict the least valuable
        (low hit count, oldest) and only when the cap is actually exceeded.
        """
        overflow = len(self.chunks) - self.max_chunks
        if overflow <= 0:
            return
        ranked = sorted(
            range(len(self.chunks)),
            key=lambda i: (self.chunks[i]["hits"] * 2 + self.chunks[i]["good"] * 5, self.chunks[i]["ts"]),
        )
        drop = set(ranked[:overflow])
        keep = [i for i in range(len(self.chunks)) if i not in drop]
        self.chunks = [self.chunks[i] for i in keep]
        self._ids = {c["id"] for c in self.chunks}
        if self.embeddings is not None and _np is not None and keep:
            self.embeddings = self.embeddings[_np.asarray(keep, dtype=_np.int64)]
        # rebuild postings (indices shifted)
        self._postings = {}
        self._df = {}
        for idx, rec in enumerate(self.chunks):
            for term in rec["tf"]:
                self._postings.setdefault(term, []).append(idx)
                self._df[term] = self._df.get(term, 0) + 1
        self._recompute_avg_len()

    def promote(self, chunk_ids, good=True):
        """Reinforce chunks behind a human-approved answer (human-eval loop)."""
        wanted = set(chunk_ids or [])
        if not wanted:
            return
        with self._lock:
            for rec in self.chunks:
                if rec["id"] in wanted:
                    rec["good" if good else "hits"] += 1
            self._dirty = True

    # ══════════════════════════════════════════════════════════════════════
    # retrieval
    # ══════════════════════════════════════════════════════════════════════
    def _bm25(self, terms):
        """BM25 over the inverted index. Returns {chunk_idx: score}."""
        n = len(self.chunks)
        if n == 0:
            return {}
        scores = {}
        for term in terms:
            if "_" in term:      # bigrams only via dense path — keeps BM25 cheap
                continue
            postings = self._postings.get(term)
            if not postings:
                continue
            df = self._df.get(term, 1)
            idf = math.log(1.0 + (n - df + 0.5) / (df + 0.5))
            for idx in postings:
                rec = self.chunks[idx]
                if rec["len"] == 0:
                    continue
                tf = rec["tf"].get(term, 0)
                if not tf:
                    continue
                denom = tf + _BM25_K1 * (1 - _BM25_B + _BM25_B * rec["len"] / self._avg_len)
                scores[idx] = scores.get(idx, 0.0) + idf * (tf * (_BM25_K1 + 1)) / max(denom, 1e-6)
        return scores

    def _dense_top(self, query, pool, limit):
        if self.embeddings is None or _np is None or not len(self.embeddings):
            return {}
        vec = self._embed(query)
        if vec is None or vec.size != self.embeddings.shape[1]:
            return {}
        nrm = float(_np.linalg.norm(vec))
        if nrm <= 0:
            return {}
        vec = vec / nrm
        if pool:
            sims = self.embeddings[_np.asarray(pool, dtype=_np.int64)] @ vec
            return {int(pool[i]): float(sims[i]) for i in range(len(pool))}
        sims = self.embeddings @ vec
        if len(sims) > limit:
            top = _np.argpartition(-sims, limit)[:limit]
            return {int(i): float(sims[i]) for i in top}
        return {int(i): float(sims[i]) for i in range(len(sims))}

    def search(self, query, k=None, min_confidence=0.0):
        """Hybrid retrieve with a confidence gate.

        Returns {answerable, confidence, results:[{text,score,bm25,dense,meta}], ms}
        `answerable=False` means "memory does not contain this" — the caller
        MUST fall through to the LLM instead of forcing a memory answer.
        """
        t0 = time.perf_counter()
        k = k or self.top_k
        query = (query or "").strip()
        q_terms = _content_terms(query)
        q_uni = {t for t in q_terms if "_" not in t}

        with self._lock:
            n_chunks = len(self.chunks)
            has_emb = self.embeddings is not None
            if n_chunks == 0:
                return {"answerable": False, "confidence": 0.0, "results": [],
                        "reason": "empty_index", "ms": round((time.perf_counter() - t0) * 1000, 2)}
            bm25 = self._bm25(q_terms)
            pool = sorted(bm25, key=lambda i: -bm25[i])[:_CANDIDATE_POOL]
            dense = self._dense_top(query, pool, _CANDIDATE_POOL)

            # RRF fusion over the union of candidates (rank-based, so BM25 and
            # cosine score scales never have to be reconciled).
            fused = {}
            for rank, i in enumerate(sorted(bm25, key=lambda i: -bm25[i])[:_CANDIDATE_POOL]):
                fused[i] = fused.get(i, 0.0) + 1.0 / (_RRF_K + rank + 1)
            for rank, i in enumerate(sorted(dense, key=lambda i: -dense[i])[:_CANDIDATE_POOL]):
                fused[i] = fused.get(i, 0.0) + 1.0 / (_RRF_K + rank + 1)
            if not fused:
                return {"answerable": False, "confidence": 0.0, "results": [],
                        "reason": "no_candidates", "ms": round((time.perf_counter() - t0) * 1000, 2)}

            top_ranked = sorted(fused, key=lambda i: -fused[i])[:k]
            best_fused = max(fused.values()) or 1e-6

            results = []
            for i in top_ranked:
                rec = self.chunks[i]
                rec["hits"] += 1
                share = fused[i] / best_fused                     # 0..1 relative confidence
                coverage = (len(q_uni & rec["terms"]) / len(q_uni)) if q_uni else 0.0
                # lexical + dense agreement bonus (catches paraphrase hits)
                agree = 0.0
                if i in bm25 and i in dense:
                    agree = 0.15
                score = round(min(1.0, 0.70 * share + 0.20 * coverage + agree), 4)
                results.append({
                    "id": rec["id"],
                    "text": rec["text"],
                    "score": score,
                    "bm25": round(bm25.get(i, 0.0), 3),
                    "dense": round(dense.get(i, 0.0), 3),
                    "coverage": round(coverage, 3),
                    "metadata": rec.get("metadata", {}),
                })
            self._dirty = True

        # Absolute confidence: needs BOTH a strong relative score and real term
        # coverage. This is what stops a hash/DPR coincidence becoming an answer.
        top = results[0] if results else None
        confidence = 0.0
        if top is not None:
            confidence = round(top["score"] * (0.5 + 0.5 * top["coverage"]), 4)
        answerable = bool(
            top
            and len(q_uni) >= self.min_terms
            and confidence >= max(min_confidence, 0.0)
            and top["coverage"] >= 0.34
        )
        return {
            "answerable": answerable,
            "confidence": confidence,
            "results": results,
            "terms": len(q_uni),
            "ms": round((time.perf_counter() - t0) * 1000, 2),
        }

    def retrieve(self, query, k=None, threshold=None):
        """Back-compat: list of {text, score, cosine, metadata} above threshold."""
        thr = self.direct_threshold if threshold is None else float(threshold)
        out = []
        for r in self.search(query, k=k)["results"]:
            if r["score"] >= thr:
                out.append({
                    "text": r["text"], "score": r["score"], "cosine": r["dense"],
                    "metadata": r.get("metadata", {}),
                })
        return out

    def retrieve_with_context(self, query, k=None):
        res = self.search(query, k=k)
        if not res["results"]:
            return "", []
        blocks = []
        for i, r in enumerate(res["results"]):
            src = (r.get("metadata") or {}).get("source") or "memory"
            blocks.append(f"[Memory {i+1} · {r['score']} · {src}]: {r['text']}")
        return "\n\n".join(blocks), res["results"]

    # ══════════════════════════════════════════════════════════════════════
    # extractive answering (zero LLM calls) + answer cache
    # ══════════════════════════════════════════════════════════════════════
    def _extract_answer(self, query, top, max_sentences=3):
        """Pick the sentences inside a chunk that actually answer the query.

        Pure extraction — nothing is generated, so nothing can be hallucinated.
        Learned chunks are stored as "Q: ...\\nA: ...", so the question line is
        skipped: echoing the question back to someone who just asked it is a
        useless answer, and the sentence after the A: marker is the real one.
        """
        raw = top["text"]
        # Tolerate every learned shape: canonical "Q: ..\nA: ..", inline
        # "Q: .. A: ..", and chained leftovers from before normalisation
        # ("Q: q? A: Q: q? A: real answer"). The split takes the text after
        # the first answer marker, then _innermost_answer peels any further
        # nested layers, so a chained chunk still yields the real answer and
        # never the question.
        m = re.search(r"(?is)(?:^|\n|\s)A\s*[:.\)]\s*", raw)
        answer_side = raw[m.end():] if m else raw
        answer_side = _innermost_answer(answer_side)
        # Chunks learned from workers can already carry Q:/A: markers, and
        # nested markers would otherwise leak into the user's reply as
        # "A: The capital of France is ...".
        answer_side = re.sub(r"(?im)^\s*(?:Q|A|QnA|Ans|Answer)\s*[:.\)]\s*", "", answer_side).strip()
        sentences = [s.strip() for s in _SENT_SPLIT_RE.split(answer_side) if s.strip()]
        sentences = [s for s in sentences if not re.match(r"^\s*(?:q|question)\s*[:.]", s, re.I)]
        if not sentences:
            sentences = [s.strip() for s in _SENT_SPLIT_RE.split(raw) if s.strip()]
        if not sentences:
            return ""

        q_uni = {t for t in _content_terms(query) if "_" not in t}
        if not q_uni:
            return ""
        scored = []
        norm_q_full = " ".join(_norm_tokens(query))
        for pos, s in enumerate(sentences):
            # Question sentences can never be answers. A multi-sentence chunk
            # can contain BOTH the question and its answer ("What is X? The
            # answer is Y."), and picking returned the whole thing — including
            # the question — because only the top sentence was checked.
            s_run = s.strip()
            if s_run.endswith("?"):
                continue
            if norm_q_full and " ".join(_norm_tokens(s_run)) == norm_q_full:
                continue
            s_uni = {t for t in _norm_tokens(s_run)}
            overlap = q_uni & s_uni
            if not overlap and pos:
                # Later sentences with no overlap are usually trailing noise.
                continue
            score = len(overlap) / (1.0 + 0.02 * pos)     # slight bias to earlier context
            if pos == 0:
                # The first sentence of a stored "Q:/A:" chunk IS the answer,
                # and a short factoid answer ("Paris.") shares no words with
                # its question. Chunk-level coverage already gated relevance,
                # so do not require sentence-level overlap here — otherwise
                # every concise factual answer is discarded.
                score += 1.2
            if re.search(r"\b(?:is|are|was|were|has|have|had)\b", s):
                score += 0.6                                  # declarative answers
            if re.search(r"\d", s):
                score += 0.3                                  # factual answers carry numbers
            if s.endswith("?"):
                score -= 1.5                                  # never answer with a question
            if re.match(r"^\s*(?:q|question)\s*[:.]", s, re.I):
                score -= 3.0
            if len(_norm_tokens(s)) < 2:
                score -= 1.0                                  # "That." is not an answer
            scored.append((score, pos, s))
        if not scored:
            return ""
        scored.sort(key=lambda x: (-x[0], x[1]))
        # HARD RULE: a question is never an answer. Echoing the user's own
        # question back at them looks like a reply but carries no information,
        # and it happened constantly once learned chunks began storing the
        # question text alongside the answer. (The loop above already skips
        # ?-sentences; this is the belt-and-braces net for any path that gets
        # past it.)
        if not scored or scored[0][2].rstrip().endswith("?"):
            return ""
        picked = sorted(scored[:max_sentences], key=lambda x: x[1])
        out = " ".join(s for _, _, s in picked).strip()
        if len(out) > 600:
            out = out[:600]
        elif not out.endswith((".", "!", "?", "…")):
            out += "."
        # HARD RULE: if what we extracted is just the question again, there is
        # no answer here — report "not answerable" so the caller generates one.
        norm_out = " ".join(_norm_tokens(out))
        norm_q = " ".join(_norm_tokens(query))
        if norm_q and (norm_out == norm_q or norm_out in norm_q):
            return ""
        return out

    def answer(self, query, k=None, min_confidence=None, use_cache=True):
        """Answer from memory when (and only when) confidence is high enough.

        This is the fast path that makes repeat questions feel instant:
        retrieval + extraction only, no Ollama round trip.
        """
        query = (query or "").strip()
        if not query:
            return {"answerable": False, "answer": "", "confidence": 0.0,
                    "sources": [], "cached": False, "ms": 0.0}
        t0 = time.perf_counter()
        key = " ".join(_norm_tokens(query))[:200]

        if use_cache:
            with self._cache_lock:
                hit = self._cache.get(key)
                if hit and (time.time() - hit["ts"]) < self.cache_ttl_s:
                    self._cache.move_to_end(key)
                    return {**hit["payload"], "cached": True,
                            "ms": round((time.perf_counter() - t0) * 1000, 2)}

        thr = self.direct_threshold if min_confidence is None else float(min_confidence)
        res = self.search(query, k=k, min_confidence=thr)
        payload = {
            "answerable": bool(res["answerable"]),
            "answer": "",
            "confidence": res["confidence"],
            "context": "",
            "sources": [],
            "ms": round((time.perf_counter() - t0) * 1000, 2),
        }
        if not res["answerable"]:
            if res["results"]:
                payload["context"] = self._format_context(res["results"])
                payload["sources"] = [(r.get("metadata") or {}).get("source") for r in res["results"]]
            return payload

        top = res["results"][0]
        answer = self._extract_answer(query, top)
        if not answer.strip():
            # Retrieval looked confident but nothing in the chunk actually
            # addresses the question. Report "not answerable" rather than an
            # empty answer with a high confidence — callers must fall through
            # to the model instead of rendering a blank bubble.
            payload["answerable"] = False
            payload["confidence"] = 0.0
            payload["context"] = self._format_context(res["results"])
            return payload
        payload["answer"] = answer
        payload["context"] = self._format_context(res["results"])
        payload["sources"] = [(r.get("metadata") or {}).get("source") for r in res["results"]]
        payload["ids"] = [r["id"] for r in res["results"]]
        self.promote([r["id"] for r in res["results"]], good=True)
        if use_cache:
            with self._cache_lock:
                self._cache[key] = {"ts": time.time(), "payload": {**payload, "cached": False}}
                self._cache.move_to_end(key)
                while len(self._cache) > 512:
                    self._cache.popitem(last=False)
        self._schedule_save()
        return payload

    def _format_context(self, results):
        blocks = []
        for i, r in enumerate(results):
            src = (r.get("metadata") or {}).get("source") or "memory"
            blocks.append(f"[Memory {i+1} · conf {r['score']} · {src}]: {r['text']}")
        return "\n\n".join(blocks)

    # ══════════════════════════════════════════════════════════════════════
    # persistence (debounced, atomic, bounded)
    # ══════════════════════════════════════════════════════════════════════
    def stats(self):
        with self._lock:
            n = len(self.chunks)
            terms = len(self._df)
        try:
            size = os.path.getsize(self.index_path) if os.path.exists(self.index_path) else 0
        except Exception:
            size = 0
        return {
            "chunks": n, "max_chunks": self.max_chunks, "unique_terms": terms,
            "index_bytes": size, "cache_entries": len(self._cache),
            "chunk_chars": self.chunk_chars, "direct_threshold": self.direct_threshold,
            "avg_chunk_tokens": round(self._avg_len, 1),
            "last_save": self._last_save, "dirty": self._dirty,
        }

    def clear(self):
        with self._lock:
            self._reset_locked()
        with self._cache_lock:
            self._cache.clear()
        self._save_now()

    def flush(self):
        self._save_now()

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

    def _save_now(self):
        with self._lock:
            if not self.chunks:
                self._dirty = False
                return
            texts = [c["text"] for c in self.chunks]
            metas = [c.get("metadata", {}) for c in self.chunks]
            ts = [c.get("ts", 0.0) for c in self.chunks]
            hits = [c.get("hits", 0) for c in self.chunks]
            good = [c.get("good", 0) for c in self.chunks]
            ids = [c["id"] for c in self.chunks]
            embs = self.embeddings
            self._dirty = False
        try:
            os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
            tmp = self.index_path + ".tmp"
            if _np is not None:
                _np.savez_compressed(
                    tmp,
                    texts=_np.array(texts, dtype=object),
                    metas=_np.array([_jsonable(m) for m in metas], dtype=object),
                    ts=_np.array(ts, dtype="float64"),
                    hits=_np.array(hits, dtype="int32"),
                    good=_np.array(good, dtype="int32"),
                    ids=_np.array(ids, dtype=object),
                    embeddings=embs if embs is not None else _np.zeros((0, self.dim), dtype="float32"),
                )
            elif torch is not None:
                torch.save({"texts": texts, "metadata": metas, "ts": ts,
                            "hits": hits, "good": good, "ids": ids,
                            "embeddings": embs}, tmp)
            else:
                return
            # np.savez appends .npz when the path lacks it
            produced = tmp if os.path.exists(tmp) else tmp + ".npz"
            os.replace(produced, self.index_path)
            self._last_save = time.time()
        except Exception:
            pass

    def _load_index(self):
        try:
            if not os.path.exists(self.index_path):
                # Migration must never block startup: the brain serves traffic
                # from the first request, and re-chunking thousands of legacy
                # documents took ~2 minutes. Run it in the background instead.
                legacy = os.path.join(os.path.dirname(self.index_path), "rag_index.pt")
                if os.path.exists(legacy) and torch is not None:
                    t = threading.Thread(target=self._migrate_v1, daemon=True,
                                         name="acronous-rag-migrate")
                    t.start()
                return
            if _np is not None and self.index_path.endswith(".npz"):
                data = _np.load(self.index_path, allow_pickle=True)
                texts = list(data["texts"])
                metas = list(data["metas"])
                ts = list(data["ts"])
                hits = list(data["hits"]) if "hits" in data else [0] * len(texts)
                good = list(data["good"]) if "good" in data else [0] * len(texts)
                ids = list(data["ids"]) if "ids" in data else []
                embs = data["embeddings"] if "embeddings" in data else None
            elif torch is not None:
                data = torch.load(self.index_path, map_location="cpu", weights_only=False)
                texts = data.get("texts", [])
                metas = data.get("metadata", [])
                ts = data.get("ts", [0.0] * len(texts))
                hits = data.get("hits", [0] * len(texts))
                good = data.get("good", [0] * len(texts))
                ids = data.get("ids", [])
                embs = data.get("embeddings")
            else:
                return
            if not texts:
                return
            start = max(0, len(texts) - self.max_chunks)
            texts, metas = texts[start:], metas[start:]
            ts, hits, good = ts[start:], hits[start:], good[start:]
            ids = ids[start:] if ids else []
            with self._lock:
                self._reset_locked()
                for i, text in enumerate(texts):
                    toks = _norm_tokens(text)
                    if not toks:
                        continue
                    tf = {}
                    for t in toks:
                        tf[t] = tf.get(t, 0) + 1
                    key = ids[i] if i < len(ids) else hashlib.md5(str(text).encode("utf-8")).hexdigest()[:16]
                    idx = len(self.chunks)
                    self.chunks.append({
                        "id": key, "text": str(text),
                        "metadata": _from_jsonable(metas[i]) if i < len(metas) else {},
                        "ts": float(ts[i]) if i < len(ts) else 0.0,
                        "tf": tf, "len": len(toks), "terms": set(tf),
                        "hits": int(hits[i]) if i < len(hits) else 0,
                        "good": int(good[i]) if i < len(good) else 0,
                    })
                    self._ids.add(key)
                    for term in tf:
                        self._postings.setdefault(term, []).append(idx)
                        self._df[term] = self._df.get(term, 0) + 1
                if embs is not None and _np is not None and len(embs) == len(texts):
                    self.embeddings = _np.asarray(embs, dtype=_np.float32)
                self._recompute_avg_len()
        except Exception:
            pass

    # Back-compat shims for callers that used the v1 shape.
    @property
    def documents(self):
        return self.chunks

    def _migrate_v1(self):
        """Import a v1 `rag_index.pt` corpus into v2 on first boot.

        v1 stored whole 1500-char documents in a torch file. The brain had
        thousands of learned documents there (internet sweeps + human-eval
        turns) and re-learning them from scratch would take days, so they are
        re-chunked and re-indexed once, automatically, on the first start with
        no v2 index present.
        """
        legacy = os.path.join(os.path.dirname(self.index_path), "rag_index.pt")
        if not os.path.exists(legacy) or torch is None:
            return
        try:
            data = torch.load(legacy, map_location="cpu", weights_only=False)
        except Exception:
            return
        docs = data.get("documents") or []
        if not docs:
            return
        migrated = 0
        for doc in docs[-int(self.max_chunks * 1.2):]:
            text = (doc.get("text") or "").strip()
            if len(text) < 20:
                continue
            try:
                migrated += self.add_document(text, doc.get("metadata") or {})
            except Exception:
                continue
        logger = __import__("logging").getLogger(__name__)
        logger.info("[RAG] migrated %d documents from the v1 index into v2", migrated)
        self._save_now()

    def reindex(self, limit=None):
        """Rebuild the whole index from `self.chunks` (repair/heal helper)."""
        with self._lock:
            payload = [(c["text"], c.get("metadata", {})) for c in self.chunks]
        if limit:
            payload = payload[-int(limit):]
        with self._lock:
            self._reset_locked()
        for text, meta in payload:
            self.add_document(text, meta)
        self._save_now()
        return len(self.chunks)


def _jsonable(value):
    try:
        import json
        return json.loads(json.dumps(value, default=str))
    except Exception:
        return {}


def _from_jsonable(value):
    return value if isinstance(value, dict) else {}
