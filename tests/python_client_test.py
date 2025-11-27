"""
Minimal MCP stdio client to sanity-check the Python server.
Workflow:
 1) spawn `uv run server.py`
 2) send initialize
 3) list tools
 4) call ping
If all succeed, prints OK and exits with code 0.
Run with: uv run tests/python_client_test.py
"""

import json
import subprocess
import sys
import time
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def send(proc, obj):
    line = json.dumps(obj, separators=(",", ":"))
    proc.stdin.write((line + "\n").encode("utf-8"))
    proc.stdin.flush()


def recv(proc, timeout=5.0):
    proc.stdout.flush()
    start = time.time()
    while True:
        if time.time() - start > timeout:
            raise TimeoutError("timeout waiting for response")
        line = proc.stdout.readline()
        if not line:
            continue
        return json.loads(line.decode("utf-8"))


def main():
    env = dict(**os.environ)
    proc = subprocess.Popen(
        ["uv", "run", "server.py"],
        cwd=str(ROOT),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    init = {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "0.0.0"},
        },
    }
    send(proc, init)
    resp = recv(proc)
    assert resp.get("id") == 0 and "result" in resp, f"init failed: {resp}"

    send(
        proc,
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )
    resp = recv(proc)
    assert resp.get("id") == 1 and "result" in resp, f"list failed: {resp}"
    tools = resp["result"].get("tools", [])
    assert any(t.get("name") == "ping" for t in tools), "ping tool missing"

    send(
        proc,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "ping", "arguments": {"prompt": "hello"}},
        },
    )
    resp = recv(proc)
    assert resp.get("id") == 2 and "result" in resp, f"call failed: {resp}"
    assert "hello" in resp["result"]["content"][0]["text"]

    proc.kill()
    print("[OK] python MCP stdio handshake passed")


if __name__ == "__main__":
    main()
