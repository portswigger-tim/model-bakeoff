import hmac
import json
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import Settings
from .storage import Link, LinkStore, SlugTaken
from .validation import ValidationError, generate_slug, validate_slug, validate_url

log = logging.getLogger("snip")
MAX_BODY_BYTES = 8192
MAX_SLUG_ATTEMPTS = 10


def _error(status: int, message: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status, headers=headers)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if not settings.api_token:
        log.warning("SNIP_API_TOKEN is not set: all write endpoints will return 401")

    store = LinkStore(settings.db_path)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        store.close()

    app = FastAPI(title="snip", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.store = store

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        return _error(exc.status_code, str(exc.detail), getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _bad_request(_: Request, exc: RequestValidationError):
        return _error(400, "invalid request")

    def require_token(authorization: str | None = Header(default=None)) -> None:
        expected = settings.api_token
        scheme, _, supplied = (authorization or "").partition(" ")
        ok = (
            bool(expected)
            and scheme.lower() == "bearer"
            and hmac.compare_digest(supplied.strip().encode(), expected.encode())
        )
        if not ok:
            raise HTTPException(401, "missing or invalid bearer token", {"WWW-Authenticate": "Bearer"})

    def short_url(request: Request, slug: str) -> str:
        base = (settings.base_url or str(request.base_url)).rstrip("/")
        return f"{base}/{slug}"

    def present(request: Request, link: Link) -> dict:
        return {
            "slug": link.slug,
            "url": link.url,
            "short_url": short_url(request, link.slug),
            "created_at": link.created_at,
            "visits": link.visits,
        }

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.post("/api/links", status_code=201, dependencies=[Depends(require_token)])
    async def create_link(request: Request):
        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            return _error(400, "request body too large")
        try:
            data = json.loads(body)
        except ValueError:
            return _error(400, "body must be valid JSON")
        if not isinstance(data, dict):
            return _error(400, "body must be a JSON object")
        try:
            url = validate_url(data.get("url"))
            slug = data.get("slug")
            if slug is not None:
                slug = validate_slug(slug)
        except ValidationError as exc:
            return _error(400, str(exc))

        try:
            if slug is not None:
                link = store.create(slug, url)
            else:
                for _ in range(MAX_SLUG_ATTEMPTS):
                    try:
                        link = store.create(generate_slug(), url)
                        break
                    except SlugTaken:
                        continue
                else:
                    log.error("could not generate a free slug")
                    return _error(500, "could not generate a slug")
        except SlugTaken:
            return _error(409, "slug already taken")

        result = present(request, link)
        del result["visits"]
        return JSONResponse(result, status_code=201)

    @app.get("/api/links/{slug}")
    def get_link(slug: str, request: Request):
        link = store.get(slug)
        if link is None:
            return _error(404, "link not found")
        return present(request, link)

    @app.delete("/api/links/{slug}", status_code=204, dependencies=[Depends(require_token)])
    def delete_link(slug: str):
        if not store.delete(slug):
            return _error(404, "link not found")
        return Response(status_code=204)

    @app.get("/{slug}")
    def follow(slug: str):
        target = store.visit(slug)
        if target is None:
            return _error(404, "link not found")
        return RedirectResponse(target, status_code=302, headers={"Cache-Control": "no-store"})

    return app
