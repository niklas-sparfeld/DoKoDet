# 0107 M4: review decisions

`PipelineNodeReviews` stores immutable item decisions, inspected coverage, and overall decisions
outside node content revisions. Each record identifies the reviewed revision and content digest,
question, reviewer, time, and evidence and policy. Coverage is explicit and can describe an inspected
empty region or a partial interval. An item decision does not imply coverage or an overall decision.
Reviewing a used node does not create a copy or change its working head.

Applicability is computed from retained history. Overall decisions and coverage apply only to their
exact revision. An item decision can apply along explicit revision and copy ancestry when the item
remains unchanged and the current evidence and policy match. An item change or deletion makes the
earlier decision inapplicable; the record remains available. Unrelated nodes do not inherit review.
Missing current evidence gives an unknown result. The caller must supply complete current evidence
and policy identities; equality of incomplete caller-supplied evidence is not proof of applicability.
M5 owns identity-specific correspondence and crop-evidence checks, including scene occlusion changes.

The service is a foundation and is not connected to existing review editors or processor selection.
It does not infer a review from a save or processor run.

Verification: 38 focused and existing pipeline-store tests passed. They cover independent item,
coverage and overall decisions; empty and partial coverage; changed and deleted content; unchanged
copies; evidence changes and missing evidence; idempotency; and review after downstream use. Ruff
check and format passed for the new files.
