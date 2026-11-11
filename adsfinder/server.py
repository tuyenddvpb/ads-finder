"""Web server local để xem kết quả."""
import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import db
from .scoring import WEIGHTS, build_groups

INDEX = Path(__file__).parent / "web" / "index.html"


def build_payload(conn, exclude_terms):
    groups = build_groups(conn, exclude_terms)
    runs = [r["last_run"] for r in conn.execute("SELECT last_run FROM queries")]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "last_run": max(runs) if runs else None,
        "weights": WEIGHTS,
        "keywords": sorted({k for g in groups for k in g["keywords"]}),
        "countries": sorted({c for g in groups for c in g["countries"]}),
        "total_ads": sum(g["n_total"] for g in groups),
        "groups": groups,
    }


def make_handler(db_path, exclude_terms):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status, body, content_type):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                self._send(200, INDEX.read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/data":
                conn = db.connect(db_path)
                try:
                    payload = build_payload(conn, exclude_terms)
                finally:
                    conn.close()
                self._send(200, json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8")
            else:
                self._send(404, b"Not found", "text/plain; charset=utf-8")

        def log_message(self, *args):
            pass

    return Handler


def serve(db_path, exclude_terms, port, host="127.0.0.1"):
    server = ThreadingHTTPServer((host, port), make_handler(db_path, exclude_terms))
    print(f"Mở trình duyệt tại http://{host}:{port}  (Ctrl+C để dừng)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
