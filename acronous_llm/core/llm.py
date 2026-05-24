import torch
import json
import os

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
        api_key = os.getenv("ACRONOUS_LLM_API_KEY", "")
        provider = os.getenv("ACRONOUS_LLM_PROVIDER", "openai").lower()
        if not api_key:
            return
        if provider in ("openai", "groq", "together"):
            try:
                from openai import OpenAI
                info = CLOUD_PROVIDERS.get(provider, CLOUD_PROVIDERS["openai"])
                self._openai_client = OpenAI(
                    api_key=api_key,
                    base_url=os.getenv("ACRONOUS_LLM_API_URL", info["base_url"]),
                )
                self.available_models = info["models"]
                if self.config.LLM_MODEL not in self.available_models:
                    self.config.LLM_MODEL = os.getenv("ACRONOUS_LLM_MODEL", info["default_model"])
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
                    self.config.LLM_MODEL = os.getenv("ACRONOUS_LLM_MODEL", info["default_model"])
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
                model_name, torch_dtype=torch.float32, device_map=self.config.DEVICE, local_files_only=True
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
            system_prompt = "You are Acronous AI, a helpful AI assistant. Respond naturally and conversationally."

        if self.backend == "openai_compat" and self._openai_client:
            return self._generate_openai(prompt, system_prompt, stream)
        if self.backend == "anthropic" and self._anthropic_client:
            return self._generate_anthropic(prompt, system_prompt)
        if self.backend == "ollama" and self.ollama_session:
            return self._generate_ollama(prompt, system_prompt, stream)
        if self._ensure_transformers():
            return self._generate_transformers(prompt, system_prompt)
        raise RuntimeError("No language model backend available")

    def generate_stream(self, prompt, system_prompt=None):
        if system_prompt is None:
            system_prompt = "You are Acronous AI, a helpful AI assistant."

        if self.backend == "openai_compat" and self._openai_client:
            yield from self._stream_openai(prompt, system_prompt)
        elif self.backend == "anthropic" and self._anthropic_client:
            yield from self._stream_anthropic(prompt, system_prompt)
        elif self.backend == "ollama" and self.ollama_session:
            yield from self._stream_ollama(prompt, system_prompt)
        else:
            yield self.generate(prompt, system_prompt, stream=False)

    def _generate_openai(self, prompt, system_prompt, stream=False):
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

    def _stream_openai(self, prompt, system_prompt):
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

    def _generate_anthropic(self, prompt, system_prompt):
        resp = self._anthropic_client.messages.create(
            model=self.config.LLM_MODEL,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            temperature=self.config.TEMPERATURE,
            max_tokens=self.config.MAX_TOKENS,
        )
        return "".join(block.text for block in resp.content if block.type == "text")

    def _stream_anthropic(self, prompt, system_prompt):
        with self._anthropic_client.messages.stream(
            model=self.config.LLM_MODEL,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            temperature=self.config.TEMPERATURE,
            max_tokens=self.config.MAX_TOKENS,
        ) as stream:
            for text in stream.text_stream:
                yield text

    def _generate_ollama(self, prompt, system_prompt, stream=False):
        full_prompt = f"{system_prompt}\n\n{prompt}\nAssistant:"
        payload = {
            "model": self.config.LLM_MODEL,
            "prompt": full_prompt,
            "temperature": self.config.TEMPERATURE,
            "max_tokens": self.config.MAX_TOKENS,
            "stream": False
        }
        resp = self.ollama_session.post(
            f"{self.config.OLLAMA_URL}/api/generate", json=payload
        )
        if resp.status_code != 200:
            raise RuntimeError("Failed to generate response.")
        data = resp.json()
        return data.get("response", "")

    def _stream_ollama(self, prompt, system_prompt):
        full_prompt = f"{system_prompt}\n\n{prompt}\nAssistant:"
        payload = {
            "model": self.config.LLM_MODEL,
            "prompt": full_prompt,
            "temperature": self.config.TEMPERATURE,
            "max_tokens": self.config.MAX_TOKENS,
            "stream": True
        }
        with self.ollama_session.post(
            f"{self.config.OLLAMA_URL}/api/generate", json=payload, stream=True
        ) as resp:
            if resp.status_code != 200:
                raise RuntimeError("Failed to generate response.")
            for line in resp.iter_lines():
                if line:
                    try:
                        data = json.loads(line.decode())
                        chunk = data.get("response", "")
                        if chunk:
                            yield chunk
                    except json.JSONDecodeError:
                        pass

    def _generate_transformers(self, prompt, system_prompt):
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
