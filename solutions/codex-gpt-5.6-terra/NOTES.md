# Notes

This implementation uses Node.js’s built-in HTTP server and test runner, with
no runtime dependencies. Links live in a locally persisted JSON file; each
mutation writes a temporary file and atomically replaces the database file.
Slugs use cryptographic randomness, while custom slugs are validated strictly.

Run the service with `SNIP_API_TOKEN='secret' npm start`. Run all tests with
`npm test`.

Known gap: the JSON store is designed for one local server process and does not
coordinate concurrent processes that share the same data file. For multi-process
deployment, use a transactional local database or external datastore.
