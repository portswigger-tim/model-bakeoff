import { HttpError } from './errors.js';

export const MAX_URL_LENGTH = 2048;
export const MIN_SLUG_LENGTH = 3;
export const MAX_SLUG_LENGTH = 32;

const SLUG_PATTERN = new RegExp(`^[A-Za-z0-9_-]{${MIN_SLUG_LENGTH},${MAX_SLUG_LENGTH}}$`);

// Paths that the router owns; a link with one of these slugs could never be
// reached through GET /{slug}.
const RESERVED_SLUGS = new Set(['api', 'healthz']);

// Printable ASCII only. This rules out whitespace and control characters,
// which would be header-injection vectors in the Location header, and
// non-ASCII characters, which Node refuses to put in headers.
const PRINTABLE_ASCII = /^[\x21-\x7E]+$/;

export function isSlugFormat(value) {
  return typeof value === 'string' && SLUG_PATTERN.test(value);
}

/**
 * Validates a target URL. Returns the value unchanged so that the link is
 * stored and echoed back exactly as the client sent it.
 */
export function validateUrl(value) {
  if (typeof value !== 'string') {
    throw new HttpError(400, 'url must be a string');
  }
  if (value.length > MAX_URL_LENGTH) {
    throw new HttpError(400, `url must be at most ${MAX_URL_LENGTH} characters`);
  }
  if (!PRINTABLE_ASCII.test(value)) {
    throw new HttpError(400, 'url must contain only printable ASCII with no whitespace (percent-encode other characters)');
  }

  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new HttpError(400, 'url must be an absolute URL');
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new HttpError(400, 'url must use the http or https scheme');
  }

  return value;
}

/**
 * Validates a client-chosen slug. Returns the value unchanged.
 */
export function validateCustomSlug(value) {
  if (typeof value !== 'string') {
    throw new HttpError(400, 'slug must be a string');
  }
  if (!SLUG_PATTERN.test(value)) {
    throw new HttpError(
      400,
      `slug must be ${MIN_SLUG_LENGTH}-${MAX_SLUG_LENGTH} characters from A-Z, a-z, 0-9, "_" and "-"`,
    );
  }
  if (RESERVED_SLUGS.has(value)) {
    throw new HttpError(400, `slug "${value}" is reserved`);
  }
  return value;
}
