# Brief: "snip" — a small URL-shortener HTTP service

Build a small, production-minded URL-shortener HTTP service. You choose the
language, framework, storage, tooling and project layout.

## Functional requirements
1. `POST /api/links` with JSON body `{"url": "<target>", "slug": "<optional custom slug>"}`
   creates a short link and returns `201` with JSON `{"slug", "url", "short_url", "created_at"}`.
   - Only absolute `http`/`https` URLs up to 2048 characters are accepted.
   - Custom slugs: 3–32 chars, `[A-Za-z0-9_-]`. A taken slug returns `409`.
   - Generated slugs are random, unguessable-enough, and collision-safe.
   - Invalid input returns `400` with a JSON error body.
2. `GET /{slug}` redirects (`302`) to the target and counts the visit; unknown slug → `404`.
3. `GET /api/links/{slug}` returns the link's metadata including `visits`.
4. `DELETE /api/links/{slug}` deletes a link. Write endpoints (`POST`, `DELETE`)
   require `Authorization: Bearer <token>`, where the token comes from the
   `SNIP_API_TOKEN` environment variable; missing/wrong token → `401`.
5. `GET /healthz` returns `200`.
6. Data persists across restarts using local storage only (no external
   services such as Postgres/Redis are available).

## Non-functional requirements
- Automated tests covering the behaviour above, runnable with one command.
- A `README.md` explaining how to install, configure, run and test it.
- Treat it as code you'd be happy to ship: sensible structure, input
  validation, safe defaults, no secrets committed.
