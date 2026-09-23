# Acronous AI

Advanced AI assistant with LLM, image generation, vision, web search, and memory.

## Architecture

| Layer       | Provider                  | Purpose                       |
|-------------|---------------------------|-------------------------------|
| **LLM**     | Contabo Ollama            | Chat, reasoning, streaming    |
| **Image**   | Python Image Service      | Text-to-image generation      |
| **Vision**  | Contabo Ollama (LLaVA)    | Image analysis                |
| **Search**  | DuckDuckGo                | Web search                    |
| **Memory**  | SQLite                    | Conversation history          |

## Environment Variables

| Variable                   | Value                  |
|----------------------------|------------------------|
| `OLLAMA_BASE_URL`          | Contabo Ollama URL     |
| `EDITOR_SERVICE_URL`       | Contabo VPS image-service URL |
| `API_BASE_URL`             | *(your server URL)*    |

## Frontend Connection

The Flutter app connects to the server URL set via `API_BASE_URL`. By default it probes `localhost:8000`.
