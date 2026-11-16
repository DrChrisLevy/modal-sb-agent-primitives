from contextlib import redirect_stdout
from io import StringIO
import json
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
            self.assertEqual(json.loads((root / "outputs/raw/second.json").read_text()), ["real output\n"] * 2)

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
        self.assertEqual(len(lines), 21)
        self.assertEqual(lines[19], "line 19")
        self.assertEqual(lines[-1], "…")
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
                self.assertFalse((root / "outputs/raw/demo.json").exists())

    def test_tool_blocks_and_final_answer_have_separate_limits(self):
        body = "\n".join(f"result {i}" for i in range(10))
        answer = "Final answer.\n\nA second paragraph."
        raw = f"Sandbox: example\nbash: exit=0\n{body}\n\n{answer}\nSandbox stopped: example\nPASS: done\nserver: 1.2s\n"
        text = recorder.clean_output(raw, {})
        self.assertIn("bash: exit=0\n" + "\n".join(f"result {i}" for i in range(6)) + "\n…\n", text)
        self.assertIn(answer, text)
        for line in ("Sandbox: example", "Sandbox stopped: example", "PASS: done", "server: 1.2s"):
            self.assertIn(line, text.splitlines())
        self.assertNotIn("result 6", text)

    def test_budget_shrinks_tools_not_short_final_answer(self):
        body = "\n".join(f"result {i}" for i in range(12))
        answer = "\n".join(f"Answer line {i}" for i in range(19))
        raw = f"Sandbox: example\nread_file: exit=0\n{body}\n\nbash: exit=0\n{body}\n\n{answer}\nSandbox stopped: example\n"
        text = recorder.clean_output(raw, {})
        self.assertIn(answer, text)
        self.assertLessEqual(len(text.splitlines()), 30)
        self.assertEqual(text.count("…"), 2)

    def test_truncated_traceback_does_not_swallow_answer_or_emit_partial_line(self):
        frames = "\n".join(f'  File "/usr/local/file.py", line {i}' for i in range(15))
        raw = f"bash: exit=1\nTraceback (most recent call last):\n{frames}\n        (self.\nFetched the proxy successfully.\n\nThe network request failed.\nSandbox and Sidecar stopped\n"
        text = recorder.clean_output(raw, {})
        self.assertIn("Fetched the proxy successfully.\n\nThe network request failed.", text)
        self.assertNotIn("(self.", text)
        self.assertIn("…\n", text)

    def test_opencode_buffered_answer_and_command_output(self):
        answer = "Created fizzbuzz.py.\n\n```text\n1\n2\n```"
        raw = answer + "\n> build · model\n← Write fizzbuzz.py\nCreated file successfully\n> build · model\n$ python fizzbuzz.py\n" + "\n".join(map(str, range(15))) + "\n> build · model\nSandbox and Sidecar stopped\n"
        text = recorder.clean_output(raw, {})
        self.assertIn(answer, text)
        self.assertIn("$ python fizzbuzz.py\n0\n1\n2\n3\n4\n5\n…", text)
        self.assertNotIn("> build", text)

    def test_verbose_answer_abbreviates_fenced_data_before_losing_conclusions(self):
        answer = "Allowed URL: 200 OK\n\n```text\n" + "\n".join(f"metadata {i}" for i in range(25)) + "\n```\n\nBlocked URL: Network is unreachable\n"
        text = recorder.clean_output(answer, {})
        self.assertLessEqual(len(text.splitlines()), 20)
        self.assertIn("…\n```\n\nBlocked URL: Network is unreachable", text)
        self.assertTrue(text.startswith("Allowed URL: 200 OK\n"))

    def test_retrim_cli_is_offline_and_checks_raws(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "blog"
            (root / "outputs/raw").mkdir(parents=True)
            post = root / "post.md"
            post.write_text(example("demo", "uv run python blog/steps/one.py"))
            raw = root / "outputs/raw/demo.json"
            raw.write_text(json.dumps(["bash: exit=0\nhello\n\nDone.\n"]))
            environment = {"ENDPOINT_URL": "https://private.example", "MODAL_PROXY_TOKEN": "test-secret-token"}
            with patch.object(recorder, "__file__", str(root / "record.py")), patch.dict(recorder.os.environ, environment), patch.object(recorder.sys, "argv", ["record.py", "--post", str(post), "--retrim", "--only", "demo"]), patch.object(recorder.subprocess, "run") as run, redirect_stdout(StringIO()):
                self.assertEqual(recorder.main(), 0)
                run.assert_not_called()
            output = root / "outputs/demo.txt"
            self.assertEqual(output.read_text(), "bash: exit=0\nhello\n\nDone.\n")
            for invalid in ("not json", '{}', '["/home/user/private"]'):
                raw.write_text(invalid)
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    recorder.retrim(post.read_text(), root)
                self.assertEqual(output.read_text(), "bash: exit=0\nhello\n\nDone.\n")
            raw.write_text('[""]')
            with redirect_stdout(StringIO()):
                recorder.retrim(post.read_text(), root)
            self.assertEqual(output.read_text(), "")
            raw.unlink()
            with self.assertRaises(OSError):
                recorder.retrim(post.read_text(), root)

    def test_bare_secret_prerequisite(self):
        post = "```bash\nmodal secret create demo KEY=fake --force\n```\n"
        self.assertEqual(recorder.recording_plan(post), [(None, [["modal", "secret", "create", "demo", "KEY=fake", "--force"]])])
