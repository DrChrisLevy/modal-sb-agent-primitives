"""Outside loop, inside tools. Run with a task argument; source env.sh first."""

# region: setup
import json
import os
import sys

import modal
from openai import OpenAI


def client_and_model():
    base = os.environ["ENDPOINT_URL"].rstrip("/")
    base = base.removesuffix("/v1/chat/completions").removesuffix("/v1")
    token = os.environ["MODAL_PROXY_TOKEN"].strip("\"' \n\t")
    client = OpenAI(base_url=base + "/v1", api_key=token, timeout=180, max_retries=1)
    model = os.environ.get("MODEL") or client.models.list().data[0].id
    return client, model
# endregion


# region: sandbox
def create_sandbox():
    app = modal.App.lookup("blog-s1-minimal", create_if_missing=True)
    image = modal.Image.debian_slim(python_version="3.13").apt_install("git")
    return modal.Sandbox.create(
        app=app, image=image, workdir="/workspace", timeout=600,
    )
# endregion


# region: tools
def tool(sandbox, name, args):
    if name == "bash": 
        command = ["bash", "-lc", args["command"]]
    elif name == "read_file":
        command = ["python", "-c", "import pathlib,sys; print(pathlib.Path(sys.argv[1]).read_text())", args["path"]]
    elif name == "write_file":
        code = "import pathlib,sys; p=pathlib.Path(sys.argv[1]); p.parent.mkdir(parents=True,exist_ok=True); print(p.write_text(sys.argv[2]))"
        command = ["python", "-c", code, args["path"], args["content"]]
    else:
        raise ValueError("unknown tool")
    process = sandbox.exec(*command, timeout=60, workdir="/workspace")
    stdout, stderr = process.stdout.read(), process.stderr.read()
    return f"exit={process.wait()}\n{stdout}{stderr}"[:10_000]
# endregion


# region: schemas
def schema(name, description, *fields):
    return {"type": "function", "function": {
        "name": name, "description": description, "parameters": {
            "type": "object", "properties": {key: {"type": "string"} for key in fields},
            "required": list(fields), "additionalProperties": False,
        },
    }}


TOOLS = [
    schema("bash", "Run a shell command in /workspace; return exit code and output.", "command"),
    schema("read_file", "Read a text file in the Sandbox.", "path"),
    schema("write_file", "Write a text file in the Sandbox, creating parent directories.", "path", "content"),
]
# endregion


# region: loop
MAX_STEPS = 50


def run(client, model, sandbox, task, messages=None):
    if messages is None:
        messages = [
            {"role": "system", "content": "You are a coding agent. Use tools in /workspace. Verify your work by running it; fix errors before replying. Be concise."},
        ]
    messages.append({"role": "user", "content": task})
    for _ in range(MAX_STEPS):
        response = client.chat.completions.create(
            model=model, messages=messages, tools=TOOLS, reasoning_effort="low",
        )
        message = response.choices[0].message
        messages.append(message.model_dump(exclude_none=True))
        if not message.tool_calls:
            if not message.content or not message.content.strip():
                raise RuntimeError("model returned no answer or tools")
            print(message.content)
            return messages
        for call in message.tool_calls:
            try:
                result = tool(sandbox, call.function.name, json.loads(call.function.arguments))
            except Exception as error:
                result = f"tool error: {type(error).__name__}"
            print(f"{call.function.name}: {result[:1500]}", flush=True)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
    raise RuntimeError(f"agent reached the {MAX_STEPS}-step limit")
# endregion


# region: main
def _main(create_sandbox):
    if not sys.argv[1:]:
        sys.exit('Usage: uv run python blog/steps/s1_minimal.py "task"')
    client, model = client_and_model()
    with client:
        sandbox = create_sandbox()
        print(f"Sandbox: {sandbox.object_id}", flush=True)
        try:
            run(client, model, sandbox, " ".join(sys.argv[1:]))
        finally:
            status = sandbox.terminate(wait=True)
            print(f"Sandbox stopped: {sandbox.object_id}; exit={status}", flush=True)


def main(create_sandbox=create_sandbox):
    try:
        _main(create_sandbox)
    except Exception as error:
        sys.exit(f"Failed: {type(error).__name__} (check configuration and service availability)")


if __name__ == "__main__":
    main()
# endregion
