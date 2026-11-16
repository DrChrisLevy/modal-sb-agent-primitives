"""Copy executable sources into Markdown fences; --check never writes."""

import argparse
import os
from pathlib import Path
import re
import sys

MARKER = re.compile(r"^<!-- snippet: ([^\s]+) -->\s*$")
REGION = re.compile(r"^\s*# region: (\S+)\s*$")
END = re.compile(r"^\s*# endregion\s*$")


def snippet(root: Path, target: str) -> str:
    filename, separator, name = target.partition("#")
    path = (root / filename).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"snippet outside blog: {target}")
    lines = path.read_text().splitlines(keepends=True)
    stack, names, selected = [], set(), []
    for line in lines:
        if match := REGION.fullmatch(line):
            region = match[1]
            if region in names:
                raise ValueError(f"duplicate region: {region} in {filename}")
            names.add(region)
            stack.append(region)
        elif END.fullmatch(line):
            if not stack:
                raise ValueError(f"unmatched endregion in {filename}")
            stack.pop()
        elif not separator or name in stack:
            selected.append(line)
    if stack:
        raise ValueError(f"unclosed region in {filename}")
    if separator and name not in names:
        raise ValueError(f"missing region: {target}")
    code = "".join(selected)
    return code + "\n" if code and not code.endswith("\n") else code


def render(post: str, root: Path) -> str:
    lines, result, i = post.splitlines(keepends=True), [], 0
    while i < len(lines):
        line = lines[i]
        result.append(line)
        i += 1
        if not (match := MARKER.fullmatch(line)):
            continue
        target = match[1]
        while i < len(lines) and not lines[i].strip():
            result.append(lines[i])
            i += 1
        if i == len(lines) or not (fence := re.fullmatch(r"(`{3,}|~{3,})[^\n]*\n?", lines[i])):
            raise ValueError(f"missing fenced block after {target}")
        delimiter = fence[1]
        code = snippet(root, target)
        if any(re.fullmatch(re.escape(delimiter[0]) + r"{" + str(len(delimiter)) + r",}\s*", row)
               for row in code.splitlines()):
            raise ValueError(f"use a longer fence for {target}")
        result.extend([lines[i], code])
        i += 1
        while i < len(lines) and not re.fullmatch(re.escape(delimiter[0]) + r"{" + str(len(delimiter)) + r",}\s*", lines[i]):
            i += 1
        if i == len(lines):
            raise ValueError(f"unclosed fenced block after {target}")
        result.append(lines[i])
        i += 1
    return "".join(result)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--post",
        default=os.environ.get("BLOG_POST_PATH"),
        help="Markdown destination (default: BLOG_POST_PATH)",
    )
    args = parser.parse_args()
    if not args.post:
        parser.error("set BLOG_POST_PATH or pass --post /path/to/post.md")
    path = Path(args.post).expanduser()
    try:
        with path.open(encoding="utf-8", newline="") as post:
            original = post.read()
        updated = render(original, Path(__file__).resolve().parent)
        if not args.check and updated != original:
            path.write_text(updated, encoding="utf-8", newline="")
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    if args.check and updated != original:
        print(f"STALE: {path}; run uv run python blog/sync.py --post {str(path)!r}", file=sys.stderr)
        return 1
    print("PASS: snippets in sync" if args.check else f"Synced {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
