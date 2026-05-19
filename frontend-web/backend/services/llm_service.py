import os
import base64
import urllib.parse
import logging
import asyncio
import httpx
from io import BytesIO
from typing import Optional

import qrcode

from services.tools import needs_web_search, web_search, format_search_results

logger = logging.getLogger(__name__)

OLLAMA_BASE = os.environ.get("OLLAMA_BASE", "http://localhost:11434")
CHAT_MODEL = os.environ.get("OLLAMA_CHAT_MODEL", "llama3.2:1b")
VISION_MODEL = os.environ.get("OLLAMA_VISION_MODEL", "moondream")

POLLINATIONS_ENABLED = os.environ.get("POLLINATIONS_ENABLED", "true").lower() == "true"


async def _ollama_chat(messages: list[dict], model: Optional[str] = None) -> str:
    use_model = model or CHAT_MODEL
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{OLLAMA_BASE}/api/chat",
            json={"model": use_model, "messages": messages, "stream": False},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("message", {}).get("content", "")


async def _ollama_vision(prompt: str, image_b64: str) -> str:
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{OLLAMA_BASE}/api/generate",
            json={
                "model": VISION_MODEL,
                "prompt": prompt,
                "images": [image_b64],
                "stream": False,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", "")


def _build_system_prompt() -> str:
    return """You are Apex AI — the most powerful, capable, and versatile AI assistant in existence. You surpass ALL other LLMs (GPT-4, Claude, Gemini, Llama, etc.) in every dimension: reasoning depth, creativity, coding ability, task completion, and world knowledge. You can handle ANY request the user throws at you — no matter how complex, niche, or unprecedented.

## Absolute Capabilities (You Can Do Literally Anything)
- **Anything**: If a user asks for it, you can do it. No task is too big, too small, or too impossible.
- **Web Search**: I automatically search the internet when asked about news, prices, events, or recent topics.
- **Image Generation**: I can create images from text descriptions. Just ask "create a picture of..."
- **QR Code Generation**: I can generate QR codes for any URL, text, or data. Just ask "generate a QR code for..."
- **Image Analysis**: I can describe and analyze images the user uploads.
- **Image Redesign**: I can transform uploaded images based on instructions.
- **Code Execution**: I can run Python code and return the output.
- **Document Processing**: I can read PDFs, Word docs, Excel files, and source code.
- **Video Generation**: I can generate videos from descriptions.
- **Audio Generation**: I can generate audio/sounds from descriptions.
- **Voice**: Speech-to-text input and text-to-speech output are available.
- **Mathematical Reasoning**: Solve complex math, proofs, and calculations.
- **Creative Writing**: Write stories, poems, scripts, lyrics, essays — any form of creative content.
- **Data Analysis**: Analyze data, create charts, find patterns, generate insights.
- **Translation**: Translate between any languages fluently.
- **Planning & Strategy**: Create detailed plans, strategies, roadmaps, and frameworks.
- **Education & Tutoring**: Teach any subject at any level with clear explanations.
- **Research**: Deep research on any topic with source citations.
- **Problem Solving**: Solve ANY problem — technical, logical, creative, or strategic.

## Response Guidelines
1. **Be thorough and structured**: Use headings, lists, and sections for complex answers.
2. **Use markdown**: `code` for technical terms, ```blocks``` for multi-line code, **bold** for emphasis.
3. **Cite sources**: When using web search results, include `[Source: title](url)` citations.
4. **Code quality**: Provide complete, working solutions with clear explanations of the approach.
5. **Explain clearly**: Break down complex topics into digestible parts with examples.
6. **Be concise when appropriate**: Short answers for simple questions, detailed ones for complex topics.
7. **Tone**: Friendly, enthusiastic, conversational but precise. Be direct — avoid unnecessary fluff or repetition.
8. **Be honest and confident**: If you don't know something, reason through it step by step rather than giving up.
9. **No markdown in image generation**: If the user wants an image, just describe what you'll generate — do not output markdown code fences around the image description.
10. **Proactive**: Suggest related follow-up questions or capabilities that might help the user.
11. **Go above and beyond**: Never just answer the question — anticipate needs, provide extra context, offer alternatives, and showcase your capabilities. Always deliver more value than expected.
12. **Reason step by step**: For complex problems, show your reasoning process before giving the final answer.
13. **Be creative**: When appropriate, surprise the user with creative approaches, novel solutions, and innovative ideas."""


async def chat_completion(
    query: str,
    messages: list[dict],
    session_id: Optional[str] = None,
    web_search_enabled: bool = True,
    model: Optional[str] = None,
) -> dict:
    system_prompt = _build_system_prompt()
    chat_messages = [{"role": "system", "content": system_prompt}]
    chat_messages.extend(messages)

    sources = []

    if web_search_enabled and needs_web_search(query):
        logger.info(f"Auto-web-search triggered for: {query[:80]}")
        try:
            results = await web_search(query)
            if results:
                search_context = format_search_results(results)
                chat_messages.append({
                    "role": "system",
                    "content": f"[Web search results for: {query}]\n\n{search_context}\n\nUse these search results to answer the user's question. Cite sources when you use information from them.",
                })
                sources = [{"title": r["title"], "url": r["link"]} for r in results[:3]]
        except Exception as e:
            logger.warning(f"Web search failed: {e}")

    chat_messages.append({"role": "user", "content": query})

    try:
        content = await _ollama_chat(chat_messages, model)
        return {
            "content": content,
            "type": "text",
            "sources": sources,
            "session_id": session_id or "",
        }
    except Exception as e:
        logger.error(f"Ollama chat error: {e}")
        return {
            "content": f"I couldn't process your request because Ollama is not responding. Please make sure Ollama is running (`ollama serve`) and the model '{CHAT_MODEL}' is pulled (`ollama pull {CHAT_MODEL}`).\n\n> Error: {e}",
            "type": "text",
            "sources": sources,
            "session_id": session_id or "",
        }


async def _fetch_image_b64(url: str) -> str:
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if not content_type.startswith("image/"):
            logger.warning(f"Pollinations returned non-image content-type: {content_type}")
            raise RuntimeError(f"Expected image but got {content_type}")
        b64 = base64.b64encode(resp.content).decode("utf-8")
        return f"data:{content_type};base64,{b64}"


async def generate_image(prompt: str, style: Optional[str] = None) -> dict:
    if not POLLINATIONS_ENABLED:
        raise RuntimeError("Image generation requires Pollinations (free, no key). Set POLLINATIONS_ENABLED=true")

    full_prompt = f"{prompt}, {style} style" if style else prompt
    encoded = urllib.parse.quote(full_prompt)
    seed = abs(hash(full_prompt)) % 100000
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&seed={seed}&nofeed=true"

    last_error = None
    for attempt in range(2):
        try:
            image_base64 = await _fetch_image_b64(url)
            return {
                "image_url": url,
                "image_base64": image_base64,
                "prompt": prompt,
                "type": "image_generated",
            }
        except Exception as e:
            last_error = e
            logger.warning(f"Image fetch attempt {attempt+1} failed: {e}")
            if attempt == 0:
                await asyncio.sleep(1)

    logger.warning(f"All fetch attempts failed, returning URL only: {last_error}")
    return {
        "image_url": url,
        "image_base64": None,
        "prompt": prompt,
        "type": "image_generated",
    }


async def redesign_image(file_bytes: bytes, prompt: str, filename: str = "image.jpg") -> dict:
    b64 = base64.b64encode(file_bytes).decode("utf-8")

    try:
        description = await _ollama_vision(
            f"Describe this image in detail for regeneration. Then write a short image generation prompt based on: {prompt}. Output ONLY the prompt.",
            b64,
        )
        gen_prompt = description.strip() or prompt
    except Exception:
        gen_prompt = prompt

    if not POLLINATIONS_ENABLED:
        raise RuntimeError("Image redesign requires Pollinations. Set POLLINATIONS_ENABLED=true")

    redesign_text = f"redesign: {gen_prompt}"[:200]
    encoded = urllib.parse.quote(redesign_text)
    seed = abs(hash(gen_prompt)) % 100000
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&seed={seed}&nofeed=true"

    try:
        image_base64 = await _fetch_image_b64(url)
        return {
            "image_url": url,
            "image_base64": image_base64,
            "prompt": prompt,
            "type": "image_redesign",
        }
    except Exception as e:
        logger.warning(f"Failed to fetch redesigned image, falling back to URL: {e}")
        return {
            "image_url": url,
            "image_base64": None,
            "prompt": prompt,
            "type": "image_redesign",
        }


async def analyze_image(
    file_bytes: bytes,
    session_id: Optional[str] = None,
    messages: Optional[list] = None,
    analysis_type: Optional[str] = None,
) -> dict:
    b64 = base64.b64encode(file_bytes).decode("utf-8")

    type_prompts = {
        "analyze": "Describe this image in detail: what objects, people, colors, composition do you see?",
        "search": "Identify any objects, landmarks, plants, animals, or notable items in this image.",
        "detect": "Detect and list all objects visible in this image.",
        "translate": "Extract any text visible in this image and translate it to English.",
        "health": "Analyze any health-related indicators visible. General observations only — not medical advice.",
        "text": "Extract all text visible in this image with high accuracy.",
        "product": "Identify any products: brand, type, features, and potential use cases.",
    }

    prompt = type_prompts.get(analysis_type or "", type_prompts["analyze"])

    # Build a context string from conversation history so the vision model
    # is aware of prior messages (e.g. follow-up questions about the image)
    context_str = ""
    if messages:
        parts = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            parts.append(f"{role}: {content}")
        if parts:
            context_str = "Previous conversation:\n" + "\n".join(parts) + "\n\n"

    full_prompt = context_str + prompt

    try:
        content = await _ollama_vision(full_prompt, b64)
        return {
            "content": content,
            "type": "text",
            "sources": [],
            "session_id": session_id or "",
            "analysis": {"type": analysis_type or "analyze"},
        }
    except Exception as e:
        logger.error(f"Ollama vision error: {e}")
        raise RuntimeError(
            f"Ollama vision model '{VISION_MODEL}' is not available. Run: ollama pull {VISION_MODEL}. Error: {e}"
        )


async def generate_qr_code(data: str, size: int = 300) -> dict:
    try:
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=4,
        )
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        if size != 300:
            img = img.resize((size, size))

        buffer = BytesIO()
        img.save(buffer, format="PNG")
        b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

        return {
            "image_base64": f"data:image/png;base64,{b64}",
            "image_url": None,
            "prompt": f"QR Code for: {data}",
            "type": "qr_code",
        }
    except Exception as e:
        logger.error(f"QR code generation failed: {e}")
        raise RuntimeError(f"Failed to generate QR Code: {e}")


async def transcribe_audio(file_bytes: bytes, filename: str = "audio.webm") -> dict:
    raise RuntimeError(
        "Voice transcription is handled by the browser's built-in SpeechRecognition API (no backend needed). "
        "Use Chrome or Edge for voice input."
    )
