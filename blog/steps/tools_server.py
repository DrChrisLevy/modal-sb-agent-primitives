"""Run shell commands in the untrusted tools container."""

# region: server
import http.server
import json
import subprocess


class Tools(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            command = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["command"]
            if not isinstance(command, str):
                raise TypeError("command must be a string")
            result = subprocess.run(["bash", "-lc", command], cwd="/workspace",
                                    capture_output=True, text=True, timeout=60)
            payload = {"exit": result.returncode, "output": result.stdout + result.stderr}
        except subprocess.TimeoutExpired:
            payload = {"exit": 124, "output": "command timed out"}
        except (ValueError, KeyError, TypeError):
            self.send_error(400, "Expected a JSON command")
            return
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    http.server.ThreadingHTTPServer(("0.0.0.0", 8080), Tools).serve_forever()
# endregion
