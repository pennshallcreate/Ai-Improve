"""Ai-Improve web server.

A dependency-light HTTP server (stdlib only, aside from `requests`) that
serves the UI and exposes a small JSON API for training the AI, asking it to
classify text, and giving it live internet access.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from core import TextClassifier, fetch_url, search

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
MODEL_PATH = os.path.join(BASE_DIR, "data", "model.json")
PORT = int(os.environ.get("PORT", "8000"))

clf = TextClassifier(MODEL_PATH)

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "AiImprove/1.0"

    # ---- helpers --------------------------------------------------------
    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        return json.loads(self.rfile.read(length) or b"{}")

    def _serve_static(self, path: str) -> None:
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        full = os.path.normpath(os.path.join(STATIC_DIR, rel))
        if not full.startswith(STATIC_DIR) or not os.path.isfile(full):
            self._json({"error": "not found"}, 404)
            return
        ext = os.path.splitext(full)[1]
        with open(full, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", _CONTENT_TYPES.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---- routing --------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        try:
            if route == "/api/stats":
                self._json(clf.stats())
            elif route == "/api/health":
                self._json({"ok": True})
            else:
                self._serve_static(route)
        except Exception as exc:  # noqa: BLE001
            self._json({"error": str(exc)}, 500)

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        try:
            data = self._read_json()
            if route == "/api/train":
                self._json(clf.train(data.get("text", ""), data.get("label", "")))
            elif route == "/api/train-batch":
                self._json(clf.train_batch(data.get("examples", [])))
            elif route == "/api/predict":
                self._json(clf.predict(data.get("text", "")))
            elif route == "/api/reset":
                self._json(clf.reset())
            elif route == "/api/web/search":
                self._json(search(data.get("query", ""), int(data.get("limit", 5))))
            elif route == "/api/web/fetch":
                self._json(fetch_url(data.get("url", "")))
            elif route == "/api/web/learn":
                self._json(self._learn_from_web(data))
            else:
                self._json({"error": "unknown endpoint"}, 404)
        except ValueError as exc:
            self._json({"error": str(exc)}, 400)
        except Exception as exc:  # noqa: BLE001
            self._json({"error": str(exc)}, 500)

    # ---- combined feature: learn from the internet ----------------------
    def _learn_from_web(self, data: dict) -> dict:
        """Search the web for a query and train the AI on the results."""
        query = data.get("query", "")
        label = (data.get("label") or query).strip()
        found = search(query, int(data.get("limit", 5)))
        examples = [
            {"text": f"{r['title']} {r['snippet']}", "label": label, "source": "web"}
            for r in found["results"] if r.get("snippet") or r.get("title")
        ]
        result = clf.train_batch(examples)
        result["query"] = query
        result["label"] = label
        result["used_results"] = len(examples)
        return result

    def log_message(self, fmt, *args):  # quieter logs
        pass


def main() -> None:
    httpd = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Ai-Improve running at http://localhost:{PORT}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()


if __name__ == "__main__":
    main()
