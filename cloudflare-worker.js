// Deploy as a Cloudflare Worker. It relays Telegram Bot API requests from a VDS
// whose provider blocks direct access to api.telegram.org.
async function handle(request) {
    const url = new URL(request.url);
    if (!url.pathname.startsWith('/bot')) {
      return new Response('Not found', { status: 404 });
    }
    const upstream = new URL(`https://api.telegram.org${url.pathname}${url.search}`);
    const headers = new Headers(request.headers);
    headers.delete('host');
    const response = await fetch(upstream, {
      method: request.method,
      headers,
      body: request.method === 'GET' || request.method === 'HEAD' ? undefined : request.body,
    });
    return new Response(response.body, {
      status: response.status,
      headers: { 'content-type': response.headers.get('content-type') || 'application/json', 'cache-control': 'no-store' },
    });
  }

addEventListener('fetch', event => event.respondWith(handle(event.request)));
