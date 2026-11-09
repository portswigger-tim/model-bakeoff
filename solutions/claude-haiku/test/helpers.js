import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createApp } from '../src/app.js';
import { LinkStore } from '../src/store.js';

export const TOKEN = 'test-token-value';
export const BASE_URL = 'http://snip.test';

/**
 * Starts a real server on an ephemeral port backed by a temporary SQLite file.
 * Pass an existing dbPath (and its directory) to reuse data across restarts.
 */
export async function startServer({ apiToken = TOKEN, dir, dbPath } = {}) {
  const ownsDir = !dir;
  const dataDir = dir ?? mkdtempSync(join(tmpdir(), 'snip-test-'));
  const path = dbPath ?? join(dataDir, 'snip.db');

  const store = new LinkStore(path);
  const server = createApp({ store, baseUrl: BASE_URL, apiToken });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));

  const origin = `http://127.0.0.1:${server.address().port}`;

  return {
    origin,
    dbPath: path,
    dir: dataDir,
    async stop() {
      const closed = new Promise((resolve) => server.close(resolve));
      server.closeAllConnections();
      await closed;
      store.close();
      if (ownsDir) {
        rmSync(dataDir, { recursive: true, force: true });
      }
    },
  };
}

export function authHeader(token = TOKEN) {
  return { Authorization: `Bearer ${token}` };
}

export function postLink(origin, body, headers = {}) {
  return fetch(`${origin}/api/links`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeader(), ...headers },
    body: typeof body === 'string' ? body : JSON.stringify(body),
  });
}

/**
 * Fetches without following redirects so the 302 itself can be asserted.
 * The body is drained so the keep-alive socket is released.
 */
export async function visit(origin, slug) {
  const res = await fetch(`${origin}/${slug}`, { redirect: 'manual' });
  await res.arrayBuffer();
  return res;
}
