import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from snip.app import create_server


class SnipHTTPTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "links.db")
        self.server = create_server(
            port=0,
            db_path=self.db_path,
            api_token="test-token",
            base_url="http://short.test",
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.server_address

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()
        self.temp_dir.cleanup()

    def request(self, method: str, path: str, body: object | None = None, token: str | None = "test-token"):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=2)
        headers = {}
        encoded = None
        if body is not None:
            encoded = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        connection.request(method, path, body=encoded, headers=headers)
        response = connection.getresponse()
        content = response.read()
        result = json.loads(content) if content else None
        headers_out = dict(response.getheaders())
        connection.close()
        return response.status, headers_out, result

    def test_health_and_authentication(self) -> None:
        status, _, body = self.request("GET", "/healthz", token=None)
        self.assertEqual(status, 200)
        self.assertEqual(body, {"status": "ok"})

        status, headers, body = self.request("POST", "/api/links", {"url": "https://example.com"}, token=None)
        self.assertEqual(status, 401)
        self.assertIn("Bearer", headers["WWW-Authenticate"])
        self.assertEqual(body["error"], "authentication required")

        status, _, _ = self.request("POST", "/api/links", {"url": "https://example.com"}, token="wrong")
        self.assertEqual(status, 401)

    def test_validation_and_duplicate_slug(self) -> None:
        for payload in (
            {"url": "ftp://example.com"},
            {"url": "https://example.com", "slug": "no"},
            {"url": "https://example.com", "slug": "bad slug"},
            {"url": "https://example.com/" + "x" * 2040},
        ):
            status, _, body = self.request("POST", "/api/links", payload)
            self.assertEqual(status, 400, body)
            self.assertIn("error", body)

        status, _, body = self.request("POST", "/api/links", {"url": "https://example.com", "slug": "docs"})
        self.assertEqual(status, 201)
        self.assertEqual(body["slug"], "docs")
        self.assertEqual(body["short_url"], "http://short.test/docs")

        status, _, _ = self.request("POST", "/api/links", {"url": "https://other.example", "slug": "docs"})
        self.assertEqual(status, 409)

        status, _, _ = self.request("POST", "/api/links", {"url": "https://example.com", "slug": "abc"}, token="test-token")
        self.assertEqual(status, 201)

    def test_redirect_metadata_visits_and_delete(self) -> None:
        status, _, created = self.request("POST", "/api/links", {"url": "https://example.com/a?b=1", "slug": "go-there"})
        self.assertEqual(status, 201)
        self.assertEqual(set(created), {"slug", "url", "short_url", "created_at"})

        status, _, metadata = self.request("GET", "/api/links/go-there", token=None)
        self.assertEqual(status, 200)
        self.assertEqual(metadata["visits"], 0)
        self.assertEqual(metadata["url"], "https://example.com/a?b=1")

        status, headers, body = self.request("GET", "/go-there", token=None)
        self.assertEqual(status, 302)
        self.assertEqual(headers["Location"], "https://example.com/a?b=1")
        self.assertIsNone(body)

        status, _, metadata = self.request("GET", "/api/links/go-there", token=None)
        self.assertEqual(status, 200)
        self.assertEqual(metadata["visits"], 1)

        status, _, _ = self.request("DELETE", "/api/links/go-there", token=None)
        self.assertEqual(status, 401)
        status, _, _ = self.request("DELETE", "/api/links/go-there")
        self.assertEqual(status, 204)
        status, _, _ = self.request("GET", "/api/links/go-there", token=None)
        self.assertEqual(status, 404)

    def test_data_persists_after_restart(self) -> None:
        status, _, _ = self.request("POST", "/api/links", {"url": "https://persist.example", "slug": "persist"})
        self.assertEqual(status, 201)
        self.request("GET", "/persist", token=None)
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()

        self.server = create_server(
            port=0,
            db_path=self.db_path,
            api_token="test-token",
            base_url="http://short.test",
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.server_address
        status, _, metadata = self.request("GET", "/api/links/persist", token=None)
        self.assertEqual(status, 200)
        self.assertEqual(metadata["visits"], 1)


if __name__ == "__main__":
    unittest.main()

