"""Serve the Shake Jelly Balls reference site (the site/ folder) as plain static
files. No database, no login, no betting -- this is the public stats site.

    python server/serve_site.py            # http://localhost:8000
    python server/serve_site.py --lan      # reachable from phones on the wifi
    python server/serve_site.py --port 9000

The site is a hash-routed single page, so the server only ever hands out a
handful of files (index.html, app.js, styles.css, data.json, logo.jpg). Any
unknown path falls back to index.html so a stray URL still lands somewhere sane.

Run server/build_site.py first (or after adding a game) to (re)generate
site/data.json -- this server just serves whatever is on disk.
"""

import argparse
import mimetypes
import pathlib
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = ROOT / "site"


class Handler(BaseHTTPRequestHandler):
    server_version = "SJBStats/1.0"

    def log_message(self, fmt, *args):
        pass  # quiet; NSSM captures stdout and we don't want a request log flood

    def do_GET(self):
        path = unquote(urlparse(self.path).path).lstrip("/")
        rel = path or "index.html"
        target = (SITE / rel).resolve()

        # path-traversal guard: must stay inside site/
        if not str(target).startswith(str(SITE.resolve())):
            self.send_error(403, "Forbidden")
            return

        # SPA / stray-URL fallback: a stray ROUTE (no file extension) -> index.html so
        # the hash-router can take over. A missing file that looks like an asset (has an
        # extension, e.g. a player photo or stylesheet) must 404 cleanly — serving
        # index.html in its place made missing images come back as 200 text/html, which
        # the browser then failed to decode (looked like a broken/"sporadic" photo).
        if not target.is_file():
            if pathlib.PurePosixPath(rel).suffix:
                self.send_error(404, "Not found")
                return
            target = SITE / "index.html"
            if not target.is_file():
                self.send_error(404, "Site not built — run server/build_site.py")
                return

        ctype, _ = mimetypes.guess_type(str(target))
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        # The whole site is a few small files that change together on a rebuild,
        # so never serve stale HTML/JS/CSS/JSON. Only the logo is worth caching.
        if target.suffix.lower() in (".jpg", ".jpeg", ".png", ".svg", ".ico", ".webp"):
            self.send_header("Cache-Control", "max-age=86400")
        else:
            self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    do_HEAD = do_GET


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def main():
    ap = argparse.ArgumentParser(description="SJB reference site static server")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--lan", action="store_true",
                    help="listen on all interfaces so phones on the same wifi can reach it")
    args = ap.parse_args()

    if not (SITE / "data.json").is_file():
        print("  WARNING: site/data.json is missing — run: python server/build_site.py")

    host = "0.0.0.0" if args.lan else "127.0.0.1"
    httpd = ThreadingHTTPServer((host, args.port), Handler)
    print("\n  Shake Jelly Balls — stats")
    print(f"  {'-' * 40}")
    print(f"  local   http://localhost:{args.port}")
    if args.lan:
        print(f"  wifi    http://{lan_ip()}:{args.port}")
    print("  Ctrl+C to stop.\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.\n")


if __name__ == "__main__":
    main()
