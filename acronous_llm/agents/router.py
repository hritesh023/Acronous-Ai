import json
import base64
import string as string_module
from pathlib import Path

class QueryRouter:
    def __init__(self, neural_engine, core_engine):
        self.neural = neural_engine
        self.core = core_engine

    def _likely_has_typos(self, text):
        words = [w.strip(string_module.punctuation).lower() for w in text.split() if w.strip(string_module.punctuation)]
        if len(words) < 2:
            return False
        vowels = set('aeiouy')
        suspicious = 0
        for word in words:
            if len(word) <= 1 and word not in ('a', 'i'):
                suspicious += 1
                continue
            alpha = [c for c in word if c.isalpha()]
            if not alpha:
                continue
            if not any(c in vowels for c in alpha):
                suspicious += 1
                continue
            cons_run = 0
            for c in word:
                if c.isalpha() and c not in vowels:
                    cons_run += 1
                    if cons_run > 3:
                        suspicious += 1
                        break
                else:
                    cons_run = 0
            else:
                if len(word) > 2 and any(word[i] == word[i-1] == word[i-2] for i in range(2, len(word))):
                    suspicious += 1
        return suspicious / max(len(words), 1) > 0.25

    def auto_correct(self, text):
        if not text or len(text.strip()) < 3:
            return text
        if not self._likely_has_typos(text):
            return text
        try:
            prompt = f"""Fix any spelling mistakes and typos in this message. Return ONLY the corrected version with no explanation, no quotes, no extra text.

Message: {text}
Corrected:"""
            corrected = self.core.llm.generate(
                prompt,
                system_prompt="You fix typos and spelling mistakes. Return only the corrected text with nothing else."
            )
            corrected = corrected.strip().strip('"').strip("'").strip()
            return corrected if corrected else text
        except Exception:
            return text

    def route(self, query):
        query_lower = query.lower().strip()
        embedding = self.core.embedder.embed(query)
        intent_id, intent_probs = self.neural.predict_intent(embedding, return_probs=True)
        intent_name = self.neural.classifier.get_intent_name(intent_id)

        features = self._extract_features(query_lower)
        features["intent_id"] = intent_id
        features["intent_name"] = intent_name
        features["intent_confidence"] = max(intent_probs) if isinstance(intent_probs, list) else 0

        intent_to_type = {
            "image_generation": "image_generation",
            "image_analysis": "image_analysis",
            "code_generation": "code_generation",
            "translation": "translation",
        }
        route_type = intent_to_type.get(intent_name)
        if route_type is None:
            route_type = self._determine_type(query)
        features["type"] = route_type
        features["needs_search"] = route_type in ["web_search", "news", "factual"]
        features["needs_planning"] = self._needs_planning(query)
        features["embedding"] = embedding

        return features

    def _extract_features(self, query_lower):
        words = query_lower.split()
        return {
            "has_question": "?" in query_lower,
            "word_count": len(words),
            "has_url": "http" in query_lower or "www." in query_lower,
        }

    def _determine_type(self, query):
        try:
            prompt = f"""Classify the user's request into exactly one category.

Categories:
- image_generation: user wants to CREATE or GENERATE an image, picture, drawing, visual, painting, sketch, illustration
- image_analysis: user wants to ANALYZE or DESCRIBE an existing image or photo
- code_generation: user wants code, functions, algorithms, debugging
- translation: user wants text translated to another language
- web_search: user asks about current events, news, weather, or needs up-to-date web info
- factual: user asks a factual question answerable from general knowledge
- general_chat: everything else (conversation, opinions, jokes, etc.)

Examples:
- "draw a sunset with mountains" -> image_generation
- "paint a landscape" -> image_generation
- "sketch a portrait" -> image_generation
- "make a picture of a cat" -> image_generation
- "generate an image of a forest" -> image_generation
- "show me a picture of a lion" -> image_generation
- "illustrate a fantasy scene" -> image_generation
- "create a digital art of a dragon" -> image_generation
- "analyze this image" -> image_analysis
- "what is in this photo" -> image_analysis
- "write a function to sort an array" -> code_generation
- "translate hello to french" -> translation
- "what is the weather today" -> web_search
- "what is the capital of France" -> factual
- "tell me a joke" -> general_chat
- "how are you" -> general_chat

User request: {query}"""
            resp = self.core.llm.generate(prompt, system_prompt="You classify user intents concisely.")
            resp = resp.strip().lower()
            valid = {"image_generation", "image_analysis", "code_generation", "translation", "web_search", "factual", "general_chat"}
            for v in valid:
                if v in resp:
                    return v
            return "general_chat"
        except Exception:
            return "general_chat"

    def _needs_planning(self, query):
        try:
            prompt = f"""Does this request require multi-step research or comparison? Answer with "yes" or "no".

Examples:
- "compare Python and JavaScript" -> yes
- "research the latest AI developments" -> yes
- "write a detailed report on climate change" -> yes
- "what is 2+2" -> no
- "tell me a joke" -> no
- "draw a cat" -> no

Request: {query}"""
            resp = self.core.llm.generate(prompt, system_prompt="You answer concisely with yes or no.")
            return resp.strip().lower().startswith("yes")
        except Exception:
            return False

    def execute(self, query, route, session_id="default", image=None, messages=None, file_path=None):
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

        if image is not None:
            if self._is_modification_request(query, image):
                result = self._handle_image_modification(query, image)
            else:
                result = self._handle_image(query, image)
        elif file_path is not None:
            result = self._handle_file(query, file_path, context)
        elif route_type == "image_generation":
            result = self._handle_image_generation(query, context)
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
        if route_type in ("web_search", "factual"):
            result = self._handle_search(query, context) if route_type == "web_search" else self._handle_factual(query, context)
            content = result.get("content", "")
            chunk_size = 30
            for i in range(0, len(content), chunk_size):
                yield content[i:i + chunk_size]
        else:
            prompt = f"{context}\nUser: {query}" if context else f"User: {query}"
            system_prompt = "You are Acronous AI, a helpful local AI assistant."
            yield from self.core.llm.generate_stream(prompt, system_prompt)

    def _handle_chat(self, query, context):
        prompt = f"{context}\nUser: {query}" if context else f"User: {query}"
        response = self.core.llm.generate(prompt)
        return {"type": "chat", "content": response, "sources": []}

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
            system_prompt="You are Acronous AI. Answer using the search results provided. Cite sources when possible."
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
        is_auto = not query or not query.strip()
        if is_auto:
            prompt = f"""{image_context}

The user captured this image with no specific request. Analyze it purely based on what's detected above and provide your insights."""
        else:
            prompt = f"""{image_context}

User query about image: {query}

Respond based on the image analysis above."""
        response = self.core.llm.generate(prompt)
        return {"type": "image_analysis", "content": response, "analysis": analysis, "objects": objects}

    def _is_modification_request(self, query, image=None):
        if not query or not query.strip():
            return False
        try:
            image_context = ""
            if image and self.core.vision:
                try:
                    analysis = self.core.vision.analyze_image(image)
                    image_context = f"\nImage analysis available: {json.dumps(analysis, indent=2)[:200]}"
                except Exception:
                    pass
            prompt = f"""Determine if the user wants to MODIFY/EDIT/TRANSFORM/CONVERT the uploaded image or file (not just analyze/describe it).

Examples of MODIFICATION requests:
- "remove the person from this image"
- "erase the background and make it transparent"
- "change this to a cartoon style"
- "add a cat to this photo"
- "redesign this room to look modern"
- "make this look like a painting"
- "convert this image to black and white"
- "turn this photo into a sketch"
- "replace the sky with stars"
- "change the color of the car to red"
- "convert this file to json"
- "extract text from this and save as markdown"
- "translate this pdf to spanish"

Examples of ANALYSIS/DESCRIPTION requests (NOT modification):
- "what is in this image"
- "describe this photo"
- "how many people are there"
- "read the text in this image"
- "tell me about this file"
- "what does this document contain"

User request: {query}{image_context}

Answer with "yes" or "no":"""
            resp = self.core.llm.generate(prompt, system_prompt="You classify requests concisely.")
            return resp.strip().lower().startswith("yes")
        except Exception:
            return False

    def _handle_image_modification(self, query, image):
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

            decision_prompt = f"""You are an expert image editing AI. Analyze the user's request and the image, then decide the BEST editing approach.

User request: "{query}"

Image info: {img_width}x{img_height}px, mode={pil_image.mode if hasattr(pil_image, 'mode') else 'unknown'}
Image Analysis: {json.dumps(analysis, indent=2)[:300]}
Detected Objects: {json.dumps(objects, indent=2)[:300] if objects else 'None'}

Available editing approaches:
1. "pil" - Direct pixel manipulation using Python Imaging Library. Best for:
   - Color adjustments (grayscale, sepia, invert, colorize, brightness, contrast, saturation)
   - Geometric transforms (resize, crop, rotate, flip, perspective)
   - Filters (blur, sharpen, smooth, edge enhance, emboss, contour, posterize, solarize)
   - Overlays and composites (add borders, add text/labels)
   - Channel operations (extract R/G/B, swap channels)
   These are FAST and work without any AI model. Good for simple, precise edits.

2. "inpaint" - AI-powered inpainting that selectively edits specific regions. BEST for:
   - Removing/erasing specific objects ("remove the person", "delete the car", "erase the text")
   - Replacing objects with something else ("change the dog to a cat", "turn the car red")
   - Adding new objects to specific locations ("add a tree on the left", "put a bird in the sky")
   - Editing specific regions while keeping the rest unchanged ("change the sky", "replace the background")
   Uses an AI model to fill in masked areas realistically.

3. "img2img" - Image-to-image generation using an AI model. Best for:
   - Redesigning while preserving overall structure/composition
   - Changing artistic style (make it look like a painting, sketch, cartoon)
   - Changing lighting, weather, seasons throughout the whole image
   - Significant transformation of the whole scene
   Requires an image generation model (diffusers/HF/OpenAI).

4. "generate" - Generate a completely new image from scratch. Best for:
   - Complete transformation with no relation to original
   - Creating something entirely different
   Requires an image generation model.

Available PIL operations (for 'pil' approach):
- resize: {{"op": "resize", "width": N, "height": N}}
- crop: {{"op": "crop", "left": N, "top": N, "right": N, "bottom": N}}
- rotate: {{"op": "rotate", "degrees": N}}
- flip_horizontal: {{"op": "flip_horizontal"}}
- flip_vertical: {{"op": "flip_vertical"}}
- grayscale: {{"op": "grayscale"}}
- invert: {{"op": "invert"}}
- sepia: {{"op": "sepia"}}
- brightness: {{"op": "brightness", "factor": F}} (0.0=black, 1.0=original, 2.0=double)
- contrast: {{"op": "contrast", "factor": F}}
- saturation: {{"op": "saturation", "factor": F}}
- sharpness: {{"op": "sharpness", "factor": F}}
- blur: {{"op": "blur", "radius": N}}
- sharpen: {{"op": "sharpen"}}
- smooth: {{"op": "smooth"}}
- edge_enhance: {{"op": "edge_enhance"}}
- emboss: {{"op": "emboss"}}
- posterize: {{"op": "posterize", "bits": N}} (1-8 bits per channel)
- solarize: {{"op": "solarize", "threshold": N}} (0-255)
- equalize: {{"op": "equalize"}}
- autocontrast: {{"op": "autocontrast", "cutoff": N}} (0-100)
- colorize: {{"op": "colorize", "color": "#HEXCODE"}} (tint image with color)
- border: {{"op": "border", "width": N, "color": "#HEXCODE"}}
- overlay: {{"op": "overlay", "mode": "colorize|blend", "color": "#HEXCODE", "alpha": F}}

Respond with ONLY valid JSON in this exact format - no markdown, no code fences:
{{"approach": "pil|inpaint|img2img|generate", "operations": [...], "prompt": "description if needed", "mask_description": "what region to edit", "strength": 0.7}}

For 'pil' approach, list multiple operations to apply in order.
For 'inpaint' approach, provide:
  - 'prompt': what to generate in the edited region (e.g., "a red car" if replacing, "empty background" if erasing)
  - 'mask_description': describe WHAT region to edit (e.g., "the person on the left", "the sky", "the car in the center", "the background")
  - 'strength': how much to change (0.0-1.0, default 0.85)
For 'img2img', provide a 'prompt' describing the modified image and optional 'strength' (0.0-1.0).
For 'generate', provide a 'prompt' for the new image."""

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
                                if c.startswith("#"):
                                    c = c.lstrip("#")
                                    cr, cg, cb = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
                                else:
                                    cr, cg, cb = 128, 128, 128
                                gray = ImageOps.grayscale(edited)
                                color_layer = Image.new("RGB", gray.size, (cr, cg, cb))
                                edited = Image.blend(Image.merge("RGB", [gray]*3), color_layer, 0.4)
                            except Exception:
                                pass
                        elif op == "border":
                            edited = ImageOps.expand(edited, border=op_desc.get("width", 5), fill=op_desc.get("color", "#000000"))
                        elif op == "overlay":
                            try:
                                c = op_desc.get("color", "#000000")
                                if c.startswith("#"):
                                    c = c.lstrip("#")
                                    cr2, cg2, cb2 = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
                                else:
                                    cr2, cg2, cb2 = 0, 0, 0
                                overlay = Image.new("RGB", edited.size, (cr2, cg2, cb2))
                                alpha = op_desc.get("alpha", 0.3)
                                edited = Image.blend(edited, overlay, alpha)
                            except Exception:
                                pass
                    except Exception:
                        continue

                buf = io.BytesIO()
                edited.save(buf, format="PNG", optimize=True)
                img_bytes = buf.getvalue()
                ops_summary = "; ".join([
                    f"{o.get('op', '')}" + (f"({', '.join(f'{k}={v}' for k,v in o.items() if k != 'op')})" if any(k != 'op' for k in o) else "")
                    for o in decision.get("operations", [])
                ])
                desc = self.core.llm.generate(
                    f"I just applied these edits to the user's image: {ops_summary}. "
                    f"Their request was: '{query}'. Describe what was done briefly.",
                    system_prompt="You describe image edits conversationally."
                )
                content_msg = desc.strip() if desc else ""

            elif approach == "inpaint":
                img_prompt = decision.get("prompt", query)
                mask_description = decision.get("mask_description", "")
                strength = decision.get("strength", 0.85)
                if self.core.image_gen.is_available():
                    img_bytes, error = self.core.image_gen.inpaint(
                        pil_image, mask_description, img_prompt, strength=strength
                    )
                else:
                    img_bytes, error = None, "no_generator"
                if error or img_bytes is None:
                    return {"type": "error", "content": "", "sources": []}
                desc = self.core.llm.generate(
                    f"The user requested image editing: '{query}'. I applied inpainting with prompt '{img_prompt}' "
                    f"on the region: '{mask_description}'. Describe the result briefly.",
                    system_prompt="You describe image edits conversationally."
                )
                content_msg = desc.strip() if desc else ""

            elif approach == "img2img":
                img_prompt = decision.get("prompt", query)
                strength = decision.get("strength", 0.7)
                if self.core.image_gen.is_available():
                    img_bytes, error = self.core.image_gen.redesign(pil_image, img_prompt, strength=strength)
                else:
                    img_bytes, error = None, "no_generator"
                if error or img_bytes is None:
                    img_bytes, error = self.core.image_gen.generate(img_prompt)
                if error or img_bytes is None:
                    return {"type": "error", "content": "", "sources": []}
                desc = self.core.llm.generate(
                    f"The user requested: '{query}'. I redesigned their image using prompt '{img_prompt}'. "
                    f"Describe what was done briefly.",
                    system_prompt="You describe image edits conversationally."
                )
                content_msg = desc.strip() if desc else ""

            else:
                img_prompt = decision.get("prompt", query)
                if self.core.image_gen.is_available():
                    img_bytes, error = self.core.image_gen.generate(img_prompt)
                else:
                    img_bytes, error = None, "no_generator"
                if error or img_bytes is None:
                    return {"type": "error", "content": "", "sources": []}
                desc = self.core.llm.generate(
                    f"The user requested: '{query}'. I generated a completely new image with prompt '{img_prompt}'. "
                    f"Describe the result briefly.",
                    system_prompt="You describe image edits conversationally."
                )
                content_msg = desc.strip() if desc else ""

            b64 = base64.b64encode(img_bytes).decode("utf-8")
            return {
                "type": "image_modification",
                "content": content_msg,
                "image_data": b64,
                "image_type": "modified",
                "sources": []
            }
        except json.JSONDecodeError:
            content_msg = ""
            try:
                from PIL import Image as PilImg
                import io
                if isinstance(image, str):
                    retry_img = PilImg.open(image)
                else:
                    retry_img = image
                buf = io.BytesIO()
                if hasattr(retry_img, 'save'):
                    retry_img.save(buf, format="PNG")
                    return {
                        "type": "chat",
                        "content": content_msg,
                        "image_data": base64.b64encode(buf.getvalue()).decode("utf-8"),
                        "image_type": "original",
                        "sources": []
                    }
            except Exception:
                pass
            return {
                "type": "chat",
                "content": content_msg,
                "sources": []
            }

    def _handle_file(self, query, file_path, context):
        file_path = str(file_path)
        ext = Path(file_path).suffix.lower()
        file_name = Path(file_path).name

        content_text = ""
        content_type = "unknown"

        text_exts = {'.txt', '.md', '.csv', '.json', '.xml', '.log', '.py', '.js', '.ts', '.html', '.css', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.sh', '.bat', '.ps1', '.sql', '.r', '.go', '.rs', '.java', '.cpp', '.c', '.h', '.hpp', '.rb', '.php', '.swift', '.kt', '.scala', '.pl', '.lua', '.dart'}
        doc_exts = {'.pdf', '.docx', '.doc', '.odt', '.rtf'}

        if ext in text_exts:
            content_text = Path(file_path).read_text(encoding='utf-8', errors='replace')
            content_type = "text"
        elif ext == '.pdf':
            content_type = "pdf"
            try:
                import PyPDF2
                with open(file_path, 'rb') as f:
                    reader = PyPDF2.PdfReader(f)
                    content_text = "\n".join([page.extract_text() or "" for page in reader.pages])
            except ImportError:
                try:
                    import pdfplumber
                    with pdfplumber.open(file_path) as pdf:
                        content_text = "\n".join([page.extract_text() or "" for page in pdf.pages])
                except ImportError:
                    content_text = f"[PDF file: {file_name}, {Path(file_path).stat().st_size} bytes]"
        elif ext in {'.docx', '.doc'}:
            content_type = "document"
            try:
                import docx
                doc = docx.Document(file_path)
                content_text = "\n".join([p.text for p in doc.paragraphs])
            except ImportError:
                content_text = f"[Word document: {file_name}, {Path(file_path).stat().st_size} bytes]"
        else:
            content_text = f"[File: {file_name}, Type: {ext or 'unknown'}, Size: {Path(file_path).stat().st_size} bytes]"
            content_type = "binary"

        max_chars = 15000
        if len(content_text) > max_chars:
            content_text = content_text[:max_chars] + f"\n\n[...truncated, total {len(content_text)} characters]"

        if not query or not query.strip():
            query = f"Analyze this {content_type} file: {file_name}"

        file_prompt = f"""User uploaded a file and asks: "{query}"

File: {file_name}
Type: {content_type}

Content:
{content_text if content_text else "[No extractable text content]"}

Process the user's request based on the file content above.
- If they ask for conversion, convert the content and provide the result.
- If they ask for analysis, analyze thoroughly.
- If they ask for extraction, extract the requested information.
- If they ask for translation, translate the content.
Provide your response with the processed result."""

        response = self.core.llm.generate(
            file_prompt,
            system_prompt="You are Acronous AI, a file processing assistant. Process the file according to the user's request."
        )

        return {
            "type": "file_processing",
            "content": response,
            "sources": []
        }

    def _handle_image_generation(self, query, context):
        try:
            image_type = self._classify_image_prompt(query)
            params = self._suggest_image_params(query, image_type)
            enriched_prompt = self._enrich_image_prompt(query, image_type)
            img_bytes, error = self.core.image_gen.generate(
                enriched_prompt,
                steps=params.get("steps"),
                guidance_scale=params.get("guidance_scale"),
                height=params.get("height"),
                width=params.get("width"),
                image_type=image_type,
            )
            if error:
                return {"type": "error", "content": "", "sources": []}
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            return {
                "type": "image_gen",
                "content": query,
                "image_data": b64,
                "image_type": image_type,
                "sources": []
            }
        except Exception:
            return {"type": "error", "content": "", "sources": []}

    def _classify_image_prompt(self, query):
        q = query.lower()
        if any(w in q for w in ['cartoon', 'anime', 'animated', 'animation']):
            return "animated"
        if any(w in q for w in ['diagram', 'flowchart', 'flow chart', 'schematic']):
            return "diagram"
        if any(w in q for w in ['qr code', 'qrcode', 'barcode']):
            return "qr_code"
        return "realistic"

    def _enrich_image_prompt(self, query, image_type="realistic"):
        try:
            if image_type == "realistic":
                prompt_text = f"""Rewrite this image description into a highly detailed NATURAL PHOTOGRAPHIC prompt for image generation. This must NOT look like a painting or illustration — it must look like a real photograph.

Focus on: natural lighting, realistic textures, fine details, authentic colors, depth of field, natural skin texture (if people are involved), realistic materials, and environmental authenticity.

AVOID: painterly effects, brush strokes, canvas texture, airbrushing, illustrated look, soft blur, artificial smoothness, cartoonish features, stylized rendering.

Add relevant photography terms such as: "DSLR photography", "natural lighting", "sharp focus", "highly detailed", "realistic textures", "authentic colors", "natural skin texture", "depth of field". Do NOT use terms like "8K" or "photorealistic" as they trigger painting-like outputs.

Return ONLY the enhanced prompt.

Original: {query}
Enhanced:"""
                system = "You enhance prompts for photographic realism. Never add painting-like terms. Return only the enhanced prompt."
            elif image_type == "animated":
                prompt_text = f"""Rewrite this for an animated/cartoon style generator. Focus on vibrant colors and stylized art. Return ONLY the enhanced prompt.

Original: {query}
Enhanced:"""
                system = "You create animated-style image prompts."
            else:
                prompt_text = f"""Rewrite this for generating: {image_type}. Return ONLY the enhanced prompt.

Original: {query}
Enhanced:"""
                system = "You create image prompts."

            enriched = self.core.llm.generate(prompt_text, system_prompt=system)
            enriched = enriched.strip().strip('"').strip("'")
            if len(enriched) >= len(query) * 0.5:
                return enriched
        except Exception:
            pass

        if image_type == "realistic":
            return f"natural photography style, realistic textures, sharp focus, natural lighting, {query}"
        elif image_type == "animated":
            return f"animated style, vibrant colors, {query}"
        return query

    def _suggest_image_params(self, query, image_type="realistic"):
        try:
            prompt = f"""Suggest optimal generation parameters for this image request.
Return ONLY valid JSON: {{"steps": int, "guidance_scale": float, "height": int, "width": int}}

Image type: {image_type}
Request: {query}

JSON:"""
            resp = self.core.llm.generate(
                prompt,
                system_prompt="You suggest image generation parameters. Return valid JSON only."
            )
            resp = resp.strip()
            if resp.startswith("```"):
                resp = resp.split("\n", 1)[-1]
                if "```" in resp:
                    resp = resp.split("```")[0]
            params = json.loads(resp)
            return {
                "steps": int(params.get("steps", self.core.image_gen.config.IMAGE_STEPS)),
                "guidance_scale": float(params.get("guidance_scale", self.core.image_gen.config.IMAGE_GUIDANCE_SCALE)),
                "height": int(params.get("height", self.core.image_gen.config.IMAGE_HEIGHT)),
                "width": int(params.get("width", self.core.image_gen.config.IMAGE_WIDTH)),
            }
        except Exception:
            return {
                "steps": self.core.image_gen.config.IMAGE_STEPS,
                "guidance_scale": self.core.image_gen.config.IMAGE_GUIDANCE_SCALE,
                "height": self.core.image_gen.config.IMAGE_HEIGHT,
                "width": self.core.image_gen.config.IMAGE_WIDTH,
            }
