import { NextResponse } from 'next/server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export const maxDuration = 60;

const BACKEND = (process.env.RENDER_BACKEND_URL || 'https://hoster-1-1qzm.onrender.com').replace(/\/$/, '');
const HOP_BY_HOP = new Set([
  'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
  'te', 'trailer', 'trailers', 'transfer-encoding', 'upgrade', 'host'
]);

async function proxy(request, context) {
  const params = await context.params;
  const segments = params?.path || [];
  const incoming = new URL(request.url);
  const target = BACKEND + '/' + segments.map(encodeURIComponent).join('/') + incoming.search;

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
  // Stream uploads rather than buffering a second full copy in the function.
  // Vercel's platform request-size limit still applies; large uploads should
  // eventually go directly to private Supabase Storage.
  if (!['GET', 'HEAD'].includes(request.method) && request.body) {
    init.body = request.body;
    init.duplex = 'half';
  }

  let upstream;
  try {
    upstream = await fetch(target, init);
  } catch (error) {
    const timedOut = error?.name === 'TimeoutError' || error?.name === 'AbortError';
    return NextResponse.json(
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

  // Preserve each cookie separately (session + flash/remember cookies).
  const cookies = getSetCookie ? getSetCookie() : [];
  for (const cookie of cookies) responseHeaders.append('set-cookie', cookie);
  if (!cookies.length) {
    const singleCookie = upstream.headers.get('set-cookie');
    if (singleCookie) responseHeaders.set('set-cookie', singleCookie);
  }

  const location = responseHeaders.get('location');
  if (location) {
    try {
      const redirectUrl = new URL(location, BACKEND);
      if (redirectUrl.origin === new URL(BACKEND).origin) {
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

export const GET = proxy;
export const HEAD = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const OPTIONS = proxy;
