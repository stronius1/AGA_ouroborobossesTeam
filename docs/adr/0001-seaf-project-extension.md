# ADR-0001: versioned AGA extension over SEAF core v1.4.0

- Status: accepted
- Date: 2026-07-15
- Decision owners: synthetic AGA architecture team

## Context

Pinned `seaf-core` v1.4.0 defines SEAF application components,
`seaf.app.integrations`, contexts and `seaf.change.adr`. It does not define the
governance attributes needed by the deterministic demo rule: `owner`,
`criticality` and `target_status`. Adding those fields directly to the example
without a schema would make provenance unverifiable.

The framework manifest also has no active package version that can be used as
runtime provenance. The immutable submodule commit therefore remains the
source of truth for the SEAF version.

## Decision

Create the project-owned package `aga.project/v1` in
`architecture/metamodel/aga-extension.yaml`. It extends component objects with:

- non-empty `owner`;
- `criticality`: `low | medium | high | mission_critical`;
- `target_status`: `strategic | tactical | tolerate | eliminate`.

The extension also defines the root `aga` metadata marker. AGA accepts exactly
`seaf-core/v1.4.0` plus `aga.project/v1`; unknown or missing versions fail
closed. Findings cite the exact extension file and JSON Pointer. No
project-owned source is placed in either upstream submodule.

The same package explicitly schemas optional governance-only integration
attributes used by legacy-compatible rules (`protocol`, `pattern`, `zone`,
`transfer_mode`, `gateway_controlled`, `data_categories`, `approvals`) and the
ADR status vocabulary. This avoids accepting undeclared corporate fields.

We deliberately do not add unverified ADR fields such as `systems` or
`alternatives`. Semantic review uses the official `issue`, `decision`,
`context` and `consequences` fields.

## Consequences

- The synthetic architecture remains SEAF-native while governance attributes
  have an explicit, versioned schema.
- A change to an enum or required field requires a new extension version,
  adapter update and regression run.
- Removing or failing to load the extension produces `input_error`; it cannot
  produce `approve`.

## Rollback

Remove governance-dependent rules and data together, point the adapter back to
the previous accepted extension version, then rerun the safe import, snapshot
and deterministic review tests. The pinned SEAF framework itself is unchanged.
