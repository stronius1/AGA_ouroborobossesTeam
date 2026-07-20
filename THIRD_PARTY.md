# Third-party dependencies and provenance

Audit baseline: 2026-07-15; GitVerse pin/license recheck: 2026-07-16;
submission supply-chain recheck: 2026-07-19.

| Dependency | Purpose | Upstream | Tag | Pinned commit | License |
|---|---|---|---|---|---|
| SEAF.ArchTool | UI/runtime, validators, GigaChat/MCP client | `https://gitverse.ru/seafteam/seaf-archtool-core.git` | `v2026.29.0` | `83c82ab1673f1245b499c26b82d507fa602a11d6` | Apache-2.0 (`LICENSE`, `NOTICE` verified in the pinned submodule checkout) |
| SEAF core | Framework/metamodel | `https://gitverse.ru/seafteam/seaf-core.git` | `v1.4.0` | `60ce335832d2734814c020306a85d1e8b12cf67b` | Apache-2.0 (`LICENSE` verified in the pinned submodule checkout) |
| PyYAML | AGA YAML parser | PyPI project metadata | `6.0.3` | exact package pin | MIT |
| pytest | Test-only | PyPI project metadata | `9.0.3` | exact package pin | MIT |

Pytest transitive development dependencies are also exact-pinned in
`aga-skill/requirements-dev.txt`; their notices are recorded in
`aga-skill/THIRD_PARTY_NOTICES.md`.

The two GitVerse revisions above were inspected in isolated read-only
checkouts and are now recorded as exact Git links in `.gitmodules` and the root
tree. Local pin verification is required on every checkout. Recursive
clean-clone verification remains pending until a permitted public remote URL
exists.

The pinned seaf-core v1.4.0 file
`entities/ta/presentation/components.yaml` contains a duplicate
`seaf.ta.components.server` presentation key. A project-owned Apache-2.0
overlay replaces only that malformed import with a content-addressed copy in
which the first, K8s Namespace block has its intended entity ID. Both AGA's
strict loader and ArchTool therefore consume the same valid document. Exact
source and effective hashes are recorded in the overlay README; the upstream
submodule remains unmodified and all duplicate YAML keys remain hard failures.
The wrapper flattens four import-only aggregator documents but preserves their
ordered transitive leaf closure; an integration test checks that equivalence.

"Exact" in the dependency table means an exact declared version. Submission
CI additionally installs its Python dependency closure from
`aga-skill/requirements-ci.txt` with `--require-hashes`; the container installs
PyYAML from the architecture-specific hashes in
`aga-skill/requirements-container.txt`. GitHub Actions use full commit SHAs,
the Docker base uses a manifest-list digest, and apt uses the dated sources in
`aga-skill/debian-snapshot.sources`. `make project-results-check` validates
those local declarations. This evidence establishes content-addressed inputs,
not bit-for-bit reproducibility of every host toolchain or a successful image
build on a machine without a Docker daemon.

## Update procedure

1. Fetch the candidate upstream tag in an isolated temporary directory.
2. Verify signed/reported tag provenance where the upstream provides it.
3. Compare complete trees and review changelog, `LICENSE` and `NOTICE`.
4. Run `make bootstrap`, `make test`, `make test-seaf`, `make demo-offline` and
   `make project-results-check` from a fresh recursive clone.
5. Update the exact commit in the Git link, this table and the architecture
   provenance fixture in one human-reviewed change. Do not configure branch
   tracking in `.gitmodules`.

## Rollback

Move the affected Git link back to the previously reviewed commit, update the
versioned provenance record, initialize recursively and rerun the same clean
clone checks. Project-owned overrides remain outside both upstream trees, so a
rollback never requires patching a submodule.

License compatibility and all transitive notices are a release check. No
third-party source is relicensed by this repository.
