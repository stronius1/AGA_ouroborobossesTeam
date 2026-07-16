# -*- coding: utf-8 -*-
"""Safe publisher contract for evolution artifacts.

Only the no-side-effect dry-run implementation lives here.  A future Git/PR
adapter must be explicitly configured outside this module and still cannot
merge, approve, or push directly to the protected branch.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


FORBIDDEN_ACTIONS = frozenset(
    {"merge", "approve", "approve_pr", "push_main", "push_to_main"}
)


class PublisherError(RuntimeError):
    """Base publisher failure."""


class PublisherPolicyError(PublisherError, PermissionError):
    """An action violates the immutable HITL/SoD policy."""


class PublisherValidationError(PublisherError, ValueError):
    """A publication request is malformed."""


@dataclass(frozen=True)
class PublishRequest:
    cycle_id: str
    artifacts: Mapping[str, str | Path]
    branch_name: str | None = None
    commit_message: str | None = None
    draft: bool = True
    requested_actions: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.cycle_id, str) or not self.cycle_id.strip():
            raise PublisherValidationError("cycle_id must be a non-empty string")
        if not isinstance(self.artifacts, Mapping):
            raise PublisherValidationError("artifacts must be a mapping")
        for name, path in self.artifacts.items():
            if not isinstance(name, str) or not name.strip():
                raise PublisherValidationError("artifact names must be non-empty strings")
            if not isinstance(path, (str, Path)):
                raise PublisherValidationError(
                    f"artifact {name!r} path must be str or Path"
                )
        if not isinstance(self.requested_actions, tuple) or not all(
            isinstance(item, str) for item in self.requested_actions
        ):
            raise PublisherValidationError("requested_actions must be a tuple of strings")
        if not isinstance(self.metadata, Mapping):
            raise PublisherValidationError("metadata must be a mapping")


@dataclass(frozen=True)
class PublicationResult:
    publisher: str
    status: str
    cycle_id: str
    artifacts: tuple[str, ...]
    external_side_effects: bool
    branch_name: str | None = None
    draft_pr_url: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "publisher": self.publisher,
            "status": self.status,
            "cycle_id": self.cycle_id,
            "artifacts": list(self.artifacts),
            "external_side_effects": self.external_side_effects,
            "branch_name": self.branch_name,
            "draft_pr_url": self.draft_pr_url,
            "details": dict(self.details),
        }


@runtime_checkable
class EvolutionPublisher(Protocol):
    """Publication boundary used by the evolver."""

    requires_network: bool

    def publish(self, request: PublishRequest) -> PublicationResult:
        ...


def _normalise_action(action: str) -> str:
    return action.strip().lower().replace("-", "_").replace(" ", "_")


def validate_publish_request(request: PublishRequest) -> None:
    if not isinstance(request, PublishRequest):
        raise PublisherValidationError("publish expects a PublishRequest")
    forbidden = {
        action
        for action in (_normalise_action(item) for item in request.requested_actions)
        if action in FORBIDDEN_ACTIONS
    }
    if forbidden:
        raise PublisherPolicyError(
            f"publisher can never execute: {', '.join(sorted(forbidden))}"
        )
    if not request.draft and request.branch_name:
        raise PublisherPolicyError("publisher may open only a draft PR")


class DryRunPublisher:
    """Default publisher: reports candidate artifacts and changes nothing."""

    requires_network = False
    name = "dry-run"

    def publish(self, request: PublishRequest) -> PublicationResult:
        validate_publish_request(request)
        return PublicationResult(
            publisher=self.name,
            status="dry_run",
            cycle_id=request.cycle_id,
            # Persist stable logical names, not developer-specific absolute paths.
            artifacts=tuple(request.artifacts.keys()),
            external_side_effects=False,
            branch_name=None,
            draft_pr_url=None,
            details={
                "candidate_branch": request.branch_name,
                "draft_requested": request.draft,
                "message": "artifacts validated; no branch, commit, push, or PR created",
            },
        )

    def merge(self, *_args: Any, **_kwargs: Any) -> None:
        raise PublisherPolicyError("merge is permanently forbidden for the evolver")

    def approve(self, *_args: Any, **_kwargs: Any) -> None:
        raise PublisherPolicyError("approve is permanently forbidden for the evolver")

    def approve_pr(self, *_args: Any, **_kwargs: Any) -> None:
        raise PublisherPolicyError("approve is permanently forbidden for the evolver")

    def push_to_main(self, *_args: Any, **_kwargs: Any) -> None:
        raise PublisherPolicyError(
            "direct push to the protected branch is permanently forbidden"
        )


def default_publisher() -> EvolutionPublisher:
    """Return the only safe implicit publisher."""

    return DryRunPublisher()


__all__ = [
    "DryRunPublisher",
    "EvolutionPublisher",
    "FORBIDDEN_ACTIONS",
    "PublicationResult",
    "PublishRequest",
    "PublisherError",
    "PublisherPolicyError",
    "PublisherValidationError",
    "default_publisher",
    "validate_publish_request",
]
