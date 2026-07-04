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
  const now = new Date();
  const opts = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric', hour: 'numeric', minute: 'numeric', second: 'numeric', timeZone: tz, timeZoneName: 'short' };
  try { return now.toLocaleDateString('en-US', opts); } catch {
    // If tz is an invalid IANA name, fall back to UTC
    return now.toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
  }
}

async function resolveUserGeo(request) {
  // Try Cloudflare's built-in geo data first (fastest, most reliable)
  if (request.cf) {
    const tz = request.cf.timezone || null;
    const city = request.cf.city || '';
    const country = request.cf.country || '';
    const location = [city, country].filter(Boolean).join(', ') || null;
    if (tz || location) return { tz, location };
  }

  const ip = request.headers.get('CF-Connecting-IP') || request.headers.get('True-Client-IP');
  if (!ip) return { tz: null, location: null };

  // Fallback 1: ip-api.com (HTTPS)
  try {
    const resp = await fetch(`https://ip-api.com/json/${ip}?fields=timezone,city,country,status`);
    if (resp.ok) {
      const d = await resp.json();
      if (d.status === 'success') {
        const tz = d.timezone || null;
        const city = d.city || '';
        const country = d.country || '';
        const location = [city, country].filter(Boolean).join(', ') || null;
        return { tz, location };
      }
    }
  } catch {}

  // Fallback 2: freeipapi.com
  try {
    const resp = await fetch(`https://freeipapi.com/api/json/${ip}`);
    if (resp.ok) {
      const d = await resp.json();
      const tz = (d.timeZone || d.timezone || null);
      const city = d.cityName || d.city || '';
      const country = d.countryName || d.country || '';
      const location = [city, country].filter(Boolean).join(', ') || null;
      return { tz, location };
    }
  } catch {}

  return { tz: null, location: null };
}

function buildSystemPrompt(tz, location, webContext) {
  const formatted = formatLocalTime(tz) || new Date().toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
  let prompt = `You are Acronous AI, a helpful assistant with live internet access. Current date and time: ${formatted}.`;
  if (location) prompt += ` User's location: ${location}.`;
  prompt += ` Answer in natural, conversational language.`;
  prompt += `\n\nACCURACY RULE: You MUST always give accurate, up-to-date answers for EVERY query. Before answering any question involving facts, data, or information that could be time-sensitive, use the web_search tool to verify. Never rely solely on your training data — always confirm with live search results.`;
  if (webContext) {
    prompt += `\n\nIMPORTANT: Live web search results are provided below. You MUST use these to answer — they contain current, up-to-date information. Do not rely on your training data for current events, facts, or data. Only use your training data for general knowledge or when the web results don't cover the topic.\n\nWeb results:\n${webContext}`;
  }
  prompt += `\n\nIf the user asks for code or programming, provide the code clearly. For general questions, never give code-like answers — respond in plain natural language.`;
  return prompt;
}

async function webSearch(query) {
  // Strategy 1: DuckDuckGo HTML search (most comprehensive)
  try {
    const resp = await fetch(`https://html.duckduckgo.com/html/?q=${encodeURIComponent(query)}`, {
      headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36' }
    });
    if (resp.ok) {
      const html = await resp.text();
      const results = [];
      const seen = new Set();
      const blocks = html.split('<a rel="nofollow" class="result__a"');
      for (let i = 1; i < blocks.length && results.length < 5; i++) {
        const block = blocks[i];
        const titleMatch = block.match(/<a[^>]*class="result__a"[^>]*>([\s\S]*?)<\/a>/);
        const snippetMatch = block.match(/class="result__snippet"[^>]*>([\s\S]*?)<\/a>/);
        if (titleMatch) {
          const title = titleMatch[1].replace(/<[^>]*>/g, '').replace(/&[^;]+;/g, ' ').trim();
          const snippet = snippetMatch ? snippetMatch[1].replace(/<[^>]*>/g, '').replace(/&[^;]+;/g, ' ').trim() : '';
          const key = title.toLowerCase().slice(0, 50);
          if (title && title.length > 2 && !seen.has(key)) {
            seen.add(key);
            results.push(`- ${title}${snippet ? `: ${snippet}` : ''}`);
          }
        }
      }
      if (results.length > 0) return results.join('\n');
    }
  } catch {}

  // Strategy 2: DuckDuckGo Lite API (simpler HTML, very stable)
  try {
    const resp = await fetch(`https://lite.duckduckgo.com/lite/?q=${encodeURIComponent(query)}`, {
      headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36' }
    });
    if (resp.ok) {
      const html = await resp.text();
      const results = [];
      const seen = new Set();
      const rows = html.split('<tr class="result">');
      for (let i = 1; i < rows.length && results.length < 5; i++) {
        const row = rows[i];
        const linkMatch = row.match(/<a[^>]*class="result-link"[^>]*>([\s\S]*?)<\/a>/);
        const snippetMatch = row.match(/<td[^>]*class="result-snippet"[^>]*>([\s\S]*?)<\/td>/);
        if (linkMatch) {
          const title = linkMatch[1].replace(/<[^>]*>/g, '').replace(/&[^;]+;/g, ' ').trim();
          const snippet = snippetMatch ? snippetMatch[1].replace(/<[^>]*>/g, '').replace(/&[^;]+;/g, ' ').trim() : '';
          const key = title.toLowerCase().slice(0, 50);
          if (title && title.length > 2 && !seen.has(key)) {
            seen.add(key);
            results.push(`- ${title}${snippet ? `: ${snippet}` : ''}`);
          }
        }
      }
      if (results.length > 0) return results.join('\n');
    }
  } catch {}

  // Strategy 3: DuckDuckGo Instant Answer API (direct answers for queries like time, weather)
  try {
    const resp = await fetch(`https://api.duckduckgo.com/?q=${encodeURIComponent(query)}&format=json&skip_disambig=1`);
    if (resp.ok) {
      const data = await resp.json();
      if (data.AbstractText) return `- ${data.AbstractText}`;
      if (data.Answer) return `- ${data.Answer}`;
      if (data.Abstract) return `- ${data.Abstract}`;
      if (data.RelatedTopics?.length > 0) {
        return data.RelatedTopics.slice(0, 5).map(t => {
          const text = t.Text || (t.Result ? t.Result.replace(/<[^>]*>/g, '') : '');
          return text ? `- ${text}` : null;
        }).filter(Boolean).join('\n');
      }
    }
  } catch {}

  return null;
}

const WEB_SEARCH_TOOL = {
  type: 'function',
  function: {
    name: 'web_search',
    description: 'Search the internet for current, up-to-date information about any topic. Use this when you need recent news, live data, facts that may have changed, or any information beyond your training data.',
    parameters: {
      type: 'object',
      properties: {
        query: { type: 'string', description: 'The search query to look up on the internet' }
      },
      required: ['query']
    }
  }
};

function cleanResponse(text) {
  let clean = text
    .replace(/(?:powered\s+by|brought\s+to\s+you\s+by|sponsored\s+by|supported\s+by|in\s+partnership\s+with|provided\s+by)[^.\n]*/gi, '')
    .replace(/\b(pollinations\.ai|openrouter)\b[^.\n]*/gi, '')
    .replace(/\s*(?:based\s+on\s+(?:my|the|our)\s+(?:web\s+)?search\s*,?\s*|according\s+to\s+(?:my|the|our)\s+(?:web\s+)?(?:search|results?|findings?)\s*,?\s*|as\s+per\s+(?:my|the)\s+search\s*,?\s*|i\s+(?:searched|looked\s+up|checked|found|retrieved|gathered)\s+(?:online|the\s+web|information|data)\s*,?\s*|i\s+have\s+(?:access\s+to|retrieved|gathered)\s+(?:current|up-to-date|recent)\s+information\s*,?\s*|let\s+me\s+(?:search|look\s+up|check|find)\s+(?:that|this|online|the\s+web)\s*,?\s*|according\s+to\s+(?:my|the)\s+(?:internal\s+)?(?:system\s+)?(?:prompt|instructions?|guidelines?|configuration|knowledge)\s*,?\s*)/gi, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/\s{2,}/g, ' ')
    .trim();
  return clean || text.trim();
}

async function callOpenRouter(messages, env, tools) {
  if (!env.OPENROUTER_API_KEY) return null;
  const body = { messages, model: env.OPENROUTER_MODEL, max_tokens: 1536, temperature: 0.7 };
  if (tools) body.tools = tools;
  return fetch(`${env.OPENROUTER_BASE_URL}/chat/completions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${env.OPENROUTER_API_KEY}`, 'HTTP-Referer': 'https://ai.acronous.com', 'X-Title': 'Acronous AI' },
    body: JSON.stringify(body)
  }).then(async resp => {
    if (!resp.ok) return null;
    const data = await resp.json();
    return data?.choices?.[0]?.message || null;
  }).catch(() => null);
}

async function callOpenRouterWithTools(messages, env) {
  let msg = await callOpenRouter(messages, env, [WEB_SEARCH_TOOL]);
  if (!msg) return null;

  const msgs = [...messages];
  let loopCount = 0;
  while (msg.tool_calls?.length > 0 && loopCount < 3) {
    loopCount++;
    msgs.push({ role: 'assistant', content: msg.content || null, tool_calls: msg.tool_calls });

    for (const tc of msg.tool_calls) {
      if (tc.function.name === 'web_search') {
        let query = '';
        try { query = JSON.parse(tc.function.arguments).query || ''; } catch {}
        const results = await webSearch(query);
        msgs.push({ role: 'tool', tool_call_id: tc.id, content: results || 'No search results found for that query.' });
      }
    }

    msg = await callOpenRouter(msgs, env);
    if (!msg) return null;
  }

  return msg;
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
        const { tz, location } = await resolveUserGeo(request);

        const systemPrompt = buildSystemPrompt(tz, location);

        const messages = [
          { role: 'system', content: systemPrompt },
          ...history,
          { role: 'user', content: message }
        ];

        let content = null;

        if (env.OPENROUTER_API_KEY) {
          const msg = await callOpenRouterWithTools(messages, env);
          if (msg?.content) content = cleanResponse(msg.content);
        }

        if (!content) {
          const webContext = await webSearch(message);
          const fbSystemPrompt = buildSystemPrompt(tz, location, webContext);
          const fbMessages = [
            { role: 'system', content: fbSystemPrompt },
            ...history,
            { role: 'user', content: message }
          ];
          content = await tryPollinations(fbMessages);
        }

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
