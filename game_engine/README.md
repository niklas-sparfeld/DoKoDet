# DokoDetector game engine

This package owns deterministic Doppelkopf rules and game reconstruction.

## First hop

Run the commands below from `game_engine/`:

- Owned source: `src/game_engine/`.
- Tests: `tests/`.
- Upstream boundary: consume ordered `table-observation/v1` values with the declared round setup.
- Observed-card input: retain `side` (`face_up`, `face_down`, or `unknown`) and identity status;
  `face_down` cards have no identity candidates. Reconstruction does not use side or face-down
  status to make a gameplay decision yet.
- Downstream boundary: emit retained reconstruction hypotheses and replay results for backend,
  operations, and web consumers.
- Local checks:

  ```bash
  mise exec -- uv run pytest
  mise exec -- uv run ruff check .
  mise exec -- uv run ruff format --check .
  ```

Use the [repository documentation route](../README.md#documentation-route) for architecture,
work state, shared contracts, and component boundaries. The
[game-reconstruction contract](../GAME_RECONSTRUCTION_CONTRACT.md) owns the ruleset and serialized
reconstruction boundary. Use the [domain glossary](../docs/glossary.md) for canonical rules and
game terms.
