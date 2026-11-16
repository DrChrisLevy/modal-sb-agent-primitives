"""Keep execution locked down; give a trusted Sidecar the dummy credential."""

from pathlib import Path

import modal

from s1_minimal import main


def wait_for(sandbox, host, port):
    ready = sandbox.exec("python", "-c", '''
import socket, sys, time
for attempt in range(60):
    try:
        with socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=1):
            break
    except OSError:
        time.sleep(0.5)
else:
    raise RuntimeError("key-proxy did not become ready")
''', host, str(port), timeout=100)
    if ready.wait() != 0:
        sandbox.terminate(wait=True)
        raise RuntimeError("key-proxy did not become ready")


# region: sandbox
def create_sandbox():
    app = modal.App.lookup("blog-s3-sidecar", create_if_missing=True)
    image = modal.Image.debian_slim(python_version="3.13").apt_install("git")
    proxy_image = image.add_local_file(
        Path(__file__).with_name("key_proxy.py"), "/key_proxy.py", copy=True,
    ).build(app)
    sandbox = modal.Sandbox.create(
        app=app, image=image, workdir="/workspace", timeout=600,
        outbound_cidr_allowlist=[],
    )
    sandbox._experimental_sidecars.create(
        "python", "/key_proxy.py", name="key-proxy", image=proxy_image,
        env={"UPSTREAM": "https://httpbin.org", "KEY_ENV": "BLOG_DEMO_KEY"},
        secrets=[modal.Secret.from_name("blog-demo-key")],
        outbound_domain_allowlist=["httpbin.org"],
    )
    wait_for(sandbox, "key-proxy", 8080)
    return sandbox
# endregion


if __name__ == "__main__":
    main(create_sandbox=create_sandbox)
