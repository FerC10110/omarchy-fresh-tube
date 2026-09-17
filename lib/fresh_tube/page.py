"""The page that embeds YouTube's player for the browser fallback.

YouTube's embedded player refuses to play (error 153) unless a referring page embeds it, so
`play` cannot open the embed URL directly: instead the `place-window` helper serves this page on a
loopback port for as long as the browser window is open, and the browser embeds the player from it.
"""
import http.server
import threading

EMBED_URL = "https://www.youtube.com/embed/{}?autoplay=1"
PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Fresh Tube</title>
<style>
html, body {{ margin: 0; height: 100%; background: #000; overflow:hidden }}
iframe {{ position: fixed; inset: 0; width: 100%; height: 100%; border: 0 }}
</style>
</head>
<body>
<iframe src="{src}" allow="autoplay; fullscreen; encrypted-media; picture-in-picture" allowfullscreen></iframe>
</body>
</html>
"""


def page_html(video_id):
    return PAGE.format(src=EMBED_URL.format(video_id))


class Handler(http.server.BaseHTTPRequestHandler):
    video_id = ""

    def do_GET(self):
        if self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        body = page_html(self.video_id).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # the helper's output goes nowhere anyway


class PageServer(http.server.HTTPServer):
    """An HTTP server over a socket that is already bound and listening."""

    def __init__(self, sock, handler):
        super().__init__(sock.getsockname(), handler, bind_and_activate=False)
        self.socket.close()
        self.socket = sock
        self.server_address = sock.getsockname()


def serve(sock, video_id):
    """Serve the page for `video_id` on `sock` from a daemon thread; returns the server."""
    handler = type("PageHandler", (Handler,), {"video_id": video_id})
    server = PageServer(sock, handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
