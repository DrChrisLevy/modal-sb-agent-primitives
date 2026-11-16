"""Trusted loop in main, untrusted shell commands in a Sidecar."""

import json
import os
from pathlib import Path
import sys
import urllib.request
from urllib.parse import urlparse

import modal

import s1_minimal as loop
from s3_sidecar import wait_for


# region: tool
def tool(sandbox, name, args):
    request = urllib.request.Request("http://tools:8080", method="POST",
        data=json.dumps(args).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=70) as response:
        result = json.load(response)
    return f"exit={result['exit']}\n{result['output']}"[:10_000]


def agent(task):
    loop.TOOLS = [loop.TOOLS[0]]
    loop.tool = tool
    client, model = loop.client_and_model()
    with client:
        loop.run(client, model, None, task)
# endregion


# region: sandbox
def create_sandbox():
    app = modal.App.lookup("blog-s5-tools-sidecar", create_if_missing=True)
    steps = Path(__file__).parent
    base = modal.Image.debian_slim(python_version="3.13")
    tools_image = (base.run_commands("mkdir -p /workspace")
        .add_local_file(steps / "tools_server.py", "/tools_server.py", copy=True).build(app))
    image = base.pip_install("modal", "openai")
    for filename in ("s1_minimal.py", "s3_sidecar.py", "s5_tools_sidecar.py"):
        image = image.add_local_file(steps / filename, "/" + filename, copy=True)
    sandbox = modal.Sandbox.create("sleep", "600", app=app, image=image, timeout=600,
        env={key: os.environ[key] for key in ("ENDPOINT_URL", "MODEL") if key in os.environ},
        secrets=[modal.Secret.from_dict({"MODAL_PROXY_TOKEN": os.environ["MODAL_PROXY_TOKEN"]})],
        outbound_domain_allowlist=[urlparse(os.environ["ENDPOINT_URL"]).hostname])
    try:
        tools = sandbox._experimental_sidecars.create(
            "python", "/tools_server.py", name="tools", image=tools_image)
        wait_for(sandbox, "tools", 8080)
        seed = tools.exec("python", "-c",
            "from pathlib import Path; Path('/workspace/add.py').write_text('def add(a, b):\\n    return a - b\\n')")
        assert seed.wait() == 0, "could not seed tools workspace"
        return sandbox, tools
    except BaseException:
        sandbox.terminate(wait=True)
        raise
# endregion


# region: run
def run(sandbox, task):
    process = sandbox.exec("python", "/s5_tools_sidecar.py", "--agent", task, timeout=360)
    print(process.stdout.read(), end="", flush=True)
    print(process.stderr.read(), end="", flush=True)
    assert process.wait() == 0, "agent failed"


if __name__ == "__main__":
    if sys.argv[1:2] == ["--agent"]:
        agent(sys.argv[2])
    elif sys.argv[1:]:
        sandbox, tools = create_sandbox()
        try:
            run(sandbox, " ".join(sys.argv[1:]))
        finally:
            sandbox.terminate(wait=True)
            print("Sandbox and tools Sidecar stopped")
    else:
        sys.exit('Usage: s5_tools_sidecar.py "task"')
# endregion
