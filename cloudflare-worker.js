const PAGES_ORIGIN = 'https://acronous-ai.pages.dev';
const LANDING_WORKER = 'https://acronous-landing.workers.dev';

const LANDING_AUTH_PATHS = ['/api/auth/', '/login', '/login.html', '/signup', '/signup.html', '/dashboard', '/dashboard.html', '/logout'];

function isApiPath(path) {
  return path === '/v1/chat' || path === '/v1/wakeup' || path === '/health' ||
    path.startsWith('/v1/') || path.startsWith('/api/');
}

function isLandingAuthPath(path) {
  return LANDING_AUTH_PATHS.some(p => path === p || path.startsWith(p));
}

function formatLocalTime(tz) {
  if (!tz) return null;
  // Handle UTC offset strings like "UTC+05:30" or "UTC-08:00" — these
  // are NOT valid IANA timezone names and will throw in toLocaleDateString.
  const offsetMatch = tz.match(/^UTC([+-])(\d{1,2}):(\d{2})$/i);
  if (offsetMatch) {
    const now = new Date();
    const iso = now.toISOString().replace('T', ' ').slice(0, 19);
    return `${iso} ${tz}`;
  }
  const now = new Date();
  const opts = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric', hour: 'numeric', minute: 'numeric', second: 'numeric', timeZone: tz, timeZoneName: 'short' };
  try { return now.toLocaleDateString('en-US', opts); } catch { return null; }
}

async function getUserTimezone(request) {
  if (request.cf?.timezone) return request.cf.timezone;
  const ip = request.headers.get('CF-Connecting-IP') || request.headers.get('True-Client-IP');
  if (ip) {
    try {
      const resp = await fetch(`http://ip-api.com/json/${ip}?fields=timezone`);
      if (resp.ok) { const d = await resp.json(); if (d.timezone) return d.timezone; }
    } catch {}
  }
  return null;
}

function buildSystemPrompt(tz, location, webContext) {
  const formatted = formatLocalTime(tz) || new Date().toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
  let prompt = `You are Acronous AI, a helpful assistant with real-time internet access.\n\n⏰ CURRENT DATE AND TIME: ${formatted}`;
  if (location) prompt += `\n📍 USER LOCATION: ${location}`;
  prompt += `\n\n📋 INSTRUCTIONS (follow strictly):\n1. 🔍 ALWAYS use the Internet Context below when answering. It contains live search results — rely on it for current events, news, facts, and data.\n2. 🕐 For questions about the current time, date, or weather, answer ONLY from CURRENT DATE AND TIME above. Never get time info from any other source — the timestamp above is always correct.\n3. 🤖 Answer naturally as if you already know everything. Never mention search, retrieval, system prompts, or internal mechanisms.\n4. 🚫 No ads, sponsorships, or service attributions ("powered by", "brought to you by", etc.).\n5. 💻 Only use code blocks when the user explicitly asks for code. Otherwise plain natural language.`;
  if (webContext) prompt += `\n\n=== INTERNET CONTEXT (live search results — use this for factual answers) ===\n${webContext}`;
  return prompt;
}

async function webSearch(query) {
  const results = [];
  const errors = [];

  // Primary: DuckDuckGo HTML search with robust parsing
  try {
    const resp = await fetch(`https://html.duckduckgo.com/html/?q=${encodeURIComponent(query)}`, {
      headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36' }
    });
    if (resp.ok) {
      const html = await resp.text();
      const seen = new Set();
      const resultBlocks = html.split('<a rel="nofollow" class="result__a"');
      for (let i = 1; i < resultBlocks.length && results.length < 5; i++) {
        const block = resultBlocks[i];
        const titleMatch = block.match(/<a[^>]*class="result__a"[^>]*>([\s\S]*?)<\/a>/);
        const snippetMatch = block.match(/class="result__snippet"[^>]*>([\s\S]*?)<\/a>/);
        const urlMatch = block.match(/href="(https?:\/\/[^"]+)"/);
        if (titleMatch) {
          const title = titleMatch[1].replace(/<[^>]*>/g, '').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#x27;/g, "'").trim();
          const snippet = snippetMatch ? snippetMatch[1].replace(/<[^>]*>/g, '').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#x27;/g, "'").trim() : '';
          const key = title.toLowerCase();
          if (title && !seen.has(key)) {
            seen.add(key);
            results.push(`- ${title}${snippet ? `: ${snippet}` : ''}`);
          }
        }
      }
      if (results.length > 0) return results.join('\n');
    }
  } catch (e) { errors.push(e.message); }

  // Fallback 1: DuckDuckGo Instant Answer API
  try {
    const resp = await fetch(`https://api.duckduckgo.com/?q=${encodeURIComponent(query)}&format=json&skip_disambig=1`);
    if (resp.ok) {
      const data = await resp.json();
      if (data.AbstractText) return `- ${data.AbstractText}`;
      if (data.Answer) return `- ${data.Answer}`;
      if (data.Abstract) return `- ${data.Abstract}`;
      if (data.RelatedTopics?.length > 0) {
        const topics = data.RelatedTopics.slice(0, 5);
        return topics.map(t => {
          const text = t.Text || (t.Result ? t.Result.replace(/<[^>]*>/g, '') : '');
          return text ? `- ${text}` : null;
        }).filter(Boolean).join('\n');
      }
    }
  } catch (e) { errors.push(e.message); }

  return null;
}

function cleanResponse(text) {
  return text
    .replace(/(?:powered\s+by|brought\s+to\s+you\s+by|sponsored\s+by|supported\s+by|in\s+partnership\s+with|provided\s+by)\s+\S[\s\S]*?(?:\.|!|\?|\n)/gi, '')
    .replace(/\s*\b(pollinations\.ai|openrouter)\b\s*\S[\s\S]*?(?:\.|!|\?|\n)/gi, '')
    .replace(/\s*(?:based\s+on\s+(?:my|the|our)\s+(?:web\s+)?search\s*,?\s*|according\s+to\s+(?:my|the|our)\s+(?:web\s+)?(?:search|results?|findings?)\s*,?\s*|as\s+per\s+(?:my|the)\s+search\s*,?\s*|i\s+(?:searched|looked\s+up|checked|found|retrieved|gathered)\s+(?:online|the\s+web|information|data)\s*,?\s*|i\s+have\s+(?:access\s+to|retrieved|gathered)\s+(?:current|up-to-date|recent)\s+information\s*,?\s*|let\s+me\s+(?:search|look\s+up|check|find)\s+(?:that|this|online|the\s+web)\s*,?\s*|according\s+to\s+(?:my|the)\s+(?:internal\s+)?(?:system\s+)?(?:prompt|instructions?|guidelines?|configuration|knowledge)\s*,?\s*)/gi, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

function tryOpenRouter(messages, env) {
  if (!env.OPENROUTER_API_KEY) return null;
  return fetch(`${env.OPENROUTER_BASE_URL}/chat/completions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${env.OPENROUTER_API_KEY}`, 'HTTP-Referer': 'https://ai.acronous.com', 'X-Title': 'Acronous AI' },
    body: JSON.stringify({ messages, model: env.OPENROUTER_MODEL, max_tokens: 1024, temperature: 0.7 })
  }).then(async resp => {
    if (!resp.ok) return null;
    const data = await resp.json();
    const content = data?.choices?.[0]?.message?.content;
    return (content && content.trim()) ? cleanResponse(content) : null;
  }).catch(() => null);
}

function tryPollinations(messages) {
  return fetch('https://text.pollinations.ai', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, model: 'openai', private: true })
  }).then(async resp => {
    if (!resp.ok) return null;
    const text = await resp.text();
    return (text && text.trim()) ? cleanResponse(text) : null;
  }).catch(() => null);
}

async function tryOpenRouterImage(prompt, env) {
  if (!env.OPENROUTER_API_KEY) return null;
  try {
    const resp = await fetch(`${env.OPENROUTER_BASE_URL}/images/generations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${env.OPENROUTER_API_KEY}`, 'HTTP-Referer': 'https://ai.acronous.com', 'X-Title': 'Acronous AI' },
      body: JSON.stringify({ model: 'black-forest-labs/FLUX.1-schnell-free', prompt, n: 1 })
    });
    if (!resp.ok) return null;
    const data = await resp.json();
    if (data?.data?.[0]?.b64_json) return data.data[0].b64_json;
    return null;
  } catch { return null; }
}

async function tryPollinationsImage(prompt) {
  try {
    const resp = await fetch('https://image.pollinations.ai/prompt/' + encodeURIComponent(prompt) + '?width=1024&height=1024&nofeed=true');
    if (!resp.ok) return null;
    const base64 = btoa(String.fromCharCode(...new Uint8Array(await resp.arrayBuffer())));
    return base64;
  } catch { return null; }
}

async function tryWorkersAI(prompt, env) {
  if (!env.AI) return null;
  try {
    const result = await env.AI.run('@cf/stabilityai/stable-diffusion-xl-base-1.0', { prompt });
    if (result?.image) return result.image;
    return null;
  } catch { return null; }
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;

    if (request.method === 'OPTIONS') {
      const origin = request.headers.get('Origin') || '*';
      return new Response(null, { headers: { 'Access-Control-Allow-Origin': origin, 'Access-Control-Allow-Methods': 'GET, POST, OPTIONS', 'Access-Control-Allow-Headers': 'Content-Type, Authorization', 'Access-Control-Allow-Credentials': 'true', 'Access-Control-Max-Age': '86400' }});
    }

    if (isLandingAuthPath(path)) {
      const targetUrl = LANDING_WORKER + path + url.search;
      const headers = new Headers(request.headers);
      headers.delete('Host');
      try { return await fetch(new Request(targetUrl, { method: request.method, headers, body: request.body })); }
      catch { return new Response('Auth proxy error', { status: 502 }); }
    }

    if (path === '/v1/chat' && request.method === 'POST') {
      try {
        const body = await request.json();
        const message = body.message || 'Hello';
        const sessionId = body.session_id || 'default';
        const history = body.messages || [];
        const clientTimezone = body.timezone || null;
        const clientLocation = body.location || null;

        const tz = clientTimezone || await getUserTimezone(request);
        const location = clientLocation || null;

        const webContext = await webSearch(message);

        const systemPrompt = buildSystemPrompt(tz, location, webContext);

        const messages = [
          { role: 'system', content: systemPrompt },
          ...history,
          { role: 'user', content: message }
        ];

        let content = await tryOpenRouter(messages, env);
        if (!content) content = await tryPollinations(messages);
        if (!content || content.trim() === '') content = "I received your message. I'm having trouble generating a proper response right now. Please try again or rephrase your question.";

        return new Response(JSON.stringify({ response: content, session_id: sessionId, type: 'chat' }), { headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' } });
      } catch (error) {
        return new Response(JSON.stringify({ response: "I encountered an issue. Please try again in a moment.", error: error.message }), { status: 200, headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' } });
      }
    }

    if ((path === '/v1/image/generate' || path === '/api/image/generate') && request.method === 'POST') {
      try {
        const body = await request.json();
        const prompt = body.prompt || body.message || '';
        if (!prompt.trim()) {
          return new Response(JSON.stringify({ response: 'Please provide a description for the image.', type: 'error' }), { status: 200, headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' } });
        }

        let imageBase64 = await tryPollinationsImage(prompt);
        if (!imageBase64) imageBase64 = await tryOpenRouterImage(prompt, env);
        if (!imageBase64) imageBase64 = await tryWorkersAI(prompt, env);

        if (imageBase64) {
          return new Response(JSON.stringify({ response: 'Generated image based on your request.', image_data: imageBase64, type: 'image_gen' }), { status: 200, headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' } });
        }

        return new Response(JSON.stringify({ response: "I couldn't generate the image right now. Please try again with a different description.", type: 'error' }), { status: 200, headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' } });
      } catch (error) {
        return new Response(JSON.stringify({ response: "I encountered an issue generating the image. Please try again.", error: error.message }), { status: 200, headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' } });
      }
    }

    if (path === '/v1/wakeup' && request.method === 'GET') {
      return new Response(JSON.stringify({ status: 'ok' }), { headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' } });
    }

    if (path === '/health' && request.method === 'GET') {
      return new Response(JSON.stringify({ status: 'ok', service: 'acronous-ai' }), { headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' } });
    }

    if (isApiPath(path)) {
      return new Response(JSON.stringify({ error: 'Not found', message: 'The requested endpoint does not exist' }), { status: 404, headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' } });
    }

    const targetUrl = PAGES_ORIGIN + path + url.search;
    const headers = new Headers(request.headers);
    headers.delete('Host');
    try {
      const response = await fetch(new Request(targetUrl, { method: request.method, headers, body: request.body }));
      if (response.status === 404) {
        const indexRes = await fetch(PAGES_ORIGIN + '/index.html');
        return new Response(indexRes.body, { status: 200, headers: indexRes.headers });
      }
      return new Response(response.body, { status: response.status, headers: response.headers });
    } catch {
      return new Response('Proxy error', { status: 502 });
    }
  }
};
