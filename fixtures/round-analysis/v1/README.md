# Round-analysis status fixtures

statuses.json contains deterministic status documents for the local round-recording proof of
concept. It covers the queued, evidence-analysis, reconstruction, complete, and failed states.
The complete documents cover all four reconstruction outcomes: resolved, ambiguous, incomplete,
and impossible.

The fixture is contract data. It does not represent a real recognition result. The local PoC
analyzer is deterministic-local/v1; it emits an insufficient_evidence table observation. The
fixtures show the result shapes that the existing reconstruction contract and the first PoC UI
must handle.
