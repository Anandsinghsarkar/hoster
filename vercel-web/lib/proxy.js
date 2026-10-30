const BACKEND = (process.env.RENDER_BACKEND_URL || 'https://hoster-1-1qzm.onrender.com').replace(/\/$/, '');
const HOP_BY_HOP = new Set([
  'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
  'te', 'trailer', 'transfer-encoding', 'upgrade', 'host'
]);

export async function proxyToRender(request, pathSegments = []) {
  const incoming = new URL(request.url);
  const path = pathSegments.map((part) => encodeURIComponent(part)).join('/');
  const target = BACKEND + '/' + path + incoming.search;

  const headers = new Headers();
  request.headers.forEach((value, key) => {
    const lower = key.toLowerCase();
    if (!HOP_BY_HOP.has(lower) && lower !== 'content-length') headers.set(key, value);
  });
  headers.set('x-forwarded-host', incoming.host);
  headers.set('x-forwarded-proto', incoming.protocol.replace(':', ''));

  const init = {
    method: request.method,
    headers,
    redirect: 'manual',
    cache: 'no-store',
    signal: AbortSignal.timeout(55000)
  };

  if (!['GET', 'HEAD'].includes(request.method) && request.body) {
    init.body = request.body;
    init.duplex = 'half';
  }

  let upstream;
  try {
    upstream = await fetch(target, init);
  } catch (error) {
    const timedOut = error?.name === 'TimeoutError' || error?.name === 'AbortError';
    return Response.json(
      { error: timedOut ? 'The hosting backend took too long to respond.' : 'Hosting backend is temporarily unavailable. Please retry shortly.' },
      { status: timedOut ? 504 : 502, headers: { 'Cache-Control': 'no-store' } }
    );
  }

  const responseHeaders = new Headers();
  const getSetCookie = upstream.headers.getSetCookie?.bind(upstream.headers);
  upstream.headers.forEach((value, key) => {
    const lower = key.toLowerCase();
    if (!HOP_BY_HOP.has(lower) && lower !== 'content-length' && lower !== 'set-cookie') {
      responseHeaders.set(key, value);
    }
  });

  const cookies = getSetCookie ? getSetCookie() : [];
  for (const cookie of cookies) responseHeaders.append('set-cookie', cookie);
  if (!cookies.length) {
    const cookie = upstream.headers.get('set-cookie');
    if (cookie) responseHeaders.set('set-cookie', cookie);
  }

  const location = responseHeaders.get('location');
  if (location) {
    try {
      const backendOrigin = new URL(BACKEND).origin;
      const redirectUrl = new URL(location, BACKEND);
      if (redirectUrl.origin === backendOrigin) {
        responseHeaders.set('location', incoming.origin + redirectUrl.pathname + redirectUrl.search + redirectUrl.hash);
      }
    } catch {}
  }

  responseHeaders.set('cache-control', 'no-store');
  return new Response(request.method === 'HEAD' ? null : upstream.body, {
    status: upstream.status,
    headers: responseHeaders
  });
}
