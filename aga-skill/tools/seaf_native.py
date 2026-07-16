# -*- coding: utf-8 -*-
"""Safe SEAF/DocHub input adapter for the ``aga.canonical/v2`` contract.

The adapter deliberately accepts one pinned project profile only:
``seaf-core/v1.4.0`` with the ``aga.project/v1`` extension.  Import resolution
is local and fail-closed.  A remote-looking import is never fetched; it must
name an immutable revision, a SHA-256 checksum and a vendored local file.

All filesystem reads pass through :mod:`tools.validation`, which provides the
no-follow/open-at boundary shared by the rest of AGA.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Any, ClassVar, Iterable, Mapping, Sequence
from urllib.parse import urlsplit

from .validation import (
    DEFAULT_MAX_ALIASES,
    DEFAULT_MAX_YAML_BYTES,
    DEFAULT_MAX_YAML_DEPTH,
    DEFAULT_MAX_YAML_NODES,
    ValidationError,
    safe_artifact_path,
    safe_read_artifact,
    strict_load_yaml_text,
)


CANONICAL_SCHEMA = "aga.canonical/v2"
SEAF_SCHEMA = "seaf-core/v1.4.0"
PROJECT_EXTENSION = "aga.project/v1"

DEFAULT_MAX_IMPORT_DEPTH = 32
DEFAULT_MAX_IMPORT_FILES = 256
DEFAULT_MAX_TOTAL_BYTES = 8 * DEFAULT_MAX_YAML_BYTES

_REMOTE_SCHEMES = frozenset({"http", "https", "git", "ssh"})
_EXACT_REVISION = re.compile(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\Z")
_SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")
_KNOWN_ENTITY_SECTIONS = (
    "components",
    "seaf.app.integrations",
    "seaf.change.adr",
    "contexts",
)
_PROJECT_CRITICALITIES = frozenset({"low", "medium", "high", "mission_critical"})
_PROJECT_TARGET_STATUSES = frozenset({"strategic", "tactical", "tolerate", "eliminate"})
_ADR_STATUSES = frozenset({"proposed", "accepted", "deprecated", "superseded"})
_ADR_AREAS = frozenset({"people", "money", "resources", "time", "business", "technology", "other"})
_ADR_VECTORS = frozenset({"negative", "positive", "unknown"})


def _serialise(value: Any) -> Any:
    """Convert frozen contract values into deterministic JSON-compatible data."""

    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _serialise(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _serialise(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_serialise(item) for item in value]
    if isinstance(value, Path):
        return value.as_posix()
    return value


class _Serializable:
    """Small serialisation mixin used by every public canonical value."""

    def as_dict(self) -> dict[str, Any]:
        return _serialise(self)

    to_dict = as_dict


def _require_text(value: Any, *, path: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(
            "expected a non-empty string",
            path=path,
            field=field,
            code="invalid_type",
        )
    return value.strip()


def _optional_text(value: Any, *, path: str, field: str, default: str = "") -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValidationError(
            "expected a string", path=path, field=field, code="invalid_type"
        )
    return value.strip()


def _optional_bool(value: Any, *, path: str, field: str, default: bool = False) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValidationError(
            "expected a boolean", path=path, field=field, code="invalid_type"
        )
    return value


def _string_tuple(value: Any, *, path: str, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValidationError(
            "expected a list of strings", path=path, field=field, code="invalid_type"
        )
    result: list[str] = []
    for index, item in enumerate(value):
        result.append(_require_text(item, path=path, field=f"{field}/{index}"))
    return tuple(result)


def _adr_text(value: Any, *, path: str, field: str) -> str:
    """Normalise the required SEAF v1.4 structured statement list."""

    if not isinstance(value, list):
        raise ValidationError(
            "ADR narrative must be a list of SEAF {area, vector, content} statements",
            path=path,
            field=field,
            code="invalid_type",
        )
    statements: list[str] = []
    for index, statement in enumerate(value):
        item_field = f"{field}/{index}"
        if isinstance(statement, Mapping):
            text = _require_text(statement.get("content"), path=path, field=f"{item_field}/content")
            area = _require_text(
                statement.get("area"), path=path, field=f"{item_field}/area"
            )
            vector = _require_text(
                statement.get("vector"), path=path, field=f"{item_field}/vector"
            )
            if area not in _ADR_AREAS:
                raise ValidationError(
                    f"unsupported ADR area {area!r}", path=path,
                    field=f"{item_field}/area", code="invalid_enum"
                )
            if vector not in _ADR_VECTORS:
                raise ValidationError(
                    f"unsupported ADR vector {vector!r}", path=path,
                    field=f"{item_field}/vector", code="invalid_enum"
                )
            labels = "/".join(part for part in (area, vector) if part)
            if labels:
                text = f"[{labels}] {text}"
        else:
            raise ValidationError(
                "ADR statement must be a string or mapping",
                path=path,
                field=item_field,
                code="invalid_type",
            )
        if text:
            statements.append(text)
    return "\n".join(statements)


@dataclass(frozen=True)
class SourceProvenance(_Serializable):
    """Exact source location for a canonical value.

    ``pointer`` is an RFC 6901 JSON Pointer (the empty string denotes the
    document root).  ``file`` is always repository-root-relative POSIX text.
    """

    file: str
    pointer: str
    commit: str | None = None
    line: int | None = None
    sha256: str | None = None

    def __post_init__(self) -> None:
        if not self.file or Path(self.file).is_absolute() or ".." in PurePosixPath(self.file).parts:
            raise ValueError("SourceProvenance.file must be a safe repository-relative path")
        if self.pointer and not self.pointer.startswith("/"):
            raise ValueError("SourceProvenance.pointer must be an RFC 6901 JSON Pointer")
        if self.line is not None and (isinstance(self.line, bool) or self.line < 1):
            raise ValueError("SourceProvenance.line must be a positive integer")
        if self.sha256 is not None and not _SHA256.fullmatch(self.sha256):
            raise ValueError("SourceProvenance.sha256 must contain 64 hexadecimal characters")


@dataclass(frozen=True)
class System(_Serializable):
    id: str
    name: str
    owner: str
    criticality: str
    target_status: str
    domain: str
    infra: bool
    description: str
    source_ref: SourceProvenance


@dataclass(frozen=True)
class Integration(_Serializable):
    id: str
    name: str
    source: str
    target: str
    description: str
    protocol: str
    pattern: str
    zone: str
    transfer_mode: str
    gateway_controlled: bool
    data_categories: tuple[str, ...]
    approvals: tuple[str, ...]
    source_ref: SourceProvenance


@dataclass(frozen=True)
class ADR(_Serializable):
    id: str
    title: str
    status: str
    context: str
    decision: str
    consequences: str
    source_ref: SourceProvenance


@dataclass(frozen=True)
class Diagram(_Serializable):
    id: str
    title: str
    kind: str
    artifact: str
    components: tuple[str, ...]
    source_ref: SourceProvenance


@dataclass(frozen=True)
class ChangedArtifact(_Serializable):
    path: str
    status: str
    sha256: str | None
    source_ref: SourceProvenance
    changed_pointers: tuple[str, ...] = ()


@dataclass(frozen=True)
class RepositoryRevision(_Serializable):
    base_commit: str
    head_commit: str
    manifest_sha256: str
    archtool_commit: str
    seaf_core_commit: str
    aga_version: str
    rules_sha256: str


@dataclass(frozen=True)
class CanonicalSnapshot(_Serializable):
    """The complete serialisable ``aga.canonical/v2`` document."""

    schema: str
    systems: tuple[System, ...]
    integrations: tuple[Integration, ...]
    adrs: tuple[ADR, ...]
    diagrams: tuple[Diagram, ...]
    changed_artifacts: tuple[ChangedArtifact, ...]
    repository_revision: RepositoryRevision | None
    source_provenance: tuple[SourceProvenance, ...]


@dataclass(frozen=True)
class ResolvedDocument:
    """One safely loaded document in a resolved import closure."""

    path: str
    data: Mapping[str, Any]
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class ResolvedWorkspace:
    """A deterministic, cycle-free DocHub import closure."""

    repository_root: Path
    root: ResolvedDocument
    documents: tuple[ResolvedDocument, ...]
    schema: str
    extensions: tuple[str, ...]
    trusted_dependencies: Mapping[str, str]
    total_bytes: int
    yaml_nodes: int

    @property
    def manifest_sha256(self) -> str:
        return self.root.sha256

    @property
    def import_paths(self) -> tuple[str, ...]:
        return tuple(document.path for document in self.documents if document.path != self.root.path)

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(document.path for document in self.documents)


@dataclass(frozen=True)
class _ImportTarget:
    path: str
    expected_sha256: str | None = None
    revision: str | None = None


def _json_pointer(*parts: str) -> str:
    return "".join("/" + part.replace("~", "~0").replace("/", "~1") for part in parts)


def _count_yaml_nodes(value: Any) -> int:
    """Count constructed YAML values, including mapping key nodes."""

    count = 0
    stack = [value]
    seen: set[int] = set()
    while stack:
        item = stack.pop()
        count += 1
        if isinstance(item, Mapping):
            identity = id(item)
            if identity in seen:
                continue
            seen.add(identity)
            for key, child in item.items():
                stack.append(key)
                stack.append(child)
        elif isinstance(item, list):
            identity = id(item)
            if identity in seen:
                continue
            seen.add(identity)
            stack.extend(item)
    return count


def _validate_root_contract(data: Mapping[str, Any], *, path: str) -> tuple[str, tuple[str, ...]]:
    metadata = data.get("aga")
    if not isinstance(metadata, Mapping):
        raise ValidationError(
            "root manifest must declare aga schema metadata",
            path=path,
            field="/aga",
            code="schema_missing",
        )
    schema = metadata.get("schema")
    if schema != SEAF_SCHEMA:
        raise ValidationError(
            f"unsupported SEAF schema/version {schema!r}; expected {SEAF_SCHEMA!r}",
            path=path,
            field="/aga/schema",
            code="schema_unsupported",
        )
    extensions_value = metadata.get("extensions")
    if not isinstance(extensions_value, list) or any(
        not isinstance(item, str) or not item for item in extensions_value
    ):
        raise ValidationError(
            "aga.extensions must be a list of versioned extension identifiers",
            path=path,
            field="/aga/extensions",
            code="extension_missing",
        )
    extensions = tuple(extensions_value)
    if PROJECT_EXTENSION not in extensions:
        raise ValidationError(
            f"required project extension {PROJECT_EXTENSION!r} is missing",
            path=path,
            field="/aga/extensions",
            code="extension_missing",
        )
    unknown = sorted(set(extensions) - {PROJECT_EXTENSION})
    if unknown:
        raise ValidationError(
            f"unsupported project extension(s): {unknown}",
            path=path,
            field="/aga/extensions",
            code="extension_unsupported",
        )
    classification = metadata.get("data_classification")
    if classification != "synthetic-public":
        raise ValidationError(
            "aga.project/v1 requires data_classification: synthetic-public",
            path=path,
            field="/aga/data_classification",
            code="extension_field_missing",
        )
    unknown_metadata = sorted(set(metadata) - {"schema", "extensions", "data_classification"})
    if unknown_metadata:
        raise ValidationError(
            f"unknown aga.project/v1 metadata fields: {unknown_metadata}",
            path=path,
            field="/aga",
            code="extension_field_unsupported",
        )
    return schema, extensions


def _validate_section_mappings(documents: Sequence[ResolvedDocument]) -> None:
    """Reject duplicate IDs and conflicting definitions before adaptation."""

    seen: dict[str, tuple[str, Mapping[str, Any], str]] = {}
    for document in documents:
        for section_name in _KNOWN_ENTITY_SECTIONS:
            if section_name not in document.data:
                continue
            section = document.data[section_name]
            if not isinstance(section, Mapping):
                raise ValidationError(
                    "SEAF entity section must be a mapping",
                    path=document.path,
                    field=_json_pointer(section_name),
                    code="invalid_type",
                )
            for raw_id, raw_definition in section.items():
                entity_id = _require_text(
                    raw_id,
                    path=document.path,
                    field=_json_pointer(section_name),
                )
                if not isinstance(raw_definition, Mapping):
                    raise ValidationError(
                        "SEAF entity definition must be a mapping",
                        path=document.path,
                        field=_json_pointer(section_name, entity_id),
                        code="invalid_type",
                    )
                previous = seen.get(entity_id)
                if previous is None:
                    seen[entity_id] = (section_name, raw_definition, document.path)
                    continue
                previous_section, previous_definition, previous_path = previous
                conflicting = previous_section != section_name or previous_definition != raw_definition
                raise ValidationError(
                    (
                        f"conflicting definition for ID {entity_id!r}; first defined in "
                        f"{previous_path}"
                        if conflicting
                        else f"duplicate ID {entity_id!r}; first defined in {previous_path}"
                    ),
                    path=document.path,
                    field=_json_pointer(section_name, entity_id),
                    code="conflicting_definition" if conflicting else "duplicate_id",
                )


def _validate_project_extension_loaded(documents: Sequence[ResolvedDocument]) -> None:
    """Prove that the declared project extension package is in the import closure."""

    matches: list[ResolvedDocument] = []
    for document in documents:
        package = document.data.get("$package")
        if not isinstance(package, Mapping):
            continue
        metadata = package.get("aga-project")
        if not isinstance(metadata, Mapping):
            continue
        if metadata.get("version") != "1.0.0":
            raise ValidationError(
                "aga-project package version must be 1.0.0 for aga.project/v1",
                path=document.path,
                field="/$package/aga-project/version",
                code="extension_unsupported",
            )
        matches.append(document)
    if len(matches) != 1:
        raise ValidationError(
            "aga.project/v1 must be loaded exactly once through $package.aga-project",
            path=documents[0].path if documents else None,
            field="/$package/aga-project",
            code="extension_missing" if not matches else "duplicate_extension",
        )
    extension = matches[0]
    if documents and extension.path == documents[0].path:
        raise ValidationError(
            "aga.project/v1 must be a separate imported schema document",
            path=extension.path,
            field="/$package/aga-project",
            code="extension_inline_forbidden",
        )

    entities = extension.data.get("entities")
    if not isinstance(entities, Mapping):
        raise ValidationError(
            "aga.project/v1 package must define its entity schemas",
            path=extension.path,
            field="/entities",
            code="extension_invalid",
        )

    def entity_schema(name: str) -> Mapping[str, Any]:
        entity = entities.get(name)
        schema = entity.get("schema") if isinstance(entity, Mapping) else None
        if not isinstance(schema, Mapping):
            raise ValidationError(
                f"aga.project/v1 is missing schema for {name}",
                path=extension.path,
                field=_json_pointer("entities", name, "schema"),
                code="extension_invalid",
            )
        return schema

    aga_schema = entity_schema("aga")
    aga_properties = aga_schema.get("properties")
    if (
        not isinstance(aga_properties, Mapping)
        or not isinstance(aga_properties.get("schema"), Mapping)
        or aga_properties["schema"].get("const") != SEAF_SCHEMA
        or not isinstance(aga_properties.get("extensions"), Mapping)
        or not isinstance(aga_properties["extensions"].get("contains"), Mapping)
        or aga_properties["extensions"]["contains"].get("const") != PROJECT_EXTENSION
        or not isinstance(aga_properties.get("data_classification"), Mapping)
        or aga_properties["data_classification"].get("const") != "synthetic-public"
        or set(aga_schema.get("required", ()))
        != {"schema", "extensions", "data_classification"}
        or aga_schema.get("additionalProperties") is not False
    ):
        raise ValidationError(
            "aga.project/v1 workspace metadata schema does not match the contract",
            path=extension.path,
            field="/entities/aga/schema",
            code="extension_invalid",
        )

    component_schema = entity_schema("components")
    patterns = component_schema.get("patternProperties")
    component_items = list(patterns.values()) if isinstance(patterns, Mapping) else []
    valid_component = False
    for item in component_items:
        properties = item.get("properties") if isinstance(item, Mapping) else None
        if not isinstance(properties, Mapping):
            continue
        criticality = properties.get("criticality")
        target_status = properties.get("target_status")
        if (
            isinstance(properties.get("owner"), Mapping)
            and isinstance(criticality, Mapping)
            and set(criticality.get("enum", ())) == _PROJECT_CRITICALITIES
            and isinstance(target_status, Mapping)
            and set(target_status.get("enum", ())) == _PROJECT_TARGET_STATUSES
            and set(item.get("required", ()))
            == {"owner", "criticality", "target_status"}
        ):
            valid_component = True
            break
    if not valid_component:
        raise ValidationError(
            "aga.project/v1 component governance fields do not match the contract",
            path=extension.path,
            field="/entities/components/schema",
            code="extension_invalid",
        )

    integration_schema = entity_schema("seaf.app.integrations")
    integration_patterns = integration_schema.get("patternProperties")
    integration_items = (
        list(integration_patterns.values()) if isinstance(integration_patterns, Mapping) else []
    )
    expected_integration_fields = {
        "protocol", "pattern", "zone", "transfer_mode", "gateway_controlled",
        "data_categories", "approvals",
    }
    if not any(
        isinstance(item, Mapping)
        and isinstance(item.get("properties"), Mapping)
        and expected_integration_fields <= set(item["properties"])
        for item in integration_items
    ):
        raise ValidationError(
            "aga.project/v1 integration fields do not match the contract",
            path=extension.path,
            field="/entities/seaf.app.integrations/schema",
            code="extension_invalid",
        )

    adr_schema = entity_schema("seaf.change.adr")
    definitions = adr_schema.get("$defs")
    adr_definition = definitions.get("seaf.change.adr") if isinstance(definitions, Mapping) else None
    adr_properties = adr_definition.get("properties") if isinstance(adr_definition, Mapping) else None
    status_schema = adr_properties.get("status") if isinstance(adr_properties, Mapping) else None
    if not isinstance(status_schema, Mapping) or set(status_schema.get("enum", ())) != _ADR_STATUSES:
        raise ValidationError(
            "aga.project/v1 ADR status schema does not match the contract",
            path=extension.path,
            field="/entities/seaf.change.adr/schema",
            code="extension_invalid",
        )


class DocHubImportResolver:
    """Resolve a bounded SEAF/DocHub YAML import graph beneath one repository."""

    def __init__(
        self,
        repository_root: str | Path,
        *,
        max_file_bytes: int = DEFAULT_MAX_YAML_BYTES,
        max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
        max_depth: int = DEFAULT_MAX_IMPORT_DEPTH,
        max_files: int = DEFAULT_MAX_IMPORT_FILES,
        max_yaml_nodes: int = DEFAULT_MAX_YAML_NODES,
        max_yaml_depth: int = DEFAULT_MAX_YAML_DEPTH,
        max_aliases: int = DEFAULT_MAX_ALIASES,
        trusted_dependencies: Mapping[str, str] | None = None,
    ) -> None:
        try:
            root = Path(repository_root).resolve(strict=True)
        except (FileNotFoundError, OSError) as exc:
            raise ValidationError(
                "repository root does not exist or cannot be resolved",
                path=repository_root,
                code="path_root_invalid",
            ) from exc
        if not root.is_dir():
            raise ValidationError(
                "repository root is not a directory",
                path=repository_root,
                code="path_root_invalid",
            )
        limits = {
            "max_file_bytes": max_file_bytes,
            "max_total_bytes": max_total_bytes,
            "max_depth": max_depth,
            "max_files": max_files,
            "max_yaml_nodes": max_yaml_nodes,
            "max_yaml_depth": max_yaml_depth,
            "max_aliases": max_aliases,
        }
        for name, value in limits.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        self.repository_root = root
        self.max_file_bytes = max_file_bytes
        self.max_total_bytes = max_total_bytes
        self.max_depth = max_depth
        self.max_files = max_files
        self.max_yaml_nodes = max_yaml_nodes
        self.max_yaml_depth = max_yaml_depth
        self.max_aliases = max_aliases
        if trusted_dependencies is None:
            trusted_dependencies = {}
        if not isinstance(trusted_dependencies, Mapping):
            raise ValueError("trusted_dependencies must map local prefixes to commit SHAs")
        validated_dependencies: dict[str, str] = {}
        for raw_prefix, revision in trusted_dependencies.items():
            prefix = self._normalise_relative_path(
                raw_prefix, source="trusted_dependencies", field=str(raw_prefix)
            )
            if not isinstance(revision, str) or not _EXACT_REVISION.fullmatch(revision):
                raise ValueError("trusted_dependencies must contain only full commit SHAs")
            if prefix in validated_dependencies:
                raise ValueError("trusted dependency prefixes must be unique")
            validated_dependencies[prefix] = revision.lower()
        self.trusted_dependencies = MappingProxyType(validated_dependencies)

    @staticmethod
    def _normalise_relative_path(value: Any, *, source: str, field: str) -> str:
        text = _require_text(value, path=source, field=field)
        windows = PureWindowsPath(text)
        if Path(text).is_absolute() or windows.is_absolute() or windows.drive:
            raise ValidationError(
                "absolute import path is not allowed",
                path=source,
                field=field,
                code="path_absolute",
            )
        portable = text.replace("\\", "/")
        parts = portable.split("/")
        if ".." in parts:
            raise ValidationError(
                "parent traversal is not allowed",
                path=source,
                field=field,
                code="path_traversal",
            )
        if not parts or any(part in {"", "."} for part in parts):
            raise ValidationError(
                "import path is not canonical",
                path=source,
                field=field,
                code="invalid_path",
            )
        return PurePosixPath(*parts).as_posix()

    @staticmethod
    def _is_remote(value: str) -> bool:
        parsed = urlsplit(value)
        return parsed.scheme.lower() in _REMOTE_SCHEMES or bool(parsed.netloc)

    def _parse_import_item(self, item: Any, *, source: str, field: str) -> _ImportTarget:
        if isinstance(item, str):
            if self._is_remote(item):
                raise ValidationError(
                    "remote import requires an exact revision, sha256 and vendored path",
                    path=source,
                    field=field,
                    code="remote_import_unpinned",
                )
            return _ImportTarget(self._normalise_relative_path(item, source=source, field=field))
        if not isinstance(item, Mapping):
            raise ValidationError(
                "import must be a local path or pinned import mapping",
                path=source,
                field=field,
                code="invalid_type",
            )

        remote = item.get("url", item.get("uri"))
        if remote is None:
            local = item.get("path", item.get("local"))
            if local is None:
                raise ValidationError(
                    "local import mapping must contain path",
                    path=source,
                    field=field,
                    code="invalid_import",
                )
            return _ImportTarget(
                self._normalise_relative_path(local, source=source, field=f"{field}/path")
            )
        remote_text = _require_text(remote, path=source, field=f"{field}/url")
        if not self._is_remote(remote_text):
            raise ValidationError(
                "url/uri import must use an explicit remote URI scheme",
                path=source,
                field=f"{field}/url",
                code="invalid_import",
            )
        revision = item.get("revision", item.get("ref", item.get("pin")))
        checksum = item.get("sha256")
        local = item.get("path", item.get("local"))
        if (
            not isinstance(revision, str)
            or not _EXACT_REVISION.fullmatch(revision)
            or not isinstance(checksum, str)
            or not _SHA256.fullmatch(checksum)
            or local is None
        ):
            raise ValidationError(
                "remote import requires an exact hexadecimal revision, sha256 and vendored path",
                path=source,
                field=field,
                code="remote_import_unpinned",
            )
        return _ImportTarget(
            self._normalise_relative_path(local, source=source, field=f"{field}/path"),
            checksum.lower(),
            revision.lower(),
        )

    def _imports(self, document: ResolvedDocument) -> tuple[_ImportTarget, ...]:
        raw = document.data.get("imports", [])
        if raw is None:
            return ()
        if isinstance(raw, list):
            return tuple(
                self._parse_import_item(
                    item,
                    source=document.path,
                    field=_json_pointer("imports", str(index)),
                )
                for index, item in enumerate(raw)
            )
        if isinstance(raw, Mapping):
            # DocHub also uses ``imports`` as a package catalogue.  Accept only
            # its closed metadata shape; entries do not identify files.
            allowed = {"name", "vendor", "description", "version"}
            for package, metadata in raw.items():
                package_id = _require_text(
                    package, path=document.path, field=_json_pointer("imports")
                )
                if not isinstance(metadata, Mapping) or "version" not in metadata:
                    raise ValidationError(
                        "package import metadata must contain a version",
                        path=document.path,
                        field=_json_pointer("imports", package_id),
                        code="invalid_import",
                    )
                unknown = set(metadata) - allowed
                if unknown:
                    raise ValidationError(
                        f"unknown package import fields: {sorted(unknown)}",
                        path=document.path,
                        field=_json_pointer("imports", package_id),
                        code="invalid_import",
                    )
                _require_text(
                    metadata["version"],
                    path=document.path,
                    field=_json_pointer("imports", package_id, "version"),
                )
            return ()
        raise ValidationError(
            "imports must be a list or a DocHub package catalogue",
            path=document.path,
            field=_json_pointer("imports"),
            code="invalid_type",
        )

    def resolve(self, manifest_path: str | Path = "dochub.yaml") -> ResolvedWorkspace:
        root_relative = self._normalise_relative_path(
            str(manifest_path), source=str(manifest_path), field="manifest_path"
        )
        documents: list[ResolvedDocument] = []
        loaded: dict[str, ResolvedDocument] = {}
        visiting: list[str] = []
        total_bytes = 0
        total_nodes = 0

        def visit(relative_path: str, *, depth: int, expected_sha256: str | None = None) -> None:
            nonlocal total_bytes, total_nodes
            if relative_path in visiting:
                cycle = visiting[visiting.index(relative_path) :] + [relative_path]
                raise ValidationError(
                    f"import cycle detected: {' -> '.join(cycle)}",
                    path=relative_path,
                    field="/imports",
                    code="import_cycle",
                )
            if depth > self.max_depth:
                raise ValidationError(
                    f"import depth limit exceeded ({self.max_depth})",
                    path=relative_path,
                    code="import_depth_limit",
                )
            if relative_path in loaded:
                if expected_sha256 and loaded[relative_path].sha256 != expected_sha256:
                    raise ValidationError(
                        "vendored import checksum mismatch",
                        path=relative_path,
                        field="sha256",
                        code="import_checksum_mismatch",
                    )
                return
            if len(loaded) >= self.max_files:
                raise ValidationError(
                    f"import file limit exceeded ({self.max_files})",
                    path=relative_path,
                    code="import_file_limit",
                )

            text = safe_read_artifact(
                self.repository_root,
                relative_path,
                allowed_extensions={".yaml", ".yml"},
                max_bytes=self.max_file_bytes,
                reject_symlinks=True,
                reject_hardlinks=True,
            )
            raw = text.encode("utf-8")
            checksum = hashlib.sha256(raw).hexdigest()
            if expected_sha256 and checksum != expected_sha256:
                raise ValidationError(
                    "vendored import checksum mismatch",
                    path=relative_path,
                    field="sha256",
                    code="import_checksum_mismatch",
                )
            total_bytes += len(raw)
            if total_bytes > self.max_total_bytes:
                raise ValidationError(
                    f"import graph byte limit exceeded ({self.max_total_bytes})",
                    path=relative_path,
                    code="import_byte_limit",
                )
            data = strict_load_yaml_text(
                text,
                source=relative_path,
                expected_type=dict,
                max_bytes=self.max_file_bytes,
                max_aliases=self.max_aliases,
                max_depth=self.max_yaml_depth,
                max_nodes=self.max_yaml_nodes,
            )
            node_count = _count_yaml_nodes(data)
            total_nodes += node_count
            if total_nodes > self.max_yaml_nodes:
                raise ValidationError(
                    f"import graph YAML node limit exceeded ({self.max_yaml_nodes})",
                    path=relative_path,
                    code="yaml_node_limit",
                )
            document = ResolvedDocument(
                path=relative_path,
                data=MappingProxyType(data),
                sha256=checksum,
                size_bytes=len(raw),
            )
            loaded[relative_path] = document
            documents.append(document)
            visiting.append(relative_path)
            try:
                parent = PurePosixPath(relative_path).parent
                for target in self._imports(document):
                    combined = (
                        PurePosixPath(target.path)
                        if parent == PurePosixPath(".")
                        else parent / target.path
                    ).as_posix()
                    combined = self._normalise_relative_path(
                        combined, source=relative_path, field="/imports"
                    )
                    if target.revision is not None:
                        matching_dependencies = [
                            (prefix, commit)
                            for prefix, commit in self.trusted_dependencies.items()
                            if combined == prefix or combined.startswith(prefix + "/")
                        ]
                        if (
                            len(matching_dependencies) != 1
                            or matching_dependencies[0][1] != target.revision
                        ):
                            raise ValidationError(
                                "remote import path and revision are not backed by one trusted dependency",
                                path=combined,
                                field="/imports/revision",
                                code="remote_import_revision_unverified",
                            )
                    visit(combined, depth=depth + 1, expected_sha256=target.expected_sha256)
            finally:
                visiting.pop()

        visit(root_relative, depth=0)
        root_document = loaded[root_relative]
        schema, extensions = _validate_root_contract(root_document.data, path=root_relative)
        _validate_project_extension_loaded(documents)
        _validate_section_mappings(documents)
        return ResolvedWorkspace(
            repository_root=self.repository_root,
            root=root_document,
            documents=tuple(documents),
            schema=schema,
            extensions=extensions,
            trusted_dependencies=MappingProxyType(dict(self.trusted_dependencies)),
            total_bytes=total_bytes,
            yaml_nodes=total_nodes,
        )


class SeafCanonicalAdapter:
    """Map a resolved SEAF v1.4.0 workspace into ``aga.canonical/v2``."""

    schema: ClassVar[str] = CANONICAL_SCHEMA

    @staticmethod
    def _source_ref(
        document: ResolvedDocument,
        section: str,
        entity_id: str,
        source_commit: str | None,
    ) -> SourceProvenance:
        return SourceProvenance(
            file=document.path,
            pointer=_json_pointer(section, entity_id),
            commit=source_commit,
            sha256=document.sha256,
        )

    @staticmethod
    def _document_commit(
        workspace: ResolvedWorkspace,
        document: ResolvedDocument,
        revision: RepositoryRevision | None,
    ) -> str | None:
        matches = [
            commit
            for prefix, commit in workspace.trusted_dependencies.items()
            if document.path == prefix or document.path.startswith(prefix + "/")
        ]
        if len(matches) > 1:
            raise ValidationError(
                "document is covered by more than one trusted dependency",
                path=document.path,
                code="ambiguous_dependency_provenance",
            )
        return matches[0] if matches else revision.head_commit if revision else None

    def _system(
        self,
        entity_id: str,
        item: Mapping[str, Any],
        document: ResolvedDocument,
        source_commit: str | None,
    ) -> System:
        base = _json_pointer("components", entity_id)
        missing = [name for name in ("title", "entity", "owner", "criticality", "target_status")
                   if name not in item]
        if missing:
            raise ValidationError(
                f"{PROJECT_EXTENSION} required field(s) missing: {missing}",
                path=document.path,
                field=base,
                code="extension_field_missing",
            )
        owner = _require_text(item["owner"], path=document.path, field=f"{base}/owner")
        title = _require_text(item["title"], path=document.path, field=f"{base}/title")
        _require_text(item["entity"], path=document.path, field=f"{base}/entity")
        criticality = _require_text(
            item["criticality"], path=document.path, field=f"{base}/criticality"
        )
        if criticality not in _PROJECT_CRITICALITIES:
            raise ValidationError(
                f"unsupported criticality {criticality!r}",
                path=document.path,
                field=f"{base}/criticality",
                code="invalid_enum",
            )
        target_status = _require_text(
            item["target_status"], path=document.path, field=f"{base}/target_status"
        )
        if target_status not in _PROJECT_TARGET_STATUSES:
            raise ValidationError(
                f"unsupported target_status {target_status!r}",
                path=document.path,
                field=f"{base}/target_status",
                code="invalid_enum",
            )
        return System(
            id=entity_id,
            name=title,
            owner=owner,
            criticality=criticality,
            target_status=target_status,
            domain=_optional_text(
                item.get("domain"), path=document.path, field=f"{base}/domain"
            ),
            infra=_optional_bool(
                item.get("infra"), path=document.path, field=f"{base}/infra"
            ),
            description=_optional_text(
                item.get("description"), path=document.path, field=f"{base}/description"
            ),
            source_ref=self._source_ref(document, "components", entity_id, source_commit),
        )

    def _integration(
        self,
        entity_id: str,
        item: Mapping[str, Any],
        document: ResolvedDocument,
        source_commit: str | None,
    ) -> Integration:
        base = _json_pointer("seaf.app.integrations", entity_id)
        missing = [name for name in ("title", "description", "from", "to") if name not in item]
        if missing:
            raise ValidationError(
                f"seaf-core/v1.4.0 integration required field(s) missing: {missing}",
                path=document.path, field=base, code="required"
            )
        title = _require_text(item["title"], path=document.path, field=f"{base}/title")
        description = _require_text(
            item["description"], path=document.path, field=f"{base}/description"
        )
        source = _require_text(item.get("from"), path=document.path, field=f"{base}/from")
        target = _require_text(item.get("to"), path=document.path, field=f"{base}/to")
        return Integration(
            id=entity_id,
            name=title,
            source=source,
            target=target,
            description=description,
            protocol=_optional_text(
                item.get("protocol", item.get("technology")),
                path=document.path,
                field=f"{base}/protocol|technology",
            ),
            pattern=_optional_text(
                item.get("pattern"), path=document.path, field=f"{base}/pattern"
            ),
            zone=_optional_text(item.get("zone"), path=document.path, field=f"{base}/zone"),
            transfer_mode=_optional_text(
                item.get("transfer_mode"),
                path=document.path,
                field=f"{base}/transfer_mode",
            ),
            gateway_controlled=_optional_bool(
                item.get("gateway_controlled"),
                path=document.path,
                field=f"{base}/gateway_controlled",
            ),
            data_categories=_string_tuple(
                item.get("data_categories"),
                path=document.path,
                field=f"{base}/data_categories",
            ),
            approvals=_string_tuple(
                item.get("approvals"), path=document.path, field=f"{base}/approvals"
            ),
            source_ref=self._source_ref(
                document, "seaf.app.integrations", entity_id, source_commit
            ),
        )

    def _adr(
        self,
        entity_id: str,
        item: Mapping[str, Any],
        document: ResolvedDocument,
        source_commit: str | None,
    ) -> ADR:
        base = _json_pointer("seaf.change.adr", entity_id)
        required = ("title", "moment", "issue", "decision", "status", "context", "consequences")
        missing = [name for name in required if name not in item]
        if missing:
            raise ValidationError(
                f"seaf-core/v1.4.0 ADR required field(s) missing: {missing}",
                path=document.path, field=base, code="required"
            )
        title = _require_text(item["title"], path=document.path, field=f"{base}/title")
        moment = _require_text(item["moment"], path=document.path, field=f"{base}/moment")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", moment):
            raise ValidationError(
                "ADR moment must use YYYY-MM-DD", path=document.path,
                field=f"{base}/moment", code="invalid_format"
            )
        issue = _require_text(item["issue"], path=document.path, field=f"{base}/issue")
        decision = _require_text(
            item["decision"], path=document.path, field=f"{base}/decision"
        )
        status = _require_text(item["status"], path=document.path, field=f"{base}/status")
        if status not in _ADR_STATUSES:
            raise ValidationError(
                f"unsupported ADR status {status!r}", path=document.path,
                field=f"{base}/status", code="invalid_enum"
            )
        context = _adr_text(
            item.get("context"), path=document.path, field=f"{base}/context"
        )
        if issue:
            context = "\n".join(part for part in (issue, context) if part)
        return ADR(
            id=entity_id,
            title=title,
            status=status,
            context=context,
            decision=decision,
            consequences=_adr_text(
                item.get("consequences"),
                path=document.path,
                field=f"{base}/consequences",
            ),
            source_ref=self._source_ref(
                document, "seaf.change.adr", entity_id, source_commit
            ),
        )

    @staticmethod
    def _diagram_artifact(
        value: Any,
        *,
        workspace: ResolvedWorkspace,
        document: ResolvedDocument,
        field: str,
    ) -> str:
        artifact = _optional_text(value, path=document.path, field=field)
        if not artifact:
            return ""
        windows = PureWindowsPath(artifact)
        if Path(artifact).is_absolute() or windows.is_absolute() or windows.drive:
            raise ValidationError(
                "absolute diagram artifact path is not allowed",
                path=document.path,
                field=field,
                code="path_absolute",
            )
        if DocHubImportResolver._is_remote(artifact):
            raise ValidationError(
                "remote diagram artifacts are not allowed",
                path=document.path,
                field=field,
                code="remote_artifact",
            )
        parts: list[str] = list(PurePosixPath(document.path).parent.parts)
        for part in artifact.replace("\\", "/").split("/"):
            if part in {"", "."}:
                continue
            if part == "..":
                if not parts:
                    raise ValidationError(
                        "diagram artifact escapes the repository root",
                        path=document.path,
                        field=field,
                        code="path_outside_root",
                    )
                parts.pop()
            else:
                parts.append(part)
        if not parts:
            raise ValidationError(
                "diagram artifact path is empty",
                path=document.path,
                field=field,
                code="invalid_path",
            )
        relative = PurePosixPath(*parts).as_posix()
        safe_artifact_path(
            workspace.repository_root,
            relative,
            allowed_extensions={".puml", ".plantuml", ".mmd", ".drawio", ".yaml", ".yml"},
            reject_symlinks=True,
            reject_hardlinks=True,
        )
        return relative

    def _diagram(
        self,
        entity_id: str,
        item: Mapping[str, Any],
        document: ResolvedDocument,
        workspace: ResolvedWorkspace,
        source_commit: str | None,
    ) -> Diagram:
        base = _json_pointer("contexts", entity_id)
        artifact = self._diagram_artifact(
            item.get(
                "template", item.get("source", item.get("artifact", item.get("uml")))
            ),
            workspace=workspace,
            document=document,
            field=f"{base}/template|source|artifact|uml",
        )
        kind = _optional_text(
            item.get("format", item.get("type", item.get("presentation"))),
            path=document.path,
            field=f"{base}/format|type|presentation",
        )
        if not kind and artifact:
            suffix = PurePosixPath(artifact).suffix.lower()
            kind = {".puml": "plantuml", ".plantuml": "plantuml", ".mmd": "mermaid"}.get(
                suffix, "context"
            )
        return Diagram(
            id=entity_id,
            title=_optional_text(
                item.get("title", item.get("name")),
                path=document.path,
                field=f"{base}/title|name",
                default=entity_id,
            )
            or entity_id,
            kind=kind or "context",
            artifact=artifact,
            components=_string_tuple(
                item.get("components"), path=document.path, field=f"{base}/components"
            ),
            source_ref=self._source_ref(document, "contexts", entity_id, source_commit),
        )

    def adapt(
        self,
        workspace: ResolvedWorkspace,
        *,
        revision: RepositoryRevision | None = None,
        changed_artifacts: Iterable[ChangedArtifact] = (),
    ) -> CanonicalSnapshot:
        if workspace.schema != SEAF_SCHEMA or workspace.extensions != (PROJECT_EXTENSION,):
            raise ValidationError(
                "resolved workspace does not use the supported SEAF/project schema",
                path=workspace.root.path,
                field="/aga",
                code="schema_unsupported",
            )

        systems: list[System] = []
        integrations: list[Integration] = []
        adrs: list[ADR] = []
        diagrams: list[Diagram] = []
        provenance: list[SourceProvenance] = []
        for document in workspace.documents:
            source_commit = self._document_commit(workspace, document, revision)
            section = document.data.get("components", {})
            for entity_id, item in section.items():
                system = self._system(str(entity_id), item, document, source_commit)
                systems.append(system)
                provenance.append(system.source_ref)
            section = document.data.get("seaf.app.integrations", {})
            for entity_id, item in section.items():
                integration = self._integration(
                    str(entity_id), item, document, source_commit
                )
                integrations.append(integration)
                provenance.append(integration.source_ref)
            section = document.data.get("seaf.change.adr", {})
            for entity_id, item in section.items():
                adr = self._adr(str(entity_id), item, document, source_commit)
                adrs.append(adr)
                provenance.append(adr.source_ref)
            section = document.data.get("contexts", {})
            for entity_id, item in section.items():
                diagram = self._diagram(
                    str(entity_id), item, document, workspace, source_commit
                )
                diagrams.append(diagram)
                provenance.append(diagram.source_ref)

        changes = tuple(changed_artifacts)
        if any(not isinstance(item, ChangedArtifact) for item in changes):
            raise TypeError("changed_artifacts must contain ChangedArtifact values")
        provenance.extend(item.source_ref for item in changes)
        key = lambda item: item.id
        return CanonicalSnapshot(
            schema=CANONICAL_SCHEMA,
            systems=tuple(sorted(systems, key=key)),
            integrations=tuple(sorted(integrations, key=key)),
            adrs=tuple(sorted(adrs, key=key)),
            diagrams=tuple(sorted(diagrams, key=key)),
            changed_artifacts=tuple(sorted(changes, key=lambda item: item.path)),
            repository_revision=revision,
            source_provenance=tuple(
                sorted(provenance, key=lambda item: (item.file, item.pointer))
            ),
        )


def load_seaf_native(
    repository_root: str | Path,
    manifest_path: str | Path = "dochub.yaml",
    *,
    revision: RepositoryRevision | None = None,
    changed_artifacts: Iterable[ChangedArtifact] = (),
    **resolver_limits: int,
) -> CanonicalSnapshot:
    """Resolve and adapt one repository in a single fail-closed operation."""

    workspace = DocHubImportResolver(repository_root, **resolver_limits).resolve(manifest_path)
    return SeafCanonicalAdapter().adapt(
        workspace, revision=revision, changed_artifacts=changed_artifacts
    )


__all__ = [
    "ADR",
    "CANONICAL_SCHEMA",
    "CanonicalSnapshot",
    "ChangedArtifact",
    "DEFAULT_MAX_IMPORT_DEPTH",
    "DEFAULT_MAX_IMPORT_FILES",
    "DEFAULT_MAX_TOTAL_BYTES",
    "Diagram",
    "DocHubImportResolver",
    "Integration",
    "PROJECT_EXTENSION",
    "RepositoryRevision",
    "ResolvedDocument",
    "ResolvedWorkspace",
    "SEAF_SCHEMA",
    "SeafCanonicalAdapter",
    "SourceProvenance",
    "System",
    "load_seaf_native",
]
