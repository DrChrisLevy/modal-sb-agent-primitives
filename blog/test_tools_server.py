import http.server
import json
from pathlib import Path
import sys
import subprocess
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).parent / "steps"))
from tools_server import Tools


class ToolsTests(unittest.TestCase):
    def setUp(self):
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Tools)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()

    def request(self, data):
        with urllib.request.urlopen(self.url, data=data) as response:
            return json.load(response)

    def test_commands(self):
        original = subprocess.run
        with patch("tools_server.subprocess.run", side_effect=lambda *a, **kw: original(*a, **{**kw, "cwd": "/"})) as run:
            for command, expected in [("printf hello", {"exit": 0, "output": "hello"}),
                                      ("true", {"exit": 0, "output": ""}),
                                      ("printf error >&2; exit 7", {"exit": 7, "output": "error"})]:
                self.assertEqual(self.request(json.dumps({"command": command}).encode()), expected)
            self.assertEqual(run.call_args.kwargs["cwd"], "/workspace")
            self.assertEqual(run.call_args.kwargs["timeout"], 60)

    def test_timeout(self):
        with patch("tools_server.subprocess.run", side_effect=subprocess.TimeoutExpired("bash", 60)):
            self.assertEqual(self.request(b'{"command":"sleep 99"}'),
                             {"exit": 124, "output": "command timed out"})

    def test_invalid_request(self):
        for body in (b"", b"{}", b'{"command":null}'):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.request(body)
            self.assertEqual(error.exception.code, 400)
            error.exception.close()
