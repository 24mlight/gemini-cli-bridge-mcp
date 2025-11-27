"""
Python MCP server wrapper for the Gemini CLI.
Run with: uv run server.py
"""
from __future__ import annotations

import shutil
import subprocess
from typing import Optional

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("gemini-cli-mcp-python")


def _ensure_gemini() -> str:
    path = shutil.which("gemini")
    if not path:
        raise RuntimeError(
            "gemini CLI not found in PATH. Install the Google Gemini CLI and ensure 'gemini' is available."
        )
    return path


@mcp.tool()
def ping(message: str = "pong") -> str:
    """Simple connectivity check."""
    return message


@mcp.tool()
def help() -> str:
    """Return `gemini -help` output."""
    gemini = _ensure_gemini()
    result = subprocess.run(
        [gemini, "-help"],
        text=True,
        capture_output=True,
        check=False,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "gemini -help failed")
    return result.stdout.strip()


@mcp.tool()
def ask_gemini(prompt: str, model: Optional[str] = None, sandbox: bool = False) -> str:
    """Call local Gemini CLI with a prompt."""
    gemini = _ensure_gemini()
    args = [gemini]
    if model:
        args += ["-m", model]
    if sandbox:
        args.append("-s")
    args += ["-p", prompt]

    result = subprocess.run(
        args,
        text=True,
        capture_output=True,
        check=False,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"gemini exited {result.returncode}")
    return result.stdout.strip()


if __name__ == "__main__":
    mcp.run()
