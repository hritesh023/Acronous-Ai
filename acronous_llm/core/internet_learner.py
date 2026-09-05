"""Autonomous internet learner for the Acronous brain.

This module lets the shared `acronous_llm` brain keep growing even when NO
user is interacting with EquiVO, Navigwiz, or Acronous AI. It runs multiple
learning phases on a background schedule:

  Phase 1 — Quick Scan (every 5 min):
    Rotates through 30+ knowledge domains, searches the open web, fetches
    full page content, extracts facts, and stores them.

  Phase 2 — Deep Dive (every 30 min):
    Picks the freshest/most important topics from the quick scan, fetches
    full articles, extracts concepts and relationships, builds knowledge
    graph edges, and cross-references facts.

  Phase 3 — Self-Evaluation (every 2 hours):
    Analyzes knowledge gaps, identifies stale facts, prunes outdated
    knowledge, and generates learning priorities for the next cycle.

It is fully self-hosted: only internet *data fetching* (which is allowed by
project policy) happens here — never an external LLM model service.
"""
import re
import time
import logging
import hashlib
import threading
import json
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)

# ── Knowledge domains (30+) ────────────────────────────────────────────────
# Organized by category for smarter rotation. Each entry is (domain, weight)
# where weight controls how often/prioritized it is (higher = more often).
KNOWLEDGE_DOMAINS = {
    # Technology & AI
    "artificial intelligence news": 1.0,
    "machine learning breakthroughs": 0.9,
    "large language model updates": 1.0,
    "AI regulation and ethics": 0.7,
    "robotics and automation": 0.8,
    "quantum computing advances": 0.6,
    "cybersecurity news": 0.8,
    "cloud computing trends": 0.6,
    "blockchain and web3": 0.5,
    "open source software releases": 0.7,
    # Science
    "space exploration and astronomy": 0.8,
    "medical and health research": 0.9,
    "climate science and environment": 0.8,
    "physics and mathematics breakthroughs": 0.6,
    "biology and genetics discoveries": 0.7,
    "chemistry research": 0.5,
    "neuroscience findings": 0.6,
    # World & Economy
    "economics and global markets": 0.8,
    "geopolitics and world news": 0.7,
    "cryptocurrency and finance": 0.6,
    "startup and venture capital": 0.6,
    "energy and sustainability": 0.7,
    # Culture & Knowledge
    "software engineering best practices": 0.8,
    "history facts and discoveries": 0.5,
    "philosophy and ethics": 0.4,
    "psychology research": 0.6,
    "education technology": 0.5,
    # Product & Industry
    "product launches and reviews": 0.7,
    "developer tools and frameworks": 0.8,
    "data science and analytics": 0.7,
    "natural language processing": 0.8,
    "computer vision advances": 0.7,
    "edge computing and IoT": 0.5,
}

# Real-time RSS/news feeds for breaking information
REALTIME_FEEDS = [
    ("https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtVnVHZ0pWVXlnQVAB?hl=en-US&gl=US&ceid=US:en", "AI News"),
    ("https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtVnVHZ0pWVXlnQVAB?hl=en-US&gl=US&ceid=US:en", "Tech News"),
    ("https://news.google.com/rss/topics/CAAqKggKIiRDQkFTRlFvSUwyMHZNRFp1ZEdvU0FtVnVHZ0pKVGlnQVAB?hl=en-US&gl=US&ceid=US:en", "Science"),
    ("https://news.google.com/rss/search?q=artificial+intelligence+OR+AI+OR+LLM&hl=en-US&gl=US&ceid=US:en", "AI/LLM"),
    ("https://news.google.com/rss/search?q=breaking+technology+news&hl=en-US&gl=US&ceid=US:en", "Breaking Tech"),
    ("https://news.google.com/rss/search?q=space+exploration+OR+NASA+OR+SpaceX&hl=en-US&gl=US&ceid=US:en", "Space"),
    ("https://news.google.com/rss/search?q=medical+breakthrough+OR+health+research&hl=en-US&gl=US&ceid=US:en", "Health"),
]


class KnowledgeGraph:
    """Tracks concepts and their relationships extracted from learned facts."""

    def __init__(self, persist_path=None):
        self.persist_path = persist_path
        self.concepts = {}        # concept -> {count, last_seen, sources[]}
        self.edges = defaultdict(lambda: defaultdict(int))  # concept_a -> concept_b -> strength
        self._load()

    def extract_concepts(self, text):
        """Extract key concepts/entities from text using simple heuristics."""
        if not text:
            return []
        concepts = set()
        # Extract capitalized phrases (potential proper nouns / entities)
        for m in re.finditer(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b', text):
            c = m.group(1).strip()
            if len(c) > 2 and c not in {'The', 'This', 'That', 'What', 'How', 'When', 'Where', 'Which', 'According', 'However', 'Moreover', 'Furthermore', 'Also', 'Then', 'Now', 'But', 'And', 'For', 'Not', 'You', 'His', 'Her', 'Its', 'Our', 'Their', 'Can', 'Has', 'Had', 'Was', 'Were', 'Are', 'Will', 'Would', 'Could', 'Should'}:
                concepts.add(c)
        # Extract tech/domain terms
        tech_patterns = [
            r'\b(GPT-\d+|LLaMA|LLaVa|Claude|Gemini|Grok|Mistral|Qwen|DeepSeek)\b',
            r'\b(Python|JavaScript|Rust|Go|TypeScript|Swift|Kotlin|Java|C\+\+)\b',
            r'\b(Python|JavaScript|Rust|Go|TypeScript|Swift|Kotlin|Java|C\+\+)\b',
            r'\b(PyTorch|TensorFlow|Keras|Scikit|Pandas|NumPy)\b',
            r'\b(Docker|Kubernetes|AWS|Azure|GCP|Cloudflare)\b',
            r'\b(OpenAI|Anthropic|Google|Meta|Microsoft|Apple|NVIDIA|Tesla)\b',
        ]
        for pat in tech_patterns:
            for m in re.finditer(pat, text, re.IGNORECASE):
                concepts.add(m.group(1))
        return list(concepts)[:20]

    def add_fact(self, text, source=None):
        """Add a fact and extract concepts + relationships."""
        concepts = self.extract_concepts(text)
        # Update concept registry
        for c in concepts:
            if c not in self.concepts:
                self.concepts[c] = {"count": 0, "last_seen": None, "sources": []}
            self.concepts[c]["count"] += 1
            self.concepts[c]["last_seen"] = datetime.now().isoformat()
            if source and source not in self.concepts[c]["sources"]:
                self.concepts[c]["sources"].append(source)
                if len(self.concepts[c]["sources"]) > 10:
                    self.concepts[c]["sources"] = self.concepts[c]["sources"][-10:]
        # Build co-occurrence edges (concepts in same fact are related)
        for i, a in enumerate(concepts):
            for b in concepts[i+1:]:
                self.edges[a][b] += 1
                self.edges[b][a] += 1
        return concepts

    def get_related(self, concept, top_k=5):
        """Get most related concepts to a given concept."""
        if concept not in self.edges:
            return []
        related = sorted(self.edges[concept].items(), key=lambda x: -x[1])
        return related[:top_k]

    def get_important_concepts(self, top_k=20):
        """Get the most frequently seen concepts."""
        sorted_concepts = sorted(self.concepts.items(), key=lambda x: -x[1]["count"])
        return [(c, d["count"]) for c, d in sorted_concepts[:top_k]]

    def get_stale_concepts(self, days=30):
        """Get concepts not seen in the last N days."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        return [c for c, d in self.concepts.items()
                if d.get("last_seen") and d["last_seen"] < cutoff]

    def _save(self):
        if not self.persist_path:
            return
        try:
            import os
            os.makedirs(os.path.dirname(self.persist_path), exist_ok=True)
            with open(self.persist_path, 'w', encoding='utf-8') as f:
                json.dump({
                    "concepts": self.concepts,
                    "edges": dict(self.edges),
                }, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _load(self):
        if not self.persist_path:
            return
        try:
            with open(self.persist_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.concepts = data.get("concepts", {})
            raw_edges = data.get("edges", {})
            for a, neighbors in raw_edges.items():
                for b, strength in neighbors.items():
                    self.edges[a][b] = strength
        except Exception:
            pass


class InternetLearner:
    """Continuously grows the brain's knowledge from the open web.

    Three learning phases run on different schedules:
      - Quick scan: every 5 minutes, 3-5 rotating topics
      - Deep dive: every 30 minutes, full article extraction
      - Self-eval: every 2 hours, gap detection and pruning
    """

    def __init__(self, config, memory, rag, neural, web_search, device=None):
        self.config = config
        self.memory = memory          # core.memory (SQLite knowledge store)
        self.rag = rag                # core.rag (vector memory)
        self.neural = neural          # neural engine (classifier + learner)
        self.web = web_search         # core.search.WebSearch
        self._stop = threading.Event()
        self._thread = None
        self._seen = set(self._load_seen())
        self._stats = {
            "learned": 0, "searches": 0, "last_run": None,
            "deep_dives": 0, "facts_verified": 0, "stale_pruned": 0,
            "gaps_identified": 0, "concepts_tracked": len(KNOWLEDGE_DOMAINS),
        }
        # Knowledge graph for concept extraction and relationship mapping
        kg_path = str(self.config.MODELS_DIR / "knowledge_graph.json")
        self.knowledge_graph = KnowledgeGraph(persist_path=kg_path)
        # Track what topics need deep-diving
        self._pending_deepdives = []
        # Track learning priorities from self-evaluation
        self._learning_priorities = []

    # ── Public control ─────────────────────────────────────────────────
    def start(self, interval_seconds=300):
        """Start the background learning thread (default 5 min for quick scan)."""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            args=(interval_seconds,),
            daemon=True,
            name="internet-learner",
        )
        self._thread.start()
        logger.info("InternetLearner started (interval=%ss)", interval_seconds)
        return self._thread

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("InternetLearner stopped")

    def run_once(self, num_topics=None):
        """Do a single quick-scan learning sweep now."""
        results = self._quick_scan(num_topics=num_topics)
        self._persist_seen()
        return results

    def run_deep_dive(self, num_topics=5):
        """Do a single deep-dive learning sweep (full article extraction)."""
        return self._deep_dive(num_topics=num_topics)

    def run_self_evaluate(self):
        """Analyze knowledge gaps and prune stale facts."""
        return self._self_evaluate()

    def get_stats(self):
        return dict(self._stats)

    # ── Internal loop ──────────────────────────────────────────────────
    def _run_loop(self, interval_seconds):
        cycle = 0
        while not self._stop.is_set():
            try:
                cycle += 1
                # Phase 1: Quick scan every cycle (default 5 min)
                self._quick_scan()

                # Phase 2: Deep dive every 6 cycles (~30 min)
                if cycle % 6 == 0:
                    self._deep_dive()

                # Phase 3: Self-evaluate every 24 cycles (~2 hours)
                if cycle % 24 == 0:
                    self._self_evaluate()

            except Exception as exc:
                logger.warning("internet learning pass failed: %s", exc)
            self._stop.wait(interval_seconds)

    # ── Phase 1: Quick Scan ────────────────────────────────────────────
    def _quick_scan(self, num_topics=None):
        """Rapid scan of rotating topics — stores facts from search snippets + RSS."""
        topics = self._select_topics(num_topics=num_topics or 5)
        learned = 0

        # Also scan real-time RSS feeds for breaking news
        rss_facts = self._scan_rss_feeds()
        learned += rss_facts

        for topic in topics:
            if self._stop.is_set():
                break
            learned += self._learn_topic(topic, depth="quick")
            time.sleep(0.5)  # polite spacing

        self._stats["learned"] += learned
        self._stats["searches"] += len(topics)
        self._stats["last_run"] = datetime.now().isoformat()
        self._save_state()
        return learned

    def _scan_rss_feeds(self):
        """Scan real-time RSS feeds for breaking/fresh news."""
        learned = 0
        for feed_url, feed_name in REALTIME_FEEDS:
            if self._stop.is_set():
                break
            try:
                import requests as _req
                resp = _req.get(feed_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
                if resp.status_code != 200:
                    continue
                items = re.findall(r'<item>[\s\S]*?</item>', resp.text)
                for item in items[:3]:  # top 3 per feed
                    title_m = re.search(r'<title>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?<\/title>', item)
                    link_m = re.search(r'<link>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?<\/link>', item)
                    desc_m = re.search(r'<description>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?<\/description>', item)
                    if not title_m:
                        continue
                    title = title_m.group(1).strip()
                    url = link_m.group(1).strip() if link_m else ""
                    desc = desc_m.group(1).strip() if desc_m else ""
                    desc = re.sub(r'<[^>]+>', '', desc)[:300]

                    fact = self._distill(title, desc)
                    if not fact:
                        continue
                    key = self._fact_key(fact)
                    if key in self._seen:
                        continue
                    self._seen.add(key)
                    self._store_fact(fact, f"rss:{feed_name}", url, confidence=0.7)
                    learned += 1
            except Exception:
                continue
        return learned

    def _select_topics(self, num_topics=5):
        """Select topics using weighted rotation + learning priorities."""
        all_topics = list(KNOWLEDGE_DOMAINS.items())

        # Blend in learning priorities from self-evaluation
        if self._learning_priorities:
            for priority_topic in self._learning_priorities[:3]:
                if priority_topic not in [t for t, _ in all_topics]:
                    all_topics.append((priority_topic, 0.9))

        # Weighted selection: higher weight = more likely to be picked
        import random
        total_weight = sum(w for _, w in all_topics)
        selected = []
        used = set()
        for _ in range(min(num_topics, len(all_topics))):
            r = random.random() * total_weight
            cumulative = 0
            for topic, weight in all_topics:
                if topic in used:
                    continue
                cumulative += weight
                if cumulative >= r:
                    selected.append(topic)
                    used.add(topic)
                    break
        return selected

    # ── Phase 2: Deep Dive ─────────────────────────────────────────────
    def _deep_dive(self, num_topics=5):
        """Deep learning: fetch full articles, extract concepts, build knowledge graph."""
        # Pick topics that had the most new facts in the last quick scan
        # or topics from the pending deep-dive list
        topics = self._pending_deepdives[:num_topics] if self._pending_deepdives else self._select_topics(num_topics)
        self._pending_deepdives = self._pending_deepdives[num_topics:]

        learned = 0
        for topic in topics:
            if self._stop.is_set():
                break
            learned += self._learn_topic(topic, depth="deep")
            time.sleep(1)

        self._stats["deep_dives"] += 1
        self._stats["learned"] += learned
        self._save_state()
        return learned

    # ── Phase 3: Self-Evaluation ───────────────────────────────────────
    def _self_evaluate(self):
        """Analyze what the brain knows and doesn't know, then set priorities."""
        gaps_found = 0

        # 1. Find stale concepts that need refresh
        stale = self.knowledge_graph.get_stale_concepts(days=14)
        if stale:
            for concept in stale[:5]:
                self._learning_priorities.append(f"{concept} latest news")
                gaps_found += 1

        # 2. Find concepts with few sources (need verification)
        underverified = [
            (c, d) for c, d in self.knowledge_graph.concepts.items()
            if d["count"] >= 3 and len(d.get("sources", [])) < 2
        ]
        for concept, _ in underverified[:3]:
            self._learning_priorities.append(f"{concept} verified facts")
            gaps_found += 1

        # 3. Prune very old knowledge from seen set to prevent unbounded growth
        if len(self._seen) > 25000:
            self._seen = set(list(self._seen)[-20000:])

        # 4. Decay confidence on old knowledge in memory
        self._decay_stale_knowledge()

        # 5. Save knowledge graph
        self.knowledge_graph._save()

        self._stats["gaps_identified"] += gaps_found
        self._stats["stale_pruned"] = self._stats.get("stale_pruned", 0) + len(stale)
        self._save_state()
        return gaps_found

    def _decay_stale_knowledge(self):
        """Reduce confidence on knowledge entries older than 30 days."""
        try:
            if not self.memory or not hasattr(self.memory, 'conn'):
                return
            cutoff = (datetime.now() - timedelta(days=30)).isoformat()
            self.memory.cursor.execute(
                "UPDATE knowledge SET confidence = confidence * 0.9 WHERE timestamp < ? AND confidence > 0.1",
                (cutoff,)
            )
            self.memory.conn.commit()
        except Exception:
            pass

    # ── Topic Learning (shared by quick scan and deep dive) ─────────────
    def _learn_topic(self, topic, depth="quick"):
        """Search + fetch + distill + store a single topic."""
        try:
            results = self.web.search(topic, max_results=6 if depth == "deep" else 4)
        except Exception:
            return 0
        if not results:
            return 0

        stored = 0
        new_facts_for_topic = []
        max_results = 5 if depth == "deep" else 3

        for r in results[:max_results]:
            title = (r.get("title") or "").strip()
            snippet = (r.get("snippet") or "").strip()
            url = (r.get("url") or "").strip()
            if not title or not url:
                continue

            # For deep dive: fetch full page content
            full_content = ""
            if depth == "deep" and url:
                try:
                    full_content = self.web.fetch_page_content(url, max_chars=3000)
                except Exception:
                    pass

            # Build fact from whatever content we have
            if full_content and len(full_content) > 100:
                fact = self._distill_deep(title, full_content)
            else:
                fact = self._distill(title, snippet)

            if not fact:
                continue
            key = self._fact_key(fact)
            if key in self._seen:
                continue
            self._seen.add(key)

            self._store_fact(fact, topic, url, confidence=0.6 if depth == "quick" else 0.8)
            new_facts_for_topic.append(fact)
            stored += 1

            # Extract concepts and build knowledge graph
            try:
                self.knowledge_graph.add_fact(fact, source=topic)
            except Exception:
                pass

        # If we learned several facts about a topic, mark it for potential deep dive
        if stored >= 2 and depth == "quick":
            self._pending_deepdives.append(topic)

        return stored

    def _store_fact(self, fact, topic, url, confidence=0.6):
        """Store a fact in all three memory systems."""
        if self.memory:
            try:
                key = self._fact_key(fact)
                self.memory.store_knowledge(key, fact, source="internet", confidence=confidence)
            except Exception:
                pass
        if self.rag:
            try:
                self.rag.add_and_index(
                    fact,
                    {"type": "internet_learned", "topic": topic, "url": url, "source": "web"}
                )
            except Exception:
                pass
        try:
            self.neural.learn_from_interaction(
                topic, fact, "web_search",
                session_id="__auto__internet", feedback_score=0.5,
            )
        except Exception:
            pass

    # ── Fact Distillation ──────────────────────────────────────────────
    @staticmethod
    def _distill(title, snippet):
        """Build a compact fact string from a search title/snippet."""
        parts = [title]
        if snippet:
            clean = re.sub(r"\s+", " ", snippet).strip(" .")
            if clean and len(clean) > 20:
                parts.append(clean)
        fact = " | ".join(parts)
        return fact[:2000]

    @staticmethod
    def _distill_deep(title, content):
        """Build a richer fact from full article content."""
        parts = [title]
        if content:
            # Extract the first few meaningful sentences
            sentences = re.split(r'(?<=[.!?])\s+', content)
            meaningful = [s.strip() for s in sentences if len(s.strip()) > 40 and not s.strip().startswith(('Advertisement', 'Subscribe', 'Sign up', 'Cookie', 'Privacy'))]
            if meaningful:
                parts.extend(meaningful[:3])
        fact = " | ".join(parts)
        return fact[:2000]

    @staticmethod
    def _fact_key(fact):
        return hashlib.sha256(fact.encode("utf-8")).hexdigest()[:20]

    # ── State persistence ──────────────────────────────────────────────
    def _load_seen(self):
        try:
            seen_path = self.config.MODELS_DIR / "internet_learned.json"
            with open(seen_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _persist_seen(self):
        try:
            seen_path = self.config.MODELS_DIR / "internet_learned.json"
            with open(seen_path, "w", encoding="utf-8") as f:
                json.dump(list(self._seen)[-20000:], f)
        except Exception:
            pass

    def _save_state(self):
        """Persist everything so nothing is lost on restart."""
        try:
            self.neural.save_state(str(self.config.MODELS_DIR / "learner.pt"))
        except Exception:
            pass
        self._persist_seen()
        try:
            self.knowledge_graph._save()
        except Exception:
            pass
