"""Local, credential-free tests for snippet extraction and synchronization."""

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from sync import render, snippet


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "step.py").write_text("# region: loop\nprint('ok')\n# endregion\n")

    def test_region_whole_file_and_idempotence(self):
        for target in ("step.py#loop", "step.py"):
            post = f"Before\n<!-- snippet: {target} -->\n\n```python\nstale\n```\nAfter\n"
            updated = render(post, self.root)
            self.assertIn("```python\nprint('ok')\n```", updated)
            self.assertNotIn("region:", updated)
            self.assertEqual(render(updated, self.root), updated)

    def test_empty_region(self):
        (self.root / "step.py").write_text("# region: empty\n# endregion\n")
        self.assertEqual(snippet(self.root, "step.py#empty"), "")
        self.assertEqual(render("No snippets\n", self.root), "No snippets\n")

    def test_missing_sources_regions_and_fences(self):
        for target in ("missing.py", "step.py#missing", "../outside.py"):
            with self.subTest(target=target), self.assertRaises((ValueError, OSError)):
                snippet(self.root, target)
        for post in ("<!-- snippet: step.py -->\n", "<!-- snippet: step.py -->\n```python\n"):
            with self.assertRaises(ValueError):
                render(post, self.root)

    def test_malformed_regions(self):
        for source in ("# endregion\n", "# region: loop\n", "# region: x\n# endregion\n# region: x\n# endregion\n"):
            (self.root / "step.py").write_text(source)
            with self.assertRaises(ValueError):
                snippet(self.root, "step.py")

    def test_nested_region_and_unterminated_line(self):
        (self.root / "step.py").write_text("# region: outer\na\n# region: inner\nb\n# endregion\n# endregion\nc")
        self.assertEqual(snippet(self.root, "step.py#outer"), "a\nb\n")
        self.assertEqual(snippet(self.root, "step.py"), "a\nb\nc\n")

    def test_check_and_missing_source_exit_nonzero_without_writing(self):
        script = self.root / "sync.py"
        script.write_text(Path(__file__).with_name("sync.py").read_text())
        post = self.root / "article.md"
        command = [sys.executable, str(script), "--post", str(post)]
        for target in ("step.py#loop", "missing.py", "step.py#absent"):
            content = f"<!-- snippet: {target} -->\n```python\nstale\n```\n"
            post.write_text(content)
            result = subprocess.run([*command, "--check"], capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(post.read_text(), content)
        post.write_text("<!-- snippet: step.py -->\n```python\nold\n```\n")
        result = subprocess.run(command, capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(subprocess.run([*command, "--check"], capture_output=True).returncode, 0)

    def test_default_environment_and_cli_destinations(self):
        script = self.root / "sync.py"
        script.write_text(Path(__file__).with_name("sync.py").read_text())
        env = {**os.environ, "HOME": str(self.root)}
        env.pop("BLOG_POST_PATH", None)
        result = subprocess.run([sys.executable, str(script)], capture_output=True, env=env)
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"BLOG_POST_PATH", result.stderr)
        external = self.root / "site/article.md"
        for mode, post in (("env", external), ("cli", external)):
            with self.subTest(mode=mode):
                post.parent.mkdir(parents=True, exist_ok=True)
                post.write_text("<!-- snippet: step.py#loop -->\n```python\nstale\n```\n")
                env = {**os.environ, "HOME": str(self.root)}
                env.pop("BLOG_POST_PATH", None)
                command = [sys.executable, str(script)]
                if mode == "env":
                    env["BLOG_POST_PATH"] = str(post)
                elif mode == "cli":
                    env["BLOG_POST_PATH"] = str(self.root / "missing.md")
                    command.extend(["--post", str(post)])
                result = subprocess.run(command, capture_output=True, env=env)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("print('ok')", post.read_text())
                result = subprocess.run([*command, "--check"], capture_output=True, env=env)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli_preserves_unmarked_content_and_line_endings(self):
        script = self.root / "sync.py"
        script.write_text(Path(__file__).with_name("sync.py").read_text())
        post = self.root / "article.md"
        prefix = b"---\r\ntitle: Keep me\r\n---\r\n\r\n## Prose\r\n![alt](/image.png)\r\n```bash\r\nkeep this\r\n```\r\n"
        marker = b"<!-- snippet: step.py -->\r\n\r\n```python\r\n"
        suffix = b"```\r\nEnd of prose without a newline"
        post.write_bytes(prefix + marker + b"stale\r\n" + suffix)
        result = subprocess.run([sys.executable, str(script), "--post", str(post)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(post.read_bytes(), prefix + marker + b"print('ok')\n" + suffix)

    def test_missing_destination_exit_nonzero_without_creating_it(self):
        script = self.root / "sync.py"
        script.write_text(Path(__file__).with_name("sync.py").read_text())
        post = self.root / "missing.md"
        for args in ([], ["--check"]):
            result = subprocess.run([sys.executable, str(script), "--post", str(post), *args], capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn(b"ERROR:", result.stderr)
            self.assertFalse(post.exists())


if __name__ == "__main__":
    unittest.main()
