"""PC device credentials never follow a server-selected redirect."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from worker.client import WorkerApiError, checked_server, request


@pytest.mark.parametrize("server", [
    "http://example.com", "https://user:pass@example.com", "https://@example.com",
    "https://example.com/path", "https://example.com?x=1", "https://example.com/#part",
    "https://example.com:bad", "https://example.com:0",
])
def test_server_address_must_be_single_trusted_origin(server):
    with pytest.raises(WorkerApiError):
        checked_server(server)


def test_token_is_not_forwarded_on_redirect():
    captured = []

    class Target(BaseHTTPRequestHandler):
        def do_POST(self):
            captured.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *_):
            pass

    target = ThreadingHTTPServer(("127.0.0.1", 0), Target)

    class Redirect(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{target.server_port}/steal")
            self.end_headers()

        def log_message(self, *_):
            pass

    origin = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
    threads = [Thread(target=server.serve_forever, daemon=True) for server in (origin, target)]
    for thread in threads:
        thread.start()
    try:
        with pytest.raises(WorkerApiError):
            request(f"http://127.0.0.1:{origin.server_port}", "/api/v1/pc/heartbeat", "secret-token", {})
        assert captured == []
    finally:
        for server in (origin, target):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=2)
