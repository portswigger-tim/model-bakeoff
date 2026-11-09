import assert from 'node:assert/strict';
import { describe, test } from 'node:test';
import { isAuthorized } from '../src/auth.js';
import { loadConfig } from '../src/config.js';
import { generateSlug } from '../src/slug.js';
import { validateCustomSlug, validateUrl } from '../src/validation.js';

describe('validateUrl', () => {
  test('accepts http and https absolute URLs and returns them unchanged', () => {
    assert.equal(validateUrl('http://example.com'), 'http://example.com');
    assert.equal(validateUrl('https://example.com/path?q=1#frag'), 'https://example.com/path?q=1#frag');
  });

  test('rejects non-http schemes', () => {
    for (const url of ['ftp://x.com', 'file:///etc/passwd', 'data:text/plain,hi', 'mailto:a@b.c']) {
      assert.throws(() => validateUrl(url), { status: 400 }, url);
    }
  });
});

describe('validateCustomSlug', () => {
  test('accepts the allowed alphabet and length range', () => {
    assert.equal(validateCustomSlug('aZ0_-'), 'aZ0_-');
  });

  test('rejects out-of-range lengths and disallowed characters', () => {
    assert.throws(() => validateCustomSlug('ab'), { status: 400 });
    assert.throws(() => validateCustomSlug('a'.repeat(33)), { status: 400 });
    assert.throws(() => validateCustomSlug('has space'), { status: 400 });
    assert.throws(() => validateCustomSlug('dot.dot'), { status: 400 });
  });

  test('rejects reserved slugs', () => {
    assert.throws(() => validateCustomSlug('api'), { status: 400 });
    assert.throws(() => validateCustomSlug('healthz'), { status: 400 });
  });
});

describe('generateSlug', () => {
  test('produces 8 base62 characters by default', () => {
    for (let i = 0; i < 100; i += 1) {
      assert.match(generateSlug(), /^[A-Za-z0-9]{8}$/);
    }
  });

  test('honours a custom length', () => {
    assert.equal(generateSlug(12).length, 12);
  });
});

describe('isAuthorized', () => {
  test('accepts the matching bearer token, case-insensitive scheme', () => {
    assert.equal(isAuthorized('Bearer secret', 'secret'), true);
    assert.equal(isAuthorized('bearer secret', 'secret'), true);
  });

  test('rejects wrong, missing and malformed credentials', () => {
    assert.equal(isAuthorized('Bearer nope', 'secret'), false);
    assert.equal(isAuthorized(undefined, 'secret'), false);
    assert.equal(isAuthorized('Bearer', 'secret'), false);
    assert.equal(isAuthorized('secret', 'secret'), false);
  });

  test('rejects everything when no token is configured', () => {
    assert.equal(isAuthorized('Bearer ', null), false);
    assert.equal(isAuthorized('Bearer x', null), false);
    assert.equal(isAuthorized('Bearer x', ''), false);
  });
});

describe('loadConfig', () => {
  test('applies defaults when nothing is set', () => {
    const config = loadConfig({});
    assert.equal(config.port, 3000);
    assert.equal(config.apiToken, null);
    assert.equal(config.baseUrl, 'http://localhost:3000');
    assert.match(config.dbPath, /data\/snip\.db$/);
  });

  test('reads every variable and strips trailing slashes from the base URL', () => {
    const config = loadConfig({
      PORT: '8080',
      SNIP_API_TOKEN: 'tok',
      SNIP_DB_PATH: '/var/lib/snip/links.db',
      SNIP_BASE_URL: 'https://s.example.com//',
    });
    assert.equal(config.port, 8080);
    assert.equal(config.apiToken, 'tok');
    assert.equal(config.dbPath, '/var/lib/snip/links.db');
    assert.equal(config.baseUrl, 'https://s.example.com');
  });

  test('rejects an invalid PORT', () => {
    for (const PORT of ['0', '65536', 'eighty', '80.5']) {
      assert.throws(() => loadConfig({ PORT }), /PORT/, PORT);
    }
  });

  test('rejects an invalid SNIP_BASE_URL', () => {
    assert.throws(() => loadConfig({ SNIP_BASE_URL: 'snip.example.com' }), /SNIP_BASE_URL/);
    assert.throws(() => loadConfig({ SNIP_BASE_URL: 'ftp://snip.example.com' }), /SNIP_BASE_URL/);
  });
});
