"""Small building blocks for a long-lived coding agent."""

import argparse
from io import BytesIO
import json
import time
import urllib.request

import modal

from s1_minimal import client_and_model, run
from s3_sidecar import wait_for
from s6_snapshots import base_image, sessions

APP_NAME = "blog-s7-building-blocks"
CONVERSATIONS = ("chat-a", "chat-b")


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


# region: named
def get_sandbox(conversation):
    try:
        return modal.Sandbox.from_name(APP_NAME, conversation)
    except modal.exception.NotFoundError:
        store, key = sessions(), "s7/" + conversation
        if key in store:
            previous = modal.Sandbox.from_id(store[key])
            image = previous._experimental_get_exit_snapshot(timeout=180)
        else:
            image = base_image()
        sandbox = modal.Sandbox.create(app=app(), name=conversation, image=image,
            workdir="/workspace", timeout=600,
            experimental_options={"enable_exit_snapshot": True})
        store[key] = sandbox.object_id
        return sandbox
# endregion


# region: history
def histories():
    return modal.Volume.from_name("blog-s7-history", create_if_missing=True, version=2)


def turn(conversation, task):
    sandbox, volume = get_sandbox(conversation), histories()
    path = f"/history/{conversation}.json"
    try:
        messages = json.loads(b"".join(volume.read_file(path)))
    except FileNotFoundError:
        messages = None
    client, model = client_and_model()
    with client:
        messages = run(client, model, sandbox, task, messages=messages)
    with volume.batch_upload(force=True) as batch:
        batch.put_file(BytesIO(json.dumps(messages).encode()), path)
    return messages[-1]["content"]
# endregion


def stop(conversation):
    modal.Sandbox.from_name(APP_NAME, conversation).terminate(wait=True)
    print(f"Stopped {conversation}; its exit snapshot will preserve the workspace", flush=True)


def cleanup():
    for conversation in CONVERSATIONS:
        try:
            modal.Sandbox.from_name(APP_NAME, conversation).terminate(wait=True)
        except modal.exception.NotFoundError:
            pass
        try:
            histories().remove_file(f"/history/{conversation}.json")
        except FileNotFoundError:
            pass
        sessions().pop("s7/" + conversation, None)
    print("PASS: conversation Sandboxes and test histories cleaned up", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    for command in ("server", "cleanup"):
        subcommands.add_parser(command)
    chat = subcommands.add_parser("turn")
    chat.add_argument("conversation", choices=CONVERSATIONS)
    chat.add_argument("task")
    halt = subcommands.add_parser("stop")
    halt.add_argument("conversation", choices=CONVERSATIONS)
    args = parser.parse_args()
    began = time.monotonic()
    if args.command == "turn":
        turn(args.conversation, args.task)
    elif args.command == "stop":
        stop(args.conversation)
    else:
        {"server": server, "cleanup": cleanup}[args.command]()
    print(f"{args.command}: {time.monotonic() - began:.1f}s", flush=True)
