# snip

`snip` is a small HTTP URL-shortener with token-protected writes and local JSON
storage. It has no runtime dependencies and requires Node.js 20 or later.

## Run it

```sh
npm install
SNIP_API_TOKEN='choose-a-long-random-secret' npm start
```

The service listens on port `3000` by default and persists links to
`./data/snip.json`. The data file is written by replacing it atomically, so a
completed write survives a process restart. Do not run several server processes
against the same file; this simple local store is for a single service process.

Configuration:

| Variable | Default | Purpose |
| --- | --- | --- |
| `SNIP_API_TOKEN` | unset (writes denied) | Bearer token required by POST and DELETE |
| `PORT` | `3000` | TCP port to listen on |
| `SNIP_DATA_FILE` | `./data/snip.json` | Local JSON database path |
| `SNIP_PUBLIC_BASE_URL` | request origin | Public base URL used to construct `short_url` |

For example, create a link:

```sh
curl -X POST http://localhost:3000/api/links \
  -H "Authorization: Bearer $SNIP_API_TOKEN" \
  -H 'Content-Type: application/json' \
  --data '{"url":"https://example.com/docs","slug":"docs"}'
```

The API accepts only absolute `http` or `https` targets up to 2048 characters.
Custom slugs must be 3–32 characters of letters, digits, `_`, or `-`.
Generated slugs have 72 bits of cryptographic randomness.

Endpoints:

- `POST /api/links` — create a link (`201`)
- `GET /api/links/{slug}` — read metadata and visit count
- `DELETE /api/links/{slug}` — delete a link (`204`, requires Bearer token)
- `GET /{slug}` — redirect with `302` and record a visit
- `GET /healthz` — liveness endpoint

Errors are JSON objects such as `{"error":"Link not found"}`. Missing or
incorrect credentials return `401`; an occupied custom slug returns `409`.

## Test

```sh
npm test
```
