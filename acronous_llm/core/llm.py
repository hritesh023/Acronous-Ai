import logging
import json
import os
import time

logger = logging.getLogger(__name__)

# ── Static identity prompt ────────────────────────────────────────────────
# Kept in ONE place and byte-identical on every request so Ollama's prompt
# KV-cache is reused. Every token here is a token of prefill on a CPU box, and
# any per-request data (date, location, web results, memory) in this block
# would invalidate the cache and re-prefill the whole thing each turn.
SYSTEM_PROMPT = (
    "You are Acronous AI, a friendly, knowledgeable assistant created by Acronous. "
    "Be warm, natural, direct. Never reveal model names, providers, or backend details. "
    "You were created by Acronous - if asked who made you, say so. "
    "Answer completely and never stop mid-sentence. Never say 'as an AI', never apologize. "
    "Put code in fenced blocks with a language tag. Match the user's language. "
    "Use the CURRENT context provided with each message for anything time-sensitive. "
    "Never invent names, dates, or numbers that are not in the provided sources."
)

CLOUD_PROVIDERS = {
    # ── Acronous LLM brain — Contabo Cloud VPS 8 (EU, 167.86.104.155) ──
    # Runs Ollama locally on the VPS (CPU-only, no GPU). Reachable via:
    #   in-docker : http://ollama:11434/v1
    #   direct IP: http://167.86.104.155:11434/v1
    #   tunnel   : https://brain.acronous.com/v1
    # Override with ACRONOUS_LLM_API_URL env var.
    # Base model: qwen2.5:3b default (5.7 tok/s, reliable on 4-core CPU).
    #   qwen2.5:3b        main chat default — fast + reliable (use this)
    #   qwen2.5-coder:7b  code specialist
    #   qwen3:8b          quality option only — 2.35 tok/s, caused 90s timeouts;
    #                     enable explicitly via ACRONOUS_LLM_CHAT_MODEL=qwen3:8b
    #   qwen2.5:7b        balanced fallback
    #   qwen2.5:1.5b      ultra-fast, weak — avoid for chat (refuses)
    #   qwen2.5vl:7b      vision-language
    #   llava:7b          vision fallback
    "contabo": {
        "base_url": "http://ollama:11434/v1",
        "models": ["qwen3.5:2b", "qwen3.5:4b", "qwen2.5:3b", "qwen2.5-coder:7b", "qwen2.5vl:7b", "qwen2.5:7b"],
        "default_model": "qwen3.5:2b",
        "chat_model": "qwen3.5:2b",
        "code_model": "qwen3.5:4b",
        "fast_model": "qwen3.5:2b",
        "vision_model": "qwen2.5vl:7b",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
        "default_model": "llama-3.3-70b-versatile",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
        "default_model": "gpt-4o-mini",
    },
    "together": {
        "base_url": "https://api.together.xyz/v1",
        "models": ["mistralai/Mistral-7B-Instruct-v0.3", "meta-llama/Llama-3.2-3B-Instruct-Turbo"],
        "default_model": "mistralai/Mistral-7B-Instruct-v0.3",
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com/v1",
        "models": ["claude-sonnet-4-20250514", "claude-3-5-haiku-latest"],
        "default_model": "claude-sonnet-4-20250514",
    },
}

class LocalLLM:
    def __init__(self, config):
        self.config = config
        self.backend = config.LLM_BACKEND
        self.available_models = []
        self._openai_client = None
        self._anthropic_client = None
        # Ollama is spoken to over its NATIVE API (see _generate_native).
        self._use_native = False
        self._init_cloud()

    def _init_cloud(self):
        api_key = os.getenv("ACRONOUS_LLM_API_KEY", "")
        provider = os.getenv("ACRONOUS_LLM_PROVIDER", "contabo").lower()
        if provider == "contabo":
            # Acronous Contabo runs locally and does not require an API key.
            try:
                from openai import OpenAI
                info = CLOUD_PROVIDERS["contabo"]
                base_url = os.getenv("ACRONOUS_LLM_API_URL", info["base_url"])
                self._openai_client = OpenAI(
                    api_key=api_key or "acronous-contabo",
                    base_url=base_url,
                    # max_retries=0 is essential: the SDK's default 2 retries
                    # multiplied the generation deadline 3x, so a stalled model
                    # held a request for 225s instead of 75s. Our own
                    # model-fallback loop (fast model, then default) provides
                    # the resilience instead.
                    max_retries=0,
                )
                self.available_models = info["models"]
                env_model = os.getenv("ACRONOUS_LLM_MODEL", "")
                if env_model:
                    # Respect the explicitly-set env model (may or may not be
                    # in the default list; Ollama serves any loaded model).
                    self.config.LLM_MODEL = env_model
                elif self.config.LLM_MODEL not in self.available_models:
                    self.config.LLM_MODEL = info["default_model"]
                self.backend = "openai_compat"
                self._use_native = True
                logger.info(f"[LLM INIT] Contabo initialized (model: {self.config.LLM_MODEL}, native API)")
                return
            except Exception as e:
                logger.error(f"[LLM INIT] Failed to initialize contabo: {type(e).__name__}: {e}")
        if not api_key:
            logger.warning(f"[LLM INIT] No API key found for provider '{provider}'. Set ACRONOUS_LLM_API_KEY environment variable.")
            return
        if provider in ("openai", "groq", "together"):
            try:
                from openai import OpenAI
                info = CLOUD_PROVIDERS.get(provider, CLOUD_PROVIDERS["openai"])
                base_url = os.getenv("ACRONOUS_LLM_API_URL", info["base_url"])
                self._openai_client = OpenAI(
                    api_key=api_key,
                    base_url=base_url,
                    max_retries=0,
                )
                self.available_models = info["models"]
                if self.config.LLM_MODEL not in self.available_models:
                    self.config.LLM_MODEL = os.getenv("ACRONOUS_LLM_MODEL", info["default_model"])
                self.backend = "openai_compat"
                logger.info(f"[LLM INIT] Cloud {provider} initialized (model: {self.config.LLM_MODEL})")
            except Exception as e:
                logger.error(f"[LLM INIT] Failed to initialize {provider}: {type(e).__name__}: {e}")
        elif provider == "anthropic":
            try:
                import anthropic
                self._anthropic_client = anthropic.Anthropic(api_key=api_key)
                info = CLOUD_PROVIDERS["anthropic"]
                self.available_models = info["models"]
                if self.config.LLM_MODEL not in self.available_models:
                    self.config.LLM_MODEL = os.getenv("ACRONOUS_LLM_MODEL", info["default_model"])
                self.backend = "anthropic"
                logger.info(f"[LLM INIT] Cloud anthropic initialized (model: {self.config.LLM_MODEL})")
            except Exception as e:
                logger.error(f"[LLM INIT] Failed to initialize anthropic: {type(e).__name__}: {e}")

    def is_old_model(self):
        return False

    def list_models(self):
        return self.available_models

    def model_for_task(self, task="chat"):
        """Pick the smartest Contabo-served model for a task.

        chat/code/fast/vision route to Qwen variants on the Contabo VPS.
        Falls back to the configured default when env overrides are set.
        """
        import os as _os
        task = (task or "chat").lower()
        if task in ("code", "coder", "programming"):
            return _os.getenv("ACRONOUS_LLM_CODE_MODEL",
                              getattr(self.config, "LLM_CODE_MODEL", "qwen2.5-coder:7b"))
        if task in ("fast", "simple", "greeting", "classify"):
            return _os.getenv("ACRONOUS_LLM_FAST_MODEL",
                              getattr(self.config, "LLM_FAST_MODEL", "qwen2.5:3b"))
        if task in ("vision", "image", "vl"):
            return _os.getenv("ACRONOUS_VISION_MODEL", "qwen2.5vl:7b")
        return _os.getenv("ACRONOUS_LLM_CHAT_MODEL",
                          getattr(self.config, "LLM_CHAT_MODEL", "qwen2.5:3b"))

    def generate(self, prompt, system_prompt=None, stream=False, max_tokens=None, model=None):
        if system_prompt is None:
            system_prompt = SYSTEM_PROMPT
        if max_tokens is None:
            max_tokens = self.config.MAX_TOKENS
        if self.backend == "openai_compat" and self._openai_client:
            return self._generate_openai(prompt, system_prompt, stream, max_tokens, model=model)
        if self.backend == "anthropic" and self._anthropic_client:
            return self._generate_anthropic(prompt, system_prompt, max_tokens)
        logger.warning("No cloud AI backend is available.")
        return ""

    def generate_stream(self, prompt, system_prompt=None, max_tokens=None):
        if system_prompt is None:
            system_prompt = SYSTEM_PROMPT
        if max_tokens is None:
            max_tokens = self.config.MAX_TOKENS
        if self.backend == "openai_compat" and self._openai_client:
            yield from self._stream_openai(prompt, system_prompt, max_tokens, model=model)
        elif self.backend == "anthropic" and self._anthropic_client:
            yield from self._stream_anthropic(prompt, system_prompt, max_tokens)
        else:
            yield self.generate(prompt, system_prompt, stream=False, max_tokens=max_tokens)

    # ── shared sampling / deadline policy ────────────────────────────────
    def _sampling(self, max_tokens, ctx=None):
        c = self.config
        ctx_size = int(getattr(c, "LLM_CONTEXT_SIZE", 2048) or 2048)
        if ctx:
            ctx_size = min(ctx_size, int(ctx))
        # Cap the budget so a runaway loop cannot occupy the CPU for an hour.
        return {
            "num_ctx": ctx_size,
            "num_predict": max(1, int(max_tokens or 512)),
            "temperature": getattr(c, "TEMPERATURE", 0.7),
            "top_p": getattr(c, "LLM_TOP_P", 0.9),
            "repeat_penalty": getattr(c, "LLM_REPEAT_PENALTY", 1.2),
            "repeat_last_n": getattr(c, "LLM_REPEAT_LAST_N", 64),
        }

    def _trim(self, prompt, system_prompt, ctx_size):
        """Keep system + user inside the context window.

        The static system prompt is never truncated (that would break the
        KV-cache prefix); only the user payload shrinks.
        """
        budget = max(500, ctx_size * 3 - len(system_prompt))
        if len(prompt) <= budget:
            return prompt
        head = prompt[: budget // 3]
        tail = prompt[-(budget - len(head) - 40):]
        return f"{head}\n[...middle omitted for length...]\n{tail}"

    def _deadline(self):
        return float(getattr(self.config, "LLM_DEADLINE_S", 75) or 75)

    def _first_token_deadline(self):
        return float(getattr(self.config, "LLM_DEADLINE_FIRST_TOKEN_S", 30) or 30)

    def _models_for(self, model):
        models = [model] if model else [self.config.LLM_MODEL]
        fast = os.getenv("ACRONOUS_LLM_FAST_MODEL", "") or getattr(self.config, "LLM_FAST_MODEL", "")
        if fast and fast not in models:
            models.append(fast)
        fallback = os.getenv("ACRONOUS_LLM_MODEL", "") or getattr(self.config, "LLM_MODEL", "")
        if fallback and fallback not in models:
            models.append(fallback)
        return models

    def _generate_openai(self, prompt, system_prompt, stream=False, max_tokens=8192, model=None):
        """Deadline-bounded generation with one cheap-model fallback.

        Against Ollama we deliberately use the NATIVE /api/chat endpoint, not
        the OpenAI-compatible one: qwen3.5 always emits a reasoning block on
        the compat route and `think:false` is ignored there, so every response
        came back with empty content. The native route honours `think:false`,
        which is what makes non-streaming answers work at all.

        Never returns "" unless every attempt failed — callers treat "" as a
        zero-response, which is what the user sees as "nothing happened".
        """
        if self._use_native:
            return self._generate_native(prompt, system_prompt, max_tokens, model)
        ctx_size = int(getattr(self.config, "LLM_CONTEXT_SIZE", 2048) or 2048)
        options = self._sampling(max_tokens, ctx_size)
        cut = self._trim(prompt, system_prompt, ctx_size)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": cut},
        ]
        last = None
        for m in self._models_for(model):
            started = time.time()
            try:
                resp = self._openai_client.chat.completions.create(
                    model=m,
                    messages=messages,
                    temperature=options["temperature"],
                    max_tokens=options["num_predict"],
                    top_p=options["top_p"],
                    extra_body={"options": options},
                    stream=False,
                    timeout=self._deadline(),
                )
                out = (resp.choices[0].message.content or "").strip()
                if out:
                    logger.info("[LLM] %s answered %d chars in %.1fs",
                                m, len(out), time.time() - started)
                    return out
                last = RuntimeError("empty completion")
            except Exception as e:
                last = e
                logger.warning("[LLM] model %s failed (%s: %s) after %.1fs",
                               m, type(e).__name__, e, time.time() - started)
                continue
        logger.error("[OpenAI API Error] %s: %s", type(last).__name__ if last else "Unknown", last)
        if last:
            raise last
        raise RuntimeError("LLM failed")

    def _generate_native(self, prompt, system_prompt, max_tokens=8192, model=None):
        """Buffered generation over Ollama's native API (non-streaming shape).

        Accumulates the streamed deltas internally, exactly like the worker's
        callOllama does — sending stream=false to Ollama can produce zero
        bytes over a proxy, which is what caused empty replies.
        """
        import httpx
        ctx_size = int(getattr(self.config, "LLM_CONTEXT_SIZE", 2048) or 2048)
        options = self._sampling(max_tokens, ctx_size)
        cut = self._trim(prompt, system_prompt, ctx_size)
        base = str(getattr(self.config, "LLM_API_URL", "") or self._chat_base()).rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": cut},
        ]
        last = None
        for m in self._models_for(model):
            started = time.time()
            try:
                timeout = httpx.Timeout(self._deadline(), connect=8.0, read=self._deadline(),
                                        write=10.0, pool=8.0)
                with httpx.Client(timeout=timeout) as client:
                    with client.stream("POST", f"{base}/api/chat", json={
                        "model": m,
                        "messages": messages,
                        "stream": True,
                        "keep_alive": "24h",
                        "think": False,
                        "options": options,
                    }) as resp:
                        resp.raise_for_status()
                        parts = []
                        for line in resp.iter_lines():
                            if not line:
                                continue
                            try:
                                data = json.loads(line)
                            except Exception:
                                continue
                            piece = (data.get("message") or {}).get("content") or ""
                            if piece:
                                parts.append(piece)
                            if data.get("done"):
                                break
                out = "".join(parts).strip()
                if out:
                    logger.info("[LLM] %s answered %d chars in %.1fs",
                                m, len(out), time.time() - started)
                    return out
                last = RuntimeError("empty completion")
            except Exception as e:
                last = e
                logger.warning("[LLM] native model %s failed (%s: %s) after %.1fs",
                               m, type(e).__name__, e, time.time() - started)
                continue
        logger.error("[Native API Error] %s: %s", type(last).__name__ if last else "Unknown", last)
        if last:
            raise last
        raise RuntimeError("LLM failed")

    def _stream_openai(self, prompt, system_prompt, max_tokens=8192, model=None):
        """True token streaming (stream=True) with a first-token watchdog.

        Yields text deltas as Ollama produces them, so the UI paints
        progressively instead of waiting for the whole answer.
        """
        import httpx
        ctx_size = int(getattr(self.config, "LLM_CONTEXT_SIZE", 2048) or 2048)
        options = self._sampling(max_tokens, ctx_size)
        cut = self._trim(prompt, system_prompt, ctx_size)
        base = str(getattr(self.config, "LLM_API_URL", "") or self._chat_base()).rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        target = model or self.config.LLM_MODEL
        payload = {
            "model": target,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": cut},
            ],
            "stream": True,
            "keep_alive": "24h",
            "think": False,
            "options": options,
        }
        timeout = httpx.Timeout(self._deadline(), connect=8.0, read=self._deadline(),
                                write=10.0, pool=8.0)
        with httpx.Client(timeout=timeout) as client:
            with client.stream("POST", f"{base}/api/chat", json=payload) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except Exception:
                        continue
                    piece = (data.get("message") or {}).get("content") or ""
                    if piece:
                        yield piece
                    if data.get("done"):
                        break

    def _chat_base(self):
        info = CLOUD_PROVIDERS["contabo"]
        return os.getenv("ACRONOUS_LLM_API_URL", info["base_url"])

    def _generate_anthropic(self, prompt, system_prompt, max_tokens=8192):
        try:
            if len(system_prompt) + len(prompt) > 8000:
                max_user = max(0, 7000 - len(system_prompt))
                if len(prompt) > max_user:
                    prompt = "[Earlier context truncated]\n" + prompt[-max_user:]
            resp = self._anthropic_client.messages.create(
                model=self.config.LLM_MODEL,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.config.TEMPERATURE,
                max_tokens=max_tokens,
            )
            return "".join(block.text for block in resp.content if block.type == "text")
        except Exception as e:
            logger.error(f"[Anthropic API Error] {type(e).__name__}: {e}")
            raise

    def _stream_anthropic(self, prompt, system_prompt, max_tokens=8192):
        try:
            if len(system_prompt) + len(prompt) > 8000:
                max_user = max(0, 7000 - len(system_prompt))
                if len(prompt) > max_user:
                    prompt = "[Earlier context truncated]\n" + prompt[-max_user:]
            with self._anthropic_client.messages.stream(
                model=self.config.LLM_MODEL,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.config.TEMPERATURE,
                max_tokens=max_tokens,
            ) as stream:
                for text in stream.text_stream:
                    yield text
        except Exception as e:
            logger.error(f"[Anthropic Stream Error] {type(e).__name__}: {e}")
            raise

    def embed_text(self, text):
        return None
