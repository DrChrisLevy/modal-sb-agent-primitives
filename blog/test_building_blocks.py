from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, Mock, patch

sys.path.insert(0, str(Path(__file__).parent / "steps"))
import s7_building_blocks as blocks


class BuildingBlockTests(unittest.TestCase):
    def test_named_running_sandbox_is_reused(self):
        with patch.object(blocks.modal.Sandbox, "from_name", return_value=Mock()) as lookup, \
             patch.object(blocks.modal.Sandbox, "create") as create:
            self.assertIs(blocks.get_sandbox("chat-a"), lookup.return_value)
        lookup.assert_called_once_with(blocks.APP_NAME, "chat-a")
        create.assert_not_called()

    def test_missing_name_creates_fresh_or_restores_with_same_name(self):
        for store in ({}, {"s7/chat-a": "sb-old"}):
            with self.subTest(store=store):
                restoring = bool(store)
                with patch.object(blocks, "app"), patch.object(blocks, "base_image") as base, \
                     patch.object(blocks, "sessions", return_value=store), \
                     patch.object(blocks.modal.Sandbox, "from_name", side_effect=blocks.modal.exception.NotFoundError), \
                     patch.object(blocks.modal.Sandbox, "from_id") as previous, \
                     patch.object(blocks.modal.Sandbox, "create") as create:
                    sandbox = blocks.get_sandbox("chat-a")
                self.assertEqual(create.call_args.kwargs["name"], "chat-a")
                self.assertEqual(store["s7/chat-a"], sandbox.object_id)
                if restoring:
                    previous.assert_called_once_with("sb-old")
                    previous.return_value._experimental_get_exit_snapshot.assert_called_once_with(timeout=180)
                    self.assertIs(create.call_args.kwargs["image"], previous.return_value._experimental_get_exit_snapshot.return_value)
                else:
                    previous.assert_not_called()
                    self.assertIs(create.call_args.kwargs["image"], base.return_value)

    def test_turn_loads_history_and_saves_only_its_conversation_file(self):
        history = [{"role": "user", "content": "apples"}]
        for data, expected in (([json.dumps(history).encode()], history), (FileNotFoundError(), None)):
            with self.subTest(data=data):
                volume = MagicMock()
                if isinstance(data, Exception):
                    volume.read_file.side_effect = data
                else:
                    volume.read_file.return_value = data
                result = [{"role": "assistant", "content": "apples"}]
                with patch.object(blocks, "get_sandbox") as sandbox, \
                     patch.object(blocks, "histories", return_value=volume), \
                     patch.object(blocks, "client_and_model", return_value=(MagicMock(), "model")), \
                     patch.object(blocks, "run", return_value=result) as run:
                    self.assertEqual(blocks.turn("chat-a", "question"), "apples")
                self.assertEqual(run.call_args.kwargs["messages"], expected)
                volume.read_file.assert_called_once_with("/history/chat-a.json")
                upload = volume.batch_upload.return_value.__enter__.return_value.put_file
                payload, path = upload.call_args.args
                self.assertEqual(path, "/history/chat-a.json")
                self.assertEqual(json.loads(payload.getvalue()), result)

    def test_failed_turn_does_not_save_incomplete_history(self):
        volume = MagicMock()
        volume.read_file.side_effect = FileNotFoundError
        with patch.object(blocks, "get_sandbox"), patch.object(blocks, "histories", return_value=volume), \
             patch.object(blocks, "client_and_model", return_value=(MagicMock(), "model")), \
             patch.object(blocks, "run", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                blocks.turn("chat-b", "question")
        volume.batch_upload.assert_not_called()
