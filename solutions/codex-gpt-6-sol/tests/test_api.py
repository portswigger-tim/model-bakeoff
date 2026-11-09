import http.client
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from snip.app import SnipServer
from snip.store import Store


TOKEN = "test-secret-token"


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".snip-test-", dir=".")
        self.db_path = Path(self.temp.name) / "links.db"
        self._start_server()

    def tearDown(self):
        self._stop_server()
        self.temp.cleanup()

    def _start_server(self):
        self.server = SnipServer(("127.0.0.1", 0), Store(self.db_path), TOKEN, "http://127.0.0.1:8000")
        self.server.base_url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def _stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method, path, body=None, token=TOKEN, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        request_headers = dict(headers or {})
        if token is not None:
            request_headers["Authorization"] = f"Bearer {token}"
        if body is not None:
            request_headers["Content-Type"] = "application/json"
            body = json.dumps(body).encode("utf-8")
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        data = response.read()
        result = (response.status, dict(response.getheaders()), json.loads(data) if data else None)
        connection.close()
        return result

    def test_create_redirect_metadata_and_delete(self):
        status, _, created = self.request("POST", "/api/links", {"url": "https://example.com/a?x=1", "slug": "my-link"})
        self.assertEqual(status, 201)
        self.assertEqual(created["slug"], "my-link")
        self.assertEqual(created["url"], "https://example.com/a?x=1")
        self.assertEqual(created["short_url"], f"{self.server.base_url}/my-link")
        self.assertTrue(created["created_at"].endswith("Z"))

        status, headers, _ = self.request("GET", "/my-link")
        self.assertEqual(status, 302)
        self.assertEqual(headers["Location"], "https://example.com/a?x=1")
        status, _, metadata = self.request("GET", "/api/links/my-link")
        self.assertEqual(status, 200)
        self.assertEqual(metadata["visits"], 1)
        self.assertEqual(metadata["created_at"], created["created_at"])

        self.assertEqual(self.request("DELETE", "/api/links/my-link")[0], 204)
        self.assertEqual(self.request("GET", "/my-link")[0], 404)
        self.assertEqual(self.request("GET", "/api/links/my-link")[0], 404)
        self.assertEqual(self.request("DELETE", "/api/links/my-link")[0], 404)

    def test_authentication(self):
        body = {"url": "https://example.com"}
        self.assertEqual(self.request("POST", "/api/links", body, token=None)[0], 401)
        self.assertEqual(self.request("POST", "/api/links", body, token="wrong")[0], 401)
        self.assertEqual(self.request("DELETE", "/api/links/abc", token=None)[0], 401)
        self.assertEqual(self.request("DELETE", "/api/links/abc", token="wrong")[0], 401)
        self.assertEqual(self.request("POST", "/api/links", body, token="tëst")[0], 401)
        status, _, error = self.request("POST", "/api/links", body, token=None)
        self.assertIn("error", error)
        self.assertEqual(status, 401)

    def test_url_and_slug_validation(self):
        invalid_urls = [None, "", "example.com", "/relative", "ftp://example.com", "https://", "http://example.com:bad", "https://example.com/has space", "https://example.com/\r\nX: evil", "https://example.com/\ud800", "https://example.com/" + "a" * 2049]
        for url in invalid_urls:
            with self.subTest(url=url):
                status, _, error = self.request("POST", "/api/links", {"url": url})
                self.assertEqual(status, 400)
                self.assertIn("error", error)
        for slug in [None, "ab", "a" * 33, "bad.slug", "non ascii é", "healthz", 123]:
            with self.subTest(slug=slug):
                self.assertEqual(self.request("POST", "/api/links", {"url": "https://example.com", "slug": slug})[0], 400)
        self.assertEqual(self.request("POST", "/api/links", {"url": "https://example.com", "extra": 1})[0], 400)
        self.assertEqual(self.request("POST", "/api/links", ["https://example.com"])[0], 400)
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        connection.request("POST", "/api/links", body=b"{bad", headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
        self.assertEqual(connection.getresponse().status, 400)
        connection.close()

    def test_custom_collision_and_generated_retry(self):
        body = {"url": "https://example.com", "slug": "taken"}
        self.assertEqual(self.request("POST", "/api/links", body)[0], 201)
        self.assertEqual(self.request("POST", "/api/links", body)[0], 409)
        with patch("snip.store.secrets.token_urlsafe", side_effect=["taken", "fresh123"]):
            status, _, link = self.request("POST", "/api/links", {"url": "https://example.org"})
        self.assertEqual(status, 201)
        self.assertEqual(link["slug"], "fresh123")
        status, _, generated = self.request("POST", "/api/links", {"url": "https://example.org"})
        self.assertEqual(status, 201)
        self.assertRegex(generated["slug"], r"^[A-Za-z0-9_-]{12}$")

    def test_persistence_across_restart(self):
        self.assertEqual(self.request("POST", "/api/links", {"url": "https://example.com", "slug": "persistent"})[0], 201)
        self.assertEqual(self.request("GET", "/persistent")[0], 302)
        self._stop_server()
        self._start_server()
        status, _, link = self.request("GET", "/api/links/persistent")
        self.assertEqual(status, 200)
        self.assertEqual(link["visits"], 1)
        self.assertEqual(link["url"], "https://example.com")

    def test_concurrent_visits_are_counted(self):
        self.assertEqual(self.request("POST", "/api/links", {"url": "https://example.com", "slug": "popular"})[0], 201)
        with ThreadPoolExecutor(max_workers=8) as pool:
            statuses = list(pool.map(lambda _: self.request("GET", "/popular")[0], range(24)))
        self.assertEqual(statuses, [302] * 24)
        self.assertEqual(self.request("GET", "/api/links/popular")[2]["visits"], 24)

    def test_health_unknown_and_unicode_redirect(self):
        self.assertEqual(self.request("GET", "/healthz")[0], 200)
        self.assertEqual(self.request("GET", "/missing")[0], 404)
        self.assertEqual(self.request("GET", "/api/links/missing")[0], 404)
        url = "https://example.com/café"
        self.assertEqual(self.request("POST", "/api/links", {"url": url, "slug": "unicode"})[0], 201)
        status, headers, _ = self.request("GET", "/unicode")
        self.assertEqual(status, 302)
        self.assertEqual(headers["Location"], "https://example.com/caf%C3%A9")


if __name__ == "__main__":
    unittest.main()
