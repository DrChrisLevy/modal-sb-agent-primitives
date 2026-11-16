"""Connect Token example for reaching a server in a Sandbox."""

import argparse
import time
import urllib.request

import modal

from s3_sidecar import wait_for
from s6_snapshots import base_image

APP_NAME = "blog-s7-building-blocks"


def app():
    return modal.App.lookup(APP_NAME, create_if_missing=True)


# region: server
def server():
    sandbox = modal.Sandbox.create("python", "-m", "http.server", "8080",
        app=app(), image=base_image(), workdir="/workspace")
    try:
        wait_for(sandbox, "127.0.0.1", 8080)
        credentials = sandbox.create_connect_token(port=8080)
        request = urllib.request.Request(credentials.url,
            headers={"Authorization": "Bearer " + credentials.token})
        with urllib.request.urlopen(request, timeout=30) as response:
            assert response.status == 200 and b"Directory listing" in response.read()
        print("PASS: app reached the Sandbox server with a Connect Token", flush=True)
    finally:
        sandbox.terminate(wait=True)
# endregion


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["server"])
    args = parser.parse_args()
    began = time.monotonic()
    server()
    print(f"{args.command}: {time.monotonic() - began:.1f}s", flush=True)
