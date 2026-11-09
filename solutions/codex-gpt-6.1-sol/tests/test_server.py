"""Exercise the documented entry point over HTTP, including process restart."""

import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ServerTests(unittest.TestCase):
    def test_http_lifecycle_survives_process_restart(self):
        with tempfile.TemporaryDirectory(prefix=".snip-test-", dir=ROOT) as directory:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            env = {
                **os.environ,
                "SNIP_API_TOKEN": "integration-test-only",
                "SNIP_DB_PATH": str(Path(directory) / "links.db"),
                "SNIP_HOST": "127.0.0.1",
                "SNIP_PORT": str(port),
                "SNIP_BASE_URL": f"http://127.0.0.1:{port}",
            }

            def start():
                process = subprocess.Popen(
                    [sys.executable, "-m", "snip"],
                    cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                )
                self.addCleanup(stop, process)
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        self.fail(f"Server exited: {process.stderr.read().decode()}")
                    try:
                        status, _, _ = request("GET", "/healthz")
                        if status == 200:
                            return process
                    except OSError:
                        pass
                    time.sleep(0.025)
                self.fail("Server did not become healthy within eight seconds")

            def stop(process):
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                process.stderr.close()

            def request(method, path, body=None, auth=False):
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
                headers = {"Content-Type": "application/json"}
                if auth:
                    headers["Authorization"] = "Bearer integration-test-only"
                try:
                    conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
                    response = conn.getresponse()
                    return response.status, dict(response.getheaders()), response.read()
                finally:
                    conn.close()

            first = start()
            self.assertEqual(request("POST", "/api/links", {"url": "https://example.com"})[0], 401)
            status, _, body = request("POST", "/api/links", {"url": "https://example.com", "slug": "restart"}, auth=True)
            self.assertEqual(status, 201)
            self.assertEqual(json.loads(body)["short_url"], f"http://127.0.0.1:{port}/restart")
            status, headers, _ = request("GET", "/restart")
            self.assertEqual(status, 302)
            self.assertEqual(headers["Location"], "https://example.com")
            stop(first)

            second = start()
            status, _, body = request("GET", "/api/links/restart")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["visits"], 1)
            self.assertEqual(request("DELETE", "/api/links/restart", auth=True)[0], 204)
            self.assertEqual(request("GET", "/restart")[0], 404)
            stop(second)

    def test_entry_point_rejects_missing_token(self):
        env = {key: value for key, value in os.environ.items() if not key.startswith("SNIP_")}
        result = subprocess.run(
            [sys.executable, "-m", "snip"], cwd=ROOT, env=env,
            capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("SNIP_API_TOKEN", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_entry_point_rejects_invalid_port(self):
        for port in ["0", "65536", "not-a-port"]:
            with self.subTest(port=port):
                result = subprocess.run(
                    [sys.executable, "-m", "snip"], cwd=ROOT,
                    env={**os.environ, "SNIP_PORT": port, "SNIP_API_TOKEN": "test-only"},
                    capture_output=True, text=True, timeout=5,
                )
                self.assertEqual(result.returncode, 1)
                self.assertIn("Configuration error", result.stderr)
                self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()

