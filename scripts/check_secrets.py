#!/usr/bin/env python3
"""Scan project-owned text for high-confidence credential material.

This is intentionally small and deterministic so it can run in public CI
without uploading repository contents.  It complements, rather than replaces,
platform secret scanning.
"""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {
    ".git",
    ".tmp",
    "__pycache__",
    "node_modules",
    "seaf-archtool-core",  # audited upstream; scanned in its own supply chain
}
EXCLUDED_PREFIXES = (
    Path("architecture/vendor/seaf-core"),  # audited pinned upstream submodule
)
TEXT_SUFFIXES = {
    "",
    ".css",
    ".env",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".puml",
    ".py",
    ".sh",
    ".toml",
    ".ts",
    ".txt",
    ".yaml",
    ".yml",
}
TOKEN_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    "API token": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "bearer value": re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}", re.IGNORECASE),
}
ASSIGNMENT = re.compile(
    r"(?m)^\s*(?P<name>[A-Z0-9_]*(?:PASSWORD|SECRET|TOKEN|CREDENTIAL|API_KEY)"
    r"[A-Z0-9_]*)\s*[:=]\s*(?P<quote>['\"]?)(?P<value>[^'\"#\s]+)"
)
SAFE_VALUES = {
    "none",
    "null",
    "redacted",
    "changeme",
    "placeholder",
    "example",
    # Documentation says where a value is supplied; it does not contain one.
    "передаётся",
}


def _candidate_files() -> list[Path]:
    candidates: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path == Path(__file__).resolve():
            continue
        relative = path.relative_to(ROOT)
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        if any(
            relative == prefix or prefix in relative.parents
            for prefix in EXCLUDED_PREFIXES
        ):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES or path.stat().st_size > 5_000_000:
            continue
        candidates.append(path)
    return sorted(candidates)


def _safe_assignment(path: Path, match: re.Match[str]) -> bool:
    value = match.group("value").strip()
    lowered = value.lower()
    if (
        not value
        or lowered in SAFE_VALUES
        or value.startswith(("${", "<", "{{"))
        or len(value) < 8
    ):
        return True

    # A Python regex constant is executable source, not a populated credential.
    # Keep this exception deliberately narrow: quoted values and arbitrary calls
    # are still reported.
    return (
        path.suffix.lower() == ".py"
        and match.group("quote") == ""
        and match.group("name").endswith(("_RE", "_REGEX", "_PATTERN"))
        and value == "re.compile("
    )


def scan_text(path: Path, text: str) -> list[str]:
    """Return finding labels without ever returning matched credential text."""

    findings: list[str] = []
    for label, pattern in TOKEN_PATTERNS.items():
        if pattern.search(text):
            findings.append(f"possible {label}")
    for match in ASSIGNMENT.finditer(text):
        if not _safe_assignment(path, match):
            findings.append("possible populated secret assignment")
    return findings


def main() -> int:
    findings: list[str] = []
    for path in _candidate_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        relative = path.relative_to(ROOT).as_posix()
        findings.extend(
            f"{relative}: {finding}" for finding in scan_text(path, text)
        )
    if findings:
        for finding in sorted(set(findings)):
            print(f"SECRET SCAN ERROR: {finding}")
        return 1
    print(f"SECRET SCAN OK: {len(_candidate_files())} project-owned text files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
