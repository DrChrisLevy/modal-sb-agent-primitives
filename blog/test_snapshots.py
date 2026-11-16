from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, Mock, patch

sys.path.insert(0, str(Path(__file__).parent / "steps"))
import s6_snapshots as snapshots


class SnapshotTests(unittest.TestCase):
    def test_execute_output_empty_and_error(self):
        container = Mock()
        process = container.exec.return_value
        process.wait.return_value = 0
        for value in ("hello\n", ""):
            process.stdout.read.return_value = value
            self.assertEqual(snapshots.execute(container, "true"), value.strip())
        process.wait.return_value = 7
        process.stderr.read.return_value = "failed"
        with self.assertRaisesRegex(AssertionError, "command failed: failed"):
            snapshots.execute(container, "false")

    def test_filesystem_locks_restored_container_and_cleans_up(self):
        source, restored = Mock(), Mock()
        with patch.object(snapshots, "app"), patch.object(snapshots, "base_image"), \
             patch.object(snapshots.modal.Sandbox, "create", side_effect=[source, restored]) as create, \
             patch.object(snapshots, "execute"), redirect_stdout(StringIO()):
            snapshots.filesystem()
        self.assertTrue(create.call_args.kwargs["block_network"])
        self.assertIs(create.call_args.kwargs["image"], source.snapshot_filesystem.return_value)
        source.terminate.assert_called_once_with(wait=True)
        restored.terminate.assert_called_once_with(wait=True)

    def test_filesystem_install_failure_still_stops_source(self):
        source = Mock()
        with patch.object(snapshots, "app"), patch.object(snapshots, "base_image"), \
             patch.object(snapshots.modal.Sandbox, "create", return_value=source), \
             patch.object(snapshots, "execute", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                snapshots.filesystem()
        source.terminate.assert_called_once_with(wait=True)
        source.snapshot_filesystem.assert_not_called()

    def test_start_uses_default_entrypoint_and_terminates_without_manual_snapshot(self):
        for failure in (None, RuntimeError("agent failed")):
            with self.subTest(failure=failure):
                sandbox, store = Mock(), {}
                with patch.object(snapshots, "app"), patch.object(snapshots, "base_image"), \
                     patch.object(snapshots, "sessions", return_value=store), \
                     patch.object(snapshots.modal.Sandbox, "create", return_value=sandbox) as create, \
                     patch.object(snapshots, "client_and_model", return_value=(MagicMock(), "model")), \
                     patch.object(snapshots, "run", side_effect=failure), \
                     patch.object(snapshots, "execute") as execute, redirect_stdout(StringIO()):
                    if failure is None:
                        snapshots.start("chat")
                    else:
                        with self.assertRaises(RuntimeError):
                            snapshots.start("chat")
                self.assertEqual(create.call_args.args, ())
                self.assertEqual(create.call_args.kwargs["experimental_options"], {"enable_exit_snapshot": True})
                self.assertEqual(store["chat"], sandbox.object_id)
                self.assertEqual(execute.call_count, 2 if failure is None else 1)
                sandbox.wait.assert_not_called()
                sandbox.snapshot_filesystem.assert_not_called()
                sandbox.terminate.assert_called_once_with(wait=True)

    def test_resume_reads_saved_id_and_cleans_up_on_failed_verification(self):
        previous, restored = Mock(), Mock()
        with patch.object(snapshots, "app"), patch.object(snapshots, "sessions", return_value={"chat": "sb-saved"}), \
             patch.object(snapshots.modal.Sandbox, "from_id", return_value=previous) as lookup, \
             patch.object(snapshots.modal.Sandbox, "create", return_value=restored), \
             patch.object(snapshots, "execute", side_effect=AssertionError):
            with self.assertRaises(AssertionError):
                snapshots.resume("chat")
        lookup.assert_called_once_with("sb-saved")
        previous._experimental_get_exit_snapshot.assert_called_once_with(timeout=180)
        restored.terminate.assert_called_once_with(wait=True)

    def test_missing_conversation_does_not_create_a_container(self):
        with patch.object(snapshots, "sessions", return_value={}), \
             patch.object(snapshots.modal.Sandbox, "create") as create:
            with self.assertRaises(KeyError):
                snapshots.resume("missing")
        create.assert_not_called()

    def test_memory_restores_counter_and_cleans_up(self):
        source, restored = Mock(), Mock()
        with patch.object(snapshots, "app"), patch.object(snapshots, "base_image"), \
             patch.object(snapshots, "wait_for"), \
             patch.object(snapshots, "execute", side_effect=["1", "2", "3"]), \
             patch.object(snapshots.modal.Sandbox, "create", return_value=source) as create, \
             patch.object(snapshots.modal.Sandbox, "_experimental_from_snapshot", return_value=restored), \
             redirect_stdout(StringIO()):
            snapshots.memory()
        self.assertEqual(create.call_args.kwargs["runtime"], "vm")
        self.assertTrue(create.call_args.kwargs["_experimental_enable_snapshot"])
        source.terminate.assert_called_once_with(wait=True)
        restored.terminate.assert_called_once_with(wait=True)
