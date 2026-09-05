from .router import QueryRouter
from .planner import TaskPlanner

COMPLEXITY_PATTERNS = [
    "explain", "analyze", "compare", "contrast", "research",
    "comprehensive", "detailed", "in-depth", "investigate",
    "write a report", "write an essay", "difference between",
    "how does", "why is", "what are the", "what is the",
    "pros and cons", "advantages and disadvantages",
    "step by step", "tutorial", "guide", "overview of",
]

class AcronousAgentEngine:
    def __init__(self, neural_engine, core_engine):
        self.neural = neural_engine
        self.core = core_engine
        # Wire the real embedder into the neural engine so learning uses real
        # semantic vectors (not the hash fallback).
        try:
            self.neural.set_embedder(self.core.embedder)
        except Exception:
            pass
        self.router = QueryRouter(neural_engine, core_engine)
        self.planner = TaskPlanner(core_engine)

    # ── Autonomous learning loop ──────────────────────────────────────────
    def _learn_from_interaction(self, query, result, session_id, route_type=None):
        """After EVERY completed user interaction, let the brain learn:
          1. Feed the query+label to the neural learner (implicit feedback).
          2. Store the Q→A pair into the vector RAG memory so future similar
             questions recall past answers.
          3. Persist the learner state + feedback so learning survives restarts.
        Runs best-effort — never lets learning failures break the response."""
        try:
            content = ""
            if isinstance(result, dict):
                content = result.get("content") or ""
                if route_type is None:
                    route_type = result.get("type") or route_type
            if not query or not content:
                return
            route_type = route_type or "general_chat"
            self.neural.learn_from_interaction(query, content, route_type, session_id)
            # Vector memory of the exchange for RAG recall on later turns.
            try:
                self.core.rag.add_and_index(
                    f"Q: {query}\nA: {content[:800]}",
                    {"type": route_type, "session": session_id}
                )
            except Exception:
                pass
        except Exception:
            pass

    def _save_learning_state(self):
        try:
            cfg = self.neural.config
            self.neural.save_state(str(cfg.MODELS_DIR / "learner.pt"))
        except Exception:
            pass

    def _learn_preferences(self, query, session_id):
        """Lightweight autonomous preference/fact extraction from the user's
        message. No LLM call (fast) — just regex heuristics that grow the
        brain's memory of who this user is and how they like to work."""
        if not query:
            return
        q = query.lower().strip()
        try:
            # Language preference: "in hindi", "in spanish", "translate to french"
            import re as _re
            lang_map = {
                "hindi": "Hindi", "spanish": "Spanish", "french": "French",
                "german": "German", "tamil": "Tamil", "telugu": "Telugu",
                "bengali": "Bengali", "marathi": "Marathi", "kannada": "Kannada",
                "malayalam": "Malayalam", "gujarati": "Gujarati", "punjabi": "Punjabi",
                "japanese": "Japanese", "korean": "Korean", "chinese": "Chinese",
                "italian": "Italian", "portuguese": "Portuguese", "russian": "Russian",
                "arabic": "Arabic", "english": "English",
            }
            lang_hit = None
            for key, val in lang_map.items():
                if _re.search(rf"\bin\s+{key}\b|to\s+{key}\b|{key}-\s*language", q):
                    lang_hit = val
                    break
            if lang_hit:
                self.neural.remember_preference(session_id, "language", lang_hit)

            # Role/topic interest heuristics
            if _re.search(r"\b(i'?m|i am|i'm a|i work\s+as)\s+(a\s+)?(developer|engineer|student|teacher|designer|doctor|lawyer|manager|writer|analyst|data\s+scientist|accountant|marketer|sales|researcher)\b", q):
                role = _re.search(r"\b(i'?m|i am|i'm a|i work\s+as)\s+(a\s+)?([a-z\s]+)", q)
                if role:
                    self.neural.remember_preference(session_id, "role", role.group(3).strip())

            # User's name
            if _re.search(r"\b(my name is|call me|i am|i'm)\s+([a-z]+)\b", q, _re.I):
                m = _re.search(r"\b(my name is|call me|i am|i'm)\s+([a-z]+)\b", q, _re.I)
                if m and m.group(2)[0].isupper() is False:
                    pass  # only store if it looks like a name (has odd capitalization)
        except Exception:
            pass

    def _is_time_query(self, query):
        if not query:
            return False
        keywords = [
            "time", "date", "what day", "what month", "what year",
            "current time", "current date", "what's the time",
            "what's the date", "tell me the time", "tell me the date",
            "what is the time", "what is the date", "how old",
            "when is", "when was", "what year is it",
            "today", "tomorrow", "yesterday", "clock",
            "morning", "afternoon", "evening", "night",
            "what's today", "what day is it",
        ]
        lower = query.lower().strip()
        for kw in keywords:
            if kw in lower:
                return True
        return False

    def estimate_complexity(self, query):
        if not query or not query.strip():
            return 0
        t = query.strip()
        word_count = len(t.split())
        if word_count <= 3:
            return 0
        lower = t.lower()
        score = 0
        for p in COMPLEXITY_PATTERNS:
            if p in lower:
                score += 2
        if word_count > 15:
            score += 2
        if word_count > 30:
            score += 3
        if "?" in t:
            score += 1
        if len(t) > 200:
            score += 2
        return score

    def _complexity_bucket(self, score):
        if score >= 6:
            return "complex"
        if score >= 3:
            return "moderate"
        return "simple"

    def _timezone_context(self, timezone="", location="", query=""):
        if not self._is_time_query(query):
            return ""
        time_parts = []
        if location:
            time_parts.append(f"[User location: {location}]")
        from datetime import datetime, timezone as tz_base
        if timezone:
            from datetime import timedelta, timezone as tz_mod
            user_now = None
            tz_label = ""
            try:
                try:
                    from zoneinfo import ZoneInfo
                    user_tz = ZoneInfo(timezone)
                    user_now = datetime.now(user_tz)
                    tz_label = user_now.strftime('%Z')
                except (ImportError, KeyError, TypeError):
                    try:
                        import pytz
                        user_tz = pytz.timezone(timezone)
                        user_now = datetime.now(user_tz)
                        tz_label = user_now.strftime('%Z')
                    except (ImportError, KeyError):
                        pass
            except Exception:
                pass

            if user_now is None:
                try:
                    upper = timezone.upper().strip()
                    if upper.startswith("UTC") or upper.startswith("GMT"):
                        offset_str = upper[3:].strip()
                        if offset_str:
                            sign = 1 if offset_str.startswith("+") else -1
                            parts = offset_str.lstrip("+-").split(":")
                            hours = int(parts[0])
                            minutes = int(parts[1]) if len(parts) > 1 else 0
                            offset = timedelta(hours=sign * hours, minutes=sign * minutes)
                            user_tz = tz_mod(offset)
                            user_now = datetime.now(user_tz)
                            tz_label = user_now.strftime('%z')
                except Exception:
                    pass

            if user_now is None:
                user_now = datetime.now(tz_base.utc).astimezone()
                tz_label = user_now.strftime('%Z')

            time_parts.append(
                f"[Current date and time: {user_now.strftime('%A, %B %d, %Y at %I:%M %p')} {tz_label}]"
            )
        else:
            now = datetime.now(tz_base.utc).astimezone()
            time_parts.append(
                f"[Current date and time: {now.strftime('%A, %B %d, %Y at %I:%M %p %Z')}]"
            )
        return "\n".join(time_parts)

    def _complexity_to_max_tokens(self, score):
        if score >= 8:
            return 4096
        if score >= 5:
            return 2048
        if score >= 3:
            return 1024
        return 512

    def process(self, query, session_id="default", context=None, messages=None, timezone="", location=""):
        time_context = self._timezone_context(timezone, location, query)
        ctx_parts = [p for p in [time_context, context] if p]
        context = "\n".join(ctx_parts) if ctx_parts else ""
        complexity = self.estimate_complexity(query)
        max_tokens = self._complexity_to_max_tokens(complexity)
        route = self.router.route(query)
        if route.get("needs_planning"):
            result = self.planner.plan_and_execute(query, session_id, context)
        else:
            result = self.router.execute(query, route, session_id, messages=messages, context=context, max_tokens=max_tokens)
        if isinstance(result, dict):
            result["complexity"] = complexity
            result["complexity_label"] = self._complexity_bucket(complexity)
        # AUTONOMOUS LEARNING: improve from every completed interaction.
        self._learn_from_interaction(query, result, session_id, route.get("type"))
        self._learn_preferences(query, session_id)
        self._save_learning_state()
        return result

    def process_stream(self, query, session_id="default", context=None, messages=None, timezone="", location=""):
        time_context = self._timezone_context(timezone, location, query)
        ctx_parts = [p for p in [time_context, context] if p]
        context = "\n".join(ctx_parts) if ctx_parts else ""
        complexity = self.estimate_complexity(query)
        max_tokens = self._complexity_to_max_tokens(complexity)
        route = self.router.route(query)
        if route.get("needs_planning"):
            result = self.planner.plan_and_execute(query, session_id, context)
            content = result.get("content", "")
            chunk_size = 30
            for i in range(0, len(content), chunk_size):
                yield content[i:i + chunk_size]
            self._learn_from_interaction(query, result, session_id, route.get("type"))
            self._save_learning_state()
            return
        full = []
        for chunk in self.router.execute_stream(query, route, session_id, messages=messages, context=context, max_tokens=max_tokens):
            full.append(chunk)
            yield chunk
        joined = "".join(full)
        self._learn_from_interaction(query, {"content": joined, "type": route.get("type")}, session_id, route.get("type"))
        self._learn_preferences(query, session_id)
        self._save_learning_state()

    def process_with_image(self, query, image, session_id="default", messages=None, timezone="", location=""):
        context = self._timezone_context(timezone, location, query)
        route = self.router.route(query)
        result = self.router.execute(query, route, session_id, image=image, messages=messages, context=context)
        self._learn_from_interaction(query, result, session_id, route.get("type"))
        self._save_learning_state()
        return result

    def generate_image(self, prompt, session_id="default", timezone="", location=""):
        context = ""
        try:
            mem_context = self.core.memory.get_recent_context(session_id)
            if mem_context:
                context = mem_context
        except Exception:
            pass
        result = self.router._handle_image_generation(prompt, context)
        self._learn_from_interaction(prompt, result, session_id, "image_generation")
        self._save_learning_state()
        return result

    def redesign_image(self, image, prompt):
        img_bytes, error = self.core.image_gen.redesign(image, prompt)
        if error:
            return {"type": "image_redesign", "content": None, "error": error}
        return {"type": "image_redesign", "content": img_bytes, "error": None, "prompt": prompt}

    def modify_image(self, query, image_path):
        result = self.router._handle_image_modification(query, image_path)
        self._save_learning_state()
        return result

    def process_with_file(self, query, file_path, session_id="default", messages=None):
        context = ""
        route = self.router.route(query)
        result = self.router.execute(query, route, session_id, file_path=file_path, messages=messages, context=context)
        self._learn_from_interaction(query, result, session_id, route.get("type"))
        self._save_learning_state()
        return result

    # ── Explicit feedback from the UI (thumbs up/down) ─────────────────────
    def record_feedback(self, session_id, query, rating, response=""):
        """Record explicit user feedback (rating 1-5, or 0 for a downvote).
        Feeds the FeedbackCollector and, for negative ratings, nudges the
        learner so the brain avoids repeating the same style of answer."""
        try:
            score = max(0.0, min(1.0, float(rating or 0)))
            self.neural.feedback.record(query, response, score, {"session": session_id})
            if score < 0.5:
                emb = self.neural.core_embedder.embed(query) if self.neural.core_embedder else self.neural._plain_embed(query)
                self.neural.learner.update(emb, 0.1)
            self._save_learning_state()
        except Exception:
            pass

    def get_learning_context(self, session_id):
        """Expose what the brain has learned about this user so callers can
        inject it into the prompt for personalization."""
        try:
            return self.neural.serve_memory_context(session_id)
        except Exception:
            return ""

    # ── Continuous autonomous (internet) learning ─────────────────────────
    def start_internet_learning(self, interval_seconds=300):
        """Start the background internet-learner so the brain keeps growing
        even with no user interaction. Best-effort: no-op if it can't wire up.
        Returns the learner (or None)."""
        try:
            core = self.core
            if getattr(core, "internet_learner", None) is None:
                from acronous_llm.core.internet_learner import InternetLearner
                core.internet_learner = InternetLearner(
                    core.config, core.memory, core.rag, self.neural, core.search
                )
            self.core.internet_learner.start(interval_seconds)
            return self.core.internet_learner
        except Exception:
            return None

    def learn_from_internet_once(self, num_topics=None):
        """Do a single immediate internet-learning sweep (useful for tests /
        on-startup refresh)."""
        try:
            from acronous_llm.core.internet_learner import InternetLearner
            if getattr(self.core, "internet_learner", None) is None:
                self.core.internet_learner = InternetLearner(
                    self.core.config, self.core.memory, self.core.rag,
                    self.neural, self.core.search
                )
            return self.core.internet_learner.run_once(num_topics=num_topics)
        except Exception:
            return 0
