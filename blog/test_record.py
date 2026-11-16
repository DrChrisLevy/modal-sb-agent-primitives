from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import record as recorder


def example(name, commands):
    return f"```bash\n{commands}\n```\n\nExample output:\n\n<!-- output: {name} -->\n```text\n\n```\n"


class RecordTests(unittest.TestCase):
    def test_plan_order_prerequisites_and_nested_fences(self):
        setup = "```bash\nuv run modal secret create demo KEY=fake --force\n```\n"
        post = "```bash\nmodal endpoint create --shared --model example\n```\n"
        post += example("first", 'uv run python blog/steps/one.py "a task"') + setup
        post += example("second", "uv run python blog/steps/two.py start\nuv run python blog/steps/two.py resume")
        post += "````text\n```bash\nnot a command\n```\n````\n"
        plan = recorder.recording_plan(post)
        self.assertEqual([name for name, _ in plan], ["first", None, "second"])
        self.assertEqual(plan[0][1][0][-1], "a task")
        with TemporaryDirectory() as temp:
            root = Path(temp) / "blog"
            root.mkdir()
            with patch.object(recorder.subprocess, "run", return_value=Mock(returncode=0, stdout="real output\n")) as run, redirect_stdout(StringIO()):
                recorder.record(post, root, only="second")
            self.assertEqual(len(run.call_args_list), 3)
            self.assertEqual(run.call_args_list[0].args[0][:5], ["uv", "run", "modal", "secret", "create"])
            self.assertEqual([call.args[0][-1] for call in run.call_args_list[1:]], ["start", "resume"])
            self.assertEqual(run.call_args.kwargs["cwd"], root.parent)
            self.assertEqual(run.call_args.kwargs["stderr"], recorder.subprocess.STDOUT)
            self.assertFalse((root / "outputs/first.txt").exists())
            self.assertEqual((root / "outputs/second.txt").read_text(), "real output\n\nreal output\n")

    def test_empty_unknown_and_invalid_plans(self):
        self.assertEqual(recorder.recording_plan("No commands\n"), [])
        for post in ("```bash\nuv run python blog/steps/one.py\n```\n",
                     example("../outside", "uv run python blog/steps/one.py"),
                     example("demo", "echo unexpected"),
                     example("demo", "uv run python blog/steps/one.py") * 2,
                     "```bash\nmissing closing fence"):
            with self.subTest(post=post), self.assertRaises(ValueError):
                recorder.recording_plan(post)
        with self.assertRaises(ValueError):
            recorder.record("", Path("blog"), only="missing")

    def test_cleanup_noise_ansi_and_truncation(self):
        raw = "\x1b[32mhello\x1b[0m\n⠋ Working\r\nView app: https://modal.com/apps/example\n\nworld\n"
        self.assertEqual(recorder.clean_output(raw, {}), "hello\n\nworld\n")
        raw = "\n".join(f"line {i}" for i in range(80))
        lines = recorder.clean_output(raw, {}).splitlines()
        self.assertEqual(len(lines), 40)
        self.assertEqual(lines[19], "…")
        self.assertEqual(lines[-1], "line 79")
        self.assertEqual(recorder.clean_output("", {}), "")

    def test_sensitive_data_rejected_even_in_noise_or_truncated_middle(self):
        env = {"ENDPOINT_URL": "https://private.example/v1", "MODAL_PROXY_TOKEN": "test-secret-token"}
        for secret in ("PRIVATE.EXAMPLE", "test-secret-token", "/home/someone/file", "file:///home/someone/file", "/Users/someone/file", "/root/file", "C:\\Users\\someone\\file", "~/file"):
            raw = "\n".join(["safe"] * 100 + [secret] + ["safe"] * 100)
            with self.subTest(secret=secret), self.assertRaises(ValueError) as error:
                recorder.clean_output(raw, env)
            self.assertNotIn(secret, str(error.exception))

    def test_failed_or_sensitive_command_writes_no_output(self):
        post = example("demo", "uv run python blog/steps/one.py")
        for result in (Mock(returncode=1, stdout="failure\n"), Mock(returncode=0, stdout="/home/user/private\n")):
            with self.subTest(result=result), TemporaryDirectory() as temp:
                root = Path(temp) / "blog"
                root.mkdir()
                with patch.object(recorder.subprocess, "run", return_value=result), self.assertRaises(ValueError):
                    recorder.record(post, root)
                self.assertFalse((root / "outputs/demo.txt").exists())

    def test_bare_secret_prerequisite(self):
        post = "```bash\nmodal secret create demo KEY=fake --force\n```\n"
        self.assertEqual(recorder.recording_plan(post), [(None, [["modal", "secret", "create", "demo", "KEY=fake", "--force"]])])
