from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, Mock, patch

sys.path.insert(0, str(Path(__file__).parent / "steps"))
import s7_building_blocks as blocks


class BuildingBlockTests(unittest.TestCase):
    def test_server_uses_connect_token_and_stops_sandbox(self):
        sandbox = Mock()
        sandbox.create_connect_token.return_value = Mock(url="https://sandbox.example", token="test-token")
        response = MagicMock()
        response.__enter__.return_value.status = 200
        response.__enter__.return_value.read.return_value = b"Directory listing for /workspace"
        output = StringIO()
        with patch.object(blocks, "app") as app, patch.object(blocks, "base_image") as image, \
             patch.object(blocks, "wait_for") as wait_for, \
             patch.object(blocks.modal.Sandbox, "create", return_value=sandbox) as create, \
             patch.object(blocks.urllib.request, "urlopen", return_value=response) as urlopen, redirect_stdout(output):
            blocks.server()
        create.assert_called_once_with("python", "-m", "http.server", "8080",
            app=app.return_value, image=image.return_value, workdir="/workspace")
        wait_for.assert_called_once_with(sandbox, "127.0.0.1", 8080)
        sandbox.create_connect_token.assert_called_once_with(port=8080)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://sandbox.example")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-token")
        self.assertEqual(urlopen.call_args.kwargs, {"timeout": 30})
        sandbox.terminate.assert_called_once_with(wait=True)
        self.assertIn("PASS: app reached the Sandbox server with a Connect Token", output.getvalue())

    def test_server_stops_sandbox_on_request_error_or_invalid_response(self):
        for error, status, body in ((TimeoutError(), 200, b"Directory listing"),
                                    (None, 403, b"Directory listing"), (None, 200, b"")):
            with self.subTest(error=error, status=status, body=body):
                sandbox = Mock()
                sandbox.create_connect_token.return_value = Mock(url="https://sandbox.example", token="test-token")
                response = MagicMock()
                response.__enter__.return_value.status = status
                response.__enter__.return_value.read.return_value = body
                with patch.object(blocks, "app"), patch.object(blocks, "base_image"), \
                     patch.object(blocks, "wait_for"), \
                     patch.object(blocks.modal.Sandbox, "create", return_value=sandbox), \
                     patch.object(blocks.urllib.request, "urlopen", return_value=response, side_effect=error):
                    with self.assertRaises(TimeoutError if error else AssertionError):
                        blocks.server()
                sandbox.terminate.assert_called_once_with(wait=True)
