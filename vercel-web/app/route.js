import { proxyToRender } from '../lib/proxy.js';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export const maxDuration = 60;

export const GET = (request) => proxyToRender(request, []);
export const HEAD = (request) => proxyToRender(request, []);
export const POST = (request) => proxyToRender(request, []);
export const PUT = (request) => proxyToRender(request, []);
export const PATCH = (request) => proxyToRender(request, []);
export const DELETE = (request) => proxyToRender(request, []);
export const OPTIONS = (request) => proxyToRender(request, []);
