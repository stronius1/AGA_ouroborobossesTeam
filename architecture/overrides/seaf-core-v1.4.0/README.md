# seaf-core v1.4.0 presentation overlay

This directory is a narrow Apache-2.0 derivative of the exact seaf-core commit
`60ce335832d2734814c020306a85d1e8b12cf67b`.

The upstream `entities/ta/presentation/components.yaml` blob has SHA-256
`c784b57b54aa5f5ebab57f732d7088617661ac4d206493f39a4a6e9a6f628ad6` and
defines `seaf.ta.components.server` twice. The first block is demonstrably the
K8s Namespace presentation; this copy changes only that first key to
`seaf.ta.components.k8s_namespace`. Its SHA-256 is
`0af3c2c90a3a31257b2f38ba577590f1f32da048a72e2264fb80793b415efb7c`.

`architecture/seaf-core-v1.4.0-overlay.yaml` flattens four upstream import-only
aggregators while preserving their ordered transitive leaf closure. Among the
semantic leaf documents it replaces only the malformed source document with
this corrected copy. The upstream submodule stays byte-for-byte clean and
pinned. The adjacent `templates/list.md` is a
content-identical copy required by the relocated presentation document, apart
from a normalized final newline. Its upstream/copy SHA-256 values are
`eb2a5b974dbe99234f726070656e5faf69d7774a2e0f76da917197e740767be3` and
`3c6b3d7659e0fa9af46216049bc3154e502e0622744104eb523c243093324056`.
See the upstream submodule `LICENSE` for the Apache-2.0 terms.
