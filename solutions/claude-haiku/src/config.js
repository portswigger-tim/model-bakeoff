import { resolve } from 'node:path';

export const DEFAULT_PORT = 3000;
export const DEFAULT_DB_PATH = 'data/snip.db';

/**
 * Reads runtime configuration from environment variables.
 *
 *   PORT              HTTP port (default 3000)
 *   SNIP_API_TOKEN    bearer token required by POST and DELETE; unset means
 *                     those endpoints reject every request
 *   SNIP_DB_PATH      SQLite file location (default data/snip.db)
 *   SNIP_BASE_URL     public origin used to build short_url (default http://localhost:PORT)
 */
export function loadConfig(env = process.env) {
  const port = parsePort(env.PORT || String(DEFAULT_PORT));
  const apiToken = env.SNIP_API_TOKEN || null;
  const dbPath = resolve(env.SNIP_DB_PATH || DEFAULT_DB_PATH);
  const baseUrl = parseBaseUrl(env.SNIP_BASE_URL || `http://localhost:${port}`);

  return { port, apiToken, dbPath, baseUrl };
}

function parsePort(value) {
  const port = Number(value);
  if (!/^\d+$/.test(value) || port < 1 || port > 65535) {
    throw new Error(`PORT must be an integer between 1 and 65535, got "${value}"`);
  }
  return port;
}

function parseBaseUrl(value) {
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error(`SNIP_BASE_URL must be an absolute URL, got "${value}"`);
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new Error('SNIP_BASE_URL must use http or https');
  }
  return value.replace(/\/+$/, '');
}
