# 0107 M6: virtual-scene content

The node store accepts `virtual_scenes` with the `virtual-scene-data/v1` content contract. Each
frame stores an exact frame identity, calibration revision and digest, card poses and stacking
order, and separate pile and ignore regions. A frame can have no card scene. A scene may contain a
fully hidden card. The node store checks that recording frame identities match the source video.
It validates scene frame dimensions and calibration references. A calibration change therefore
requires a matching scene revision. Historical revisions remain immutable.

The scene geometry uses the existing `reviewed-card-scene/v1` geometry envelope. That historical
schema name does not give the new scene review authority. Review decisions and coverage use the
independent node review records. Item origin and changes use the node provenance service. Visible
regions are derived views. They are not stored in this content or accepted as review decisions.
Callers must recompute affected visible regions and review applicability after pose, stacking, or
calibration changes.

`from_proposed` maps supported proposal frames and explicit empty frames. It returns the source
proposal separately, including detector and calibration lineage. `from_draft` maps a reviewed
draft and returns the original draft and legacy review facts separately; unknown reviewer identity
remains unknown. Callers must retain these source records and create provenance and review records
at migration. The mapping does not infer individual authors or reviewers. For a mixed draft, an
explicit complete scene is required. The mapping checks retained poses and relative ordering; it
does not invent cross-group order. Unsupported proposals, missing frame or calibration evidence,
and incomplete geometry are refused. Migration must report these cases and preserve their sources.

The existing application is not switched to this store. Epic 0108 owns editor integration and the
coordinated cutover. The M8 inventory must identify source records that cannot map without explicit
missing evidence.

Verification: focused node, review, identity, scene geometry, and scene contract tests passed. They
cover proposed and mixed-origin scenes, independent review coverage, a fully hidden card, stacking
and calibration changes, separate pile and ignore regions, source-frame checks, and immutable reads.
Ruff check and format passed for the changed Python files.
