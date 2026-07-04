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
  const now = new Date();
  const year = now.getFullYear();
  const formatted = formatLocalTime(tz) || now.toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
  let prompt = `You are Acronous AI, a helpful assistant with live internet access. Current date and time: ${formatted}.`;
  if (location) prompt += ` User's location: ${location}.`;
  prompt += ` Answer in natural, conversational language.`;
  prompt += `\n\nCRITICAL IMPORTANT: The current year is ${year}. Your training data has a knowledge cutoff and does NOT include recent events (especially recent elections, political changes, appointments, sports results, or scientific breakthroughs). You MUST treat any information older than ${year} as potentially outdated.`;
  if (webContext) {
    prompt += `\n\nACCURACY RULE — ABSOLUTE: Live web search results from ${formatted} are below. You are FORBIDDEN from using your internal training data for ANY factual claim that contradicts these results. You MUST answer based SOLELY on the search results below. If the results don't contain the answer, say "I don't have enough information" — do NOT guess, do NOT fall back to your training data. This is critical: your training data about who holds political office, election winners, and current events is months or years out of date.\n\nWeb results:\n${webContext}`;
  } else {
    prompt += `\n\nACCURACY RULE: No live web results are available. Only answer if you are highly confident in the accuracy of your training data. For any factual, political, or current-event question where you are not 100% certain, say "I don't have enough information to answer that accurately" instead of guessing. Never fabricate information.`;
  }
  prompt += `\n\nOUTPUT RULE — ABSOLUTE: Never output JSON, XML, YAML, or any structured data. Never wrap your response in code blocks unless the user explicitly asks for code. Never include your reasoning, thought process, internal steps, or search details. Never output objects with keys like "role", "content", "reasoning", "tool_calls". Respond ONLY in plain natural language — paragraphs or simple dash bullet points. This is critical: the user should never see JSON or code in your response.`;
  return prompt;
}

async function duckDuckGoSearch(q) {
  // Strategy A: DuckDuckGo HTML
  try {
    const resp = await fetch(`https://html.duckduckgo.com/html/?q=${encodeURIComponent(q)}`, {
      headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36' }
    });
    if (resp.ok) {
      const html = await resp.text();
      if (html.includes('result__a') || html.includes('result__snippet')) {
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
    }
  } catch {}

  // Strategy B: DuckDuckGo Lite
  try {
    const resp = await fetch(`https://lite.duckduckgo.com/lite/?q=${encodeURIComponent(q)}`, {
      headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36' }
    });
    if (resp.ok) {
      const html = await resp.text();
      if (html.includes('result-link')) {
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
    }
  } catch {}

  // Strategy C: DuckDuckGo Instant Answer API
  try {
    const resp = await fetch(`https://api.duckduckgo.com/?q=${encodeURIComponent(q)}&format=json&skip_disambig=1`);
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

async function bingSearch(q) {
  try {
    const resp = await fetch(`https://www.bing.com/search?q=${encodeURIComponent(q)}`, {
      headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36', 'Accept-Language': 'en-US,en;q=0.9' }
    });
    if (!resp.ok) return null;
    const html = await resp.text();
    if (!html.includes('b_algo')) return null;
    const results = [];
    const seen = new Set();
    const blocks = html.split('<li class="b_algo"');
    for (let i = 1; i < blocks.length && results.length < 5; i++) {
      const block = blocks[i];
      const titleMatch = block.match(/<a[^>]*href="https?:\/\/[^"]*"[^>]*>([\s\S]*?)<\/a>/i);
      const snippetMatch = block.match(/<p[^>]*class="b_lineclamp[^"]*"[^>]*>([\s\S]*?)<\/p>/i);
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
    return results.length > 0 ? results.join('\n') : null;
  } catch { return null; }
}

async function wikipediaSearch(query) {
  try {
    const searchResp = await fetch(`https://en.wikipedia.org/w/api.php?action=opensearch&search=${encodeURIComponent(query)}&limit=3&format=json`);
    if (!searchResp.ok) return null;
    const searchData = await searchResp.json();
    const titles = searchData[1];
    const descriptions = searchData[2];
    if (!titles || titles.length === 0) return null;

    const results = [];
    for (let i = 0; i < titles.length && results.length < 3; i++) {
      const pageResp = await fetch(`https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(titles[i])}`);
      if (pageResp.ok) {
        const page = await pageResp.json();
        if (page.extract) {
          const snippet = page.extract.replace(/\n+/g, ' ').slice(0, 300);
          results.push(`- ${page.title}: ${snippet}`);
        }
      }
    }
    return results.length > 0 ? results.join('\n') : null;
  } catch { return null; }
}

async function webSearch(query) {
  const currentYear = new Date().getFullYear();
  const queries = [query];
  const currentAffairsPattern = /\b(who is|current|present|now|today|recent|latest|what is the)\b/i;
  const leaderPattern = /\b(chief minister|prime minister|president|minister|chairman|ceo|governor|mayor|chancellor|king|queen|emperor|sultan)\b/i;
  if (currentAffairsPattern.test(query) || leaderPattern.test(query)) {
    queries.push(`${query} ${currentYear}`);
    queries.push(query.replace(currentAffairsPattern, '').trim() + ` ${currentYear}`);
  }

  for (const q of queries) {
    let result = await duckDuckGoSearch(q);
    if (result) return result;
    result = await bingSearch(q);
    if (result) return result;
  }

  const wikiResult = await wikipediaSearch(query);
  if (wikiResult) return wikiResult;

  return null;
}

function stripJsonLeak(text) {
  if (!text) return text;
  let c = text;
  c = c.replace(/\s*\{["\s]*(?:role|reasoning|tool_calls)["\s]*:[\s\S]*$/g, '');
  c = c.replace(/```(?:json)?[\s\S]*?```/g, '');
  c = c.replace(/[\s"'\}\]\)]+$/, '');
  return c.trim() || text;
}

function cleanResponse(text) {
  if (!text) return text;
  let clean = stripJsonLeak(text);
  clean = clean
    .replace(/(?:powered\s+by|brought\s+to\s+you\s+by|sponsored\s+by|supported\s+by|in\s+partnership\s+with|provided\s+by)[^.\n]*/gi, '')
    .replace(/\b(pollinations\.ai|openrouter)\b[^.\n]*/gi, '')
    .replace(/\s*(?:based\s+on\s+(?:my|the|our)\s+(?:web\s+)?search\s*,?\s*|according\s+to\s+(?:my|the|our)\s+(?:web\s+)?(?:search|results?|findings?)\s*,?\s*|as\s+per\s+(?:my|the)\s+search\s*,?\s*|i\s+(?:searched|looked\s+up|checked|found|retrieved|gathered)\s+(?:online|the\s+web|information|data)\s*,?\s*|i\s+have\s+(?:access\s+to|retrieved|gathered)\s+(?:current|up-to-date|recent)\s+information\s*,?\s*|let\s+me\s+(?:search|look\s+up|check|find)\s+(?:that|this|online|the\s+web)\s*,?\s*|according\s+to\s+(?:my|the)\s+(?:internal\s+)?(?:system\s+)?(?:prompt|instructions?|guidelines?|configuration|knowledge)\s*,?\s*)/gi, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/\s{2,}/g, ' ')
    .trim();
  if (!clean) return text.trim();

  // Safety net: if still looks like JSON, try to extract content
  if (/^\s*\{/.test(clean) && /"\w+"\s*:/.test(clean)) {
    try {
      const parsed = JSON.parse(clean);
      if (parsed.content) return parsed.content;
      if (parsed.answer) return parsed.answer;
    } catch {}
  }
  return clean;
}

async function callOpenRouter(messages, env) {
  if (!env.OPENROUTER_API_KEY) return null;
  const body = { messages, model: env.OPENROUTER_MODEL, max_tokens: 1536, temperature: 0.7 };
  return fetch(`${env.OPENROUTER_BASE_URL}/chat/completions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${env.OPENROUTER_API_KEY}`, 'HTTP-Referer': 'https://ai.acronous.com', 'X-Title': 'Acronous AI' },
    body: JSON.stringify(body)
  }).then(async resp => {
    if (!resp.ok) return null;
    const data = await resp.json();
    return data?.choices?.[0]?.message?.content || null;
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

function arrayBufferToBase64(buf) {
  let binary = '';
  const bytes = new Uint8Array(buf);
  const chunkSize = 8192;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}

async function tryPollinationsImage(prompt) {
  try {
    const resp = await fetch('https://image.pollinations.ai/prompt/' + encodeURIComponent(prompt) + '?width=1024&height=1024&nofeed=true');
    if (!resp.ok) return null;
    const base64 = arrayBufferToBase64(await resp.arrayBuffer());
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

        // Always proactively search the web for every query to ensure accuracy
        const webContext = await webSearch(message);
        const systemPrompt = buildSystemPrompt(tz, location, webContext);

        const messages = [
          { role: 'system', content: systemPrompt },
          ...history,
          { role: 'user', content: message }
        ];

        let content = null;

        if (env.OPENROUTER_API_KEY) {
          const raw = await callOpenRouter(messages, env);
          if (raw) content = cleanResponse(raw);
        }

        if (!content) {
          content = await tryPollinations(messages);
        }

        if (content) {
          content = content.trim();
        }

        if (!content || content === '') content = "I received your message. I'm having trouble generating a proper response right now. Please try again or rephrase your question.";

        return new Response(JSON.stringify({ response: content, session_id: sessionId, type: 'chat' }), { headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' } });
      } catch (error) {
        return new Response(JSON.stringify({ response: "I encountered an issue. Please try again in a moment." }), { status: 200, headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' } });
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
        return new Response(JSON.stringify({ response: "I encountered an issue generating the image. Please try again." }), { status: 200, headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' } });
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
