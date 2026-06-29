// Acronous Landing Page — Cloudflare Worker
// Routes subdomains to their respective app builds:
//   acronous.com             → Landing Page (env.ASSETS)
//   auth.acronous.com        → Auth Server (deployed separately)
//   ai.acronous.com          → Acronous AI Flutter web
//   equyvo.acronous.com      → Equyvo React SPA
//   navigwiz.acronous.com    → Navigwiz Flutter web
//
// Deployment:
//   wrangler deploy
//   Then add acronous.com + subdomains in Cloudflare dashboard
//
// For subdomains to route through this worker, each subdomain's DNS
// must point to Cloudflare and have a Worker Route in the dashboard,
// OR set the worker as the origin for each subdomain.

// ── Known subdomain app origins ─────────────────────────────────────────
const SUBDOMAIN_ORIGINS = {
  'ai.acronous.com':        'https://acronous-ai.pages.dev',
  'equyvo.acronous.com':    'https://equyvo.pages.dev',
  'navigwiz.acronous.com':  'https://navigwiz.pages.dev',
  // Update this URL to wherever the auth server is deployed:
  'auth.acronous.com':      'https://acronous-auth-server.your-domain.com',
};

// Always serve the landing page for these hosts
const LANDING_HOSTS = new Set([
  'acronous.com',
  'www.acronous.com',
]);

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Authorization',
  'Access-Control-Allow-Credentials': 'true',
};

function redirect(url, status = 301) {
  return new Response(null, {
    status,
    headers: { Location: url.toString() },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const host = url.hostname;

    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: CORS_HEADERS });
    }

    // ── www → bare domain redirect ─────────────────────────────────────
    if (host === 'www.acronous.com') {
      url.hostname = 'acronous.com';
      return redirect(url);
    }

    // ── Subdomain proxy routing ────────────────────────────────────────
    const origin = SUBDOMAIN_ORIGINS[host];
    if (origin) {
      const targetUrl = origin + url.pathname + url.search;
      const proxyReq = new Request(targetUrl, {
        method: request.method,
        headers: request.headers,
        body: request.body,
      });
      try {
        const response = await fetch(proxyReq);
        // For auth server, don't apply SPA fallback
        if (host === 'auth.acronous.com') {
          return response;
        }
        // SPA fallback for subdomain apps
        const body = response.status === 404
          ? await fetch(origin + '/index.html')
          : response;
        return new Response(body.body, {
          status: body.status,
          headers: body.headers,
        });
      } catch {
        return new Response('Subdomain proxy error', { status: 502 });
      }
    }

    // ── Unknown host → redirect to acronous.com (landing page) ─────────
    if (!LANDING_HOSTS.has(host)) {
      url.hostname = 'acronous.com';
      return redirect(url);
    }

    // ── acronous.com — serve landing page with SPA fallback ────────────
    try {
      const response = await env.ASSETS.fetch(request);
      if (response.status === 404) {
        const indexResponse = await env.ASSETS.fetch(
          new Request(new URL('/index.html', request.url), request)
        );
        return new Response(indexResponse.body, {
          status: 200,
          headers: indexResponse.headers,
        });
      }
      return response;
    } catch {
      return new Response('Not Found', { status: 404 });
    }
  },
};
