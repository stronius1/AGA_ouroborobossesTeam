# SEAF → AGA canonical mapping

The executable adapter is `aga-skill/tools/seaf_native.py`. It accepts only a
root manifest with this project-owned, versioned marker:

```yaml
aga:
  schema: seaf-core/v1.4.0
  extensions: [aga.project/v1]
  data_classification: synthetic-public
```

An absent or unknown schema, extension, extension field, or metadata field is
an `input_error`; no best-effort fallback to the legacy `fixtures/seaf.yaml`
shape is performed. The serialised result always has
`schema: aga.canonical/v2`.

## Source provenance

Every canonical entity has a `source_ref` with these fields:

| Canonical field | Source | Required | Transformation and absence behaviour |
|---|---|---:|---|
| `file` | YAML document containing the entity | yes | Repository-root-relative POSIX path produced by the safe resolver. Absolute, traversing, symlinked, and hardlinked inputs are rejected. |
| `pointer` | Entity position in YAML | yes | RFC 6901 JSON Pointer; `~` becomes `~0` and `/` becomes `~1`. It is never a display-only label. |
| `commit` | Trusted snapshot provenance | for Git snapshots | For a document below a trusted dependency prefix, this is that dependency's exact gitlink revision; otherwise it is `RepositoryRevision.head_commit`. It is `null` only for fixture/unit adaptation without Git provenance. |
| `line` | Optional Git/materialiser location | no | Positive one-based line or `null`. The SEAF adapter uses the lossless pointer because PyYAML does not retain source marks after strict construction. |
| `sha256` | Exact source YAML bytes | yes for SEAF entities | Lowercase SHA-256 computed after the bounded no-follow read. |

All entity mappings below are defined by `seaf-core/v1.4.0` plus
`aga.project/v1`.

## `System`

One top-level `components.<id>` definition becomes one `System`.

| Canonical field | SEAF source | Required | Transformation and absence behaviour |
|---|---|---:|---|
| `id` | key below `components` | yes | Non-empty string, unchanged. Duplicate or conflicting IDs anywhere in the import closure fail the whole input. |
| `name` | `title` | yes | Official base requires `title`; legacy `name` cannot override it. `entity` is also validated as required. |
| `owner` | `owner` | yes, project extension | Trimmed string; absence fails with `extension_field_missing`. |
| `criticality` | `criticality` | yes, project extension | Preserved after validation against `low`, `medium`, `high`, `mission_critical`. |
| `target_status` | `target_status` | yes, project extension | Preserved after validation against `strategic`, `tactical`, `tolerate`, `eliminate`. |
| `domain` | `domain` | no | Trimmed string; missing becomes `""`. |
| `infra` | `infra` | no | Boolean; missing becomes `false`, non-boolean input fails. |
| `description` | `description` | no | Trimmed string; missing becomes `""`. |
| `source_ref` | containing file plus `/components/<escaped-id>` | yes | Exact provenance described above. |

## `Integration`

One top-level `seaf.app.integrations.<id>` definition becomes one
`Integration`.

| Canonical field | SEAF source | Required | Transformation and absence behaviour |
|---|---|---:|---|
| `id` | integration mapping key | yes | Non-empty string, unchanged. |
| `name` | `title` | yes | Trimmed official title; absence fails closed. |
| `source` | `from` | yes | Non-empty component ID, unchanged. This is the canonical flow source. |
| `target` | `to` | yes | Non-empty component ID, unchanged. This is the canonical flow target. |
| `description` | `description` | yes | Non-empty official description; absence fails closed. |
| `protocol` | `protocol`, otherwise `technology` | no | Missing becomes `""`. |
| `pattern`, `zone`, `transfer_mode` | same-named project fields | no | Missing becomes `""`; values are retained for rules-driven review. |
| `gateway_controlled` | same-named project field | no | Missing becomes `false`; non-boolean input fails. |
| `data_categories`, `approvals` | same-named project fields | no | Lists of strings become immutable canonical arrays; missing becomes `[]`. |
| `source_ref` | containing file plus `/seaf.app.integrations/<escaped-id>` | yes | Exact provenance described above. |

## `ADR`

One top-level `seaf.change.adr.<id>` definition becomes one `ADR`.

| Canonical field | SEAF source | Required | Transformation and absence behaviour |
|---|---|---:|---|
| `id` | ADR mapping key | yes | Non-empty string, unchanged. |
| `title` | `title` | yes | Trimmed string; absence fails. |
| `status` | `status` | yes | Project extension enum: `proposed`, `accepted`, `deprecated`, `superseded`. |
| `context` | required `issue` followed by required `context` | yes | Structured SEAF statement arrays are joined in order; validated `area`/`vector` become a stable prefix and `content` is retained. |
| `decision` | `decision` | yes | Non-empty scalar retained. |
| `consequences` | `consequences` | yes | Structured SEAF statement array is normalised like `context`. |
| `source_ref` | containing file plus `/seaf.change.adr/<escaped-id>` | yes | Exact provenance described above. |

`moment` is required and validated as `YYYY-MM-DD`; `deciders` is optional.
They remain SEAF source data but are not copied into `aga.canonical/v2`;
adding them requires a canonical schema revision.

## `Diagram`

One top-level `contexts.<id>` definition becomes one `Diagram`.

| Canonical field | SEAF source | Required | Transformation and absence behaviour |
|---|---|---:|---|
| `id` | context mapping key | yes | Non-empty string, unchanged. |
| `title` | `title`, otherwise `name` | no | Missing/empty becomes the context ID. |
| `kind` | `format`, `type`, or `presentation` | no | If absent, inferred from the artifact suffix (`plantuml`/`mermaid`), otherwise `context`. |
| `artifact` | `template`, `source`, `artifact`, or v1.4 `uml` | no | Resolved relative to the containing YAML into a repository-root-relative path. Escapes, remote references, symlinks, hardlinks, missing files, and unsupported extensions fail. Missing becomes `""` for generated contexts. |
| `components` | `components` | no | Ordered list of component IDs; missing becomes `[]`. |
| `source_ref` | containing file plus `/contexts/<escaped-id>` | yes | Points to the context definition; `artifact` points to the real diagram file. |

## Git input values

`ChangedArtifact` fields are `path`, Git-derived `status`, exact `sha256`
(the base blob for deletions), `source_ref`, and entity-level
`changed_pointers` derived by comparing base/head YAML. They must be supplied
by the trusted snapshot builder, never by untrusted `meta.yaml`. This prevents
an edit elsewhere in one integrations file from relabelling every existing
flow as newly introduced.

`RepositoryRevision` is immutable and contains `base_commit`, `head_commit`,
`manifest_sha256`, `archtool_commit`, `seaf_core_commit`, `aga_version`, and
`rules_sha256`. No field is inferred from a branch or worktree: the trusted Git
snapshot builder supplies the values and a prefix-to-dependency-commit map. The
adapter uses the exact dependency commit for documents inside that prefix and
uses `head_commit` for superproject-owned documents.

Snapshot provenance also carries `dependency_verification`. Production mode
is `verified-gitlinks` only after both `seaf-archtool-core` and
`architecture/vendor/seaf-core` are exact Git gitlinks at their configured
commits, with HEAD, index, and every tracked worktree entry matching the pinned
trees. Ignored untracked outputs are outside this pin proof. The local cleaner
removes project-owned caches but deliberately does not mutate dependency
`node_modules`/`dist`; absence of those outputs requires clean-clone evidence.
Synthetic unit/demo repositories use the explicit
`fixture-unverified` mode, so their placeholder dependency commits cannot be
mistaken for supply-chain evidence.

## Import boundary

`DocHubImportResolver` resolves local `.yaml`/`.yml` imports relative to the
importing document under one repository root. It enforces per-file and total
byte limits, import depth, file count, YAML alias/depth/node limits, UTF-8,
duplicate YAML keys, cycle detection, and duplicate/conflicting entity IDs.

Remote content is never fetched. A remote import is accepted only when its
mapping contains an immutable full 40- or 64-character hexadecimal revision,
a 64-character SHA-256 and a vendored local path. The revision must occur in
trusted snapshot dependency provenance and the local bytes must match the
checksum. The vendored path must lie beneath the dependency prefix bound to
that exact revision in snapshot provenance; a standalone resolver must receive
the same prefix-to-revision mapping explicitly. A merely well-formed revision,
or a trusted revision attached to the wrong local path, fails closed.
