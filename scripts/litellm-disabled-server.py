#!/usr/bin/env python3
"""Keep a deliberately disabled LiteLLM pod live but unready.

The proxy's liveness endpoint stays healthy so Kubernetes does not restart it
in a loop when Azure configuration is incomplete. Readiness remains 503, which
prevents the private Service from routing AI traffic to the disabled process.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from os import environ


class DisabledLiteLLMHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - HTTP handler API
        status = 200 if self.path == "/health/liveliness" else 503
        body = b'{"status":"disabled","detail":"Azure AI Foundry configuration is incomplete"}'
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        """Avoid request noise while the readiness probe checks this endpoint."""


if __name__ == "__main__":
    port = int(environ.get("LITELLM_DISABLED_PORT", "4000"))
    ThreadingHTTPServer(("0.0.0.0", port), DisabledLiteLLMHandler).serve_forever()
