"""Run an off-the-shelf harness inside the locked execution container."""

import json
import os
from pathlib import Path
import sys
from urllib.parse import urlparse

import modal

from s3_sidecar import wait_for


# region: image
image = (modal.Image.debian_slim(python_version="3.13")
    .apt_install("npm", "git", "ripgrep")
    .run_commands("npm install -g @opencode/cli@2.3.0"))
# endregion


# region: config
def config():
    model = os.environ.get("MODEL") or "moonshotai/Kimi-K3.1-Pro"
    return {
        "model": f"proxy/{model}",
        "providers": {"proxy": {
            "package": "@opencode/ai/providers/openai-compatible",
            "settings": {"baseURL": "http://key-proxy:8080/v1"},
            "models": {model: {}},
        }},
    }
# endregion


# region: sandbox
def create_sandbox():
    upstream = os.environ["ENDPOINT_URL"].rstrip("/")
    upstream = upstream.removesuffix("/v1/chat/completions").removesuffix("/v1")
    token = os.environ["MODAL_PROXY_TOKEN"].strip("\"' \n\t")
    app = modal.App.lookup("blog-s4-opencode", create_if_missing=True)
    proxy_image = modal.Image.debian_slim(python_version="3.13").add_local_file(
        Path(__file__).with_name("key_proxy.py"), "/key_proxy.py", copy=True,
    ).build(app)
    sandbox = modal.Sandbox.create(
        app=app, image=image, workdir="/workspace", timeout=600, outbound_cidr_allowlist=[],
    )
    try:
        sandbox._experimental_sidecars.create(
            "python", "/key_proxy.py", name="key-proxy", image=proxy_image,
            env={"UPSTREAM": upstream, "KEY_ENV": "MODAL_PROXY_TOKEN"},
            secrets=[modal.Secret.from_dict({"MODAL_PROXY_TOKEN": token})],
            outbound_domain_allowlist=[urlparse(upstream).hostname],
        )
        wait_for(sandbox, "key-proxy", 8080)
        process = sandbox.exec("python", "-c",
            "from pathlib import Path; import sys; Path('opencode.json').write_text(sys.argv[1])",
            json.dumps(config()), timeout=30)
        assert process.wait() == 0, "could not write OpenCode config"
        return sandbox
    except BaseException:
        sandbox.terminate(wait=True)
        raise
# endregion


# region: run
def run(sandbox, task):
    process = sandbox.exec("opencode", "run", task, timeout=360)
    process.stdin.write_eof()
    process.stdin.drain()
    print(process.stderr.read(), end="", flush=True)
    print(process.stdout.read(), end="", flush=True)
    assert process.wait() == 0, "OpenCode failed"


if __name__ == "__main__":
    if not sys.argv[1:]:
        sys.exit('Usage: s4_opencode.py "task"')
    sandbox = create_sandbox()
    try:
        run(sandbox, " ".join(sys.argv[1:]))
    finally:
        sandbox.terminate(wait=True)
        print("Sandbox and Sidecar stopped")
# endregion
