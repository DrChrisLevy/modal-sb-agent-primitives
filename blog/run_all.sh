#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

uv run python blog/sync.py --check
printf '\n=== Step 1: minimal coding agent ===\n'
uv run python blog/steps/s1_minimal.py \
  'Create /workspace/fizzbuzz.py that prints FizzBuzz for numbers 1 through 15 (one line per number). Run it with python, check its output, and report the complete output.'
printf '\n=== Step 2: locked Sandbox network ===\n'
uv run python blog/steps/s2_locked.py \
  'Write /workspace/hello.py to print hello from the locked Sandbox, run it, then try fetching https://example.com with Python urllib and a 5-second timeout. Report the output and what happened to the fetch; network failure is expected.'

printf '\n=== Deterministic network check ===\n'
uv run python - <<'PY'
import sys

sys.path.insert(0, "blog/steps")
from s2_locked import create_sandbox

sandbox = create_sandbox()
try:
    process = sandbox.exec(
        "python", "-c",
        "import urllib.request; urllib.request.urlopen('https://example.com', timeout=5).read(1)",
        timeout=15,
    )
    status = process.wait()
    assert status != 0, "FAIL: locked Sandbox reached example.com"
    print(f"PASS: example.com fetch blocked (exit={status})")
finally:
    status = sandbox.terminate(wait=True)
    print(f"Sandbox stopped: {sandbox.object_id}; exit={status}")
PY

printf '\n=== Step 2: outbound CIDR allowlist ===\n'
uv run python blog/steps/s2_allowlist.py \
  'Fetch https://1.1.1.1/cdn-cgi/trace and https://example.com with urllib, 5s timeout, report each.'

printf '\n=== Step 2: outbound domain allowlist ===\n'
uv run python blog/steps/s2_domain.py \
  'Fetch https://pypi.org, http://pypi.org, https://example.com, and https://1.1.1.1/cdn-cgi/trace with urllib, 5s timeout, report each.'

printf '\n=== Deterministic allowlist and DNS check ===\n'
uv run python - <<'PY'
import sys

sys.path.insert(0, "blog/steps")
from s2_allowlist import create_sandbox as allowlisted
from s2_domain import create_sandbox as domain_allowed
from s2_locked import create_sandbox as locked

for label, factory in [
    ("CIDR", allowlisted),
    ("domain", domain_allowed),
    ("block_network", locked),
]:
    sandbox = factory()
    try:
        dns = sandbox.exec("getent", "hosts", "example.com", timeout=15)
        status = dns.wait()
        print(f"{label}: DNS example.com {'succeeded' if status == 0 else 'failed'} (exit={status})", flush=True)
        if label != "block_network":
            checks = [
                ("https://1.1.1.1/cdn-cgi/trace", label == "CIDR"),
                ("https://example.com", False),
            ]
            if label == "domain":
                checks += [("https://pypi.org", True), ("http://pypi.org", False)]
            for url, allowed in checks:
                process = sandbox.exec(
                    "python", "-c",
                    "import sys,urllib.request; urllib.request.urlopen(sys.argv[1], timeout=5).read(1)",
                    url, timeout=15,
                )
                status = process.wait()
                print(f"{label}: {url} exit={status}", flush=True)
                assert (status == 0) == allowed, f"FAIL: unexpected fetch result for {url}"
    finally:
        status = sandbox.terminate(wait=True)
        print(f"Sandbox stopped: {sandbox.object_id}; exit={status}", flush=True)
print("PASS: separate CIDR and domain policies enforced; DNS observations recorded")
PY
printf '\n=== Sandbox credential: environment Secret ===\n'
uv run modal secret create blog-demo-key BLOG_DEMO_KEY=blog-demo-not-a-real-key --force
uv run python blog/steps/s2_secret.py \
  'Read and print only BLOG_DEMO_KEY from the environment, then use it as a Bearer Authorization header in a urllib request to https://httpbin.org/headers with a 10-second timeout. Report the reflected Authorization header. Do not inspect any other environment variables.'

printf '\n=== Sandbox credential: experimental header injection ===\n'
uv run python blog/steps/s2_injected.py \
  'Check whether BLOG_DEMO_KEY is in the environment, then use urllib to request https://httpbin.org/headers without setting Authorization, with a 10-second timeout. Report the reflected Authorization header. Do not inspect any other environment variables.'

printf '\n=== Deterministic credential check ===\n'
uv run python - <<'PY'
import sys

sys.path.insert(0, "blog/steps")
from s2_secret import create_sandbox as env_secret
from s2_injected import create_sandbox as injected

for label, factory in [("environment", env_secret), ("injection", injected)]:
    sandbox = factory()
    try:
        code = '''import json, os, sys, urllib.request
is_env = sys.argv[1] == "environment"
dummy = "blog-demo-not-a-real-key"
assert os.environ.get("BLOG_DEMO_KEY") == (dummy if is_env else None)
print("PASS: dummy credential " + ("visible in environment" if is_env else "absent from environment"), flush=True)
headers = {"Authorization": "Bearer " + os.environ["BLOG_DEMO_KEY"]} if is_env else {}
request = urllib.request.Request("https://httpbin.org/headers", headers=headers)
with urllib.request.urlopen(request, timeout=10) as response:
    received = {k.lower(): v for k, v in json.load(response)["headers"].items()}
assert received.get("authorization") == "Bearer " + dummy
print("PASS: echo server received dummy Authorization " + ("set by code" if is_env else "injected outside Sandbox"), flush=True)
'''
        process = sandbox.exec("python", "-c", code, label, timeout=30)
        print(process.stdout.read(), end="", flush=True)
        status = process.wait()
        assert status == 0, f"FAIL: {label} credential check (exit={status})"
    finally:
        status = sandbox.terminate(wait=True)
        print(f"Sandbox stopped: {sandbox.object_id}; exit={status}", flush=True)
print("PASS: both credential approaches verified")
PY
printf '\n=== Sidecar: locked execution and trusted key proxy ===\n'
uv run python blog/steps/s3_sidecar.py \
  'Fetch http://key-proxy:8080/headers and https://example.com, and check whether BLOG_DEMO_KEY is set.'

printf '\n=== Deterministic Sidecar check ===\n'
uv run python - <<'PY'
import sys

sys.path.insert(0, "blog/steps")
from s3_sidecar import create_sandbox

sandbox = create_sandbox()
try:
    code = '''import json, os, urllib.error, urllib.request
assert "BLOG_DEMO_KEY" not in os.environ
print("PASS: main has no credential in its environment", flush=True)
try:
    urllib.request.urlopen("https://example.com", timeout=5)
except urllib.error.URLError:
    print("PASS: main cannot reach example.com", flush=True)
else:
    raise AssertionError("main reached example.com")
with urllib.request.urlopen("http://key-proxy:8080/headers", timeout=15) as response:
    headers = {k.lower(): v for k, v in json.load(response)["headers"].items()}
assert headers.get("authorization") == "Bearer blog-demo-not-a-real-key"
print("PASS: proxy adds the fake Authorization header", flush=True)
'''
    process = sandbox.exec("python", "-c", code, timeout=30)
    print(process.stdout.read(), end="", flush=True)
    assert process.wait() == 0, "FAIL: main-container Sidecar checks"
    proxy = sandbox._experimental_sidecars.get(name="key-proxy")
    audit = proxy.exec("cat", "/tmp/key-proxy-audit.log", timeout=15)
    log = audit.stdout.read()
    assert audit.wait() == 0 and "GET /headers" in log, "FAIL: missing proxy audit entry"
    assert "blog-demo-not-a-real-key" not in log, "FAIL: credential in audit log"
    print("Sidecar audit log:", log, sep="\n", end="", flush=True)
    print("PASS: Sidecar audit records the request without the key", flush=True)
finally:
    status = sandbox.terminate(wait=True)
    print(f"Sandbox and Sidecar stopped: {sandbox.object_id}; exit={status}", flush=True)
PY
printf '\n=== OpenCode: harness inside the locked main ===\n'
uv run python - <<'PY'
import sys

sys.path.insert(0, "blog/steps")
from s4_opencode import create_sandbox, run

sandbox = create_sandbox()
try:
    check = sandbox.exec("python", "-c", '''import os, socket, urllib.request, urllib.error
assert not any(k in os.environ for k in ("MODAL_PROXY_TOKEN", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"))
print("PASS: main has no model credential", flush=True)
try:
    urllib.request.urlopen("https://example.com", timeout=5)
except urllib.error.URLError:
    print("PASS: main cannot reach example.com", flush=True)
else:
    raise AssertionError("main reached example.com")
with socket.create_connection(("key-proxy", 8080), timeout=5):
    print("PASS: main can reach proxy", flush=True)
''', timeout=30)
    print(check.stdout.read(), end="", flush=True)
    assert check.wait() == 0, "OpenCode boundary checks failed"
    run(sandbox, "Write hello.py that prints hello from OpenCode, then run it with python.")
    verify = sandbox.exec("python", "hello.py", timeout=30)
    output = verify.stdout.read().strip()
    assert verify.wait() == 0 and output == "hello from OpenCode", "generated program failed"
    proxy = sandbox._experimental_sidecars.get(name="key-proxy")
    audit = proxy.exec("cat", "/tmp/key-proxy-audit.log", timeout=15)
    log = audit.stdout.read()
    assert audit.wait() == 0 and "POST /v1/chat/completions" in log
    print("Sidecar audit:\n" + log, end="", flush=True)
    print("PASS: OpenCode wrote and ran a program; model POSTs used the proxy", flush=True)
finally:
    sandbox.terminate(wait=True)
    print("OpenCode Sandbox and Sidecar stopped", flush=True)
PY
printf '\n=== Trusted main: untrusted tools Sidecar ===\n'
uv run python - <<'PY'
import sys

sys.path.insert(0, "blog/steps")
from s5_tools_sidecar import create_sandbox, run

sandbox, tools = create_sandbox()
try:
    check = tools.exec("python", "-c", '''import os, urllib.request
assert "MODAL_PROXY_TOKEN" not in os.environ
print("PASS: tools Sidecar has no model credential", flush=True)
with urllib.request.urlopen("https://example.com", timeout=15) as response:
    assert response.status == 200
print("PASS: tools Sidecar can reach example.com", flush=True)
''', timeout=30)
    print(check.stdout.read(), end="", flush=True)
    assert check.wait() == 0, "tools boundary checks failed"
    run(sandbox, "Fix add.py so add(a, b) returns their sum. Test it with Python.")
    verify = tools.exec("python", "-c", '''from add import add
assert add(2, 3) == 5
assert add(-2, 1) == -1
assert add(0, 0) == 0
print("PASS: agent fixed add.py in the tools workspace")
''', workdir="/workspace", timeout=30)
    print(verify.stdout.read(), end="", flush=True)
    assert verify.wait() == 0, "agent did not fix add.py"
finally:
    sandbox.terminate(wait=True)
    print("Sandbox and tools Sidecar stopped", flush=True)
PY
printf '\n=== Snapshots ===\n'
uv run python blog/steps/s6_snapshots.py filesystem
uv run python blog/steps/s6_snapshots.py start blog-snapshot-smoke
uv run python blog/steps/s6_snapshots.py resume blog-snapshot-smoke
uv run python blog/steps/s6_snapshots.py sidecar
uv run python blog/steps/s6_snapshots.py memory
printf "\n=== Connect Tokens ===\n"
uv run python blog/steps/s7_building_blocks.py server
printf '\nPASS: all implemented blog steps ran\n'
