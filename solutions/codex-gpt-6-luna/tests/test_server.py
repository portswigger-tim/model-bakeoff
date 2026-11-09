import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from snip.server import initialize_database, make_handler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


class SnipHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "snip.sqlite3"
        initialize_database(self.db_path)
        handler = make_handler(self.db_path, "test-secret", "http://short.test")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp_dir.cleanup()

    def request(self, path, method="GET", body=None, token="test-secret"):
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(self.base + path, data=data, headers=headers, method=method)
        opener = build_opener(NoRedirect)
        try:
            response = opener.open(request, timeout=3)
            try:
                return response.status, dict(response.headers), response.read()
            finally:
                response.close()
        except HTTPError as error:
            try:
                return error.code, dict(error.headers), error.read()
            finally:
                error.close()

    def create(self, body):
        return self.request("/api/links", "POST", body)

    def test_health(self):
        status, _, body = self.request("/healthz", token=None)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"status": "ok"})

    def test_create_custom_slug_metadata_redirect_and_visits(self):
        status, _, body = self.create({"url": "https://example.com/path", "slug": "docs_1"})
        self.assertEqual(status, 201)
        created = json.loads(body)
        self.assertEqual(created["slug"], "docs_1")
        self.assertEqual(created["short_url"], "http://short.test/docs_1")
        status, _, body = self.request("/api/links/docs_1", token=None)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["visits"], 0)
        status, headers, _ = self.request("/docs_1", token=None)
        self.assertEqual(status, 302)
        self.assertEqual(headers["Location"], "https://example.com/path")
        status, _, body = self.request("/api/links/docs_1", token=None)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["visits"], 1)

    def test_generated_slug_and_collision(self):
        status, _, body = self.create({"url": "http://example.com"})
        self.assertEqual(status, 201)
        generated = json.loads(body)["slug"]
        self.assertRegex(generated, r"\A[A-Za-z0-9_-]{12}\Z")
        status, _, body = self.create({"url": "http://other.example", "slug": generated})
        self.assertEqual(status, 409)
        self.assertIn("error", json.loads(body))

    def test_write_endpoints_require_correct_token(self):
        status, _, _ = self.request("/api/links", "POST", {"url": "https://example.com"}, token=None)
        self.assertEqual(status, 401)
        status, _, _ = self.request("/api/links", "POST", {"url": "https://example.com"}, token="wrong")
        self.assertEqual(status, 401)
        self.create({"url": "https://example.com", "slug": "remove-me"})
        status, _, _ = self.request("/api/links/remove-me", "DELETE", token=None)
        self.assertEqual(status, 401)
        status, _, _ = self.request("/api/links/remove-me", "DELETE")
        self.assertEqual(status, 204)

    def test_invalid_urls_and_slugs_return_json_400(self):
        invalid_urls = ["", "example.com", "ftp://example.com", "http:///missing-host", "https://user:pw@example.com"]
        for value in invalid_urls:
            with self.subTest(url=value):
                status, headers, body = self.create({"url": value})
                self.assertEqual(status, 400)
                self.assertIn("application/json", headers["Content-Type"])
                self.assertIn("error", json.loads(body))
        for value in ["ab", "has space", "bad/path", "x" * 33]:
            with self.subTest(slug=value):
                status, _, body = self.create({"url": "https://example.com", "slug": value})
                self.assertEqual(status, 400)
                self.assertIn("error", json.loads(body))
        status, _, _ = self.create({"url": "https://example.com/" + "x" * 2050})
        self.assertEqual(status, 400)

    def test_malformed_json_unknown_routes_and_missing_links(self):
        request = Request(
            self.base + "/api/links",
            data=b"not json",
            headers={"Authorization": "Bearer test-secret", "Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as raised:
            urlopen(request, timeout=3)
        self.assertEqual(raised.exception.code, 400)
        try:
            self.assertIn("error", json.loads(raised.exception.read()))
        finally:
            raised.exception.close()
        self.assertEqual(self.request("/api/links/missing", token=None)[0], 404)
        self.assertEqual(self.request("/unknown", token=None)[0], 404)
        self.assertEqual(self.request("/api/links/missing", "DELETE")[0], 404)

    def test_data_survives_database_reinitialization(self):
        self.create({"url": "https://example.com/persist", "slug": "persistent"})
        initialize_database(self.db_path)
        status, _, body = self.request("/api/links/persistent", token=None)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["url"], "https://example.com/persist")


if __name__ == "__main__":
    unittest.main()

