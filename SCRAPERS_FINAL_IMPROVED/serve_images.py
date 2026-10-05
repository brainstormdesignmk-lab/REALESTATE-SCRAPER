# serve_images.py
# Tiny static server for the processed property images, meant to sit behind a
# Cloudflare Tunnel on the T60. It binds to localhost only (the tunnel connects
# locally), so nothing is exposed on the LAN directly.
#
#   .venv/bin/python serve_images.py                 # 127.0.0.1:8088
#   .venv/bin/python serve_images.py --port 8090 --root /path/to/images
#   METROPOLIS_IMAGES_DIR=/path .venv/bin/python serve_images.py
#
# The Lovable app points image URLs at the tunnel hostname, e.g.
#   https://img.example.com/<property-key>/01.jpg
#
# Cache headers are intentionally aggressive: image files are content-addressed
# by property key and never edited in place, so Cloudflare (and the browser) can
# hold them for a year. That is what keeps a short T60 outage from breaking
# pages that were already served.

from __future__ import annotations

import argparse
import os
import posixpath
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, "_shared"))

try:
    from media import images_root as _images_root
except Exception:  # keep the server usable even without the scraper deps
    def _images_root(_variant_dir=None):  # type: ignore
        return os.environ.get("METROPOLIS_IMAGES_DIR") or os.path.join(
            BASE_DIR, "output", "images"
        )

CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".png": "image/png",
    ".json": "application/json; charset=utf-8",
}
CACHE_SECONDS = 31536000  # one year


class ImageHandler(BaseHTTPRequestHandler):
    server_version = "MetropolisImages/1.0"
    root = ""

    def _resolve(self, url_path: str):
        """Map a URL path to a file inside the root, refusing traversal."""
        path = posixpath.normpath(url_path.split("?", 1)[0]).lstrip("/")
        if not path or path.startswith(".."):
            return None
        candidate = os.path.realpath(os.path.join(self.root, path))
        if candidate != self.root and not candidate.startswith(self.root + os.sep):
            return None
        if os.path.isfile(candidate):
            return candidate
        return None

    def _send(self, status: int, body: bytes = b"", ctype: str = "text/plain; charset=utf-8",
              cache: bool = False):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        if cache:
            self.send_header("Cache-Control", f"public, max-age={CACHE_SECONDS}, immutable")
        else:
            self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if self.command != "HEAD" and body:
            self.wfile.write(body)

    def _handle(self):
        if self.command not in ("GET", "HEAD"):
            self._send(405)
            return
        if self.path in ("/", "/health", "/healthz"):
            self._send(200, b"ok", cache=False)
            return
        file_path = self._resolve(self.path)
        if not file_path:
            self._send(404)
            return
        ext = os.path.splitext(file_path)[1].lower()
        ctype = CONTENT_TYPES.get(ext, "application/octet-stream")
        try:
            with open(file_path, "rb") as fh:
                body = fh.read()
        except OSError:
            self._send(500)
            return
        self._send(200, body, ctype=ctype, cache=True)

    do_GET = _handle
    do_HEAD = _handle

    def log_message(self, fmt, *args):  # quieter, single-line, timestamped
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def main():
    parser = argparse.ArgumentParser(description="Serve the processed property images.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default 127.0.0.1).")
    parser.add_argument("--port", type=int, default=8088, help="Port (default 8088).")
    parser.add_argument("--root", default=None,
                        help="Images root. Defaults to $METROPOLIS_IMAGES_DIR or ./output/images.")
    args = parser.parse_args()

    root = os.path.realpath(args.root or _images_root(BASE_DIR))
    os.makedirs(root, exist_ok=True)
    ImageHandler.root = root

    httpd = ThreadingHTTPServer((args.host, args.port), ImageHandler)
    print(f"Serving {root} on http://{args.host}:{args.port}  (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
