import torch
import json
import re
import os
import random

CLOUD_PROVIDERS = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
        "default_model": "gpt-4o-mini",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
        "default_model": "llama-3.1-8b-instant",
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
        self._model = None
        self._tokenizer = None
        self._model_loaded = False
        self.ollama_session = None
        self.available_models = []
        self._openai_client = None
        self._anthropic_client = None
        self._check_ollama()
        self._init_cloud()

    def _init_cloud(self):
        api_key = os.getenv("APEX_LLM_API_KEY", "")
        provider = os.getenv("APEX_LLM_PROVIDER", "openai").lower()
        if not api_key:
            return
        if provider in ("openai", "groq", "together"):
            try:
                from openai import OpenAI
                info = CLOUD_PROVIDERS.get(provider, CLOUD_PROVIDERS["openai"])
                self._openai_client = OpenAI(
                    api_key=api_key,
                    base_url=os.getenv("APEX_LLM_API_URL", info["base_url"]),
                )
                self.available_models = info["models"]
                if self.config.LLM_MODEL not in self.available_models:
                    self.config.LLM_MODEL = os.getenv("APEX_LLM_MODEL", info["default_model"])
                self.backend = "openai_compat"
            except Exception:
                pass
        elif provider == "anthropic":
            try:
                import anthropic
                self._anthropic_client = anthropic.Anthropic(api_key=api_key)
                info = CLOUD_PROVIDERS["anthropic"]
                self.available_models = info["models"]
                if self.config.LLM_MODEL not in self.available_models:
                    self.config.LLM_MODEL = os.getenv("APEX_LLM_MODEL", info["default_model"])
                self.backend = "anthropic"
            except Exception:
                pass

    def _check_ollama(self):
        try:
            import requests
            resp = requests.get(f"{self.config.OLLAMA_URL}/api/tags", timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                self.available_models = [m["name"] for m in data.get("models", [])]
                self.ollama_session = requests.Session()
                self.backend = "ollama"
                if self.available_models:
                    if self.config.LLM_MODEL not in self.available_models:
                        self.config.LLM_MODEL = self.available_models[0]
        except Exception:
            pass

    def list_models(self):
        return self.available_models

    def _ensure_transformers(self):
        if self._model_loaded:
            return self._model is not None
        self._model_loaded = True
        if not self._model_is_cached():
            return False
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
            model_name = self._get_transformers_model()
            self._tokenizer = AutoTokenizer.from_pretrained(model_name, local_files_only=True)
            self._model = AutoModelForCausalLM.from_pretrained(
                model_name, torch_dtype=torch.float32, device_map="cpu", local_files_only=True
            )
            return True
        except Exception:
            return False

    def _model_is_cached(self):
        try:
            from huggingface_hub import scan_cache_dir
            model_name = self._get_transformers_model()
            cache_info = scan_cache_dir()
            for repo in cache_info.repos:
                if model_name.replace("/", "--") in repo.repo_id or model_name == repo.repo_id:
                    return True
            return False
        except Exception:
            hf_cache = os.environ.get("HF_HOME", os.path.expanduser("~/.cache/huggingface"))
            model_dir = os.path.join(hf_cache, "hub", f"models--{self._get_transformers_model().replace('/', '--')}")
            snapshots = os.path.join(model_dir, "snapshots")
            return os.path.exists(snapshots) and len(os.listdir(snapshots)) > 0 if os.path.exists(snapshots) else False

    def _get_transformers_model(self):
        mapping = {
            "llama3.2:1b": "TinyLlama/TinyLlama-1.1B-Chat-v1.0",
            "llama3.2:3b": "microsoft/Phi-3-mini-4k-instruct",
            "phi3": "microsoft/Phi-3-mini-4k-instruct",
            "mistral": "Mistral-7B-Instruct-v0.2"
        }
        return mapping.get(self.config.LLM_MODEL, "TinyLlama/TinyLlama-1.1B-Chat-v1.0")

    def generate(self, prompt, system_prompt=None, stream=False):
        if system_prompt is None:
            system_prompt = "You are Apex AI, a helpful AI assistant. Respond naturally and conversationally."

        if self.backend == "openai_compat" and self._openai_client:
            return self._generate_openai(prompt, system_prompt, stream)
        if self.backend == "anthropic" and self._anthropic_client:
            return self._generate_anthropic(prompt, system_prompt)
        if self.backend == "ollama" and self.ollama_session:
            return self._generate_ollama(prompt, system_prompt, stream)
        if self._ensure_transformers():
            return self._generate_transformers(prompt, system_prompt)
        return self._rule_based_response(prompt)

    def generate_stream(self, prompt, system_prompt=None):
        if system_prompt is None:
            system_prompt = "You are Apex AI, a helpful AI assistant."

        if self.backend == "openai_compat" and self._openai_client:
            yield from self._stream_openai(prompt, system_prompt)
        elif self.backend == "anthropic" and self._anthropic_client:
            yield from self._stream_anthropic(prompt, system_prompt)
        elif self.backend == "ollama" and self.ollama_session:
            yield from self._stream_ollama(prompt, system_prompt)
        else:
            full = self.generate(prompt, system_prompt, stream=False)
            chunk_size = 30
            for i in range(0, len(full), chunk_size):
                yield full[i:i + chunk_size]

    def _generate_openai(self, prompt, system_prompt, stream=False):
        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]
            resp = self._openai_client.chat.completions.create(
                model=self.config.LLM_MODEL,
                messages=messages,
                temperature=self.config.TEMPERATURE,
                max_tokens=self.config.MAX_TOKENS,
                stream=False,
            )
            return resp.choices[0].message.content or ""
        except Exception:
            return self._rule_based_response(prompt)

    def _stream_openai(self, prompt, system_prompt):
        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]
            stream = self._openai_client.chat.completions.create(
                model=self.config.LLM_MODEL,
                messages=messages,
                temperature=self.config.TEMPERATURE,
                max_tokens=self.config.MAX_TOKENS,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    yield delta.content
        except Exception:
            yield self._rule_based_response(prompt)

    def _generate_anthropic(self, prompt, system_prompt):
        try:
            resp = self._anthropic_client.messages.create(
                model=self.config.LLM_MODEL,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.config.TEMPERATURE,
                max_tokens=self.config.MAX_TOKENS,
            )
            return "".join(block.text for block in resp.content if block.type == "text")
        except Exception:
            return self._rule_based_response(prompt)

    def _stream_anthropic(self, prompt, system_prompt):
        try:
            with self._anthropic_client.messages.stream(
                model=self.config.LLM_MODEL,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.config.TEMPERATURE,
                max_tokens=self.config.MAX_TOKENS,
            ) as stream:
                for text in stream.text_stream:
                    yield text
        except Exception:
            yield self._rule_based_response(prompt)

    def _generate_ollama(self, prompt, system_prompt, stream=False):
        try:
            full_prompt = f"{system_prompt}\n\n{prompt}\nAssistant:"
            payload = {
                "model": self.config.LLM_MODEL,
                "prompt": full_prompt,
                "temperature": self.config.TEMPERATURE,
                "max_tokens": self.config.MAX_TOKENS,
                "stream": False
            }
            resp = self.ollama_session.post(
                f"{self.config.OLLAMA_URL}/api/generate", json=payload, timeout=120
            )
            if resp.status_code != 200:
                return self._rule_based_response(prompt)
            data = resp.json()
            return data.get("response", "")
        except Exception:
            return self._rule_based_response(prompt)

    def _stream_ollama(self, prompt, system_prompt):
        try:
            full_prompt = f"{system_prompt}\n\n{prompt}\nAssistant:"
            payload = {
                "model": self.config.LLM_MODEL,
                "prompt": full_prompt,
                "temperature": self.config.TEMPERATURE,
                "max_tokens": self.config.MAX_TOKENS,
                "stream": True
            }
            with self.ollama_session.post(
                f"{self.config.OLLAMA_URL}/api/generate", json=payload, stream=True, timeout=120
            ) as resp:
                if resp.status_code != 200:
                    yield self._rule_based_response(prompt)
                    return
                for line in resp.iter_lines():
                    if line:
                        try:
                            data = json.loads(line.decode())
                            chunk = data.get("response", "")
                            if chunk:
                                yield chunk
                        except Exception:
                            pass
        except Exception:
            yield self._rule_based_response(prompt)

    def _generate_transformers(self, prompt, system_prompt):
        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ]
            inputs = self._tokenizer.apply_chat_template(
                messages, add_generation_prompt=True, return_tensors="pt"
            )
            with torch.no_grad():
                outputs = self._model.generate(
                    inputs, max_new_tokens=self.config.MAX_TOKENS,
                    temperature=self.config.TEMPERATURE, do_sample=True,
                    pad_token_id=self._tokenizer.eos_token_id
                )
            response = self._tokenizer.decode(outputs[0][inputs.shape[1]:], skip_special_tokens=True)
            return response.strip()
        except Exception:
            return self._rule_based_response(prompt)

    def _rule_based_response(self, prompt):
        prompt_lower = prompt.lower().strip()
        greetings = {"hello", "hi", "hey", "greetings", "sup", "howdy"}
        farewells = {"bye", "goodbye", "see you", "cya"}
        thanks = {"thank", "thanks", "appreciate"}
        identity = {"who are you", "what are you", "tell me about yourself"}
        capabilities = {"what can you do", "help", "capabilities", "features"}

        if any(w in prompt_lower for w in identity):
            return "I'm Apex AI, a helpful AI assistant that runs on a cloud or local backend. I can chat, search the web, analyze images, generate code, and learn from our conversations."
        if any(w in prompt_lower for w in capabilities):
            return "I can help with natural conversation, web searching, image analysis, code generation, translations, and answering questions. I learn from feedback and remember our conversations."
        if any(w in prompt_lower for w in thanks):
            return "You're welcome! Happy to help. Let me know if you need anything else."
        if any(w in prompt_lower for w in farewells):
            return "Goodbye! Feel free to come back anytime you need assistance."
        if prompt_lower.split() and prompt_lower.split()[0] in {"hello", "hi", "hey"}:
            return "Hi there! How can I help you today?"
        return (
            "I understand you're asking about something. To give you the best answer, "
            "I need a working backend connection. Please check the server status "
            "or configure an API key in the settings."
        )

    def embed_text(self, text):
        if self._model is not None:
            try:
                inputs = self._tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
                with torch.no_grad():
                    outputs = self._model.get_input_embeddings()(inputs["input_ids"])
                return outputs.mean(dim=1).squeeze()
            except Exception:
                pass
        return torch.zeros(self.config.EMBED_DIM)
