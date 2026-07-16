# -*- coding: utf-8 -*-
"""Strict input validation and file-boundary helpers for AGA.

This module is deliberately independent from :mod:`tools.aga`: callers can
adopt the security boundary without creating an import cycle.  It uses only
the standard library and PyYAML.

Public functions either return validated (and, where documented, normalised)
data or raise :class:`ValidationError`.  No malformed input is converted to an
empty mapping and no filesystem error is silently ignored.
"""
from __future__ import annotations

import datetime as _datetime
import math
import os
import re
import stat
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import yaml
from yaml.events import AliasEvent
from yaml.nodes import MappingNode


DEFAULT_MAX_YAML_BYTES = 1_048_576
DEFAULT_MAX_ARTIFACT_BYTES = 1_048_576
DEFAULT_MAX_ALIASES = 50
DEFAULT_MAX_YAML_DEPTH = 40
DEFAULT_MAX_YAML_NODES = 100_000
DEFAULT_ARTIFACT_EXTENSIONS = frozenset(
    {".md", ".puml", ".mmd", ".yaml", ".yml", ".json", ".txt"}
)

KNOWN_KINDS = frozenset(
    {"system_passport", "integration_flow", "adr", "diagram", "out_of_scope"}
)
SEVERITIES = frozenset({"blocker", "major", "minor"})
RULE_STATUSES = frozenset({"active", "candidate", "deprecated"})
CHECK_TYPES = frozenset({"deterministic", "llm", "hybrid"})
CRITICALITIES = frozenset(
    {"mission_critical", "business_critical", "business_operational", "office"}
)
TARGET_STATUSES = frozenset({"invest", "tolerate", "migrate", "eliminate"})
FLOW_PATTERNS = frozenset({"api_gateway", "esb", "mq", "file", "direct_db"})
FLOW_ZONES = frozenset({"internal", "dmz", "external"})
TRANSFER_MODES = frozenset({"batch", "realtime", "streaming", "interactive"})
ADR_STATUSES = frozenset({"proposed", "accepted", "deprecated", "superseded"})
VERDICTS = frozenset({"approve", "approve_with_warnings", "request_changes_escalate"})

# Operators currently represented in rules/*.yaml plus canonical aliases used
# by the rules-driven dispatcher described in the remediation contract.
SUPPORTED_DETECT_OPERATORS = frozenset(
    {
        "field_required",
        "field_banned",
        "required_fields",
        "field_matches_registry",
        "systems_must_exist",
        "systems_field_must_exist",
        "no_endpoint_with_target_status",
        "endpoint_target_status_forbidden",
        "pdn_external_requires_approval",
        "required_sections",
        "field_in_vocab",
        "parseable",
        "diagram_parseable",
        "node_label_pattern",
        "c4_level_declared",
        "edges_labeled",
        "diagram_edges_labeled",
        "no_orphan_nodes",
        "diagram_no_orphans",
        "flow_present_on_diagram",
        "edges_covered_by_flows",
    }
)
RULE_DOCUMENT_DOMAINS = {
    "principles.yaml": "principles",
    "seaf-checks.yaml": "seaf",
    "diagram-checks.yaml": "diagram",
    "adr-checks.yaml": "adr",
}


class ValidationError(ValueError):
    """A stable, serialisable validation failure.

    ``path`` names the source document/artifact, ``field`` is a dotted/indexed
    schema path, and ``code`` is intended for programmatic handling.
    """

    def __init__(
        self,
        message: str,
        *,
        path: str | os.PathLike[str] | None = None,
        field: str | None = None,
        code: str = "validation_error",
    ) -> None:
        self.message = str(message)
        self.path = str(path) if path is not None else None
        self.field = field
        self.code = code
        details = []
        if self.path:
            details.append(self.path)
        if self.field:
            details.append(self.field)
        where = f" ({': '.join(details)})" if details else ""
        super().__init__(f"[{self.code}] {self.message}{where}")

    def as_dict(self) -> dict[str, Any]:
        """Return the structured ``input_error`` representation used by AGA."""

        return {
            "type": "input_error",
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "field": self.field,
        }

    to_dict = as_dict


class _DuplicateKeyError(yaml.YAMLError):
    def __init__(self, key: Any, mark: Any) -> None:
        self.key = key
        self.problem_mark = mark
        super().__init__(f"duplicate mapping key: {key!r}")


class _YamlLimitError(yaml.YAMLError):
    def __init__(self, code: str, message: str, mark: Any = None) -> None:
        self.code = code
        self.problem = message
        self.problem_mark = mark
        super().__init__(message)


class _StrictSafeLoader(yaml.SafeLoader):
    """SafeLoader with duplicate-key, alias, depth and node limits."""

    def __init__(
        self,
        stream: str,
        *,
        max_aliases: int,
        max_depth: int,
        max_nodes: int,
    ) -> None:
        self._max_aliases = max_aliases
        self._max_depth = max_depth
        self._max_nodes = max_nodes
        self._alias_count = 0
        self._compose_depth = 0
        self._node_count = 0
        super().__init__(stream)

    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(AliasEvent):
            self._alias_count += 1
            if self._alias_count > self._max_aliases:
                event = self.peek_event()
                raise _YamlLimitError(
                    "yaml_alias_limit",
                    f"YAML alias limit exceeded ({self._max_aliases})",
                    getattr(event, "start_mark", None),
                )
        self._node_count += 1
        if self._node_count > self._max_nodes:
            event = self.peek_event()
            raise _YamlLimitError(
                "yaml_node_limit",
                f"YAML node limit exceeded ({self._max_nodes})",
                getattr(event, "start_mark", None),
            )
        self._compose_depth += 1
        if self._compose_depth > self._max_depth:
            event = self.peek_event()
            self._compose_depth -= 1
            raise _YamlLimitError(
                "yaml_depth_limit",
                f"YAML nesting depth limit exceeded ({self._max_depth})",
                getattr(event, "start_mark", None),
            )
        try:
            return super().compose_node(parent, index)
        finally:
            self._compose_depth -= 1

    def construct_mapping(self, node: Any, deep: bool = False) -> dict[Any, Any]:
        if not isinstance(node, MappingNode):
            return super().construct_mapping(node, deep=deep)
        # Expanding merge keys before checking prevents ``<<`` from hiding an
        # explicit duplicate/override.
        self.flatten_mapping(node)
        result: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in result
            except TypeError as exc:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found an unhashable mapping key",
                    key_node.start_mark,
                ) from exc
            if duplicate:
                raise _DuplicateKeyError(key, key_node.start_mark)
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def _field(base: str | None, key: str | int) -> str:
    if isinstance(key, int):
        return f"{base or '$'}[{key}]"
    return f"{base}.{key}" if base else str(key)


def _line_field(mark: Any) -> str | None:
    if mark is None:
        return None
    return f"line {mark.line + 1}, column {mark.column + 1}"


def _check_loaded_structure(value: Any, *, source: str, max_depth: int) -> None:
    """Reject recursive aliases and measure graph depth in linear time.

    Memoisation is important here: recursively walking every alias reference
    can itself turn a small alias DAG into exponential validation work.
    """

    visiting: set[int] = set()
    depths: dict[int, int] = {}

    def measure(item: Any) -> int:
        if not isinstance(item, (dict, list)):
            return 0
        identity = id(item)
        if identity in visiting:
            raise ValidationError(
                "recursive YAML alias is not allowed",
                path=source,
                code="yaml_recursive_alias",
            )
        if identity in depths:
            return depths[identity]
        visiting.add(identity)
        values = item.values() if isinstance(item, dict) else item
        depth = 1 + max((measure(child) for child in values), default=0)
        visiting.remove(identity)
        depths[identity] = depth
        return depth

    if measure(value) > max_depth:
        raise ValidationError(
            f"YAML nesting depth limit exceeded ({max_depth})",
            path=source,
            code="yaml_depth_limit",
        )


def _type_name(expected_type: type | tuple[type, ...]) -> str:
    types = expected_type if isinstance(expected_type, tuple) else (expected_type,)
    return " or ".join(t.__name__ for t in types)


def strict_load_yaml_text(
    text: str | bytes,
    *,
    source: str | os.PathLike[str] = "<memory>",
    expected_type: type | tuple[type, ...] | None = dict,
    max_bytes: int = DEFAULT_MAX_YAML_BYTES,
    max_aliases: int = DEFAULT_MAX_ALIASES,
    max_depth: int = DEFAULT_MAX_YAML_DEPTH,
    max_nodes: int = DEFAULT_MAX_YAML_NODES,
) -> Any:
    """Safely load one YAML document with strict resource/schema boundaries."""

    source_name = str(source)
    if isinstance(text, bytes):
        raw = text
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValidationError(
                "YAML is not valid UTF-8",
                path=source_name,
                field=f"byte {exc.start}",
                code="invalid_encoding",
            ) from exc
    elif isinstance(text, str):
        try:
            raw = text.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValidationError(
                "YAML text cannot be encoded as UTF-8",
                path=source_name,
                field=f"character {exc.start}",
                code="invalid_encoding",
            ) from exc
    else:
        raise ValidationError(
            "YAML input must be str or bytes",
            path=source_name,
            code="invalid_type",
        )
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 0:
        raise ValueError("max_bytes must be a non-negative integer")
    if len(raw) > max_bytes:
        raise ValidationError(
            f"YAML exceeds size limit ({max_bytes} bytes)",
            path=source_name,
            code="file_too_large",
        )
    for name, value in (
        ("max_aliases", max_aliases),
        ("max_depth", max_depth),
        ("max_nodes", max_nodes),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")

    loader = _StrictSafeLoader(
        text,
        max_aliases=max_aliases,
        max_depth=max_depth,
        max_nodes=max_nodes,
    )
    try:
        data = loader.get_single_data()
    except _DuplicateKeyError as exc:
        location = _line_field(exc.problem_mark)
        raise ValidationError(
            f"duplicate YAML mapping key {exc.key!r}"
            + (f" at {location}" if location else ""),
            path=source_name,
            field=str(exc.key),
            code="yaml_duplicate_key",
        ) from exc
    except _YamlLimitError as exc:
        raise ValidationError(
            exc.problem,
            path=source_name,
            field=_line_field(exc.problem_mark),
            code=exc.code,
        ) from exc
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        problem = getattr(exc, "problem", None) or str(exc)
        raise ValidationError(
            f"malformed YAML: {problem}",
            path=source_name,
            field=_line_field(mark),
            code="yaml_parse_error",
        ) from exc
    finally:
        loader.dispose()

    _check_loaded_structure(data, source=source_name, max_depth=max_depth)
    if expected_type is not None and not isinstance(data, expected_type):
        raise ValidationError(
            f"YAML root must be {_type_name(expected_type)}, got {type(data).__name__}",
            path=source_name,
            field="$",
            code="yaml_root_type",
        )
    return data


def _read_file_limited(
    path: Path,
    *,
    max_bytes: int,
    reject_symlinks: bool,
) -> bytes:
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise ValidationError(
            "file does not exist", path=path, code="file_not_found"
        ) from exc
    except OSError as exc:
        raise ValidationError(
            f"cannot inspect file: {exc}", path=path, code="file_access_error"
        ) from exc
    if reject_symlinks and stat.S_ISLNK(info.st_mode):
        raise ValidationError("symlink is not allowed", path=path, code="path_symlink")
    if not reject_symlinks and stat.S_ISLNK(info.st_mode):
        try:
            info = path.stat()
        except OSError as exc:
            raise ValidationError(
                f"cannot inspect symlink target: {exc}",
                path=path,
                code="file_access_error",
            ) from exc
    if not stat.S_ISREG(info.st_mode):
        raise ValidationError("path is not a regular file", path=path, code="path_not_regular")
    if info.st_size > max_bytes:
        raise ValidationError(
            f"file exceeds size limit ({max_bytes} bytes)",
            path=path,
            code="file_too_large",
        )
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if reject_symlinks:
        flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValidationError(
            f"cannot open file safely: {exc}", path=path, code="file_access_error"
        ) from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ValidationError(
                "opened path is not a regular file", path=path, code="path_not_regular"
            )
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            raise ValidationError(
                "file changed during validation", path=path, code="file_race"
            )
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > max_bytes:
            raise ValidationError(
                f"file exceeds size limit ({max_bytes} bytes)",
                path=path,
                code="file_too_large",
            )
        return raw
    finally:
        os.close(descriptor)


def strict_load_yaml(
    path: str | os.PathLike[str],
    *,
    expected_type: type | tuple[type, ...] | None = dict,
    max_bytes: int = DEFAULT_MAX_YAML_BYTES,
    max_aliases: int = DEFAULT_MAX_ALIASES,
    max_depth: int = DEFAULT_MAX_YAML_DEPTH,
    max_nodes: int = DEFAULT_MAX_YAML_NODES,
    reject_symlinks: bool = True,
) -> Any:
    """Load a UTF-8 YAML file without following a leaf symlink."""

    source = Path(path)
    raw = _read_file_limited(source, max_bytes=max_bytes, reject_symlinks=reject_symlinks)
    return strict_load_yaml_text(
        raw,
        source=source,
        expected_type=expected_type,
        max_bytes=max_bytes,
        max_aliases=max_aliases,
        max_depth=max_depth,
        max_nodes=max_nodes,
    )


def _normalise_extensions(allowed_extensions: Iterable[str] | None) -> frozenset[str] | None:
    if allowed_extensions is None:
        return None
    if isinstance(allowed_extensions, (str, bytes)):
        raise ValueError("allowed_extensions must be an iterable of extensions")
    result = set()
    for extension in allowed_extensions:
        if not isinstance(extension, str) or not extension:
            raise ValueError("each allowed extension must be a non-empty string")
        result.add((extension if extension.startswith(".") else f".{extension}").lower())
    return frozenset(result)


def _relative_parts(relative_path: str | os.PathLike[str], *, source: str | None = None) -> tuple[str, ...]:
    if not isinstance(relative_path, (str, os.PathLike)):
        raise ValidationError(
            "artifact path must be a string",
            path=source,
            code="invalid_type",
        )
    value = os.fspath(relative_path)
    if not isinstance(value, str):
        raise ValidationError(
            "artifact path must be a text string", path=source, code="invalid_type"
        )
    if not value or "\x00" in value or any(ch in value for ch in ("\n", "\r")):
        raise ValidationError("artifact path is empty or unsafe", path=source, code="invalid_path")
    windows_path = PureWindowsPath(value)
    if Path(value).is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise ValidationError("absolute artifact path is not allowed", path=value, code="path_absolute")
    # Treat backslash as a separator too, so a manifest remains safe if moved
    # between POSIX and Windows.
    portable = value.replace("\\", "/")
    lexical_parts = portable.split("/")
    if any(part in ("", ".") for part in lexical_parts):
        raise ValidationError("artifact path is not canonical", path=value, code="invalid_path")
    parts = PurePosixPath(portable).parts
    if any(part == ".." for part in parts):
        raise ValidationError("parent traversal is not allowed", path=value, code="path_traversal")
    if not parts or any(part in ("", ".") for part in parts):
        raise ValidationError("artifact path is not canonical", path=value, code="invalid_path")
    return tuple(parts)


def safe_artifact_path(
    root: str | os.PathLike[str],
    relative_path: str | os.PathLike[str],
    *,
    allowed_extensions: Iterable[str] | None = DEFAULT_ARTIFACT_EXTENSIONS,
    max_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES,
    reject_symlinks: bool = True,
    reject_hardlinks: bool = True,
) -> Path:
    """Resolve and validate an untrusted artifact path inside ``root``.

    The check rejects absolute/parent paths, symlinks in every untrusted path
    component, non-regular files, unexpected extensions, hardlinks and files
    over the configured limit.
    """

    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 0:
        raise ValueError("max_bytes must be a non-negative integer")
    extensions = _normalise_extensions(allowed_extensions)
    parts = _relative_parts(relative_path)
    root_path = Path(root)
    try:
        resolved_root = root_path.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise ValidationError(
            "artifact root does not exist or cannot be resolved",
            path=root_path,
            code="path_root_invalid",
        ) from exc
    if not resolved_root.is_dir():
        raise ValidationError(
            "artifact root is not a directory", path=root_path, code="path_root_invalid"
        )

    lexical = resolved_root.joinpath(*parts)
    current = resolved_root
    try:
        for index, part in enumerate(parts):
            current = current / part
            info = current.lstat()
            if reject_symlinks and stat.S_ISLNK(info.st_mode):
                raise ValidationError(
                    "symlink artifact/path component is not allowed",
                    path=relative_path,
                    field="/".join(parts[: index + 1]),
                    code="path_symlink",
                )
    except FileNotFoundError as exc:
        raise ValidationError(
            "artifact does not exist", path=relative_path, code="path_not_found"
        ) from exc
    except ValidationError:
        raise
    except OSError as exc:
        raise ValidationError(
            f"cannot inspect artifact: {exc}", path=relative_path, code="file_access_error"
        ) from exc

    try:
        resolved = lexical.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValidationError(
            "artifact resolves outside the allowed root",
            path=relative_path,
            code="path_outside_root",
        ) from exc
    except (FileNotFoundError, OSError) as exc:
        raise ValidationError(
            "artifact cannot be resolved", path=relative_path, code="path_not_found"
        ) from exc

    info = resolved.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValidationError(
            "artifact is not a regular file", path=relative_path, code="path_not_regular"
        )
    if reject_hardlinks and info.st_nlink != 1:
        raise ValidationError(
            "hardlinked artifact is not allowed",
            path=relative_path,
            code="path_hardlink",
        )
    if extensions is not None and resolved.suffix.lower() not in extensions:
        raise ValidationError(
            f"artifact extension {resolved.suffix or '<none>'!r} is not allowed",
            path=relative_path,
            field="extension",
            code="path_extension",
        )
    if info.st_size > max_bytes:
        raise ValidationError(
            f"artifact exceeds size limit ({max_bytes} bytes)",
            path=relative_path,
            code="path_too_large",
        )
    return resolved


def open_directory_no_follow(root: str | os.PathLike[str]) -> int:
    """Open an absolute directory path component-by-component without links."""

    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if (
        nofollow is None
        or directory is None
        or os.open not in getattr(os, "supports_dir_fd", set())
    ):
        raise ValidationError(
            "safe directory traversal requires O_NOFOLLOW, O_DIRECTORY, and openat",
            path=root,
            code="safe_open_unsupported",
        )
    absolute = Path(os.path.abspath(os.fspath(root)))
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | nofollow | directory
    try:
        descriptor = os.open(absolute.anchor, flags)
    except OSError as exc:
        raise ValidationError(
            f"cannot open filesystem anchor safely: {exc}",
            path=root,
            code="file_access_error",
        ) from exc
    try:
        for part in absolute.parts[1:]:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise ValidationError(
                "path is not a real directory", path=root, code="path_root_invalid"
            )
        return descriptor
    except OSError as exc:
        os.close(descriptor)
        raise ValidationError(
            f"directory path contains an unavailable or linked component: {exc}",
            path=root,
            code="path_root_invalid",
        ) from exc
    except Exception:
        os.close(descriptor)
        raise


def _open_relative_no_follow(root: Path, parts: Sequence[str]) -> int:
    """Open a contained file component-by-component (TOCTOU-safe on POSIX)."""

    directory_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    directory_flags |= getattr(os, "O_DIRECTORY", 0)
    directory_flags |= getattr(os, "O_NOFOLLOW", 0)
    file_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptors: list[int] = []
    try:
        descriptor = open_directory_no_follow(root)
        descriptors.append(descriptor)
        for part in parts[:-1]:
            descriptor = os.open(part, directory_flags, dir_fd=descriptor)
            descriptors.append(descriptor)
        result = os.open(parts[-1], file_flags, dir_fd=descriptor)
        return result
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def safe_read_bytes(
    root: str | os.PathLike[str],
    relative_path: str | os.PathLike[str],
    *,
    max_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES,
    reject_hardlinks: bool = True,
) -> bytes:
    """Read exact bytes through a root-anchored descriptor traversal."""

    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 0:
        raise ValueError("max_bytes must be a non-negative integer")
    parts = _relative_parts(relative_path)
    root_path = Path(os.path.abspath(os.fspath(root)))
    try:
        descriptor = _open_relative_no_follow(root_path, parts)
    except (OSError, ValidationError) as exc:
        if isinstance(exc, ValidationError):
            raise
        raise ValidationError(
            f"cannot open artifact safely: {exc}",
            path=relative_path,
            code="file_access_error",
        ) from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ValidationError(
                "artifact is not a regular file",
                path=relative_path,
                code="path_not_regular",
            )
        if reject_hardlinks and opened.st_nlink != 1:
            raise ValidationError(
                "hardlinked artifact is not allowed",
                path=relative_path,
                code="path_hardlink",
            )
        if opened.st_size > max_bytes:
            raise ValidationError(
                f"artifact exceeds size limit ({max_bytes} bytes)",
                path=relative_path,
                code="path_too_large",
            )
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > max_bytes:
            raise ValidationError(
                f"artifact exceeds size limit ({max_bytes} bytes)",
                path=relative_path,
                code="path_too_large",
            )
        final = os.fstat(descriptor)
        if (
            not stat.S_ISREG(final.st_mode)
            or (reject_hardlinks and final.st_nlink != 1)
            or (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns)
            != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        ):
            raise ValidationError(
                "artifact changed while it was read",
                path=relative_path,
                code="file_changed_during_read",
            )
        return payload
    finally:
        os.close(descriptor)


def safe_read_artifact(
    root: str | os.PathLike[str],
    relative_path: str | os.PathLike[str],
    *,
    allowed_extensions: Iterable[str] | None = DEFAULT_ARTIFACT_EXTENSIONS,
    max_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES,
    reject_symlinks: bool = True,
    reject_hardlinks: bool = True,
    encoding: str = "utf-8",
) -> str:
    """Validate and read an untrusted text artifact without following links."""

    resolved = safe_artifact_path(
        root,
        relative_path,
        allowed_extensions=allowed_extensions,
        max_bytes=max_bytes,
        reject_symlinks=reject_symlinks,
        reject_hardlinks=reject_hardlinks,
    )
    root_resolved = Path(root).resolve(strict=True)
    parts = resolved.relative_to(root_resolved).parts
    try:
        descriptor = _open_relative_no_follow(root_resolved, parts)
    except OSError as exc:
        raise ValidationError(
            f"cannot open artifact safely: {exc}",
            path=relative_path,
            code="file_access_error",
        ) from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise ValidationError(
                "artifact is not a regular file", path=relative_path, code="path_not_regular"
            )
        if reject_hardlinks and info.st_nlink != 1:
            raise ValidationError(
                "hardlinked artifact is not allowed", path=relative_path, code="path_hardlink"
            )
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > max_bytes:
            raise ValidationError(
                f"artifact exceeds size limit ({max_bytes} bytes)",
                path=relative_path,
                code="path_too_large",
            )
    finally:
        os.close(descriptor)
    try:
        return raw.decode(encoding)
    except UnicodeDecodeError as exc:
        raise ValidationError(
            f"artifact is not valid {encoding}",
            path=relative_path,
            field=f"byte {exc.start}",
            code="invalid_encoding",
        ) from exc


def _expect_mapping(value: Any, *, path: str | None, field: str | None) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError(
            "expected a mapping", path=path, field=field, code="invalid_type"
        )
    return value


def _expect_list(value: Any, *, path: str | None, field: str | None) -> list[Any]:
    if not isinstance(value, list):
        raise ValidationError("expected a list", path=path, field=field, code="invalid_type")
    return value


def _expect_string(
    value: Any,
    *,
    path: str | None,
    field: str | None,
    allow_empty: bool = False,
    max_length: int | None = None,
) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValidationError(
            "expected a non-empty string" if not allow_empty else "expected a string",
            path=path,
            field=field,
            code="invalid_type",
        )
    if max_length is not None and len(value) > max_length:
        raise ValidationError(
            f"string exceeds length limit ({max_length})",
            path=path,
            field=field,
            code="value_too_long",
        )
    return value


def _required(data: Mapping[str, Any], key: str, *, path: str | None, base: str | None = None) -> Any:
    field = _field(base, key)
    if key not in data or data[key] is None:
        raise ValidationError(
            f"required field {key!r} is missing",
            path=path,
            field=field,
            code="required_field",
        )
    return data[key]


def _enum(value: Any, allowed: Iterable[str], *, path: str | None, field: str) -> str:
    allowed_set = frozenset(allowed)
    if not isinstance(value, str) or value not in allowed_set:
        raise ValidationError(
            f"expected one of {sorted(allowed_set)}, got {value!r}",
            path=path,
            field=field,
            code="invalid_enum",
        )
    return value


def _string_list(
    value: Any,
    *,
    path: str | None,
    field: str,
    allow_empty: bool = True,
    unique: bool = True,
) -> list[str]:
    items = _expect_list(value, path=path, field=field)
    if not allow_empty and not items:
        raise ValidationError(
            "list must not be empty", path=path, field=field, code="invalid_value"
        )
    result: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        string = _expect_string(item, path=path, field=_field(field, index), max_length=1024)
        if unique and string in seen:
            raise ValidationError(
                f"duplicate value {string!r}",
                path=path,
                field=_field(field, index),
                code="duplicate_value",
            )
        seen.add(string)
        result.append(string)
    return result


def _validate_id(value: Any, pattern: str, *, path: str | None, field: str) -> str:
    result = _expect_string(value, path=path, field=field, max_length=128)
    if not re.fullmatch(pattern, result):
        raise ValidationError(
            f"identifier {result!r} has an invalid format",
            path=path,
            field=field,
            code="invalid_id",
        )
    return result


def _deduplicate(items: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(items))


def validate_manifest(data: Any, *, path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Validate and normalise a fixture PR manifest.

    Duplicate entries are removed while preserving order; an artifact present
    in ``changed_files`` is removed from ``context_files`` because changed
    semantics take precedence.  This manifest remains a fixture/test provider,
    not a substitute for a trusted VCS diff.
    """

    source = str(path) if path is not None else None
    manifest = _expect_mapping(data, path=source, field="$manifest")
    result = dict(manifest)
    result["id"] = _expect_string(
        _required(manifest, "id", path=source), path=source, field="id", max_length=128
    )
    result["title"] = _expect_string(
        _required(manifest, "title", path=source),
        path=source,
        field="title",
        max_length=4096,
    )
    changed = _string_list(
        _required(manifest, "changed_files", path=source),
        path=source,
        field="changed_files",
        unique=False,
    )
    context = _string_list(
        _required(manifest, "context_files", path=source),
        path=source,
        field="context_files",
        unique=False,
    )
    for list_name, paths in (("changed_files", changed), ("context_files", context)):
        for index, artifact in enumerate(paths):
            try:
                _relative_parts(artifact, source=source)
            except ValidationError as exc:
                raise ValidationError(
                    exc.message,
                    path=source or exc.path,
                    field=_field(list_name, index),
                    code=exc.code,
                ) from exc
            extension = PurePosixPath(artifact.replace("\\", "/")).suffix.lower()
            if extension not in DEFAULT_ARTIFACT_EXTENSIONS:
                raise ValidationError(
                    f"artifact extension {extension or '<none>'!r} is not allowed",
                    path=source,
                    field=_field(list_name, index),
                    code="path_extension",
                )
    changed = _deduplicate(changed)
    changed_set = set(changed)
    result["changed_files"] = changed
    result["context_files"] = [item for item in _deduplicate(context) if item not in changed_set]
    return result


def load_manifest(path: str | os.PathLike[str], **yaml_limits: Any) -> dict[str, Any]:
    data = strict_load_yaml(path, expected_type=dict, **yaml_limits)
    return validate_manifest(data, path=path)


_FRONTMATTER_RE = re.compile(
    r"\A(?:\ufeff)?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL
)


def parse_frontmatter_strict(
    text: str,
    *,
    path: str | os.PathLike[str] | None = None,
    require: bool = True,
    max_bytes: int = 65_536,
    max_aliases: int = 20,
    max_depth: int = 20,
) -> tuple[dict[str, Any], str]:
    """Parse Markdown frontmatter without treating parser errors as `{}`."""

    source = str(path) if path is not None else "<frontmatter>"
    if not isinstance(text, str):
        raise ValidationError(
            "artifact content must be text", path=source, code="invalid_type"
        )
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        if require:
            raise ValidationError(
                "required YAML frontmatter is missing",
                path=source,
                field="frontmatter",
                code="frontmatter_missing",
            )
        return {}, text
    metadata = strict_load_yaml_text(
        match.group(1),
        source=f"{source}#frontmatter",
        expected_type=dict,
        max_bytes=max_bytes,
        max_aliases=max_aliases,
        max_depth=max_depth,
    )
    return metadata, text[match.end() :]


def kind_for_artifact_path(
    artifact_path: str | os.PathLike[str], *, allow_out_of_scope: bool = True
) -> str:
    """Derive the only permitted artifact kind from its repository path."""

    parts = _relative_parts(artifact_path)
    suffix = PurePosixPath(*parts).suffix.lower()
    candidates: set[str] = set()
    directory_kinds = {
        "systems": "system_passport",
        "flows": "integration_flow",
        "adrs": "adr",
        "diagrams": "diagram",
    }
    for part in parts[:-1]:
        if part in directory_kinds:
            candidates.add(directory_kinds[part])
    if suffix in {".puml", ".mmd"}:
        candidates.add("diagram")
    if len(candidates) > 1:
        raise ValidationError(
            f"artifact path maps to conflicting kinds {sorted(candidates)}",
            path=artifact_path,
            field="kind",
            code="kind_path_mismatch",
        )
    if candidates:
        return next(iter(candidates))
    if allow_out_of_scope:
        return "out_of_scope"
    raise ValidationError(
        "artifact path is outside a known kind directory",
        path=artifact_path,
        field="kind",
        code="unknown_kind_path",
    )


def _validate_optional_string_list(
    result: dict[str, Any], data: Mapping[str, Any], key: str, *, path: str | None
) -> None:
    if key in data:
        result[key] = _string_list(data[key], path=path, field=key)


def validate_frontmatter(
    data: Any,
    *,
    artifact_path: str | os.PathLike[str] | None = None,
    expected_kind: str | None = None,
    path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Validate metadata for one known artifact kind and enforce kind/path."""

    source = str(path if path is not None else artifact_path) if (
        path is not None or artifact_path is not None
    ) else None
    metadata = _expect_mapping(data, path=source, field="frontmatter")
    result = dict(metadata)
    if expected_kind is not None:
        _enum(expected_kind, KNOWN_KINDS, path=source, field="expected_kind")
    if artifact_path is not None:
        path_kind = kind_for_artifact_path(artifact_path)
        if expected_kind is not None and path_kind != expected_kind:
            raise ValidationError(
                f"expected kind {expected_kind!r} conflicts with path kind {path_kind!r}",
                path=source,
                field="kind",
                code="kind_path_mismatch",
            )
        expected_kind = path_kind

    declared = metadata.get("kind")
    if declared is None:
        if expected_kind not in {"diagram", "out_of_scope"}:
            raise ValidationError(
                "required field 'kind' is missing",
                path=source,
                field="kind",
                code="required_field",
            )
        kind = expected_kind or "out_of_scope"
    else:
        kind = _enum(declared, KNOWN_KINDS, path=source, field="kind")
    if expected_kind is not None and kind != expected_kind:
        raise ValidationError(
            f"declared kind {kind!r} conflicts with path kind {expected_kind!r}",
            path=source,
            field="kind",
            code="kind_path_mismatch",
        )
    result["kind"] = kind

    if kind == "integration_flow":
        for key in ("id", "source", "target"):
            pattern = r"IF-\d{4}" if key == "id" else r"(?:AS|EXT)-\d{4}"
            result[key] = _validate_id(
                _required(metadata, key, path=source), pattern, path=source, field=key
            )
        result["pattern"] = _enum(
            _required(metadata, "pattern", path=source), FLOW_PATTERNS, path=source, field="pattern"
        )
        result["zone"] = _enum(
            _required(metadata, "zone", path=source), FLOW_ZONES, path=source, field="zone"
        )
        _validate_optional_string_list(result, metadata, "data_categories", path=source)
        _validate_optional_string_list(result, metadata, "approvals", path=source)
        if "transfer_mode" in metadata:
            result["transfer_mode"] = _enum(
                metadata["transfer_mode"],
                TRANSFER_MODES,
                path=source,
                field="transfer_mode",
            )
        if "gateway_controlled" in metadata and not isinstance(metadata["gateway_controlled"], bool):
            raise ValidationError(
                "gateway_controlled must be boolean",
                path=source,
                field="gateway_controlled",
                code="invalid_type",
            )

    elif kind == "system_passport":
        result["id"] = _validate_id(
            _required(metadata, "id", path=source), r"AS-\d{4}", path=source, field="id"
        )
        for key in ("name", "owner"):
            result[key] = _expect_string(
                _required(metadata, key, path=source), path=source, field=key, max_length=1024
            )
        result["criticality"] = _enum(
            _required(metadata, "criticality", path=source),
            CRITICALITIES,
            path=source,
            field="criticality",
        )
        result["target_status"] = _enum(
            _required(metadata, "target_status", path=source),
            TARGET_STATUSES,
            path=source,
            field="target_status",
        )

    elif kind == "adr":
        result["id"] = _validate_id(
            _required(metadata, "id", path=source), r"ADR-\d{4}", path=source, field="id"
        )
        result["status"] = _enum(
            _required(metadata, "status", path=source), ADR_STATUSES, path=source, field="status"
        )
        date = _required(metadata, "date", path=source)
        if isinstance(date, str):
            try:
                _datetime.date.fromisoformat(date)
            except ValueError as exc:
                raise ValidationError(
                    "date must use ISO YYYY-MM-DD format",
                    path=source,
                    field="date",
                    code="invalid_value",
                ) from exc
        elif not isinstance(date, _datetime.date):
            raise ValidationError(
                "date must use ISO YYYY-MM-DD format",
                path=source,
                field="date",
                code="invalid_type",
            )
        result["author"] = _expect_string(
            _required(metadata, "author", path=source), path=source, field="author", max_length=1024
        )
        systems = _string_list(
            _required(metadata, "systems", path=source), path=source, field="systems"
        )
        for index, system_id in enumerate(systems):
            _validate_id(system_id, r"AS-\d{4}", path=source, field=_field("systems", index))
        result["systems"] = systems

    return result


def validate_review_frontmatter(
    data: Any,
    *,
    expected_kind: str,
    path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Validate the structural review boundary without stealing rule findings.

    The full :func:`validate_frontmatter` schema is appropriate for authored
    artifacts, but the review engine must still report several missing or
    semantically invalid fields through rules-as-code (for example ADR-002,
    ADR-004, PRIN-001 and SEAF-005).  This profile therefore rejects malformed
    present values and identifiers, while leaving those documented governance
    defects to the detector registry.
    """

    source = str(path) if path is not None else None
    metadata = _expect_mapping(data, path=source, field="frontmatter")
    kind = _enum(expected_kind, KNOWN_KINDS, path=source, field="kind")
    result = dict(metadata)

    declared = metadata.get("kind")
    if declared is not None:
        declared_kind = _enum(declared, KNOWN_KINDS, path=source, field="kind")
        if declared_kind != kind:
            raise ValidationError(
                f"declared kind {declared_kind!r} conflicts with path kind {kind!r}",
                path=source,
                field="kind",
                code="kind_path_mismatch",
            )

    if kind in {"diagram", "out_of_scope"}:
        return result
    if not metadata:
        raise ValidationError(
            "frontmatter is required",
            path=source,
            field="frontmatter",
            code="required_field",
        )

    if kind == "integration_flow":
        for key in ("id", "source", "target"):
            identifier_pattern = r"IF-\d{4}" if key == "id" else r"(?:AS|EXT)-\d{4}"
            result[key] = _validate_id(
                _required(metadata, key, path=source),
                identifier_pattern,
                path=source,
                field=key,
            )
        result["pattern"] = _enum(
            _required(metadata, "pattern", path=source),
            FLOW_PATTERNS,
            path=source,
            field="pattern",
        )
        result["zone"] = _enum(
            _required(metadata, "zone", path=source),
            FLOW_ZONES,
            path=source,
            field="zone",
        )
        _validate_optional_string_list(result, metadata, "data_categories", path=source)
        _validate_optional_string_list(result, metadata, "approvals", path=source)
        if "transfer_mode" in metadata:
            result["transfer_mode"] = _enum(
                metadata["transfer_mode"],
                TRANSFER_MODES,
                path=source,
                field="transfer_mode",
            )
        if "gateway_controlled" in metadata and not isinstance(
            metadata["gateway_controlled"], bool
        ):
            raise ValidationError(
                "gateway_controlled must be boolean",
                path=source,
                field="gateway_controlled",
                code="invalid_type",
            )

    elif kind == "system_passport":
        result["id"] = _validate_id(
            _required(metadata, "id", path=source),
            r"AS-\d{4}",
            path=source,
            field="id",
        )
        # Empty strings remain detector-visible as missing governance data;
        # non-string values are malformed input and cannot enter detectors.
        for key in ("name", "owner", "criticality"):
            if key in metadata and metadata[key] is not None:
                result[key] = _expect_string(
                    metadata[key], path=source, field=key, allow_empty=True, max_length=1024
                )
        if "target_status" in metadata and metadata["target_status"] not in (None, ""):
            result["target_status"] = _enum(
                metadata["target_status"],
                TARGET_STATUSES,
                path=source,
                field="target_status",
            )

    elif kind == "adr":
        result["id"] = _validate_id(
            _required(metadata, "id", path=source),
            r"ADR-\d{4}",
            path=source,
            field="id",
        )
        if "status" in metadata and metadata["status"] is not None:
            # Unknown string values are intentionally handled by ADR-002.
            result["status"] = _expect_string(
                metadata["status"], path=source, field="status", allow_empty=True,
                max_length=128,
            )
        if "date" in metadata and metadata["date"] not in (None, ""):
            date = metadata["date"]
            if isinstance(date, str):
                try:
                    _datetime.date.fromisoformat(date)
                except ValueError as exc:
                    raise ValidationError(
                        "date must use ISO YYYY-MM-DD format",
                        path=source,
                        field="date",
                        code="invalid_value",
                    ) from exc
            elif not isinstance(date, _datetime.date):
                raise ValidationError(
                    "date must use ISO YYYY-MM-DD format",
                    path=source,
                    field="date",
                    code="invalid_type",
                )
        if "author" in metadata and metadata["author"] is not None:
            result["author"] = _expect_string(
                metadata["author"], path=source, field="author", allow_empty=True,
                max_length=1024,
            )
        systems = _string_list(
            _required(metadata, "systems", path=source),
            path=source,
            field="systems",
        )
        for index, system_id in enumerate(systems):
            _validate_id(
                system_id,
                r"AS-\d{4}",
                path=source,
                field=_field("systems", index),
            )
        result["systems"] = systems

    return result


def load_and_validate_frontmatter(
    text: str,
    *,
    artifact_path: str | os.PathLike[str] | None = None,
    expected_kind: str | None = None,
    require: bool | None = None,
) -> tuple[dict[str, Any], str]:
    if require is None:
        derived = expected_kind or (
            kind_for_artifact_path(artifact_path) if artifact_path is not None else None
        )
        require = derived not in {"diagram", "out_of_scope"}
    metadata, body = parse_frontmatter_strict(text, path=artifact_path, require=require)
    return (
        validate_frontmatter(
            metadata,
            artifact_path=artifact_path,
            expected_kind=expected_kind,
        ),
        body,
    )


_CONDITION_FIELD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)*")


def validate_exception_condition(
    condition: Any,
    *,
    path: str | os.PathLike[str] | None = None,
    field: str = "when",
    max_depth: int = 12,
    max_clauses: int = 100,
) -> dict[str, Any]:
    """Validate the exception condition DSL (``all/any`` and leaf operators)."""

    source = str(path) if path is not None else None
    clauses = 0

    def validate(item: Any, current_field: str, depth: int) -> dict[str, Any]:
        nonlocal clauses
        clauses += 1
        if clauses > max_clauses:
            raise ValidationError(
                f"condition exceeds clause limit ({max_clauses})",
                path=source,
                field=current_field,
                code="condition_limit",
            )
        if depth > max_depth:
            raise ValidationError(
                f"condition exceeds depth limit ({max_depth})",
                path=source,
                field=current_field,
                code="condition_limit",
            )
        node = _expect_mapping(item, path=source, field=current_field)
        group_keys = [key for key in ("all", "any") if key in node]
        if group_keys:
            if len(group_keys) != 1 or len(node) != 1:
                raise ValidationError(
                    "condition group must contain exactly one of 'all' or 'any'",
                    path=source,
                    field=current_field,
                    code="invalid_condition",
                )
            group = group_keys[0]
            children = _expect_list(node[group], path=source, field=_field(current_field, group))
            if not children:
                raise ValidationError(
                    f"'{group}' condition must not be empty",
                    path=source,
                    field=_field(current_field, group),
                    code="invalid_condition",
                )
            return {
                group: [
                    validate(child, _field(_field(current_field, group), index), depth + 1)
                    for index, child in enumerate(children)
                ]
            }

        allowed_keys = {"field", "equals", "contains", "in"}
        unknown = set(node) - allowed_keys
        operators = [key for key in ("equals", "contains", "in") if key in node]
        if unknown or "field" not in node or len(operators) != 1 or len(node) != 2:
            raise ValidationError(
                "leaf condition requires 'field' and exactly one of equals/contains/in",
                path=source,
                field=current_field,
                code="invalid_condition",
            )
        lookup = _expect_string(
            node["field"], path=source, field=_field(current_field, "field"), max_length=256
        )
        if not _CONDITION_FIELD_RE.fullmatch(lookup):
            raise ValidationError(
                "condition field must be a safe dotted lookup",
                path=source,
                field=_field(current_field, "field"),
                code="invalid_condition",
            )
        operator = operators[0]
        operand = node[operator]
        if operator == "in":
            operand = _expect_list(
                operand, path=source, field=_field(current_field, operator)
            )
            if not operand:
                raise ValidationError(
                    "'in' operand must not be empty",
                    path=source,
                    field=_field(current_field, operator),
                    code="invalid_condition",
                )
            if any(isinstance(value, (Mapping, list, tuple, set)) for value in operand):
                raise ValidationError(
                    "'in' values must be scalar",
                    path=source,
                    field=_field(current_field, operator),
                    code="invalid_condition",
                )
        elif operator == "contains" and isinstance(operand, Mapping):
            raise ValidationError(
                "'contains' operand cannot be a mapping",
                path=source,
                field=_field(current_field, operator),
                code="invalid_condition",
            )
        elif operator == "contains" and isinstance(operand, list) and any(
            isinstance(value, (Mapping, list, tuple, set)) for value in operand
        ):
            raise ValidationError(
                "'contains' values must be scalar",
                path=source,
                field=_field(current_field, operator),
                code="invalid_condition",
            )
        elif operator == "equals" and isinstance(operand, Mapping):
            raise ValidationError(
                "'equals' operand cannot be a mapping",
                path=source,
                field=_field(current_field, operator),
                code="invalid_condition",
            )
        return {"field": lookup, operator: operand}

    return validate(condition, field, 1)


_MISSING = object()


def dotted_lookup(data: Mapping[str, Any], field: str, default: Any = None) -> Any:
    value: Any = data
    for component in field.split("."):
        if not isinstance(value, Mapping) or component not in value:
            return default
        value = value[component]
    return value


def condition_matches(condition: Mapping[str, Any], data: Mapping[str, Any]) -> bool:
    """Evaluate a previously validated condition against artifact metadata."""

    if "all" in condition:
        return all(condition_matches(child, data) for child in condition["all"])
    if "any" in condition:
        return any(condition_matches(child, data) for child in condition["any"])
    actual = dotted_lookup(data, condition["field"], _MISSING)
    if actual is _MISSING:
        return False
    if "equals" in condition:
        return actual == condition["equals"]
    if "contains" in condition:
        expected = condition["contains"]
        if isinstance(actual, (list, tuple, set, frozenset)):
            if isinstance(expected, (list, tuple, set, frozenset)):
                return all(value in actual for value in expected)
            return expected in actual
        if isinstance(actual, str) and isinstance(expected, str):
            return expected in actual
        if isinstance(actual, Mapping):
            return expected in actual
        return False
    allowed = condition["in"]
    if isinstance(actual, (list, tuple, set, frozenset)):
        return any(value in allowed for value in actual)
    return actual in allowed


# More explicit alias for consumers that prefer verb-based naming.
evaluate_exception_condition = condition_matches


def _condition_disables_trigger(condition: Mapping[str, Any], detect: Mapping[str, Any]) -> bool:
    """Conservatively detect an exception equivalent to disabling a trigger."""

    field: str | None = None
    banned: list[Any] | None = None
    if set(detect) == {"field", "banned"}:
        field = detect.get("field")
        value = detect.get("banned")
        banned = value if isinstance(value, list) else None
    elif set(detect) == {"field_banned"} and isinstance(detect["field_banned"], Mapping):
        spec = detect["field_banned"]
        field = spec.get("field")
        value = spec.get("banned", spec.get("values"))
        banned = value if isinstance(value, list) else None
    if not field or not banned:
        return False

    def metadata_for(value: Any) -> dict[str, Any]:
        result: dict[str, Any] = {}
        target = result
        components = field.split(".")
        for component in components[:-1]:
            nested: dict[str, Any] = {}
            target[component] = nested
            target = nested
        target[components[-1]] = value
        return result

    # If the exception matches every value that fires the detector without
    # needing any additional metadata, it is equivalent to switching it off.
    return all(condition_matches(condition, metadata_for(value)) for value in banned)


_SEMVER_RE = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)")
_PROVENANCE_RE = re.compile(r"(?:seed|precedent:[A-Za-z0-9._-]+|incident:[A-Za-z0-9._-]+)")


def _validate_semver(value: Any, *, path: str | None, field: str) -> str:
    version = _expect_string(value, path=path, field=field, max_length=64)
    if not _SEMVER_RE.fullmatch(version):
        raise ValidationError(
            "expected semantic version MAJOR.MINOR.PATCH",
            path=path,
            field=field,
            code="invalid_value",
        )
    return version


def _validate_provenance(value: Any, *, path: str | None, field: str) -> str:
    provenance = _expect_string(value, path=path, field=field, max_length=512)
    if not _PROVENANCE_RE.fullmatch(provenance):
        raise ValidationError(
            "provenance must be seed, precedent:<id>, or incident:<id>",
            path=path,
            field=field,
            code="invalid_value",
        )
    return provenance


def validate_exception(
    exception: Any,
    *,
    detect: Mapping[str, Any] | None = None,
    path: str | os.PathLike[str] | None = None,
    field: str = "exception",
) -> dict[str, Any]:
    source = str(path) if path is not None else None
    item = _expect_mapping(exception, path=source, field=field)
    result = dict(item)
    for key in ("id", "rationale"):
        result[key] = _expect_string(
            _required(item, key, path=source, base=field),
            path=source,
            field=_field(field, key),
            max_length=4096,
        )
    result["provenance"] = _validate_provenance(
        _required(item, "provenance", path=source, base=field),
        path=source,
        field=_field(field, "provenance"),
    )
    result["added_in"] = _validate_semver(
        _required(item, "added_in", path=source, base=field),
        path=source,
        field=_field(field, "added_in"),
    )
    result["when"] = validate_exception_condition(
        _required(item, "when", path=source, base=field),
        path=source,
        field=_field(field, "when"),
    )
    if detect is not None and _condition_disables_trigger(result["when"], detect):
        waiver = item.get("committee_waiver")
        cases = item.get("positive_regression_cases")
        waiver_ok = isinstance(waiver, (str, Mapping)) and bool(waiver)
        cases_ok = isinstance(cases, list) and bool(cases) and all(
            isinstance(case, str) and case.strip() for case in cases
        )
        if not (waiver_ok and cases_ok):
            raise ValidationError(
                "exception disables the complete rule trigger; committee waiver and "
                "positive regression cases are required",
                path=source,
                field=_field(field, "when"),
                code="tautological_exception",
            )
    return result


def _validate_detect(
    detect: Any,
    *,
    path: str | None,
    field: str,
    supported_detect: Iterable[str] | None,
) -> dict[str, Any]:
    spec = dict(_expect_mapping(detect, path=path, field=field))
    supported = (
        SUPPORTED_DETECT_OPERATORS
        if supported_detect is None
        else frozenset(supported_detect)
    )

    # Legacy seed representation: {field: pattern, banned: [file]}.
    if set(spec) == {"field", "banned"}:
        if "field_banned" not in supported:
            raise ValidationError(
                "detect operator 'field_banned' is not supported",
                path=path,
                field=field,
                code="unknown_detect_operator",
            )
        _expect_string(spec["field"], path=path, field=_field(field, "field"))
        _string_list(spec["banned"], path=path, field=_field(field, "banned"), allow_empty=False)
        return spec

    if len(spec) != 1:
        raise ValidationError(
            "detect must contain exactly one supported operator",
            path=path,
            field=field,
            code="invalid_detect",
        )
    operator, operand = next(iter(spec.items()))
    if operator not in supported:
        raise ValidationError(
            f"unsupported detect operator {operator!r}",
            path=path,
            field=_field(field, operator),
            code="unknown_detect_operator",
        )

    string_operand = {
        "field_required",
        "field_matches_registry",
        "systems_field_must_exist",
        "no_endpoint_with_target_status",
        "endpoint_target_status_forbidden",
        "pdn_external_requires_approval",
        "node_label_pattern",
    }
    list_operand = {"required_fields", "systems_must_exist", "required_sections"}
    true_operand = {
        "parseable",
        "diagram_parseable",
        "c4_level_declared",
        "edges_labeled",
        "diagram_edges_labeled",
        "no_orphan_nodes",
        "diagram_no_orphans",
        "flow_present_on_diagram",
        "edges_covered_by_flows",
    }
    operand_field = _field(field, operator)
    if operator in string_operand:
        _expect_string(operand, path=path, field=operand_field)
        if operator == "node_label_pattern":
            try:
                re.compile(operand)
            except re.error as exc:
                raise ValidationError(
                    f"invalid regular expression: {exc}",
                    path=path,
                    field=operand_field,
                    code="invalid_detect",
                ) from exc
    elif operator in list_operand:
        _string_list(operand, path=path, field=operand_field, allow_empty=False)
    elif operator in true_operand:
        if operand is not True:
            raise ValidationError(
                "boolean detect flag must be true",
                path=path,
                field=operand_field,
                code="invalid_detect",
            )
    elif operator == "field_in_vocab":
        vocab = _expect_mapping(operand, path=path, field=operand_field)
        if set(vocab) != {"field", "vocab"}:
            raise ValidationError(
                "field_in_vocab requires exactly field and vocab",
                path=path,
                field=operand_field,
                code="invalid_detect",
            )
        _expect_string(vocab["field"], path=path, field=_field(operand_field, "field"))
        _string_list(
            vocab["vocab"],
            path=path,
            field=_field(operand_field, "vocab"),
            allow_empty=False,
        )
    elif operator == "field_banned":
        banned = _expect_mapping(operand, path=path, field=operand_field)
        unknown = set(banned) - {"field", "banned", "values"}
        values_key = "banned" if "banned" in banned else "values" if "values" in banned else None
        if unknown or "field" not in banned or values_key is None or len(banned) != 2:
            raise ValidationError(
                "field_banned requires exactly field and banned/values",
                path=path,
                field=operand_field,
                code="invalid_detect",
            )
        _expect_string(banned["field"], path=path, field=_field(operand_field, "field"))
        _string_list(
            banned[values_key],
            path=path,
            field=_field(operand_field, values_key),
            allow_empty=False,
        )
    return spec


def validate_rule(
    rule: Any,
    *,
    path: str | os.PathLike[str] | None = None,
    field: str = "rule",
    supported_detect: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Validate one rule, its provenance, detector and exception DSL."""

    source = str(path) if path is not None else None
    item = _expect_mapping(rule, path=source, field=field)
    result = dict(item)
    result["id"] = _validate_id(
        _required(item, "id", path=source, base=field),
        r"[A-Z][A-Z0-9]*-\d{3}",
        path=source,
        field=_field(field, "id"),
    )
    status = _enum(
        _required(item, "status", path=source, base=field),
        RULE_STATUSES,
        path=source,
        field=_field(field, "status"),
    )
    result["status"] = status
    if status in {"active", "candidate"}:
        for key in ("title", "statement", "source_ref"):
            result[key] = _expect_string(
                _required(item, key, path=source, base=field),
                path=source,
                field=_field(field, key),
                max_length=20_000,
            )
        result["severity"] = _enum(
            _required(item, "severity", path=source, base=field),
            SEVERITIES,
            path=source,
            field=_field(field, "severity"),
        )
        scope = _string_list(
            _required(item, "scope", path=source, base=field),
            path=source,
            field=_field(field, "scope"),
            allow_empty=False,
        )
        for index, kind in enumerate(scope):
            _enum(kind, KNOWN_KINDS - {"out_of_scope"}, path=source, field=_field(_field(field, "scope"), index))
        result["scope"] = scope
        check_type = _enum(
            _required(item, "check_type", path=source, base=field),
            CHECK_TYPES,
            path=source,
            field=_field(field, "check_type"),
        )
        result["check_type"] = check_type
        if check_type in {"deterministic", "hybrid"}:
            result["detect"] = _validate_detect(
                _required(item, "detect", path=source, base=field),
                path=source,
                field=_field(field, "detect"),
                supported_detect=supported_detect,
            )
        elif "detect" in item:
            # A hint on an LLM rule is still schema-checked, but dispatchers must
            # continue to honour check_type and not execute it deterministically.
            result["detect"] = _validate_detect(
                item["detect"],
                path=source,
                field=_field(field, "detect"),
                supported_detect=supported_detect,
            )
    else:
        for key in ("title", "statement", "source_ref"):
            if key in item:
                _expect_string(item[key], path=source, field=_field(field, key))
        if "severity" in item:
            _enum(item["severity"], SEVERITIES, path=source, field=_field(field, "severity"))

    provenance = _expect_mapping(
        _required(item, "provenance", path=source, base=field),
        path=source,
        field=_field(field, "provenance"),
    )
    result["provenance"] = dict(provenance)
    result["provenance"]["origin"] = _validate_provenance(
        _required(provenance, "origin", path=source, base=_field(field, "provenance")),
        path=source,
        field=_field(_field(field, "provenance"), "origin"),
    )
    result["provenance"]["added_in"] = _validate_semver(
        _required(provenance, "added_in", path=source, base=_field(field, "provenance")),
        path=source,
        field=_field(_field(field, "provenance"), "added_in"),
    )

    exceptions = item.get("exceptions", [])
    exception_items = _expect_list(exceptions, path=source, field=_field(field, "exceptions"))
    validated_exceptions: list[dict[str, Any]] = []
    exception_ids: set[str] = set()
    for index, exception in enumerate(exception_items):
        current_field = _field(_field(field, "exceptions"), index)
        validated = validate_exception(
            exception,
            detect=result.get("detect"),
            path=source,
            field=current_field,
        )
        if validated["id"] in exception_ids:
            raise ValidationError(
                f"duplicate exception id {validated['id']!r}",
                path=source,
                field=_field(current_field, "id"),
                code="duplicate_id",
            )
        exception_ids.add(validated["id"])
        validated_exceptions.append(validated)
    result["exceptions"] = validated_exceptions
    return result


def validate_rules_document(
    data: Any,
    *,
    path: str | os.PathLike[str] | None = None,
    seen_rule_ids: set[str] | None = None,
    supported_detect: Iterable[str] | None = None,
) -> dict[str, Any]:
    source = str(path) if path is not None else None
    document = _expect_mapping(data, path=source, field="$rules")
    schema = _required(document, "schema", path=source)
    if schema != "aga.rules/v1":
        raise ValidationError(
            "rules schema must be 'aga.rules/v1'",
            path=source,
            field="schema",
            code="invalid_schema",
        )
    domain = _enum(
        _required(document, "domain", path=source),
        {"principles", "seaf", "diagram", "adr"},
        path=source,
        field="domain",
    )
    rules = _expect_list(_required(document, "rules", path=source), path=source, field="rules")
    ids = seen_rule_ids if seen_rule_ids is not None else set()
    validated: list[dict[str, Any]] = []
    for index, rule in enumerate(rules):
        current = _field("rules", index)
        item = validate_rule(
            rule, path=source, field=current, supported_detect=supported_detect
        )
        if item["id"] in ids:
            raise ValidationError(
                f"duplicate rule id {item['id']!r}",
                path=source,
                field=_field(current, "id"),
                code="duplicate_id",
            )
        ids.add(item["id"])
        validated.append(item)
    result = dict(document)
    result["schema"] = schema
    result["domain"] = domain
    result["rules"] = validated
    return result


def validate_seaf(
    data: Any, *, path: str | os.PathLike[str] | None = None
) -> dict[str, Any]:
    """Validate a SEAF snapshot and make ``infra: false`` explicit."""

    source = str(path) if path is not None else None
    document = _expect_mapping(data, path=source, field="$seaf")
    if _required(document, "schema", path=source) != "aga.seaf-fixture/v1":
        raise ValidationError(
            "SEAF schema must be 'aga.seaf-fixture/v1'",
            path=source,
            field="schema",
            code="invalid_schema",
        )
    _expect_string(_required(document, "version", path=source), path=source, field="version")
    systems = _expect_list(_required(document, "systems", path=source), path=source, field="systems")
    if not systems:
        raise ValidationError(
            "SEAF systems must not be empty", path=source, field="systems", code="invalid_value"
        )
    validated: list[dict[str, Any]] = []
    ids: set[str] = set()
    for index, system in enumerate(systems):
        base = _field("systems", index)
        item = _expect_mapping(system, path=source, field=base)
        result = dict(item)
        system_id = _validate_id(
            _required(item, "id", path=source, base=base),
            r"AS-\d{4}",
            path=source,
            field=_field(base, "id"),
        )
        if system_id in ids:
            raise ValidationError(
                f"duplicate SEAF system id {system_id!r}",
                path=source,
                field=_field(base, "id"),
                code="duplicate_id",
            )
        ids.add(system_id)
        result["id"] = system_id
        for key in ("name", "owner", "domain"):
            result[key] = _expect_string(
                _required(item, key, path=source, base=base),
                path=source,
                field=_field(base, key),
                max_length=2048,
            )
        result["criticality"] = _enum(
            _required(item, "criticality", path=source, base=base),
            CRITICALITIES,
            path=source,
            field=_field(base, "criticality"),
        )
        result["target_status"] = _enum(
            _required(item, "target_status", path=source, base=base),
            TARGET_STATUSES,
            path=source,
            field=_field(base, "target_status"),
        )
        infra = item.get("infra", False)
        if not isinstance(infra, bool):
            raise ValidationError(
                "infra must be boolean",
                path=source,
                field=_field(base, "infra"),
                code="invalid_type",
            )
        result["infra"] = infra
        validated.append(result)
    result_document = dict(document)
    result_document["systems"] = validated
    return result_document


def validate_severity_policy(
    data: Any, *, path: str | os.PathLike[str] | None = None
) -> dict[str, Any]:
    source = str(path) if path is not None else None
    policy = _expect_mapping(data, path=source, field="$policy")
    if _required(policy, "schema", path=source) != "aga.severity-policy/v1":
        raise ValidationError(
            "severity policy schema must be 'aga.severity-policy/v1'",
            path=source,
            field="schema",
            code="invalid_schema",
        )
    severities = _string_list(
        _required(policy, "severities", path=source), path=source, field="severities", allow_empty=False
    )
    if set(severities) != set(SEVERITIES):
        raise ValidationError(
            f"severities must contain exactly {sorted(SEVERITIES)}",
            path=source,
            field="severities",
            code="invalid_value",
        )
    if _required(policy, "aggregation", path=source) != "max_severity":
        raise ValidationError(
            "only max_severity aggregation is supported",
            path=source,
            field="aggregation",
            code="invalid_enum",
        )
    verdict_policy = _expect_mapping(
        _required(policy, "verdict_policy", path=source), path=source, field="verdict_policy"
    )
    verdict_keys = {"has_blocker", "has_major", "minor_only", "none"}
    if set(verdict_policy) != verdict_keys:
        raise ValidationError(
            f"verdict_policy requires exactly {sorted(verdict_keys)}",
            path=source,
            field="verdict_policy",
            code="invalid_value",
        )
    for key, value in verdict_policy.items():
        _enum(value, VERDICTS, path=source, field=_field("verdict_policy", key))
    if verdict_policy["has_blocker"] != "request_changes_escalate" or verdict_policy[
        "has_major"
    ] != "request_changes_escalate":
        raise ValidationError(
            "blocker and major findings must require human escalation",
            path=source,
            field="verdict_policy",
            code="policy_invariant",
        )

    confidence = _expect_mapping(
        _required(policy, "confidence", path=source), path=source, field="confidence"
    )
    confidence_values: dict[str, float] = {}
    for key in ("min_for_blocker", "min_for_finding"):
        value = _required(confidence, key, path=source, base="confidence")
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= 1
        ):
            raise ValidationError(
                "confidence threshold must be a number between 0 and 1",
                path=source,
                field=_field("confidence", key),
                code="invalid_value",
            )
        confidence_values[key] = float(value)
    if confidence_values["min_for_blocker"] < confidence_values["min_for_finding"]:
        raise ValidationError(
            "min_for_blocker cannot be below min_for_finding",
            path=source,
            field="confidence",
            code="policy_invariant",
        )

    autonomy = _expect_mapping(
        _required(policy, "autonomy", path=source), path=source, field="autonomy"
    )
    if autonomy.get("auto_merge") is not False:
        raise ValidationError(
            "autonomy.auto_merge must remain false",
            path=source,
            field="autonomy.auto_merge",
            code="policy_invariant",
        )
    auto_verdicts = _string_list(
        _required(autonomy, "auto_verdicts", path=source, base="autonomy"),
        path=source,
        field="autonomy.auto_verdicts",
    )
    if not set(auto_verdicts).issubset({"approve", "approve_with_warnings"}):
        raise ValidationError(
            "only approve/warning verdicts may be automatic",
            path=source,
            field="autonomy.auto_verdicts",
            code="policy_invariant",
        )
    human = _string_list(
        _required(autonomy, "human_required_for", path=source, base="autonomy"),
        path=source,
        field="autonomy.human_required_for",
        allow_empty=False,
    )
    if "request_changes_escalate" not in human:
        raise ValidationError(
            "request_changes_escalate must require a human",
            path=source,
            field="autonomy.human_required_for",
            code="policy_invariant",
        )

    costs = _expect_mapping(
        _required(policy, "error_costs", path=source), path=source, field="error_costs"
    )
    cost_keys = {
        "missed_blocker",
        "missed_major",
        "missed_minor",
        "false_blocker",
        "false_major",
        "false_minor",
    }
    if set(costs) != cost_keys:
        raise ValidationError(
            f"error_costs requires exactly {sorted(cost_keys)}",
            path=source,
            field="error_costs",
            code="invalid_value",
        )
    for key, value in costs.items():
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValidationError(
                "error cost must be a non-negative number",
                path=source,
                field=_field("error_costs", key),
                code="invalid_value",
            )
    escalation = _expect_mapping(
        _required(policy, "escalation", path=source), path=source, field="escalation"
    )
    _expect_string(
        _required(escalation, "assignee", path=source, base="escalation"),
        path=source,
        field="escalation.assignee",
    )
    return dict(policy)


def validate_corpus(
    data: Any,
    *,
    path: str | os.PathLike[str] | None = None,
    minimum_cases: int = 1,
) -> dict[str, Any]:
    source = str(path) if path is not None else None
    if isinstance(minimum_cases, bool) or not isinstance(minimum_cases, int) or minimum_cases < 1:
        raise ValueError("minimum_cases must be a positive integer")
    corpus = _expect_mapping(data, path=source, field="$corpus")
    if _required(corpus, "schema", path=source) != "aga.golden-corpus/v1":
        raise ValidationError(
            "corpus schema must be 'aga.golden-corpus/v1'",
            path=source,
            field="schema",
            code="invalid_schema",
        )
    cases = _expect_list(_required(corpus, "cases", path=source), path=source, field="cases")
    if len(cases) < minimum_cases:
        raise ValidationError(
            f"corpus has {len(cases)} cases; at least {minimum_cases} required",
            path=source,
            field="cases",
            code="corpus_too_small",
        )
    ids: set[str] = set()
    validated_cases: list[dict[str, Any]] = []
    for index, case in enumerate(cases):
        base = _field("cases", index)
        item = _expect_mapping(case, path=source, field=base)
        result = dict(item)
        case_id = _validate_id(
            _required(item, "id", path=source, base=base),
            r"pr-\d{2,}",
            path=source,
            field=_field(base, "id"),
        )
        if case_id in ids:
            raise ValidationError(
                f"duplicate corpus case id {case_id!r}",
                path=source,
                field=_field(base, "id"),
                code="duplicate_id",
            )
        ids.add(case_id)
        result["id"] = case_id
        for key in ("title", "scenario"):
            result[key] = _expect_string(
                _required(item, key, path=source, base=base),
                path=source,
                field=_field(base, key),
                max_length=20_000,
            )
        materialized = _required(item, "materialized", path=source, base=base)
        if not isinstance(materialized, bool):
            raise ValidationError(
                "materialized must be boolean",
                path=source,
                field=_field(base, "materialized"),
                code="invalid_type",
            )
        if "origin" in item:
            result["origin"] = _validate_provenance(
                item["origin"], path=source, field=_field(base, "origin")
            )
        expected = _expect_mapping(
            _required(item, "expected", path=source, base=base),
            path=source,
            field=_field(base, "expected"),
        )
        findings = _expect_list(
            _required(expected, "findings", path=source, base=_field(base, "expected")),
            path=source,
            field=_field(_field(base, "expected"), "findings"),
        )
        validated_findings: list[dict[str, Any]] = []
        finding_keys: set[tuple[Any, ...]] = set()
        for finding_index, finding in enumerate(findings):
            finding_base = _field(_field(_field(base, "expected"), "findings"), finding_index)
            finding_item = _expect_mapping(finding, path=source, field=finding_base)
            result_finding = dict(finding_item)
            result_finding["rule_id"] = _validate_id(
                _required(finding_item, "rule_id", path=source, base=finding_base),
                r"[A-Z][A-Z0-9]*-\d{3}",
                path=source,
                field=_field(finding_base, "rule_id"),
            )
            result_finding["severity"] = _enum(
                _required(finding_item, "severity", path=source, base=finding_base),
                SEVERITIES,
                path=source,
                field=_field(finding_base, "severity"),
            )
            for optional in ("artifact", "location", "canonical_defect"):
                if optional in finding_item:
                    result_finding[optional] = _expect_string(
                        finding_item[optional],
                        path=source,
                        field=_field(finding_base, optional),
                        max_length=4096,
                    )
            key = (
                result_finding["rule_id"],
                result_finding["severity"],
                result_finding.get("artifact"),
                result_finding.get("location"),
                result_finding.get("canonical_defect"),
            )
            if key in finding_keys:
                raise ValidationError(
                    "duplicate expected finding",
                    path=source,
                    field=finding_base,
                    code="duplicate_value",
                )
            finding_keys.add(key)
            validated_findings.append(result_finding)
        outcome = _enum(
            _required(expected, "outcome", path=source, base=_field(base, "expected")),
            VERDICTS,
            path=source,
            field=_field(_field(base, "expected"), "outcome"),
        )
        result["expected"] = {**expected, "findings": validated_findings, "outcome": outcome}
        validated_cases.append(result)
    result_document = dict(corpus)
    result_document["cases"] = validated_cases
    return result_document


def validate_precedent(
    data: Any, *, path: str | os.PathLike[str] | None = None
) -> dict[str, Any]:
    source = str(path) if path is not None else None
    precedent = _expect_mapping(data, path=source, field="$precedent")
    result = dict(precedent)
    result["id"] = _validate_id(
        _required(precedent, "id", path=source),
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}",
        path=source,
        field="id",
    )
    date = _required(precedent, "date", path=source)
    if isinstance(date, str):
        try:
            _datetime.date.fromisoformat(date)
        except ValueError as exc:
            raise ValidationError(
                "date must use ISO YYYY-MM-DD format",
                path=source,
                field="date",
                code="invalid_value",
            ) from exc
    elif not isinstance(date, _datetime.date):
        raise ValidationError(
            "date must use ISO YYYY-MM-DD format", path=source, field="date", code="invalid_type"
        )
    for nullable in ("pr", "rule_id", "golden_case"):
        if nullable not in precedent:
            raise ValidationError(
                f"required field {nullable!r} is missing",
                path=source,
                field=nullable,
                code="required_field",
            )
        value = precedent[nullable]
        if value is not None:
            _expect_string(value, path=source, field=nullable, max_length=4096)
    result["architect_action"] = _enum(
        _required(precedent, "architect_action", path=source),
        {"accept", "override", "edit", "missed"},
        path=source,
        field="architect_action",
    )
    for key in ("architect", "rationale"):
        result[key] = _expect_string(
            _required(precedent, key, path=source), path=source, field=key, max_length=20_000
        )
    if "proposed_mutation" not in precedent:
        raise ValidationError(
            "required field 'proposed_mutation' is missing",
            path=source,
            field="proposed_mutation",
            code="required_field",
        )
    mutation = precedent["proposed_mutation"]
    if mutation is not None:
        mutation_mapping = _expect_mapping(mutation, path=source, field="proposed_mutation")
        _enum(
            _required(mutation_mapping, "type", path=source, base="proposed_mutation"),
            {
                "add_exception",
                "adjust_severity",
                "add_rule",
                "activate_rule",
                "deprecate_rule",
            },
            path=source,
            field="proposed_mutation.type",
        )
    status = _expect_string(
        _required(precedent, "status", path=source), path=source, field="status"
    )
    if status not in {"pending", "rejected", "backlog", "distilled"} and not re.fullmatch(
        r"distilled\s*\(\d+\.\d+\.\d+\)", status
    ):
        raise ValidationError(
            "invalid precedent lifecycle status",
            path=source,
            field="status",
            code="invalid_enum",
        )
    return result


def validate_permissions(
    data: Any, *, path: str | os.PathLike[str] | None = None
) -> dict[str, Any]:
    source = str(path) if path is not None else None
    permissions = _expect_mapping(data, path=source, field="$permissions")
    if _required(permissions, "schema", path=source) != "aga.permissions/v1":
        raise ValidationError(
            "permissions schema must be 'aga.permissions/v1'",
            path=source,
            field="schema",
            code="invalid_schema",
        )
    _expect_string(_required(permissions, "role", path=source), path=source, field="role")
    normalised: dict[str, dict[str, list[str]]] = {}
    for section_name in ("allow", "deny"):
        section = _expect_mapping(
            _required(permissions, section_name, path=source), path=source, field=section_name
        )
        normalised[section_name] = {}
        for capability in ("read", "write", "actions"):
            if capability in section:
                normalised[section_name][capability] = _string_list(
                    section[capability],
                    path=source,
                    field=_field(section_name, capability),
                )
            else:
                normalised[section_name][capability] = []
    allow_actions = set(normalised["allow"]["actions"])
    deny_actions = set(normalised["deny"]["actions"])
    overlap = allow_actions & deny_actions
    if overlap:
        raise ValidationError(
            f"actions are both allowed and denied: {sorted(overlap)}",
            path=source,
            field="allow.actions",
            code="permission_conflict",
        )
    required_denied_actions = {"merge", "approve_pr", "push_to_main", "modify_architecture_repo"}
    missing_actions = required_denied_actions - deny_actions
    if missing_actions:
        raise ValidationError(
            f"mandatory denied actions missing: {sorted(missing_actions)}",
            path=source,
            field="deny.actions",
            code="policy_invariant",
        )
    denied_writes = set(normalised["deny"]["write"])
    required_denied_writes = {
        "evolver/fitness.py",
        "evolver/permissions.yaml",
        "golden/corpus.yaml#expected",
        "SKILL.md#section-0",
    }
    missing_writes = required_denied_writes - denied_writes
    if missing_writes:
        raise ValidationError(
            f"mandatory protected writes missing: {sorted(missing_writes)}",
            path=source,
            field="deny.write",
            code="policy_invariant",
        )
    exact_write_overlap = set(normalised["allow"]["write"]) & denied_writes
    if exact_write_overlap:
        raise ValidationError(
            f"write targets are both allowed and denied: {sorted(exact_write_overlap)}",
            path=source,
            field="allow.write",
            code="permission_conflict",
        )
    result = dict(permissions)
    result["allow"] = normalised["allow"]
    result["deny"] = normalised["deny"]
    return result


def load_rules_document(
    path: str | os.PathLike[str],
    *,
    seen_rule_ids: set[str] | None = None,
    supported_detect: Iterable[str] | None = None,
    **yaml_limits: Any,
) -> dict[str, Any]:
    data = strict_load_yaml(path, expected_type=dict, **yaml_limits)
    return validate_rules_document(
        data,
        path=path,
        seen_rule_ids=seen_rule_ids,
        supported_detect=supported_detect,
    )


def load_seaf_document(path: str | os.PathLike[str], **yaml_limits: Any) -> dict[str, Any]:
    return validate_seaf(
        strict_load_yaml(path, expected_type=dict, **yaml_limits), path=path
    )


def load_severity_policy(path: str | os.PathLike[str], **yaml_limits: Any) -> dict[str, Any]:
    return validate_severity_policy(
        strict_load_yaml(path, expected_type=dict, **yaml_limits), path=path
    )


def load_corpus(
    path: str | os.PathLike[str], *, minimum_cases: int = 1, **yaml_limits: Any
) -> dict[str, Any]:
    return validate_corpus(
        strict_load_yaml(path, expected_type=dict, **yaml_limits),
        path=path,
        minimum_cases=minimum_cases,
    )


def load_permissions(path: str | os.PathLike[str], **yaml_limits: Any) -> dict[str, Any]:
    return validate_permissions(
        strict_load_yaml(path, expected_type=dict, **yaml_limits), path=path
    )


def load_precedent(
    path: str | os.PathLike[str],
    *,
    max_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES,
) -> tuple[dict[str, Any], str]:
    source = Path(path)
    raw = _read_file_limited(source, max_bytes=max_bytes, reject_symlinks=True)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError(
            "precedent is not valid UTF-8",
            path=source,
            field=f"byte {exc.start}",
            code="invalid_encoding",
        ) from exc
    metadata, body = parse_frontmatter_strict(text, path=source, require=True)
    return validate_precedent(metadata, path=source), body


def validate_rules_directory(
    rules_dir: str | os.PathLike[str],
    *,
    supported_detect: Iterable[str] | None = None,
    statuses: Iterable[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Validate all rule documents, cross-file IDs, and severity policy."""

    directory = Path(rules_dir)
    try:
        if not directory.resolve(strict=True).is_dir():
            raise OSError("not a directory")
    except (FileNotFoundError, OSError) as exc:
        raise ValidationError(
            "rules directory does not exist or is not a directory",
            path=directory,
            code="path_root_invalid",
        ) from exc
    selected_statuses: frozenset[str] | None = None
    if statuses is not None:
        selected_statuses = frozenset(statuses)
        unknown = selected_statuses - RULE_STATUSES
        if unknown:
            raise ValueError(f"unknown statuses: {sorted(unknown)}")
    seen: set[str] = set()
    all_rules: list[dict[str, Any]] = []
    documents = {
        path.name: path
        for path in directory.glob("*.yaml")
        if path.name != "severity-policy.yaml"
    }
    missing_documents = set(RULE_DOCUMENT_DOMAINS) - set(documents)
    if missing_documents:
        raise ValidationError(
            f"required rule documents are missing: {sorted(missing_documents)}",
            path=directory,
            code="required_file",
        )
    unexpected_documents = set(documents) - set(RULE_DOCUMENT_DOMAINS)
    if unexpected_documents:
        raise ValidationError(
            f"unexpected rule documents: {sorted(unexpected_documents)}",
            path=directory,
            code="invalid_schema",
        )
    for filename in RULE_DOCUMENT_DOMAINS:
        document_path = documents[filename]
        document = load_rules_document(
            document_path,
            seen_rule_ids=seen,
            supported_detect=supported_detect,
        )
        expected_domain = RULE_DOCUMENT_DOMAINS[filename]
        if document["domain"] != expected_domain:
            raise ValidationError(
                f"{filename} must declare domain {expected_domain!r}",
                path=document_path,
                field="domain",
                code="invalid_schema",
            )
        all_rules.extend(
            rule
            for rule in document["rules"]
            if selected_statuses is None or rule["status"] in selected_statuses
        )
    policy_path = directory / "severity-policy.yaml"
    policy = load_severity_policy(policy_path)
    return all_rules, policy


# Compatibility aliases with concise names for integration points.
validate_policy = validate_severity_policy
validate_rules = validate_rules_document


__all__ = [
    "ADR_STATUSES",
    "CHECK_TYPES",
    "DEFAULT_ARTIFACT_EXTENSIONS",
    "DEFAULT_MAX_ALIASES",
    "DEFAULT_MAX_ARTIFACT_BYTES",
    "DEFAULT_MAX_YAML_BYTES",
    "DEFAULT_MAX_YAML_DEPTH",
    "FLOW_PATTERNS",
    "FLOW_ZONES",
    "KNOWN_KINDS",
    "RULE_STATUSES",
    "RULE_DOCUMENT_DOMAINS",
    "SEVERITIES",
    "SUPPORTED_DETECT_OPERATORS",
    "TRANSFER_MODES",
    "ValidationError",
    "condition_matches",
    "dotted_lookup",
    "evaluate_exception_condition",
    "kind_for_artifact_path",
    "load_and_validate_frontmatter",
    "load_corpus",
    "load_manifest",
    "load_permissions",
    "load_precedent",
    "load_rules_document",
    "load_seaf_document",
    "load_severity_policy",
    "parse_frontmatter_strict",
    "safe_artifact_path",
    "safe_read_artifact",
    "strict_load_yaml",
    "strict_load_yaml_text",
    "validate_corpus",
    "validate_exception",
    "validate_exception_condition",
    "validate_frontmatter",
    "validate_review_frontmatter",
    "validate_manifest",
    "validate_permissions",
    "validate_policy",
    "validate_precedent",
    "validate_rule",
    "validate_rules",
    "validate_rules_directory",
    "validate_rules_document",
    "validate_seaf",
    "validate_severity_policy",
]
