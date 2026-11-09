"""snip HTTP application factory."""

import hmac
import re
import sqlite3

from flask import Flask, jsonify, redirect, request
from werkzeug.exceptions import HTTPException

from .config import Settings, valid_url
from .storage import GenerationExhausted, SlugTaken, Storage


SLUG = re.compile(r"[A-Za-z0-9_-]{3,32}", re.ASCII)
RESERVED = {"healthz"}


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings or Settings.from_env()
    app = Flask(__name__)
    app.config.update(MAX_CONTENT_LENGTH=32768, PROPAGATE_EXCEPTIONS=False)
    store = Storage(settings.database)
    app.extensions["snip_store"] = store

    def error(message: str, status: int):
        return jsonify(error=message), status

    def metadata(link: dict) -> dict:
        return {**link, "short_url": f"{settings.base_url.rstrip('/')}/{link['slug']}"}

    @app.before_request
    def authenticate():
        if request.method in {"POST", "DELETE"}:
            expected = f"Bearer {settings.api_token}".encode("utf-8")
            actual = request.headers.get("Authorization", "").encode("utf-8")
            if not hmac.compare_digest(actual, expected):
                response = jsonify(error="Unauthorized")
                response.status_code = 401
                response.headers["WWW-Authenticate"] = 'Bearer realm="snip"'
                return response

    @app.after_request
    def response_headers(response):
        # Caching redirects would bypass the counter and make deletion ineffective.
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.errorhandler(HTTPException)
    def http_error(exc):
        response = exc.get_response()
        response.data = app.json.dumps({"error": exc.description})
        response.content_type = "application/json"
        return response

    @app.errorhandler(sqlite3.Error)
    @app.errorhandler(GenerationExhausted)
    def storage_error(exc):
        app.logger.error("Storage operation failed: %s", type(exc).__name__)
        response = jsonify(error="Storage temporarily unavailable")
        response.status_code = 503
        response.headers["Retry-After"] = "1"
        return response

    @app.errorhandler(Exception)
    def unexpected_error(exc):
        app.logger.exception("Unhandled request error")
        return error("Internal server error", 500)

    @app.get("/healthz")
    def health():
        return jsonify(status="ok")

    @app.post("/api/links")
    def create_link():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return error("Expected a JSON object", 400)
        if body.keys() - {"url", "slug"}:
            return error("Only url and slug fields are accepted", 400)
        if not valid_url(body.get("url")):
            return error("url must be an absolute HTTP(S) URL of at most 2048 characters", 400)
        slug = body.get("slug")
        if "slug" in body and (not isinstance(slug, str) or not SLUG.fullmatch(slug)):
            return error("slug must contain 3–32 ASCII letters, digits, underscores or hyphens", 400)
        if slug in RESERVED:
            return error("slug is reserved", 400)
        try:
            link = store.create(body["url"], slug)
        except SlugTaken:
            return error("slug is already taken", 409)
        response = jsonify(metadata(link))
        response.status_code = 201
        response.headers["Location"] = f"/api/links/{link['slug']}"
        return response

    @app.get("/api/links/<slug>")
    def get_link(slug):
        link = store.get(slug)
        if link is None:
            return error("Link not found", 404)
        return jsonify(metadata(link))

    @app.delete("/api/links/<slug>")
    def delete_link(slug):
        if not store.delete(slug):
            return error("Link not found", 404)
        return "", 204

    @app.get("/<slug>")
    def follow_link(slug):
        if request.method == "HEAD":
            link = store.get(slug)
            target = link["url"] if link else None
        else:
            target = store.visit(slug)
        if target is None:
            return error("Link not found", 404)
        return redirect(target, code=302)

    return app

