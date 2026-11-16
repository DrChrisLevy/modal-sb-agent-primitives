"""A small, fixed-upstream credential proxy; run only in the trusted Sidecar."""

# region: proxy
import http.server
import os
import urllib.error
import urllib.request


class Proxy(http.server.BaseHTTPRequestHandler):
    def forward(self):
        key = os.environ[os.environ["KEY_ENV"]]
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        request = urllib.request.Request(
            os.environ["UPSTREAM"] + self.path, data=body or None, method=self.command,
            headers={"Authorization": "Bearer " + key,
                     "Content-Type": self.headers.get("Content-Type", "application/json")},
        )
        with open("/tmp/key-proxy-audit.log", "a") as audit:
            audit.write(f"{self.command} {self.path}\n")
        try:
            response = urllib.request.urlopen(request, timeout=180)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            body = response.read()
            self.send_response(response.status)
            self.send_header("Content-Type", response.headers.get("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    do_GET = do_POST = forward


if __name__ == "__main__":
    http.server.ThreadingHTTPServer(("0.0.0.0", 8080), Proxy).serve_forever()
# endregion
