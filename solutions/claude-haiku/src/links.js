import { HttpError } from './errors.js';
import { generateSlug } from './slug.js';
import { SlugTakenError } from './store.js';
import { validateCustomSlug, validateUrl } from './validation.js';

// Random slugs can collide. With ~47 bits of entropy this almost never
// happens, but retrying keeps the guarantee explicit.
const MAX_GENERATED_SLUG_ATTEMPTS = 5;

/**
 * Creates a link. A custom slug that is taken yields 409; a generated slug
 * that collides is retried with a fresh random value.
 */
export function createLink(store, baseUrl, { url, slug }) {
  validateUrl(url);

  if (slug !== undefined && slug !== null) {
    validateCustomSlug(slug);
    const link = tryInsert(store, slug, url);
    if (!link) {
      throw new HttpError(409, `slug "${slug}" is already taken`);
    }
    return toCreateResponse(link, baseUrl);
  }

  for (let attempt = 0; attempt < MAX_GENERATED_SLUG_ATTEMPTS; attempt += 1) {
    const link = tryInsert(store, generateSlug(), url);
    if (link) {
      return toCreateResponse(link, baseUrl);
    }
  }
  throw new Error('could not generate a unique slug');
}

export function getLink(store, baseUrl, slug) {
  const link = store.findBySlug(slug);
  if (!link) {
    throw new HttpError(404, 'link not found');
  }
  return { ...toCreateResponse(link, baseUrl), visits: link.visits };
}

export function deleteLink(store, slug) {
  if (!store.delete(slug)) {
    throw new HttpError(404, 'link not found');
  }
}

function tryInsert(store, slug, url) {
  try {
    return store.insert({ slug, url, createdAt: new Date().toISOString() });
  } catch (err) {
    if (err instanceof SlugTakenError) {
      return null;
    }
    throw err;
  }
}

function toCreateResponse(link, baseUrl) {
  return {
    slug: link.slug,
    url: link.url,
    short_url: `${baseUrl}/${link.slug}`,
    created_at: link.createdAt,
  };
}
