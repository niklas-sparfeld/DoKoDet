# 0107 M5: identity review after refresh

`IdentityReviewRefresh` compares exact source and target visual identity revisions. The caller
supplies explicit item correspondence for those revisions and the human identity review records.
The service does not infer correspondence from item IDs, card labels, or crop equality. It checks
that item provenance covers each outcome and that each decision matches its source revision and item.

An applicable result supplies the original review ID and human classification as an overlay. The
processor prediction remains in the immutable target revision. A consumer must use the overlay to
show the retained correction. No new review decision or content revision is created. The service is
not connected to the existing processor or editor; Epic 0108 owns that integration. The source review
and its revision remain the durable audit record. The caller must retain the exact correspondence
and revision references if it needs to reproduce a result.

A transfer requires a one-to-one correspondence, one unambiguous human identity decision, matching
crop image hashes, and matching crop policy, encoding, decoder, and transform versions. The review
record must contain that same evidence. Changed evidence is inapplicable. Missing evidence, missing
or ambiguous decisions, and missing or ambiguous correspondence are unknown and require review.
Deleted source items retain their old reviews but do not transfer. Matching visual identities do not
establish correspondence. Scene changes require fresh crop evidence for every affected card; this
service does not calculate visible regions or crops.

Verification: the focused identity, review, node, edit, and accepted-use tests passed. They cover a
human correction against a changed model prediction, changed crop from occlusion, changed crop policy,
a deleted card, duplicate labels, ambiguous correspondence, and unaffected crops after a full rerun.
Ruff check and format passed for the new Python files.
