"""Small HTTP API for importing .mokuro files made elsewhere. LAN only, no auth.

GET  /series  -> {"series": [{"name", "chapters", "published"}]}
POST /import  {"series": str, "files": [{"name": str, "content": str}]}
              -> {"results": [{"name", "status", "detail"}]}
"""

import json
import logging
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .config import Config
from .importer import InvalidImport, import_mokuro, list_series, to_dict
from .registry import Registry

log = logging.getLogger(__name__)

MAX_BODY_BYTES = 200 * 1024 * 1024


def make_server(config: Config, port: int, host: str = "0.0.0.0") -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/health":
                self._send(HTTPStatus.OK, {"status": "ok"})
            elif self.path == "/series":
                self._send(HTTPStatus.OK, {"series": [to_dict(s) for s in list_series(config)]})
            else:
                self._send(HTTPStatus.NOT_FOUND, {"error": "route not found"})

        def do_POST(self) -> None:
            if self.path != "/import":
                self._send(HTTPStatus.NOT_FOUND, {"error": "route not found"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY_BYTES:
                self._send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "body too large"})
                return
            try:
                body = json.loads(self.rfile.read(length))
                series = body["series"]
                files = [(f["name"], f["content"].encode("utf-8")) for f in body["files"]]
            except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
                self._send(HTTPStatus.BAD_REQUEST, {"error": "invalid body"})
                return
            # sqlite connections can't cross threads, and each request runs in its own.
            registry = Registry(config.state_db)
            try:
                results = import_mokuro(config, registry, series, files)
            except InvalidImport as e:
                self._send(HTTPStatus.BAD_REQUEST, {"error": str(e)})
                return
            finally:
                registry.close()
            log.info(
                "import %s: %s",
                series,
                ", ".join(f"{r.name}={r.status}" for r in results) or "no files",
            )
            self._send(HTTPStatus.OK, {"results": [to_dict(r) for r in results]})

        def _send(self, status: HTTPStatus, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:
            log.debug("api: " + format, *args)

    return ThreadingHTTPServer((host, port), Handler)


def start_api(config: Config, port: int) -> ThreadingHTTPServer:
    server = make_server(config, port)
    threading.Thread(target=server.serve_forever, name="api", daemon=True).start()
    return server
