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
        self.router = QueryRouter(neural_engine, core_engine)
        self.planner = TaskPlanner(core_engine)

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
            return
        yield from self.router.execute_stream(query, route, session_id, messages=messages, context=context, max_tokens=max_tokens)

    def process_with_image(self, query, image, session_id="default", messages=None, timezone="", location=""):
        context = self._timezone_context(timezone, location, query)
        route = self.router.route(query)
        return self.router.execute(query, route, session_id, image=image, messages=messages, context=context)

    def generate_image(self, prompt, session_id="default", timezone="", location=""):
        context = ""
        try:
            mem_context = self.core.memory.get_recent_context(session_id)
            if mem_context:
                context = mem_context
        except Exception:
            pass
        return self.router._handle_image_generation(prompt, context)

    def redesign_image(self, image, prompt):
        img_bytes, error = self.core.image_gen.redesign(image, prompt)
        if error:
            return {"type": "image_redesign", "content": None, "error": error}
        return {"type": "image_redesign", "content": img_bytes, "error": None, "prompt": prompt}

    def modify_image(self, query, image_path):
        return self.router._handle_image_modification(query, image_path)

    def process_with_file(self, query, file_path, session_id="default", messages=None):
        context = ""
        route = self.router.route(query)
        return self.router.execute(query, route, session_id, file_path=file_path, messages=messages, context=context)
