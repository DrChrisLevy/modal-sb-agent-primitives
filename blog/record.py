"""Record the post's output-marked examples in order, without publishing secrets."""

import argparse
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from urllib.parse import urlsplit

from sync import output_path

ANSI = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]")
HOME = re.compile(r"/home/|/Users/|/root(?:/|\b)|[A-Za-z]:[\\/]Users[\\/]|~/")
OUTPUT = re.compile(r"\s*(?:Example output:\s*)?<!-- output: ([^\s]+) -->")


def bash_blocks(post):
    lines = post.splitlines(keepends=True)
    i = 0
    while i < len(lines):
        opening = re.fullmatch(r"(`{3,}|~{3,})([^\n]*)\n?", lines[i])
        i += 1
        if not opening:
            continue
        delimiter, language = opening[1], opening[2].strip()
        content = []
        while i < len(lines) and not re.fullmatch(re.escape(delimiter[0]) + r"{" + str(len(delimiter)) + r",}\s*", lines[i]):
            content.append(lines[i])
            i += 1
        if i == len(lines):
            raise ValueError("unclosed Markdown fence")
        i += 1
        if language == "bash":
            marker = OUTPUT.match("".join(lines[i:]))
            yield "".join(content), marker[1] if marker else None


def recording_plan(post):
    plan, names = [], set()
    for block, name in bash_blocks(post):
        commands = [shlex.split(line) for line in block.replace("\\\n", " ").splitlines()
                    if line.strip() and not line.lstrip().startswith("#")]
        examples = [command for command in commands
                    if len(command) >= 4 and command[:3] == ["uv", "run", "python"] and command[3].startswith("blog/")]
        if examples:
            if not name or len(examples) != len(commands):
                raise ValueError("each example bash block needs one output marker and only example commands")
            if name in names:
                raise ValueError("duplicate output name")
            output_path(Path(__file__).resolve().parent, name)
            names.add(name)
            plan.append((name, commands))
        elif name:
            raise ValueError("output marker is not attached to an example")
        elif commands and all((command[2:] if command[:2] == ["uv", "run"] else command)[:3]
                              == ["modal", "secret", "create"] for command in commands):
            plan.append((None, commands))
    return plan


def clean_output(raw, environment):
    text = ANSI.sub("", raw)
    host = urlsplit(environment.get("ENDPOINT_URL", "").strip("\"' \n\t")).hostname
    token = environment.get("MODAL_PROXY_TOKEN", "").strip("\"' \n\t")
    if host and host.lower() in text.lower():
        raise ValueError("unsafe output: endpoint host detected; nothing saved")
    if token and token in text:
        raise ValueError("unsafe output: model token detected; nothing saved")
    if HOME.search(text):
        raise ValueError("unsafe output: home path detected; nothing saved")
    lines = []
    for line in text.replace("\r", "\n").splitlines():
        line = line.rstrip()
        if re.search(r"https://modal\.com/(?:apps|logs|runs|sandboxes)/", line):
            continue
        if re.match(r"^\s*[\u2800-\u28ff]", line) or re.fullmatch(r"[\s─━│└├┌┐┘┤┬┴┼]+", line):
            continue
        if line or (lines and lines[-1]):
            lines.append(line)
    while lines and not lines[-1]:
        lines.pop()
    if len(lines) > 40:
        lines = lines[:19] + ["…"] + lines[-20:]
    return "\n".join(lines) + ("\n" if lines else "")


def record(post, root, only=None):
    plan = recording_plan(post)
    if only and only not in {name for name, _ in plan}:
        raise ValueError("unknown --only output name")
    environment = {**os.environ, "NO_COLOR": "1", "TERM": "dumb", "PYTHONUNBUFFERED": "1"}
    for name, commands in plan:
        if name and only and name != only:
            continue
        combined = []
        for command in commands:
            result = subprocess.run(command, cwd=root.parent, env=environment, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", timeout=900)
            clean_output(result.stdout, environment)
            combined.append(result.stdout)
            if result.returncode:
                raise ValueError(f"{name or 'prerequisite'} failed (exit {result.returncode}):\n"
                                 + clean_output(result.stdout, environment))
        if name:
            text = clean_output("\n".join(combined), environment)
            path = output_path(root, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            print(f"Recorded {name}: {len(text.splitlines())} lines", flush=True)
            if only:
                break


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--post", default=os.environ.get("BLOG_POST_PATH"))
    parser.add_argument("--only", metavar="NAME")
    args = parser.parse_args()
    if not args.post:
        parser.error("set BLOG_POST_PATH or pass --post")
    if not os.environ.get("ENDPOINT_URL") or not os.environ.get("MODAL_PROXY_TOKEN"):
        parser.error("source env.sh before recording")
    try:
        record(Path(args.post).expanduser().read_text(encoding="utf-8"), Path(__file__).resolve().parent, args.only)
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"ERROR: recording failed ({type(error).__name__}); no raw output published", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
