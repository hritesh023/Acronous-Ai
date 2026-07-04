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

const TIME_KEYWORDS = /\b(time|date|today|tomorrow|yesterday|now|current|weather|news|latest|recent|update|forecast|clock|hour|minute)\b/i;

function formatLocalTime(tz) {
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

function buildSystemPrompt(tz, webContext) {
  const formatted = tz ? formatLocalTime(tz) : new Date().toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
  let prompt = `You are Acronous AI, a helpful assistant. Current date and time: ${formatted}.`;
  prompt += ` Respond in natural, conversational language. If the user asks for code or programming, provide the code clearly.`;
  prompt += ` Never include advertisements, sponsorships, promotional content, or mentions of any provider/platform.`;
  prompt += ` Never include phrases like "powered by", "brought to you by", "sponsored by", or any service attribution.`;
  if (webContext) prompt += ` Use this current information to answer: ${webContext}`;
  return prompt;
}

async function webSearch(query) {
  try {
    const resp = await fetch(`https://api.duckduckgo.com/?q=${encodeURIComponent(query)}&format=json&skip_disambig=1`);
    if (!resp.ok) return null;
    const data = await resp.json();
    if (data.AbstractText) return data.AbstractText;
    if (data.Answer) return data.Answer;
    if (data.Abstract) return data.Abstract;
    if (data.RelatedTopics?.length > 0) return data.RelatedTopics.slice(0, 3).map(t => t.Text || t.FirstURL).filter(Boolean).join(' | ');
    return null;
  } catch { return null; }
}

function cleanResponse(text) {
  return text
    .replace(/(?:powered\s+by|brought\s+to\s+you\s+by|sponsored\s+by|supported\s+by|in\s+partnership\s+with|provided\s+by)[^.\n]*/gi, '')
    .replace(/\b(pollinations\.ai|openrouter)\b[^.\n]*/gi, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

async function tryOpenRouter(message, env, systemPrompt) {
  if (!env.OPENROUTER_API_KEY) return null;
  try {
    const resp = await fetch(`${env.OPENROUTER_BASE_URL}/chat/completions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${env.OPENROUTER_API_KEY}`, 'HTTP-Referer': 'https://ai.acronous.com', 'X-Title': 'Acronous AI' },
      body: JSON.stringify({ messages: [{ role: 'system', content: systemPrompt }, { role: 'user', content: message }], model: env.OPENROUTER_MODEL, max_tokens: 800, temperature: 0.7 })
    });
    if (!resp.ok) return null;
    const data = await resp.json();
    const content = data?.choices?.[0]?.message?.content;
    return (content && content.trim()) ? cleanResponse(content) : null;
  } catch { return null; }
}

async function tryPollinations(message, systemPrompt) {
  try {
    const resp = await fetch('https://text.pollinations.ai', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: [{ role: 'system', content: systemPrompt }, { role: 'user', content: message }], model: 'openai', private: true })
    });
    if (!resp.ok) return null;
    const text = await resp.text();
    return (text && text.trim()) ? cleanResponse(text) : null;
  } catch { return null; }
}

async function tryHuggingFaceImage(prompt) {
  try {
    const resp = await fetch('https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ inputs: prompt })
    });
    if (!resp.ok) return null;
    const base64 = btoa(String.fromCharCode(...new Uint8Array(await resp.arrayBuffer())));
    return base64;
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

        const tz = await getUserTimezone(request);
        let webContext = null;
        if (TIME_KEYWORDS.test(message)) webContext = await webSearch(message);
        const systemPrompt = buildSystemPrompt(tz, webContext);

        let content = await tryOpenRouter(message, env, systemPrompt);
        if (!content) content = await tryPollinations(message, systemPrompt);
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

        let imageBase64 = await tryHuggingFaceImage(prompt);
        if (!imageBase64) imageBase64 = await tryPollinationsImage(prompt);
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
