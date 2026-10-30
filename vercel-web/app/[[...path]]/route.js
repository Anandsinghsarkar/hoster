import { NextResponse } from 'next/server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const BACKEND = (process.env.RENDER_BACKEND_URL || 'https://hoster-1-1qzm.onrender.com').replace(/\/$/, '');
const HOP_BY_HOP = new Set([
  'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
  'te', 'trailers', 'transfer-encoding', 'upgrade', 'host'
]);

async function proxy(request, context) {
  const params = await context.params;
  const segments = params?.path || [];
  const incoming = new URL(request.url);
  const target = BACKEND + '/' + segments.map(encodeURIComponent).join('/') + incoming.search;

  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase())) headers.set(key, value);
  });
  headers.set('x-forwarded-host', incoming.host);
  headers.set('x-forwarded-proto', incoming.protocol.replace(':', ''));

  const init = {
    method: request.method,
    headers,
    redirect: 'manual',
    cache: 'no-store'
  };
  if (!['GET', 'HEAD'].includes(request.method)) init.body = await request.arrayBuffer();

  let upstream;
  try {
    upstream = await fetch(target, init);
  } catch {
    return NextResponse.json(
      { error: 'Hosting backend is temporarily unavailable. Please retry shortly.' },
      { status: 502, headers: { 'Cache-Control': 'no-store' } }
    );
  }

  const responseHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase()) && key.toLowerCase() !== 'content-length') {
      responseHeaders.append(key, value);
    }
  });

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
