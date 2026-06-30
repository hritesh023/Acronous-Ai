// Acronous AI (Flutter Web) — Cloudflare Pages Worker
// Serves Flutter SPA with SPA fallback and proxies auth routes to acronous.com
//
// Deployment:
//   flutter build web && Copy-Item web/_worker.js build/web/ && npx wrangler pages deploy build/web --project-name=acronous-ai

const AUTH_ORIGIN = 'https://acronous.com';

const AUTH_ROUTES = new Set([
  '/login', '/login.html',
  '/signup', '/signup.html',
  '/dashboard', '/dashboard.html',
  '/logout',
]);

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: {
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
          'Access-Control-Allow-Headers': 'Content-Type, Authorization',
          'Access-Control-Allow-Credentials': 'true',
          'Access-Control-Max-Age': '86400',
        },
      });
    }

    // Auth routes → proxy to centralized auth at acronous.com
    if (AUTH_ROUTES.has(path) || path.startsWith('/api/auth/')) {
      try {
        const targetUrl = `${AUTH_ORIGIN}${path}${url.search}`;
        const headers = new Headers(request.headers);
        const body = (request.method !== 'GET' && request.method !== 'HEAD') ? request.body : null;
        const proxyReq = new Request(targetUrl, { method: request.method, headers, body, redirect: 'follow' });
        const resp = await fetch(proxyReq);
        const respHeaders = new Headers(resp.headers);
        respHeaders.set('Access-Control-Allow-Origin', '*');
        return new Response(resp.body, { status: resp.status, headers: respHeaders });
      } catch {
        return new Response(
          `<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>Auth Unavailable</title></head><body>
          <h2>Authentication server is temporarily unreachable</h2>
          <p>Please try again later. <a href="${AUTH_ORIGIN}/login">Go to Sign In</a></p>
          </body></html>`,
          { status: 502, headers: { 'Content-Type': 'text/html; charset=utf-8' } },
        );
      }
    }

    // SPA fallback for Flutter routes
    try {
      const response = await env.ASSETS.fetch(request);
      if (response.status === 404) {
        const indexResponse = await env.ASSETS.fetch(
          new Request(new URL('/index.html', request.url), request)
        );
        return new Response(indexResponse.body, { status: 200, headers: indexResponse.headers });
      }
      return response;
    } catch {
      return new Response('Not Found', { status: 404 });
    }
  },
};
