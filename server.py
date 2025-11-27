"""
Full-featured MCP server (Python) mirroring the Node implementation.
Run with: uv run server.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("gemini-cli-mcp-python")

# -------- constants --------
KEEPALIVE_INTERVAL_MS = 25_000
QUOTA_STRING = "Quota exceeded for quota metric 'Gemini 2.5 Pro Requests'"
MODEL_PRO = "gemini-2.5-pro"
MODEL_FLASH = "gemini-2.5-flash"
CACHE_TTL = 30 * 60  # seconds (extended for repeated prompts)
CACHE_LIMIT = 50
CACHE_DIR = Path(tempfile.gettempdir()) / "gemini-mcp-chunks"


# -------- helpers --------
def _ensure_gemini() -> str:
    path = shutil.which("gemini")
    if not path:
        raise RuntimeError(
            "gemini CLI not found in PATH. Install the Gemini CLI and ensure 'gemini' is available."
        )
    return path


def _run_gemini(prompt: str, model: Optional[str], sandbox: bool) -> str:
    gemini = _ensure_gemini()
    args = [gemini]
    if model:
        args += ["-m", model]
    if sandbox:
        args.append("-s")
    args += ["-p", prompt]

    # Minimal env to reduce startup overhead and avoid color noise
    env = os.environ.copy()
    env.setdefault("NO_COLOR", "1")
    # If user already has GEMINI_API_KEY etc., we keep them; we only add flags that speed/clean output.

    result = subprocess.run(
        args,
        text=True,
        capture_output=True,
        check=False,
        encoding="utf-8",
        env=env,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(stderr or f"gemini exited {result.returncode}")
    return result.stdout.strip()


def _run_with_preferred_model(prompt: str, sandbox: bool, requested_model: Optional[str]) -> str:
    """
    Always try gemini-3-pro-preview first.
    If it fails (e.g., account/model not available), fall back to previous behavior:
    - use requested_model (if provided) else MODEL_PRO
    - if quota exceeded and not already flash, retry MODEL_FLASH
    """
    primary_model = "gemini-3-pro-preview"
    fallback_model = requested_model or MODEL_PRO

    try:
        return _run_gemini(prompt, primary_model, sandbox)
    except RuntimeError as primary_error:
        # Attempt previous behavior
        try:
            result = _run_gemini(prompt, fallback_model, sandbox)
            return result
        except RuntimeError as e:
            msg = str(e)
            if QUOTA_STRING in msg and fallback_model != MODEL_FLASH:
                return _run_gemini(prompt, MODEL_FLASH, sandbox)
            # If all attempts fail, raise the latest error
            raise e


# -------- change-mode parsing/chunking --------
@dataclass
class Edit:
    filename: str
    old_start: int
    old_end: int
    old: str
    new_start: int
    new_end: int
    new: str


def parse_edits(text: str) -> List[Edit]:
    edits: List[Edit] = []
    pattern = re.compile(
        r"\*\*FILE:\s*(.+?):(\d+)\*\*\s*\n```?\s*\nOLD:\s*\n([\s\S]*?)\nNEW:\s*\n([\s\S]*?)\n```",
        re.MULTILINE,
    )
    for match in pattern.finditer(text):
        filename, start_line, old_code, new_code = match.groups()
        start = int(start_line)
        old_lines = 0 if not old_code.strip() else len(old_code.strip("\n").splitlines())
        new_lines = 0 if not new_code.strip() else len(new_code.strip("\n").splitlines())
        edits.append(
            Edit(
                filename=filename.strip(),
                old_start=start,
                old_end=start + (old_lines - 1 if old_lines else 0),
                old=old_code.rstrip(),
                new_start=start,
                new_end=start + (new_lines - 1 if new_lines else 0),
                new=new_code.rstrip(),
            )
        )
    return edits


def validate_edits(edits: List[Edit]) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    for e in edits:
        if not e.filename:
            errors.append("missing filename")
        if e.old_start > e.old_end:
            errors.append(f"{e.filename}: old range invalid")
        if e.new_start > e.new_end:
            errors.append(f"{e.filename}: new range invalid")
        if not e.old and not e.new:
            errors.append(f"{e.filename}: empty edit")
    return (len(errors) == 0, errors)


def chunk_edits(edits: List[Edit], max_chars: int = 20_000):
    if not edits:
        return [edits]
    chunks: List[List[Edit]] = []
    current: List[Edit] = []
    size = 0
    for e in edits:
        est = len(e.filename) * 2 + len(e.old) + len(e.new) + 250
        if current and size + est > max_chars:
            chunks.append(current)
            current = []
            size = 0
        current.append(e)
        size += est
    if current:
        chunks.append(current)
    return chunks


def format_chunk(edits: List[Edit], idx: int, total: int, cache_key: Optional[str]) -> str:
    header = (
        f"[CHANGEMODE OUTPUT - Chunk {idx} of {total}]\n\n"
        if total > 1
        else "[CHANGEMODE OUTPUT]\n\n"
    )
    body_parts = []
    for i, e in enumerate(edits, 1):
        body_parts.append(
            f"### Edit {i}: {e.filename}\n\n"
            "Replace this exact text:\n```\n"
            f"{e.old}\n```\n\n"
            "With this text:\n```\n"
            f"{e.new}\n```\n"
        )
    footer = "\nApply these edits in order."
    if cache_key and idx < total:
        footer += (
            f"\n\nNext chunk: fetch-chunk cacheKey=\"{cache_key}\" chunkIndex={idx+1}"
        )
    return header + "\n".join(body_parts) + footer


# -------- cache helpers --------
def _ensure_cache_dir():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _prune_cache():
    files = sorted(CACHE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
    now = time.time()
    for f in files:
        if now - f.stat().st_mtime > CACHE_TTL:
            f.unlink(missing_ok=True)
    files = sorted(CACHE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
    if len(files) > CACHE_LIMIT:
        for f in files[:-CACHE_LIMIT]:
            f.unlink(missing_ok=True)


def cache_chunks(prompt: str, chunks: List[List[Edit]]) -> str:
    import hashlib

    _ensure_cache_dir()
    _prune_cache()
    key = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:8]
    data = [
        [e.__dict__ for e in chunk]
        for chunk in chunks
    ]
    (CACHE_DIR / f"{key}.json").write_text(json.dumps(data), encoding="utf-8")
    return key


def load_chunks(key: str) -> Optional[List[List[Edit]]]:
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    if time.time() - path.stat().st_mtime > CACHE_TTL:
        path.unlink(missing_ok=True)
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        [Edit(**e) for e in chunk]
        for chunk in data
    ]


# -------- prompt builders --------
def build_change_mode_prompt(user_prompt: str) -> str:
    return f"""
[CHANGEMODE INSTRUCTIONS]
You are generating code modifications that will be processed by an automated system. The output format is critical.

OUTPUT FORMAT (follow exactly):
**FILE: [filename]:[line_number]**
```
OLD:
[exact code to be replaced - must match file content precisely]
NEW:
[new code to insert - complete and functional]
```

IMPORTANT: The OLD section must be an EXACT copy from the file.

USER REQUEST:
{user_prompt}
""".strip()


def build_brainstorm_prompt(
    prompt: str,
    methodology: str,
    domain: Optional[str],
    constraints: Optional[str],
    existing: Optional[str],
    idea_count: int,
    include_analysis: bool,
) -> str:
    framework = {
        "divergent": "Generate many ideas, suspend judgment, combine wild concepts.",
        "convergent": "Refine and prioritize, focus on feasibility and impact.",
        "scamper": "SCAMPER: Substitute, Combine, Adapt, Modify, Put to other use, Eliminate, Reverse.",
        "design-thinking": "Empathize, Define, Ideate, Prototype mindset, user-centered.",
        "lateral": "Break assumptions, use analogies, random connections.",
        "auto": "Blend divergent + SCAMPER + human-centered; pick best approach automatically.",
    }.get(methodology, "auto strategy.")
    analysis = (
        "\nFor each idea, add Feasibility/Impact/Innovation (1-5) and one-line assessment."
        if include_analysis
        else ""
    )
    return f"""# BRAINSTORM
Challenge: {prompt}
Methodology: {framework}
Domain: {domain or 'general'}
Constraints: {constraints or 'none listed'}
Context: {existing or 'n/a'}
Need {idea_count} distinct, actionable ideas.{analysis}
Format:
### Idea N: Name
Description: ...
{ 'Scores: Feasibility/Impact/Innovation | Assessment' if include_analysis else '' }
Ensure ideas are non-duplicative and respect constraints.
"""


# -------- MCP tools --------
@mcp.tool()
def ping(message: str = "pong") -> str:
    return message


@mcp.tool()
def help() -> str:
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
def ask_gemini(
    prompt: str,
    model: Optional[str] = None,
    sandbox: bool = False,
    changeMode: bool = False,
    chunkIndex: Optional[int] = None,
    chunkCacheKey: Optional[str] = None,
) -> str:
    if changeMode and chunkIndex and chunkCacheKey:
        chunks = load_chunks(chunkCacheKey)
        if not chunks:
            return "Cache miss. Re-run changeMode prompt."
        if chunkIndex < 1 or chunkIndex > len(chunks):
            return f"Invalid chunk index {chunkIndex}; available 1..{len(chunks)}"
        return format_chunk(chunks[chunkIndex - 1], chunkIndex, len(chunks), chunkCacheKey)

    if not prompt.strip():
        raise RuntimeError("Please provide a prompt.")

    effective_prompt = build_change_mode_prompt(prompt) if changeMode else prompt
    result = _run_with_preferred_model(effective_prompt, sandbox, model)

    if not changeMode:
        return f"Gemini response:\n{result}"

    edits = parse_edits(result)
    valid, errors = validate_edits(edits)
    if not valid:
        return "Edit validation failed:\n" + "\n".join(errors) + f"\nRaw output:\n{result}"
    chunks = chunk_edits(edits)
    cache_key = cache_chunks(prompt, chunks) if len(chunks) > 1 else None
    formatted = format_chunk(chunks[0], 1, len(chunks), cache_key)
    if len(chunks) > 1:
        formatted = f"ChangeMode Summary: {len(edits)} edits across {len(chunks)} chunks.\nCacheKey: {cache_key}\n\n" + formatted
    return formatted


@mcp.tool()
def brainstorm(
    prompt: str,
    model: Optional[str] = None,
    methodology: str = "auto",
    domain: Optional[str] = None,
    constraints: Optional[str] = None,
    existingContext: Optional[str] = None,
    ideaCount: int = 12,
    includeAnalysis: bool = True,
) -> str:
    if not prompt.strip():
        raise RuntimeError("You must provide a brainstorming prompt.")
    p = build_brainstorm_prompt(
        prompt,
        methodology,
        domain,
        constraints,
        existingContext,
        ideaCount,
        includeAnalysis,
    )
    return _run_with_preferred_model(p, False, model)


@mcp.tool()
def fetch_chunk(cacheKey: str, chunkIndex: int) -> str:
    chunks = load_chunks(cacheKey)
    if not chunks:
        return f"Cache miss for {cacheKey}. TTL {CACHE_TTL//60} minutes."
    if chunkIndex < 1 or chunkIndex > len(chunks):
        return f"Invalid chunk index {chunkIndex}; available 1..{len(chunks)}"
    return format_chunk(chunks[chunkIndex - 1], chunkIndex, len(chunks), cacheKey)


@mcp.tool()
def timeout_test(duration: int) -> str:
    if duration < 10:
        raise RuntimeError("Duration must be >= 10ms")
    steps = max(1, duration // 5000)
    step = duration / steps
    start = time.time()
    msgs = [f"Starting timeout test for {duration}ms"]
    for i in range(1, steps + 1):
        time.sleep(step / 1000)
        elapsed = time.time() - start
        msgs.append(f"Step {i}/{steps} - elapsed {elapsed:.1f}s")
    total = (time.time() - start) * 1000
    msgs.append(f"Done. Target {duration}ms, actual {int(total)}ms")
    return "\n".join(msgs)


if __name__ == "__main__":
    mcp.run()
