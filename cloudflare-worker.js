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

function buildSystemPrompt(timestamp, webContext) {
  let prompt = `You are Acronous AI, a helpful assistant. Current date and time: ${timestamp}.`;
  prompt += ` Respond in natural, conversational language. If the user asks for code or programming, provide the code clearly.`;
  prompt += ` Never include advertisements, sponsorships, promotional content, or mentions of any provider/platform.`;
  prompt += ` Never include phrases like "powered by", "brought to you by", "sponsored by", or any service attribution.`;
  if (webContext) {
    prompt += ` Use this current information to answer: ${webContext}`;
  }
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
    if (data.RelatedTopics?.length > 0) {
      return data.RelatedTopics.slice(0, 3).map(t => t.Text || t.FirstURL).filter(Boolean).join(' | ');
    }
    return null;
  } catch {
    return null;
  }
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
    const headers = {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${env.OPENROUTER_API_KEY}`,
      'HTTP-Referer': 'https://ai.acronous.com',
      'X-Title': 'Acronous AI'
    };
    const response = await fetch(`${env.OPENROUTER_BASE_URL}/chat/completions`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        messages: [
          { role: 'system', content: systemPrompt },
          { role: 'user', content: message }
        ],
        model: env.OPENROUTER_MODEL,
        max_tokens: 800,
        temperature: 0.7
      })
    });
    if (!response.ok) return null;
    const data = await response.json();
    const content = data?.choices?.[0]?.message?.content;
    return (content && content.trim()) ? cleanResponse(content) : null;
  } catch {
    return null;
  }
}

async function tryPollinations(message, systemPrompt) {
  try {
    const response = await fetch('https://text.pollinations.ai', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        messages: [
          { role: 'system', content: systemPrompt },
          { role: 'user', content: message }
        ],
        model: 'openai',
        private: true
      })
    });
    if (!response.ok) return null;
    const text = await response.text();
    return (text && text.trim()) ? cleanResponse(text) : null;
  } catch {
    return null;
  }
}

async function tryPollinationsImage(prompt) {
  try {
    const url = 'https://image.pollinations.ai/prompt/' + encodeURIComponent(prompt) + '?width=1024&height=1024&nofeed=true';
    const response = await fetch(url);
    if (!response.ok) return null;
    const blob = await response.arrayBuffer();
    const base64 = btoa(String.fromCharCode(...new Uint8Array(blob)));
    return base64;
  } catch {
    return null;
  }
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;

    if (request.method === 'OPTIONS') {
      const origin = request.headers.get('Origin') || '*';
      return new Response(null, { headers: {
        'Access-Control-Allow-Origin': origin,
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type, Authorization',
        'Access-Control-Allow-Credentials': 'true',
        'Access-Control-Max-Age': '86400',
      }});
    }

    if (isLandingAuthPath(path)) {
      const targetUrl = LANDING_WORKER + path + url.search;
      const headers = new Headers(request.headers);
      headers.delete('Host');
      const proxyReq = new Request(targetUrl, {
        method: request.method,
        headers,
        body: request.body,
      });
      try {
        return await fetch(proxyReq);
      } catch {
        return new Response('Auth proxy error', { status: 502 });
      }
    }

    if (path === '/v1/chat' && request.method === 'POST') {
      try {
        const body = await request.json();
        const message = body.message || 'Hello';
        const sessionId = body.session_id || 'default';
        const timestamp = new Date().toISOString().replace('T', ' ').slice(0, 19) + ' UTC';

        let webContext = null;
        if (TIME_KEYWORDS.test(message)) {
          webContext = await webSearch(message);
        }

        const systemPrompt = buildSystemPrompt(timestamp, webContext);

        let content = await tryOpenRouter(message, env, systemPrompt);
        if (!content) {
          content = await tryPollinations(message, systemPrompt);
        }
        if (!content || content.trim() === '') {
          content = "I received your message. I'm having trouble generating a proper response right now — this might be a temporary issue with the AI model. Please try again or rephrase your question.";
        }

        return new Response(
          JSON.stringify({
            response: content,
            session_id: sessionId,
            type: 'chat'
          }),
          {
            headers: {
              'Content-Type': 'application/json',
              'Access-Control-Allow-Origin': '*'
            }
          }
        );

      } catch (error) {
        console.error('Chat error:', error.message);
        return new Response(
          JSON.stringify({
            response: "I encountered an issue while processing your request. Please try again in a moment.",
            error: error.message
          }),
          {
            status: 200,
            headers: {
              'Content-Type': 'application/json',
              'Access-Control-Allow-Origin': '*'
            }
          }
        );
      }
    }

    if ((path === '/v1/image/generate' || path === '/api/image/generate') && request.method === 'POST') {
      try {
        const body = await request.json();
        const prompt = body.prompt || body.message || '';

        if (!prompt.trim()) {
          return new Response(JSON.stringify({
            response: 'Please provide a description for the image.',
            type: 'error'
          }), { status: 200, headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' } });
        }

        const imageBase64 = await tryPollinationsImage(prompt);
        if (imageBase64) {
          return new Response(JSON.stringify({
            response: 'Generated image based on your request.',
            image_data: imageBase64,
            type: 'image_gen'
          }), { status: 200, headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' } });
        }

        return new Response(JSON.stringify({
          response: "I couldn't generate the image right now. Please try again with a different description.",
          type: 'error'
        }), { status: 200, headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' } });

      } catch (error) {
        return new Response(JSON.stringify({
          response: "I encountered an issue generating the image. Please try again.",
          error: error.message
        }), { status: 200, headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' } });
      }
    }

    if (path === '/v1/wakeup' && request.method === 'GET') {
      return new Response(
        JSON.stringify({ status: 'ok' }),
        {
          headers: {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
          }
        }
      );
    }

    if (path === '/health' && request.method === 'GET') {
      return new Response(
        JSON.stringify({ status: 'ok', service: 'acronous-ai' }),
        {
          headers: {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
          }
        }
      );
    }

    if (isApiPath(path)) {
      return new Response(
        JSON.stringify({ error: 'Not found', message: 'The requested endpoint does not exist' }),
        { status: 404, headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' } }
      );
    }

    const targetUrl = PAGES_ORIGIN + path + url.search;
    const headers = new Headers(request.headers);
    headers.delete('Host');
    const proxyReq = new Request(targetUrl, {
      method: request.method,
      headers,
      body: request.body,
    });
    try {
      const response = await fetch(proxyReq);
      if (response.status === 404) {
        const indexRes = await fetch(PAGES_ORIGIN + '/index.html');
        return new Response(indexRes.body, {
          status: 200,
          headers: indexRes.headers,
        });
      }
      return new Response(response.body, {
        status: response.status,
        headers: response.headers,
      });
    } catch {
      return new Response('Proxy error', { status: 502 });
    }
  }
};
