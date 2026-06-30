// Acronous AI (Flutter Web) — Cloudflare Pages SPA Fallback Worker
// Serves the Flutter web SPA with client-side routing support.
//
// Deployment:
//
//   Option A — Direct Pages deploy:
//     cd Acronous\ Ai
//     flutter build web
//     npx wrangler pages deploy build/web --project-name=acronous-ai
//
//   Option B — via wrangler.toml:
//     cd Acronous\ Ai\build\web
//     npx wrangler pages deploy
//
//   Then set custom domain: ai.acronous.com
//
//   After deploying, update PAGES_ORIGIN in Acronous Ai/wrangler.toml:
//     PAGES_ORIGIN = "https://your-project.pages.dev"

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: {
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Methods': 'GET, OPTIONS',
          'Access-Control-Allow-Headers': 'Content-Type',
        },
      });
    }

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
