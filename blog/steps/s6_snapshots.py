"""Run filesystem, exit, Sidecar, and memory snapshot examples."""

import argparse
from pathlib import Path
import time

import modal

from s1_minimal import client_and_model, run
from s3_sidecar import wait_for
import s5_tools_sidecar


def execute(container, *command):
    process = container.exec(*command, workdir="/workspace", timeout=180)
    output, error = process.stdout.read(), process.stderr.read()
    assert process.wait() == 0, f"command failed: {error}"
    return output.strip()


def app():
    return modal.App.lookup("blog-s6-snapshots", create_if_missing=True)


# region: sessions
def sessions():
    return modal.Dict.from_name("blog-s6-conversations", create_if_missing=True)
# endregion


def base_image():
    return modal.Image.debian_slim(python_version="3.13").run_commands("mkdir -p /workspace")


# region: filesystem
def filesystem():
    sandbox = modal.Sandbox.create(app=app(), image=base_image(), timeout=300)
    try:
        execute(sandbox, "python", "-m", "pip", "install", "humanize==4.13.0")
        image = sandbox.snapshot_filesystem()
    finally:
        sandbox.terminate(wait=True)
    locked = modal.Sandbox.create(app=app(), image=image, block_network=True)
    try:
        execute(locked, "python", "-c", '''import humanize, urllib.request, urllib.error
assert humanize.intcomma(1234) == "1,234"
try:
    urllib.request.urlopen("https://example.com", timeout=5)
except urllib.error.URLError:
    pass
else:
    raise AssertionError("network was not blocked")
''')
        print("PASS: filesystem snapshot imports installed package with network blocked", flush=True)
    finally:
        locked.terminate(wait=True)
# endregion


# region: exit_start
VERIFY_ADD = "from add import add; assert add(2, 3) == 5; assert add(-2, 1) == -1; assert add(0, 0) == 0"


def start(conversation):
    sandbox = modal.Sandbox.create(
        app=app(), image=base_image(), workdir="/workspace", timeout=600,
        experimental_options={"enable_exit_snapshot": True})
    try:
        sessions()[conversation] = sandbox.object_id
        execute(sandbox, "python", "-c",
            "from pathlib import Path; Path('add.py').write_text('def add(a, b):\\n    return a - b\\n')")
        client, model = client_and_model()
        with client:
            run(client, model, sandbox, "Fix add.py so add(a, b) returns their sum. Test it with Python.")
        execute(sandbox, "python", "-c", VERIFY_ADD)
    finally:
        sandbox.terminate(wait=True)
    print(f"PASS: exit snapshot source fixed add.py and terminated ({conversation})", flush=True)
# endregion


# region: exit_resume
def resume(conversation):
    previous = modal.Sandbox.from_id(sessions()[conversation])
    image = previous._experimental_get_exit_snapshot(timeout=180)
    restored = modal.Sandbox.create(app=app(), image=image, workdir="/workspace")
    try:
        execute(restored, "python", "-c", VERIFY_ADD)
        print(execute(restored, "cat", "add.py"), flush=True)
        print("PASS: exit snapshot restored the fixed add.py in a separate invocation", flush=True)
    finally:
        restored.terminate(wait=True)
# endregion


# region: sidecar
def sidecar():
    sandbox, tools = s5_tools_sidecar.create_sandbox()
    try:
        execute(tools, "python", "-c", "from pathlib import Path; Path('notes.txt').write_text('keep this')")
        image = tools.snapshot_filesystem()
        tools.terminate(wait=True)
        replacement = sandbox._experimental_sidecars.create(
            "python", "/tools_server.py", name="restored-tools", image=image)
        wait_for(sandbox, "restored-tools", 8080)
        assert execute(replacement, "cat", "notes.txt") == "keep this"
        print("PASS: Sidecar filesystem snapshot preserved the tools workspace", flush=True)
    finally:
        sandbox.terminate(wait=True)
# endregion


# region: memory
def memory():
    image = base_image().add_local_file(
        Path(__file__).with_name("counter_server.py"), "/counter_server.py", copy=True)
    sandbox = modal.Sandbox.create("python", "/counter_server.py", app=app(), image=image,
        runtime="vm", _experimental_enable_snapshot=True, timeout=600)
    restored = None
    read_counter = "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080', timeout=5).read().decode())"
    try:
        wait_for(sandbox, "127.0.0.1", 8080)
        assert execute(sandbox, "python", "-c", read_counter) == "1"
        before = int(execute(sandbox, "python", "-c", read_counter))
        snapshot = sandbox._experimental_snapshot()
        restored = modal.Sandbox._experimental_from_snapshot(snapshot)
        wait_for(restored, "127.0.0.1", 8080)
        after = int(execute(restored, "python", "-c", read_counter))
        assert after == before + 1
        print(f"PASS: memory snapshot resumed the in-memory counter: {before} -> {after}", flush=True)
    finally:
        if restored is not None:
            restored.terminate(wait=True)
        sandbox.terminate(wait=True)
# endregion


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("part", choices=("filesystem", "start", "resume", "sidecar", "memory"))
    parser.add_argument("conversation", nargs="?", default="snapshot-demo")
    args = parser.parse_args()
    began = time.monotonic()
    if args.part in ("start", "resume"):
        {"start": start, "resume": resume}[args.part](args.conversation)
    else:
        {"filesystem": filesystem, "sidecar": sidecar, "memory": memory}[args.part]()
    print(f"{args.part}: {time.monotonic() - began:.1f}s", flush=True)
