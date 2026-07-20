# AGA MCP contract

The MCP session layer exposes a stateless Streamable HTTP endpoint at `/mcp`;
bounded immutable review and remediation state is retained by the trusted
services and addressed by opaque digests. It implements the subset used by the
pinned ArchTool configuration:
`initialize`, `notifications/initialized`, `ping`, `tools/list` and
`tools/call`. The locally supported protocol version is exactly
`2025-11-25`; an unknown date-based initialize request is negotiated down to
that version, and every later GET/DELETE/POST request must send
`MCP-Protocol-Version: 2025-11-25`.

The six gateway tools are:

| Tool | Purpose |
|---|---|
| `aga_prepare_review` | Resolve registered full base/head commit IDs, build a bounded SEAF snapshot, run deterministic checks and prepare PRIN-004..007 tasks. |
| `aga_seaf_lookup` | Read one entity from evidence already bound to the prepared review. |
| `aga_parse_diagram` | Parse one prepared PlantUML/Mermaid artifact without accepting a client filesystem path. |
| `aga_finalize_review` | Validate semantic JSON against prepared tasks/evidence, merge with deterministic findings and compute a fail-closed verdict. |
| `aga_prepare_remediation` | Prepare one deterministic SEAF-004 candidate from an exact trusted finalized review and immutable registered Git revision. |
| `aga_finalize_remediation` | First-write finalize the exact prepared candidate and return a trusted minimal diff without writing, committing, pushing, approving or merging. |

Gateway discovery must return exactly all six tools. Before a model call, the
managed worker receives only its stage subset: the four review tools for
`aga:review`, or the two remediation tools for `aga:remediate`.

## HTTP framing and no-batch policy

Each POST body must contain exactly one JSON-RPC request or notification.
JSON-RPC batch arrays, including an empty array, are not supported by this
pinned ArchTool contract. The HTTP boundary rejects them before protocol
negotiation or dispatch with HTTP `400`, JSON-RPC error `-32600` and
`data.code=batch_not_supported`; no tool callback is invoked. A valid single
notification remains a `202` response without a body.

## Correlation and finalization

`repository_id`, `review_id`, `base` and `head` are bound on first prepare.
Base/head are full 40- or 64-character Git object IDs, not branch names or
abbreviated SHAs. Prepare returns opaque `review_digest`, `task_digest` and
per-entity evidence references. Finalize must return the same correlation.
Every prepared artifact exposes an exact immutable `source_provenance` object
with no extension fields: `{file,pointer,commit,line,sha256}`. `pointer` is a
non-empty canonical RFC 6901 JSON Pointer, `commit` is a full 40- or
64-character object ID, `line` is null or a positive integer, and `sha256` is
a lowercase digest. A dependency artifact's exact commit may intentionally
differ from the review head; the service preserves both values rather than
rewriting provenance to the head revision.
Each artifact also has strict delta metadata: `change_status` is `changed` or
`context`, and `changed_pointers` is a unique canonical RFC 6901 pointer array.
A changed artifact has at least one pointer equal to or below its entity
pointer; a context artifact has none. The default Git-backed prepare hook maps
the repository snapshot's exact entity/field pointers to head entities. A
changed non-YAML diagram has no field diff, so its owning context pointer is
used as the smallest available target.
For a materialized `.puml`, `.plantuml` or Mermaid `text` field the artifact
additionally requires `content_provenance`: the exact diagram file, mapped `/.../text`
pointer, commit, line and SHA-256. Prepare verifies that digest against the
stored UTF-8 text and binds it into the review digest; a decoding/newline
transformation that changes captured bytes fails closed. The content commit is
resolved independently from the owning YAML document by the longest exact
trusted-dependency path prefix, or the review head outside dependencies. A
finding at that text
location, and the parse-diagram result, use this content provenance rather
than presenting the owning YAML entity hash as if it covered diagram bytes.
Non-materialized artifacts expose `content_provenance: null`.
Deterministic findings preserve the direct AGA `base_revision`,
`head_revision`, canonical defect and strict source-provenance object; MCP adds
an opaque evidence reference without replacing commit/file/pointer evidence.
If a trusted callback omits those provenance fields, the service adds them only
after exactly one prepared artifact matches the artifact, optional entity,
optional exact callback provenance, and resolving location pointer. An
unbound, ambiguous or non-resolving deterministic finding is dropped, marks
prepare `incomplete`, and emits `deterministic_evidence_unbound`; it cannot
enter the final merge. Final findings and low-confidence observations require
`base_revision`, `head_revision` and `source_provenance` in the output schema.
The native deterministic engine may report an unchanged artifact impacted by
a changed dependency (for example, an existing integration after an endpoint
lifecycle change), but only when the trusted callback supplies its exact
entity ID and full provenance matching that immutable context artifact.
Semantic findings never receive this exception: their primary entity must be
changed.
Prepare and final results also carry `review_provenance_json`, a canonical JSON
string that binds manifest/rules hashes, dependency verification, exact pins,
scope and ignored paths. The semantic rule catalog and verdict policy loaded
for the snapshot are frozen in the stored review; finalization cannot silently
fall back to a different process-default rules directory.

Finalization is first-write immutable. An identical semantic retry returns
the stored result; a different retry returns `finalization_conflict` and
cannot rewrite the verdict. Missing, timed-out, invalid or incomplete semantic
work yields `incomplete` at the AGA finalize boundary. The upstream ArchTool
agent loop is not claimed to enforce this on its own; the real SDK/UI loop is
still an unverified external-stage check.

Semantic rule tasks contain only artifacts whose normalized `kind` is inside
the trusted catalog scope. `entity_ids` contains only changed target entities;
`context_entity_ids` lists bounded unchanged context in the same scope, and
`evidence_refs` covers both groups. A finding must target an `entity_id` from
the changed group and cite its own evidence, but may cite additional context
evidence. A rule with no changed matching artifacts has empty `entity_ids` and
can complete only with zero findings; there is no fallback to all prepared
artifacts. Finalization independently rechecks both artifact kind and changed
status against the frozen task/catalog state.

A semantic finding's `location` must be a canonical RFC 6901 pointer equal to
its prepared entity pointer or a descendant of it. The descendant suffix must
resolve in the immutable prepared `data_json`. For an accepted finding the
service, not the semantic agent, adds the exact prepared `base_revision`,
`head_revision` and `source_provenance`. An invalid, sibling or missing pointer,
or an out-of-scope entity, rejects semantic findings from that response and
produces an `incomplete` result with `semantic_validation_error` and mandatory
human review.

The current canonical adapter exposes head entity values plus exact changed
pointers, not a parallel base-value object for every entity. The MCP evidence
therefore does not invent base values: semantic agents compare the prepared
head value with the supplied delta pointers and bounded context. Entities
deleted from the head cannot become semantic finding targets through this
model; structural/deletion handling remains in the trusted snapshot and
deterministic stages.

Signals below confidence `0.40` remain observations. If the trusted catalog
severity is `blocker` or `major`, such a signal cannot approve the review even
when every semantic rule reports completion: finalization is `incomplete`,
adds `semantic_low_confidence`, and requires escalation/HITL.

State-mutating prepare/finalize operations are never abandoned in a daemon
worker: the transport cannot return `tool_timeout` and then write review state
later. Prepare has its own trusted-hook timeout and stores one immutable
`incomplete` result when that expires; finalize is schema/size-bounded and runs
to its single first-write result. The outer request timeout remains applicable
to read-only lookup/diagram workers. CLI startup requires prepare timeout not
to exceed the configured request timeout.

## Trust and deployment boundary

- Client arguments never contain repository or rules filesystem paths.
- Production snapshot mode is `verified` and requires clean, exact gitlinks
  for both `seaf-archtool-core` and `architecture/vendor/seaf-core`.
- Synthetic tests and the offline demo explicitly use `fixture` mode and emit
  `dependency_verification: fixture-unverified`.
- Loopback may use `mode=none`. Compose uses an unpublished internal network.
  Non-loopback bearer mode requires both a token and an explicit assertion
  that a trusted TLS reverse proxy protects the endpoint.
- Request threads, read-only tool workers, body size, response size, execution time,
  stored reviews and trace entries are bounded. Traces retain only tool name,
  argument hash, status and duration.
- A timed-out trusted prepare hook retains its worker permit until the callback
  actually exits; repeated hangs therefore return `prepare_busy` instead of
  creating unbounded daemon threads. Canonical bytes are capped per review and
  across the store, with weight-based LRU eviction in addition to the count/TTL
  limits.
- The server has no merge, commit, push or evolution-apply capability.

## Evidence boundary

Python unit and HTTP contract tests cover schemas, negotiation, limits,
authentication, immutable finalization and fail-closed errors. They are not a
substitute for running the installed `@modelcontextprotocol/sdk` 1.29.0 client
and the full ArchTool agent loop; that check awaits pinned upstream
submodules, Node 20 and an authorised agent environment.
