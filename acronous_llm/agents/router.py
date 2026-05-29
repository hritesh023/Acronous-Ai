import json
import re
import base64


class QueryRouter:
    def __init__(self, neural_engine, core_engine):
        self.neural = neural_engine
        self.core = core_engine

    def route(self, query):
        query_lower = query.lower().strip()
        embedding = self.core.embedder.embed(query)
        route_type = self._determine_type_with_llm(query)
        features = {
            "type": route_type,
            "needs_search": route_type in ("web_search", "factual", "news"),
            "needs_planning": self._needs_planning(query),
            "embedding": embedding,
            "has_question": "?" in query_lower,
            "word_count": len(query_lower.split()),
        }
        return features

    def _determine_type_with_llm(self, query):
        prompt = f"""Classify this user request into exactly one category. Return ONLY the category name, nothing else.

Categories:
- web_search: ANY question seeking factual information, current events, news, politics, government officials, weather, time, date, prices, sports scores, definitions, explanations, who is, what is, where is, when did, how does — any information that requires up-to-date or external knowledge
- image_generation: user asks to draw, paint, sketch, generate, create, or make an image/picture/photo/art/diagram
- file_generation: user asks to create, generate, or make a file in a specific format — pdf, csv, svg, json, html, md, text/txt, spreadsheet, document, report, chart, diagram, icon, logo, invoice, resume, letter, certificate, or any downloadable document
- code_generation: user asks to write code, a function, program, algorithm, or debugging help
- translation: user explicitly says "translate" or asks how to say something in another language
- image_analysis: user uploaded or wants to analyze an image/photo
- general_chat: ONLY simple greetings, casual conversation, opinions, jokes, or creative writing — NOT any question seeking information or facts

IMPORTANT: When in doubt, choose web_search. Any question about a person, place, event, thing, concept, or fact MUST be web_search. Only choose general_chat if the user is clearly just greeting, thanking, or making small talk with no information-seeking intent.

User request: {query}
Category:"""
        try:
            result = self.core.llm.generate(
                prompt,
                system_prompt="You classify user requests into categories. Return only the category name."
            )
            result = result.strip().lower().strip('"').strip("'").strip()
            valid = {"image_generation", "file_generation", "web_search", "code_generation", "translation", "image_analysis", "general_chat"}
            if result in valid:
                return result
            return "web_search"
        except Exception:
            return "web_search"

    def execute(self, query, route, session_id="default", image=None, messages=None, file_path=None, context=None, max_tokens=None):
        try:
            self.core.memory.add_message(session_id, "user", query, {"type": route.get("type", "chat")})
        except Exception:
            pass

        stored_context = ""
        try:
            stored_context = self.core.memory.get_recent_context(session_id)
        except Exception:
            pass

        context = context or ""
        if messages and isinstance(messages, list):
            conv_lines = []
            for m in messages[-20:]:
                role = m.get('role', 'user')
                content = m.get('content', '')
                line = f"You: {content}" if role == 'assistant' else f"User: {content}"
                conv_lines.append(line)
            conv_history = "\n".join(conv_lines)
            context = context + "\n" + conv_history + "\n" + stored_context if stored_context else context + "\n" + conv_history
        elif stored_context:
            context = context + "\n" + stored_context

        route_type = route.get("type", "general_chat")

        try:
            if image is not None:
                if self._is_modification_request(query, image):
                    result = self._handle_image_modification(query, image, context)
                else:
                    result = self._handle_image(query, image, context)
            elif file_path is not None:
                result = self._handle_file(query, file_path, context, max_tokens)
            elif route_type == "image_generation":
                result = self._handle_image_generation(query, context)
            elif route_type == "file_generation":
                result = self._handle_file_generation(query, context)
            elif route_type == "web_search" or route_type == "factual" or route_type == "news":
                if context and "[Current date and time:" in context:
                    result = self._handle_time_query(query, context, max_tokens)
                else:
                    result = self._handle_search(query, context, max_tokens)
            elif route_type == "code_generation":
                result = self._handle_code(query, context, max_tokens)
            elif route_type == "translation":
                result = self._handle_translation(query, max_tokens)
            else:
                result = self._handle_chat(query, context, max_tokens)
        except Exception:
            result = {"type": "error", "content": "Something went wrong. Please try again.", "sources": []}

        if result and result.get("content"):
            try:
                self.core.memory.add_message(session_id, "assistant", result["content"], {"type": result.get("type", "chat")})
            except Exception:
                pass

        if not result or not result.get("content"):
            try:
                fallback = self._handle_search(query, context, max_tokens)
                if fallback and fallback.get("content"):
                    result = fallback
            except Exception:
                pass

        return result

    def execute_stream(self, query, route, session_id="default", messages=None, context=None, max_tokens=None):
        try:
            self.core.memory.add_message(session_id, "user", query, {"type": route.get("type", "chat")})
        except Exception:
            pass
        stored_context = ""
        try:
            stored_context = self.core.memory.get_recent_context(session_id)
        except Exception:
            pass
        context = context or ""
        if messages and isinstance(messages, list):
            conv_lines = []
            for m in messages[-20:]:
                role = m.get('role', 'user')
                content = m.get('content', '')
                line = f"You: {content}" if role == 'assistant' else f"User: {content}"
                conv_lines.append(line)
            conv_history = "\n".join(conv_lines)
            context = context + "\n" + conv_history + "\n" + stored_context if stored_context else context + "\n" + conv_history
        elif stored_context:
            context = context + "\n" + stored_context

        route_type = route.get("type", "general_chat")
        if route_type in ("web_search", "factual", "news"):
            if context and "[Current date and time:" in context:
                result = self._handle_time_query(query, context, max_tokens)
            else:
                result = self._handle_search(query, context, max_tokens)
            content = result.get("content", "")
            chunk_size = 30
            for i in range(0, len(content), chunk_size):
                yield content[i:i + chunk_size]
        else:
            search_data = self._execute_web_search(query)
            context_with_search = context
            if search_data:
                context_with_search = f"{context}\n\n{search_data}"
            prompt = f"""{context_with_search}

User: {query}

Answer using ONLY the web search results above. Do not use any pre-trained knowledge — the web search results are the only authoritative source. If the search results lack specific information, be honest that you could not find current data on this topic. Never say "As of my knowledge" or "based on my training". Never tell the user to check external sources. Answer directly and concisely."""
            yield from self.core.llm.generate_stream(prompt, max_tokens=max_tokens)

    def _refine_search_query(self, query):
        try:
            prompt = f"""Rewrite this question into 2-3 concise search queries that would best find the answer on a search engine. Return each query on a separate line, nothing else.

Original: {query}
Search queries:"""
            result = self.core.llm.generate(
                prompt,
                system_prompt="You generate effective search engine queries. Return one per line."
            )
            lines = [l.strip() for l in result.strip().split("\n") if l.strip() and len(l.strip()) > 5]
            if lines:
                return lines[:3]
        except Exception:
            pass
        return [query]

    def _execute_web_search(self, query):
        try:
            from datetime import datetime, timezone
            queries = self._refine_search_query(query)
            all_results = []
            seen_urls = set()
            for q in queries[:3]:
                results = self.core.search.search_with_deep_content(q, max_results=3)
                for r in results:
                    url = r.get("url", "")
                    if url and url not in seen_urls and r.get("snippet"):
                        seen_urls.add(url)
                        all_results.append(r)
                if len(all_results) >= 3:
                    break
            if not all_results:
                alt_query = f"{query} {datetime.now(timezone.utc).astimezone().year}"
                results = self.core.search.search_with_deep_content(alt_query, max_results=3)
                all_results = [r for r in results if r.get("snippet")]
            if all_results:
                snippets = "\n\n".join([
                    f"[{r['title']}]({r['url']}): {r['snippet']}\n{r.get('content', '')[:500]}"
                    for r in all_results
                ])
                return f"Web search results for '{query}':\n\n{snippets}"
        except Exception:
            pass
        return ""

    def _handle_time_query(self, query, context, max_tokens=None):
        prompt = f"""{context}

The user asked: {query}

Using the date, time, and location information provided above, answer their question conversationally and accurately. Be warm and natural. Never mention or repeat the internal markers like [Current date and time:] or [User location:]. Just give a natural, friendly answer."""
        response = self.core.llm.generate(prompt, max_tokens=max_tokens)
        return {"type": "chat", "content": (response.strip() if response else ""), "sources": []}

    def _handle_search(self, query, context, max_tokens=None):
        search_data = ""
        search_results = []
        try:
            from datetime import datetime, timezone
            queries = self._refine_search_query(query)
            all_results = []
            seen_urls = set()
            for q in queries[:3]:
                results = self.core.search.search_with_deep_content(q, max_results=5)
                for r in results:
                    url = r.get("url", "")
                    if url and url not in seen_urls and r.get("snippet"):
                        seen_urls.add(url)
                        all_results.append(r)
                if len(all_results) >= 5:
                    break
            if not all_results:
                alt_query = f"{query} {datetime.now(timezone.utc).astimezone().year}"
                results = self.core.search.search_with_deep_content(alt_query, max_results=5)
                all_results = [r for r in results if r.get("snippet")]
            search_results = all_results[:5]
            if search_results:
                snippets = "\n\n".join([
                    f"[{r['title']}]({r['url']}): {r['snippet']}\n{r.get('content', '')[:500]}"
                    for r in search_results
                ])
                search_data = snippets
        except Exception:
            pass

        if search_data:
            prompt = f"""{context}

Web search results for "{query}":

{search_data}

Answer using ONLY the web search results above. Do not use any pre-trained knowledge — the web results are the authoritative source. Never say "As of my knowledge" or "based on my training". Never tell the user to check external sources or official websites — you already have the information. Answer directly, confidently, and concisely. When possible, mention the source names to add credibility."""
        else:
            prompt = f"""{context}

The user asked: {query}

I searched the web but could not find any current information from multiple search sources. Do NOT use your pre-trained knowledge to answer. Be honest and tell the user that no current information was found from web search. Suggest trying a more specific query or different search terms. Never make up information or fall back to training data. Never say "As of my knowledge" or "based on my training". Never tell the user to check external sources."""
        response = self.core.llm.generate(prompt, max_tokens=max_tokens)
        return {"type": "factual", "content": response, "sources": [{"title": r["title"], "url": r["url"]} for r in search_results]}

    def _is_simple_greeting(self, query):
        if not query or not query.strip():
            return False
        lower = query.lower().strip()
        single_word = {"hi", "hello", "hey", "greetings", "howdy", "sup", "yo", "hii", "heyy", "helloo"}
        if lower.rstrip("!.,?") in single_word:
            return True
        greeting_phrases = [
            "good morning", "good afternoon", "good evening",
            "how are you", "how's it going", "how are you doing",
            "what's up", "whats up", "nice to meet you",
            "pleased to meet you", "good to see you",
            "long time no see", "how have you been",
        ]
        for phrase in greeting_phrases:
            if phrase in lower:
                return True
        return False

    def _handle_chat(self, query, context, max_tokens=None):
        if self._is_simple_greeting(query):
            prompt = f"""User: "{query}"

Respond naturally with a warm, friendly greeting. Keep it concise and conversational."""
            response = self.core.llm.generate(prompt, max_tokens=max_tokens)
            return {"type": "chat", "content": (response.strip() if response else ""), "sources": []}

        search_data = ""
        search_results = []

        try:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).astimezone()
            queries = self._refine_search_query(query)
            all_results = []
            seen_urls = set()
            for q in queries[:2]:
                results = self.core.search.search_with_deep_content(q, max_results=3)
                for r in results:
                    url = r.get("url", "")
                    if url and url not in seen_urls and r.get("snippet"):
                        seen_urls.add(url)
                        all_results.append(r)
                if len(all_results) >= 3:
                    break
            if not all_results:
                alt_q = f"{query} {now.year}"
                results = self.core.search.search_with_deep_content(alt_q, max_results=3)
                all_results = [r for r in results if r.get("snippet")]
            search_results = all_results[:3]
            if search_results:
                snippets = "\n\n".join([
                    f"[{r['title']}]({r['url']}): {r['snippet']}\n{r.get('content', '')[:300]}"
                    for r in search_results
                ])
                search_data = f"\n\nRelated web information:\n{snippets}\n"
        except Exception:
            pass

        if search_data:
            prompt = f"""{context}{search_data}

User: {query}

Answer naturally using any relevant web search results above. If the search results contain information relevant to the query, use them as the authoritative source. If they don't, just respond conversationally. Never say "As of my knowledge" or "based on my training". Never tell the user to check external sources."""
        else:
            prompt = f"""User: "{query}"

Respond naturally and conversationally. Never say "As of my knowledge" or "based on my training". Never tell the user to check external sources."""
        response = self.core.llm.generate(prompt, max_tokens=max_tokens)
        content = response.strip() if response else ""
        return {"type": "chat", "content": content, "sources": [{"title": r["title"], "url": r["url"]} for r in search_results]}

    def _needs_planning(self, query):
        query_lower = query.lower().strip()
        planning_keywords = [
            "compare", "vs ", " versus ", "difference between",
            "research", "write a report", "comprehensive analysis",
            "detailed report", "in-depth", "thorough research",
            "multi-step", "step by step", "investigate",
        ]
        if any(kw in query_lower for kw in planning_keywords):
            return True
        return False

    def _handle_code(self, query, context, max_tokens=None):
        prompt = f"""The user wants code for: {query}

Provide a clear, natural response that includes:
1. A brief explanation of the approach
2. The code itself (properly formatted)
3. Key things to note about using it

Keep the tone helpful and conversational — like a senior developer pair-programming with them."""
        response = self.core.llm.generate(prompt, max_tokens=max_tokens)
        return {"type": "code", "content": response, "sources": []}

    def _handle_translation(self, query, max_tokens=None):
        prompt = f"""Translate the following. First identify the source and target languages, then provide the translation in a natural way.

Text: {query}

Respond conversationally — tell them what you detected and then give the translation naturally."""
        response = self.core.llm.generate(prompt, max_tokens=max_tokens)
        return {"type": "translation", "content": response, "sources": []}

    def _handle_image(self, query, image, context=""):
        analysis = None
        objects = None
        image_context = ""
        if self.core.vision is not None:
            try:
                analysis = self.core.vision.analyze_image(image)
                objects = self.core.vision.detect_objects(image)
                labels = analysis.get("labels", []) if isinstance(analysis, dict) else []
                top_labels = [l.get("label", str(l))[:50] for l in labels[:5]] if isinstance(labels, list) else []
                obj_names = []
                if objects and isinstance(objects, list):
                    for o in objects[:5]:
                        if isinstance(o, dict):
                            obj_names.append(o.get("label", o.get("name", str(o))[:30]))
                        else:
                            obj_names.append(str(o)[:30])
                desc_parts = []
                if top_labels:
                    desc_parts.append(f"The image appears to contain: {', '.join(top_labels)}.")
                if obj_names:
                    desc_parts.append(f"Detected objects include: {', '.join(obj_names)}.")
                if not desc_parts:
                    desc_parts.append("[The image was analyzed but no clear labels were detected.]")
                image_context = " ".join(desc_parts)
            except Exception:
                image_context = "[Image analysis is temporarily unavailable.]"
        conv = f"\nConversation history:\n{context}\n" if context else ""
        is_auto = not query or not query.strip()
        if is_auto:
            prompt = f"""{image_context}{conv}

The user captured this image with no specific request. Describe what you see and provide your insights naturally. Never mention that you're reading from analysis data — just describe the image conversationally."""
        else:
            prompt = f"""{image_context}{conv}

User query about image: {query}

Respond based on the image content and conversation history above. Never mention that you're reading from analysis data — just describe naturally."""
        response = self.core.llm.generate(prompt)
        return {"type": "image_analysis", "content": response, "analysis": analysis, "objects": objects}

    def _is_modification_request(self, query, image=None):
        if not query or not query.strip():
            return False
        try:
            prompt = f"""Determine if the user wants to MODIFY/EDIT/TRANSFORM the uploaded image (not just analyze/describe it).

User request: {query}

Answer with "yes" if they want to change/modify the image, or "no" if they just want to analyze/describe it:"""
            resp = self.core.llm.generate(prompt, system_prompt="You classify requests concisely.")
            return resp.strip().lower().startswith("yes")
        except Exception:
            return False

    def _modification_error_response(self, query, error, approach):
        try:
            prompt = f"""I tried to edit the user's image but encountered an issue.

User's request: "{query}"

Explain what happened in a natural, conversational way. Be honest but not overly technical. Suggest what the user could try instead. Keep it to 2-3 sentences and do not use markdown."""
            response_text = self.core.llm.generate(
                prompt,
                system_prompt="You are a helpful AI assistant that edits images. When something fails, explain naturally and offer alternatives."
            )
            content = response_text.strip().strip('"').strip("'").strip()
            if content:
                return {"type": "error", "content": content, "sources": []}
        except Exception:
            pass
        return {"type": "error", "content": "Could not edit that image. Try a different request.", "sources": []}

    def _handle_image_modification(self, query, image, context=""):
        try:
            from PIL import Image, ImageEnhance, ImageFilter, ImageOps
            import io

            analysis = {}
            objects = []
            if self.core.vision:
                try:
                    analysis = self.core.vision.analyze_image(image)
                    objects = self.core.vision.detect_objects(image)
                except Exception:
                    pass

            if isinstance(image, str):
                try:
                    pil_image = Image.open(image)
                except Exception:
                    pil_image = image
            else:
                pil_image = image

            if not isinstance(pil_image, Image.Image):
                try:
                    pil_image = Image.open(io.BytesIO(pil_image))
                except Exception:
                    pil_image = Image.open(pil_image)

            img_width, img_height = pil_image.size if hasattr(pil_image, 'size') else (512, 512)

            conv = f"\nConversation history:\n{context}\n" if context else ""
            decision_prompt = f"""You are an expert image editing AI. Analyze the user's request, conversation history, and the image, then decide the BEST editing approach.

User request: "{query}"
{conv}
Image dimensions: {img_width}x{img_height}px

Available editing approaches:
1. "pil" - Direct pixel manipulation using Python Imaging Library for color adjustments, geometric transforms, filters, and overlays. Fast, no AI model needed.
2. "inpaint" - AI-powered inpainting that selectively edits specific regions using an AI model. Best for erasing, replacing, or adding objects in specific areas.
3. "img2img" - Image-to-image generation using an AI model. Best for redesigning while preserving overall composition, changing style or scene.
4. "generate" - Generate a completely new image from scratch.

For PIL approach, available operations include: resize, crop, rotate, flip_horizontal, flip_vertical, grayscale, invert, sepia, brightness, contrast, saturation, sharpness, blur, sharpen, smooth, edge_enhance, emboss, posterize, solarize, equalize, autocontrast, colorize, border, overlay.

Respond with ONLY valid JSON - no markdown, no code fences:
{{"approach": "pil|inpaint|img2img|generate", "operations": [...], "prompt": "description of what to generate", "mask_description": "what region to edit", "strength": 0.7}}

For 'pil' approach, list operations to apply in order.
For 'inpaint' approach, include 'prompt' (what to generate in the edited region), 'mask_description' (which region to edit), and 'strength' (0.0-1.0).
For 'img2img', include a 'prompt' describing the modified image and optional 'strength' (0.0-1.0).
For 'generate', include a 'prompt' for the new image."""

            decision_resp = self.core.llm.generate(
                decision_prompt,
                system_prompt="You are an image editing expert. Analyze the request and respond with valid JSON only."
            )

            decision_resp = decision_resp.strip()
            if decision_resp.startswith("```"):
                decision_resp = decision_resp.split("\n", 1)[-1]
                if "```" in decision_resp:
                    decision_resp = decision_resp.split("```")[0]
            decision = json.loads(decision_resp)
            approach = decision.get("approach", "img2img")

            if approach == "pil":
                if pil_image.mode != "RGB":
                    pil_image = pil_image.convert("RGB")
                edited = pil_image.copy()
                for op_desc in decision.get("operations", []):
                    op = op_desc["op"] if isinstance(op_desc, dict) and "op" in op_desc else op_desc.get("op", "")
                    try:
                        if op == "resize":
                            w = op_desc.get("width", edited.width)
                            h = op_desc.get("height", edited.height)
                            edited = edited.resize((w, h), Image.LANCZOS)
                        elif op == "crop":
                            edited = edited.crop((
                                op_desc.get("left", 0),
                                op_desc.get("top", 0),
                                op_desc.get("right", edited.width),
                                op_desc.get("bottom", edited.height),
                            ))
                        elif op == "rotate":
                            edited = edited.rotate(op_desc.get("degrees", 0), expand=True, fillcolor=(255, 255, 255))
                        elif op == "flip_horizontal":
                            edited = ImageOps.mirror(edited)
                        elif op == "flip_vertical":
                            edited = ImageOps.flip(edited)
                        elif op == "grayscale":
                            edited = ImageOps.grayscale(edited).convert("RGB")
                        elif op == "invert":
                            edited = ImageOps.invert(edited)
                        elif op == "sepia":
                            gray = ImageOps.grayscale(edited)
                            w_table = gray.width
                            sepia_data = []
                            for py in range(gray.height):
                                for px in range(w_table):
                                    p = gray.getpixel((px, py))
                                    tr = min(255, int(p * 1.2))
                                    tg = min(255, int(p * 1.05))
                                    tb = min(255, int(p * 0.8))
                                    sepia_data.append((tr, tg, tb))
                            edited = Image.new("RGB", (gray.width, gray.height))
                            edited.putdata(sepia_data)
                        elif op == "brightness":
                            edited = ImageEnhance.Brightness(edited).enhance(op_desc.get("factor", 1.0))
                        elif op == "contrast":
                            edited = ImageEnhance.Contrast(edited).enhance(op_desc.get("factor", 1.0))
                        elif op == "saturation":
                            edited = ImageEnhance.Color(edited).enhance(op_desc.get("factor", 1.0))
                        elif op == "sharpness":
                            edited = ImageEnhance.Sharpness(edited).enhance(op_desc.get("factor", 1.0))
                        elif op == "blur":
                            edited = edited.filter(ImageFilter.BoxBlur(op_desc.get("radius", 2)))
                        elif op == "sharpen":
                            edited = edited.filter(ImageFilter.SHARPEN)
                        elif op == "smooth":
                            edited = edited.filter(ImageFilter.SMOOTH)
                        elif op == "edge_enhance":
                            edited = edited.filter(ImageFilter.EDGE_ENHANCE)
                        elif op == "emboss":
                            edited = edited.filter(ImageFilter.EMBOSS)
                        elif op == "posterize":
                            edited = ImageOps.posterize(edited, min(op_desc.get("bits", 4), 8))
                        elif op == "solarize":
                            edited = ImageOps.solarize(edited, threshold=op_desc.get("threshold", 128))
                        elif op == "equalize":
                            edited = ImageOps.equalize(edited)
                        elif op == "autocontrast":
                            edited = ImageOps.autocontrast(edited, cutoff=op_desc.get("cutoff", 0))
                        elif op == "colorize":
                            try:
                                c = op_desc.get("color", "#808080")
                                if isinstance(c, str) and c.startswith("#"):
                                    r, g, b = int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
                                else:
                                    r, g, b = 128, 128, 128
                                gray = ImageOps.grayscale(edited)
                                edited = ImageOps.colorize(gray, black=(0, 0, 0), white=(r, g, b)).convert("RGB")
                            except Exception:
                                pass
                        elif op == "border":
                            bw = op_desc.get("width", 5)
                            bc = op_desc.get("color", "black")
                            edited = ImageOps.expand(edited, border=bw, fill=bc)
                        elif op == "overlay":
                            try:
                                ol = Image.new("RGB", edited.size, op_desc.get("color", "#000000"))
                                alpha = op_desc.get("alpha", 0.3)
                                edited = Image.blend(edited, ol, alpha)
                            except Exception:
                                pass
                    except Exception:
                        continue
                img_buf = io.BytesIO()
                edited.save(img_buf, format="PNG")
                img_bytes = img_buf.getvalue()
                img_b64 = base64.b64encode(img_bytes).decode()
                try:
                    prompt_text = f"""The user requested to edit an image: {query}

I applied the following PIL operations and the image was edited successfully. Describe what was done in a natural, conversational way (1-2 sentences): {json.dumps(decision.get('operations', []))}"""
                    response_text = self.core.llm.generate(
                        prompt_text,
                        system_prompt="You describe what image edits were applied. Be brief and natural."
                    )
                    content = response_text.strip().strip('"').strip("'").strip()
                except Exception:
                    content = ""
                return {"type": "image_edit", "content": content, "image_data": img_b64, "image_type": "png", "sources": []}

            elif approach in ("inpaint", "img2img"):
                from io import BytesIO
                img_buf = BytesIO()
                if pil_image.mode != "RGB":
                    pil_image = pil_image.convert("RGB")
                pil_image.save(img_buf, format="PNG")
                img_bytes = img_buf.getvalue()
                import base64
                img_b64 = base64.b64encode(img_bytes).decode()
                result = self.core.image_gen.img2img(
                    img_b64,
                    decision.get("prompt", query),
                    strength=decision.get("strength", 0.7),
                    mask_description=decision.get("mask_description") if approach == "inpaint" else None,
                )
                if result and isinstance(result, dict) and result.get("image_data"):
                    gen_prompt = f"""The user requested: {query}

The image was {'edited using AI inpainting' if approach == 'inpaint' else 'redesigned using AI image-to-image'}. Describe the result naturally in 1-2 sentences. Don't mention technical details."""
                    try:
                        response_text = self.core.llm.generate(
                            gen_prompt,
                            system_prompt="You describe image editing results briefly and naturally."
                        )
                        content = response_text.strip().strip('"').strip("'").strip()
                    except Exception:
                        content = ""
                    return {"type": "image_edit", "content": content, "image_data": result["image_data"], "image_type": "png", "sources": []}
                return self._modification_error_response(query, "Image editing failed. Please try a different request.", approach)

            elif approach == "generate":
                return self._handle_image_generation(decision.get("prompt", query), "")

            return self._modification_error_response(query, "Could not determine the appropriate editing approach.", approach)
        except json.JSONDecodeError:
            return self._modification_error_response(query, "Could not interpret your request.", "unknown")
        except Exception:
            return self._modification_error_response(query, "Something went wrong while editing.", "unknown")

    def _handle_image_generation(self, prompt, context):
        try:
            img_bytes, error = self.core.image_gen.generate(prompt)
            if img_bytes:
                b64 = base64.b64encode(img_bytes).decode("utf-8")
                return {
                    "type": "image_gen",
                    "content": f"Generated: {prompt}",
                    "image_data": b64,
                    "image_type": "png",
                    "sources": [],
                }
            error_msg = error or "Could not generate the image. Try a different prompt."
            return {"type": "error", "content": error_msg, "sources": []}
        except Exception:
            return {"type": "error", "content": "Could not generate the image. Try again.", "sources": []}

    def _handle_file_generation(self, query, context):
        try:
            conv = f"\nConversation history:\n{context}\n" if context else ""
            prompt = f"""{conv}The user wants to generate a file. Determine what type of file they want and create it.

User request: {query}

Respond with ONLY valid JSON - no markdown, no code fences:
{{"file_type": "pdf|csv|svg|json|html|md|txt", "filename": "suggested filename with extension", "content": "the full file content here"}}

Rules:
- For CSV: return comma-separated values with header row
- For PDF: return the text content that should appear in the document
- For SVG: return valid SVG markup inside an <svg> tag
- For JSON: return valid JSON
- For HTML: return a complete HTML document
- For MD: return markdown content
- For TXT: return plain text

The content you provide will be written directly into the file, so make sure it's complete and properly formatted."""
            resp = self.core.llm.generate(prompt, system_prompt="You generate files. Respond with valid JSON only.")
            resp = resp.strip()
            if resp.startswith("```"):
                resp = resp.split("\n", 1)[-1]
                if "```" in resp:
                    resp = resp.split("```")[0]
            decision = json.loads(resp)
            file_type = decision.get("file_type", "txt")
            filename = decision.get("filename", f"file.{file_type}")
            content = decision.get("content", query)
            result = self.core.file_gen.generate(content, file_type, filename)
            if result and result.get("file_data"):
                return {
                    "type": "file_gen",
                    "content": f"Here is your {file_type.upper()} file: {result['file_name']}",
                    "file_data": result["file_data"],
                    "file_name": result["file_name"],
                    "file_type": result["file_type"],
                    "mime": result.get("mime", "text/plain"),
                    "sources": [],
                }
            return {"type": "error", "content": "Could not generate that file. Try a different request.", "sources": []}
        except json.JSONDecodeError:
            return {"type": "error", "content": "Could not interpret your request. Try being more specific about the file type.", "sources": []}
        except Exception:
            return {"type": "error", "content": "Could not generate the file. Try again.", "sources": []}

    def _handle_file(self, query, file_path, context, max_tokens=None):
        try:
            text = ""
            from pathlib import Path
            path = Path(file_path)
            ext = path.suffix.lower()
            if ext in (".txt", ".md", ".py", ".js", ".ts", ".html", ".css", ".json", ".xml", ".yaml", ".yml", ".csv"):
                text = path.read_text(encoding="utf-8", errors="replace")
            elif ext == ".pdf":
                try:
                    import pypdf
                    reader = pypdf.PdfReader(str(path))
                    text = "\n".join(page.extract_text() or "" for page in reader.pages)
                except ImportError:
                    text = "[PDF processing requires pypdf library]"
            elif ext in (".docx", ".doc"):
                try:
                    import docx
                    doc = docx.Document(str(path))
                    text = "\n".join(p.text for p in doc.paragraphs)
                except ImportError:
                    text = "[DOCX processing requires python-docx library]"
            else:
                text = path.read_text(encoding="utf-8", errors="replace")
            if len(text) > 5000:
                text = text[:5000] + "\n...[truncated]"
            prompt = f"""{context}

The user shared a file ({path.name}) with the following content:

{text}

User query: {query}

Respond naturally based on the file content. If the user didn't ask a specific question, summarize the file contents."""
            response = self.core.llm.generate(prompt, max_tokens=max_tokens)
            return {"type": "chat", "content": response, "sources": []}
        except Exception as e:
            return {"type": "error", "content": "Could not process that file. Try a different format.", "sources": []}
