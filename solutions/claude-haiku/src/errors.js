/**
 * An error that maps directly onto an HTTP response.
 * Anything thrown as a non-HttpError is treated as a 500.
 */
export class HttpError extends Error {
  constructor(status, message, headers = {}) {
    super(message);
    this.name = 'HttpError';
    this.status = status;
    this.headers = headers;
  }
}
