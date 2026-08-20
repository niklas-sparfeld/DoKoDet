# AGENTS.md

## Development

Keep changes small and easy to verify.

Use a lightweight test-driven workflow when it makes sense:

1. Write or update a test.
2. Implement the change.
3. Run the relevant tests and checks.

Prefer automated verification over repeated manual testing.

## Git

Use trunk-based development.

* Work directly on `main`.
* Do not create branches unless explicitly requested.
* Keep commits focused.
* Do not modify or discard unrelated changes.

## Language

Use [ASD-STE100](https://github.com/danyuchn/asd-ste100-skill) principles for documentation and technical prose.

Use simple English, short sentences, active voice, and consistent terminology.

## Local development

Prefer fast, reproducible development on a MacBook.

Do not require cloud infrastructure, phones, or other real hardware for the normal development loop when a practical local substitute exists.

Prefer fixtures, recorded inputs, mocks, simulators, and local implementations where appropriate.

## Tooling

Use `mise` to declare the project's development toolchain in `mise.toml`.

* Keep `mise.toml` in git.
* Add required runtimes and development tools to it where practical.
* Respect the versions declared there.
* Run `mise install` after setup changes.
* Use the normal tooling of each language for dependencies, tests, builds, and formatting.

Do not add `mise` tasks merely to wrap existing project commands.

## Verification

Before considering a change complete:

* run the relevant automated tests,
* run applicable linting, formatting, type, or static checks,
* verify that the change is reproducible locally,
* add a regression test for a fixed bug when practical.
