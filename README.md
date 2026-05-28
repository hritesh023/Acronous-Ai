# Acronous AI

Advanced AI assistant with LLM, image generation, vision, web search, and memory.

## Architecture

| Layer       | Provider           | Purpose                       |
|-------------|--------------------|-------------------------------|
| **LLM**     | Groq API           | Chat, reasoning, streaming    |
| **Image**   | HF Inference API   | Image generation / editing    |
| **Vision**  | HF Inference API   | Image analysis                |
| **Search**  | DuckDuckGo         | Web search                    |
| **Memory**  | SQLite             | Conversation history          |

## Environment Variables

| Variable                   | Value                  |
|----------------------------|------------------------|
| `ACRONOUS_LLM_PROVIDER`    | `groq`                 |
| `ACRONOUS_LLM_MODEL`       | `llama-3.1-8b-instant` |
| `ACRONOUS_EMBED_MODEL`     | `all-MiniLM-L6-v2`     |
| `ACRONOUS_IMAGE_PROVIDER`  | `huggingface`          |
| `ACRONOUS_HF_IMAGE_MODEL`  | `Lykon/dreamshaper-8`  |
| `ACRONOUS_SEARCH`          | `duckduckgo`           |
| `ACRONOUS_ENABLE_WEB`      | `true`                 |
| `ACRONOUS_ENABLE_VISION`   | `true`                 |
| `API_BASE_URL`             | *(your server URL)*    |
|                            |                        |
| **Secret**                 | **Value**              |
| `ACRONOUS_LLM_API_KEY`     | `gsk_...` (Groq key)   |
| `HF_API_TOKEN`             | `hf_...` (HF token)    |

## Frontend Connection

The Flutter app connects to the server URL set via `API_BASE_URL`. By default it probes `localhost:8000`.
