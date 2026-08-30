# Gemini round analysis integration

## Plan status

- **Summary:** Make the backend round-analysis path use Gemini for every normal analysis.
- **Status:** Closed
- **Depends on:** Existing Gemini visible-card and identity-classification providers and completed
  Plan 0032.
- **Closure reason:** Complete
- **Closure note:** The normal backend application now requires a Gemini API key and constructs the
  Gemini visible-card and identity-classification analyzer without a runtime fallback.
- **Boundary:** This plan selects Gemini at the backend analyzer boundary. It does not claim that
  the current visible-card capability is production-quality or that one evidence package contains
  a complete round.

## Milestone status

- **M0:** Complete — configure the backend to construct the Gemini analyzer and require its runtime
  credential.

## 1. Outcome

The normal backend server must refuse to start without `GEMINI_API_KEY`. When the key is present,
each round-analysis evidence package is processed by the Gemini visible-card provider and Gemini
identity classifier. The backend must not silently select the deterministic local analyzer.

The existing explicit analyzer injection remains available to local tests. It is not a server
configuration or a runtime fallback.

## 2. Delivery milestones

### M0 — Always-on Gemini backend analyzer

- Add runtime Gemini settings for the API key, model, timeout, and retry count.
- Construct the cached Gemini visible-card provider and Gemini identity classifier behind the
  existing `TableEvidenceAnalyzer` boundary.
- Make the backend application factory select Gemini when no test analyzer is injected, and fail
  clearly when the key is absent.
- Add tests that verify provider selection and missing-credential behavior without making network
  requests.
- Document the required server environment.

#### M0 implementation evidence — 2026-08-30

- Added required runtime settings for `GEMINI_API_KEY`, model, timeout, and bounded retries.
- Made the normal backend application construct cached Gemini visible-card and identity-classifier
  components behind the existing `TableEvidenceAnalyzer` boundary.
- Removed the deterministic local analyzer from the normal application default. It remains an
  explicit test-only injection.
- Verification: backend tests (126 passed), analyzer package tests (55 passed), focused Ruff
  checks, and local HTTP pipeline checks pass. The backend format check retains one unrelated
  pre-existing assertion-format finding.
