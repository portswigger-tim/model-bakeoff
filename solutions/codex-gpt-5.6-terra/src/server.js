import http from 'node:http';
import { resolve } from 'node:path';
import { createApp } from './app.js';
import { LinkStore } from './store.js';

const port = Number.parseInt(process.env.PORT ?? '3000', 10);
if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('PORT must be an integer between 1 and 65535');

const dataFile = resolve(process.env.SNIP_DATA_FILE ?? './data/snip.json');
const publicBaseUrl = process.env.SNIP_PUBLIC_BASE_URL;
if (publicBaseUrl) {
  const parsed = new URL(publicBaseUrl);
  if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('SNIP_PUBLIC_BASE_URL must be an http(s) URL');
}

const store = new LinkStore(dataFile);
const app = createApp({ store, apiToken: process.env.SNIP_API_TOKEN, publicBaseUrl });
const server = http.createServer(app);

server.listen(port, () => {
  console.log(`snip listening on port ${port}`);
});

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
