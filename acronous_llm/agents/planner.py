import re
import json

class TaskPlanner:
    def __init__(self, core_engine):
        self.core = core_engine

    def plan_and_execute(self, query, session_id="default", context=None):
        self.core.memory.add_message(session_id, "user", query, {"type": "planned"})
        plan = self._create_plan(query)
        results = []
        for step in plan["steps"]:
            result = self._execute_step(step, query, session_id)
            results.append(result)
        summary_prompt = f"""Original request: {query}

Results from each step:
{chr(10).join([f"- {r['step']}: {r['result'][:200]}" for r in results])}

Synthesize these results into a comprehensive final answer."""
        final = self.core.llm.generate(summary_prompt)
        self.core.memory.add_message(session_id, "assistant", final, {"type": "planned"})
        return {
            "type": "planned",
            "content": final,
            "plan": plan,
            "steps": results
        }

    def _create_plan(self, query):
        query_lower = query.lower()
        steps = []
        if any(w in query_lower for w in ["compare", "vs", "versus", "difference"]):
            items = self._extract_items(query)
            for item in items:
                steps.append({"action": "search", "target": item, "description": f"Research {item}"})
            steps.append({"action": "synthesize", "description": "Compare findings"})
        elif any(w in query_lower for w in ["research", "report", "article"]):
            steps.append({"action": "search", "target": query, "description": "Gather information"})
            steps.append({"action": "search", "target": f"{query} latest 2025 2026", "description": "Find recent developments"})
            steps.append({"action": "synthesize", "description": "Compile research"})
        else:
            steps.append({"action": "search", "target": query, "description": "Search for information"})
            steps.append({"action": "synthesize", "description": "Format response"})
        return {"steps": steps, "original_query": query}

    def _extract_items(self, query):
        import re
        items = []
        patterns = [
            r"compare\s+(.+?)\s+(?:and|vs|versus|with)\s+(.+)",
            r"(.+?)\s+(?:vs|versus|and)\s+(.+)",
        ]
        for p in patterns:
            match = re.search(p, query, re.IGNORECASE)
            if match:
                items = [match.group(1).strip(), match.group(2).strip()]
                break
        if not items:
            conjunctions = [" vs ", " versus ", " and ", " or "]
            for c in conjunctions:
                if c in query:
                    parts = query.split(c)
                    if len(parts) >= 2:
                        items = [parts[0].strip(), parts[1].strip()]
                        break
        return items

    def _execute_step(self, step, original_query, session_id):
        if step["action"] == "search":
            results = self.core.search.search_with_content(step["target"], max_results=2)
            snippets = "\n".join([
                f"{r['title']}: {r['snippet']}"
                for r in results if r.get("snippet")
            ])
            self.core.rag.add_and_index(
                snippets or f"Search results for: {step['target']}",
                {"step": step["description"], "query": original_query}
            )
            return {"step": step["description"], "result": snippets or "No results found"}
        elif step["action"] == "synthesize":
            rag_context, _ = self.core.rag.retrieve_with_context(original_query, k=5)
            prompt = f"""Based on the gathered information, provide a comprehensive response.

Context:
{rag_context or 'No specific context available.'}

Original Request: {original_query}

Response:"""
            response = self.core.llm.generate(prompt)
            return {"step": step["description"], "result": response}
        return {"step": step["description"], "result": ""}
