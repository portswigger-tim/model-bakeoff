import { mkdirSync } from 'node:fs';
import { dirname } from 'node:path';
import { DatabaseSync } from 'node:sqlite';

// SQLite result codes for a primary-key or unique constraint violation.
const SQLITE_CONSTRAINT_PRIMARYKEY = 1555;
const SQLITE_CONSTRAINT_UNIQUE = 2067;

export class SlugTakenError extends Error {
  constructor(slug) {
    super(`slug "${slug}" is already taken`);
    this.name = 'SlugTakenError';
  }
}

/**
 * SQLite-backed link storage. node:sqlite is synchronous, so each statement
 * runs to completion before the next request is handled and the visit counter
 * needs no extra locking.
 */
export class LinkStore {
  constructor(dbPath) {
    if (dbPath !== ':memory:') {
      mkdirSync(dirname(dbPath), { recursive: true });
    }

    this.db = new DatabaseSync(dbPath);
    this.db.exec(`
      PRAGMA journal_mode = WAL;
      PRAGMA busy_timeout = 5000;
      PRAGMA synchronous = NORMAL;

      CREATE TABLE IF NOT EXISTS links (
        slug       TEXT PRIMARY KEY,
        url        TEXT NOT NULL,
        created_at TEXT NOT NULL,
        visits     INTEGER NOT NULL DEFAULT 0 CHECK (visits >= 0)
      );
    `);

    this.insertStmt = this.db.prepare(
      'INSERT INTO links (slug, url, created_at, visits) VALUES (?, ?, ?, 0)',
    );
    this.selectStmt = this.db.prepare(
      'SELECT slug, url, created_at, visits FROM links WHERE slug = ?',
    );
    this.visitStmt = this.db.prepare(
      'UPDATE links SET visits = visits + 1 WHERE slug = ? RETURNING url',
    );
    this.deleteStmt = this.db.prepare('DELETE FROM links WHERE slug = ?');
  }

  /**
   * Inserts a link. Throws SlugTakenError if the slug already exists; the
   * primary key constraint is the only source of truth for uniqueness.
   */
  insert({ slug, url, createdAt }) {
    try {
      this.insertStmt.run(slug, url, createdAt);
    } catch (err) {
      if (err.errcode === SQLITE_CONSTRAINT_PRIMARYKEY || err.errcode === SQLITE_CONSTRAINT_UNIQUE) {
        throw new SlugTakenError(slug);
      }
      throw err;
    }
    return this.findBySlug(slug);
  }

  findBySlug(slug) {
    const row = this.selectStmt.get(slug);
    return row ? toLink(row) : undefined;
  }

  /**
   * Atomically counts a visit and returns the target URL, or undefined when
   * the slug does not exist.
   */
  recordVisit(slug) {
    const row = this.visitStmt.get(slug);
    return row?.url;
  }

  delete(slug) {
    return this.deleteStmt.run(slug).changes > 0;
  }

  ping() {
    this.db.prepare('SELECT 1').get();
  }

  close() {
    this.db.close();
  }
}

function toLink(row) {
  return {
    slug: row.slug,
    url: row.url,
    createdAt: row.created_at,
    visits: row.visits,
  };
}
