# Final demo recording plan — 2:50 maximum

This is a recording plan, not evidence that a video exists. Record only after
the official-agent E2E has succeeded and sanitized traces/metrics are frozen.

| Time | Screen | Continuous narration |
|---|---|---|
| 0:00–0:18 | SEAF.ArchTool opens the synthetic integration context | Architecture changes are reviewed manually across models, links and decisions. A critical dependency or duplicate master can hide in valid-looking YAML. |
| 0:18–0:38 | Show `demo.portal_to_legacy_scoring` and retiring component | This synthetic change adds a portal dependency on Legacy Scoring, whose governed target status is eliminate. The same SEAF manifest is the UI and review source. |
| 0:38–0:58 | Show actual base/head SHAs and run the review action | AGA does not trust a manifest list. Git supplies base/head changed paths; a bounded resolver materializes the import and context closure with commit/file/pointer provenance. |
| 0:58–1:18 | Agent chat and MCP trace: prepare | The official agent orchestrates AGA tools. Prepare returns deterministic findings plus PRIN-004 through PRIN-007 semantic tasks; missing tools cannot become success. |
| 1:18–1:45 | Lookup/diagram tool calls and structured semantic output | The agent checks reuse, the single master, prose dependencies and ADR quality against only the prepared SEAF evidence. Architecture text is untrusted and output is strict JSON. |
| 1:45–2:08 | MCP trace: finalize; display both finding classes | Finalize verifies rule IDs, source references and evidence, then deduplicates semantic and deterministic findings. Raw model prose never changes the verdict. |
| 2:08–2:28 | Final report: blocker, source pointer, HITL | The new dependency is a blocker with exact SEAF evidence. The result requests changes and a human architect; AGA has no merge capability. |
| 2:28–2:45 | Results screen | The deterministic regression has 26 cases. The independent agent basket has 16 frozen synthetic SEAF cases; state the actual real-run precision, recall, blocker recall and unsafe approves shown on screen. |
| 2:45–2:50 | Closing architecture view | One SEAF source, agent semantic reasoning, deterministic safety and mandatory human control. |

## Pre-publication checks

- `ffprobe` duration is strictly below 180 seconds;
- narration is continuous and readable at normal speed;
- actual official-agent and MCP prepare/finalize traces are visible;
- real metrics are spoken exactly as frozen evidence reports them;
- no credential, cookie, token, internal URL or raw closed prompt is visible;
- the public URL opens in a private window without authentication.

