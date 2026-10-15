"""Single in-memory UI page and explicit desktop bridge policy (GPL-3.0).

The listening socket is owned before WebView is created. No files or Python
methods are served by HTTP. This is a local patch, not an upstream certification.
"""
from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import secrets
import socket
import threading

PATCH_ID = 'private0516-mesh-bridge-20261007-v1'
BRIDGE_METHODS = ('snapshot', 'configure_options', 'choose', 'start', 'cancel',
                  'open_output', 'close')
PATCH_FILES = ('webview/util.py', 'webview/platforms/edgechromium.py')


def _verify_vendor_patch(webview):
    """Fail closed on a missing/partial local overlay; this is not a signature."""
    manifest = json.loads((Path(__file__).parent / 'vendor_patch/manifest.json').read_text(encoding='utf8'))
    if manifest.get('patch_id') != PATCH_ID:
        raise RuntimeError('Mesh Converter bridge patch manifest is missing or incompatible.')
    records = manifest.get('files', [])
    if {item['path'] for item in records} != set(PATCH_FILES) or len(records) != len(PATCH_FILES):
        raise RuntimeError('Mesh Converter bridge patch file list is invalid.')
    vendor_root = Path(webview.__file__).resolve().parent.parent
    for item in records:
        data = (vendor_root / item['path']).read_bytes()
        if hashlib.sha256(data).hexdigest() != item['patched_sha256']:
            raise RuntimeError('Mesh Converter requires its reviewed bridge overlay: ' + item['path'])


def attach_bridge(window, api, trusted_url, webview):
    _verify_vendor_patch(webview)
    window._private0516_trusted_url = trusted_url
    window._private0516_allowed_calls = frozenset(BRIDGE_METHODS)
    window._private0516_bridge_ready = False
    # The API instance (and its _window backreference) is never exposed.
    window.expose(*(getattr(api, name) for name in BRIDGE_METHODS))


class _ExclusiveHTTPServer(HTTPServer):
    allow_reuse_address = False
    request_queue_size = 4

    def server_bind(self):
        # On Windows, do not permit a second listener to share this socket.
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def get_request(self):
        request, address = super().get_request()
        request.settimeout(2.0)
        return request, address


class TrustedUiServer:
    """Bind synchronously; an occupied port raises before a window can open.

    A stable origin keeps localStorage preferences across launches. The new
    webview-secure1 profile deliberately does not reuse old web content/storage.
    Each launch serves just one nonce path; no API, filesystem handler or CORS.
    """
    def __init__(self, ui_path):
        page = Path(ui_path).read_bytes()
        host = '127.0.0.1:42001'
        route = '/' + secrets.token_hex(24) + '/ui.html'
        self.url = 'http://' + host + route

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.0'

            def do_GET(self):
                self._page(False)

            def do_HEAD(self):
                self._page(True)

            def _page(self, head_only):
                if self.headers.get_all('Host', []) != [host] or self.path != route:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(page)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('X-Frame-Options', 'DENY')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
                # Existing inline UI/styles and pywebview eval/new Function are
                # required. There are no external scripts, fonts, frames or APIs.
                self.send_header('Content-Security-Policy',
                    "default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval'; "
                    "style-src 'unsafe-inline'; font-src data:; img-src data:; "
                    "connect-src 'none'; frame-src 'none'; child-src 'none'; "
                    "worker-src 'none'; object-src 'none'; base-uri 'none'; "
                    "form-action 'none'; frame-ancestors 'none'")
                self.end_headers()
                if not head_only:
                    self.wfile.write(page)

            def log_message(self, format, *args):
                # Do not persist the per-launch document path in access logs.
                pass

        try:
            self._server = _ExclusiveHTTPServer(('127.0.0.1', 42001), Handler)
        except OSError as exc:
            raise RuntimeError(
                'Mesh Converter cannot reserve its local UI port (127.0.0.1:42001). '
                'Close another instance or the process using that port, then retry. '
                'No existing listener/page was used. '
                '本地界面端口被占用，程序已停止启动；请关闭另一个实例或占用端口的进程。'
            ) from exc
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        name='MeshConverter trusted UI', daemon=True)

    def __enter__(self):
        try:
            self._thread.start()
        except BaseException:
            self._server.server_close()
            raise
        return self

    def __exit__(self, *_):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=3.0)
