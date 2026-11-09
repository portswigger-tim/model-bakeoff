import { createHash, timingSafeEqual } from 'node:crypto';

const BEARER_PATTERN = /^Bearer\s+(\S+)$/i;

/**
 * Checks an Authorization header against the configured API token.
 *
 * Both sides are hashed first so that timingSafeEqual always compares equal
 * lengths and the comparison leaks nothing about the token's length. With no
 * token configured, every request is rejected.
 */
export function isAuthorized(authorizationHeader, expectedToken) {
  if (!expectedToken || typeof authorizationHeader !== 'string') {
    return false;
  }
  const match = BEARER_PATTERN.exec(authorizationHeader);
  if (!match) {
    return false;
  }

  const provided = createHash('sha256').update(match[1]).digest();
  const expected = createHash('sha256').update(expectedToken).digest();
  return timingSafeEqual(provided, expected);
}
