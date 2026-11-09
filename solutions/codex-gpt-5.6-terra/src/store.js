import { mkdirSync, readFileSync, renameSync, unlinkSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { randomUUID } from 'node:crypto';

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

/** A small synchronous store so each mutation is durable before its response. */
export class LinkStore {
  constructor(filePath) {
    this.filePath = filePath;
    this.database = this.#load();
  }

  #load() {
    try {
      const parsed = JSON.parse(readFileSync(this.filePath, 'utf8'));
      if (parsed?.version !== 1 || !parsed.links || typeof parsed.links !== 'object' || Array.isArray(parsed.links)) {
        throw new Error('unsupported database format');
      }
      // A null-prototype dictionary makes allowed slugs such as "__proto__" safe.
      return { version: 1, links: Object.assign(Object.create(null), parsed.links) };
    } catch (error) {
      if (error.code === 'ENOENT') return { version: 1, links: Object.create(null) };
      throw new Error(`Could not load SNIP_DATA_FILE: ${error.message}`);
    }
  }

  #save() {
    mkdirSync(dirname(this.filePath), { recursive: true });
    const temporaryPath = `${this.filePath}.${process.pid}.${randomUUID()}.tmp`;
    try {
      writeFileSync(temporaryPath, `${JSON.stringify(this.database)}\n`, { encoding: 'utf8', mode: 0o600 });
      renameSync(temporaryPath, this.filePath);
    } catch (error) {
      try { unlinkSync(temporaryPath); } catch {}
      throw error;
    }
  }

  get(slug) {
    const link = this.database.links[slug];
    return link ? clone(link) : null;
  }

  has(slug) {
    return Object.hasOwn(this.database.links, slug);
  }

  create(link) {
    if (this.has(link.slug)) return false;
    this.database.links[link.slug] = { ...link, visits: 0 };
    this.#save();
    return true;
  }

  recordVisit(slug) {
    const link = this.database.links[slug];
    if (!link) return null;
    link.visits += 1;
    this.#save();
    return clone(link);
  }

  delete(slug) {
    if (!this.has(slug)) return false;
    delete this.database.links[slug];
    this.#save();
    return true;
  }
}
