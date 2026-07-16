# Acronous AI

Advanced AI assistant with LLM, image generation, vision, web search, and memory.

## Architecture

| Layer       | Provider              | Purpose                       |
|-------------|-----------------------|-------------------------------|
| **LLM**     | OpenRouter            | Chat, reasoning, streaming    |
| **Image**   | Python Image Service  | Text-to-image generation      |
| **Vision**  | OpenRouter            | Image analysis                |
| **Search**  | DuckDuckGo            | Web search                    |
| **Memory**  | SQLite                | Conversation history          |

## Environment Variables

| Variable                   | Value                  |
|----------------------------|------------------------|
| `OPENROUTER_API_KEY`       | `sk-or-v1-...`         |
| `EDITOR_SERVICE_URL`       | Oracle Cloud image-service URL |
| `API_BASE_URL`             | *(your server URL)*    |

## Frontend Connection

The Flutter app connects to the server URL set via `API_BASE_URL`. By default it probes `localhost:8000`.
