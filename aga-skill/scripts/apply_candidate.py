# -*- coding: utf-8 -*-
"""Validate an AGA evolution candidate without changing source files.

The build manifest is useful as an inventory, but it is not an authority to
modify the repository: the same process created the manifest and its hashes.
This command therefore reconstructs the candidate from the current protected
rules and pending precedent, recomputes fitness and the gate, and only reports
the result.  Applying a validated bundle is an external, reviewed VCS
transaction and is intentionally unsupported here.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

PKG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG_ROOT))

from evolver.fitness import gate, markdown_report  # noqa: E402
from evolver.mutations import (  # noqa: E402
    MutationValidationError,
    UnsupportedMutationTypeError,
    validate_mutation,
)
from evolver.policy import CandidateChange, guard_candidate_changes  # noqa: E402
from scripts.run_evolution import (  # noqa: E402
    SEMVER_BUMP,
    _all_rules,
    _distilled_precedent_text,
    _evaluate_with_locked_inputs,
    _verify_locked_corpus,
    apply_mutation,
    bump,
    render_pr_body,
)
from tools.aga import RULE_FILES, parse_frontmatter  # noqa: E402
from tools.validation import DEFAULT_MAX_ARTIFACT_BYTES  # noqa: E402


MANIFEST_KEYS = frozenset(
    {
        "schema",
        "cycle_id",
        "version_from",
        "version_to",
        "gate_passed",
        "artifacts",
        "base_rules",
        "candidate_rules",
        "precedent_artifact",
        "human_confirmation_required",
        "auto_merge",
    }
)
FIXED_ARTIFACTS = frozenset(
    {
        "rules.diff",
        "metrics-baseline.json",
        "metrics-candidate.json",
        "evolution-pr.md",
        "CHANGELOG-entry.md",
    }
)
RULE_NAMES = frozenset({*RULE_FILES, "severity-policy.yaml"})
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
SEMVER_RE = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
CYCLE_RE = re.compile(r"aga-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}\Z")
MAX_BUNDLE_BYTES = 32 * 1024 * 1024


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _safe_directory(path: Path) -> Path:
    """Return an absolute real directory path without following its final link."""

    absolute = _absolute(path)
    try:
        descriptor = _open_directory_fd(absolute)
    except OSError as exc:
        raise ValueError(
            f"directory contains an unavailable or linked component: {absolute}: {exc}"
        ) from exc
    os.close(descriptor)
    return absolute


def _relative_to_root(path: Path, root: Path) -> Path:
    absolute = _absolute(path)
    try:
        return absolute.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path escapes its trusted root: {absolute}") from exc


def _open_directory_fd(path: Path) -> int:
    """Open every absolute directory component without following links."""

    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if (
        nofollow is None
        or directory_flag is None
        or os.open not in getattr(os, "supports_dir_fd", set())
    ):
        raise ValueError(
            "safe candidate validation requires O_NOFOLLOW, O_DIRECTORY, and openat"
        )
    absolute = _absolute(path)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | nofollow | directory_flag
    descriptor = os.open(absolute.anchor, flags)
    try:
        for part in absolute.parts[1:]:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise ValueError(f"path is not a real directory: {absolute}")
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _safe_read(
    path: Path, *, root: Path, limit: int = DEFAULT_MAX_ARTIFACT_BYTES
) -> bytes:
    """Read a bounded file through descriptor-relative no-follow traversal."""

    root = _safe_directory(root)
    relative = _relative_to_root(path, root)
    if not relative.parts:
        raise ValueError("a directory cannot be read as an artifact")

    directory_fd = _open_directory_fd(root)
    nofollow = getattr(os, "O_NOFOLLOW")
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | nofollow
        | getattr(os, "O_DIRECTORY")
    )
    try:
        for part in relative.parts[:-1]:
            child = os.open(part, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = child
        descriptor = os.open(
            relative.parts[-1],
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | nofollow,
            dir_fd=directory_fd,
        )
    except OSError as exc:
        os.close(directory_fd)
        raise ValueError(f"cannot safely open artifact {relative}: {exc}") from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError(f"artifact must be a regular file: {relative}")
        if opened.st_nlink != 1:
            raise ValueError(f"hardlinked artifact is forbidden: {relative}")
        if opened.st_size > limit:
            raise ValueError(f"artifact exceeds {limit} bytes: {relative}")
        remaining = limit + 1
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > limit:
            raise ValueError(f"artifact exceeds {limit} bytes: {relative}")
        final = os.fstat(descriptor)
        if (
            not stat.S_ISREG(final.st_mode)
            or final.st_nlink != 1
            or (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns)
            != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        ):
            raise ValueError(f"artifact changed while it was read: {relative}")
        return payload
    finally:
        os.close(descriptor)
        os.close(directory_fd)


def _decode(payload: bytes, label: str) -> str:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"artifact is not UTF-8: {label}") from exc
    if "\x00" in text:
        raise ValueError(f"artifact contains NUL: {label}")
    return text


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _strict_json(payload: bytes, label: str) -> Any:
    try:
        return json.loads(_decode(payload, label), object_pairs_hook=_unique_object)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON artifact {label}: {exc}") from exc


def _require_sha_map(
    value: Any, *, keys: set[str] | frozenset[str], label: str
) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f"{label} must contain exactly: {', '.join(sorted(keys))}")
    if any(
        not isinstance(digest, str) or not SHA256_RE.fullmatch(digest)
        for digest in value.values()
    ):
        raise ValueError(f"{label} contains an invalid SHA-256 digest")
    return dict(value)


def _safe_name(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(f"{label} must be a safe basename")
    return value


def _inventory(directory: Path, expected: set[str] | frozenset[str]) -> None:
    directory = _safe_directory(directory)
    descriptor = _open_directory_fd(directory)
    try:
        names = set(os.listdir(descriptor))
    finally:
        os.close(descriptor)
    if names != set(expected):
        missing = sorted(set(expected) - names)
        extra = sorted(names - set(expected))
        raise ValueError(
            f"invalid candidate rule inventory; missing={missing}, extra={extra}"
        )


def _validate_manifest(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != MANIFEST_KEYS:
        raise ValueError("candidate manifest has an invalid exact schema")
    manifest = dict(value)
    if (
        manifest["schema"] != "aga.candidate-manifest/v1"
        or manifest["gate_passed"] is not True
        or manifest["auto_merge"] is not False
        or manifest["human_confirmation_required"] is not True
    ):
        raise ValueError(
            "candidate manifest does not declare a passed, human-only gate"
        )
    if not isinstance(manifest["cycle_id"], str) or not CYCLE_RE.fullmatch(
        manifest["cycle_id"]
    ):
        raise ValueError("candidate manifest has an invalid cycle_id")
    for key in ("version_from", "version_to"):
        if not isinstance(manifest[key], str) or not SEMVER_RE.fullmatch(manifest[key]):
            raise ValueError(f"candidate manifest has an invalid {key}")

    precedent_name = _safe_name(manifest["precedent_artifact"], "precedent_artifact")
    if precedent_name in FIXED_ARTIFACTS or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,126}\.md", precedent_name
    ):
        raise ValueError("precedent_artifact must be a Markdown file")
    artifact_names = set(FIXED_ARTIFACTS) | {precedent_name}
    manifest["artifacts"] = _require_sha_map(
        manifest["artifacts"], keys=artifact_names, label="artifacts"
    )
    manifest["base_rules"] = _require_sha_map(
        manifest["base_rules"], keys=RULE_NAMES, label="base_rules"
    )
    manifest["candidate_rules"] = _require_sha_map(
        manifest["candidate_rules"], keys=RULE_NAMES, label="candidate_rules"
    )
    return manifest


def _write_captured_rules(directory: Path, captured: Mapping[str, bytes]) -> None:
    directory.mkdir(mode=0o700)
    for name in sorted(captured):
        (directory / name).write_bytes(captured[name])


def _distilled_precedent(source_text: str, source: Path, version: str) -> str:
    return _distilled_precedent_text(
        source_text,
        source=source,
        version=version,
    )


def _candidate_changelog(
    source_payload: bytes, entry_text: str, *, version: str
) -> bytes:
    source_text = _decode(source_payload, "CHANGELOG.md")
    prefix = "# Changelog\n\n"
    if not source_text.startswith(prefix):
        raise ValueError("CHANGELOG.md has an unsupported heading layout")
    if re.search(rf"(?m)^## v{re.escape(version)}(?:\s|$)", source_text):
        raise ValueError("candidate version already exists in CHANGELOG.md")
    entry = entry_text.rstrip("\n")
    return (prefix + entry + "\n\n" + source_text[len(prefix) :]).encode("utf-8")


def _candidate_target(mutation: Mapping[str, Any]) -> str:
    value = mutation.get("rule_id")
    if value is None and mutation.get("type") == "add_rule":
        rule = mutation.get("rule")
        value = rule.get("id") if isinstance(rule, Mapping) else None
    if not isinstance(value, str) or not value:
        raise ValueError("validated mutation has no target rule id")
    return value


def _changed_rule_ids(base_dir: Path, candidate_dir: Path) -> set[str]:
    base = {rule["id"]: rule for rule in _all_rules(base_dir)}
    candidate = {rule["id"]: rule for rule in _all_rules(candidate_dir)}
    identifiers = set(base) | set(candidate)
    return {
        identifier
        for identifier in identifiers
        if base.get(identifier) != candidate.get(identifier)
    }


def validate_candidate(build: Path) -> dict[str, Any]:
    """Independently reproduce and validate a candidate-only build bundle."""

    build = _safe_directory(build)
    manifest_payload = _safe_read(
        build / "candidate-manifest.json", root=build, limit=1024 * 1024
    )
    manifest = _validate_manifest(
        _strict_json(manifest_payload, "candidate-manifest.json")
    )

    artifact_payloads: dict[str, bytes] = {}
    total_bytes = len(manifest_payload)
    for name, expected in manifest["artifacts"].items():
        payload = _safe_read(build / name, root=build)
        total_bytes += len(payload)
        if total_bytes > MAX_BUNDLE_BYTES:
            raise ValueError(f"candidate bundle exceeds {MAX_BUNDLE_BYTES} bytes")
        if _sha256_bytes(payload) != expected:
            raise ValueError(f"artifact hash mismatch: {name}")
        artifact_payloads[name] = payload

    candidate_root = _safe_directory(build / "candidate-rules")
    _inventory(candidate_root, RULE_NAMES)
    candidate_payloads: dict[str, bytes] = {}
    for name, expected in manifest["candidate_rules"].items():
        payload = _safe_read(candidate_root / name, root=candidate_root)
        total_bytes += len(payload)
        if total_bytes > MAX_BUNDLE_BYTES:
            raise ValueError(f"candidate bundle exceeds {MAX_BUNDLE_BYTES} bytes")
        if _sha256_bytes(payload) != expected:
            raise ValueError(f"candidate rule hash mismatch: {name}")
        candidate_payloads[name] = payload

    source_rules_root = _safe_directory(PKG_ROOT / "rules")
    _inventory(source_rules_root, RULE_NAMES)
    source_payloads: dict[str, bytes] = {}
    for name, expected in manifest["base_rules"].items():
        payload = _safe_read(source_rules_root / name, root=source_rules_root)
        if _sha256_bytes(payload) != expected:
            raise ValueError(f"base rule drift detected: {name}")
        source_payloads[name] = payload

    version_payload = _safe_read(PKG_ROOT / "VERSION", root=PKG_ROOT, limit=128)
    current_version = _decode(version_payload, "VERSION").strip()
    if current_version != manifest["version_from"]:
        raise ValueError("base VERSION drift detected")
    changelog_payload = _safe_read(
        PKG_ROOT / "CHANGELOG.md", root=PKG_ROOT, limit=DEFAULT_MAX_ARTIFACT_BYTES
    )

    precedent_name = manifest["precedent_artifact"]
    precedent_path = PKG_ROOT / "precedents" / "cases" / precedent_name
    source_precedent_payload = _safe_read(
        precedent_path, root=PKG_ROOT / "precedents" / "cases"
    )
    source_precedent = _decode(source_precedent_payload, precedent_name)
    precedent, _ = parse_frontmatter(source_precedent, source=str(precedent_path))
    if (
        precedent.get("status") != "pending"
        or precedent.get("architect_action") not in {"override", "missed"}
        or not isinstance(precedent.get("architect"), str)
        or not precedent["architect"].strip()
        or not isinstance(precedent.get("rationale"), str)
        or not precedent["rationale"].strip()
        or not isinstance(precedent.get("id"), str)
        or not precedent["id"].strip()
    ):
        raise ValueError(
            "source precedent is not an approved pending architect decision"
        )
    expected_distilled = _distilled_precedent(
        source_precedent, precedent_path, manifest["version_to"]
    ).encode("utf-8")
    if artifact_payloads[precedent_name] != expected_distilled:
        raise ValueError(
            "distilled precedent artifact cannot be reproduced from its source"
        )

    locked_inputs = _verify_locked_corpus(precedent)
    provenance = f"precedent:{precedent['id']}"
    raw_mutations = precedent.get("proposed_mutations")
    if raw_mutations is None:
        raw_mutations = [precedent.get("proposed_mutation")]
    if (
        not isinstance(raw_mutations, list)
        or not raw_mutations
        or raw_mutations == [None]
    ):
        raise ValueError("source precedent has no candidate mutations")

    matches: list[tuple[dict[str, Any], str, str, Path, Path]] = []
    temporary = tempfile.TemporaryDirectory(prefix="aga-candidate-validation-")
    temp_root = Path(temporary.name)
    try:
        base_dir = temp_root / "base-rules"
        _write_captured_rules(base_dir, source_payloads)
        base_rules = _all_rules(base_dir)
        for index, raw_mutation in enumerate(raw_mutations[:3], 1):
            try:
                mutation = validate_mutation(
                    raw_mutation, base_rules, approved_provenance={provenance}
                )
            except (MutationValidationError, UnsupportedMutationTypeError):
                continue
            expected_version = bump(current_version, SEMVER_BUMP[mutation["type"]])
            if expected_version != manifest["version_to"]:
                continue
            candidate_dir = temp_root / f"candidate-{index}"
            diff, changed_file = apply_mutation(
                base_dir, candidate_dir, mutation, expected_version
            )
            reproduced = {
                name: (candidate_dir / name).read_bytes() for name in sorted(RULE_NAMES)
            }
            if reproduced == candidate_payloads:
                matches.append((mutation, diff, changed_file, base_dir, candidate_dir))

        if len(matches) != 1:
            raise ValueError(
                "candidate rules do not map uniquely to a validated mutation from the precedent"
            )
        mutation, diff, changed_file, base_dir, candidate_dir = matches[0]
        target_rule = _candidate_target(mutation)
        changed_ids = _changed_rule_ids(base_dir, candidate_dir)
        if changed_ids != {target_rule}:
            raise ValueError("candidate must change exactly its declared target rule")
        if artifact_payloads["rules.diff"] != diff.encode("utf-8"):
            raise ValueError(
                "rules.diff cannot be reproduced from the validated mutation"
            )
        guard_candidate_changes(
            [
                CandidateChange(
                    f"rules/{changed_file}",
                    source_payloads[changed_file],
                    candidate_payloads[changed_file],
                )
            ]
        )
        if (
            candidate_payloads["severity-policy.yaml"]
            != source_payloads["severity-policy.yaml"]
        ):
            raise ValueError("candidate changed the protected severity policy")

        stored_base = _strict_json(
            artifact_payloads["metrics-baseline.json"], "metrics-baseline.json"
        )
        stored_candidate = _strict_json(
            artifact_payloads["metrics-candidate.json"], "metrics-candidate.json"
        )
        recomputed_base = _evaluate_with_locked_inputs(
            base_dir, locked_inputs, minimum_cases=15
        )
        recomputed_candidate = _evaluate_with_locked_inputs(
            candidate_dir,
            locked_inputs,
            minimum_cases=15,
            include_candidates=mutation["type"] == "add_rule",
            protected_error_costs=recomputed_base["error_costs"],
        )
        if stored_base != recomputed_base:
            raise ValueError(
                "stored baseline metrics differ from independent evaluation"
            )
        if stored_candidate != recomputed_candidate:
            raise ValueError(
                "stored candidate metrics differ from independent evaluation"
            )
        passed, checks = gate(
            recomputed_base,
            recomputed_candidate,
            changed_rule_ids=changed_ids,
            mutation=mutation,
        )
        if not passed or not all(check["passed"] for check in checks):
            raise ValueError("independently recomputed candidate gate did not pass")

        changelog_text = _decode(
            artifact_payloads["CHANGELOG-entry.md"], "CHANGELOG-entry.md"
        )
        first_line = changelog_text.splitlines()[0] if changelog_text else ""
        date_match = re.fullmatch(
            rf"## v{re.escape(manifest['version_to'])} — ([0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}})",
            first_line,
        )
        if date_match is None:
            raise ValueError("CHANGELOG entry has an invalid candidate version/date")
        try:
            candidate_date = dt.date.fromisoformat(date_match.group(1))
            cycle_date = dt.datetime.strptime(
                manifest["cycle_id"][4:12], "%Y%m%d"
            ).date()
        except ValueError as exc:
            raise ValueError("candidate artifact date is invalid") from exc
        if abs((candidate_date - cycle_date).days) > 1:
            raise ValueError("candidate artifact date is inconsistent with cycle_id")
        expected_changelog = (
            f"## v{manifest['version_to']} — {candidate_date.isoformat()}\n"
            f"- {mutation['type']} для {target_rule} (provenance: {provenance}); "
            f"precision {recomputed_base['precision']} → "
            f"{recomputed_candidate['precision']}, weighted cost "
            f"{recomputed_base['weighted_cost']} → "
            f"{recomputed_candidate['weighted_cost']} на "
            f"{recomputed_candidate['cases_evaluated']} cases.\n"
        )
        if changelog_text != expected_changelog:
            raise ValueError(
                "CHANGELOG entry cannot be reproduced from validated evidence"
            )
        candidate_changelog_payload = _candidate_changelog(
            changelog_payload,
            expected_changelog,
            version=manifest["version_to"],
        )

        cycle_suffix = manifest["cycle_id"].rsplit("-", 1)[-1]
        branch = (
            f"skill/evolution-{candidate_date.isoformat()}-{target_rule}-{cycle_suffix}"
        )
        expected_pr = render_pr_body(
            {
                "version_from": current_version,
                "version_to": manifest["version_to"],
                "mutation_type": mutation["type"],
                "rule_id": target_rule,
                "precedent": provenance,
                "rationale": str(precedent["rationale"]).strip(),
                "branch": branch,
                "date": candidate_date.isoformat(),
                "diff": diff,
                "metrics_table": markdown_report(
                    recomputed_base, recomputed_candidate, checks
                ),
            }
        ).encode("utf-8")
        if artifact_payloads["evolution-pr.md"] != expected_pr:
            raise ValueError(
                "evolution PR body cannot be reproduced from validated evidence"
            )

        changed_rule_files = {
            name
            for name in RULE_NAMES
            if candidate_payloads[name] != source_payloads[name]
        }
        if changed_rule_files != {changed_file}:
            raise ValueError("candidate must alter exactly one declared rule file")
        rule_path = f"aga-skill/rules/{changed_file}"
        precedent_relative = f"aga-skill/precedents/cases/{precedent_name}"
        transaction_payloads = {
            rule_path: candidate_payloads[changed_file],
            "aga-skill/VERSION": (manifest["version_to"] + "\n").encode("utf-8"),
            "aga-skill/CHANGELOG.md": candidate_changelog_payload,
            precedent_relative: expected_distilled,
        }
        transaction_base_payloads = {
            rule_path: source_payloads[changed_file],
            "aga-skill/VERSION": version_payload,
            "aga-skill/CHANGELOG.md": changelog_payload,
            precedent_relative: source_precedent_payload,
        }
        base_binding_payloads = {
            f"aga-skill/rules/{name}": payload
            for name, payload in source_payloads.items()
        }
        base_binding_payloads.update(transaction_base_payloads)
        base_binding_payloads.update(
            {
                "aga-skill/golden/corpus.yaml": locked_inputs.corpus_payload,
                "aga-skill/golden/corpus.lock.json": locked_inputs.corpus_lock_payload,
                "aga-skill/fixtures/seaf.yaml": locked_inputs.seaf_payload,
            }
        )
        base_binding_payloads.update(
            {
                f"aga-skill/golden/prs/{relative}": payload
                for relative, payload in locked_inputs.fixture_files
            }
        )

        return {
            "manifest": manifest,
            "mutation": mutation,
            "changed_rule_ids": sorted(changed_ids),
            "gate_checks": checks,
            "fixtures_revision": locked_inputs.fixtures_revision,
            "baseline_revision": recomputed_base["rules_revision"],
            "candidate_revision": recomputed_candidate["rules_revision"],
            "precedent": provenance,
            # Already independently reproduced and verified against the
            # bundle above; exposed so a separately authorised publisher can
            # reuse the exact validated branch name and PR body instead of
            # recomputing (and risking drifting from) this validation.
            "branch": branch,
            "pr_body": expected_pr.decode("utf-8"),
            "candidate_rule_payloads": candidate_payloads,
            "changed_rule_files": sorted(changed_rule_files),
            "transaction_payloads": transaction_payloads,
            "transaction_base_payloads": transaction_base_payloads,
            "base_binding_payloads": base_binding_payloads,
            "target_rule": target_rule,
        }
    finally:
        temporary.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate an AGA candidate bundle without changing sources"
    )
    parser.add_argument("--build", default=str(PKG_ROOT / "build"))
    parser.add_argument(
        "--actor", required=True, help="human actor identity for audit output"
    )
    args = parser.parse_args()
    try:
        if (
            not args.actor.strip()
            or len(args.actor) > 200
            or any(
                ord(character) < 32 or ord(character) == 127 for character in args.actor
            )
        ):
            raise ValueError(
                "actor must be a printable non-empty identity up to 200 characters"
            )
        validated = validate_candidate(Path(args.build))
        manifest = validated["manifest"]
        print(
            json.dumps(
                {
                    "status": "validated_candidate_bundle",
                    "cycle_id": manifest["cycle_id"],
                    "actor": args.actor,
                    "changed_rule_ids": validated["changed_rule_ids"],
                    "gate_checks": validated["gate_checks"],
                    "baseline_revision": validated["baseline_revision"],
                    "candidate_revision": validated["candidate_revision"],
                    "sources_changed": False,
                    "apply_supported": False,
                    "external_apply_required": True,
                    "merge_performed": False,
                    "push_performed": False,
                    "approval_performed": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(
            json.dumps(
                {"error": "candidate_validation_error", "message": str(error)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
