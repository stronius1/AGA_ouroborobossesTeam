#!/usr/bin/env python3
"""Remove classified caches/runtime outputs; never delete versioned evidence."""

from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IGNORED_DIRS = {".git", "node_modules", "dist"}
IGNORED_PREFIXES = (
    ("seaf-archtool-core",),
    ("architecture", "vendor", "seaf-core"),
)
CACHE_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
CACHE_FILES = {".DS_Store"}
GENERATED_DIRS = (ROOT / "aga-skill" / "build",)
GENERATED_FILES = (
    ROOT / "aga-skill" / "logs" / "reviews.jsonl",
    ROOT / "aga-skill" / "logs" / "evolution.jsonl",
)


def main() -> int:
    removed: list[Path] = []
    for path in GENERATED_DIRS:
        if path.is_dir():
            shutil.rmtree(path)
            removed.append(path)
    for path in GENERATED_FILES:
        if path.is_file():
            path.unlink()
            removed.append(path)
    candidates = sorted(ROOT.rglob("*"), key=lambda path: len(path.parts), reverse=True)
    for path in candidates:
        try:
            relative_parts = path.relative_to(ROOT).parts
        except ValueError:
            continue
        if any(part in IGNORED_DIRS for part in relative_parts) or any(
            relative_parts[: len(prefix)] == prefix for prefix in IGNORED_PREFIXES
        ):
            continue
        if path.is_dir() and path.name in CACHE_DIRS:
            shutil.rmtree(path)
            removed.append(path)
        elif path.is_file() and (path.name in CACHE_FILES or path.suffix == ".pyc"):
            path.unlink()
            removed.append(path)
    for path in sorted(removed):
        print(f"removed {path.relative_to(ROOT)}")
    print(f"removed {len(removed)} generated cache entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
