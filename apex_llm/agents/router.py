import json

class QueryRouter:
    def __init__(self, neural_engine, core_engine):
        self.neural = neural_engine
        self.core = core_engine
        self.search_keywords = [
            "search", "find", "look up", "what is", "who is", "how to",
            "weather", "news", "latest", "definition", "meaning",
            "google", "internet", "web", "online"
        ]
        self.image_keywords = [
            "image", "picture", "photo", "scan", "detect", "see",
            "look at", "analyze this", "what is this"
        ]
        self.code_keywords = [
            "write code", "generate code", "create a function", "debug",
            "algorithm", "implement a", "write a program", "code for",
            "script that", "function that"
        ]
        self.translate_keywords = [
            "translate", "translation", "convert to", "in spanish",
            "in french", "in german", "meaning in"
        ]

    def route(self, query):
        query_lower = query.lower().strip()
        embedding = self.core.embedder.embed(query)
        intent_id, intent_probs = self.neural.predict_intent(embedding, return_probs=True)
        intent_name = self.neural.classifier.get_intent_name(intent_id)

        features = self._extract_features(query_lower)
        features["intent_id"] = intent_id
        features["intent_name"] = intent_name
        features["intent_confidence"] = max(intent_probs) if isinstance(intent_probs, list) else 0

        route_type = self._determine_type(features, query_lower)
        features["type"] = route_type
        features["needs_search"] = route_type in ["web_search", "news", "factual"]
        features["needs_planning"] = self._needs_planning(query_lower)
        features["embedding"] = embedding

        return features

    def _extract_features(self, query_lower):
        import re
        clean = re.sub(r'[^\w\s]', ' ', query_lower)
        words = set(clean.split())
        return {
            "has_question": "?" in query_lower,
            "question_words": bool(
                words & {"what", "why", "how", "when", "where", "who", "which"}
            ),
            "word_count": len(query_lower.split()),
            "has_url": "http" in query_lower or "www." in query_lower,
        }

    def _determine_type(self, features, query_lower):
        word_count = features["word_count"]
        q_words = set(query_lower.split())
        code_keywords_set = {"code", "function", "algorithm", "debug", "script", "program"}
        if q_words & code_keywords_set:
            return "code_generation"
        if any(k in query_lower for k in self.translate_keywords):
            return "translation"
        if any(k in query_lower for k in self.image_keywords):
            return "image_analysis"
        if features["question_words"] or features["has_question"]:
            if word_count <= 8:
                return "factual"
            return "web_search"
        search_matches = sum(1 for k in self.search_keywords if k in query_lower)
        if search_matches >= 1:
            return "web_search"
        return "general_chat"

    def _needs_planning(self, query_lower):
        planning_triggers = [
            "compare", "plan", "create a report", "research",
            "analyze", "evaluate", "step by step", "detailed",
            "write an essay", "write a article"
        ]
        return any(t in query_lower for t in planning_triggers)

    def execute(self, query, route, session_id="default", image=None, messages=None):
        try:
            self.core.memory.add_message(session_id, "user", query, {"type": route.get("type", "chat")})
        except Exception:
            pass

        stored_context = ""
        try:
            stored_context = self.core.memory.get_recent_context(session_id)
        except Exception:
            pass

        if messages and isinstance(messages, list):
            conv_history = "\n".join([
                f"{m.get('role', 'user').capitalize()}: {m.get('content', '')}"
                for m in messages[-20:]
            ])
            context = conv_history + "\n" + stored_context if stored_context else conv_history
        else:
            context = stored_context

        route_type = route.get("type", "general_chat")

        try:
            if route_type == "image_analysis" and image is not None:
                result = self._handle_image(query, image)
            elif route_type == "web_search":
                result = self._handle_search(query, context)
            elif route_type == "factual":
                result = self._handle_factual(query, context)
            elif route_type == "code_generation":
                result = self._handle_code(query, context)
            elif route_type == "translation":
                result = self._handle_translation(query)
            else:
                result = self._handle_chat(query, context)
        except Exception as e:
            result = {
                "type": "error",
                "content": f"Error processing request: {str(e)}. Make sure Ollama is running and a model is installed.",
                "sources": []
            }

        if result and result.get("content"):
            try:
                self.core.memory.add_message(session_id, "assistant", result["content"], {"type": result.get("type", "chat")})
            except Exception:
                pass
        return result

    def execute_stream(self, query, route, session_id="default", messages=None):
        try:
            self.core.memory.add_message(session_id, "user", query, {"type": route.get("type", "chat")})
        except Exception:
            pass
        stored_context = ""
        try:
            stored_context = self.core.memory.get_recent_context(session_id)
        except Exception:
            pass
        if messages and isinstance(messages, list):
            conv_history = "\n".join([
                f"{m.get('role', 'user').capitalize()}: {m.get('content', '')}"
                for m in messages[-20:]
            ])
            context = conv_history + "\n" + stored_context if stored_context else conv_history
        else:
            context = stored_context

        route_type = route.get("type", "general_chat")
        try:
            if route_type in ("web_search", "factual"):
                result = self._handle_search(query, context) if route_type == "web_search" else self._handle_factual(query, context)
                content = result.get("content", "")
                chunk_size = 30
                for i in range(0, len(content), chunk_size):
                    yield content[i:i + chunk_size]
            else:
                prompt = f"{context}\nUser: {query}" if context else f"User: {query}"
                system_prompt = "You are Apex AI, a helpful local AI assistant."
                yield from self.core.llm.generate_stream(prompt, system_prompt)
        except Exception as e:
            yield f"Error: {str(e)}"

    def _handle_chat(self, query, context):
        prompt = f"{context}\nUser: {query}" if context else f"User: {query}"
        response = self.core.llm.generate(prompt)
        return {
            "type": "chat",
            "content": response,
            "sources": []
        }

    def _handle_search(self, query, context):
        search_results = self.core.search.search_with_content(query, max_results=3)
        snippets = "\n\n".join([
            f"Source: {r['title']}\n{r['snippet']}\n{r.get('content', '')[:500]}"
            for r in search_results if r.get("snippet")
        ])
        if snippets:
            rag_context = f"Web search results for '{query}':\n\n{snippets}"
            self.core.rag.add_and_index(rag_context, {"source": "web_search", "query": query})
        prompt = f"""Based on these search results, answer the user's question. If the search results are insufficient, say so.

Search Results:
{snippets if snippets else 'No search results found.'}

User Question: {query}

Answer:"""
        response = self.core.llm.generate(
            prompt,
            system_prompt="You are Apex AI. Answer using the search results provided. Cite sources when possible."
        )
        return {
            "type": "search",
            "content": response,
            "sources": [{"title": r["title"], "url": r["url"]} for r in search_results]
        }

    def _handle_factual(self, query, context):
        rag_context, rag_results = self.core.rag.retrieve_with_context(query)
        if rag_context:
            prompt = f"""Previous context:\n{context}\n\nRetrieved knowledge:\n{rag_context}\n\nUser: {query}\n\nAnswer:"""
        else:
            search_results = self.core.search.search_with_content(query, max_results=2)
            snippets = "\n".join([
                f"{r['title']}: {r['snippet']}"
                for r in search_results if r.get("snippet")
            ])
            if snippets:
                self.core.rag.add_and_index(snippets, {"source": "web"})
                prompt = f"""Search results:\n{snippets}\n\nUser: {query}\n\nAnswer:"""
            else:
                prompt = f"User: {query}\n\nAnswer based on your knowledge:"
        response = self.core.llm.generate(prompt)
        return {"type": "factual", "content": response, "sources": []}

    def _handle_code(self, query, context):
        prompt = f"Generate code for the following request. Include explanations:\n\n{query}\n\nCode:"
        response = self.core.llm.generate(prompt)
        return {"type": "code", "content": response, "sources": []}

    def _handle_translation(self, query):
        prompt = f"Translate the following text. Identify the source and target languages from context:\n\n{query}\n\nTranslation:"
        response = self.core.llm.generate(prompt)
        return {"type": "translation", "content": response, "sources": []}

    def _handle_image(self, query, image):
        analysis = self.core.vision.analyze_image(image)
        objects = self.core.vision.detect_objects(image)
        image_context = f"Image Analysis: {json.dumps(analysis, indent=2)}"
        if objects:
            image_context += f"\n\nDetected Objects: {json.dumps(objects, indent=2)}"
        prompt = f"""{image_context}

User query about image: {query}

Respond based on the image analysis above."""
        response = self.core.llm.generate(prompt)
        return {
            "type": "image_analysis",
            "content": response,
            "analysis": analysis,
            "objects": objects
        }
