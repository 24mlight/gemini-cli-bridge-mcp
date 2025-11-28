"""
Profile MCP latency segments:
- server startup (process launch -> initialize response)
- ping (baseline RPC)
- ask_gemini tool call

Run: uv run scripts/profile_latency.py
"""

import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PROMPT = os.getenv(
    "PROFILE_PROMPT",
    "ask gemini what is the latest model from deepseek and must not use web search",
)


def send(proc, obj):
    proc.stdin.write(json.dumps(obj) + "\n")
    proc.stdin.flush()


def recv(proc, timeout=120):
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
            # skip log/diagnostic lines
            continue


def main():
    t0 = time.perf_counter()
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
                "clientInfo": {"name": "latency-profiler", "version": "0.0.1"},
            },
        },
    )
    print("waiting for initialize...", flush=True)
    init_resp = recv(proc, 15)
    print("initialized.", flush=True)
    t_init = time.perf_counter()

    send(
        proc,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "ping", "arguments": {"prompt": "warmup"}},
        },
    )
    print("waiting for ping...", flush=True)
    ping_resp = recv(proc, 10)
    print("ping ok.", flush=True)
    t_ping = time.perf_counter()

    send(
        proc,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "ask_gemini", "arguments": {"prompt": PROMPT}},
        },
    )
    print("waiting for ask_gemini...", flush=True)
    ask_resp = recv(proc, 240)
    print("ask_gemini returned.", flush=True)
    t_ask = time.perf_counter()

    try:
        proc.kill()
    finally:
        try:
            proc.wait(timeout=2)
        except Exception:
            pass
    stderr = ""

    print("=== Latency Report ===")
    print(f"Server start -> initialize: {(t_init - t0):.2f}s (init ok={init_resp.get('id') == 0})")
    print(f"Initialize -> ping: {(t_ping - t_init):.2f}s (ping ok={ping_resp.get('id') == 1})")
    print(f"Ping -> ask_gemini: {(t_ask - t_ping):.2f}s")
    print(f"Total: {(t_ask - t0):.2f}s")
    if stderr.strip():
        print("\n[stderr]\n" + stderr.strip())
    print("\nask_gemini result (truncated):\n", str(ask_resp)[:500])


if __name__ == "__main__":
    main()
