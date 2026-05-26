---
title: Acronous AI
emoji: 🤖
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
app_file: server.py
sleepTime: 0
---

# Acronous AI

Advanced AI assistant with LLM, image generation, vision, web search, and memory.

## Environment Variables

Set these in Space Settings → Variables & Secrets:

- `ACRONOUS_LLM_BACKEND`: `auto` (uses transformers locally)
- `ACRONOUS_LLM_MODEL`: `TinyLlama/TinyLlama-1.1B-Chat-v1.0`
- `ACRONOUS_EMBED_MODEL`: `all-MiniLM-L6-v2`
- `ACRONOUS_DIFFUSERS_MODEL`: `Lykon/dreamshaper-8`
- `ACRONOUS_DEVICE`: `cpu`
- `ACRONOUS_ENABLE_WEB`: `true`
- `ACRONOUS_ENABLE_VISION`: `true`
