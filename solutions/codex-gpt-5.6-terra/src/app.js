import { randomBytes } from 'node:crypto';
import { URL } from 'node:url';

const CUSTOM_SLUG = /^[A-Za-z0-9_-]{3,32}$/;
const MAX_BODY_BYTES = 16 * 1024;

export class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function sendJson(response, status, payload) {
  response.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store'
  });
  response.end(JSON.stringify(payload));
}

function sendError(response, status, message) {
  sendJson(response, status, { error: message });
}

async function readJson(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > MAX_BODY_BYTES) throw new HttpError(400, 'JSON body is too large');
    chunks.push(chunk);
  }
  if (size === 0) throw new HttpError(400, 'JSON body is required');
  try {
    const value = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    if (!value || Array.isArray(value) || typeof value !== 'object') {
      throw new HttpError(400, 'JSON body must be an object');
    }
    return value;
  } catch (error) {
    if (error instanceof HttpError) throw error;
    throw new HttpError(400, 'Malformed JSON body');
  }
}

function validateTarget(value) {
  if (typeof value !== 'string' || value.length === 0 || value.length > 2048) {
    throw new HttpError(400, 'url must be a non-empty string of at most 2048 characters');
  }
  let parsed;
  try { parsed = new URL(value); } catch { throw new HttpError(400, 'url must be an absolute http or https URL'); }
  if ((parsed.protocol !== 'http:' && parsed.protocol !== 'https:') || !parsed.hostname) {
    throw new HttpError(400, 'url must be an absolute http or https URL');
  }
  return value;
}

function validateCustomSlug(value) {
  if (value === undefined) return null;
  if (typeof value !== 'string' || !CUSTOM_SLUG.test(value)) {
    throw new HttpError(400, 'slug must be 3–32 characters using letters, digits, _ or -');
  }
  return value;
}

function generatedSlug() {
  // 72 random bits: URL-safe, short, and impractical to enumerate.
  return randomBytes(9).toString('base64url');
}

function getPathSlug(pathname, prefix = '/') {
  if (!pathname.startsWith(prefix)) return null;
  const remainder = pathname.slice(prefix.length);
  if (!remainder || remainder.includes('/')) return null;
  try {
    const slug = decodeURIComponent(remainder);
    return CUSTOM_SLUG.test(slug) ? slug : null;
  } catch { return null; }
}

function requestOrigin(request, configuredOrigin) {
  if (configuredOrigin) return configuredOrigin;
  const host = request.headers.host || 'localhost';
  return `http://${host}`;
}

function metadata(link, origin) {
  return {
    slug: link.slug,
    url: link.url,
    short_url: `${origin}/${encodeURIComponent(link.slug)}`,
    created_at: link.created_at,
    visits: link.visits
  };
}

function isAuthorized(request, token) {
  if (!token) return false;
  const value = request.headers.authorization;
  return value === `Bearer ${token}`;
}

export function createApp({ store, apiToken, publicBaseUrl } = {}) {
  if (!store) throw new Error('store is required');
  const configuredOrigin = publicBaseUrl ? new URL(publicBaseUrl).origin : null;

  return async function app(request, response) {
    try {
      const url = new URL(request.url, 'http://snip.local');
      const { pathname } = url;
      const origin = requestOrigin(request, configuredOrigin);

      if (request.method === 'GET' && pathname === '/healthz') {
        sendJson(response, 200, { status: 'ok' });
        return;
      }

      if (request.method === 'POST' && pathname === '/api/links') {
        if (!isAuthorized(request, apiToken)) throw new HttpError(401, 'Unauthorized');
        const body = await readJson(request);
        const target = validateTarget(body.url);
        const customSlug = validateCustomSlug(body.slug);
        const slug = customSlug ?? (() => {
          for (let attempt = 0; attempt < 10; attempt += 1) {
            const candidate = generatedSlug();
            if (!store.has(candidate)) return candidate;
          }
          throw new HttpError(500, 'Could not allocate a unique slug');
        })();

        const link = { slug, url: target, created_at: new Date().toISOString() };
        if (!store.create(link)) throw new HttpError(409, 'Slug is already in use');
        const result = metadata({ ...link, visits: 0 }, origin);
        delete result.visits;
        sendJson(response, 201, result);
        return;
      }

      const apiSlug = getPathSlug(pathname, '/api/links/');
      if (apiSlug && request.method === 'GET') {
        const link = store.get(apiSlug);
        if (!link) throw new HttpError(404, 'Link not found');
        sendJson(response, 200, metadata(link, origin));
        return;
      }
      if (apiSlug && request.method === 'DELETE') {
        if (!isAuthorized(request, apiToken)) throw new HttpError(401, 'Unauthorized');
        if (!store.delete(apiSlug)) throw new HttpError(404, 'Link not found');
        response.writeHead(204);
        response.end();
        return;
      }

      const slug = getPathSlug(pathname);
      if (slug && request.method === 'GET') {
        const link = store.recordVisit(slug);
        if (!link) throw new HttpError(404, 'Link not found');
        response.writeHead(302, { location: link.url, 'cache-control': 'no-store' });
        response.end();
        return;
      }

      throw new HttpError(404, 'Not found');
    } catch (error) {
      if (response.headersSent) {
        response.destroy(error);
        return;
      }
      if (error instanceof HttpError) {
        sendError(response, error.status, error.message);
        return;
      }
      console.error(error);
      sendError(response, 500, 'Internal server error');
    }
  };
}
