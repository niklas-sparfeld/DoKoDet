---
name: model-improvement
description: Use when an operator asks to inspect DokoDetector model campaigns, propose a bounded recipe, run or resume a fixture or component campaign, compare validation artifacts, or explain promotion evidence. Do not use for model code changes or autonomous promotion.
---

# DokoDetector model improvement

Use this skill for bounded model-improvement work in this repository. The Python operations package
owns state changes, validation, candidate locks, sealed tests, and promotion. Keep the skill as an
operator aid around those contracts.

## Workflow

1. Inspect the checked-in recipe, the component registry entry, and read-only campaign status.
   Confirm the component, capability, baseline bundle, data digests, and declared experiment axes.
2. If a change is useful, create a proposed recipe with
   `scripts/propose_recipe.py`. Give the operator a short reason for each axis. The script validates
   the recipe with the same `ModelRecipe` contract used by `doko` and writes the canonical recipe
   mapping that `doko model improve` consumes.
3. Ask the operator to review the proposal. Then run the normal command:

   ```text
   doko model improve <component> --recipe <proposed-recipe.json>
   ```

   For a resumed campaign, use the same recipe and campaign root. Use `doko model status` and
   `doko model compare <campaign-id>` for read-only inspection.
4. Summarize the machine-readable `comparison.json`, including the recommendation, selection order,
   failed candidates, and data and gate identities. Do not infer a recommendation from prose.
5. Stop at `candidate_locked` and hand the operator the next action. The operator must confirm the
   sealed test and promotion. The skill may prepare, but must not run, a promotion command:

   ```text
   doko model promote <campaign-id> --confirm
   ```

## Safety boundaries

- Before candidate lock, read validation artifacts only. Do not open sealed-test, system-holdout,
  or promotion artifacts, and never use them to choose a candidate.
- Never edit a resolved recipe, campaign file, comparison, candidate lock, test report, promotion
  receipt, model bundle, or champion registry. A proposal is a new input artifact, not a campaign
  mutation.
- Never add candidates after the campaign starts, accept model output as labels, bypass a gate, or
  invoke promotion without explicit operator confirmation.
- The proposal helper refuses campaign and registry destinations and refuses to overwrite an
  existing file. It reads only the source recipe and writes one proposed-recipe artifact.
- Keep the exact `doko` commands and checked-in paths in the handoff so a contributor can repeat the
  work without this skill.

## Human handoff

Use this handoff after a successful validation comparison:

```text
Candidate lock: <candidate-id>
Recommendation: <promote_candidate|keep_champion|human_review_required|no_valid_candidate>
Review: inspect comparison.json and lock.json, then confirm whether to run the sealed test.
Promotion: only the operator runs doko model promote <campaign-id> --confirm.
```

If the campaign is blocked by a stale champion, data leakage, an incompatible contract, a failed
gate, or a required human decision, stop. Record the blocking artifact and exact command. Propose a
follow-up epic for research or contract work when the operator must make a decision. Do not start a
new candidate in the completed campaign.

## Clean-room reproduction

The fixture path uses the same public command and artifact contracts as a real campaign:

```text
mise exec -- uv run --project operations doko model improve card-event-net \
  --recipe fixtures/model-improvement/v1/recipe-cardevent.json \
  --repository-root fixtures/model-improvement/v1/valid \
  --model-registry registry.json --campaign-root <campaign-root> \
  --project-root <fixture-project> --runner fixture --format json
mise exec -- uv run --project operations doko model compare <campaign-id> \
  --repository-root fixtures/model-improvement/v1/valid \
  --model-registry registry.json --campaign-root <campaign-root> --format json
```

Run the same command with the proposed recipe. Compare
`campaign.json`, `comparison.json`, and `lock.json` as structured JSON. The two paths must produce
the same campaign ID, recommendation, selection order, and result digests.
