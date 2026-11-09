import assert from 'node:assert/strict';
import { afterEach, test } from 'node:test';
import { createServer } from 'node:http';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createApp } from '../src/app.js';
import { LinkStore } from '../src/store.js';

const instances = [];

async function start({ token = 'test-secret', dataFile, publicBaseUrl } = {}) {
  const directory = await mkdtemp(join(tmpdir(), 'snip-test-'));
  const file = dataFile ?? join(directory, 'links.json');
  const server = createServer(createApp({
    store: new LinkStore(file),
    apiToken: token,
    publicBaseUrl
  }));
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  const baseUrl = `http://127.0.0.1:${address.port}`;
  const close = async () => {
    await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    await rm(directory, { recursive: true, force: true });
  };
  instances.push(close);
  return { baseUrl, file, close };
}

afterEach(async () => {
  while (instances.length) await instances.pop()();
});

function auth(token = 'test-secret') {
  return { authorization: `Bearer ${token}` };
}

async function json(response) {
  return response.json();
}

test('health endpoint responds successfully', async () => {
  const { baseUrl } = await start();
  const response = await fetch(`${baseUrl}/healthz`);
  assert.equal(response.status, 200);
  assert.deepEqual(await json(response), { status: 'ok' });
});

test('creates a custom short link and exposes its metadata', async () => {
  const { baseUrl } = await start();
  const response = await fetch(`${baseUrl}/api/links`, {
    method: 'POST',
    headers: { ...auth(), 'content-type': 'application/json' },
    body: JSON.stringify({ url: 'https://example.com/path?q=1', slug: 'hello_1' })
  });
  assert.equal(response.status, 201);
  const created = await json(response);
  assert.deepEqual(Object.keys(created).sort(), ['created_at', 'short_url', 'slug', 'url']);
  assert.equal(created.slug, 'hello_1');
  assert.equal(created.url, 'https://example.com/path?q=1');
  assert.equal(created.short_url, `${baseUrl}/hello_1`);
  assert.ok(Number.isFinite(Date.parse(created.created_at)));

  const metadataResponse = await fetch(`${baseUrl}/api/links/hello_1`);
  assert.equal(metadataResponse.status, 200);
  assert.deepEqual(await json(metadataResponse), { ...created, visits: 0 });
});

test('generates URL-safe unique slugs', async () => {
  const { baseUrl } = await start();
  const create = () => fetch(`${baseUrl}/api/links`, {
    method: 'POST',
    headers: { ...auth(), 'content-type': 'application/json' },
    body: JSON.stringify({ url: 'https://example.com' })
  });
  const [one, two] = await Promise.all([create(), create()]);
  const first = await json(one);
  const second = await json(two);
  assert.match(first.slug, /^[A-Za-z0-9_-]{12}$/);
  assert.match(second.slug, /^[A-Za-z0-9_-]{12}$/);
  assert.notEqual(first.slug, second.slug);
});

test('rejects missing or invalid authentication for writes', async () => {
  const { baseUrl } = await start();
  for (const headers of [{}, auth('wrong')]) {
    const response = await fetch(`${baseUrl}/api/links`, {
      method: 'POST',
      headers: { ...headers, 'content-type': 'application/json' },
      body: JSON.stringify({ url: 'https://example.com' })
    });
    assert.equal(response.status, 401);
    assert.deepEqual(await json(response), { error: 'Unauthorized' });
  }
});

test('validates target URLs and custom slugs', async () => {
  const { baseUrl } = await start();
  const cases = [
    { url: 'javascript:alert(1)' },
    { url: '/relative/path' },
    { url: 'ftp://example.com' },
    { url: 'https://example.com', slug: 'no spaces' },
    { url: 'https://example.com', slug: 'aa' },
    { url: 'https://example.com', slug: 'a'.repeat(33) },
    { url: 'x'.repeat(2049) }
  ];
  for (const payload of cases) {
    const response = await fetch(`${baseUrl}/api/links`, {
      method: 'POST',
      headers: { ...auth(), 'content-type': 'application/json' },
      body: JSON.stringify(payload)
    });
    assert.equal(response.status, 400, JSON.stringify(payload));
    assert.equal(typeof (await json(response)).error, 'string');
  }
});

test('handles malformed JSON and a prototype-like valid slug safely', async () => {
  const { baseUrl } = await start();
  const malformed = await fetch(`${baseUrl}/api/links`, {
    method: 'POST', headers: { ...auth(), 'content-type': 'application/json' }, body: '{'
  });
  assert.equal(malformed.status, 400);

  const create = await fetch(`${baseUrl}/api/links`, {
    method: 'POST', headers: { ...auth(), 'content-type': 'application/json' },
    body: JSON.stringify({ url: 'https://example.com', slug: '__proto__' })
  });
  assert.equal(create.status, 201);
  assert.equal((await fetch(`${baseUrl}/api/links/__proto__`)).status, 200);
});

test('reports duplicate slugs as a conflict', async () => {
  const { baseUrl } = await start();
  const options = {
    method: 'POST', headers: { ...auth(), 'content-type': 'application/json' },
    body: JSON.stringify({ url: 'https://example.com', slug: 'taken' })
  };
  assert.equal((await fetch(`${baseUrl}/api/links`, options)).status, 201);
  const duplicate = await fetch(`${baseUrl}/api/links`, options);
  assert.equal(duplicate.status, 409);
  assert.deepEqual(await json(duplicate), { error: 'Slug is already in use' });
});

test('redirects and increments visits', async () => {
  const { baseUrl } = await start();
  await fetch(`${baseUrl}/api/links`, {
    method: 'POST', headers: { ...auth(), 'content-type': 'application/json' },
    body: JSON.stringify({ url: 'https://example.com/landing', slug: 'visit-me' })
  });
  const redirect = await fetch(`${baseUrl}/visit-me`, { redirect: 'manual' });
  assert.equal(redirect.status, 302);
  assert.equal(redirect.headers.get('location'), 'https://example.com/landing');

  const metadata = await fetch(`${baseUrl}/api/links/visit-me`);
  assert.equal((await json(metadata)).visits, 1);
  const missing = await fetch(`${baseUrl}/does-not-exist`, { redirect: 'manual' });
  assert.equal(missing.status, 404);
});

test('deletes only with authorization and returns 404 thereafter', async () => {
  const { baseUrl } = await start();
  await fetch(`${baseUrl}/api/links`, {
    method: 'POST', headers: { ...auth(), 'content-type': 'application/json' },
    body: JSON.stringify({ url: 'https://example.com', slug: 'remove-me' })
  });
  assert.equal((await fetch(`${baseUrl}/api/links/remove-me`, { method: 'DELETE' })).status, 401);
  assert.equal((await fetch(`${baseUrl}/api/links/remove-me`, { method: 'DELETE', headers: auth() })).status, 204);
  assert.equal((await fetch(`${baseUrl}/api/links/remove-me`)).status, 404);
});

test('keeps links and visits after a store is recreated', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'snip-restart-'));
  const persistentFile = join(directory, 'persistent.json');
  const seed = await start({ dataFile: persistentFile });
  await fetch(`${seed.baseUrl}/api/links`, {
    method: 'POST', headers: { ...auth(), 'content-type': 'application/json' },
    body: JSON.stringify({ url: 'https://example.com/saved', slug: 'persisted' })
  });
  await fetch(`${seed.baseUrl}/persisted`, { redirect: 'manual' });
  await seed.close();
  instances.pop();

  const server = createServer(createApp({ store: new LinkStore(persistentFile), apiToken: 'test-secret' }));
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  const response = await fetch(`http://127.0.0.1:${address.port}/api/links/persisted`);
  assert.equal((await json(response)).visits, 1);
  await new Promise((resolve) => server.close(resolve));
  await rm(directory, { recursive: true, force: true });
});

test('uses the configured public base URL in responses', async () => {
  const { baseUrl } = await start({ publicBaseUrl: 'https://s.example.test/prefix' });
  const response = await fetch(`${baseUrl}/api/links`, {
    method: 'POST', headers: { ...auth(), 'content-type': 'application/json' },
    body: JSON.stringify({ url: 'https://example.com', slug: 'public-link' })
  });
  assert.equal((await json(response)).short_url, 'https://s.example.test/public-link');
});
