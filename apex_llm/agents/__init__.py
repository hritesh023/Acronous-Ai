from .router import QueryRouter
from .planner import TaskPlanner

class ApexAgentEngine:
    def __init__(self, neural_engine, core_engine):
        self.neural = neural_engine
        self.core = core_engine
        self.router = QueryRouter(neural_engine, core_engine)
        self.planner = TaskPlanner(core_engine)

    def process(self, query, session_id="default", context=None, messages=None):
        route = self.router.route(query)
        if route.get("needs_planning"):
            return self.planner.plan_and_execute(query, session_id, context)
        return self.router.execute(query, route, session_id, messages=messages)

    def process_stream(self, query, session_id="default", context=None, messages=None):
        """Generator that yields response chunks for streaming"""
        route = self.router.route(query)
        if route.get("needs_planning"):
            result = self.planner.plan_and_execute(query, session_id, context)
            content = result.get("content", "")
            chunk_size = 30
            for i in range(0, len(content), chunk_size):
                yield content[i:i + chunk_size]
            return
        yield from self.router.execute_stream(query, route, session_id, messages=messages)

    def process_with_image(self, query, image, session_id="default", messages=None):
        route = self.router.route(query)
        route["type"] = "image_analysis"
        return self.router.execute(query, route, session_id, image=image, messages=messages)

    def generate_image(self, prompt):
        img_bytes, error = self.core.image_gen.generate(prompt)
        if error:
            return {"type": "image_gen", "content": None, "error": error}
        return {"type": "image_gen", "content": img_bytes, "error": None, "prompt": prompt}

    def redesign_image(self, image, prompt):
        img_bytes, error = self.core.image_gen.redesign(image, prompt)
        if error:
            return {"type": "image_redesign", "content": None, "error": error}
        return {"type": "image_redesign", "content": img_bytes, "error": None, "prompt": prompt}
