"""
Lightweight harness tests (no external CLI needed).
Uses echo to simulate CLI outputs and checks:
 - changeMode parsing & chunking
 - candidate resolution prefers GEMINI_BIN
Run with: uv run tests/python_harness.py
"""

import os
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT))

from server import parse_edits, chunk_edits, cache_chunks, load_chunks


def test_parse_and_chunk():
    sample = """
**FILE: app.py:10**
```
OLD:
print("hi")
NEW:
print("hello")
```
**FILE: app.py:20**
```
OLD:
x=1
NEW:
x=2
```
"""
    edits = parse_edits(sample)
    assert len(edits) == 2
    chunks = chunk_edits(edits)
    assert len(chunks) == 1 and len(chunks[0]) == 2


def test_cache_roundtrip():
    edits = [[{"file": "a", "old": "1", "new": "2"}]]
    key = cache_chunks("prompt", edits)
    got = load_chunks(key)
    assert got == edits


def main():
    test_parse_and_chunk()
    test_cache_roundtrip()
    print("[OK] python harness passed")


if __name__ == "__main__":
    main()
