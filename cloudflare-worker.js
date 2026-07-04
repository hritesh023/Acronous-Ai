const PAGES_ORIGIN = 'https://acronous-ai.pages.dev';
const LANDING_WORKER = 'https://acronous-landing.workers.dev';

const LANDING_AUTH_PATHS = ['/api/auth/', '/login', '/login.html', '/signup', '/signup.html', '/dashboard', '/dashboard.html', '/logout'];

const SEARXNG_URLS = [
  'https://searx.be/search',
  'https://search.sapti.me/search',
  'https://searx.thegreenwebfoundation.org/search',
  'https://searx.tuxcloud.net/search',
  'https://searx.work/search',
  'https://searx.info/search',
  'https://search.mdosch.de/search',
  'https://northboot.xyz/search',
];

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
    return now.toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
  }
}

async function resolveUserGeo(request) {
  if (request.cf) {
    const tz = request.cf.timezone || null;
    const city = request.cf.city || '';
    const country = request.cf.country || '';
    const location = [city, country].filter(Boolean).join(', ') || null;
    if (tz || location) return { tz, location };
  }

  const ip = request.headers.get('CF-Connecting-IP') || request.headers.get('True-Client-IP');
  if (!ip) return { tz: null, location: null };

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
  prompt += `\n\nCRITICAL: The current year is ${year}. Your training data has a knowledge cutoff and does NOT include recent events (especially recent elections, political changes, appointments, sports results, or scientific breakthroughs). You MUST treat any information older than ${year} as potentially outdated.`;
  if (webContext) {
    prompt += `\n\nLive web search results from ${formatted} are below. Use these as your PRIMARY source for factual claims — they reflect current, up-to-date information. If the search results contain the answer, base your response on them. If the search results don't fully answer the question, combine them with your knowledge but clearly indicate what comes from search results vs your training data.\n\nWeb results:\n${webContext}`;
  } else {
    prompt += `\n\nNote: Live web search results are not available right now. Use your training data to answer, but be careful with highly time-sensitive topics. If you're uncertain about current information, you can say so, but don't overuse "I don't have enough information" — use your best knowledge and just note when you're unsure.`;
  }
  prompt += `\n\nOUTPUT RULE — ABSOLUTE: Never output JSON, XML, YAML, or any structured data. Never wrap your response in code blocks unless the user explicitly asks for code. Never include your reasoning, thought process, internal steps, or search details. Never output objects with keys like "role", "content", "reasoning", "tool_calls". Respond ONLY in plain natural language — paragraphs or simple dash bullet points. This is critical: the user should never see JSON or code in your response.`;
  return prompt;
}

async function searchSearxng(query) {
  for (const searxngUrl of SEARXNG_URLS) {
    try {
      const searchUrl = new URL(searxngUrl);
      searchUrl.searchParams.set('q', query);
      searchUrl.searchParams.set('format', 'json');
      searchUrl.searchParams.set('language', 'en');
      searchUrl.searchParams.set('pageno', '1');
      searchUrl.searchParams.set('categories', 'general');

      const response = await fetch(searchUrl.toString(), {
        headers: { 'Accept': 'application/json', 'User-Agent': 'Acronous-AI/1.0.0' },
        signal: AbortSignal.timeout(5000),
      });
      if (!response.ok) continue;

      const data = await response.json();
      const rawResults = data.results || [];
      if (rawResults.length === 0) continue;

      return rawResults.slice(0, 8).map(r => {
        const title = r.title || '';
        const content = r.content || r.snippet || '';
        return `- ${title}${content ? `: ${content}` : ''}`;
      }).filter(Boolean).join('\n');
    } catch { continue; }
  }
  return null;
}

async function duckDuckGoSearch(q) {
  try {
    const resp = await fetch(`https://html.duckduckgo.com/html/?q=${encodeURIComponent(q)}`, {
      headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36' },
      signal: AbortSignal.timeout(6000),
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

  try {
    const resp = await fetch(`https://lite.duckduckgo.com/lite/?q=${encodeURIComponent(q)}`, {
      headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36' },
      signal: AbortSignal.timeout(6000),
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

  try {
    const resp = await fetch(`https://api.duckduckgo.com/?q=${encodeURIComponent(q)}&format=json&skip_disambig=1`, {
      signal: AbortSignal.timeout(5000),
    });
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
      headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36', 'Accept-Language': 'en-US,en;q=0.9' },
      signal: AbortSignal.timeout(6000),
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
    let result = await searchSearxng(q);
    if (result) return result;
    result = await duckDuckGoSearch(q);
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

async function callOpenRouterVision(messages, env) {
  if (!env.OPENROUTER_API_KEY) return null;
  const models = [
    env.VISION_MODEL || 'google/gemini-2.5-flash-lite',
    env.FALLBACK_VISION_MODEL || 'nvidia/nemotron-nano-12b-v2-vl:free',
  ];
  for (const model of models) {
    try {
      const resp = await fetch(`${env.OPENROUTER_BASE_URL}/chat/completions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${env.OPENROUTER_API_KEY}`, 'HTTP-Referer': 'https://ai.acronous.com', 'X-Title': 'Acronous AI' },
        body: JSON.stringify({ model, messages, max_tokens: 2048, temperature: 0.3 })
      });
      if (resp.ok) {
        const data = await resp.json();
        const content = data?.choices?.[0]?.message?.content || null;
        if (content) return content;
      }
    } catch { continue; }
  }
  return null;
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

async function tryPollinationsImageEdit(imageBase64, prompt) {
  try {
    const resp = await fetch('https://image.pollinations.ai/prompt/' + encodeURIComponent(prompt), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt,
        img: imageBase64,
        width: 1024,
        height: 1024,
        nofeed: true,
      }),
    });
    if (!resp.ok) return null;
    return arrayBufferToBase64(await resp.arrayBuffer());
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

function jsonOk(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
  });
}

function jsonError(msg, status = 200) {
  return jsonOk({ response: msg, type: 'error' }, status);
}

async function handleMultipartVision(request, env, systemPrompt) {
  const formData = await request.formData();
  const file = formData.get('file');
  const message = formData.get('message') || 'Analyze this image.';
  const sessionId = formData.get('session_id') || 'default';
  const timezone = formData.get('timezone') || '';
  const location = formData.get('location') || '';
  const historyRaw = formData.get('messages') || '';

  if (!file) return jsonError('No image file provided.');

  const fileBytes = await file.arrayBuffer();
  const base64 = arrayBufferToBase64(fileBytes);
  const mimeType = file.type || 'image/jpeg';

  let history = [];
  if (historyRaw) {
    try { history = JSON.parse(historyRaw); } catch {}
  }

  const systemMsg = { role: 'system', content: systemPrompt };
  const userContent = [
    { type: 'text', text: message },
    { type: 'image_url', image_url: { url: `data:${mimeType};base64,${base64}` } },
  ];
  const visionMessages = [systemMsg, ...history, { role: 'user', content: userContent }];

  let content = await callOpenRouterVision(visionMessages, env);
  if (!content) {
    const fallbackMessages = [
      systemMsg,
      ...history,
      { role: 'user', content: `[Image attached] ${message}\n\nPlease analyze the image the user sent.` },
    ];
    content = await callOpenRouter(fallbackMessages, env);
  }
  if (!content) content = "I received your image. I'm having trouble analyzing it right now. Please try again.";

  return jsonOk({ response: cleanResponse(content), session_id: sessionId, type: 'chat' });
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

    if (path === '/v1/chat/image' && request.method === 'POST') {
      try {
        const formData = await request.formData();
        const file = formData.get('file');
        const message = formData.get('message') || '';
        const sessionId = formData.get('session_id') || 'default';
        const historyRaw = formData.get('messages') || '';

        if (!file) return jsonError('No image file provided.');

        const fileBytes = await file.arrayBuffer();
        const base64 = arrayBufferToBase64(fileBytes);
        const mimeType = file.type || 'image/jpeg';

        let history = [];
        if (historyRaw) {
          try { history = JSON.parse(historyRaw); } catch {}
        }

        const webContext = await webSearch(message);
        const systemPrompt = buildSystemPrompt(
          formData.get('timezone') || null,
          formData.get('location') || null,
          webContext
        );

        const userContent = [
          { type: 'text', text: message || 'What can you tell me about this image?' },
          { type: 'image_url', image_url: { url: `data:${mimeType};base64,${base64}` } },
        ];
        const visionMessages = [
          { role: 'system', content: systemPrompt },
          ...history,
          { role: 'user', content: userContent },
        ];

        let content = await callOpenRouterVision(visionMessages, env);
        if (!content) {
          const fallbackMessages = [
            { role: 'system', content: systemPrompt },
            ...history,
            { role: 'user', content: `${message}\n\n[The user attached an image for context]` },
          ];
          content = await callOpenRouter(fallbackMessages, env);
        }
        if (content) content = cleanResponse(content);
        if (!content || !content.trim()) content = "I received your image. I'm having trouble analyzing it right now. Please try again.";

        return jsonOk({ response: content, session_id: sessionId, type: 'chat' });
      } catch (error) {
        return jsonError("I encountered an issue processing your image. Please try again.");
      }
    }

    if (path === '/v1/chat/file' && request.method === 'POST') {
      try {
        const formData = await request.formData();
        const file = formData.get('file');
        const message = formData.get('message') || '';
        const sessionId = formData.get('session_id') || 'default';
        const historyRaw = formData.get('messages') || '';

        if (!file) return jsonError('No file provided.');

        const fileBytes = await file.arrayBuffer();
        const base64 = arrayBufferToBase64(fileBytes);
        const fileName = file.name || 'file';
        const mimeType = file.type || 'application/octet-stream';

        let history = [];
        if (historyRaw) {
          try { history = JSON.parse(historyRaw); } catch {}
        }

        const webContext = await webSearch(message);
        const systemPrompt = buildSystemPrompt(null, null, webContext);

        const llmPrompt = `The user uploaded a file named "${fileName}" (type: ${mimeType}). Their message: "${message}". Please analyze this file and respond helpfully. If it's a code file, review the code. If it's a document, summarize it.`;

        let userMsgContent;
        if (mimeType.startsWith('image/')) {
          userMsgContent = [
            { type: 'text', text: llmPrompt },
            { type: 'image_url', image_url: { url: `data:${mimeType};base64,${base64}` } },
          ];
        } else {
          const fileContent = new TextDecoder().decode(fileBytes).slice(0, 50000);
          userMsgContent = `${llmPrompt}\n\nFile contents:\n${fileContent}`;
        }

        const visionMessages = [
          { role: 'system', content: systemPrompt },
          ...history,
          { role: 'user', content: userMsgContent },
        ];

        let content = null;
        if (mimeType.startsWith('image/')) {
          content = await callOpenRouterVision(visionMessages, env);
        }
        if (!content) {
          const textMessages = [
            { role: 'system', content: systemPrompt },
            ...history,
            { role: 'user', content: typeof userMsgContent === 'string' ? userMsgContent : `${llmPrompt}\n\n[Image attached: ${fileName}]` },
          ];
          content = await callOpenRouter(textMessages, env);
        }
        if (content) content = cleanResponse(content);
        if (!content || !content.trim()) content = "I received your file. I'm having trouble processing it right now. Please try again.";

        return jsonOk({ response: content, session_id: sessionId, type: 'chat' });
      } catch (error) {
        return jsonError("I encountered an issue processing your file. Please try again.");
      }
    }

    if ((path === '/v1/image/generate' || path === '/api/image/generate') && request.method === 'POST') {
      try {
        const body = await request.json();
        const prompt = body.prompt || body.message || '';
        if (!prompt.trim()) {
          return jsonError('Please provide a description for the image.');
        }

        let imageBase64 = await tryPollinationsImage(prompt);
        if (!imageBase64) imageBase64 = await tryOpenRouterImage(prompt, env);
        if (!imageBase64) imageBase64 = await tryWorkersAI(prompt, env);

        if (imageBase64) {
          return jsonOk({ response: 'Generated image based on your request.', image_data: imageBase64, type: 'image_gen' });
        }

        return jsonError("I couldn't generate the image right now. Please try again with a different description.");
      } catch (error) {
        return jsonError("I encountered an issue generating the image. Please try again.");
      }
    }

    if (path === '/v1/image/edit' && request.method === 'POST') {
      try {
        const formData = await request.formData();
        const file = formData.get('file');
        const editPrompt = formData.get('message') || formData.get('prompt') || '';
        const sessionId = formData.get('session_id') || 'default';

        if (!file) return jsonError('No image file provided for editing.');
        if (!editPrompt.trim()) return jsonError('Please describe how you want to edit the image.');

        const fileBytes = await file.arrayBuffer();
        const imageBase64 = arrayBufferToBase64(fileBytes);

        let editedBase64 = await tryPollinationsImageEdit(imageBase64, editPrompt);
        if (!editedBase64 && env.AI) {
          try {
            const result = await env.AI.run('@cf/stabilityai/stable-diffusion-xl-base-1.0', {
              prompt: editPrompt,
              image: [...new Uint8Array(fileBytes)],
            });
            if (result?.image) editedBase64 = result.image;
          } catch {}
        }

        if (editedBase64) {
          return jsonOk({ response: 'Edited image based on your request.', image_data: editedBase64, type: 'image_gen', session_id: sessionId });
        }

        return jsonOk({
          response: "I wasn't able to edit the image directly. Let me analyze it and suggest what can be done.",
          session_id: sessionId,
          type: 'chat',
        });
      } catch (error) {
        return jsonError("I encountered an issue editing the image. Please try again.");
      }
    }

    if (path === '/api/image/analyze' && request.method === 'POST') {
      try {
        const formData = await request.formData();
        const file = formData.get('file');
        const sessionId = formData.get('session_id') || 'default';
        const analysisType = formData.get('analysis_type') || 'general';
        const historyRaw = formData.get('messages') || '';

        if (!file) return jsonError('No image file provided for analysis.');

        const fileBytes = await file.arrayBuffer();
        const base64 = arrayBufferToBase64(fileBytes);
        const mimeType = file.type || 'image/jpeg';

        let history = [];
        if (historyRaw) {
          try { history = JSON.parse(historyRaw); } catch {}
        }

        const analysisPrompts = {
          general: 'Analyze this image in detail. Describe what you see, including objects, people, text, colors, composition, and any notable details.',
          document: 'Analyze this document image. Extract and read any text content, describe the layout, and summarize the key information.',
          object: 'Identify and describe the main objects in this image. Provide details about their appearance, quantity, and arrangement.',
          text: 'Extract and read any text visible in this image. Preserve the original formatting and structure as much as possible.',
        };
        const analysisPrompt = analysisPrompts[analysisType] || analysisPrompts.general;

        const userContent = [
          { type: 'text', text: analysisPrompt },
          { type: 'image_url', image_url: { url: `data:${mimeType};base64,${base64}` } },
        ];
        const visionMessages = [
          { role: 'system', content: 'You are an AI image analysis assistant. Analyze images thoroughly and provide detailed, accurate descriptions.' },
          ...history,
          { role: 'user', content: userContent },
        ];

        let content = await callOpenRouterVision(visionMessages, env);
        if (!content) {
          const textMessages = [
            { role: 'system', content: 'You are an AI image analysis assistant.' },
            ...history,
            { role: 'user', content: `${analysisPrompt}\n\n[Image attached for analysis]` },
          ];
          content = await callOpenRouter(textMessages, env);
        }
        if (content) content = cleanResponse(content);
        if (!content || !content.trim()) content = "I wasn't able to analyze this image. Please try again with a clearer image.";

        return jsonOk({ response: content, session_id: sessionId, type: 'chat' });
      } catch (error) {
        return jsonError("I encountered an issue analyzing the image. Please try again.");
      }
    }

    if (path === '/api/tools/search' && request.method === 'POST') {
      try {
        const body = await request.json();
        const query = body.query || body.q || '';
        const maxResults = body.max_results || 5;
        if (!query.trim()) return jsonError('Please provide a search query.');

        const results = await webSearch(query);
        return jsonOk({ results: results || 'No results found.', query, type: 'search' });
      } catch (error) {
        return jsonError('Search failed. Please try again.');
      }
    }

    if (path === '/v1/chat/generate-natural-response' && request.method === 'POST') {
      try {
        const body = await request.json();
        const prompt = body.prompt || '';
        if (!prompt.trim()) return jsonError('Please provide a prompt.');

        const messages = [
          { role: 'system', content: 'Generate a natural, conversational response. Be concise and helpful. Never output JSON or structured data.' },
          { role: 'user', content: prompt },
        ];

        let content = null;
        if (env.OPENROUTER_API_KEY) {
          const raw = await callOpenRouter(messages, env);
          if (raw) content = cleanResponse(raw);
        }
        if (!content) content = await tryPollinations(messages);
        if (content) content = content.trim();
        if (!content) content = '';

        return jsonOk({ response: content, type: 'chat' });
      } catch (error) {
        return jsonError('Failed to generate response.');
      }
    }

    if (path === '/v1/wakeup' && request.method === 'GET') {
      return jsonOk({ status: 'ok' });
    }

    if (path === '/health' && request.method === 'GET') {
      return jsonOk({ status: 'ok', service: 'acronous-ai' });
    }

    if (isApiPath(path)) {
      return jsonOk({ error: 'Not found', message: 'The requested endpoint does not exist' }, 404);
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
