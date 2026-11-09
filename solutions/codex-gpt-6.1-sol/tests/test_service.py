from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from snip import create_app
from snip.config import Settings


TOKEN = "test-only-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
TARGET = "https://example.com/a?b=1&c=2#section"


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".snip-test-", dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        self.settings = Settings(TOKEN, Path(self.temp.name) / "nested" / "snip.db", "https://s.example")
        self.app = create_app(self.settings)
        self.client = self.app.test_client()

    def create(self, slug=None, url=TARGET):
        body = {"url": url}
        if slug is not None:
            body["slug"] = slug
        return self.client.post("/api/links", json=body, headers=AUTH)

    def assert_error(self, response, status):
        self.assertEqual(response.status_code, status, response.get_data(as_text=True))
        self.assertTrue(response.is_json)
        self.assertIsInstance(response.json["error"], str)
        self.assertTrue(response.json["error"])

    def test_health_is_public(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"status": "ok"})

    def test_create_returns_contract_and_utc_timestamp(self):
        before = datetime.now(timezone.utc)
        response = self.create("My_link-123")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(set(response.json), {"slug", "url", "short_url", "created_at"})
        self.assertEqual(response.json["slug"], "My_link-123")
        self.assertEqual(response.json["url"], TARGET)
        self.assertEqual(response.json["short_url"], "https://s.example/My_link-123")
        self.assertEqual(response.headers["Location"], "/api/links/My_link-123")
        created = datetime.fromisoformat(response.json["created_at"].replace("Z", "+00:00"))
        self.assertLessEqual(before, created)
        self.assertLessEqual(created, datetime.now(timezone.utc))

    def test_metadata_public_redirect_count_delete_lifecycle(self):
        created = self.create("my-link").json
        response = self.client.get("/api/links/my-link")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {**created, "visits": 0})
        for _ in range(3):
            response = self.client.get("/my-link")
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.headers["Location"], TARGET)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(self.client.get("/api/links/my-link").json["visits"], 3)
        response = self.client.delete("/api/links/my-link", headers=AUTH)
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.data, b"")
        self.assert_error(self.client.get("/my-link"), 404)
        self.assert_error(self.client.get("/api/links/my-link"), 404)
        self.assert_error(self.client.delete("/api/links/my-link", headers=AUTH), 404)

    def test_auth_required_for_both_write_endpoints(self):
        self.create("protected")
        for header in [None, "", "wrong", "Basic dGVzdA==", "Bearer wrong", "Bearer", f"Bearer {TOKEN}extra"]:
            with self.subTest(header=header):
                headers = {} if header is None else {"Authorization": header}
                response = self.client.post("/api/links", json={"url": TARGET}, headers=headers)
                self.assert_error(response, 401)
                self.assertIn("Bearer", response.headers["WWW-Authenticate"])
                self.assert_error(self.client.delete("/api/links/protected", headers=headers), 401)
        self.assertEqual(self.client.get("/api/links/protected").status_code, 200)

    def test_auth_precedes_parsing(self):
        self.assert_error(self.client.post("/api/links", data="{bad"), 401)

    def test_invalid_json_and_nonobject_bodies(self):
        for data in ["{bad", "", "null", "[]", '"hello"', "1", "true"]:
            with self.subTest(data=data):
                self.assert_error(self.client.post("/api/links", data=data, content_type="application/json", headers=AUTH), 400)
        self.assert_error(self.client.post("/api/links", data='{"url":"https://example.com"}', headers=AUTH), 400)
        self.assert_error(self.client.post("/api/links", json={"url": TARGET, "visits": 20}, headers=AUTH), 400)

    def test_invalid_urls(self):
        for url in [None, 5, True, [], {}, "", "/relative", "example.com", "//example.com", "ftp://example.com", "javascript:alert(1)", "https://", "https:///path", "https://user@", "https://[::1", "https://example.com:99999", "https://example.com:no", "https://example.com:0", " https://example.com", "https://example.com/\nX", "https://exa mple.com", "https://example.com/\x00", "https://example.com\\@evil.com", "https://example.com/" + "a" * 2048]:
            with self.subTest(url=url):
                self.assert_error(self.client.post("/api/links", json={"url": url}, headers=AUTH), 400)
        self.assert_error(self.client.post("/api/links", json={}, headers=AUTH), 400)

    def test_valid_urls_and_maximum_length(self):
        prefix = "https://example.com/"
        for url in ["http://localhost", "HTTP://example.com", "https://example.com:8443/path", "http://127.0.0.1/", "https://[::1]:443/a", "https://user:pass@example.com/path", "https://example.com/café", prefix + "x" * (2048 - len(prefix))]:
            with self.subTest(url=url):
                response = self.create(url=url)
                self.assertEqual(response.status_code, 201, response.json)
                self.assertEqual(response.json["url"], url)

    def test_invalid_unicode_url_is_a_client_error(self):
        self.assert_error(self.create(url="https://example.com/\ud800"), 400)

    def test_malformed_hostnames_are_rejected_before_storage(self):
        for host in [".", "..", "example..com", "x" * 64 + ".com", "exa|mple.com", "foo%00.com", "[v1.test]"]:
            with self.subTest(host=host):
                self.assert_error(self.create(url=f"https://{host}/"), 400)

    def test_international_domain_can_be_redirected(self):
        self.assertEqual(self.create("unicode", "https://bücher.example/café").status_code, 201)
        response = self.client.get("/unicode")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "https://xn--bcher-kva.example/caf%C3%A9")

    def test_invalid_slugs(self):
        for slug in [None, 1, True, [], {}, "", "ab", "a" * 33, "has space", "a/b", "a.b", "café", "abc\n", "healthz"]:
            with self.subTest(slug=slug):
                self.assert_error(self.client.post("/api/links", json={"url": TARGET, "slug": slug}, headers=AUTH), 400)

    def test_slug_boundaries_case_sensitivity_and_duplicate(self):
        for slug in ["abc", "a" * 32, "Abc", "_-0", "api"]:
            self.assertEqual(self.create(slug).status_code, 201)
            self.assertEqual(self.client.get(f"/{slug}").status_code, 302)
        self.assert_error(self.create("abc", "https://other.example"), 409)
        self.assertEqual(self.client.get("/api/links/abc").json["url"], TARGET)

    def test_generated_slugs_are_url_safe_and_distinct(self):
        slugs = []
        for _ in range(50):
            response = self.create()
            self.assertEqual(response.status_code, 201)
            slug = response.json["slug"]
            self.assertTrue(re.fullmatch(r"[A-Za-z0-9_-]{12}", slug))
            slugs.append(slug)
        self.assertEqual(len(set(slugs)), len(slugs))

    def test_generated_collision_retries_without_overwriting(self):
        self.create("collision")
        with patch("snip.storage.secrets.token_urlsafe", side_effect=["collision", "freshslug"]):
            response = self.create()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["slug"], "freshslug")
        self.assertEqual(self.client.get("/api/links/collision").json["url"], TARGET)

    def test_generated_collision_exhaustion_is_bounded(self):
        self.create("collision")
        with patch("snip.storage.secrets.token_urlsafe", return_value="collision") as generate:
            with self.assertLogs(self.app.logger, level="ERROR"):
                self.assert_error(self.create(), 503)
        self.assertEqual(generate.call_count, 8)

    def test_unknown_routes_and_methods_return_json(self):
        for path in ["/missing", "/api/links/missing", "/api/no/such/path"]:
            self.assert_error(self.client.get(path), 404)
        response = self.client.put("/api/links", json={"url": TARGET})
        self.assert_error(response, 405)
        self.assertIn("POST", response.headers["Allow"])

    def test_head_does_not_count_a_visit(self):
        self.create("head-link")
        self.assertEqual(self.client.head("/head-link").status_code, 302)
        self.assertEqual(self.client.get("/api/links/head-link").json["visits"], 0)

    def test_persistence_across_new_application_instances(self):
        created = self.create("persistent").json
        self.client.get("/persistent")
        other = create_app(self.settings).test_client()
        self.assertEqual(other.get("/api/links/persistent").json, {**created, "visits": 1})
        other.delete("/api/links/persistent", headers=AUTH)
        self.assert_error(create_app(self.settings).test_client().get("/persistent"), 404)

    def test_concurrent_visits_are_not_lost(self):
        self.create("popular")

        def visit(_):
            with self.app.test_client() as client:
                return client.get("/popular").status_code

        with ThreadPoolExecutor(max_workers=8) as pool:
            statuses = list(pool.map(visit, range(80)))
        self.assertEqual(statuses, [302] * 80)
        self.assertEqual(self.client.get("/api/links/popular").json["visits"], 80)

    def test_concurrent_custom_creation_has_one_winner(self):
        def create(_):
            with self.app.test_client() as client:
                return client.post("/api/links", json={"url": TARGET, "slug": "racing"}, headers=AUTH).status_code

        with ThreadPoolExecutor(max_workers=8) as pool:
            statuses = list(pool.map(create, range(16)))
        self.assertEqual(statuses.count(201), 1)
        self.assertEqual(statuses.count(409), 15)

    def test_sql_injection_input_is_data(self):
        response = self.create("sql-safe", "https://example.com/';DROP%20TABLE%20links;--")
        self.assertEqual(response.status_code, 201)
        self.assert_error(self.client.get("/api/links/'%20OR%201=1--"), 404)
        self.assertEqual(self.client.get("/api/links/sql-safe").status_code, 200)

    def test_host_header_cannot_poison_short_url(self):
        response = self.client.post("/api/links", json={"url": TARGET}, headers={**AUTH, "Host": "evil.example", "X-Forwarded-Host": "also-evil.example", "X-Forwarded-Proto": "http"})
        self.assertTrue(response.json["short_url"].startswith("https://s.example/"))

    def test_oversized_request_is_rejected(self):
        response = self.client.post("/api/links", data="x" * 32769, content_type="application/json", headers=AUTH)
        self.assert_error(response, 413)

    def test_storage_failure_does_not_expose_details(self):
        store = self.app.extensions["snip_store"]
        with patch.object(store, "get", side_effect=sqlite3.OperationalError("secret file details")):
            with self.assertLogs(self.app.logger, level="ERROR"):
                response = self.client.get("/api/links/anything")
        self.assert_error(response, 503)
        self.assertNotIn("secret", response.get_data(as_text=True))
        self.assertEqual(response.headers["Retry-After"], "1")

    @unittest.skipUnless(os.name == "posix", "POSIX file permissions")
    def test_new_database_is_private(self):
        self.assertEqual(self.settings.database.stat().st_mode & 0o777, 0o600)


class ConfigurationTests(unittest.TestCase):
    def test_missing_token_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "SNIP_API_TOKEN"):
                create_app()

    def test_invalid_tokens(self):
        for token in ["", " secret", "secret ", "a\nb", "a b", "\x00"]:
            with self.subTest(token=token), self.assertRaises(ValueError):
                Settings(token)

    def test_invalid_public_origin(self):
        for origin in ["/relative", "ftp://example.com", "https://example.com/prefix", "https://user@example.com", "https://example.com?x=1", "https://example.com/#x"]:
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                Settings(TOKEN, base_url=origin)

    def test_environment_configuration(self):
        with patch.dict(os.environ, {"SNIP_API_TOKEN": TOKEN, "SNIP_DB_PATH": "/tmp/custom.db", "SNIP_BASE_URL": "https://short.example/"}, clear=True):
            settings = Settings.from_env()
        self.assertEqual(settings.api_token, TOKEN)
        self.assertEqual(settings.database, Path("/tmp/custom.db"))
        self.assertEqual(settings.base_url, "https://short.example/")


if __name__ == "__main__":
    unittest.main()
