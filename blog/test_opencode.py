from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parent / "steps"))
import s4_opencode as opencode


class OpenCodeTests(unittest.TestCase):
    def test_trace_precedes_answer_for_normal_empty_and_failed_runs(self):
        for trace, answer, status in (("$ python demo.py\ntrace\n", "Final answer\n", 0),
                                      ("", "", 0), ("tool failed\n", "", 1)):
            with self.subTest(status=status, trace=trace):
                sandbox = Mock()
                process = sandbox.exec.return_value
                process.stderr.read.return_value = trace
                process.stdout.read.return_value = answer
                process.wait.return_value = status
                with redirect_stdout(StringIO()) as output:
                    if status:
                        with self.assertRaisesRegex(AssertionError, "OpenCode failed"):
                            opencode.run(sandbox, "task")
                    else:
                        opencode.run(sandbox, "task")
                self.assertEqual(output.getvalue(), trace + answer)
                sandbox.exec.assert_called_once_with("opencode", "run", "task", timeout=360)
                process.stdin.write_eof.assert_called_once()
                process.stdin.drain.assert_called_once()
