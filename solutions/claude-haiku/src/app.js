import { createServer } from 'node:http';
import { isAuthorized } from './auth.js';
import { HttpError } from './errors.js';
import { createLink, deleteLink, getLink } from './links.js';
import { isSlugFormat } from './validation.js';

export const DEFAULT_MAX_BODY_BYTES = 8 * 1024;

/**
 * Builds the HTTP server. The caller owns listening and shutdown.
 *
 * @param {object} options
 * @param {import('./store.js').LinkStore} options.store
 * @param {string} options.baseUrl     origin used to build short_url
 * @param {string|null} options.apiToken  bearer token for write endpoints
 * @param {number} [options.maxBodyBytes]
 */
export function createApp({ store, baseUrl, apiToken, maxBodyBytes = DEFAULT_MAX_BODY_BYTES }) {
  const ctx = { store, baseUrl, apiToken, maxBodyBytes };

  const server = createServer((req, res) => {
    handle(req, res, ctx).catch((err) => {
      if (!(err instanceof HttpError)) {
        console.error('unhandled error:', err);
      }
      sendError(res, err);
    });
  });

  // Guard against slow-loris style clients holding sockets open.
  server.headersTimeout = 10_000;
  server.requestTimeout = 30_000;

  return server;
}

async function handle(req, res, ctx) {
  const { pathname } = new URL(req.url, 'http://localhost');

  if (pathname === '/healthz') {
    allowMethods(req, ['GET']);
    return health(res, ctx);
  }

  if (pathname === '/api/links') {
    allowMethods(req, ['POST']);
    return postLink(req, res, ctx);
  }

  const apiMatch = /^\/api\/links\/([^/]+)$/.exec(pathname);
  if (apiMatch) {
    return linkRoute(req, res, ctx, apiMatch[1]);
  }

  const redirectMatch = /^\/([^/]+)$/.exec(pathname);
  if (redirectMatch) {
    allowMethods(req, ['GET']);
    return redirect(res, ctx, redirectMatch[1]);
  }

  throw new HttpError(404, 'not found');
}

function health(res, { store }) {
  try {
    store.ping();
  } catch {
    throw new HttpError(503, 'database unavailable');
  }
  sendJson(res, 200, { status: 'ok' });
}

async function postLink(req, res, ctx) {
  requireAuth(req, ctx);
  const body = await readJsonBody(req, ctx.maxBodyBytes);
  const link = createLink(ctx.store, ctx.baseUrl, body);
  sendJson(res, 201, link);
}

async function linkRoute(req, res, ctx, slug) {
  if (req.method === 'GET') {
    return getLinkRoute(res, ctx, slug);
  }
  if (req.method === 'DELETE') {
    requireAuth(req, ctx);
    if (!isSlugFormat(slug)) {
      throw new HttpError(404, 'link not found');
    }
    deleteLink(ctx.store, slug);
    return sendEmpty(res, 204);
  }
  throw new HttpError(405, 'method not allowed', { Allow: 'GET, DELETE' });
}

function getLinkRoute(res, ctx, slug) {
  if (!isSlugFormat(slug)) {
    throw new HttpError(404, 'link not found');
  }
  sendJson(res, 200, getLink(ctx.store, ctx.baseUrl, slug));
}

function redirect(res, { store }, slug) {
  // Slugs that cannot exist in the store are 404 before touching the database.
  const target = isSlugFormat(slug) ? store.recordVisit(slug) : undefined;
  if (!target) {
    throw new HttpError(404, 'link not found');
  }
  res.writeHead(302, {
    Location: target,
    // Stops browsers and proxies from caching the redirect, so every visit
    // reaches the server and gets counted.
    'Cache-Control': 'no-store',
  });
  res.end();
}

function requireAuth(req, { apiToken }) {
  if (!isAuthorized(req.headers.authorization, apiToken)) {
    throw new HttpError(401, 'missing or invalid bearer token', {
      'WWW-Authenticate': 'Bearer',
    });
  }
}

function allowMethods(req, methods) {
  if (!methods.includes(req.method)) {
    throw new HttpError(405, 'method not allowed', { Allow: methods.join(', ') });
  }
}

/**
 * Reads and parses a JSON object body. The Content-Type header is not
 * enforced; any body that parses as a JSON object is accepted.
 */
async function readJsonBody(req, maxBytes) {
  const declared = Number(req.headers['content-length']);
  if (declared > maxBytes) {
    throw tooLarge();
  }

  const chunks = [];
  let received = 0;
  for await (const chunk of req) {
    received += chunk.length;
    if (received > maxBytes) {
      throw tooLarge();
    }
    chunks.push(chunk);
  }

  let parsed;
  try {
    parsed = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch {
    throw new HttpError(400, 'request body must be valid JSON');
  }
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new HttpError(400, 'request body must be a JSON object');
  }
  return parsed;
}

function tooLarge() {
  return new HttpError(413, 'request body too large', { Connection: 'close' });
}

function sendJson(res, status, payload, headers = {}) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
    'X-Content-Type-Options': 'nosniff',
    ...headers,
  });
  res.end(body);
}

function sendEmpty(res, status) {
  res.writeHead(status);
  res.end();
}

function sendError(res, err) {
  if (res.headersSent) {
    res.destroy();
    return;
  }
  if (err instanceof HttpError) {
    sendJson(res, err.status, { error: err.message }, err.headers);
    return;
  }
  sendJson(res, 500, { error: 'internal server error' });
}
