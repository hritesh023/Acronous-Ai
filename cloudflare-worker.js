// Acronous AI — Cloudflare Worker
// Routes acronous.com traffic to your backend server.
//
// Update BACKEND to your server's hostname before deploying.
//
// Deploy:
//   npm install -g wrangler
//   wrangler deploy cloudflare-worker.js --name acronous-ai

const BACKEND = 'acronous-ai.onrender.com';
const PROXY_TIMEOUT = 600000; // 10 min — no hard time limit, adapts to complexity
const WARMUP_TIMEOUT = 60000;  // 60s warmup timeout
const API_PREFIXES = ['/v1/', '/api/', '/openapi', '/docs', '/redoc', '/health'];
const STATIC_EXTENSIONS = ['.js', '.css', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.woff', '.woff2', '.json', '.wasm'];

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const path = url.pathname;

    // ── Dedicated warmup endpoint ──────────────────────────────────────
    if (path === '/warmup') {
      return handleWarmup(request, url);
    }

    // ── Health check (also acts as keep-awake) ────────────────────────
    if (path === '/health') {
      return proxyToBackend(request, url, '/v1/health');
    }

    // ── API calls → proxy to backend with fallback ────────────────────
    if (API_PREFIXES.some(p => path.startsWith(p))) {
      return proxyToBackend(request, url, path);
    }

    // ── Static files → serve from cache, fallback to backend ──────────
    if (STATIC_EXTENSIONS.some(ext => path.endsWith(ext))) {
      return serveStaticOrProxy(request, url);
    }

    // ── Frontend SPA → proxy, with warmup on failure ──────────────────
    return serveFrontend(request, url);
  },
};

async function proxyToBackend(request, url, pathname) {
  url.hostname = BACKEND;
  url.pathname = pathname;

  const body = request.method === 'GET' || request.method === 'HEAD'
    ? undefined
    : await request.clone().arrayBuffer();

  const init = {
    method: request.method,
    headers: request.headers,
    body,
    signal: AbortSignal.timeout(PROXY_TIMEOUT),
  };

  // Retry once for cold starts (Render can take 30-50s on first request)
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const resp = await fetch(url.toString(), init);
      return resp;
    } catch (e) {
      if (attempt === 0) {
        wakeBackend();
        await new Promise(r => setTimeout(r, 5000));
        init.body = body;
        continue;
      }
      return new Response(
        JSON.stringify({
          error: 'Acronous AI is starting up. Please try again in a moment.',
        }),
        { status: 503, headers: { 'Content-Type': 'application/json' } },
      );
    }
  }
}

async function serveStaticOrProxy(request, url) {
  url.hostname = BACKEND;
  try {
    const resp = await fetch(url.toString(), { ...request });
    if (resp.ok) {
      // Cache static assets at Cloudflare edge for 1 hour
      const cached = new Response(resp.body, resp);
      cached.headers.set('Cache-Control', 'public, max-age=3600, s-maxage=3600');
      return cached;
    }
    return resp;
  } catch (e) {
    return serveWarmupPage('Resource temporarily unavailable');
  }
}

async function serveFrontend(request, url) {
  url.hostname = BACKEND;
  try {
    const resp = await fetch(url.toString(), { ...request });
    if (resp.ok || resp.status === 404) {
      return resp;
    }
    // Backend responded with error → warmup
    wakeBackend();
    return serveWarmupPage();
  } catch (e) {
    // Backend unreachable (sleeping) → warmup + show warmup page
    wakeBackend();
    return serveWarmupPage();
  }
}

const WARMUP_PAGE = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Acronous AI — Loading</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: #0F0F1A;
      color: #E8E8F0;
      display: flex;
      justify-content: center;
      align-items: center;
      min-height: 100vh;
    }
    .container { text-align: center; padding: 2rem; }
    .logo {
      width: 80px; height: 80px;
      background: linear-gradient(135deg, #7C3AED, #8B5CF6);
      border-radius: 20px;
      display: inline-flex; align-items: center; justify-content: center;
      font-size: 36px; font-weight: bold; color: white;
      margin-bottom: 1.5rem;
    }
    h1 { font-size: 1.5rem; margin-bottom: 0.5rem; }
    p { color: #707090; margin-bottom: 1.5rem; }
    .spinner {
      width: 32px; height: 32px;
      border: 3px solid #1C1C35;
      border-top-color: #7C3AED;
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
      margin: 0 auto;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    .retry-btn {
      margin-top: 1rem; padding: 0.6rem 1.5rem;
      background: #7C3AED; color: white; border: none;
      border-radius: 10px; font-size: 0.9rem; cursor: pointer;
    }
    .retry-btn:hover { background: #6D28D9; }
  </style>
</head>
<body>
  <div class="container">
    <div class="logo">A</div>
    <h1>Waking up Acronous AI</h1>
    <p>The server is starting up — this takes 20–30 seconds.</p>
    <div class="spinner"></div>
    <p style="margin-top:1.5rem;font-size:0.85rem;color:#505070;">
      Auto-refreshing in <span id="countdown">30</span>s
    </p>
    <button class="retry-btn" onclick="location.reload()">Retry Now</button>
  </div>
  <script>
    let sec = 30;
    setInterval(() => {
      sec--;
      document.getElementById('countdown').textContent = sec;
      if (sec <= 0) location.reload();
    }, 1000);
  </script>
</body>
</html>`;

function serveWarmupPage(message) {
  wakeBackend();
  return new Response(WARMUP_PAGE, {
    status: 503,
    headers: { 'Content-Type': 'text/html; charset=utf-8' },
  });
}

async function handleWarmup(request, url) {
  url.hostname = BACKEND;
  url.pathname = '/v1/health';
  try {
    const resp = await fetch(url.toString(), {
      signal: AbortSignal.timeout(WARMUP_TIMEOUT),
    });
    if (resp.ok) {
      return new Response(
        JSON.stringify({ status: 'ok', message: 'Acronous AI is ready' }),
        { headers: { 'Content-Type': 'application/json' } },
      );
    }
    wakeBackend();
    return new Response(
      JSON.stringify({ status: 'warming', message: 'Acronous AI is starting up' }),
      { status: 503, headers: { 'Content-Type': 'application/json' } },
    );
  } catch (e) {
    wakeBackend();
    return new Response(
      JSON.stringify({ status: 'warming', message: 'Acronous AI is starting up' }),
      { status: 503, headers: { 'Content-Type': 'application/json' } },
    );
  }
}

let warmingUp = false;

async function wakeBackend() {
  if (warmingUp) return;
  warmingUp = true;
  const url = `https://${BACKEND}/v1/wakeup`;
  try {
    await fetch(url, { signal: AbortSignal.timeout(30000) });
  } catch (_) {
  }
  warmingUp = false;
}
