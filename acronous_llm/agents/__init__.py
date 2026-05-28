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

    def _web_time_location(self):
        if not self.core.llm.is_old_model():
            return ""
        parts = []
        try:
            t = self.core.search.fetch_current_time()
            if t:
                parts.append(f"[Web-fetched current time: {t}]")
        except Exception:
            pass
        try:
            loc = self.core.search.fetch_current_location()
            if loc:
                parts.append(f"[Web-fetched current location: {loc}]")
        except Exception:
            pass
        if parts:
            return "\n" + "\n".join(parts)
        return ""

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

    def process(self, query, session_id="default", context=None, messages=None):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).astimezone()
        time_context = f"[Current date and time: {now.strftime('%A, %B %d, %Y at %I:%M %p %Z')}]"
        web_info = self._web_time_location()
        if context:
            context = f"{time_context}{web_info}\n{context}"
        else:
            context = f"{time_context}{web_info}"
        complexity = self.estimate_complexity(query)
        query = self.router.auto_correct(query)
        route = self.router.route(query)
        if route.get("needs_planning"):
            result = self.planner.plan_and_execute(query, session_id, context)
        else:
            result = self.router.execute(query, route, session_id, messages=messages, context=context)
        if isinstance(result, dict):
            result["complexity"] = complexity
            result["complexity_label"] = self._complexity_bucket(complexity)
        return result

    def process_stream(self, query, session_id="default", context=None, messages=None):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).astimezone()
        time_context = f"[Current date and time: {now.strftime('%A, %B %d, %Y at %I:%M %p %Z')}]"
        web_info = self._web_time_location()
        if context:
            context = f"{time_context}{web_info}\n{context}"
        else:
            context = f"{time_context}{web_info}"
        query = self.router.auto_correct(query)
        route = self.router.route(query)
        if route.get("needs_planning"):
            result = self.planner.plan_and_execute(query, session_id, context)
            content = result.get("content", "")
            chunk_size = 30
            for i in range(0, len(content), chunk_size):
                yield content[i:i + chunk_size]
            return
        yield from self.router.execute_stream(query, route, session_id, messages=messages, context=context)

    def process_with_image(self, query, image, session_id="default", messages=None):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).astimezone()
        web_info = self._web_time_location()
        context = f"[Current date and time: {now.strftime('%A, %B %d, %Y at %I:%M %p %Z')}]{web_info}"
        query = self.router.auto_correct(query)
        route = self.router.route(query)
        return self.router.execute(query, route, session_id, image=image, messages=messages, context=context)

    def generate_image(self, prompt, session_id="default"):
        context = ""
        try:
            context = self.core.memory.get_recent_context(session_id)
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
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).astimezone()
        web_info = self._web_time_location()
        context = f"[Current date and time: {now.strftime('%A, %B %d, %Y at %I:%M %p %Z')}]{web_info}"
        query = self.router.auto_correct(query)
        route = self.router.route(query)
        return self.router.execute(query, route, session_id, file_path=file_path, messages=messages, context=context)
