import concurrent.futures
import http.client
import json
import os
import tempfile
import threading
import unittest
from unittest.mock import patch

from snip import Server, Store


class SnipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, 'links.db')
        self.start_server()

    def start_server(self):
        self.server = Server(('127.0.0.1', 0), Store(self.db), 'secret', 'https://snip.test')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def tearDown(self):
        self.stop_server()
        self.tmp.cleanup()

    def request(self, method, path, data=None, token=None, raw=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        headers = {}
        if token is not None:
            headers['Authorization'] = token
        if data is not None:
            raw = json.dumps(data)
            headers['Content-Type'] = 'application/json'
        conn.request(method, path, body=raw, headers=headers)
        response = conn.getresponse()
        content = response.read()
        result = (response.status, dict(response.getheaders()), json.loads(content) if content else None)
        conn.close()
        return result

    def create(self, slug='example', url='https://example.com/a?x=1'):
        return self.request('POST', '/api/links', {'url': url, 'slug': slug}, 'Bearer secret')

    def test_full_lifecycle_and_persistence(self):
        status, _, data = self.create()
        self.assertEqual(status, 201)
        self.assertEqual(data['short_url'], 'https://snip.test/example')
        self.assertTrue(data['created_at'].endswith('Z'))
        self.assertEqual(self.create()[0], 409)
        status, headers, _ = self.request('GET', '/example')
        self.assertEqual((status, headers['Location']), (302, 'https://example.com/a?x=1'))
        self.assertEqual(self.request('GET', '/api/links/example')[2]['visits'], 1)
        self.stop_server()
        self.start_server()
        self.assertEqual(self.request('GET', '/api/links/example')[2]['visits'], 1)
        self.assertEqual(self.request('DELETE', '/api/links/example', token='Bearer secret')[0], 204)
        self.assertEqual(self.request('GET', '/example')[0], 404)
        self.assertEqual(self.request('GET', '/api/links/example')[0], 404)
        self.assertEqual(self.request('DELETE', '/api/links/example', token='Bearer secret')[0], 404)
        self.assertEqual(self.request('GET', '/healthz')[0], 200)

    def test_authentication(self):
        for token in (None, 'Bearer wrong', 'secret'):
            self.assertEqual(self.request('POST', '/api/links', {'url': 'https://example.com'}, token)[0], 401)
            self.assertEqual(self.request('DELETE', '/api/links/example', token=token)[0], 401)

    def test_invalid_inputs(self):
        for url in ('', 'example.com', 'ftp://example.com', 'http://', 'http://example.com:bad', 'https://example.com/\n', 'https://example.com/' + 'a' * 2049, None):
            with self.subTest(url=url):
                self.assertEqual(self.request('POST', '/api/links', {'url': url}, 'Bearer secret')[0], 400)
        for slug in ('ab', 'a' * 33, 'a.b', 'healthz', None, 123):
            with self.subTest(slug=slug):
                self.assertEqual(self.create(slug)[0], 400)
        for raw in ('{', '[]', '{}'):
            self.assertEqual(self.request('POST', '/api/links', token='Bearer secret', raw=raw)[0], 400)

    def test_generated_slug_retries_collisions(self):
        self.create('collision')
        with patch('snip.secrets.token_urlsafe', side_effect=['collision', 'fresh_slug']):
            status, _, data = self.request('POST', '/api/links', {'url': 'http://example.org'}, 'Bearer secret')
        self.assertEqual((status, data['slug']), (201, 'fresh_slug'))

    def test_concurrent_visits(self):
        self.create()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            statuses = list(pool.map(lambda _: self.request('GET', '/example')[0], range(24)))
        self.assertEqual(statuses, [302] * 24)
        self.assertEqual(self.request('GET', '/api/links/example')[2]['visits'], 24)


if __name__ == '__main__':
    unittest.main()
