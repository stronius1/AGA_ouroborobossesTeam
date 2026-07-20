# -*- coding: utf-8 -*-
"""Loop-B remediation: turn one AGA finding into a minimal, auditable patch
against the project-owned architecture model.

Scope (MVP): rule ``SEAF-004`` only ("no new dependency on an
eliminate-status system"). The proposed mutation reroutes the flagged flow
endpoint to the eliminate-status component's own declared successor
(``replaced_by``). The successor is never guessed: it must already be
declared, by the architecture's own owner, on the eliminated component's
record. If no successor is declared -- or the declared successor does not
resolve to a live, non-eliminated component -- this module refuses to
propose a patch and raises :class:`RemediationNotAvailable`. That failure is
not an error to swallow; it is the correct fail-closed outcome: no safe
automatic target exists, and only a human architect can decide one (mirrors
the never-hallucinate-a-target discipline already enforced elsewhere, e.g.
``evolver/policy.py`` and ``tools/validation.py``).

This module never writes to disk and never opens a pull request. It only
proposes text. Applying the patch to a scratch snapshot and re-running the
review to confirm the target finding is closed and no new finding appeared
is the remediation gate's job (``scripts/run_remediation.py``). Publishing a
draft PR is ``tools/publisher.py``'s job. No merge path exists anywhere in
this module.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from tools.validation import safe_read_artifact, strict_load_yaml_text

SUPPORTED_RULES = ("SEAF-004",)
COMPONENT_ID_RE = re.compile(
    r"^[a-zA-Z][a-zA-Z0-9_-]*(?:\.[a-zA-Z0-9][a-zA-Z0-9_-]*)*$"
)
INTEGRATION_ID_RE = re.compile(
    r"^[a-z0-9][a-z0-9_-]*(?:\.[a-z0-9][a-z0-9_-]*)+$"
)
SAFE_SUCCESSOR_STATUSES = frozenset({"strategic", "tactical", "tolerate"})

__all__ = [
    "COMPONENT_ID_RE",
    "INTEGRATION_ID_RE",
    "RemediationNotAvailable",
    "RemediationPatch",
    "SAFE_SUCCESSOR_STATUSES",
    "SUPPORTED_RULES",
    "propose_remediation",
]


class RemediationNotAvailable(Exception):
    """No deterministic, non-hallucinated patch can be proposed for a finding."""

    def __init__(self, reason: str, *, code: str):
        self.reason = reason
        self.code = code
        super().__init__(reason)


@dataclass(frozen=True)
class RemediationPatch:
    """A minimal, line-scoped textual patch for one architecture artifact."""

    rule_id: str
    entity_id: str
    artifact: str
    mutation_kind: str
    endpoint: str
    eliminated_component: str
    replacement_component: str
    before_text: str
    after_text: str
    summary: str

    @staticmethod
    def _sha256(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @property
    def before_sha256(self) -> str:
        return self._sha256(self.before_text)

    @property
    def after_sha256(self) -> str:
        return self._sha256(self.after_text)

    @property
    def diff_sha256(self) -> str:
        return self._sha256(self.unified_diff())

    def unified_diff(self) -> str:
        return "".join(
            difflib.unified_diff(
                self.before_text.splitlines(keepends=True),
                self.after_text.splitlines(keepends=True),
                fromfile=f"a/{self.artifact}",
                tofile=f"b/{self.artifact}",
            )
        )

    def as_dict(self) -> dict[str, Any]:
        candidate = self.candidate_dict()
        return {
            **candidate,
            "diff": self.unified_diff(),
        }

    def candidate_dict(self) -> dict[str, Any]:
        """Return the strict patch identity safe to echo through an agent.

        The complete before/after payloads stay server-side.  A caller can bind
        a candidate to immutable bytes using the three hashes and receive the
        actual unified diff only from the trusted finalize boundary.
        """

        return {
            "rule_id": self.rule_id,
            "entity_id": self.entity_id,
            "artifact": self.artifact,
            "mutation_kind": self.mutation_kind,
            "endpoint": self.endpoint,
            "eliminated_component": self.eliminated_component,
            "replacement_component": self.replacement_component,
            "summary": self.summary,
            "before_sha256": self.before_sha256,
            "after_sha256": self.after_sha256,
            "diff_sha256": self.diff_sha256,
        }

    def candidate_sha256(self) -> str:
        raw = json.dumps(
            self.candidate_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


def _safe_integrations_artifact(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise RemediationNotAvailable(
            "finding artifact is not a safe repository-relative path",
            code="unsafe_artifact",
        )
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.name != "integrations.yaml"
    ):
        raise RemediationNotAvailable(
            "finding artifact is not a supported integrations document",
            code="unsupported_layout",
        )
    return value


def _pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _line_body(line: str) -> tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n") or line.endswith("\r"):
        return line[:-1], line[-1:]
    return line, ""


def _sibling_components_path(integrations_artifact: str) -> str:
    """MVP supports exactly one layout: ``.../integrations.yaml`` next to
    ``.../components.yaml`` in the same directory."""

    integrations_artifact = _safe_integrations_artifact(integrations_artifact)
    parts = PurePosixPath(integrations_artifact).parts
    if not parts or parts[-1] != "integrations.yaml":
        raise RemediationNotAvailable(
            f"unsupported integrations artifact layout: {integrations_artifact!r}",
            code="unsupported_layout",
        )
    return str(PurePosixPath(*parts[:-1], "components.yaml"))


def _flow_block_lines(lines: list[str], flow_id: str) -> tuple[int, int]:
    """Return the ``[start, end)`` line range of one flow's YAML block."""

    header = f"  {flow_id}:"
    start = None
    for index, line in enumerate(lines):
        body, _newline = _line_body(line)
        if body == header:
            start = index
            break
    if start is None:
        raise RemediationNotAvailable(
            f"flow {flow_id!r} is not a top-level entry in the integrations document",
            code="entity_not_found",
        )
    end = len(lines)
    for index in range(start + 1, len(lines)):
        stripped = lines[index]
        if stripped.strip() == "":
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        if indent <= 2:
            end = index
            break
    return start, end


def propose_remediation(
    finding: Mapping[str, Any], workspace_root: str | Path
) -> RemediationPatch:
    """Propose one deterministic patch for a single finding, or refuse.

    ``finding`` is one entry from ``deterministic_findings`` as produced by
    :func:`tools.seaf_review.deterministic_findings`. ``workspace_root`` is
    the resolved repository root the finding's ``artifact`` path is relative
    to (i.e. the same root the review snapshot was built from).
    """

    if not isinstance(finding, Mapping):
        raise RemediationNotAvailable(
            "finding must be an object", code="malformed_finding"
        )
    rule_id = finding.get("rule_id")
    if rule_id not in SUPPORTED_RULES:
        raise RemediationNotAvailable(
            f"no remediation mutation is registered for rule {rule_id!r}",
            code="unsupported_rule",
        )

    root = Path(workspace_root)
    artifact = _safe_integrations_artifact(finding.get("artifact"))
    entity_id = finding.get("entity_id")
    location = finding.get("location")
    if not isinstance(entity_id, str) or INTEGRATION_ID_RE.fullmatch(entity_id) is None:
        raise RemediationNotAvailable(
            "finding entity_id is not a supported integration ID",
            code="malformed_finding",
        )
    if not isinstance(location, str):
        raise RemediationNotAvailable(
            "finding location is missing", code="malformed_finding"
        )
    endpoint = location.rsplit("/", 1)[-1]
    if endpoint not in ("from", "to"):
        raise RemediationNotAvailable(
            f"finding location {location!r} does not target a flow endpoint",
            code="unsupported_location",
        )
    expected_location = (
        f"/seaf.app.integrations/{_pointer_token(entity_id)}/{endpoint}"
    )
    if location != expected_location:
        raise RemediationNotAvailable(
            "finding location is not the exact canonical endpoint pointer",
            code="unsupported_location",
        )

    integrations_text = safe_read_artifact(root, artifact)
    integrations_doc = strict_load_yaml_text(integrations_text, source=artifact)
    flows = integrations_doc.get("seaf.app.integrations")
    if not isinstance(flows, Mapping) or entity_id not in flows:
        raise RemediationNotAvailable(
            f"flow {entity_id!r} is not present in {artifact!r}", code="entity_not_found"
        )
    flow = flows[entity_id]
    if not isinstance(flow, Mapping):
        raise RemediationNotAvailable(
            f"flow {entity_id!r} is not a mapping", code="malformed_flow"
        )
    eliminated_component = flow.get(endpoint)
    if (
        not isinstance(eliminated_component, str)
        or COMPONENT_ID_RE.fullmatch(eliminated_component) is None
    ):
        raise RemediationNotAvailable(
            f"flow {entity_id!r} has no safe component ID at {endpoint!r}",
            code="malformed_flow",
        )

    components_relative = _sibling_components_path(artifact)
    components_text = safe_read_artifact(root, components_relative)
    components_doc = strict_load_yaml_text(components_text, source=components_relative)
    components = components_doc.get("components")
    if not isinstance(components, Mapping) or eliminated_component not in components:
        raise RemediationNotAvailable(
            f"component {eliminated_component!r} is not defined in {components_relative!r}",
            code="entity_not_found",
        )
    eliminated = components[eliminated_component]
    if not isinstance(eliminated, Mapping) or eliminated.get("target_status") != "eliminate":
        raise RemediationNotAvailable(
            f"component {eliminated_component!r} is not target_status=eliminate; "
            "refusing to reroute a dependency that is not actually the SEAF-004 cause",
            code="precondition_failed",
        )
    replacement_component = eliminated.get("replaced_by")
    if not isinstance(replacement_component, str) or not replacement_component:
        raise RemediationNotAvailable(
            f"component {eliminated_component!r} declares no 'replaced_by' successor; "
            "no safe automatic target exists -- this requires an architect decision",
            code="no_declared_successor",
        )
    if COMPONENT_ID_RE.fullmatch(replacement_component) is None:
        raise RemediationNotAvailable(
            "declared successor is not a safe component ID",
            code="invalid_declared_successor",
        )
    replacement = components.get(replacement_component)
    if not isinstance(replacement, Mapping):
        raise RemediationNotAvailable(
            f"declared successor {replacement_component!r} is not defined in "
            f"{components_relative!r}",
            code="successor_not_found",
        )
    replacement_status = replacement.get("target_status")
    if replacement_status not in SAFE_SUCCESSOR_STATUSES:
        raise RemediationNotAvailable(
            f"declared successor {replacement_component!r} does not have an explicit "
            "non-eliminate target_status",
            code=(
                "successor_also_eliminated"
                if replacement_status == "eliminate"
                else "successor_status_invalid"
            ),
        )

    lines = integrations_text.splitlines(keepends=True)
    start, end = _flow_block_lines(lines, entity_id)
    target_line = None
    for index in range(start + 1, end):
        body, _newline = _line_body(lines[index])
        if body.strip() == f"{endpoint}: {eliminated_component}":
            target_line = index
            break
    if target_line is None:
        raise RemediationNotAvailable(
            f"could not locate an exact '{endpoint}: {eliminated_component}' line inside "
            f"the {entity_id!r} block; refusing a non-exact textual patch",
            code="patch_anchor_not_found",
        )

    original_line = lines[target_line]
    original_body, newline = _line_body(original_line)
    indent = original_body[: len(original_body) - len(original_body.lstrip(" "))]
    new_lines = list(lines)
    new_lines[target_line] = f"{indent}{endpoint}: {replacement_component}{newline}"
    after_text = "".join(new_lines)
    changed_lines = [
        index
        for index, (before, after) in enumerate(zip(lines, new_lines))
        if before != after
    ]
    if changed_lines != [target_line] or len(lines) != len(new_lines):
        raise RemediationNotAvailable(
            "candidate patch is not an exact one-line mutation",
            code="patch_not_minimal",
        )
    after_doc = strict_load_yaml_text(after_text, source=artifact)
    after_flows = after_doc.get("seaf.app.integrations")
    after_flow = after_flows.get(entity_id) if isinstance(after_flows, Mapping) else None
    if not isinstance(after_flow, Mapping) or after_flow.get(endpoint) != replacement_component:
        raise RemediationNotAvailable(
            "candidate patch does not preserve a valid integration document",
            code="patch_validation_failed",
        )

    summary = (
        f"Reroute {entity_id} ({endpoint}) away from eliminate-status "
        f"{eliminated_component!r} to its declared successor {replacement_component!r}, "
        f"resolving {rule_id}."
    )
    return RemediationPatch(
        rule_id=rule_id,
        entity_id=entity_id,
        artifact=artifact,
        mutation_kind="reroute_target",
        endpoint=endpoint,
        eliminated_component=eliminated_component,
        replacement_component=replacement_component,
        before_text=integrations_text,
        after_text=after_text,
        summary=summary,
    )
