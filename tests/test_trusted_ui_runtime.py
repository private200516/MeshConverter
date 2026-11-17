"""Socket isolation and exact-document routing for native runtime smoke tests."""
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
