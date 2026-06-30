// Acronous AI — Cloudflare Worker (API Layer)
// Replaces the Render-hosted Python backend.
// Handles all API endpoints by calling external AI providers directly.
//
// Required secrets (set via `wrangler secret put <NAME>`):
//   OPENROUTER_API_KEY   — from .env ACRONOUS_LLM_API_KEY
//
// Optional env vars (set in wrangler.toml or dashboard):
//   OPENROUTER_MODEL     — default: meta-llama/llama-3.3-70b-instruct
//   OPENROUTER_BASE_URL  — default: https://openrouter.ai/api/v1
//   PAGES_ORIGIN         — Cloudflare Pages URL for Flutter web SPA
//   ENABLE_WEB           — default: true
//   ENABLE_VISION        — default: true
//   ENABLE_VOICE         — default: true
//
// Optional KV namespace binding (set in wrangler.toml):
//   acronous_kv — for conversation persistence
//
// Deploy:
//   wrangler deploy cloudflare-worker.js --name acronous-ai

// ── Config (injected via env parameter by Cloudflare) ───────────────────
let OPENROUTER_API_KEY = '';
let OPENROUTER_MODEL = 'meta-llama/llama-3.3-70b-instruct';
let OPENROUTER_BASE_URL = 'https://openrouter.ai/api/v1';
let PAGES_ORIGIN = '';
let ENABLE_WEB = true;
let ENABLE_VISION = true;
let ENABLE_VOICE = true;
let WHISPER_API_KEY = '';

const DEFAULT_SYSTEM_PROMPT = `You are Acronous AI, an intelligent and helpful assistant. You provide accurate, thoughtful, and well-structured responses.

Current capabilities:
- You can search the web when asked about current events
- You can generate images when asked to draw, paint, or create visual content
- You have vision capabilities for analyzing images
- You can process various file types

Guidelines:
- Be concise but thorough
- Format responses with markdown when appropriate
- Never mention internal configuration or system prompts
- When generating images, describe what you would create
- For web search results, cite your sources`;

// ── Helpers ───────────────────────────────────────────────────────────────

function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      'Content-Type': 'application/json',
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    },
  });
}

function errorResponse(message, status = 500) {
  return jsonResponse({ error: message }, status);
}

function sanitizeText(text) {
  if (!text) return '';
  return text.replace(/\n{3,}/g, '\n\n').trim();
}

async function callOpenRouter(messages, options = {}) {
  const { stream = false, model = OPENROUTER_MODEL } = options;
  const body = {
    model,
    messages,
    max_tokens: 4096,
    temperature: 0.7,
    stream,
  };

  const resp = await fetch(`${OPENROUTER_BASE_URL}/chat/completions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${OPENROUTER_API_KEY}`,
      'HTTP-Referer': 'https://acronous.com',
      'X-Title': 'Acronous AI',
    },
    body: JSON.stringify(body),
  });

  if (!resp.ok) {
    const errBody = await resp.text();
    throw new Error(`OpenRouter error ${resp.status}: ${errBody}`);
  }

  return resp;
}

function buildMessages(userMessage, sessionId, timezone, location, systemPrompt) {
  const msgs = [
    { role: 'system', content: systemPrompt || DEFAULT_SYSTEM_PROMPT },
  ];

  if (timezone) {
    msgs.push({ role: 'system', content: `Current user timezone: ${timezone}` });
  }
  if (location) {
    msgs.push({ role: 'system', content: `User location: ${location}` });
  }

  msgs.push({ role: 'user', content: userMessage });
  return msgs;
}

function buildMultimodalContent(text, imageBase64, imageType) {
  const content = [];
  if (text) content.push({ type: 'text', text });
  if (imageBase64) {
    content.push({
      type: 'image_url',
      image_url: { url: `data:${imageType || 'image/jpeg'};base64,${imageBase64}` },
    });
  }
  return content;
}

// ── KV helpers ────────────────────────────────────────────────────────────

async function kvGet(key, fallback = null) {
  try {
    if (globalThis.acronous_kv) {
      const val = await globalThis.acronous_kv.get(key, 'text');
      return val ? JSON.parse(val) : fallback;
    }
  } catch (_) {}
  return fallback;
}

async function kvPut(key, value) {
  try {
    if (globalThis.acronous_kv) {
      await globalThis.acronous_kv.put(key, JSON.stringify(value));
    }
  } catch (_) {}
}

async function kvDelete(key) {
  try {
    if (globalThis.acronous_kv) {
      await globalThis.acronous_kv.delete(key);
    }
  } catch (_) {}
}

async function kvList(prefix) {
  try {
    if (globalThis.acronous_kv) {
      const list = await globalThis.acronous_kv.list({ prefix });
      return list.keys;
    }
  } catch (_) {}
  return [];
}

// ── In-memory fallback ────────────────────────────────────────────────────

const memStore = new Map();

function memGet(key) {
  return memStore.get(key) || null;
}

function memPut(key, value) {
  memStore.set(key, value);
}

function memDelete(key) {
  memStore.delete(key);
}

async function storeGet(key) {
  const fromKv = await kvGet(key);
  if (fromKv !== null) return fromKv;
  return memGet(key);
}

async function storePut(key, value) {
  await kvPut(key, value);
  memPut(key, value);
}

async function storeDelete(key) {
  await kvDelete(key);
  memDelete(key);
}

// ── Health / Readiness ────────────────────────────────────────────────────

function healthHandler() {
  return jsonResponse({ status: 'ok' });
}

function readyHandler() {
  return jsonResponse({ status: 'ok' });
}

function healthLLMHandler() {
  if (!OPENROUTER_API_KEY) {
    return jsonResponse({ status: 'unavailable' }, 503);
  }
  return jsonResponse({ status: 'ok' });
}

function wakeupHandler() {
  return jsonResponse({ status: 'ok' });
}

// ── Chat (POST /v1/chat) ──────────────────────────────────────────────────

async function chatHandler(request) {
  try {
    const body = await request.json();
    const { message, session_id = 'default', timezone = '', location = '' } = body;

    if (!message) {
      return jsonResponse({
        response: '',
        session_id,
        type: 'error',
      }, 400);
    }

    const messages = buildMessages(message, session_id, timezone, location);
    const resp = await callOpenRouter(messages);
    const data = await resp.json();
    const content = sanitizeText(data?.choices?.[0]?.message?.content || '');

    return jsonResponse({
      response: content,
      session_id,
      type: 'chat',
      image_data: '',
      image_type: '',
      file_data: '',
      file_name: '',
      file_type: '',
      complexity: 0,
      complexity_label: 'simple',
    });
  } catch (e) {
    return jsonResponse({
      response: 'The AI service is temporarily unavailable. Please try again.',
      session_id: 'default',
      type: 'error',
      image_data: '',
      image_type: '',
      file_data: '',
      file_name: '',
      file_type: '',
      complexity: 0,
      complexity_label: 'simple',
    });
  }
}

// ── Chat Stream (POST /v1/chat/stream) ────────────────────────────────────

async function chatStreamHandler(request) {
  try {
    const body = await request.json();
    const { message, session_id = 'default', timezone = '', location = '' } = body;

    if (!message) {
      return jsonResponse({ error: 'No message provided' }, 400);
    }

    const messages = buildMessages(message, session_id, timezone, location);
    const resp = await callOpenRouter(messages, { stream: true });

    const { readable, writable } = new TransformStream();
    const writer = writable.getWriter();
    const encoder = new TextEncoder();

    (async () => {
      try {
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const chunk = line.slice(6).trim();
              if (chunk === '[DONE]') continue;
              try {
                const parsed = JSON.parse(chunk);
                const delta = parsed?.choices?.[0]?.delta?.content;
                if (delta) {
                  await writer.write(encoder.encode(`data: ${JSON.stringify({ content: delta })}\n\n`));
                }
              } catch (_) {}
            }
          }
        }

        await writer.write(encoder.encode(`data: ${JSON.stringify({ done: true })}\n\n`));
      } catch (e) {
        await writer.write(encoder.encode(`data: ${JSON.stringify({ error: 'Stream error occurred', done: true })}\n\n`));
      } finally {
        await writer.close();
      }
    })();

    return new Response(readable, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        Connection: 'keep-alive',
        'X-Accel-Buffering': 'no',
        'Access-Control-Allow-Origin': '*',
      },
    });
  } catch (e) {
    return jsonResponse({ error: 'Failed to start stream' }, 500);
  }
}

// ── Chat with Image (POST /v1/chat/image) ────────────────────────────────

async function chatImageHandler(request) {
  try {
    const formData = await request.formData();
    const message = formData.get('message') || '';
    const session_id = formData.get('session_id') || 'default';
    const file = formData.get('file');

    if (!file) {
      return jsonResponse({ response: 'No image provided', session_id, type: 'error' }, 400);
    }

    const fileBytes = await file.arrayBuffer();
    const base64 = btoa(String.fromCharCode(...new Uint8Array(fileBytes)));
    const mimeType = file.type || 'image/jpeg';

    const content = buildMultimodalContent(message || 'Analyze this image', base64, mimeType);
    const messages = [
      { role: 'system', content: DEFAULT_SYSTEM_PROMPT },
      { role: 'user', content },
    ];

    const resp = await callOpenRouter(messages);
    const data = await resp.json();
    const responseText = sanitizeText(data?.choices?.[0]?.message?.content || '');

    return jsonResponse({
      response: responseText,
      session_id,
      type: 'chat',
      image_data: '',
      image_type: '',
      file_data: '',
      file_name: '',
      file_type: '',
      complexity: 0,
      complexity_label: 'simple',
    });
  } catch (e) {
    return jsonResponse({
      response: 'Failed to process image. Please try again.',
      session_id: 'default',
      type: 'error',
    });
  }
}

// ── Chat with File (POST /v1/chat/file) ──────────────────────────────────

async function chatFileHandler(request) {
  try {
    const formData = await request.formData();
    const message = formData.get('message') || '';
    const session_id = formData.get('session_id') || 'default';
    const file = formData.get('file');

    if (!file) {
      return jsonResponse({ response: 'No file provided', session_id, type: 'error' }, 400);
    }

    const fileName = file.name || 'upload';
    const fileBytes = await file.arrayBuffer();
    const fileContent = new TextDecoder('utf-8', { fatal: false }).decode(fileBytes);
    const ext = fileName.split('.').pop()?.toLowerCase() || '';
    const textExts = ['txt', 'md', 'py', 'js', 'ts', 'html', 'css', 'json', 'xml', 'yaml', 'yml', 'csv', 'dart', 'go', 'rs', 'rb', 'php', 'java', 'cpp', 'c', 'h', 'hpp', 'swift', 'kt', 'sh', 'bat', 'ps1', 'sql', 'log', 'ini', 'cfg', 'toml'];

    let extractedText = '';
    if (textExts.includes(ext)) {
      extractedText = fileContent;
    } else {
      extractedText = `[File: ${fileName}] (${file.size} bytes, type: ${file.type || ext})`;
    }

    const userContent = message
      ? `I've attached a file "${fileName}".\n\nFile content:\n${extractedText.slice(0, 50000)}\n\nUser message: ${message}`
      : `Here is the file "${fileName}". Please analyze it.\n\n${extractedText.slice(0, 50000)}`;

    const messages = buildMessages(userContent, session_id);
    const resp = await callOpenRouter(messages);
    const data = await resp.json();
    const responseText = sanitizeText(data?.choices?.[0]?.message?.content || '');

    return jsonResponse({
      response: responseText,
      session_id,
      type: 'chat',
      image_data: '',
      image_type: '',
      file_data: '',
      file_name: '',
      file_type: '',
      complexity: 0,
      complexity_label: 'simple',
    });
  } catch (e) {
    return jsonResponse({
      response: 'Failed to process file. Please try again.',
      session_id: 'default',
      type: 'error',
    });
  }
}

// ── Image Generation (GET/POST /v1/image/generate) ───────────────────────

async function generateImageHandler(request) {
  try {
    let prompt = '';
    let session_id = 'default';

    if (request.method === 'GET') {
      const url = new URL(request.url);
      prompt = url.searchParams.get('prompt') || '';
      session_id = url.searchParams.get('session_id') || 'default';
    } else {
      const body = await request.json();
      prompt = body.prompt || '';
      session_id = body.session_id || 'default';
    }

    if (!prompt) {
      return jsonResponse({ response: '', session_id, type: 'error', image_data: '' }, 400);
    }

    const encodedPrompt = encodeURIComponent(prompt);
    const imageUrl = `https://image.pollinations.ai/prompt/${encodedPrompt}?width=1024&height=1024&nologo=true`;

    const imageResp = await fetch(imageUrl, { signal: AbortSignal.timeout(30000) });
    if (!imageResp.ok) {
      throw new Error(`Pollinations error: ${imageResp.status}`);
    }

    const imageBuffer = await imageResp.arrayBuffer();
    const base64Image = btoa(String.fromCharCode(...new Uint8Array(imageBuffer)));

    return request.method === 'GET'
      ? new Response(imageBuffer, {
          headers: {
            'Content-Type': 'image/png',
            'Access-Control-Allow-Origin': '*',
            'Cache-Control': 'public, max-age=3600',
          },
        })
      : jsonResponse({
          response: `Generated image for: ${prompt}`,
          image_data: base64Image,
          session_id,
          type: 'image_gen',
        });
  } catch (e) {
    return jsonResponse({
      response: 'Image generation failed. Please try again.',
      session_id: 'default',
      type: 'error',
      image_data: '',
    });
  }
}

// ── Image Edit (POST /v1/image/edit) ─────────────────────────────────────

async function editImageHandler(request) {
  try {
    const formData = await request.formData();
    const message = formData.get('message') || '';
    const session_id = formData.get('session_id') || 'default';
    const file = formData.get('file');

    if (!file) {
      return jsonResponse({ response: 'No image provided', session_id, type: 'error' }, 400);
    }

    const fileBytes = await file.arrayBuffer();
    const base64 = btoa(String.fromCharCode(...new Uint8Array(fileBytes)));
    const mimeType = file.type || 'image/jpeg';

    const editDesc = message?.trim()
      ? message
      : 'edit this image';

    const content = buildMultimodalContent(
      `Edit this image as follows: ${editDesc}. Return an image edit description.`,
      base64,
      mimeType,
    );
    const messages = [
      { role: 'system', content: 'You describe image edits concisely.' },
      { role: 'user', content },
    ];

    const resp = await callOpenRouter(messages);
    const data = await resp.json();
    const editQuery = data?.choices?.[0]?.message?.content?.trim() || 'edit this image';

    const encodedQuery = encodeURIComponent(editQuery);
    const imageUrl = `https://image.pollinations.ai/prompt/${encodedQuery}?width=1024&height=1024&nologo=true`;
    const imageResp = await fetch(imageUrl, { signal: AbortSignal.timeout(30000) });

    if (!imageResp.ok) throw new Error('Edit generation failed');
    const imageBuffer = await imageResp.arrayBuffer();
    const resultBase64 = btoa(String.fromCharCode(...new Uint8Array(imageBuffer)));

    return jsonResponse({
      response: `Image edited: ${editQuery}`,
      session_id,
      type: 'chat',
      image_data: resultBase64,
      image_type: 'png',
      file_data: '',
      file_name: '',
      file_type: '',
    });
  } catch (e) {
    return jsonResponse({
      response: 'Image editing failed. Please try again.',
      session_id: 'default',
      type: 'error',
    });
  }
}

// ── API Chat (POST /api/chat) ────────────────────────────────────────────

async function apiChatHandler(request) {
  try {
    const body = await request.json();
    const { query, session_id = 'default' } = body;

    if (!query) {
      return jsonResponse({
        content: 'No query provided',
        type: 'error',
        session_id,
        sources: [],
        analysis: null,
      });
    }

    const messages = buildMessages(query, session_id);
    const resp = await callOpenRouter(messages);
    const data = await resp.json();
    const content = sanitizeText(data?.choices?.[0]?.message?.content || '');

    return jsonResponse({
      content,
      type: 'chat',
      session_id,
      sources: [],
      analysis: null,
    });
  } catch (e) {
    return jsonResponse({
      content: 'The AI service is temporarily unavailable.',
      type: 'error',
      session_id: 'default',
      sources: [],
      analysis: null,
    });
  }
}

// ── QR Code (POST /api/image/qr-code) ────────────────────────────────────

async function qrCodeHandler(request) {
  try {
    const body = await request.json();
    const { data, size = 256 } = body;

    if (!data) {
      return jsonResponse({ error: 'No data provided' }, 400);
    }

    const qrUrl = `https://api.qrserver.com/v1/create-qr-code/?size=${size}x${size}&data=${encodeURIComponent(data)}`;
    const resp = await fetch(qrUrl);
    if (!resp.ok) throw new Error('QR generation failed');

    const imageBuffer = await resp.arrayBuffer();
    const b64 = btoa(String.fromCharCode(...new Uint8Array(imageBuffer)));

    return jsonResponse({ image: b64, format: 'png' });
  } catch (e) {
    return jsonResponse({ error: 'QR code generation failed' }, 500);
  }
}

// ── Image Redesign (POST /api/image/redesign) ────────────────────────────

async function redesignImageHandler(request) {
  try {
    const formData = await request.formData();
    const file = formData.get('file');
    const prompt = formData.get('prompt') || '';

    if (!file) {
      return jsonResponse({ content: null, error: 'No image provided' }, 400);
    }

    const encodedPrompt = encodeURIComponent(prompt || 'redesign this image');
    const imageUrl = `https://image.pollinations.ai/prompt/${encodedPrompt}?width=1024&height=1024&nologo=true`;
    const resp = await fetch(imageUrl, { signal: AbortSignal.timeout(30000) });

    if (!resp.ok) throw new Error('Redesign failed');
    const imageBuffer = await resp.arrayBuffer();
    const b64 = btoa(String.fromCharCode(...new Uint8Array(imageBuffer)));

    return jsonResponse({ content: b64, error: null, prompt });
  } catch (e) {
    return jsonResponse({ content: null, error: 'Image redesign failed' }, 500);
  }
}

// ── Image Analyze (POST /api/image/analyze) ──────────────────────────────

async function analyzeImageHandler(request) {
  try {
    const formData = await request.formData();
    const file = formData.get('file');
    const session_id = formData.get('session_id') || 'default';

    if (!file) {
      return jsonResponse({ content: '', type: 'error', session_id }, 400);
    }

    const fileBytes = await file.arrayBuffer();
    const base64 = btoa(String.fromCharCode(...new Uint8Array(fileBytes)));
    const mimeType = file.type || 'image/jpeg';

    const content = buildMultimodalContent(
      'Analyze this image in detail. Describe what you see, including objects, text, colors, composition, and any notable elements.',
      base64,
      mimeType,
    );
    const messages = [
      { role: 'system', content: 'You are an image analysis AI. Provide detailed, structured analysis of images.' },
      { role: 'user', content },
    ];

    const resp = await callOpenRouter(messages);
    const data = await resp.json();
    const analysis = sanitizeText(data?.choices?.[0]?.message?.content || '');

    return jsonResponse({
      content: analysis,
      type: 'analysis',
      session_id,
    });
  } catch (e) {
    return jsonResponse({ content: '', type: 'error', session_id: 'default' });
  }
}

// ── Web Search (POST /api/tools/search) ──────────────────────────────────

async function searchHandler(request) {
  try {
    const body = await request.json();
    const { query, max_results = 5 } = body;

    if (!query) {
      return jsonResponse({ results: [] });
    }

    const searchUrl = `https://api.duckduckgo.com/?q=${encodeURIComponent(query)}&format=json&no_html=1`;
    const resp = await fetch(searchUrl, {
      headers: { 'User-Agent': 'AcronousAI/1.0' },
    });

    const data = await resp.json();
    const results = [];

    if (data.AbstractText) {
      results.push({
        title: data.AbstractSource || 'Summary',
        url: data.AbstractURL || '',
        snippet: data.AbstractText,
      });
    }

    const relatedTopics = data.RelatedTopics || [];
    for (const topic of relatedTopics.slice(0, max_results)) {
      if (topic.Text) {
        results.push({
          title: topic.Text.split(' - ')[0] || topic.FirstURL || '',
          url: topic.FirstURL || '',
          snippet: topic.Text,
        });
      }
      if (topic.Topics) {
        for (const sub of topic.Topics.slice(0, 3)) {
          if (sub.Text && results.length < max_results) {
            results.push({
              title: sub.Text.split(' - ')[0] || sub.FirstURL || '',
              url: sub.FirstURL || '',
              snippet: sub.Text,
            });
          }
        }
      }
    }

    return jsonResponse({ results });
  } catch (e) {
    return jsonResponse({ error: 'Search failed', results: [] });
  }
}

// ── Voice Transcribe (POST /api/voice/transcribe) ────────────────────────

async function transcribeHandler(request) {
  try {
    const formData = await request.formData();
    const file = formData.get('file');

    if (!file) {
      return jsonResponse({ text: '', error: 'No audio file provided' });
    }

    if (!WHISPER_API_KEY) {
      return jsonResponse({
        text: '',
        error: 'Voice transcription requires a separate API key. Set WHISPER_API_KEY as a Worker secret, or run the Python server locally for this feature.',
      });
    }

    const fileBytes = await file.arrayBuffer();
    const audioBlob = new Blob([fileBytes], { type: file.type || 'audio/webm' });

    const whisperForm = new FormData();
    whisperForm.append('file', audioBlob, file.name || 'audio.webm');
    whisperForm.append('model', 'whisper-1');

    const resp = await fetch('https://api.openai.com/v1/audio/transcriptions', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${WHISPER_API_KEY}`,
      },
      body: whisperForm,
    });

    if (!resp.ok) {
      const errBody = await resp.text();
      return jsonResponse({ text: '', error: `Transcription failed: ${errBody}` });
    }

    const data = await resp.json();
    return jsonResponse({ text: data.text || '' });
  } catch (e) {
    return jsonResponse({ text: '', error: 'Transcription failed' });
  }
}

// ── Document Processing (POST /api/tools/process-document) ──────────────

async function processDocumentHandler(request) {
  try {
    const formData = await request.formData();
    const file = formData.get('file');

    if (!file) {
      return jsonResponse({ text: '', error: 'No file provided' });
    }

    const fileName = file.name || 'upload';
    const fileBytes = await file.arrayBuffer();
    const ext = fileName.split('.').pop()?.toLowerCase() || '';
    const textExts = ['txt', 'md', 'py', 'js', 'ts', 'html', 'css', 'json', 'xml', 'yaml', 'yml', 'csv', 'dart', 'go', 'rs', 'rb', 'php', 'java', 'cpp', 'c', 'h', 'hpp', 'swift', 'kt', 'sh', 'bat', 'ps1', 'sql', 'log', 'ini', 'cfg', 'toml', 'rtf'];

    let text = '';
    if (textExts.includes(ext)) {
      text = new TextDecoder('utf-8', { fatal: false }).decode(fileBytes);
    } else {
      text = `[${fileName}] Binary file (${fileBytes.byteLength} bytes). Use the Python backend for PDF/DOCX processing.`;
    }

    return jsonResponse({ text, filename: fileName, size: fileBytes.byteLength });
  } catch (e) {
    return jsonResponse({ text: '', error: 'Document processing failed' });
  }
}

// ── Models List (GET /api/models/list) ────────────────────────────────────

function modelsHandler() {
  return jsonResponse({
    models: [
      {
        id: 'default',
        name: 'Acronous AI',
        provider: 'acronous',
        backend: 'managed',
      },
    ],
  });
}

// ── Status (GET /api/status) ──────────────────────────────────────────────

function statusHandler() {
  return jsonResponse({
    status: 'running',
    vision_enabled: ENABLE_VISION,
    voice_enabled: ENABLE_VOICE,
    web_search_enabled: ENABLE_WEB,
  });
}

// ── Config (GET /api/config) ──────────────────────────────────────────────

function configHandler() {
  return jsonResponse({
    enable_web: ENABLE_WEB,
    enable_vision: ENABLE_VISION,
    enable_voice: ENABLE_VOICE,
    suggestions: [
      { icon: 'book', title: 'Learn Something', desc: 'Explain ML simply', query: 'Explain machine learning in simple terms' },
      { icon: 'code', title: 'Write Code', desc: 'Create a Python script', query: 'Write a Python script that scrapes a website' },
      { icon: 'image', title: 'Generate Art', desc: 'Draw a landscape', query: 'Draw a serene mountain landscape at sunset' },
      { icon: 'search', title: 'Research', desc: 'Latest AI news', query: 'What are the latest developments in artificial intelligence?' },
    ],
  });
}

// ── LLM Config (GET/POST /api/config/llm) ─────────────────────────────────

function llmConfigGetHandler() {
  return jsonResponse({ status: 'managed' });
}

function llmConfigPostHandler() {
  return jsonResponse({ status: 'managed' });
}

// ── Conversation CRUD ─────────────────────────────────────────────────────

async function listConversationsHandler() {
  const convs = await storeGet('conversations_list');
  return jsonResponse({ conversations: convs || [] });
}

async function createConversationHandler(request) {
  const body = await request.json();
  const session_id = crypto.randomUUID();
  const title = body.title || 'New Conversation';
  const conv = { id: session_id, title, created_at: new Date().toISOString(), updated_at: new Date().toISOString() };

  const existing = (await storeGet('conversations_list')) || [];
  existing.unshift(conv);
  await storePut('conversations_list', existing);

  return jsonResponse(conv);
}

async function deleteConversationHandler(request, convId) {
  const existing = (await storeGet('conversations_list')) || [];
  const filtered = existing.filter(c => c.id !== convId);
  await storePut('conversations_list', filtered);
  await storeDelete(`messages:${convId}`);
  return jsonResponse({ status: 'ok' });
}

async function updateConversationHandler(request, convId) {
  const body = await request.json();
  const title = body.title || 'Conversation';
  return jsonResponse({ id: convId, title, status: 'ok' });
}

async function exportConversationHandler(request, convId) {
  const messages = await storeGet(`messages:${convId}`);
  const lines = (messages || []).map(m => `**${m.role}**: ${m.content}`);
  return new Response(lines.join('\n'), {
    headers: {
      'Content-Type': 'text/markdown',
      'Access-Control-Allow-Origin': '*',
    },
  });
}

async function listMessagesHandler(request, convId) {
  const messages = await storeGet(`messages:${convId}`);
  const formatted = (messages || []).map((m, i) => ({
    id: `msg_${i}`,
    role: m.role || 'user',
    content: m.content || '',
    msg_type: 'text',
    created_at: m.timestamp || '',
  }));
  return jsonResponse({ messages: formatted });
}

async function addMessageHandler(request, convId) {
  const body = await request.json();
  const msg = {
    role: body.role || 'user',
    content: body.content || '',
    timestamp: new Date().toISOString(),
  };

  const existing = (await storeGet(`messages:${convId}`)) || [];
  existing.push(msg);
  await storePut(`messages:${convId}`, existing);

  return jsonResponse({ status: 'ok', id: `msg_${crypto.randomUUID().slice(0, 8)}` });
}

async function syncConversationsHandler(request) {
  const body = await request.json();
  const conversations = body.conversations || [];
  return jsonResponse({ status: 'ok', synced: conversations.length });
}

// ── Auth Helpers (KV-persisted) ─────────────────────────────────────────

const TOKEN_NAME = 'acronous_token';

function base64Url(buf) {
  return btoa(String.fromCharCode(...new Uint8Array(buf)))
    .replace(/=/g, '').replace(/\+/g, '-').replace(/\//g, '_');
}

function base64UrlDecode(str) {
  str = str.replace(/-/g, '+').replace(/_/g, '/');
  while (str.length % 4) str += '=';
  return Uint8Array.from(atob(str), c => c.charCodeAt(0));
}

function textEncode(s) { return new TextEncoder().encode(s); }
function textDecode(b) { return new TextDecoder().decode(b); }

async function createJWT(payload, secret) {
  const header = base64Url(textEncode(JSON.stringify({ alg: 'HS256', typ: 'JWT' })));
  const now = Math.floor(Date.now() / 1000);
  const body = base64Url(textEncode(JSON.stringify({ ...payload, iat: now, exp: now + 604800 })));
  const data = header + '.' + body;
  const key = await crypto.subtle.importKey('raw', textEncode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const sig = await crypto.subtle.sign('HMAC', key, textEncode(data));
  return data + '.' + base64Url(sig);
}

async function verifyJWT(token, secret) {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    const key = await crypto.subtle.importKey('raw', textEncode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['verify']);
    const valid = await crypto.subtle.verify('HMAC', key, base64UrlDecode(parts[2]), textEncode(parts[0] + '.' + parts[1]));
    if (!valid) return null;
    const payload = JSON.parse(textDecode(base64UrlDecode(parts[1])));
    if (payload.exp < Math.floor(Date.now() / 1000)) return null;
    return payload;
  } catch { return null; }
}

async function hashPw(password, salt) {
  const hash = await crypto.subtle.digest('SHA-256', textEncode(password + salt));
  return base64Url(hash);
}

function userKey(email) { return `user:${email.toLowerCase()}`; }

async function getUser(email) {
  const kv = globalThis.authUsersKv;
  if (kv) {
    const raw = await kv.get(userKey(email));
    return raw ? JSON.parse(raw) : null;
  }
  return memGet(userKey(email)) || null;
}

async function saveUser(user) {
  const kv = globalThis.authUsersKv;
  if (kv) {
    await kv.put(userKey(user.email), JSON.stringify(user));
  }
  memPut(userKey(user.email), user);
}

function corsResponse(body, status = 200, origin) {
  const headers = { 'Content-Type': 'application/json' };
  if (origin) headers['Access-Control-Allow-Origin'] = origin;
  headers['Access-Control-Allow-Credentials'] = 'true';
  return new Response(JSON.stringify(body), { status, headers });
}

function redirectResponse(location) {
  return new Response(null, { status: 302, headers: { Location: location } });
}

function setCookie(token, hostname) {
  const domain = hostname?.endsWith('acronous.com') ? 'Domain=.acronous.com; ' : '';
  return `${TOKEN_NAME}=${token}; ${domain}Path=/; Max-Age=604800; SameSite=Lax; Secure`;
}

function clearCookie(hostname) {
  const domain = hostname?.endsWith('acronous.com') ? 'Domain=.acronous.com; ' : '';
  return `${TOKEN_NAME}=; ${domain}Path=/; Max-Age=0`;
}

function getTokenFromReq(request) {
  const auth = request.headers.get('Authorization');
  if (auth?.startsWith('Bearer ')) return auth.slice(7);
  const cookie = request.headers.get('Cookie');
  if (cookie) {
    const m = cookie.match(new RegExp(`${TOKEN_NAME}=([^;]+)`));
    if (m) return decodeURIComponent(m[1]);
  }
  return null;
}

// ── Auth HTML Pages (inline, self-contained) ────────────────────────────

const AUTH_STYLE = `
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#08080c;--surface:#0f0f16;--surface-2:#181822;--border:#22223a;--text:#e0e0f0;--text-muted:#7878a0;--primary:#6366f1;--primary-hover:#5558e6;--primary-glow:rgba(99,102,241,0.12);--accent-1:#22d3ee;--accent-2:#a78bfa;--error:#f87171;--success:#34d399;--radius:16px}
html{font-size:16px}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:1rem}
.bg-glow{position:fixed;inset:0;pointer-events:none;overflow:hidden;z-index:0}
.bg-glow::before{content:'';position:absolute;top:-30%;left:-10%;width:50%;height:60%;background:radial-gradient(circle,var(--primary-glow) 0%,transparent 70%);border-radius:50%}
.bg-glow::after{content:'';position:absolute;bottom:-30%;right:-10%;width:50%;height:60%;background:radial-gradient(circle,rgba(168,85,247,0.08) 0%,transparent 70%);border-radius:50%}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:2.5rem;width:100%;max-width:420px;position:relative;z-index:1;backdrop-filter:blur(24px)}
.logo{width:72px;height:72px;margin:0 auto 1.25rem;border-radius:18px;overflow:hidden;display:flex;align-items:center;justify-content:center;background:#0a0a0f;border:1px solid var(--border)}
.logo svg{width:40px;height:40px}
h1{font-size:1.35rem;font-weight:700;text-align:center;margin-bottom:0.2rem;letter-spacing:-0.01em}
.subtitle{text-align:center;color:var(--text-muted);margin-bottom:1.75rem;font-size:0.875rem}
.form-group{margin-bottom:1rem}
label{display:block;font-size:0.8rem;font-weight:500;margin-bottom:0.35rem;color:var(--text-muted);letter-spacing:0.01em;text-transform:uppercase}
input{width:100%;padding:0.75rem 1rem;background:var(--surface-2);border:1px solid var(--border);border-radius:10px;color:var(--text);font-size:0.925rem;outline:none;transition:all 0.2s;font-family:inherit}
input:focus{border-color:var(--primary);box-shadow:0 0 0 3px rgba(99,102,241,0.1)}
input::placeholder{color:var(--text-muted);opacity:0.4}
.btn{width:100%;padding:0.8rem;border:none;border-radius:10px;font-size:0.95rem;font-weight:600;cursor:pointer;transition:all 0.2s;background:linear-gradient(135deg,var(--primary),#818cf8);color:white;font-family:inherit}
.btn:hover{opacity:0.92;transform:translateY(-1px);box-shadow:0 4px 20px rgba(99,102,241,0.25)}
.btn:active{transform:translateY(0)}
.btn:disabled{opacity:0.4;cursor:not-allowed;transform:none;box-shadow:none}
.btn-loading{display:flex;align-items:center;justify-content:center;gap:0.5rem}
.spinner{width:18px;height:18px;border:2px solid rgba(255,255,255,0.2);border-top-color:white;border-radius:50%;animation:spin 0.6s linear infinite;flex-shrink:0}
@keyframes spin{to{transform:rotate(360deg)}}
.error{background:rgba(248,113,113,0.08);border:1px solid rgba(248,113,113,0.15);border-radius:10px;padding:0.65rem 0.85rem;color:var(--error);font-size:0.85rem;margin-bottom:1rem;display:none;line-height:1.4}
.error.show{display:block}
.footer-text{text-align:center;margin-top:1.5rem;font-size:0.85rem;color:var(--text-muted)}
.footer-text a{color:var(--accent-2);text-decoration:none;font-weight:600}
.footer-text a:hover{text-decoration:underline;color:var(--primary)}
.divider{display:flex;align-items:center;gap:1rem;margin:1.25rem 0;color:var(--text-muted);font-size:0.8rem}
.divider::before,.divider::after{content:'';flex:1;height:1px;background:var(--border)}
.back-link{display:inline-flex;align-items:center;gap:0.4rem;color:var(--text-muted);text-decoration:none;font-size:0.85rem;margin-bottom:1.5rem;transition:color 0.2s}
.back-link:hover{color:var(--text)}
`;

function escapeHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function loginPage(redirect) {
  return `<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Sign In - Acronous</title><style>${AUTH_STYLE}</style></head><body><div class="bg-glow"></div><div class="card"><div class="logo"><svg viewBox="0 0 80 80" fill="none"><rect width="80" height="80" rx="18" fill="#0a0a0f" stroke="#22223a" stroke-width="1"/><text x="40" y="50" text-anchor="middle" font-size="34" font-weight="800" fill="#6366f1" font-family="sans-serif">A</text></svg></div><h1>Welcome back</h1><p class="subtitle">Sign in to your Acronous account</p><div id="error" class="error"></div><form id="loginForm" novalidate><div class="form-group"><label for="email">Email</label><input id="email" type="email" placeholder="you@example.com" required autocomplete="email" autocapitalize="off" spellcheck="false"></div><div class="form-group"><label for="password">Password</label><input id="password" type="password" placeholder="&#xb7;&#xb7;&#xb7;&#xb7;&#xb7;&#xb7;&#xb7;&#xb7;&#xb7;&#xb7;&#xb7;&#xb7;" required autocomplete="current-password" minlength="6"></div><button type="submit" class="btn" id="submitBtn">Sign In</button></form><p class="footer-text">Don't have an account? <a href="/signup${redirect ? '?redirect='+encodeURIComponent(redirect) : ''}">Create one</a></p></div><script>
(function(){var e=document.getElementById('loginForm'),t=document.getElementById('email'),n=document.getElementById('password'),o=document.getElementById('error'),i=document.getElementById('submitBtn'),r=new URLSearchParams(location.search).get('redirect')||'/';e.addEventListener('submit',async function(a){a.preventDefault();o.classList.remove('show');i.disabled=true;i.innerHTML='<div class="spinner"></div> Signing in...';try{var d=await fetch('/api/auth/login-redirect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:t.value.trim(),password:n.value,redirect:r})}),s=await d.json();if(s.redirectUrl){window.location.href=s.redirectUrl}else{o.textContent=s.error||'Invalid email or password';o.classList.add('show');i.disabled=false;i.textContent='Sign In'}}catch(c){o.textContent='Connection error. Please try again.';o.classList.add('show');i.disabled=false;i.textContent='Sign In'}})})();
</script></body></html>`;
}

function signupPage(redirect) {
  return `<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Sign Up - Acronous</title><style>${AUTH_STYLE}</style></head><body><div class="bg-glow"></div><div class="card"><div class="logo"><svg viewBox="0 0 80 80" fill="none"><rect width="80" height="80" rx="18" fill="#0a0a0f" stroke="#22223a" stroke-width="1"/><text x="40" y="50" text-anchor="middle" font-size="34" font-weight="800" fill="#6366f1" font-family="sans-serif">A</text></svg></div><h1>Create your account</h1><p class="subtitle">One account for all Acronous products</p><div id="error" class="error"></div><form id="signupForm" novalidate><div class="form-group"><label for="name">Full Name</label><input id="name" type="text" placeholder="John Doe" autocomplete="name" autocapitalize="words"></div><div class="form-group"><label for="email">Email</label><input id="email" type="email" placeholder="you@example.com" required autocomplete="email" autocapitalize="off" spellcheck="false"></div><div class="form-group"><label for="password">Password</label><input id="password" type="password" placeholder="&#xb7;&#xb7;&#xb7;&#xb7;&#xb7;&#xb7;&#xb7;&#xb7;&#xb7;&#xb7;&#xb7;&#xb7;" required minlength="6" autocomplete="new-password"></div><button type="submit" class="btn" id="submitBtn">Create Account</button></form><p class="footer-text">Already have an account? <a href="/login${redirect ? '?redirect='+encodeURIComponent(redirect) : ''}">Sign in</a></p></div><script>
(function(){var e=document.getElementById('signupForm'),t=document.getElementById('name'),n=document.getElementById('email'),o=document.getElementById('password'),i=document.getElementById('error'),r=document.getElementById('submitBtn'),a=new URLSearchParams(location.search).get('redirect')||'/';e.addEventListener('submit',async function(d){d.preventDefault();i.classList.remove('show');r.disabled=true;r.innerHTML='<div class="spinner"></div> Creating account...';try{var s=await fetch('/api/auth/signup-redirect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:n.value.trim(),password:o.value,name:t.value.trim()||n.value.split('@')[0],redirect:a})}),u=await s.json();if(u.redirectUrl){window.location.href=u.redirectUrl}else{i.textContent=u.error||'Sign up failed';i.classList.add('show');r.disabled=false;r.textContent='Create Account'}}catch(c){i.textContent='Connection error. Please try again.';i.classList.add('show');r.disabled=false;r.textContent='Create Account'}})})();
</script></body></html>`;
}

function dashboardPage(user, token) {
  const tokenParam = token ? `?token=${token}` : '';
  return `<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Dashboard - Acronous</title><style>${AUTH_STYLE}.back-link{margin-bottom:1rem}.apps-grid{display:grid;grid-template-columns:1fr;gap:0.75rem;margin-top:1.25rem}@media(min-width:600px){.apps-grid{grid-template-columns:1fr 1fr}}.app-card{background:var(--surface-2);border:1px solid var(--border);border-radius:14px;padding:1.25rem;text-decoration:none;color:var(--text);transition:all 0.2s;display:flex;align-items:center;gap:1rem}.app-card:hover{border-color:var(--primary);transform:translateY(-2px);box-shadow:0 4px 24px var(--primary-glow)}.app-icon{width:44px;height:44px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:1.2rem;font-weight:700;color:white;flex-shrink:0}.app-icon.ai{background:linear-gradient(135deg,#6366f1,#22d3ee)}.app-icon.eq{background:linear-gradient(135deg,#ec4899,#a78bfa)}.app-icon.nw{background:linear-gradient(135deg,#f59e0b,#f87171)}.app-info h3{font-size:0.95rem;font-weight:600;margin-bottom:0.15rem}.app-info p{font-size:0.8rem;color:var(--text-muted)}.user-info{display:flex;align-items:center;justify-content:space-between;margin-bottom:1.5rem;padding-bottom:1.25rem;border-bottom:1px solid var(--border)}.user-details span{display:block}.user-details .name{font-weight:600;font-size:1rem}.user-details .email{font-size:0.8rem;color:var(--text-muted);margin-top:0.1rem}.btn-outline{background:transparent;border:1px solid var(--border);color:var(--text);padding:0.45rem 1rem;border-radius:8px;cursor:pointer;font-size:0.8rem;transition:all 0.2s;font-family:inherit}.btn-outline:hover{border-color:var(--error);color:var(--error)}
</style></head><body><div class="bg-glow"></div><div class="card" style="max-width:520px"><div class="logo"><svg viewBox="0 0 80 80" fill="none"><rect width="80" height="80" rx="18" fill="#0a0a0f" stroke="#22223a" stroke-width="1"/><text x="40" y="50" text-anchor="middle" font-size="34" font-weight="800" fill="#6366f1" font-family="sans-serif">A</text></svg></div><h1>Acronous Apps</h1><div class="user-info"><div class="user-details"><span class="name">${escapeHtml(user.name)}</span><span class="email">${escapeHtml(user.email)}</span></div><button class="btn-outline" id="logoutBtn">Sign Out</button></div><p class="subtitle" style="text-align:left;margin-bottom:0">Choose an app to launch</p><div class="apps-grid"><a class="app-card" href="https://ai.acronous.com${tokenParam}"><div class="app-icon ai">AI</div><div class="app-info"><h3>Acronous AI</h3><p>AI-powered chat &amp; assistance</p></div></a><a class="app-card" href="https://equyvo.acronous.com${tokenParam}"><div class="app-icon eq">Eq</div><div class="app-info"><h3>Equyvo</h3><p>Social content &amp; discovery</p></div></a><a class="app-card" href="https://navigwiz.acronous.com${tokenParam}" style="grid-column:1/-1"><div class="app-icon nw">Nw</div><div class="app-info"><h3>Navigwiz</h3><p>AI-powered browser &amp; workspace</p></div></a></div></div><script>
(function(){document.getElementById('logoutBtn').addEventListener('click',async function(){await fetch('/api/auth/logout',{method:'POST'});window.location.href='/login'});var e=new URLSearchParams(location.search).get('token');if(e){document.querySelectorAll('.app-card').forEach(function(t){var n=new URL(t.href);n.searchParams.set('token',e);t.href=n.toString()})}})();
</script></body></html>`;
}

// ── Auth Request Handler ────────────────────────────────────────────────

async function handleAuthRequest(request, url, env) {
  const path = url.pathname;
  const method = request.method;
  const origin = request.headers.get('Origin') || 'https://acronous.com';
  const hostname = url.hostname;
  const jwtSecret = env?.JWT_SECRET || 'acronous-auth-secret-change-in-prod';

  if (path === '/api/auth/signup' && method === 'POST') {
    try {
      const { email, password, name } = await request.json();
      if (!email || !password) return corsResponse({ error: 'Email and password are required' }, 400, origin);
      if (password.length < 6) return corsResponse({ error: 'Password must be at least 6 characters' }, 400, origin);
      if (await getUser(email)) return corsResponse({ error: 'An account with this email already exists' }, 409, origin);
      const salt = crypto.randomUUID();
      const hashed = await hashPw(password, salt);
      const user = { id: crypto.randomUUID(), email: email.toLowerCase(), name: name || email.split('@')[0], salt, password: hashed, createdAt: new Date().toISOString() };
      await saveUser(user);
      const token = await createJWT({ id: user.id, email: user.email, name: user.name }, jwtSecret);
      const res = corsResponse({ success: true, token, user: { id: user.id, email: user.email, name: user.name } }, 200, origin);
      res.headers.append('Set-Cookie', setCookie(token, hostname));
      return res;
    } catch { return corsResponse({ error: 'Something went wrong. Please try again.' }, 500, origin); }
  }

  if (path === '/api/auth/signup-redirect' && method === 'POST') {
    try {
      const { email, password, name, redirect } = await request.json();
      if (!email || !password) return corsResponse({ error: 'Email and password are required' }, 400, origin);
      if (password.length < 6) return corsResponse({ error: 'Password must be at least 6 characters' }, 400, origin);
      if (await getUser(email)) return corsResponse({ error: 'An account with this email already exists' }, 409, origin);
      const salt = crypto.randomUUID();
      const hashed = await hashPw(password, salt);
      const user = { id: crypto.randomUUID(), email: email.toLowerCase(), name: name || email.split('@')[0], salt, password: hashed, createdAt: new Date().toISOString() };
      await saveUser(user);
      const token = await createJWT({ id: user.id, email: user.email, name: user.name }, jwtSecret);
      const target = (redirect || '/') + ((redirect || '').includes('?') ? '&' : '?') + 'token=' + token;
      const res = corsResponse({ success: true, redirectUrl: target, token }, 200, origin);
      res.headers.append('Set-Cookie', setCookie(token, hostname));
      return res;
    } catch { return corsResponse({ error: 'Authentication failed. Please try again.' }, 500, origin); }
  }

  if (path === '/api/auth/login' && method === 'POST') {
    try {
      const { email, password } = await request.json();
      if (!email || !password) return corsResponse({ error: 'Email and password are required' }, 400, origin);
      const user = await getUser(email);
      if (!user) return corsResponse({ error: 'Invalid email or password' }, 401, origin);
      const hashed = await hashPw(password, user.salt);
      if (hashed !== user.password) return corsResponse({ error: 'Invalid email or password' }, 401, origin);
      const token = await createJWT({ id: user.id, email: user.email, name: user.name }, jwtSecret);
      const res = corsResponse({ success: true, token, user: { id: user.id, email: user.email, name: user.name } }, 200, origin);
      res.headers.append('Set-Cookie', setCookie(token, hostname));
      return res;
    } catch { return corsResponse({ error: 'Something went wrong. Please try again.' }, 500, origin); }
  }

  if (path === '/api/auth/login-redirect' && method === 'POST') {
    try {
      const { email, password, redirect } = await request.json();
      if (!email || !password) return corsResponse({ error: 'Email and password are required' }, 400, origin);
      const user = await getUser(email);
      if (!user) return corsResponse({ error: 'Invalid email or password' }, 401, origin);
      const hashed = await hashPw(password, user.salt);
      if (hashed !== user.password) return corsResponse({ error: 'Invalid email or password' }, 401, origin);
      const token = await createJWT({ id: user.id, email: user.email, name: user.name }, jwtSecret);
      const target = (redirect || '/') + ((redirect || '').includes('?') ? '&' : '?') + 'token=' + token;
      const res = corsResponse({ success: true, redirectUrl: target, token }, 200, origin);
      res.headers.append('Set-Cookie', setCookie(token, hostname));
      return res;
    } catch { return corsResponse({ error: 'Something went wrong. Please try again.' }, 500, origin); }
  }

  if (path === '/api/auth/logout' && method === 'POST') {
    const res = corsResponse({ success: true }, 200, origin);
    res.headers.append('Set-Cookie', clearCookie(hostname));
    return res;
  }

  if (path === '/api/auth/verify') {
    const token = getTokenFromReq(request);
    if (!token) return corsResponse({ valid: false }, 200, origin);
    const decoded = await verifyJWT(token, jwtSecret);
    if (!decoded) return corsResponse({ valid: false }, 200, origin);
    return corsResponse({ valid: true, user: { id: decoded.id, email: decoded.email, name: decoded.name } }, 200, origin);
  }

  if (path === '/api/auth/me') {
    const token = getTokenFromReq(request);
    if (!token) return corsResponse({ error: 'Not authenticated' }, 401, origin);
    const decoded = await verifyJWT(token, jwtSecret);
    if (!decoded) return corsResponse({ error: 'Not authenticated' }, 401, origin);
    return corsResponse({ user: { id: decoded.id, email: decoded.email, name: decoded.name } }, 200, origin);
  }

  if (path === '/login' || path === '/login.html') {
    const token = getTokenFromReq(request);
    if (token) {
      const decoded = await verifyJWT(token, jwtSecret);
      if (decoded) return redirectResponse(url.searchParams.get('redirect') || '/');
    }
    return new Response(loginPage(url.searchParams.get('redirect') || ''), { headers: { 'Content-Type': 'text/html;charset=utf-8' } });
  }

  if (path === '/signup' || path === '/signup.html') {
    const token = getTokenFromReq(request);
    if (token) {
      const decoded = await verifyJWT(token, jwtSecret);
      if (decoded) return redirectResponse(url.searchParams.get('redirect') || '/');
    }
    return new Response(signupPage(url.searchParams.get('redirect') || ''), { headers: { 'Content-Type': 'text/html;charset=utf-8' } });
  }

  if (path === '/dashboard' || path === '/dashboard.html') {
    const token = getTokenFromReq(request);
    if (!token) return redirectResponse('/login?redirect=' + encodeURIComponent(url.pathname));
    const decoded = await verifyJWT(token, jwtSecret);
    if (!decoded) return redirectResponse('/login?redirect=' + encodeURIComponent(url.pathname));
    return new Response(dashboardPage(decoded, token), { headers: { 'Content-Type': 'text/html;charset=utf-8' } });
  }

  if (path === '/logout') {
    const res = redirectResponse('/login');
    res.headers.append('Set-Cookie', clearCookie(hostname));
    return res;
  }

  if (path === '/health') {
    return corsResponse({ status: 'ok' }, 200, origin);
  }

  return new Response('Not Found', { status: 404 });
}

// ── Auth route matcher ──────────────────────────────────────────────────

const AUTH_ROUTES = new Set([
  '/login', '/login.html',
  '/signup', '/signup.html',
  '/dashboard', '/dashboard.html',
  '/logout',
]);

// ── Static / SPA serving ──────────────────────────────────────────────────

async function serveStaticOrSPA(request) {
  const method = request.method;

  // Only proxy GET/HEAD requests to Pages for static file serving.
  // Non-GET requests that don't match an API route return a 405 error.
  if (method !== 'GET' && method !== 'HEAD') {
    return jsonResponse({ error: 'Method not allowed' }, 405);
  }

  if (PAGES_ORIGIN) {
    const url = new URL(request.url);
    const pagesOriginUrl = new URL(PAGES_ORIGIN);

    // Avoid proxying to self — prevents infinite loop when the Worker
    // is deployed on the same domain as the Pages origin
    if (url.hostname !== pagesOriginUrl.hostname) {
      const pagesUrl = `${PAGES_ORIGIN}${url.pathname}${url.search}`;
      try {
        const resp = await fetch(pagesUrl);
        if (resp.ok) {
          const headers = new Headers(resp.headers);
          headers.set('Access-Control-Allow-Origin', '*');
          return new Response(resp.body, { status: resp.status, headers });
        }
        if (resp.status === 404) {
          // SPA fallback — serve index.html
          const indexResp = await fetch(`${PAGES_ORIGIN}/index.html`);
          const indexHeaders = new Headers(indexResp.headers);
          indexHeaders.set('Access-Control-Allow-Origin', '*');
          return new Response(indexResp.body, { status: 200, headers: indexHeaders });
        }
      } catch {}
    }
  }

  // Fallback: redirect to the main landing page
  const landingPage = 'https://acronous.com';
  return new Response(
    `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="refresh" content="0; url=${landingPage}">
  <title>Redirecting to Acronous</title>
</head>
<body>
  <p>Redirecting to <a href="${landingPage}">acronous.com</a>...</p>
</body>
</html>`,
    {
      status: 200,
      headers: { 'Content-Type': 'text/html; charset=utf-8' },
    },
  );
}

// ── CORS preflight ────────────────────────────────────────────────────────

function optionsHandler() {
  return new Response(null, {
    status: 204,
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization',
      'Access-Control-Max-Age': '86400',
    },
  });
}

// ── Router ────────────────────────────────────────────────────────────────

function matchPath(path) {
  const parts = path.split('?')[0].replace(/\/+$/, '') || '/';
  const segments = parts.split('/').filter(Boolean);

  const conversationMatch = parts.match(/^\/api\/conversations\/([^\/]+)\/(messages|export)(?:\/(.+))?$/);
  if (conversationMatch) {
    return { type: 'conversation_child', convId: conversationMatch[1], child: conversationMatch[2], rest: conversationMatch[3] };
  }

  const conversationIdMatch = parts.match(/^\/api\/conversations\/([^\/]+)$/);
  if (conversationIdMatch) {
    return { type: 'conversation_id', convId: conversationIdMatch[1] };
  }

  return { type: parts, segments };
}

const AI_HOSTS = new Set([
  'ai.acronous.com',
  'acronous-ai.hriteshkumarpatro.workers.dev',
  'acronous-ai.httpsacronous-landinghriteshkumarpatroworkersdev.workers.dev',
]);

function isApiPath(path) {
  const apiPrefixes = ['/v1/', '/api/', '/health', '/v1/health'];
  return apiPrefixes.some(p => path === p || path.startsWith(p));
}

function isLandingPageHost(hostname) {
  return hostname === 'acronous.com' || hostname === 'www.acronous.com';
}

export default {
  async fetch(request, env) {
    // Load config from env (secrets + vars)
    OPENROUTER_API_KEY = env.OPENROUTER_API_KEY || '';
    OPENROUTER_MODEL = env.OPENROUTER_MODEL || 'meta-llama/llama-3.3-70b-instruct';
    OPENROUTER_BASE_URL = env.OPENROUTER_BASE_URL || 'https://openrouter.ai/api/v1';
    PAGES_ORIGIN = env.PAGES_ORIGIN || '';
    ENABLE_WEB = (env.ENABLE_WEB || 'true') === 'true';
    ENABLE_VISION = (env.ENABLE_VISION || 'true') === 'true';
    ENABLE_VOICE = (env.ENABLE_VOICE || 'true') === 'true';
    WHISPER_API_KEY = env.WHISPER_API_KEY || '';
    if (env.acronous_kv) globalThis.acronous_kv = env.acronous_kv;
    if (env.AUTH_USERS) globalThis.authUsersKv = env.AUTH_USERS;

    const url = new URL(request.url);
    const hostname = url.hostname;
    const path = url.pathname.replace(/\/+$/, '') || '/';
    const method = request.method;

    if (method === 'OPTIONS') return optionsHandler();

    // ── Auth routes → handled directly (no proxy) ─────────────────────
    // Handled BEFORE host checks so auth works from ANY domain/URL
    if (AUTH_ROUTES.has(path) || path.startsWith('/api/auth/')) {
      return handleAuthRequest(request, url, env);
    }

    // ── Root domain traffic → landing page (unless it's an API call) ────
    if (isLandingPageHost(hostname) && !isApiPath(path)) {
      return Response.redirect('https://acronous.com', 301);
    }

    // ── Unknown host → redirect to landing page ─────────────────────────
    if (!AI_HOSTS.has(hostname) && !isLandingPageHost(hostname) && !isApiPath(path)) {
      return Response.redirect('https://acronous.com', 301);
    }

    const route = matchPath(path);

    try {
      // ── Health & Readiness ──────────────────────────────────────────
      if (path === '/v1/health') return healthHandler();
      if (path === '/v1/ready') return readyHandler();
      if (path === '/v1/health/llm') return healthLLMHandler();
      if (path === '/v1/wakeup') return wakeupHandler();
      if (path === '/health') return healthHandler();

      // ── Chat ────────────────────────────────────────────────────────
      if (path === '/v1/chat/stream' && method === 'POST') return chatStreamHandler(request);
      if (path === '/v1/chat' && method === 'POST') return chatHandler(request);
      if (path === '/v1/chat/image' && method === 'POST') return chatImageHandler(request);
      if (path === '/v1/chat/file' && method === 'POST') return chatFileHandler(request);

      // ── Image ───────────────────────────────────────────────────────
      if (path === '/v1/image/generate') return generateImageHandler(request);
      if (path === '/v1/image/edit' && method === 'POST') return editImageHandler(request);

      // ── API ─────────────────────────────────────────────────────────
      if (path === '/api/chat' && method === 'POST') return apiChatHandler(request);
      if (path === '/api/image/qr-code' && method === 'POST') return qrCodeHandler(request);
      if (path === '/api/image/redesign' && method === 'POST') return redesignImageHandler(request);
      if (path === '/api/image/analyze' && method === 'POST') return analyzeImageHandler(request);
      if (path === '/api/tools/search' && method === 'POST') return searchHandler(request);
      if (path === '/api/voice/transcribe' && method === 'POST') return transcribeHandler(request);
      if (path === '/api/tools/process-document' && method === 'POST') return processDocumentHandler(request);
      if (path === '/api/models/list') return modelsHandler();
      if (path === '/api/status') return statusHandler();
      if (path === '/api/config' && method === 'GET') return configHandler();
      if (path === '/api/config/llm' && method === 'GET') return llmConfigGetHandler();
      if (path === '/api/config/llm' && method === 'POST') return llmConfigPostHandler();

      // ── Conversations ───────────────────────────────────────────────
      if (path === '/api/conversations') {
        if (method === 'GET') return listConversationsHandler();
        if (method === 'POST') return createConversationHandler(request);
      }

      if (route.type === 'conversation_child') {
        const { convId, child } = route;
        if (child === 'messages') {
          if (method === 'GET') return listMessagesHandler(request, convId);
          if (method === 'POST') return addMessageHandler(request, convId);
        }
        if (child === 'export') return exportConversationHandler(request, convId);
      }

      if (route.type === 'conversation_id') {
        if (method === 'DELETE') return deleteConversationHandler(request, route.convId);
        if (method === 'PUT') return updateConversationHandler(request, route.convId);
      }

      if (path === '/api/conversations/sync' && method === 'POST') return syncConversationsHandler(request);

      // ── Everything else → static/SPA ────────────────────────────────
      return serveStaticOrSPA(request);
    } catch (e) {
      return errorResponse(`Internal error: ${e.message}`);
    }
  },
};
