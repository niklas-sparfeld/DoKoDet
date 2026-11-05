# 0107 M8: migration inventory and dry run

`lineage_migration_inventory` inventories declared source roots without modifying them. It produces
a deterministic plan with a snapshot digest, file lengths and hashes, resource groups, old IDs,
UUIDv5 mapping keys and new node and revision IDs. Independent reviews remain separate. Initial and
current calibration drafts share a revision only when their parsed contents match. Unknown item and
intermediate edit history remains `not_recorded`; timestamps and command hashes do not create edits.

The inventory validates pipeline revisions and their bytes, selections, processor requests and
states, maintained drafts, independent reviews, calibration revisions and drafts, and reflow
receipts. It checks available revision, calibration, source-video, and analysis artifact references.
It reports missing or ambiguous revisions, mismatched source bytes, calibration digests, incompatible
selection targets, and lineage cycles. It records analysis context and scans declared consumer roots
for references to legacy paths. It keeps the source files and explicit sealed-artifact identities in
the plan. It does not read the contents of declared sealed paths.

Automated-run records, most analysis artifacts, consumer references, and other unclassified files
still require semantic validation. The plan reports them as uncertainties and sets
`activation_ready` to false. An unavailable sealed-artifact verification and unrecorded item history
are reported separately; neither invents a fact. The user must declare every sealed path and every
source root before scanning. Recognizable undeclared sealed directories are rejected, but their name
alone cannot identify every sealed sample. The tool does not claim that its consumer search finds
every possible indirect reference. Unknown files and an unconfirmed scope block readiness.

The caller must provide a consistent immutable filesystem snapshot. The tool requires an explicit
`snapshot_is_immutable` assertion and scans the source twice to detect changes, but two scans cannot
prove that a live tree was consistent. Separate roots must not overlap. `scope_complete` is a caller
assertion, not a discovery result. The snapshot must include all relevant source bytes or explicit
sealed declarations. `source_locations` maps a recorded source path to a declared root and relative
path when they differ. A missing source is a conflict.

Run the command with a JSON configuration and an output path outside all source roots:

```sh
mise exec -- uv run --project backend python -m dokodetector_backend.lineage_migration_inventory config.json plan.json
```

The configuration contains `roots` as a map from logical root ID to absolute snapshot directory,
`snapshot_is_immutable: true`, and optionally `scope_complete`, `consumer_root_ids`,
`source_locations`, and `sealed`. Each sealed entry has `root_id`, `relative_path`, `artifact_id`,
and `sha256`. Each source location has `root_id` and `path`. Retain the configuration with the plan
so later conversion can locate the snapshot. The command refuses an output within a source root.
No active data or sealed evaluator was migrated or run in this phase.

Verification: fixture tests cover distinct reviews with a shared base, missing history, dangling and
ambiguous references, repaired selection, corrupt content, incompatible types, calibration draft
snapshots, consumer references, sealed exclusions, source changes, and the output boundary. Ruff
check and format passed. M9 must verify conversion against the plan and leave unresolved blockers
closed to activation; 0108 owns any later local cutover.
