import http.client
import os
import threading
import urllib.error
import io
import unittest
from unittest.mock import MagicMock, mock_open, patch
from http.server import ThreadingHTTPServer


from steps import key_proxy as proxy


class ProxyTests(unittest.TestCase):
    def request(self, body, method="GET", status=200):
        response = MagicMock(status=status)
        response.headers = {"Content-Type": "text/event-stream"}
        response.read.return_value = body
        response.__enter__.return_value = response
        audit = mock_open()
        error = urllib.error.HTTPError("https://httpbin.org/headers", status, "error",
                                       response.headers, io.BytesIO(body)) if status >= 400 else None
        with patch.dict(os.environ, BLOG_DEMO_KEY="dummy", KEY_ENV="BLOG_DEMO_KEY", UPSTREAM="https://httpbin.org"), patch.object(
            proxy.urllib.request, "urlopen", return_value=response, side_effect=error,
        ) as upstream, patch("builtins.open", audit):
            with ThreadingHTTPServer(("127.0.0.1", 0), proxy.Proxy) as server:
                worker = threading.Thread(target=server.serve_forever)
                worker.start()
                try:
                    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                    connection.request(method, "/headers", body=b'{}' if method == "POST" else None,
                                       headers={"Content-Type": "application/json"})
                    result = connection.getresponse()
                    with result:
                        self.assertEqual(result.getheader("Content-Type"), "text/event-stream")
                        status, data = result.status, result.read()
                    connection.close()
                finally:
                    server.shutdown()
                    worker.join()
        return status, data, upstream, audit

    def test_forwards_get_with_credential_and_audits(self):
        status, body, upstream, audit = self.request(b"hello")
        self.assertEqual((status, body), (200, b"hello"))
        request = upstream.call_args.args[0]
        self.assertEqual(request.full_url, "https://httpbin.org/headers")
        self.assertEqual(request.get_header("Authorization"), "Bearer dummy")
        audit().write.assert_called_once_with("GET /headers\n")

    def test_empty_response(self):
        status, body, _, _ = self.request(b"")
        self.assertEqual((status, body), (200, b""))

    def test_post_body(self):
        status, body, upstream, audit = self.request(b"data: done\n\n", "POST")
        request = upstream.call_args.args[0]
        self.assertEqual(request.data, b"{}")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual((status, body), (200, b"data: done\n\n"))
        audit().write.assert_called_once_with("POST /headers\n")

    def test_upstream_error_status_and_body(self):
        status, body, _, _ = self.request(b"bad request", "POST", 400)
        self.assertEqual((status, body), (400, b"bad request"))

if __name__ == "__main__":
    unittest.main()
