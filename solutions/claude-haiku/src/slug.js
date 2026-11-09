import { randomInt } from 'node:crypto';

export const GENERATED_SLUG_LENGTH = 8;

const ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';

/**
 * Returns a random base62 slug. randomInt draws uniformly, so there is no
 * modulo bias. 8 characters gives about 47 bits of entropy.
 */
export function generateSlug(length = GENERATED_SLUG_LENGTH) {
  let slug = '';
  for (let i = 0; i < length; i += 1) {
    slug += ALPHABET[randomInt(ALPHABET.length)];
  }
  return slug;
}
