"""An HTTP counter stored only in process memory."""

# region: counter
import http.server


class Counter(http.server.BaseHTTPRequestHandler):
    count = 0

    def do_GET(self):
        Counter.count += 1
        body = str(Counter.count).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    http.server.HTTPServer(("127.0.0.1", 8080), Counter).serve_forever()
# endregion
