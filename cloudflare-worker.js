export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (url.pathname === '/v1/chat' && request.method === 'POST') {
      try {
        const body = await request.json();
        const message = body.message || 'Hello';
        const sessionId = body.session_id || 'default';

        if (!env.OPENROUTER_API_KEY) {
          return new Response(
            JSON.stringify({
              response: 'OpenRouter API key not configured',
              error: 'configuration_missing'
            }),
            {
              status: 500,
              headers: {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
              }
            }
          );
        }

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
            messages: [{ role: 'user', content: message }],
            model: env.OPENROUTER_MODEL,
            max_tokens: 500,
            temperature: 0.1
          })
        });

        if (!response.ok) {
          throw new Error(`OpenRouter API error: ${response.status}`);
        }

        const data = await response.json();

        if (!data?.choices?.[0]?.message?.content) {
          throw new Error('Invalid response from OpenRouter');
        }

        return new Response(
          JSON.stringify({
            response: data.choices[0].message.content,
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
            response: 'Sorry, I encountered an error. Please try again.',
            error: error.message
          }),
          {
            status: 500,
            headers: {
              'Content-Type': 'application/json',
              'Access-Control-Allow-Origin': '*'
            }
          }
        );
      }
    }

    if (url.pathname === '/v1/wakeup' && request.method === 'GET') {
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

    if (url.pathname === '/health' && request.method === 'GET') {
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

    return new Response(
      JSON.stringify({
        error: 'Not found',
        message: 'The requested endpoint does not exist'
      }),
      {
        status: 404,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*'
        }
      }
    );
  }
};