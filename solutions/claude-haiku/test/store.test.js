import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, before, beforeEach, describe, test } from 'node:test';
import { LinkStore, SlugTakenError } from '../src/store.js';

describe('LinkStore', () => {
  let dir;
  let store;

  before(() => {
    dir = mkdtempSync(join(tmpdir(), 'snip-store-'));
  });

  beforeEach(() => {
    store?.close();
    store = new LinkStore(join(dir, `${Date.now()}-${Math.random()}.db`));
  });

  after(() => {
    store?.close();
    rmSync(dir, { recursive: true, force: true });
  });

  const link = (overrides = {}) => ({
    slug: 'abc123',
    url: 'https://example.com',
    createdAt: '2026-01-01T00:00:00.000Z',
    ...overrides,
  });

  test('insert returns the stored link with zero visits', () => {
    const stored = store.insert(link());
    assert.deepEqual(stored, {
      slug: 'abc123',
      url: 'https://example.com',
      createdAt: '2026-01-01T00:00:00.000Z',
      visits: 0,
    });
  });

  test('insert throws SlugTakenError on a duplicate slug', () => {
    store.insert(link());
    assert.throws(() => store.insert(link({ url: 'https://other.example' })), SlugTakenError);
    assert.equal(store.findBySlug('abc123').url, 'https://example.com');
  });

  test('findBySlug returns undefined for a missing slug', () => {
    assert.equal(store.findBySlug('nope'), undefined);
  });

  test('recordVisit increments the counter and returns the target', () => {
    store.insert(link());
    assert.equal(store.recordVisit('abc123'), 'https://example.com');
    assert.equal(store.recordVisit('abc123'), 'https://example.com');
    assert.equal(store.findBySlug('abc123').visits, 2);
  });

  test('recordVisit returns undefined for a missing slug', () => {
    assert.equal(store.recordVisit('nope'), undefined);
  });

  test('delete reports whether a row was removed', () => {
    store.insert(link());
    assert.equal(store.delete('abc123'), true);
    assert.equal(store.delete('abc123'), false);
    assert.equal(store.findBySlug('abc123'), undefined);
  });

  test('ping succeeds on an open database', () => {
    assert.doesNotThrow(() => store.ping());
  });

  test('data persists when the database is reopened', () => {
    const path = join(dir, 'reopen.db');
    const first = new LinkStore(path);
    first.insert(link({ slug: 'keep1' }));
    first.recordVisit('keep1');
    first.close();

    const second = new LinkStore(path);
    try {
      const stored = second.findBySlug('keep1');
      assert.equal(stored.url, 'https://example.com');
      assert.equal(stored.visits, 1);
    } finally {
      second.close();
    }
  });
});
