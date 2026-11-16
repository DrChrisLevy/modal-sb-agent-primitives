"""Record the post's output-marked examples in order, without publishing secrets."""

import argparse
import json
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


def normalized_output(raw, environment):
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
    return "\n".join(lines) + ("\n" if lines else "")


TOOL = re.compile(r"^[\w.-]+: exit=-?\d+$")
STATUS = re.compile(r"^(?:Sandbox(?::| stopped| and .+ stopped)|PASS:|[\w-]+: \d+(?:\.\d+)?s$)")


def sections(text):
    result, body, kind, header = [], [], "answer", ""

    def flush():
        nonlocal body
        while body and not body[-1]:
            body.pop()
        while body and not body[0]:
            body.pop(0)
        if kind == "agent":
            traceback = any(line.startswith("Traceback (") for line in body)
            boundary = len(body)
            for i, line in enumerate(body):
                if not i or not line or line[0].isspace():
                    continue
                prose = re.match(r"(?:[-*] |#{1,6} |\*\*|[A-Za-z].*[ .`])", line)
                diagnostic = re.match(r"(?:===|URL:|Status:|Final URL:|HTTP |\w*(?:Error|Exception):|During handling|The above exception|Traceback)", line)
                if prose and not diagnostic and (not body[i - 1] or traceback):
                    boundary = i
                    break
            result.append(("tool", header, body[:boundary]))
            if boundary < len(body):
                result.append(("answer", "", body[boundary:]))
        elif header or body:
            result.append((kind, header, body))
        body = []

    for line in text.splitlines():
        if STATUS.match(line):
            flush()
            result.append(("status", "", [line]))
            kind, header = "answer", ""
        elif TOOL.fullmatch(line) or line.startswith(("$ ", "← ", "→ ")):
            flush()
            kind, header = ("agent" if TOOL.fullmatch(line) else "tool"), line
        elif line.startswith("> build ·"):
            flush()
            kind, header = "answer", ""
        else:
            body.append(line)
    flush()
    return [(kind, header, list(trim_blank_edges(body))) for kind, header, body in result]


def trim_blank_edges(lines):
    start, end = 0, len(lines)
    while start < end and not lines[start]:
        start += 1
    while end > start and not lines[end - 1]:
        end -= 1
    return lines[start:end]


def trim_output(text):
    parts = [(kind, header, compact_answer(body) if kind == "answer" else body)
             for kind, header, body in sections(text)]
    limits = [min(6 if kind == "tool" else 20, len(body)) for kind, _, body in parts]

    def render():
        lines = []
        for (kind, header, body), limit in zip(parts, limits):
            if kind == "answer" and lines and lines[-1]:
                lines.append("")
            if header:
                lines.append(header)
            lines.extend(body if kind == "status" else body[:limit])
            if kind != "status" and len(body) > limit:
                lines.append("…")
        return lines

    while len(render()) > 30:
        candidates = [i for i, (kind, _, _) in enumerate(parts) if kind == "tool" and limits[i] > 1]
        if not candidates:
            break
        limits[max(candidates, key=lambda i: limits[i])] -= 1
    lines = render()
    return "\n".join(lines) + ("\n" if lines else "")


def compact_answer(lines):
    lines = list(lines)
    while len(lines) > 20:
        blocks, i = [], 0
        while i < len(lines):
            fence = re.fullmatch(r"\s*(`{3,}|~{3,})[^`~]*", lines[i])
            i += 1
            if not fence:
                continue
            start = i
            while i < len(lines) and not re.fullmatch(r"\s*" + re.escape(fence[1][0]) + r"{" + str(len(fence[1])) + r",}\s*", lines[i]):
                i += 1
            if i < len(lines):
                body = lines[start:i]
                kept = body[:-1] if body and body[-1] == "…" else body
                if len(kept) > 1:
                    blocks.append((start, i, kept))
                i += 1
        if not blocks:
            break
        start, end, kept = max(blocks, key=lambda block: len(block[2]))
        lines[start:end] = kept[:-1] + ["…"]
    return lines


def clean_output(raw, environment):
    return trim_output(normalized_output(raw, environment))


def sample_output(captures, environment):
    samples = [clean_output(capture, environment).rstrip("\n") for capture in captures]
    text = "\n\n".join(sample for sample in samples if sample)
    return text + "\n" if text else ""


def retrim(post, root, only=None):
    names = [name for name, _ in recording_plan(post) if name]
    if only and only not in names:
        raise ValueError("unknown --only output name")
    for name in names:
        if only and name != only:
            continue
        path = output_path(root, name)
        captures = json.loads((path.parent / "raw" / f"{name}.json").read_text(encoding="utf-8"))
        if not isinstance(captures, list) or not captures or not all(isinstance(capture, str) for capture in captures):
            raise ValueError("invalid raw capture")
        text = sample_output(captures, os.environ)
        path.write_text(text, encoding="utf-8")
        print(f"Retrimmed {name}: {len(text.splitlines())} lines", flush=True)


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
            text = sample_output(combined, environment)
            path = output_path(root, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = path.parent / "raw" / f"{name}.json"
            raw.parent.mkdir(exist_ok=True)
            raw.write_text(json.dumps(combined, ensure_ascii=False) + "\n", encoding="utf-8")
            path.write_text(text, encoding="utf-8")
            print(f"Recorded {name}: {len(text.splitlines())} lines", flush=True)
            if only:
                break


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--post", default=os.environ.get("BLOG_POST_PATH"))
    parser.add_argument("--only", metavar="NAME")
    parser.add_argument("--retrim", action="store_true", help="regenerate samples from ignored raw captures without running commands")
    args = parser.parse_args()
    if not args.post:
        parser.error("set BLOG_POST_PATH or pass --post")
    if not os.environ.get("ENDPOINT_URL") or not os.environ.get("MODAL_PROXY_TOKEN"):
        parser.error("source env.sh before recording")
    try:
        operation = retrim if args.retrim else record
        operation(Path(args.post).expanduser().read_text(encoding="utf-8"), Path(__file__).resolve().parent, args.only)
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"ERROR: recording failed ({type(error).__name__}); no raw output published", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
