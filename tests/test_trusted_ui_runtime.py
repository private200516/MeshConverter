"""Socket isolation and exact-document routing for native runtime smoke tests."""
import gzip
from http.client import HTTPConnection
from urllib.parse import urlsplit
from pathlib import Path
import socket
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener
from trusted_ui import TrustedUiServer


class TrustedUiRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.page = Path(self.temp.name) / 'ui.html'
        self.page.write_text('<html>local smoke document</html>', encoding='utf-8')
        self.http = build_opener(ProxyHandler({}))

    def tearDown(self):
        self.temp.cleanup()

    def test_parallel_smoke_instances_own_different_ports_and_nonces(self):
        with TrustedUiServer(self.page, port=0) as first, TrustedUiServer(self.page, port=0) as second:
            self.assertNotEqual(first.url, second.url)
            self.assertNotEqual(first._server.server_address[1], second._server.server_address[1])
            for server in (first, second):
                with self.http.open(server.url, timeout=3) as response:
                    self.assertEqual(response.read(), self.page.read_bytes())
                    self.assertIn("connect-src 'none'", response.headers['Content-Security-Policy'])
                    self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_webview_can_finish_reading_before_socket_reuse(self):
        with TrustedUiServer(self.page, port=0) as server:
            route = urlsplit(server.url)
            client = HTTPConnection(route.hostname, route.port, timeout=3)
            try:
                client.request('GET', route.path)
                page = client.getresponse()
                self.assertEqual(page.version, 11)
                self.assertEqual(page.read(), self.page.read_bytes())
                connection = client.sock
                self.assertIsNotNone(connection)
                client.request('HEAD', route.path)
                head = client.getresponse()
                self.assertEqual(head.status, 200)
                self.assertEqual(head.read(), b'')
                self.assertIs(client.sock, connection)
            finally:
                client.close()

    def test_compressed_document_preserves_exact_content_and_trusted_headers(self):
        original = b'<p>local data</p>' * 4000
        self.page.write_bytes(original)
        with TrustedUiServer(self.page, port=0) as server:
            for accepted in ('gzip, deflate, br', 'gzip;q=0', 'identity'):
                request = Request(server.url, headers={'Accept-Encoding': accepted})
                with self.http.open(request, timeout=3) as response:
                    body = response.read()
                    self.assertEqual(int(response.headers['Content-Length']), len(body))
                    self.assertIn("connect-src 'none'", response.headers['Content-Security-Policy'])
                    if accepted.startswith('gzip,'):
                        self.assertEqual(response.headers['Content-Encoding'], 'gzip')
                        self.assertEqual(gzip.decompress(body), original)
                        self.assertLess(len(body), len(original))
                    else:
                        self.assertIsNone(response.headers['Content-Encoding'])
                        self.assertEqual(body, original)

    def test_nonce_route_and_host_header_are_both_required(self):
        with TrustedUiServer(self.page, port=0) as server:
            for request in (Request(server.url, headers={'Host': 'localhost'}),
                            Request(server.url.rsplit('/', 1)[0] + '/other.html')):
                with self.assertRaises(HTTPError) as caught:
                    self.http.open(request, timeout=3)
                self.assertEqual(caught.exception.code, 404)

    def test_occupied_explicit_port_does_not_reuse_another_listener(self):
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1', 0))
            occupied.listen(1)
            with self.assertRaisesRegex(RuntimeError, 'No existing listener/page was used'):
                TrustedUiServer(self.page, port=occupied.getsockname()[1])

    def test_invalid_port_is_rejected(self):
        for port in (-1, 65536, True, '42001'):
            with self.assertRaises(ValueError):
                TrustedUiServer(self.page, port=port)


if __name__ == '__main__':
    unittest.main()
