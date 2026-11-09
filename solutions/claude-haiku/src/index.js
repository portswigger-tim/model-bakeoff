#!/usr/bin/env node
import { createApp } from './app.js';
import { loadConfig } from './config.js';
import { LinkStore } from './store.js';

const SHUTDOWN_SIGNALS = ['SIGINT', 'SIGTERM'];

function main() {
  const config = loadConfig();

  if (!config.apiToken) {
    console.warn('SNIP_API_TOKEN is not set: POST and DELETE will return 401 until it is.');
  }

  const store = new LinkStore(config.dbPath);
  const server = createApp({
    store,
    baseUrl: config.baseUrl,
    apiToken: config.apiToken,
  });

  server.listen(config.port, () => {
    console.log(`snip listening on port ${config.port}, data in ${config.dbPath}`);
  });

  for (const signal of SHUTDOWN_SIGNALS) {
    process.once(signal, () => {
      console.log(`${signal} received, shutting down`);
      server.close(() => {
        store.close();
        process.exit(0);
      });
    });
  }
}

try {
  main();
} catch (err) {
  console.error(`snip: ${err.message}`);
  process.exit(1);
}
