// Acronous AI — Cloudflare Pages Worker
// Serves Flutter SPA + proxies API calls to the AI Worker

const API_WORKER = 'https://ai.acronous.com';

const API_PREFIXES = ['/v1/', '/api/', '/health'];

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    // Proxy API calls to the AI Worker
    if (API_PREFIXES.some(p => path === p || path.startsWith(p))) {
      const targetUrl = API_WORKER + path + url.search;
      const headers = new Headers(request.headers);
      headers.set('X-Forwarded-Host', url.hostname);
      const proxyReq = new Request(targetUrl, {
        method: request.method,
        headers,
        body: request.body,
      });
      try {
        return await fetch(proxyReq);
      } catch {
        return new Response('API proxy error', { status: 502 });
      }
    }

    // Static files + SPA fallback
    try {
      const response = await env.ASSETS.fetch(request);
      if (response.status === 404) {
        const indexResponse = await env.ASSETS.fetch(
          new Request(new URL('/index.html', request.url))
        );
        return new Response(indexResponse.body, {
          status: 200,
          headers: indexResponse.headers,
        });
      }
      // Bootstrap files are un-hashed — always revalidate so new deploys
      // show up immediately instead of being pinned by the Flutter service
      // worker / browser cache (stale main.dart.js = stale UI bugs).
      const NO_CACHE_FILES = [
        '/index.html',
        '/flutter_bootstrap.js',
        '/main.dart.js',
        '/flutter_service_worker.js',
        '/version.json',
        '/manifest.json',
      ];
      if (NO_CACHE_FILES.includes(path)) {
        const headers = new Headers(response.headers);
        headers.set('Cache-Control', 'no-cache, must-revalidate');
        return new Response(response.body, {
          status: response.status,
          headers,
        });
      }
      return response;
    } catch {
      return new Response('Not Found', { status: 404 });
    }
  },
};
