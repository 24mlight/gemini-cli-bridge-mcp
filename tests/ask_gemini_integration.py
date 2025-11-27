"""
Integration test: call ask_gemini via MCP stdio and print the response.
Usage: uv run tests/ask_gemini_integration.py
Note: requires Gemini CLI available (or npx fallback will attempt install).
"""

import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PROMPT = "ask gemini what is the latest model from deepseek and must not use web search"


def send(proc, obj):
    proc.stdin.write(json.dumps(obj) + "\n")
    proc.stdin.flush()


def recv(proc, timeout=60):
    start = time.time()
    while True:
        if time.time() - start > timeout:
            raise TimeoutError("timeout waiting for response")
        line = proc.stdout.readline()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            # skip log lines
            continue


def main():
    proc = subprocess.Popen(
        ["uv", "--directory", str(ROOT), "run", "python", "server.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    send(
        proc,
        {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "integration-test", "version": "0.0.0"},
            },
        },
    )
    print("init:", recv(proc, 10))

    send(
        proc,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "ask_gemini", "arguments": {"prompt": PROMPT}},
        },
    )
    resp = recv(proc, 120)  # allow some time for CLI call
    print("ask_gemini response:")
    print(json.dumps(resp, indent=2))

    proc.kill()


if __name__ == "__main__":
    main()
