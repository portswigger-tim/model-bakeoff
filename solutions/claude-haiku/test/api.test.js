import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, before, describe, test } from 'node:test';
import { authHeader, BASE_URL, postLink, startServer, TOKEN, visit } from './helpers.js';

describe('snip HTTP API', () => {
  let server;

  before(async () => {
    server = await startServer();
  });

  after(async () => {
    await server.stop();
  });

  const origin = () => server.origin;

  describe('GET /healthz', () => {
    test('returns 200', async () => {
      const res = await fetch(`${origin()}/healthz`);
      assert.equal(res.status, 200);
      assert.deepEqual(await res.json(), { status: 'ok' });
    });
  });

  describe('POST /api/links', () => {
    test('creates a link with a generated slug and returns 201', async () => {
      const res = await postLink(origin(), { url: 'https://example.com/a?b=1' });
      assert.equal(res.status, 201);

      const body = await res.json();
      assert.match(body.slug, /^[A-Za-z0-9]{8}$/);
      assert.equal(body.url, 'https://example.com/a?b=1');
      assert.equal(body.short_url, `${BASE_URL}/${body.slug}`);
      assert.ok(!Number.isNaN(Date.parse(body.created_at)), 'created_at is an ISO timestamp');
      assert.deepEqual(Object.keys(body).sort(), ['created_at', 'short_url', 'slug', 'url']);
    });

    test('accepts a custom slug', async () => {
      const res = await postLink(origin(), { url: 'http://example.org', slug: 'my-link_1' });
      assert.equal(res.status, 201);
      assert.equal((await res.json()).slug, 'my-link_1');
    });

    test('returns 409 when a custom slug is already taken', async () => {
      await postLink(origin(), { url: 'https://first.example', slug: 'taken-slug' });
      const res = await postLink(origin(), { url: 'https://second.example', slug: 'taken-slug' });
      assert.equal(res.status, 409);
      assert.ok((await res.json()).error);
    });

    test('generates distinct slugs across many requests', async () => {
      const slugs = new Set();
      for (let i = 0; i < 50; i += 1) {
        const body = await (await postLink(origin(), { url: `https://example.com/${i}` })).json();
        slugs.add(body.slug);
      }
      assert.equal(slugs.size, 50);
    });

    test('allows two links to the same target', async () => {
      const a = await postLink(origin(), { url: 'https://same.example' });
      const b = await postLink(origin(), { url: 'https://same.example' });
      assert.equal(a.status, 201);
      assert.equal(b.status, 201);
      assert.notEqual((await a.json()).slug, (await b.json()).slug);
    });

    test('accepts a URL of exactly 2048 characters', async () => {
      const url = `https://example.com/${'a'.repeat(2048 - 'https://example.com/'.length)}`;
      assert.equal(url.length, 2048);
      const res = await postLink(origin(), { url });
      assert.equal(res.status, 201);
    });

    test('treats a null slug as absent', async () => {
      const res = await postLink(origin(), { url: 'https://example.com', slug: null });
      assert.equal(res.status, 201);
      assert.match((await res.json()).slug, /^[A-Za-z0-9]{8}$/);
    });

    const invalidUrls = [
      ['a non-http scheme', 'ftp://example.com/file'],
      ['javascript scheme', 'javascript:alert(1)'],
      ['a relative URL', '/just/a/path'],
      ['a bare hostname', 'example.com'],
      ['whitespace inside', 'https://example.com/has space'],
      ['a control character', 'https://example.com/\r\nX-Injected: 1'],
      ['non-ASCII characters', 'https://example.com/café'],
      ['a URL over 2048 characters', `https://example.com/${'a'.repeat(2049)}`],
      ['a number', 12345],
      ['a missing url', undefined],
    ];

    for (const [label, url] of invalidUrls) {
      test(`rejects ${label} with 400`, async () => {
        const res = await postLink(origin(), url === undefined ? {} : { url });
        assert.equal(res.status, 400);
        assert.equal(res.headers.get('content-type'), 'application/json; charset=utf-8');
        assert.ok((await res.json()).error);
      });
    }

    const invalidSlugs = [
      ['too short', 'ab'],
      ['too long', 'a'.repeat(33)],
      ['containing a space', 'bad slug'],
      ['containing a slash', 'bad/slug'],
      ['containing a dot', 'bad.slug'],
      ['non-ASCII', 'cafés'],
      ['a number', 123456],
      ['reserved "api"', 'api'],
      ['reserved "healthz"', 'healthz'],
    ];

    for (const [label, slug] of invalidSlugs) {
      test(`rejects a slug that is ${label} with 400`, async () => {
        const res = await postLink(origin(), { url: 'https://example.com', slug });
        assert.equal(res.status, 400);
        assert.ok((await res.json()).error);
      });
    }

    test('accepts slugs at the 3 and 32 character boundaries', async () => {
      const short = await postLink(origin(), { url: 'https://example.com', slug: 'abc' });
      const long = await postLink(origin(), { url: 'https://example.com', slug: 'a'.repeat(32) });
      assert.equal(short.status, 201);
      assert.equal(long.status, 201);
    });

    test('rejects malformed JSON with 400', async () => {
      const res = await postLink(origin(), '{"url": ');
      assert.equal(res.status, 400);
      assert.match((await res.json()).error, /valid JSON/);
    });

    test('rejects a JSON body that is not an object with 400', async () => {
      const res = await postLink(origin(), '["https://example.com"]');
      assert.equal(res.status, 400);
    });

    test('rejects an empty body with 400', async () => {
      const res = await postLink(origin(), '');
      assert.equal(res.status, 400);
    });

    test('rejects a body over the size limit with 413', async () => {
      const padding = 'x'.repeat(16 * 1024);
      const res = await postLink(origin(), { url: 'https://example.com', padding });
      assert.equal(res.status, 413);
    });

    test('accepts a body without a JSON content type', async () => {
      const res = await fetch(`${origin()}/api/links`, {
        method: 'POST',
        headers: authHeader(),
        body: JSON.stringify({ url: 'https://example.com/plain' }),
      });
      assert.equal(res.status, 201);
    });
  });

  describe('authentication on write endpoints', () => {
    test('POST without Authorization returns 401', async () => {
      const res = await fetch(`${origin()}/api/links`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: 'https://example.com' }),
      });
      assert.equal(res.status, 401);
      assert.equal(res.headers.get('www-authenticate'), 'Bearer');
    });

    test('POST with a wrong token returns 401', async () => {
      const res = await postLink(origin(), { url: 'https://example.com' }, authHeader('wrong'));
      assert.equal(res.status, 401);
    });

    test('POST with a non-Bearer scheme returns 401', async () => {
      const res = await postLink(origin(), { url: 'https://example.com' }, {
        Authorization: `Basic ${TOKEN}`,
      });
      assert.equal(res.status, 401);
    });

    test('POST with a token prefix of the real token returns 401', async () => {
      const res = await postLink(origin(), { url: 'https://example.com' }, authHeader(TOKEN.slice(0, -1)));
      assert.equal(res.status, 401);
    });

    test('DELETE without Authorization returns 401 and keeps the link', async () => {
      const created = await (await postLink(origin(), { url: 'https://example.com', slug: 'keep-me' })).json();
      const res = await fetch(`${origin()}/api/links/${created.slug}`, { method: 'DELETE' });
      assert.equal(res.status, 401);

      const still = await fetch(`${origin()}/api/links/${created.slug}`);
      assert.equal(still.status, 200);
    });
  });

  describe('GET /:slug', () => {
    test('redirects with 302 to the target and counts the visit', async () => {
      const created = await (await postLink(origin(), { url: 'https://redirect.example/path', slug: 'redir-1' })).json();

      const res = await visit(origin(), created.slug);
      assert.equal(res.status, 302);
      assert.equal(res.headers.get('location'), 'https://redirect.example/path');
      assert.equal(res.headers.get('cache-control'), 'no-store');

      const meta = await (await fetch(`${origin()}/api/links/${created.slug}`)).json();
      assert.equal(meta.visits, 1);
    });

    test('returns 404 for an unknown slug', async () => {
      const res = await visit(origin(), 'no-such-slug');
      assert.equal(res.status, 404);
      assert.equal(res.headers.get('content-type'), 'application/json; charset=utf-8');
    });

    test('returns 404 for a slug with invalid characters without touching the store', async () => {
      const res = await visit(origin(), 'bad%20slug');
      assert.equal(res.status, 404);
    });
  });

  describe('GET /api/links/:slug', () => {
    test('returns metadata including visits, without auth', async () => {
      const created = await (await postLink(origin(), { url: 'https://meta.example', slug: 'meta-1' })).json();
      await visit(origin(), created.slug);
      await visit(origin(), created.slug);
      await visit(origin(), created.slug);

      const res = await fetch(`${origin()}/api/links/${created.slug}`);
      assert.equal(res.status, 200);
      assert.deepEqual(await res.json(), {
        slug: 'meta-1',
        url: 'https://meta.example',
        short_url: `${BASE_URL}/meta-1`,
        created_at: created.created_at,
        visits: 3,
      });
    });

    test('returns 404 for an unknown slug', async () => {
      const res = await fetch(`${origin()}/api/links/missing-slug`);
      assert.equal(res.status, 404);
    });

    test('returns 404 for a malformed slug', async () => {
      const res = await fetch(`${origin()}/api/links/ab`);
      assert.equal(res.status, 404);
    });
  });

  describe('DELETE /api/links/:slug', () => {
    test('deletes a link with a valid token and returns 204', async () => {
      await postLink(origin(), { url: 'https://gone.example', slug: 'gone-1' });

      const res = await fetch(`${origin()}/api/links/gone-1`, {
        method: 'DELETE',
        headers: authHeader(),
      });
      assert.equal(res.status, 204);

      assert.equal((await visit(origin(), 'gone-1')).status, 404);
      assert.equal((await fetch(`${origin()}/api/links/gone-1`)).status, 404);
    });

    test('returns 404 when the link does not exist', async () => {
      const res = await fetch(`${origin()}/api/links/never-existed`, {
        method: 'DELETE',
        headers: authHeader(),
      });
      assert.equal(res.status, 404);
    });
  });

  describe('routing', () => {
    test('unknown paths return 404', async () => {
      assert.equal((await fetch(`${origin()}/a/b/c`)).status, 404);
      assert.equal((await fetch(`${origin()}/api/links/x/y`)).status, 404);
      assert.equal((await fetch(`${origin()}/`)).status, 404);
    });

    test('unsupported methods return 405 with an Allow header', async () => {
      const put = await fetch(`${origin()}/api/links/anything`, { method: 'PUT', headers: authHeader() });
      assert.equal(put.status, 405);
      assert.equal(put.headers.get('allow'), 'GET, DELETE');

      const getCreate = await fetch(`${origin()}/api/links`);
      assert.equal(getCreate.status, 405);
      assert.equal(getCreate.headers.get('allow'), 'POST');
    });
  });
});

describe('persistence across restarts', () => {
  test('links and visit counts survive a restart', async () => {
    // The test owns the directory so that stopping a server does not delete the database.
    const dir = mkdtempSync(join(tmpdir(), 'snip-restart-'));
    try {
      const first = await startServer({ dir });
      try {
        const created = await (await postLink(first.origin, { url: 'https://durable.example', slug: 'durable' })).json();
        await visit(first.origin, created.slug);
        await visit(first.origin, created.slug);
      } finally {
        await first.stop();
      }

      await restartAndCheck(dir);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

async function restartAndCheck(dir) {
  const second = await startServer({ dir });
  try {
    const meta = await (await fetch(`${second.origin}/api/links/durable`)).json();
    assert.equal(meta.url, 'https://durable.example');
    assert.equal(meta.visits, 2);

    const res = await visit(second.origin, 'durable');
    assert.equal(res.status, 302);
    assert.equal(res.headers.get('location'), 'https://durable.example');
  } finally {
    await second.stop();
  }
}

describe('without a configured API token', () => {
  test('every write request is rejected with 401', async () => {
    const server = await startServer({ apiToken: null });
    try {
      const create = await postLink(server.origin, { url: 'https://example.com' }, authHeader('anything'));
      assert.equal(create.status, 401);

      const remove = await fetch(`${server.origin}/api/links/whatever`, {
        method: 'DELETE',
        headers: authHeader('anything'),
      });
      assert.equal(remove.status, 401);
    } finally {
      await server.stop();
    }
  });
});
