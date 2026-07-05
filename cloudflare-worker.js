const PAGES_ORIGIN = 'https://acronous-ai.pages.dev';
const LANDING_WORKER = 'https://acronous-landing.workers.dev';

const LANDING_AUTH_PATHS = ['/api/auth/', '/login', '/login.html', '/signup', '/signup.html', '/dashboard', '/dashboard.html', '/logout'];

const SEARXNG_URLS = [
  'https://searx.be/search', 'https://search.sapti.me/search',
  'https://searx.tuxcloud.net/search', 'https://searx.work/search',
  'https://searx.info/search', 'https://search.mdosch.de/search',
  'https://northboot.xyz/search', 'https://searx.raspipc.nl/search',
  'https://searx.roflcopter.fr/search', 'https://searx.xyz/search',
  'https://s.mble.dk/search', 'https://searx.tyil.nl/search',
  'https://searx.tiekoetter.com/search', 'https://searx.priv.au/search',
  'https://searx.fmac.xyz/search', 'https://searx.hu/search',
  'https://searx.no/search', 'https://searx.se/search',
  'https://searx.de/search', 'https://searx.mv/search',
];

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';

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
  const formatted = formatLocalTime(tz) || now.toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
  let prompt = `You are Acronous AI, a knowledgeable and capable assistant. Current date: ${formatted}.`;
  if (location) prompt += ` User location: ${location}.`;
  if (webContext) {
    prompt += `\n\nCurrent information:\n${webContext}`;
    prompt += `\n\nCRITICAL: Use the current information above to answer. If the answer is there, state it factually. If not, answer naturally from what you know. Never mention the information above or how you got it.`;
    prompt += `\n\nRules:\n- Speak naturally, confidently, and directly.\n- Never mention sources, references, "according to", "based on", "I found", "I searched", "my training", or "as an AI".\n- No JSON, no code blocks, no structured data.\n- Be concise and direct.`;
  } else {
    prompt += `\n\nRules:\n- Answer naturally, confidently, and directly.\n- Never mention sources, references, or how you know.\n- No JSON, no code blocks, no structured data.\n- Be concise and direct.`;
  }
  return prompt;
}

function stripHtml(html) {
  return html.replace(/<[^>]*>/g, '').replace(/&[^;]+;/g, ' ').trim();
}

function parseResults(items) {
  return items.slice(0, 5).map(r => {
    const title = r.title || '';
    const content = (r.content || r.snippet || '').slice(0, 200);
    return `- ${title}${content ? `: ${content}` : ''}`;
  }).filter(Boolean).join('\n');
}

const SEARXNG_SHUF = SEARXNG_URLS.sort(() => Math.random() - 0.5);

async function searchSearxng(query) {
  for (const url of SEARXNG_SHUF) {
    try {
      const u = new URL(url);
      u.searchParams.set('q', query);
      u.searchParams.set('format', 'json');
      u.searchParams.set('language', 'en');
      u.searchParams.set('pageno', '1');
      u.searchParams.set('categories', 'general');
      const resp = await fetch(u.toString(), {
        headers: { 'Accept': 'application/json', 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' },
        signal: AbortSignal.timeout(4000),
      });
      if (!resp.ok) continue;
      const data = await resp.json();
      const raw = data.results || [];
      if (raw.length === 0) continue;
      const items = parseResults(raw);
      if (!items) continue;
      return items.length > 3000 ? items.slice(0, 3000) : items;
    } catch {}
  }
  return null;
}

async function duckDuckGoSearch(query) {
  const strategies = [
    async () => {
      const resp = await fetch(`https://html.duckduckgo.com/html/?q=${encodeURIComponent(query)}`, {
        headers: { 'User-Agent': UA, 'Accept': 'text/html', 'Accept-Language': 'en-US,en;q=0.9' },
        signal: AbortSignal.timeout(8000),
      });
      if (!resp.ok) return null;
      const html = await resp.text();
      const results = []; const seen = new Set();
      const blocks = html.split('<a rel="nofollow" class="result__a"');
      for (let i = 1; i < blocks.length && results.length < 5; i++) {
        const b = blocks[i];
        const t = b.match(/<a[^>]*class="result__a"[^>]*>([\s\S]*?)<\/a>/);
        const s = b.match(/class="result__snippet"[^>]*>([\s\S]*?)<\/a>/);
        if (t) {
          const title = stripHtml(t[1]); const snippet = s ? stripHtml(s[1]) : '';
          const key = title.toLowerCase().slice(0, 50);
          if (title && title.length > 2 && !seen.has(key)) { seen.add(key); results.push(`- ${title}${snippet ? `: ${snippet}` : ''}`); }
        }
      }
      return results.length > 0 ? results.join('\n') : null;
    },
    async () => {
      const resp = await fetch(`https://lite.duckduckgo.com/lite/?q=${encodeURIComponent(query)}`, {
        headers: { 'User-Agent': UA },       signal: AbortSignal.timeout(8000),
      });
      if (!resp.ok) return null;
      const html = await resp.text();
      const results = []; const seen = new Set();
      const rows = html.split('<tr class="result">');
      for (let i = 1; i < rows.length && results.length < 5; i++) {
        const row = rows[i];
        const link = row.match(/<a[^>]*class="result-link"[^>]*>([\s\S]*?)<\/a>/);
        const snip = row.match(/<td[^>]*class="result-snippet"[^>]*>([\s\S]*?)<\/td>/);
        if (link) {
          const title = stripHtml(link[1]); const snippet = snip ? stripHtml(snip[1]) : '';
          const key = title.toLowerCase().slice(0, 50);
          if (title && title.length > 2 && !seen.has(key)) { seen.add(key); results.push(`- ${title}${snippet ? `: ${snippet}` : ''}`); }
        }
      }
      return results.length > 0 ? results.join('\n') : null;
    },
    async () => {
      const resp = await fetch(`https://api.duckduckgo.com/?q=${encodeURIComponent(query)}&format=json&no_html=1&skip_disambig=1`, {
        headers: { 'User-Agent': UA }, signal: AbortSignal.timeout(7000),
      });
      if (!resp.ok) return null;
      const data = await resp.json();
      if (data.AbstractText) return `- ${data.AbstractText}`;
      if (data.Answer) return `- ${data.Answer}`;
      if (data.RelatedTopics?.length > 0) {
        return data.RelatedTopics.slice(0, 5).map(t => {
          const text = t.Text || (t.Result ? stripHtml(t.Result) : '');
          return text ? `- ${text}` : null;
        }).filter(Boolean).join('\n');
      }
      return null;
    },
    async () => {
      const form = new FormData();
      form.append('q', query);
      const resp = await fetch('https://html.duckduckgo.com/html/', {
        method: 'POST', body: form,
        headers: { 'User-Agent': UA },
        signal: AbortSignal.timeout(5000),
      });
      if (!resp.ok) return null;
      const html = await resp.text();
      const results = []; const seen = new Set();
      const blocks = html.split('<a rel="nofollow" class="result__a"');
      for (let i = 1; i < blocks.length && results.length < 5; i++) {
        const b = blocks[i];
        const t = b.match(/<a[^>]*class="result__a"[^>]*>([\s\S]*?)<\/a>/);
        const s = b.match(/class="result__snippet"[^>]*>([\s\S]*?)<\/a>/);
        if (t) {
          const title = stripHtml(t[1]); const snippet = s ? stripHtml(s[1]) : '';
          const key = title.toLowerCase().slice(0, 50);
          if (title && title.length > 2 && !seen.has(key)) { seen.add(key); results.push(`- ${title}${snippet ? `: ${snippet}` : ''}`); }
        }
      }
      return results.length > 0 ? results.join('\n') : null;
    },
  ];
  const results = await Promise.allSettled(strategies.map(fn => fn()));
  for (const r of results) {
    if (r.status === 'fulfilled' && r.value) return r.value;
  }
  return null;
}

async function bingSearch(query) {
  try {
    const resp = await fetch(`https://www.bing.com/search?q=${encodeURIComponent(query)}`, {
      headers: { 'User-Agent': UA, 'Accept-Language': 'en-US,en;q=0.9' },
      signal: AbortSignal.timeout(8000),
      });
      if (!resp.ok) return null;
      const html = await resp.text();
      if (!html.includes('b_algo')) return null;
    const results = []; const seen = new Set();
    const blocks = html.split('<li class="b_algo"');
    for (let i = 1; i < blocks.length && results.length < 5; i++) {
      const b = blocks[i];
      const t = b.match(/<a[^>]*href="https?:\/\/[^"]*"[^>]*>([\s\S]*?)<\/a>/i);
      const s = b.match(/<p[^>]*class="b_lineclamp[^"]*"[^>]*>([\s\S]*?)<\/p>/i);
      if (t) {
        const title = stripHtml(t[1]); const snippet = s ? stripHtml(s[1]) : '';
        const key = title.toLowerCase().slice(0, 50);
        if (title && title.length > 2 && !seen.has(key)) { seen.add(key); results.push(`- ${title}${snippet ? `: ${snippet}` : ''}`); }
      }
    }
    return results.length > 0 ? results.join('\n') : null;
  } catch { return null; }
}

async function googleSearch(query) {
  try {
    const resp = await fetch(`https://www.google.com/search?q=${encodeURIComponent(query)}&hl=en`, {
      headers: { 'User-Agent': UA, 'Accept-Language': 'en-US,en;q=0.9' },
      signal: AbortSignal.timeout(8000),
    });
    if (!resp.ok) return null;
    const html = await resp.text();
    const results = []; const seen = new Set();
    const blocks = html.split('<div class="g"');
    for (let i = 1; i < blocks.length && results.length < 4; i++) {
      const b = blocks[i];
      const t = b.match(/<h3[^>]*>([\s\S]*?)<\/h3>/);
      const s = b.match(/<div[^>]*class="[^"]*VwiC3b[^"]*"[^>]*>([\s\S]*?)<\/div>/);
      if (t) {
        const title = stripHtml(t[1]); const snippet = s ? stripHtml(s[1]) : '';
        const key = title.toLowerCase().slice(0, 50);
        if (title && title.length > 2 && !seen.has(key)) { seen.add(key); results.push(`- ${title}${snippet ? `: ${snippet}` : ''}`); }
      }
    }
    if (results.length === 0) {
      const altBlocks = html.split('<div class="g "');
      for (let i = 1; i < altBlocks.length && results.length < 4; i++) {
        const b = altBlocks[i];
        const t = b.match(/<h3[^>]*>([\s\S]*?)<\/h3>/);
        const s = b.match(/<div[^>]*style="[^"]*"[^>]*>([\s\S]*?)<\/div>/);
        if (t) {
          const title = stripHtml(t[1]); const snippet = s ? stripHtml(s[1]) : '';
          const key = title.toLowerCase().slice(0, 50);
          if (title && title.length > 2 && !seen.has(key)) { seen.add(key); results.push(`- ${title}${snippet ? `: ${snippet}` : ''}`); }
        }
      }
    }
    return results.length > 0 ? results.join('\n') : null;
  } catch { return null; }
}

async function googleNewsSearch(query) {
  try {
    const resp = await fetch(`https://news.google.com/search?q=${encodeURIComponent(query)}&hl=en-IN&gl=IN`, {
      headers: { 'User-Agent': UA, 'Accept-Language': 'en-US,en;q=0.9' },
      signal: AbortSignal.timeout(6000),
    });
    if (!resp.ok) return null;
    const html = await resp.text();
    const results = []; const seen = new Set();
    const blocks = html.split('<article');
    for (let i = 1; i < blocks.length && results.length < 5; i++) {
      const b = blocks[i];
      const t = b.match(/<a[^>]*>([\s\S]*?)<\/a>/);
      const s = b.match(/<p[^>]*class="[^"]*"[^>]*>([\s\S]*?)<\/p>/i);
      if (t) {
        const title = stripHtml(t[1]); const snippet = s ? stripHtml(s[1]) : '';
        const key = title.toLowerCase().slice(0, 50);
        if (title && title.length > 3 && !seen.has(key)) { seen.add(key); results.push(`- ${title}${snippet ? `: ${snippet}` : ''}`); }
      }
    }
    return results.length > 0 ? results.join('\n') : null;
  } catch { return null; }
}

async function mojeekSearch(query) {
  try {
    const resp = await fetch(`https://www.mojeek.com/search?q=${encodeURIComponent(query)}`, {
      headers: { 'User-Agent': UA },       signal: AbortSignal.timeout(8000),
    });
    if (!resp.ok) return null;
    const html = await resp.text();
    const results = []; const seen = new Set();
    const blocks = html.split('<div class="results-standard');
    for (let i = 1; i < blocks.length && results.length < 4; i++) {
      const b = blocks[i];
      const t = b.match(/<h2[^>]*class="[^"]*title[^"]*"[^>]*>([\s\S]*?)<\/h2>/);
      const s = b.match(/<p[^>]*class="[^"]*snippet[^"]*"[^>]*>([\s\S]*?)<\/p>/);
      if (t) {
        const title = stripHtml(t[1]); const snippet = s ? stripHtml(s[1]) : '';
        const key = title.toLowerCase().slice(0, 50);
        if (title && title.length > 2 && !seen.has(key)) { seen.add(key); results.push(`- ${title}${snippet ? `: ${snippet}` : ''}`); }
      }
    }
    return results.length > 0 ? results.join('\n') : null;
  } catch { return null; }
}

async function wikipediaSearch(query) {
  try {
    const sr = await fetch(`https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch=${encodeURIComponent(query)}&format=json&srlimit=5&srprop=snippet`, { signal: AbortSignal.timeout(5000), headers: { 'User-Agent': 'AcronousAI/2.0' } });
    if (!sr.ok) return null;
    const sd = await sr.json();
    const titles = sd?.query?.search?.map(s => s.title) || [];
    if (titles.length === 0) return null;
    const results = [];
    for (let i = 0; i < titles.length && results.length < 5; i++) {
      const pr = await fetch(`https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(titles[i])}`, { signal: AbortSignal.timeout(4000), headers: { 'User-Agent': 'AcronousAI/2.0' } });
      if (pr.ok) {
        const page = await pr.json();
        if (page.extract) results.push(`- ${page.title}: ${page.extract.replace(/\n+/g, ' ').slice(0, 500)}`);
      }
    }
    return results.length > 0 ? results.join('\n') : null;
  } catch { return null; }
}

async function guardianSearch(query) {
  try {
    const resp = await fetch(`https://content.guardianapis.com/search?q=${encodeURIComponent(query)}&api-key=test&page-size=5&show-fields=headline,trailText&order-by=relevance`);
    if (!resp.ok) return null;
    const data = await resp.json();
    const results = data?.response?.results || [];
    if (results.length === 0) return null;
    return results.map(r => `- ${r.webTitle}${r.fields?.trailText ? `: ${stripHtml(r.fields.trailText).slice(0, 200)}` : ''}`).join('\n');
  } catch { return null; }
}

async function redditSearch(query) {
  try {
    const resp = await fetch(`https://www.reddit.com/search.json?q=${encodeURIComponent(query)}&limit=5&sort=new&t=year`, {
      headers: { 'User-Agent': 'Acronous-AI/2.0 (by /u/acronous)' },
      signal: AbortSignal.timeout(5000),
    });
    if (!resp.ok) return null;
    const data = await resp.json();
    const children = data?.data?.children || [];
    if (children.length === 0) return null;
    return children.map(c => {
      const d = c.data || {};
      const title = d.title || '';
      const selftext = (d.selftext || '').slice(0, 200);
      return `- ${title}${selftext ? `: ${selftext}` : ''}`;
    }).filter(Boolean).join('\n');
  } catch { return null; }
}

async function hackerNewsSearch(query) {
  try {
    const resp = await fetch(`https://hn.algolia.com/api/v1/search?query=${encodeURIComponent(query)}&hitsPerPage=5&tags=story`);
    if (!resp.ok) return null;
    const data = await resp.json();
    const hits = data?.hits || [];
    if (hits.length === 0) return null;
    return hits.map(h => `- ${h.title}`).join('\n');
  } catch { return null; }
}

const DDG_UA = 'Mozilla/5.0 (compatible; AcronousAI/2.0)';

async function duckDuckGoApi(query) {
  const strategies = [
    async () => {
      const resp = await fetch(`https://api.duckduckgo.com/?q=${encodeURIComponent(query)}&format=json&no_html=1&skip_disambig=1`, {
        headers: { 'User-Agent': DDG_UA }, signal: AbortSignal.timeout(5000),
      });
      if (!resp.ok) return null;
      const data = await resp.json();
      const parts = [];
      if (data.AbstractText) parts.push(`- ${data.AbstractText}`);
      if (data.Answer) parts.push(`- ${data.Answer}`);
      if (data.RelatedTopics?.length > 0) {
        data.RelatedTopics.slice(0, 5).forEach(t => {
          const text = t.Text || (t.Result ? stripHtml(t.Result) : '');
          if (text) parts.push(`- ${text}`);
          if (t.Topics) t.Topics.slice(0, 3).forEach(st => {
            if (st.Text) parts.push(`- ${st.Text}`);
          });
        });
      }
      if (data.Infobox?.content) {
        data.Infobox.content.slice(0, 5).forEach(c => {
          if (c.value) parts.push(`- ${c.value}`);
        });
      }
      return parts.length > 0 ? parts.join('\n') : null;
    },
    async () => {
      const resp = await fetch(`https://lite.duckduckgo.com/lite/?q=${encodeURIComponent(query)}`, {
        headers: { 'User-Agent': DDG_UA }, signal: AbortSignal.timeout(6000),
      });
      if (!resp.ok) return null;
      const html = await resp.text();
      const results = []; const seen = new Set();
      const rows = html.split('<tr class="result">');
      for (let i = 1; i < rows.length && results.length < 5; i++) {
        const row = rows[i];
        const link = row.match(/<a[^>]*class="result-link"[^>]*>([\s\S]*?)<\/a>/);
        const snip = row.match(/<td[^>]*class="result-snippet"[^>]*>([\s\S]*?)<\/td>/);
        if (link) {
          const title = stripHtml(link[1]); const snippet = snip ? stripHtml(snip[1]) : '';
          const key = title.toLowerCase().slice(0, 50);
          if (title && title.length > 2 && !seen.has(key)) { seen.add(key); results.push(`- ${title}${snippet ? `: ${snippet}` : ''}`); }
        }
      }
      return results.length > 0 ? results.join('\n') : null;
    },
  ];
  for (const fn of strategies) {
    const r = await fn();
    if (r) return r;
  }
  return null;
}

async function googleSearchApi(query, env) {
  if (!env.GOOGLE_API_KEY || !env.GOOGLE_CX) return null;
  try {
    const resp = await fetch(`https://www.googleapis.com/customsearch/v1?key=${env.GOOGLE_API_KEY}&cx=${env.GOOGLE_CX}&q=${encodeURIComponent(query)}&num=5`);
    if (!resp.ok) return null;
    const data = await resp.json();
    const items = data?.items || [];
    if (items.length === 0) return null;
    return items.map(i => `- ${i.title}${i.snippet ? `: ${i.snippet.slice(0, 200)}` : ''}`).join('\n');
  } catch { return null; }
}

async function googleNewsRssSearch(query) {
  try {
    const resp = await fetch(`https://news.google.com/rss/search?q=${encodeURIComponent(query)}&hl=en&gl=US&ceid=US:en`, {
      headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36' },
      signal: AbortSignal.timeout(6000),
    });
    if (!resp.ok) return null;
    const xml = await resp.text();
    const items = xml.match(/<item>[\s\S]*?<\/item>/g);
    if (!items) return null;
    const results = []; const seen = new Set();
    for (const item of items.slice(0, 5)) {
      const t = item.match(/<title>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?<\/title>/);
      const s = item.match(/<description>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?<\/description>/);
      if (t) {
        const title = stripHtml(t[1]).trim();
        const snippet = s ? stripHtml(s[1]).trim().slice(0, 200) : '';
        const key = title.toLowerCase().slice(0, 50);
        if (title && title.length > 3 && !seen.has(key)) { seen.add(key); results.push(`- ${title}${snippet ? `: ${snippet}` : ''}`); }
      }
    }
    return results.length > 0 ? results.join('\n') : null;
  } catch { return null; }
}

async function tryAllEngines(query, env) {
  const results = await Promise.allSettled([
    wikipediaSearch(query),
    duckDuckGoApi(query),
    searchSearxng(query),
  ]);
  for (const r of results) {
    if (r.status === 'fulfilled' && r.value) return r.value;
  }

  const slowEngines = [googleSearchApi, hackerNewsSearch, guardianSearch, googleNewsRssSearch, googleSearch, bingSearch];
  for (const fn of slowEngines) {
    const r = await fn(query, env);
    if (r) return r;
  }
  return null;
}

async function webSearch(query, env = {}) {
  const q = query.trim();
  const year = new Date().getFullYear();

  const queries = [q, `${q} ${year}`, `${q} latest`];
  const stripped = q.replace(/^(who is|what is|tell me about|do you know|can you tell me|i want to know about|describe|explain)\b/i, '').trim();
  if (stripped && stripped !== q && !queries.includes(stripped)) queries.push(stripped);

  for (const qi of queries.slice(0, 3)) {
    const result = await tryAllEngines(qi, env);
    if (result) return result;
  }

  return null;
}

function isInfoQuery(message) {
  const m = message.trim();
  if (!m) return false;
  // Question words at start
  if (/^(who|what|when|where|why|how|which|is|are|was|were|do|does|did|has|have|had|can|could|will|would|shall|should)\b/i.test(m)) return true;
  // Ends with question mark
  if (m.endsWith('?')) return true;
  // Information-seeking phrases
  if (/\b(current|latest|recent|update|tell me|i want to know|do you know|what is|who is|where is|when is|how to|how do|define|meaning|explain|describe|what are|what was)\b/i.test(m)) return true;
  // Factual topics
  if (/\b(chief minister|president|prime minister|governor|mayor|minister|population|capital|currency|weather|time|date|news|election|winner|score|price|rate|cost|history|origin|founder|ceo|chairman|spokesperson)\b/i.test(m)) return true;
  return false;
}

function stripJsonLeak(text) {
  if (!text) return text;
  let c = text;
  c = c.replace(/\s*\{["\s]*(?:role|reasoning|tool_calls)["\s]*:[\s\S]*$/g, '');
  c = c.replace(/```(?:json)?[\s\S]*?```/g, '');
  if (!c.trim()) return '';
  c = c.replace(/[\s"'\}\]\)]+$/, '');
  return c.trim();
}

function cleanResponse(text) {
  if (!text) return '';
  let clean = stripJsonLeak(text);
  if (!clean) return '';
  clean = clean
    .replace(/(?:powered\s+by|brought\s+to\s+you\s+by|sponsored\s+by|supported\s+by|in\s+partnership\s+with|provided\s+by)[^.\n]*/gi, '')
    .replace(/\b(pollinations\.ai|openrouter)\b[^.\n]*/gi, '')
    .replace(/\s*(?:based\s+on\s+(?:my|the|our)\s+(?:web\s+)?search\s*,?\s*|according\s+to\s+(?:my|the|our)\s+(?:web\s+)?(?:search|results?|findings?)\s*,?\s*|as\s+per\s+(?:my|the)\s+search\s*,?\s*|i\s+(?:searched|looked\s+up|checked|found|retrieved|gathered)\s+(?:online|the\s+web|information|data)\s*,?\s*|i\s+have\s+(?:access\s+to|retrieved|gathered)\s+(?:current|up-to-date|recent)\s+information\s*,?\s*|let\s+me\s+(?:search|look\s+up|check|find)\s+(?:that|this|online|the\s+web)\s*,?\s*|according\s+to\s+(?:my|the)\s+(?:internal\s+)?(?:system\s+)?(?:prompt|instructions?|guidelines?|configuration|knowledge)\s*,?\s*)/gi, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/\s{2,}/g, ' ')
    .trim();

  if (clean.length < 3 && (/^\s*\{/.test(clean) || /^\s*\[/.test(clean))) return '';

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
  const models = [
    env.OPENROUTER_MODEL || 'meta-llama/llama-3.3-70b-instruct:free',
    'deepseek/deepseek-chat:free',
    'google/gemini-2.5-flash-lite-preview-02-15:free',
  ];
  for (const model of models) {
    for (let retry = 0; retry < 2; retry++) {
      try {
        const resp = await fetch(`${env.OPENROUTER_BASE_URL}/chat/completions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${env.OPENROUTER_API_KEY}`, 'HTTP-Referer': 'https://ai.acronous.com', 'X-Title': 'Acronous AI' },
          body: JSON.stringify({ messages, model, max_tokens: 2048, temperature: 0.7 })
        });
        if (resp.ok) {
          const data = await resp.json();
          const content = cleanResponse(data?.choices?.[0]?.message?.content);
          if (content && content.trim()) return content;
        }
        if (resp.status === 429) {
          await new Promise(r => setTimeout(r, 1200));
        }
      } catch { continue; }
    }
  }
  return null;
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
        const content = data?.choices?.[0]?.message?.content;
        if (content && content.trim()) return content;
      }
    } catch { continue; }
  }
  return null;
}

async function tryWorkersAIChat(messages, env) {
  if (!env.AI) return null;
  const models = [
    '@cf/meta/llama-4-scout-17b-16e-instruct',
    '@cf/meta/llama-3.3-70b-instruct-fp8-fast',
    '@cf/meta/llama-3.2-3b-instruct',
  ];
  for (const name of models) {
    try {
      const result = await env.AI.run(name, { messages, max_tokens: 1024 });
      if (result && typeof result === 'object') {
        const text = cleanResponse(result.response || '');
        if (text.trim()) return text;
      }
    } catch { continue; }
  }
  return null;
}

async function tryPollinations(messages, env) {
  const pollModels = ['openai', 'mistral', 'llama', 'deepseek', 'qwen-coder'];
  for (const model of pollModels) {
    for (let retry = 0; retry < 2; retry++) {
      try {
        const resp = await fetch('https://text.pollinations.ai', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ messages, model, private: true, seed: Math.floor(Math.random() * 10000) })
        });
        if (resp.ok) {
          const text = await resp.text();
          const trimmed = text?.trim();
          if (trimmed) return cleanResponse(trimmed);
        } else if (resp.status === 429) {
          await new Promise(r => setTimeout(r, 500 * (retry + 1)));
        }
      } catch { continue; }
    }
  }
  return null;
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

async function tryBetterPollinationsEdit(imageBase64, editPrompt, imageDescription) {
  // Build a more detailed prompt based on what we know about the image
  const contextDesc = imageDescription ? `Original image: ${imageDescription}. ` : '';
  const enhancedPrompt = `${contextDesc}${editPrompt}. High quality, photorealistic, detailed. Keep everything else identical.`;
  
  try {
    const resp = await fetch('https://image.pollinations.ai/prompt/' + encodeURIComponent(enhancedPrompt), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt: enhancedPrompt,
        img: imageBase64,
        width: 1024,
        height: 1024,
        nofeed: true,
        model: 'turbo', // use better model if available
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

async function tryWorkersAIEdit(imageBytes, editPrompt, env) {
  // Use Workers AI with image input for editing (img2img)
  if (!env.AI) return null;
  try {
    // Try SDXL with image input (img2img/inpainting)
    const result = await env.AI.run('@cf/stabilityai/stable-diffusion-xl-base-1.0', {
      prompt: editPrompt,
      image: [...new Uint8Array(imageBytes)],
      strength: 0.85, // how much to transform
      guidance_scale: 7.5,
    });
    if (result?.image) return result.image;
    return null;
  } catch { return null; }
}

async function tryEditorService(imageBytes, editPrompt, env) {
  // Call the Python image editing microservice
  const serviceUrl = env.EDITOR_SERVICE_URL;
  if (!serviceUrl) return null;
  
  try {
    const formData = new FormData();
    formData.append('file', new Blob([imageBytes], { type: 'image/jpeg' }), 'image.jpg');
    formData.append('prompt', editPrompt);

    const resp = await fetch(`${serviceUrl}/edit`, {
      method: 'POST',
      body: formData,
    });
    if (!resp.ok) return null;

    const data = await resp.json();
    if (data?.edited) return data.edited;
    return null;
  } catch { return null; }
}

async function analyzeImageWithVision(imageBase64, mimeType, editPrompt, env) {
  // Use vision model to describe the image for better edit prompts
  if (!env.OPENROUTER_API_KEY) return null;
  try {
    const userContent = [
      { type: 'text', text: `Describe this image in detail. Focus on the subject, their clothing/attire, background, colors, and composition. The user wants to edit it: "${editPrompt}"` },
      { type: 'image_url', image_url: { url: `data:${mimeType};base64,${imageBase64}` } },
    ];
    const messages = [
      { role: 'system', content: 'You are an image analysis assistant. Describe images in detail for editing purposes.' },
      { role: 'user', content: userContent },
    ];

    const model = env.VISION_MODEL || 'google/gemini-2.5-flash-lite';
    const resp = await fetch(`${env.OPENROUTER_BASE_URL}/chat/completions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${env.OPENROUTER_API_KEY}`, 'HTTP-Referer': 'https://ai.acronous.com', 'X-Title': 'Acronous AI' },
      body: JSON.stringify({ model, messages, max_tokens: 1024, temperature: 0.3 })
    });
    if (!resp.ok) return null;
    const data = await resp.json();
    return data?.choices?.[0]?.message?.content || null;
  } catch { return null; }
}

async function craftEditPrompt(imageDescription, editPrompt) {
  // Use LLM to craft an optimal edit prompt based on image description
  if (!imageDescription) return editPrompt;
  try {
    const messages = [
      { role: 'system', content: 'You craft precise image editing prompts. Given an image description and an edit request, create a detailed prompt for an AI image editor. The prompt should specify exactly what to change while preserving everything else. Be specific about colors, styles, and placement. Output ONLY the prompt, nothing else.' },
      { role: 'user', content: `Image: ${imageDescription}\nEdit request: ${editPrompt}\n\nCreate a detailed edit prompt:` }
    ];
    // Use pollinations for this since it's free
    const resp = await fetch('https://text.pollinations.ai', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages, model: 'openai', private: true })
    });
    if (!resp.ok) return editPrompt;
    const text = await resp.text();
    const trimmed = text?.trim();
    return trimmed || editPrompt;
  } catch { return editPrompt; }
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
  if (!content || !content.trim()) {
    const now = new Date();
    content = `${now.toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}`;
  }

  return jsonOk({ response: content, session_id: sessionId, type: 'chat' });
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
        const message = (body.message || '').trim();
        if (!message) return jsonError('Please provide a message.');
        const sessionId = body.session_id || 'default';
        let history = body.messages || [];
        if (history.length > 20) history = history.slice(-20);
        const { tz, location } = await resolveUserGeo(request);

        let content = null;
        let webData = null;

        const sysPromptNoWeb = buildSystemPrompt(tz, location, null);
        const baseMsgs = [
          { role: 'system', content: sysPromptNoWeb },
          ...history,
          { role: 'user', content: message }
        ];

        // Run web search in parallel with LLM for all queries
        const [webResult, ...llmResults] = await Promise.allSettled([
          webSearch(message, env),
          env.OPENROUTER_API_KEY ? callOpenRouter(baseMsgs, env) : Promise.resolve(null),
          tryPollinations(baseMsgs, env),
          tryWorkersAIChat(baseMsgs, env),
        ]);
        webData = webResult.status === 'fulfilled' ? webResult.value : null;
        for (const r of llmResults) {
          if (r.status === 'fulfilled' && r.value && r.value.trim()) {
            content = r.value;
            break;
          }
        }

        // If LLM responded but web data is available, regenerate with web context
        if (content && webData) {
          const sysPrompt = buildSystemPrompt(tz, location, webData);
          const msgs = [
            { role: 'system', content: sysPrompt },
            ...history,
            { role: 'user', content: message }
          ];
          const providers = [
            env.OPENROUTER_API_KEY ? callOpenRouter(msgs, env) : Promise.resolve(null),
            tryPollinations(msgs, env),
            tryWorkersAIChat(msgs, env),
          ];
          const results = await Promise.allSettled(providers);
          for (const r of results) {
            if (r.status === 'fulfilled' && r.value && r.value.trim()) {
              content = r.value;
              break;
            }
          }
        }

        // Fallback: if no content yet, try LLM without web
        if (!content || !content.trim()) {
          const fallbackMsgs = [
            { role: 'system', content: sysPromptNoWeb },
            ...history,
            { role: 'user', content: message }
          ];
          const providers = [
            tryPollinations(fallbackMsgs, env),
            tryWorkersAIChat(fallbackMsgs, env),
            env.OPENROUTER_API_KEY ? callOpenRouter(fallbackMsgs, env) : Promise.resolve(null),
          ];
          const results = await Promise.allSettled(providers);
          for (const r of results) {
            if (r.status === 'fulfilled' && r.value && r.value.trim()) {
              content = r.value;
              break;
            }
          }
        }

        if (content) content = content.trim();
        if (!content) content = '';

        return jsonOk({ response: content, session_id: sessionId, type: 'chat' });
      } catch (error) {
        return jsonOk({ response: '', session_id: 'default', type: 'chat' });
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

        const webContext = await webSearch(message, env);
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
        if (!content || !content.trim()) content = '';

        return jsonOk({ response: content, session_id: sessionId, type: 'chat' });
      } catch (error) {
        return jsonOk({ response: '', session_id: sessionId || 'default', type: 'chat' });
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

        const webContext = await webSearch(message, env);
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
        if (!content || !content.trim()) content = '';

        return jsonOk({ response: content, session_id: sessionId, type: 'chat' });
      } catch (error) {
        return jsonOk({ response: '', session_id: sessionId || 'default', type: 'chat' });
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
          return jsonOk({ response: '', image_data: imageBase64, type: 'image_gen' });
        }

        return jsonOk({ response: '', type: 'error', error: 'generation_failed' });
      } catch (error) {
        return jsonOk({ response: '', type: 'error', error: 'generation_failed' });
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
        const mimeType = file.type || 'image/jpeg';

        let editedBase64 = null;

        // Strategy 1: Python Editor Service (best quality, if deployed)
        editedBase64 = await tryEditorService(fileBytes, editPrompt, env);
        if (editedBase64) {
          return jsonOk({ response: '', image_data: editedBase64, type: 'image_gen', session_id: sessionId });
        }

        // Strategy 2: Vision-guided editing - analyze image then craft better prompt
        const imageDescription = await analyzeImageWithVision(imageBase64, mimeType, editPrompt, env);
        const enhancedPrompt = imageDescription ? await craftEditPrompt(imageDescription, editPrompt) : editPrompt;

        // Strategy 3: Better Pollinations with enhanced prompt
        editedBase64 = await tryBetterPollinationsEdit(imageBase64, enhancedPrompt, imageDescription);
        if (editedBase64) {
          return jsonOk({ response: '', image_data: editedBase64, type: 'image_gen', session_id: sessionId });
        }

        // Strategy 4: Workers AI with image input
        editedBase64 = await tryWorkersAIEdit(fileBytes, enhancedPrompt, env);
        if (editedBase64) {
          return jsonOk({ response: '', image_data: editedBase64, type: 'image_gen', session_id: sessionId });
        }

        // Strategy 5: Original Pollinations img2img (fallback)
        editedBase64 = await tryPollinationsImageEdit(imageBase64, editPrompt);
        if (editedBase64) {
          return jsonOk({ response: '', image_data: editedBase64, type: 'image_gen', session_id: sessionId });
        }

        // Strategy 6: Workers AI text-to-image as last resort
        if (env.AI) {
          try {
            const result = await env.AI.run('@cf/stabilityai/stable-diffusion-xl-base-1.0', {
              prompt: enhancedPrompt,
              image: [...new Uint8Array(fileBytes)],
            });
            if (result?.image) editedBase64 = result.image;
          } catch {}
        }
        if (editedBase64) {
          return jsonOk({ response: '', image_data: editedBase64, type: 'image_gen', session_id: sessionId });
        }

        // All strategies failed - return empty so LLM can apologize naturally
        return jsonOk({
          response: '',
          session_id: sessionId,
          type: 'chat',
        });
      } catch (error) {
        return jsonOk({ response: '', session_id: sessionId || 'default', type: 'chat' });
      }
    }

    // Ultra edit endpoint (fallback from frontend)
    if (path === '/v1/image/ultra-edit' && request.method === 'POST') {
      try {
        const formData = await request.formData();
        const file = formData.get('file');
        const editPrompt = formData.get('prompt') || '';
        const sessionId = formData.get('session_id') || 'default';

        if (!file) return jsonError('No image file provided.');
        if (!editPrompt.trim()) return jsonError('No edit prompt provided.');

        const fileBytes = await file.arrayBuffer();
        const imageBase64 = arrayBufferToBase64(fileBytes);

        let editedBase64 = await tryEditorService(fileBytes, editPrompt, env);
        if (!editedBase64) editedBase64 = await tryBetterPollinationsEdit(imageBase64, editPrompt, null);
        if (!editedBase64) editedBase64 = await tryPollinationsImageEdit(imageBase64, editPrompt);

        if (editedBase64) {
          return jsonOk({ response: '', image_data: editedBase64, type: 'image_gen', session_id: sessionId });
        }
        return jsonOk({ response: '', session_id: sessionId, type: 'chat' });
      } catch (error) {
        return jsonOk({ response: '', session_id: sessionId || 'default', type: 'chat' });
      }
    }

    // Redesign endpoint (fallback from frontend)
    if (path === '/api/image/redesign' && request.method === 'POST') {
      try {
        const formData = await request.formData();
        const file = formData.get('file');
        const prompt = formData.get('prompt') || '';
        if (!file) return jsonError('No file provided.');
        if (!prompt.trim()) return jsonError('No prompt provided.');

        const fileBytes = await file.arrayBuffer();
        const imageBase64 = arrayBufferToBase64(fileBytes);

        let result = null;
        const description = await analyzeImageWithVision(imageBase64, file.type || 'image/jpeg', prompt, env);
        const enhanced = description ? await craftEditPrompt(description, prompt) : prompt;
        result = await tryBetterPollinationsEdit(imageBase64, enhanced, description);
        if (!result) result = await tryPollinationsImageEdit(imageBase64, prompt);

        if (result) {
          return jsonOk({ content: result, image_data: result, type: 'image_gen' });
        }
        return jsonOk({ content: '', type: 'chat' });
      } catch (error) {
        return jsonOk({ content: '', type: 'chat' });
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
        if (!content || !content.trim()) content = '';

        return jsonOk({ response: content, session_id: sessionId, type: 'chat' });
      } catch (error) {
        return jsonOk({ response: '', session_id: sessionId || 'default', type: 'chat' });
      }
    }

    if (path === '/api/tools/search' && request.method === 'POST') {
      try {
        const body = await request.json();
        const query = body.query || body.q || '';
        const maxResults = body.max_results || 5;
        if (!query.trim()) return jsonError('Please provide a search query.');

        const results = await webSearch(query, env);
        return jsonOk({ results: results || '', query, type: 'search' });
      } catch (error) {
        return jsonOk({ results: '', query: query || '', type: 'search' });
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
        if (!content) {
          const pollMsg = await tryPollinations(messages, env);
          if (pollMsg && pollMsg.trim()) content = pollMsg;
        }
        if (!content) {
          const aiMsg = await tryWorkersAIChat(messages, env);
          if (aiMsg) content = aiMsg;
        }

        return jsonOk({ response: content || '', type: 'chat' });
      } catch (error) {
        return jsonOk({ response: '', type: 'chat' });
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
