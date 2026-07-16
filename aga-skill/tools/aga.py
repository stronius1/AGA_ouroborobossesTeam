# -*- coding: utf-8 -*-
"""AGA deterministic review engine and narrow Ouroboros tool adapter.

The engine is deliberately configuration-driven: ``scope``, ``check_type``
and the single operator encoded in each rule's ``detect`` mapping decide what
runs.  Rule identifiers are data and are never used to select detector code.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import threading
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from tools.validation import (
    ValidationError,
    safe_artifact_path,
    safe_read_artifact,
    strict_load_yaml,
    strict_load_yaml_text,
    validate_manifest,
    validate_review_frontmatter,
    validate_rules_directory,
)

PKG_ROOT = Path(__file__).resolve().parent.parent

SEVERITY_ORDER = {"blocker": 3, "major": 2, "minor": 1}
RULE_FILES = ["principles.yaml", "seaf-checks.yaml", "diagram-checks.yaml", "adr-checks.yaml"]
KNOWN_KINDS = {"system_passport", "integration_flow", "adr", "diagram", "out_of_scope"}
ARTIFACT_EXTENSIONS = {".md", ".puml", ".mmd"}
GIT_DIFF_MAX_BYTES = 1_048_576
GIT_DIFF_MAX_PATHS = 4_096
GIT_METADATA_MAX_BYTES = 4_096
GIT_TIMEOUT_SECONDS = 30
_GIT_OBJECT_ID_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


# ---------------------------------------------------------------------------
# Strict loading and configuration validation

def load_yaml(path: str | Path, *, expected_type: type = dict) -> Any:
    """Compatibility wrapper around the single strict YAML loader."""
    return strict_load_yaml(Path(path), expected_type=expected_type)


def _require_mapping(value: Any, *, path: Path, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError("expected mapping", path=path, field=field, code="schema_type")
    return value


def _require_nonempty(rule: Mapping[str, Any], key: str, path: Path) -> None:
    value = rule.get(key)
    if value is None or value == "" or value == [] or value == {}:
        raise ValidationError("required non-empty field", path=path, field=key, code="required")


def _validate_condition(condition: Any, *, path: Path, field: str) -> None:
    if not isinstance(condition, Mapping) or not condition:
        raise ValidationError("exception condition must be a non-empty mapping",
                              path=path, field=field, code="invalid_condition")
    logical = [name for name in ("all", "any") if name in condition]
    if logical:
        if len(condition) != 1:
            raise ValidationError("logical condition cannot contain sibling keys",
                                  path=path, field=field, code="invalid_condition")
        children = condition[logical[0]]
        if not isinstance(children, list) or not children:
            raise ValidationError("logical condition requires a non-empty list",
                                  path=path, field=field, code="invalid_condition")
        for index, child in enumerate(children):
            _validate_condition(child, path=path, field=f"{field}.{logical[0]}[{index}]")
        return
    if not isinstance(condition.get("field"), str) or not condition["field"].strip():
        raise ValidationError("condition field is required", path=path, field=field,
                              code="invalid_condition")
    operators = [name for name in ("equals", "contains", "in") if name in condition]
    if len(operators) != 1 or set(condition) != {"field", operators[0]}:
        raise ValidationError("condition requires exactly one of equals/contains/in",
                              path=path, field=field, code="invalid_condition")
    if operators[0] == "in" and not isinstance(condition["in"], list):
        raise ValidationError("in operator requires a list", path=path, field=field,
                              code="invalid_condition")


def _normalise_detect(detect: Any, *, path: Path, field: str) -> tuple[str, Any]:
    if not isinstance(detect, Mapping) or not detect:
        raise ValidationError("detect must be a non-empty mapping", path=path, field=field,
                              code="invalid_detect")
    if set(detect) == {"field", "banned"}:
        return "field_banned", {"field": detect["field"], "values": detect["banned"]}
    if len(detect) != 1:
        raise ValidationError("detect must encode exactly one supported operator",
                              path=path, field=field, code="invalid_detect")
    return next(iter(detect.items()))


def _validate_rule(rule: Any, *, path: Path, index: int) -> None:
    rule = _require_mapping(rule, path=path, field=f"rules[{index}]")
    for key in ("id", "title", "statement", "severity", "scope", "check_type",
                "source_ref", "provenance", "status"):
        _require_nonempty(rule, key, path)
    if rule["severity"] not in SEVERITY_ORDER:
        raise ValidationError("unknown severity", path=path, field="severity", code="enum")
    if rule["status"] not in {"active", "candidate", "deprecated"}:
        raise ValidationError("unknown rule status", path=path, field="status", code="enum")
    if rule["check_type"] not in {"deterministic", "llm", "hybrid"}:
        raise ValidationError("unknown check_type", path=path, field="check_type", code="enum")
    if not isinstance(rule["scope"], list) or not rule["scope"] \
            or any(kind not in KNOWN_KINDS - {"out_of_scope"} for kind in rule["scope"]):
        raise ValidationError("scope must contain known review kinds", path=path,
                              field="scope", code="enum")
    provenance = _require_mapping(rule["provenance"], path=path, field="provenance")
    if not provenance.get("origin") or not provenance.get("added_in"):
        raise ValidationError("rule provenance requires origin and added_in", path=path,
                              field="provenance", code="required")
    if rule["check_type"] in {"deterministic", "hybrid"}:
        operator, _ = _normalise_detect(rule.get("detect"), path=path, field="detect")
        if operator not in DETECTORS:
            raise ValidationError(f"unsupported detect operator: {operator}", path=path,
                                  field="detect", code="unsupported_detect")
    exceptions = rule.get("exceptions", [])
    if not isinstance(exceptions, list):
        raise ValidationError("exceptions must be a list", path=path, field="exceptions",
                              code="schema_type")
    for exc_index, exception in enumerate(exceptions):
        exception = _require_mapping(exception, path=path,
                                     field=f"rules[{index}].exceptions[{exc_index}]")
        for key in ("id", "rationale", "provenance", "added_in", "when"):
            _require_nonempty(exception, key, path)
        _validate_condition(exception["when"], path=path,
                            field=f"rules[{index}].exceptions[{exc_index}].when")


def load_rules(rules_dir: str | Path | None = None, *,
               include_candidates: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load and validate rules. Candidate rules are opt-in for fitness only."""
    directory = Path(rules_dir or PKG_ROOT / "rules")
    if directory.is_symlink() or not directory.is_dir():
        raise ValidationError("rules directory must be a real directory", path=directory,
                              code="unsafe_path")
    rules: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name in RULE_FILES:
        path = directory / name
        data = strict_load_yaml(path, expected_type=dict)
        raw_rules = data.get("rules")
        if not isinstance(raw_rules, list):
            raise ValidationError("rules must be a list", path=path, field="rules",
                                  code="schema_type")
        for index, raw_rule in enumerate(raw_rules):
            _validate_rule(raw_rule, path=path, index=index)
            rule_id = raw_rule["id"]
            if rule_id in seen:
                raise ValidationError(f"duplicate rule id: {rule_id}", path=path,
                                      field=f"rules[{index}].id", code="duplicate_rule_id")
            seen.add(rule_id)
            if raw_rule["status"] == "active" or (include_candidates and raw_rule["status"] == "candidate"):
                rules.append(dict(raw_rule))
    policy_path = directory / "severity-policy.yaml"
    policy = strict_load_yaml(policy_path, expected_type=dict)
    required_policy = {"severities", "verdict_policy", "autonomy", "error_costs"}
    if not required_policy.issubset(policy):
        missing = sorted(required_policy - set(policy))
        raise ValidationError(f"severity policy is missing: {', '.join(missing)}",
                              path=policy_path, code="required")
    if policy.get("autonomy", {}).get("auto_merge") is not False:
        raise ValidationError("autonomy.auto_merge must remain false", path=policy_path,
                              field="autonomy.auto_merge", code="security_invariant")
    # The shared validation layer additionally validates each detector's
    # argument shape and exception anti-tautology contract. Local checks above
    # retain stable review error codes for existing API consumers.
    validate_rules_directory(
        directory,
        statuses={"active", "candidate"} if include_candidates else {"active"},
    )
    return rules, policy


def load_seaf(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    source = Path(path or PKG_ROOT / "fixtures" / "seaf.yaml")
    if source.is_symlink() or not source.is_file():
        raise ValidationError("SEAF fixture must be a real file", path=source, code="unsafe_path")
    data = strict_load_yaml(source, expected_type=dict)
    systems = data.get("systems")
    if not isinstance(systems, list) or not systems:
        raise ValidationError("systems must be a non-empty list", path=source,
                              field="systems", code="schema_type")
    result: dict[str, dict[str, Any]] = {}
    for index, system in enumerate(systems):
        system = _require_mapping(system, path=source, field=f"systems[{index}]")
        for key in ("id", "name", "owner", "criticality", "target_status", "infra"):
            if key not in system:
                raise ValidationError("SEAF system field is required", path=source,
                                      field=f"systems[{index}].{key}", code="required")
        if not isinstance(system["infra"], bool):
            raise ValidationError("infra must be boolean", path=source,
                                  field=f"systems[{index}].infra", code="schema_type")
        if system["id"] in result:
            raise ValidationError("duplicate SEAF system id", path=source,
                                  field=f"systems[{index}].id", code="duplicate_key")
        result[system["id"]] = dict(system)
    return result


# ---------------------------------------------------------------------------
# Frontmatter, classification and trusted changed-files providers

FM_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)


def parse_frontmatter(text: str, *, source: str = "<frontmatter>") -> tuple[dict[str, Any], str]:
    """Parse frontmatter strictly. Malformed YAML is never converted to ``{}``."""
    if not text.startswith("---"):
        return {}, text
    match = FM_RE.match(text)
    if not match:
        raise ValidationError("unterminated frontmatter", path=source, field="frontmatter",
                              code="malformed_frontmatter")
    metadata = strict_load_yaml_text(match.group(1), source=source, expected_type=dict)
    return metadata, text[match.end():]


def _path_kind(relative_path: str) -> str:
    path = PurePosixPath(relative_path)
    parts = path.parts
    if not parts:
        return "out_of_scope"
    if parts[0] == "flows" and path.suffix == ".md":
        return "integration_flow"
    if parts[0] == "systems" and path.suffix == ".md":
        return "system_passport"
    if parts[0] == "adrs" and path.suffix == ".md":
        return "adr"
    if parts[0] == "diagrams" and path.suffix in {".puml", ".mmd"}:
        return "diagram"
    return "out_of_scope"


def classify(relative_path: str | Path, metadata: Mapping[str, Any], *, strict: bool = True) -> str:
    path_kind = _path_kind(str(relative_path))
    declared = metadata.get("kind")
    if declared is not None and declared not in KNOWN_KINDS:
        raise ValidationError(f"unknown kind: {declared}", path=str(relative_path),
                              field="kind", code="unknown_kind")
    if strict and declared is not None and declared != path_kind:
        raise ValidationError(f"kind {declared!r} conflicts with path kind {path_kind!r}",
                              path=str(relative_path), field="kind", code="kind_path_conflict")
    return declared or path_kind


def _deduplicate_paths(paths: Sequence[str]) -> list[str]:
    if isinstance(paths, (str, bytes)):
        raise ValidationError("file list must not be a string", field="changed_files",
                              code="schema_type")
    result: list[str] = []
    seen: set[str] = set()
    for value in paths:
        if not isinstance(value, str) or not value:
            raise ValidationError("file list values must be non-empty strings",
                                  field="changed_files", code="schema_type")
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


class ChangedFilesProvider(Protocol):
    """Trusted source of changed paths relative to a PR's ``files/`` root."""

    def changed_files(self, pr_dir: Path, manifest: Mapping[str, Any]) -> Sequence[str]: ...

    def context_files(self, pr_dir: Path, manifest: Mapping[str, Any]) -> Sequence[str]: ...


class ManifestChangedFilesProvider:
    """Fixture-only provider. Production integrations must use VCS metadata."""

    fixture_only = True

    def changed_files(self, pr_dir: Path, manifest: Mapping[str, Any]) -> Sequence[str]:
        values = manifest.get("changed_files")
        if not isinstance(values, list):
            raise ValidationError("changed_files must be a list", path=pr_dir / "meta.yaml",
                                  field="changed_files", code="schema_type")
        return values

    def context_files(self, pr_dir: Path, manifest: Mapping[str, Any]) -> Sequence[str]:
        values = manifest.get("context_files")
        if not isinstance(values, list):
            raise ValidationError("context_files must be a list", path=pr_dir / "meta.yaml",
                                  field="context_files", code="schema_type")
        return values


class GitChangedFilesProvider:
    """Local Git implementation; no network access and no trust in PR YAML."""

    fixture_only = False

    def __init__(self, repository: str | Path, *, base: str, files_prefix: str = "") -> None:
        if (not isinstance(base, str) or not base.strip() or base.startswith("-")
                or any(character in base for character in ("\x00", "\n", "\r"))):
            raise ValidationError("Git base revision is unsafe", field="base",
                                  code="invalid_diff_config")
        portable_prefix = files_prefix.replace("\\", "/").strip("/")
        if (Path(files_prefix).is_absolute() or ".." in PurePosixPath(portable_prefix).parts
                or any(character in files_prefix for character in ("\x00", "\n", "\r"))):
            raise ValidationError("Git files prefix is unsafe", field="files_prefix",
                                  code="invalid_diff_config")
        self.base = base
        self.files_prefix = portable_prefix
        try:
            raw_repository = os.fspath(repository)
            if any(character in raw_repository for character in ("\x00", "\n", "\r")):
                raise OSError("unsafe repository path")
            self.repository = Path(repository).resolve(strict=True)
        except (OSError, RuntimeError, TypeError) as exc:
            raise ValidationError("Git repository is unavailable", path=str(repository),
                                  code="diff_provider_error") from exc

    @staticmethod
    def _environment() -> dict[str, str]:
        environment = {
            key: value for key, value in os.environ.items() if not key.startswith("GIT_")
        }
        environment.update({
            "HOME": os.devnull,
            "XDG_CONFIG_HOME": os.devnull,
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        })
        return environment

    def _git_bounded(self, arguments: Sequence[str], *, limit: int) -> bytes:
        command = [
            "git", "-c", f"safe.directory={self.repository}", "--no-pager",
            "-c", "core.fsmonitor=false", "--no-replace-objects",
            "-C", str(self.repository), *arguments,
        ]
        try:
            process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=self._environment(),
            )
        except OSError as exc:
            raise ValidationError("trusted Git operation unavailable",
                                  path=self.repository, code="diff_provider_error") from exc

        stdout = bytearray()
        stderr = bytearray()
        exceeded = threading.Event()
        stream_errors: list[BaseException] = []

        def read_stdout() -> None:
            try:
                assert process.stdout is not None
                while chunk := process.stdout.read(65_536):
                    if len(stdout) + len(chunk) > limit:
                        exceeded.set()
                        process.kill()
                        return
                    stdout.extend(chunk)
            except BaseException as exc:  # pragma: no cover - defensive OS boundary
                stream_errors.append(exc)
                process.kill()

        def read_stderr() -> None:
            try:
                assert process.stderr is not None
                while chunk := process.stderr.read(4_096):
                    stderr.extend(chunk)
                    if len(stderr) > 4_096:
                        del stderr[:-4_096]
            except BaseException as exc:  # pragma: no cover - defensive OS boundary
                stream_errors.append(exc)
                process.kill()

        readers = (
            threading.Thread(target=read_stdout, name="aga-legacy-git-stdout", daemon=True),
            threading.Thread(target=read_stderr, name="aga-legacy-git-stderr", daemon=True),
        )
        for reader in readers:
            reader.start()
        try:
            return_code = process.wait(timeout=GIT_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.wait()
            for reader in readers:
                reader.join(timeout=1.0)
            raise ValidationError("trusted Git operation timed out",
                                  path=self.repository, code="diff_provider_error") from exc
        finally:
            if process.poll() is not None:
                for reader in readers:
                    reader.join(timeout=1.0)
                for stream in (process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()
        if exceeded.is_set():
            raise ValidationError("trusted Git diff exceeds byte limit",
                                  path=self.repository, code="diff_provider_error")
        if any(reader.is_alive() for reader in readers) or stream_errors:
            process.kill()
            raise ValidationError("trusted Git output stream failed",
                                  path=self.repository, code="diff_provider_error")
        if return_code != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()[-300:]
            message = "trusted Git operation failed" + (f": {detail}" if detail else "")
            raise ValidationError(message, path=self.repository,
                                  code="diff_provider_error")
        return bytes(stdout)

    def _git_text(self, arguments: Sequence[str]) -> str:
        try:
            return self._git_bounded(arguments, limit=GIT_METADATA_MAX_BYTES).decode(
                "utf-8", errors="strict"
            ).strip()
        except UnicodeDecodeError as exc:
            raise ValidationError("trusted Git metadata is not UTF-8",
                                  path=self.repository, code="diff_provider_error") from exc

    def _validate_worktree(self) -> None:
        try:
            info = self.repository.lstat()
        except OSError as exc:
            raise ValidationError("Git repository is unavailable", path=self.repository,
                                  code="diff_provider_error") from exc
        if not stat.S_ISDIR(info.st_mode) or self.repository.resolve(strict=True) != self.repository:
            raise ValidationError("Git repository must be a real directory",
                                  path=self.repository, code="diff_provider_error")
        top = self._git_text(["rev-parse", "--path-format=absolute", "--show-toplevel"])
        bare = self._git_text(["rev-parse", "--is-bare-repository"])
        inside = self._git_text(["rev-parse", "--is-inside-work-tree"])
        if top != str(self.repository) or bare != "false" or inside != "true":
            raise ValidationError("Git repository must be the exact non-bare worktree root",
                                  path=self.repository, code="diff_provider_error")

    def _resolve_commit(self, revision: str) -> str:
        object_id = self._git_text([
            "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}",
        ])
        if not _GIT_OBJECT_ID_RE.fullmatch(object_id):
            raise ValidationError("Git revision did not resolve to a full commit ID",
                                  path=self.repository, code="diff_provider_error")
        return object_id

    def changed_files(self, pr_dir: Path, manifest: Mapping[str, Any]) -> Sequence[str]:
        try:
            self._validate_worktree()
            base = self._resolve_commit(self.base)
            head = self._resolve_commit("HEAD")
            raw = self._git_bounded([
                "diff", "--name-only", "-z", "--no-ext-diff", "--no-textconv",
                "--no-renames", base, head, "--",
            ], limit=GIT_DIFF_MAX_BYTES)
            if raw and not raw.endswith(b"\0"):
                raise UnicodeDecodeError("utf-8", raw, len(raw) - 1, len(raw),
                                         "unterminated Git path output")
            encoded_paths = raw[:-1].split(b"\0") if raw else []
            if len(encoded_paths) > GIT_DIFF_MAX_PATHS:
                raise ValidationError("trusted Git diff exceeds path count limit",
                                      path=self.repository, code="diff_provider_error")
            paths = [path.decode("utf-8", errors="strict") for path in encoded_paths]
        except UnicodeDecodeError as exc:
            raise ValidationError("trusted Git changed paths are not valid UTF-8",
                                  path=self.repository, code="diff_provider_error") from exc
        if self.files_prefix:
            prefix = self.files_prefix + "/"
            paths = [path[len(prefix):] for path in paths if path.startswith(prefix)]
        return paths

    def context_files(self, pr_dir: Path, manifest: Mapping[str, Any]) -> Sequence[str]:
        # Git diff proves changed paths only. Context must come from a separate
        # trusted repository/VCS adapter; untrusted manifest context is ignored.
        return []


# ---------------------------------------------------------------------------
# PlantUML / Mermaid parsers and graph traversal

AS_CODE_RE = re.compile(r"\b((?:AS|EXT)-\d{4})\b")
ALIAS = r"[A-Za-z_][\w.]*"
PUML_NODE_RE = re.compile(
    rf'^\s*(?:rectangle|component|node|database|actor|package|cloud|queue|system)\s+'
    rf'(?:(?:"([^"]+)"\s+as\s+({ALIAS}))|({ALIAS}))', re.M | re.I)
PUML_EDGE_RE = re.compile(
    rf"^\s*({ALIAS})\s*(?:-+>|\.+>|-+\.+>|\.+-+>)\s*({ALIAS})"
    r"\s*(?::\s*(.*?))?\s*$", re.M)
PUML_C4_RE = re.compile(r"^\s*'\s*c4:\s*(context|container|component|code)\b", re.M | re.I)
MMD_C4_RE = re.compile(r"^\s*%%\s*c4:\s*(context|container|component|code)\b", re.M | re.I)
MMD_NODE_RE = re.compile(
    rf"\s*({ALIAS})(?:\[([^\]]*)\]|\(([^)]*)\)|\{{([^}}]*)\}})?")
MMD_ARROW_RE = re.compile(r"\s*(-->|-\.->|==>)\s*(?:\|([^|]*)\|\s*)?")


def _strip_puml_non_semantic(text: str) -> str:
    text = re.sub(r"/'[\s\S]*?'/", "", text)
    output: list[str] = []
    in_note = False
    in_legend = False
    for line in text.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if in_note:
            if re.match(r"^end\s*note\b", lower):
                in_note = False
            continue
        if in_legend:
            if lower == "endlegend":
                in_legend = False
            continue
        if re.match(r"^note\b", lower):
            # ``note right of A: text`` is a complete single-line note;
            # block notes have no colon and terminate with ``end note``.
            if ":" not in stripped and not re.search(r"\bend\s*note\b", lower):
                in_note = True
            continue
        if lower.startswith("legend"):
            in_legend = True
            continue
        if stripped.startswith("'") or lower.startswith("skinparam"):
            continue
        output.append(line)
    return "\n".join(output)


def _parse_mermaid_line(line: str, nodes: dict[str, str],
                         edges: list[tuple[str, str, str]]) -> bool:
    position = 0
    first = MMD_NODE_RE.match(line, position)
    if not first:
        return False

    def add_node(match: re.Match[str]) -> str:
        alias = match.group(1)
        label = next((value for value in match.groups()[1:] if value is not None), alias)
        if alias not in nodes or nodes[alias] == alias:
            nodes[alias] = label or alias
        return alias

    previous = add_node(first)
    position = first.end()
    found_edge = False
    while True:
        arrow = MMD_ARROW_RE.match(line, position)
        if not arrow:
            break
        target = MMD_NODE_RE.match(line, arrow.end())
        if not target:
            return False
        current = add_node(target)
        edges.append((previous, current, (arrow.group(2) or "").strip()))
        previous = current
        position = target.end()
        found_edge = True
    return bool(found_edge or line[position:].strip() == "")


def parse_diagram(text: str, suffix: str) -> dict[str, Any] | None:
    """Parse the supported, deliberately small PlantUML/Mermaid subset."""
    suffix = suffix.lower()
    if suffix == ".puml":
        if not re.search(r"^\s*@startuml\b", text, re.M | re.I) \
                or not re.search(r"^\s*@enduml\b", text, re.M | re.I):
            return None
        c4_match = PUML_C4_RE.search(text)
        cleaned = _strip_puml_non_semantic(text)
        nodes: dict[str, str] = {}
        for label, alias, bare in PUML_NODE_RE.findall(cleaned):
            if bare:
                nodes[bare] = bare
            else:
                nodes[alias] = label
        edges: list[tuple[str, str, str]] = []
        for source, target, label in PUML_EDGE_RE.findall(cleaned):
            edges.append((source, target, (label or "").strip()))
            nodes.setdefault(source, source)
            nodes.setdefault(target, target)
        if not nodes and not edges:
            return None
        return {"nodes": nodes, "edges": edges,
                "c4_level": c4_match.group(1).lower() if c4_match else None}

    if suffix == ".mmd":
        if not re.search(r"^\s*(?:graph|flowchart)\b", text, re.M | re.I):
            return None
        c4_match = MMD_C4_RE.search(text)
        nodes: dict[str, str] = {}
        edges: list[tuple[str, str, str]] = []
        meaningful = False
        for raw_line in text.splitlines():
            line = raw_line.strip().rstrip(";")
            if not line or line.startswith("%%") or re.match(r"^(?:graph|flowchart)\b", line, re.I):
                continue
            if re.match(r"^(?:classDef|class|style|linkStyle|subgraph|end|direction|click)\b",
                        line, re.I):
                continue
            if _parse_mermaid_line(line, nodes, edges):
                meaningful = True
        if not meaningful or (not nodes and not edges):
            return None
        return {"nodes": nodes, "edges": edges,
                "c4_level": c4_match.group(1).lower() if c4_match else None}
    return None


def node_as_code(label: str | None) -> str | None:
    match = AS_CODE_RE.search(label or "")
    return match.group(1) if match else None


def effective_edges(diagram: Mapping[str, Any],
                    seaf: Mapping[str, Mapping[str, Any]]) -> set[tuple[str, str]]:
    """Collapse arbitrarily long infrastructure paths using cycle-safe DFS."""
    code_of = {alias: node_as_code(label) for alias, label in diagram["nodes"].items()}

    def is_infrastructure(alias: str) -> bool:
        code = code_of.get(alias)
        if not code or code not in seaf:
            return False
        value = seaf[code].get("infra")
        if not isinstance(value, bool):
            raise ValidationError("SEAF infra must be boolean", field=f"systems.{code}.infra",
                                  code="schema_type")
        return value

    adjacency: dict[str, list[str]] = {}
    for source, target, _ in diagram["edges"]:
        adjacency.setdefault(source, []).append(target)
    result: set[tuple[str, str]] = set()
    for start in diagram["nodes"]:
        if not code_of.get(start) or is_infrastructure(start):
            continue
        stack = list(adjacency.get(start, []))
        seen = {start}
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            code = code_of.get(current)
            if code and not is_infrastructure(current):
                result.add((code_of[start], code))
            elif is_infrastructure(current):
                stack.extend(adjacency.get(current, []))
    return result


# ---------------------------------------------------------------------------
# Exception DSL, detector registry and canonical findings

def _nested_value(metadata: Mapping[str, Any], dotted_field: str) -> Any:
    value: Any = metadata
    for part in dotted_field.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    return value


def condition_matches(condition: Mapping[str, Any], metadata: Mapping[str, Any]) -> bool:
    if "all" in condition:
        return all(condition_matches(item, metadata) for item in condition["all"])
    if "any" in condition:
        return any(condition_matches(item, metadata) for item in condition["any"])
    actual = _nested_value(metadata, condition["field"])
    if "equals" in condition:
        return actual == condition["equals"]
    if "contains" in condition:
        expected = condition["contains"]
        return isinstance(actual, (list, tuple, set, str)) and expected in actual
    if "in" in condition:
        return actual in condition["in"]
    return False


def exception_matches(rule: Mapping[str, Any], metadata: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for exception in rule.get("exceptions", []):
        if condition_matches(exception["when"], metadata):
            return exception
    return None


@dataclass(frozen=True)
class Detection:
    evidence: str
    location: str = ""
    canonical_defect: str = ""


@dataclass
class DetectorContext:
    artifact: str
    kind: str
    metadata: dict[str, Any]
    body: str
    text: str
    diagram: dict[str, Any] | None
    seaf: dict[str, dict[str, Any]]
    diagrams: dict[str, dict[str, Any] | None]
    flows: list[dict[str, Any]]
    declared_flows: set[tuple[str, str]]


Detector = Any


def _detect_field_required(argument: Any, ctx: DetectorContext) -> list[Detection]:
    field = str(argument)
    return [] if ctx.metadata.get(field) else [Detection(f"поле {field} отсутствует или пусто", "frontmatter")]


def _detect_field_banned(argument: Any, ctx: DetectorContext) -> list[Detection]:
    field = argument.get("field")
    values = argument.get("values")
    if not isinstance(field, str) or not isinstance(values, list):
        raise ValidationError("field_banned requires field and values", field="detect",
                              code="invalid_detect")
    value = ctx.metadata.get(field)
    if value in values:
        return [Detection(f"{field}: {value} — значение запрещено правилом",
                          f"frontmatter: {field}", f"banned:{field}:{value}")]
    return []


def _detect_required_fields(argument: Any, ctx: DetectorContext) -> list[Detection]:
    if not isinstance(argument, list):
        raise ValidationError("required_fields requires a list", field="detect",
                              code="invalid_detect")
    missing = [str(field) for field in argument if not ctx.metadata.get(field)]
    return ([Detection(f"не заполнено: {', '.join(missing)}", "frontmatter",
                       "missing_fields:" + ",".join(missing))] if missing else [])


def _detect_field_matches_registry(argument: Any, ctx: DetectorContext) -> list[Detection]:
    field = str(argument)
    record = ctx.seaf.get(ctx.metadata.get("id"))
    if not record or not ctx.metadata.get(field):
        return []
    if ctx.metadata[field] != record.get(field):
        return [Detection(f"{field} «{ctx.metadata[field]}» ≠ SEAF «{record.get(field)}»",
                          f"frontmatter: {field}", f"registry_mismatch:{field}")]
    return []


def _detect_systems_must_exist(argument: Any, ctx: DetectorContext) -> list[Detection]:
    if not isinstance(argument, list):
        raise ValidationError("systems_must_exist requires fields list", field="detect",
                              code="invalid_detect")
    missing = [str(ctx.metadata.get(field)) for field in argument
               if ctx.metadata.get(field) and ctx.metadata.get(field) not in ctx.seaf]
    return ([Detection(f"нет в реестре SEAF: {', '.join(missing)}", "frontmatter",
                       "unknown_system:" + ",".join(missing))] if missing else [])


def _detect_endpoint_status(argument: Any, ctx: DetectorContext) -> list[Detection]:
    forbidden = str(argument)
    bad = [ctx.metadata.get(field) for field in ("source", "target")
           if ctx.seaf.get(ctx.metadata.get(field), {}).get("target_status") == forbidden]
    return ([Detection(f"конечная точка с target_status={forbidden}: {', '.join(bad)}",
                       "frontmatter", f"endpoint_status:{forbidden}:{','.join(bad)}")]
            if bad else [])


def _detect_pdn_approval(argument: Any, ctx: DetectorContext) -> list[Detection]:
    approval = str(argument)
    categories = ctx.metadata.get("data_categories") or []
    approvals = ctx.metadata.get("approvals") or []
    if "pdn" in categories and ctx.metadata.get("zone") == "external" and approval not in approvals:
        return [Detection(f"ПДн в зону external без согласования {approval.upper()}",
                          "frontmatter", f"pdn_external:{approval}")]
    return []


def _detect_required_sections(argument: Any, ctx: DetectorContext) -> list[Detection]:
    if not isinstance(argument, list):
        raise ValidationError("required_sections requires a list", field="detect",
                              code="invalid_detect")
    missing = [section for section in argument
               if not re.search(rf"^##\s+{re.escape(str(section))}\b", ctx.body, re.M)]
    return ([Detection(f"нет секций: {', '.join(map(str, missing))}", "body",
                       "missing_sections:" + ",".join(map(str, missing)))] if missing else [])


def _detect_field_vocab(argument: Any, ctx: DetectorContext) -> list[Detection]:
    if not isinstance(argument, Mapping) or not isinstance(argument.get("vocab"), list):
        raise ValidationError("field_in_vocab requires field and vocab", field="detect",
                              code="invalid_detect")
    field = argument.get("field")
    value = ctx.metadata.get(field)
    if value not in argument["vocab"]:
        return [Detection(f"{field} «{value}» вне словаря", f"frontmatter: {field}",
                          f"vocab:{field}:{value}")]
    return []


def _detect_systems_field(argument: Any, ctx: DetectorContext) -> list[Detection]:
    field = str(argument)
    ghosts = [system for system in (ctx.metadata.get(field) or []) if system not in ctx.seaf]
    return ([Detection(f"систем нет в SEAF: {', '.join(ghosts)}", "frontmatter",
                       "unknown_system:" + ",".join(ghosts))] if ghosts else [])


def _detect_parseable(argument: Any, ctx: DetectorContext) -> list[Detection]:
    return ([Detection("диаграмма не разбирается парсером", "diagram", "diagram_parse")]
            if argument and ctx.diagram is None else [])


def _detect_node_pattern(argument: Any, ctx: DetectorContext) -> list[Detection]:
    if ctx.diagram is None:
        return []
    try:
        pattern = re.compile(str(argument))
    except re.error as exc:
        raise ValidationError(f"invalid node label regex: {exc}", field="detect",
                              code="invalid_detect") from exc
    unnamed = [label for label in ctx.diagram["nodes"].values() if not pattern.search(label)]
    return ([Detection(f"узлы без кода АС: {', '.join(unnamed)}", "diagram",
                       "unnamed_nodes:" + ",".join(sorted(unnamed)))] if unnamed else [])


def _detect_c4(argument: Any, ctx: DetectorContext) -> list[Detection]:
    if ctx.diagram is not None and argument and not ctx.diagram["c4_level"]:
        return [Detection("уровень C4 не декларирован (комментарий c4:)", "diagram",
                          "missing_c4_level")]
    return []


def _detect_edges_labeled(argument: Any, ctx: DetectorContext) -> list[Detection]:
    if ctx.diagram is None or not argument:
        return []
    unlabeled = [f"{source}→{target}" for source, target, label in ctx.diagram["edges"] if not label]
    return ([Detection(f"связи без подписи: {', '.join(unlabeled)}", "diagram",
                       "unlabeled_edges:" + ",".join(sorted(unlabeled)))] if unlabeled else [])


def _detect_no_orphans(argument: Any, ctx: DetectorContext) -> list[Detection]:
    if ctx.diagram is None or not argument:
        return []
    linked = {node for edge in ctx.diagram["edges"] for node in edge[:2]}
    orphans = [label for alias, label in ctx.diagram["nodes"].items() if alias not in linked]
    return ([Detection(f"изолированные узлы: {', '.join(orphans)}", "diagram",
                       "orphan_nodes:" + ",".join(sorted(orphans)))] if orphans else [])


def _detect_flow_on_diagram(argument: Any, ctx: DetectorContext) -> list[Detection]:
    if not argument or not ctx.diagrams or not ctx.metadata.get("source") or not ctx.metadata.get("target"):
        return []
    covered = any((ctx.metadata["source"], ctx.metadata["target"]) in effective_edges(diagram, ctx.seaf)
                  for diagram in ctx.diagrams.values() if diagram is not None)
    if not covered:
        source, target = ctx.metadata["source"], ctx.metadata["target"]
        return [Detection(f"поток {source}→{target} не отражён на диаграмме", "diagram",
                          f"flow_not_on_diagram:{source}:{target}")]
    return []


def _detect_edges_covered(argument: Any, ctx: DetectorContext) -> list[Detection]:
    if ctx.diagram is None or not argument or not ctx.flows:
        return []
    extra = [f"{source}→{target}" for source, target in effective_edges(ctx.diagram, ctx.seaf)
             if (source, target) not in ctx.declared_flows]
    return ([Detection(f"связи без заявленного потока: {', '.join(extra)}", "diagram",
                       "edge_without_flow:" + ",".join(sorted(extra)))] if extra else [])


DETECTORS: dict[str, Detector] = {
    "field_required": _detect_field_required,
    "field_banned": _detect_field_banned,
    "required_fields": _detect_required_fields,
    "field_matches_registry": _detect_field_matches_registry,
    "systems_must_exist": _detect_systems_must_exist,
    "no_endpoint_with_target_status": _detect_endpoint_status,
    "pdn_external_requires_approval": _detect_pdn_approval,
    "required_sections": _detect_required_sections,
    "field_in_vocab": _detect_field_vocab,
    "systems_field_must_exist": _detect_systems_field,
    "parseable": _detect_parseable,
    "node_label_pattern": _detect_node_pattern,
    "c4_level_declared": _detect_c4,
    "edges_labeled": _detect_edges_labeled,
    "no_orphan_nodes": _detect_no_orphans,
    "flow_present_on_diagram": _detect_flow_on_diagram,
    "edges_covered_by_flows": _detect_edges_covered,
}


def _finding(rule: Mapping[str, Any], artifact: str, detection: Detection) -> dict[str, Any]:
    return {
        "rule_id": rule["id"],
        "severity": rule["severity"],
        "confidence": 1.0,
        "artifact": artifact,
        "location": detection.location,
        "evidence": detection.evidence,
        "canonical_defect": detection.canonical_defect or detection.evidence,
        "source_ref": rule["source_ref"],
        "suggested_fix": "",
        "execution_mode": "deterministic",
    }


FINDING_PRECEDENCE = {"SEAF-004": {"PRIN-006"}}


def _same_finding_defect(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    if left.get("artifact") != right.get("artifact"):
        return False
    left_canonical = left.get("canonical_defect")
    right_canonical = right.get("canonical_defect")
    if left_canonical and right_canonical and left_canonical == right_canonical:
        return True
    left_location = left.get("location")
    right_location = right.get("location")
    if left_location and right_location and left_location == right_location:
        return True
    return (not left_location and not right_location
            and left.get("evidence") == right.get("evidence"))


def deduplicate_findings(findings: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for raw in findings:
        finding = dict(raw)
        key = (finding.get("rule_id"), finding.get("severity"), finding.get("artifact"),
               finding.get("location"), finding.get("canonical_defect") or finding.get("evidence"))
        if key not in seen:
            seen.add(key)
            unique.append(finding)
    for winner, losers in FINDING_PRECEDENCE.items():
        winners = [item for item in unique if item.get("rule_id") == winner]
        unique = [item for item in unique
                  if not (item.get("rule_id") in losers
                          and any(_same_finding_defect(specific, item)
                                  for specific in winners))]
    return unique


def verdict_from(findings: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]) -> str:
    verdict_policy = policy["verdict_policy"]
    severities = {finding["severity"] for finding in findings}
    if "blocker" in severities:
        return verdict_policy["has_blocker"]
    if "major" in severities:
        return verdict_policy["has_major"]
    if "minor" in severities:
        return verdict_policy["minor_only"]
    return verdict_policy["none"]


# ---------------------------------------------------------------------------
# Review orchestration

def _validate_manifest(manifest: Any, path: Path) -> dict[str, Any]:
    return validate_manifest(manifest, path=path)


def _validate_artifact_metadata(kind: str, metadata: Mapping[str, Any], relative: str) -> None:
    validate_review_frontmatter(metadata, expected_kind=kind, path=relative)


def _input_error_result(pr_dir: Path, error: ValidationError,
                        *, manifest: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "pr": (manifest or {}).get("id", pr_dir.name),
        "title": (manifest or {}).get("title", ""),
        "findings": [],
        "deterministic_findings": [],
        "suppressed_by_exception": [],
        "skipped_llm_rules": [],
        "observations": [],
        "input_errors": [error.as_dict()],
        "analysis_errors": [],
        "reviewed_files": [],
        "context_files": [],
        "verdict": "input_error",
        "escalate": True,
        "incomplete": True,
    }


def review_pr(pr_dir: str | Path, rules_dir: str | Path | None = None,
              seaf_path: str | Path | None = None, *,
              changed_files_provider: ChangedFilesProvider | None = None,
              include_candidates: bool = False) -> dict[str, Any]:
    """Run deterministic review and fail closed on every input error.

    Semantic findings are accepted only by the separately validated
    ``scripts.run_review.execute_review`` boundary.  Keeping this core entry
    point deterministic prevents callers from injecting pre-built findings.
    """
    directory = Path(pr_dir)
    manifest: dict[str, Any] | None = None
    try:
        if directory.is_symlink() or not directory.is_dir():
            raise ValidationError("PR directory must be a real directory", path=directory,
                                  code="unsafe_path")
        manifest_path = directory / "meta.yaml"
        manifest = _validate_manifest(strict_load_yaml(manifest_path, expected_type=dict), manifest_path)
        provider = changed_files_provider
        if provider is None:
            golden_root = (PKG_ROOT / "golden" / "prs").resolve()
            try:
                directory.resolve().relative_to(golden_root)
            except ValueError as exc:
                raise ValidationError(
                    "a trusted ChangedFilesProvider is required outside golden fixtures",
                    path=directory, field="changed_files", code="trusted_diff_required") from exc
            provider = ManifestChangedFilesProvider()
        changed = _deduplicate_paths(provider.changed_files(directory, manifest))
        context_getter = getattr(provider, "context_files", None)
        context_values = context_getter(directory, manifest) if callable(context_getter) else []
        context = _deduplicate_paths(context_values)
        context = [path for path in context if path not in set(changed)]
        rules, policy = load_rules(rules_dir, include_candidates=include_candidates)
        seaf = load_seaf(seaf_path)
        files_root = directory / "files"
        if files_root.is_symlink() or not files_root.is_dir():
            raise ValidationError("files root must be a real directory", path=files_root,
                                  code="unsafe_path")

        records: dict[str, dict[str, Any]] = {}
        for relative in changed + context:
            text = safe_read_artifact(files_root, relative,
                                      allowed_extensions=ARTIFACT_EXTENSIONS,
                                      reject_symlinks=True, reject_hardlinks=True)
            path_kind = _path_kind(relative)
            if Path(relative).suffix == ".md":
                metadata, body = parse_frontmatter(text, source=relative)
            else:
                metadata, body = {}, text
            kind = classify(relative, metadata, strict=True)
            if kind != path_kind:
                raise ValidationError("artifact kind/path mismatch", path=relative,
                                      field="kind", code="kind_path_conflict")
            _validate_artifact_metadata(kind, metadata, relative)
            diagram = parse_diagram(text, Path(relative).suffix) if kind == "diagram" else None
            records[relative] = {"metadata": metadata, "body": body, "text": text,
                                 "kind": kind, "diagram": diagram}

        flows = [record["metadata"] for record in records.values()
                 if record["kind"] == "integration_flow"]
        declared_flows = {(flow["source"], flow["target"]) for flow in flows}
        diagrams = {relative: record["diagram"] for relative, record in records.items()
                    if record["kind"] == "diagram"}

        deterministic: list[dict[str, Any]] = []
        suppressed: list[dict[str, Any]] = []
        for relative in changed:
            record = records[relative]
            context_object = DetectorContext(
                artifact=relative, kind=record["kind"], metadata=record["metadata"],
                body=record["body"], text=record["text"], diagram=record["diagram"],
                seaf=seaf, diagrams=diagrams, flows=flows, declared_flows=declared_flows)
            for rule in rules:
                if record["kind"] not in rule["scope"] or rule["check_type"] not in {"deterministic", "hybrid"}:
                    continue
                operator, argument = _normalise_detect(rule["detect"], path=Path(relative), field="detect")
                detector = DETECTORS[operator]
                detections = detector(argument, context_object)
                for detection in detections:
                    exception = exception_matches(rule, record["metadata"])
                    if exception:
                        suppressed.append({
                            "rule_id": rule["id"], "artifact": relative,
                            "exception": exception["id"], "provenance": exception["provenance"],
                            "canonical_defect": detection.canonical_defect or detection.evidence,
                        })
                    else:
                        deterministic.append(_finding(rule, relative, detection))

        findings = deduplicate_findings(deterministic)
        skipped = sorted(rule["id"] for rule in rules if rule["check_type"] in {"llm", "hybrid"})
        verdict = verdict_from(findings, policy)
        return {
            "pr": manifest["id"], "title": manifest["title"],
            "findings": findings, "deterministic_findings": deduplicate_findings(deterministic),
            "suppressed_by_exception": suppressed, "skipped_llm_rules": skipped,
            "observations": [], "input_errors": [], "analysis_errors": [],
            "reviewed_files": changed, "context_files": context,
            "artifact_snapshot_sha256": {
                relative: hashlib.sha256(record["text"].encode("utf-8")).hexdigest()
                for relative, record in records.items()
            },
            "verdict": verdict,
            "escalate": verdict == "request_changes_escalate",
            "incomplete": False,
        }
    except ValidationError as error:
        return _input_error_result(directory, error, manifest=manifest)
    except (OSError, UnicodeError) as error:
        wrapped = ValidationError(str(error), path=getattr(error, "filename", directory),
                                  code="input_io_error")
        return _input_error_result(directory, wrapped, manifest=manifest)


# ---------------------------------------------------------------------------
# Ouroboros adapter. External API signatures stay explicit and failures surface.

class RegistrationError(RuntimeError):
    pass


def _safe_tool_path(ctx: Any, value: str, *, directory: bool,
                    extensions: set[str] | None = None) -> Path:
    root = Path(getattr(ctx, "workspace_root", PKG_ROOT)).resolve(strict=True)
    if not directory:
        return safe_artifact_path(
            root, value, allowed_extensions=extensions,
            reject_symlinks=True, reject_hardlinks=True)
    raw = Path(value)
    if raw.is_absolute() or ".." in PurePosixPath(value.replace("\\", "/")).parts:
        raise ValidationError("tool path must be contained and relative", path=value,
                              code="unsafe_path")
    candidate = root / raw
    current = root
    for part in raw.parts:
        current = current / part
        if current.is_symlink():
            raise ValidationError("symlink path component is forbidden", path=value,
                                  code="path_symlink")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValidationError("tool path resolves outside workspace", path=value,
                              code="path_outside_root") from exc
    if directory and not resolved.is_dir():
        raise ValidationError("tool path must be a directory", path=value,
                              code="path_not_directory")
    return resolved


def tool_aga_review_pr(ctx: Any, pr_dir: str, rules_dir: str | None = None,
                       seaf_path: str | None = None) -> str:
    try:
        safe_pr = _safe_tool_path(ctx, pr_dir, directory=True)
        safe_rules = _safe_tool_path(ctx, rules_dir, directory=True) if rules_dir else None
        safe_seaf = (_safe_tool_path(ctx, seaf_path, directory=False,
                                     extensions={".yaml", ".yml"}) if seaf_path else None)
        result = review_pr(safe_pr, safe_rules, safe_seaf)
    except (ValidationError, OSError) as error:
        typed = error if isinstance(error, ValidationError) else ValidationError(
            str(error), path=pr_dir, code="input_io_error")
        result = _input_error_result(Path(pr_dir), typed)
    return json.dumps(result, ensure_ascii=False, indent=2)


def tool_aga_parse_diagram(ctx: Any, path: str) -> str:
    root = Path(getattr(ctx, "workspace_root", PKG_ROOT))
    try:
        text = safe_read_artifact(root, path, allowed_extensions={".puml", ".mmd"},
                                  reject_symlinks=True, reject_hardlinks=True)
        parsed = parse_diagram(text, Path(path).suffix)
        return json.dumps(parsed if parsed else {"error": "parse_failed"}, ensure_ascii=False)
    except ValidationError as error:
        return json.dumps({"error": error.as_dict()}, ensure_ascii=False)


def tool_aga_seaf_lookup(ctx: Any, system_id: str, seaf_path: str | None = None) -> str:
    try:
        safe_seaf = (_safe_tool_path(ctx, seaf_path, directory=False,
                                     extensions={".yaml", ".yml"}) if seaf_path else None)
        record = load_seaf(safe_seaf).get(system_id)
        return json.dumps(record or {"error": f"{system_id} not found"}, ensure_ascii=False)
    except ValidationError as error:
        return json.dumps({"error": error.as_dict()}, ensure_ascii=False)


TOOL_DEFS = [
    {"name": "aga_review_pr",
     "description": "AGA deterministic Architecture-as-Code review.",
     "parameters": {"type": "object", "properties": {
         "pr_dir": {"type": "string"}, "rules_dir": {"type": "string"},
         "seaf_path": {"type": "string"}}, "required": ["pr_dir"]}},
    {"name": "aga_parse_diagram", "description": "Parse a safe PlantUML/Mermaid artifact.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}},
                    "required": ["path"]}},
    {"name": "aga_seaf_lookup", "description": "Read one system from the validated SEAF fixture.",
     "parameters": {"type": "object", "properties": {"system_id": {"type": "string"}},
                    "required": ["system_id"]}},
]

HANDLERS = {
    "aga_review_pr": tool_aga_review_pr,
    "aga_parse_diagram": tool_aga_parse_diagram,
    "aga_seaf_lookup": tool_aga_seaf_lookup,
}


def register(registry: Any) -> list[str]:
    """Register tools or fail diagnostically on an incompatible registry API."""
    registered: list[str] = []
    for definition in TOOL_DEFS:
        try:
            registry.register(definition["name"], definition, HANDLERS[definition["name"]])
        except (TypeError, AttributeError) as error:
            raise RegistrationError(
                f"Ouroboros registry API is incompatible while registering {definition['name']}: {error}"
            ) from error
        registered.append(definition["name"])
    return registered
