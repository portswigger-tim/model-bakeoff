from __future__ import annotations

import json
import re
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http.client import HTTPConnection
from pathlib import Path
from typing import Any

from snip.app import SnipApplication, SnipServer
from snip.storage import LinkStore


class SnipHTTPTests(unittest.TestCase):
    TOKEN = "test-token-that-is-not-a-secret"

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "snip.db"
        self.store = LinkStore(self.database_path)
        self.application = SnipApplication(self.store, self.TOKEN, "http://short.test")
        self.server = SnipServer(("127.0.0.1", 0), self.application)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary_directory.cleanup()

    def request(
        self,
        method: str,
        path: str,
        payload: Any | None = None,
        *,
        token: str | None = None,
        raw_body: bytes | None = None,
        content_type: str = "application/json",
    ) -> tuple[int, dict[str, str], Any | None]:
        headers: dict[str, str] = {}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        body = raw_body
        if payload is not None:
            body = json.dumps(payload).encode()
        if body is not None:
            headers["Content-Type"] = content_type
        connection = HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            response_body = response.read()
            response_headers = {name.lower(): value for name, value in response.getheaders()}
            parsed_body = json.loads(response_body) if response_body else None
            return response.status, response_headers, parsed_body
        finally:
            connection.close()

    def create(self, url: str = "https://example.com/a?b=c", slug: str | None = "abc") -> Any:
        payload: dict[str, str] = {"url": url}
        if slug is not None:
            payload["slug"] = slug
        status, _, body = self.request("POST", "/api/links", payload, token=self.TOKEN)
        self.assertEqual(status, 201)
        return body

    def test_health(self) -> None:
        status, _, body = self.request("GET", "/healthz")
        self.assertEqual((status, body), (200, {"status": "ok"}))

    def test_write_endpoints_require_the_configured_bearer_token(self) -> None:
        for token in (None, "wrong"):
            with self.subTest(token=token):
                status, headers, body = self.request(
                    "POST", "/api/links", {"url": "https://example.com"}, token=token
                )
                self.assertEqual(status, 401)
                self.assertEqual(headers["www-authenticate"], "Bearer")
                self.assertEqual(body["error"]["code"], "unauthorized")

        self.create(slug="delete-me")
        status, _, _ = self.request("DELETE", "/api/links/delete-me")
        self.assertEqual(status, 401)

    def test_create_custom_link_and_read_metadata(self) -> None:
        created = self.create(url="https://example.com/docs", slug="My_link-1")
        self.assertEqual(created["slug"], "My_link-1")
        self.assertEqual(created["url"], "https://example.com/docs")
        self.assertEqual(created["short_url"], "http://short.test/My_link-1")
        self.assertTrue(created["created_at"].endswith("Z"))
        datetime.fromisoformat(created["created_at"].replace("Z", "+00:00"))

        status, _, metadata = self.request("GET", "/api/links/My_link-1")
        self.assertEqual(status, 200)
        self.assertEqual(metadata, {
            "slug": "My_link-1",
            "url": "https://example.com/docs",
            "created_at": created["created_at"],
            "visits": 0,
        })

    def test_generated_slugs_are_url_safe_and_unique(self) -> None:
        slugs = {self.create(slug=None)["slug"] for _ in range(20)}
        self.assertEqual(len(slugs), 20)
        self.assertTrue(all(re.fullmatch(r"[A-Za-z0-9_-]{11}", slug) for slug in slugs))

    def test_duplicate_custom_slug_returns_conflict_without_replacing_link(self) -> None:
        self.create(url="https://first.example", slug="same")
        status, _, body = self.request(
            "POST",
            "/api/links",
            {"url": "https://second.example", "slug": "same"},
            token=self.TOKEN,
        )
        self.assertEqual(status, 409)
        self.assertEqual(body["error"]["code"], "slug_conflict")
        self.assertEqual(self.store.get("same").url, "https://first.example")

    def test_invalid_inputs_return_json_400(self) -> None:
        cases = [
            ({}, "url is required"),
            ({"url": "ftp://example.com"}, "absolute http"),
            ({"url": "/relative"}, "absolute http"),
            ({"url": "https://example.com/a b"}, "whitespace"),
            ({"url": "https://example.com", "slug": "ab"}, "slug must"),
            ({"url": "https://example.com", "slug": "bad/slug"}, "slug must"),
            ({"url": "https://example.com", "extra": True}, "unknown JSON field"),
        ]
        for payload, message_fragment in cases:
            with self.subTest(payload=payload):
                status, headers, body = self.request(
                    "POST", "/api/links", payload, token=self.TOKEN
                )
                self.assertEqual(status, 400)
                self.assertTrue(headers["content-type"].startswith("application/json"))
                self.assertIn(message_fragment, body["error"]["message"])

        too_long = "https://example.com/" + "a" * 2030
        status, _, _ = self.request(
            "POST", "/api/links", {"url": too_long}, token=self.TOKEN
        )
        self.assertEqual(status, 400)

    def test_malformed_and_non_object_json_return_400(self) -> None:
        for body in (
            b"{",
            b"[]",
            b'{"url":"https://a.example","url":"https://b.example"}',
            b'{"url":NaN}',
        ):
            with self.subTest(body=body):
                status, _, response = self.request(
                    "POST", "/api/links", token=self.TOKEN, raw_body=body
                )
                self.assertEqual(status, 400)
                self.assertEqual(response["error"]["code"], "invalid_request")

    def test_redirect_counts_each_visit_and_unknown_is_404(self) -> None:
        self.create(url="https://example.com/destination?q=hello", slug="visit-me")
        for expected_visits in range(1, 4):
            status, headers, body = self.request("GET", "/visit-me")
            self.assertEqual(status, 302)
            self.assertEqual(headers["location"], "https://example.com/destination?q=hello")
            self.assertIsNone(body)
            _, _, metadata = self.request("GET", "/api/links/visit-me")
            self.assertEqual(metadata["visits"], expected_visits)

        status, _, body = self.request("GET", "/not-found")
        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["code"], "not_found")

    def test_concurrent_visits_are_not_lost(self) -> None:
        self.create(slug="popular")
        with ThreadPoolExecutor(max_workers=10) as executor:
            statuses = list(executor.map(lambda _: self.request("GET", "/popular")[0], range(30)))
        self.assertEqual(statuses, [302] * 30)
        self.assertEqual(self.store.get("popular").visits, 30)

    def test_delete_removes_link_and_unknown_delete_is_404(self) -> None:
        self.create(slug="remove-me")
        status, _, body = self.request(
            "DELETE", "/api/links/remove-me", token=self.TOKEN
        )
        self.assertEqual((status, body), (204, None))
        self.assertEqual(self.request("GET", "/remove-me")[0], 404)
        self.assertEqual(
            self.request("DELETE", "/api/links/remove-me", token=self.TOKEN)[0], 404
        )

    def test_data_persists_when_store_is_reopened(self) -> None:
        created = self.create(url="https://persistent.example", slug="lasting")
        reopened = LinkStore(self.database_path)
        link = reopened.get("lasting")
        self.assertIsNotNone(link)
        self.assertEqual(link.url, "https://persistent.example")
        self.assertEqual(link.created_at, created["created_at"])


if __name__ == "__main__":
    unittest.main()

