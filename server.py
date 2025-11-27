"""
Gemini CLI MCP server (Python)
- mirrors existing Node tool set: ask-gemini, brainstorm, fetch-chunk, ping, help, timeout-test
- CLI lookup: explicit env (GEMINI_BIN) -> local node_modules/.bin -> PATH -> common roaming dirs -> npx fallbacks
"""

import asyncio
import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

from mcp.server.fastmcp import FastMCP


DEFAULT_MODEL = os.getenv("GEMINI_DEFAULT_MODEL", "gemini-3-pro-preview")
FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-2.5-pro")
FLASH_MODEL = os.getenv("GEMINI_FLASH_MODEL", "gemini-2.5-flash")
CLI_QUOTA_MSG = "Quota exceeded for quota metric"

CACHE_DIR = Path(tempfile.gettempdir()) / "gemini-mcp-py-chunks"
CACHE_TTL = int(os.getenv("GEMINI_CACHE_TTL_MS", str(10 * 60 * 1000)))  # 10 min
CHUNK_SIZE = 5  # edits per chunk


def _now_ms() -> int:
    return int(time.time() * 1000)


def _log(msg: str):
    print(f"[GMCPT/PY] {msg}", flush=True)


def _find_cli_candidates() -> List[List[str]]:
    candidates: List[List[str]] = []

    explicit = os.getenv("GEMINI_BIN")
    if explicit:
        candidates.append([explicit])

    cwd = Path.cwd()
    local = cwd / "node_modules" / ".bin" / ("gemini.cmd" if os.name == "nt" else "gemini")
    if local.exists():
        candidates.append([str(local)])

    # PATH search
    exe_names = ["gemini.cmd", "gemini.exe", "gemini.bat", "gemini"]
    for p in os.environ.get("PATH", "").split(os.pathsep):
        for name in exe_names:
            cand = Path(p) / name
            if cand.exists():
                candidates.append([str(cand)])

    # common roaming dirs / cygwin style
    userprofile = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if userprofile:
        roaming = Path(userprofile) / "AppData" / "Roaming" / "npm"
        for name in exe_names:
            cand = roaming / name
            if cand.exists():
                candidates.append([str(cand)])
        # cygwin style
        if str(userprofile).startswith("/cygdrive/"):
            cyg = Path(userprofile) / "AppData" / "Roaming" / "npm" / "gemini"
            if cyg.exists():
                candidates.append([str(cyg)])

    # npx fallbacks (auto install if needed)
    candidates.append(["npx", "-y", "gemini"])
    candidates.append(["npx", "-y", "@google/gemini-cli"])
    candidates.append(["npx", "-y", "@google/generative-ai-cli"])
    return candidates


async def _run_cli(prompt: str, model: str, sandbox: bool, on_progress=None) -> str:
    args = []
    if model:
        args += ["-m", model]
    if sandbox:
        args.append("-s")
    args += ["-p", prompt if prompt.startswith('"') else f'"{prompt}"']

    last_error = None
    for base in _find_cli_candidates():
        cmd = base + args
        try:
            _log(f"Trying: {' '.join(cmd)}")
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as e:
            last_error = e
            continue

        stdout_chunks = []
        stderr_chunks = []
        while True:
            line = await proc.stdout.readline()
            if line:
                text = line.decode(errors="ignore")
                stdout_chunks.append(text)
                if on_progress:
                    on_progress(text)
            else:
                break
        stderr = (await proc.stderr.read()).decode(errors="ignore")
        stderr_chunks.append(stderr)
        code = await proc.wait()

        if code == 0:
            return "".join(stdout_chunks).strip()
        else:
            last_error = RuntimeError(f"cmd={' '.join(cmd)} exit={code} stderr={stderr}")
            if "ENOENT" in str(last_error):
                continue
    raise last_error or RuntimeError("Gemini CLI not found")


async def run_gemini_with_fallback(prompt: str, model: Optional[str], sandbox: bool, on_progress=None) -> str:
    # primary
    try:
        return await _run_cli(prompt, DEFAULT_MODEL, sandbox, on_progress)
    except Exception as e_primary:
        _log(f"Primary model failed: {e_primary}")
        # requested or fallback
        try:
            chosen = model or FALLBACK_MODEL
            return await _run_cli(prompt, chosen, sandbox, on_progress)
        except Exception as e_fb:
            msg = str(e_fb)
            if CLI_QUOTA_MSG in msg and (model or FALLBACK_MODEL) != FLASH_MODEL:
                _log("Quota exceeded -> trying flash")
                return await _run_cli(prompt, FLASH_MODEL, sandbox, on_progress)
            raise


def build_change_mode_prompt(user_prompt: str) -> str:
    instructions = """
[CHANGEMODE INSTRUCTIONS]
You are generating code modifications that will be processed by an automated system. The output format is critical because it enables programmatic application of changes without human intervention.
INSTRUCTIONS:
1. Analyze each provided file thoroughly
2. Identify locations requiring changes based on the user request
3. For each change, output in the exact format specified
4. The OLD section must be EXACTLY what appears in the file (copy-paste exact match)
5. Provide complete, directly replacing code blocks
6. Verify line numbers are accurate
CRITICAL REQUIREMENTS:
1. Output edits in the EXACT format specified below - no deviations
2. The OLD string MUST be findable with Ctrl+F - it must be a unique, exact match
3. Include enough surrounding lines to make the OLD string unique
4. If a string appears multiple times (like </div>), include enough context lines above and below to make it unique
5. Copy the OLD content EXACTLY as it appears - including all whitespace, indentation, line breaks
6. Never use partial lines - always include complete lines from start to finish
OUTPUT FORMAT (follow exactly):
**FILE: [filename]:[line_number]**
```
OLD:
[exact code to be replaced - must match file content precisely]
NEW:
[new code to insert - complete and functional]
```
USER REQUEST:
"""
    return instructions + user_prompt


CHANGE_RE = re.compile(
    r"\*\*FILE:\s*(.+?)\s*\*\*.*?```(?:\r?\n)?OLD:\r?\n(.*?)\r?\nNEW:\r?\n(.*?)```",
    re.DOTALL | re.IGNORECASE,
)


def parse_edits(text: str) -> List[Dict[str, str]]:
    edits = []
    for m in CHANGE_RE.finditer(text):
        edits.append(
            {"file": m.group(1).strip(), "old": m.group(2).strip(), "new": m.group(3).strip()}
        )
    return edits


def chunk_edits(edits: List[Dict[str, str]]) -> List[List[Dict[str, str]]]:
    if not edits:
        return []
    return [edits[i : i + CHUNK_SIZE] for i in range(0, len(edits), CHUNK_SIZE)]


def cache_chunks(prompt: str, chunks: List[List[Dict[str, str]]]) -> str:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_key = hashlib.sha256(prompt.encode()).hexdigest()[:8]
    payload = {"ts": _now_ms(), "chunks": chunks}
    (CACHE_DIR / f"{cache_key}.json").write_text(json.dumps(payload), encoding="utf-8")
    return cache_key


def load_chunks(cache_key: str) -> Optional[List[List[Dict[str, str]]]]:
    path = CACHE_DIR / f"{cache_key}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if _now_ms() - data.get("ts", 0) > CACHE_TTL:
        try:
            path.unlink()
        except OSError:
            pass
        return None
    return data.get("chunks")


server = FastMCP("gemini-cli-python")


@server.tool()
async def ask_gemini(
    prompt: str,
    model: Optional[str] = None,
    sandbox: bool = False,
    changeMode: bool = False,
    chunkIndex: Optional[int] = None,
    chunkCacheKey: Optional[str] = None,
) -> str:
    """
    Call Gemini CLI with optional changeMode and chunk fetch.
    """
    if changeMode and chunkIndex and chunkCacheKey:
        chunks = load_chunks(chunkCacheKey)
        if not chunks:
            return f"❌ cache miss for key {chunkCacheKey}"
        if chunkIndex < 1 or chunkIndex > len(chunks):
            return f"❌ invalid chunk index {chunkIndex}, available 1..{len(chunks)}"
        return json.dumps(
            {"chunk": chunkIndex, "total": len(chunks), "edits": chunks[chunkIndex - 1]},
            indent=2,
        )

    run_prompt = build_change_mode_prompt(prompt) if changeMode else prompt
    result = await run_gemini_with_fallback(run_prompt, model, sandbox)

    if not changeMode:
        return result

    edits = parse_edits(result)
    if not edits:
        return "No edits parsed.\n" + result
    chunks = chunk_edits(edits)
    cache_key = cache_chunks(prompt, chunks) if len(chunks) > 1 else None
    chosen_idx = chunkIndex or 1
    chosen_idx = max(1, min(chosen_idx, len(chunks)))
    resp = {
        "chunk": chosen_idx,
        "total": len(chunks),
        "cacheKey": cache_key,
        "edits": chunks[chosen_idx - 1],
    }
    return json.dumps(resp, indent=2)


@server.tool()
async def fetch_chunk(cacheKey: str, chunkIndex: int) -> str:
    chunks = load_chunks(cacheKey)
    if not chunks:
        return f"❌ cache miss for key {cacheKey}"
    if chunkIndex < 1 or chunkIndex > len(chunks):
        return f"❌ invalid chunk index {chunkIndex}, available 1..{len(chunks)}"
    return json.dumps(
        {"chunk": chunkIndex, "total": len(chunks), "edits": chunks[chunkIndex - 1]},
        indent=2,
    )


@server.tool()
async def ping(prompt: str = "Pong!") -> str:
    return prompt


@server.tool()
async def help() -> str:
    return await run_gemini_with_fallback("-help", None, False)


def _brainstorm_prompt(prompt: str, methodology: str, domain: Optional[str], constraints: Optional[str],
                       existingContext: Optional[str], ideaCount: int, includeAnalysis: bool) -> str:
    base = f"# BRAINSTORMING SESSION\n\n## Core Challenge\n{prompt}\n"
    base += f"\n## Methodology\n{methodology}\n"
    if domain:
        base += f"\nDomain: {domain}"
    if constraints:
        base += f"\nConstraints: {constraints}"
    if existingContext:
        base += f"\nContext: {existingContext}"
    base += f"\n\nGenerate {ideaCount} ideas."
    if includeAnalysis:
        base += "\nInclude feasibility/impact/innovation scores (1-5)."
    return base


@server.tool()
async def brainstorm(
    prompt: str,
    model: Optional[str] = None,
    methodology: str = "auto",
    domain: Optional[str] = None,
    constraints: Optional[str] = None,
    existingContext: Optional[str] = None,
    ideaCount: int = 12,
    includeAnalysis: bool = True,
) -> str:
    bp = _brainstorm_prompt(prompt, methodology, domain, constraints, existingContext, ideaCount, includeAnalysis)
    return await run_gemini_with_fallback(bp, model, False)


@server.tool()
async def timeout_test(duration: int) -> str:
    duration = max(10, duration)
    steps = max(1, duration // 5000)
    step = duration / steps
    start = _now_ms()
    for i in range(steps):
        await asyncio.sleep(step / 1000)
    total = _now_ms() - start
    return f"Completed {duration}ms test in {total}ms"


if __name__ == "__main__":
    server.run()
