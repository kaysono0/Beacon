# Contributing to Beacon

Thanks for your interest. Beacon is an early-stage project, so the most useful contributions right now are bug reports with reproducible evidence, verification-gate fixes, documentation corrections, and small well-scoped improvements.

## Before you start

- For a bug or a feature request, open a GitHub Issue using the repository templates. Include the exact command you ran and its output.
- For a security problem, do **not** open an issue — follow [SECURITY.md](SECURITY.md).
- For anything larger than a small local change, comment on the issue first so the scope and the verification plan can be agreed before you write code.

## Development setup

Requirements are listed in the [README](README.md#quick-start). The short version:

```bash
git clone https://github.com/kaysono0/Beacon.git
cd Beacon
make format-check     # sanity check that your checkout and toolchain work
make test-e2e-mock    # mock server + agent + evidence + report, no SDK required
```

Real-SDK work additionally needs the Agora SDK and credentials:

```bash
cp local.agora.env.example local.agora.env
# fill in AGORA_MAC_SDK_ROOT, AGORA_APP_ID, AGORA_APP_CERT, BEACON_AUTH_TOKEN
```

`local.agora.env` is git-ignored. Never commit credentials, tokens, or SDK binaries.

## Verification requirements

The [development and validation guide](docs/development.md) documents public test entrypoints, artifacts, and skipped/failure semantics. Read it before adding or changing a gate.

Use the guide's change-surface table: PR basics run on Linux, platform checks run when relevant, and real-SDK/coverage checks run in an explicitly selected, provisioned environment. The command catalog is not an all-target checklist; do not run `test-all` or every coverage target for a documentation or narrowly scoped gate change.

Rules the project holds to:

- **A gate that needs a real SDK must report `skipped` and exit `0` when the environment is missing.** Never convert a missing environment into a failure, and never convert a skip into a pass in documentation or reports.
- **Reports in `reports/` are generated artifacts.** Do not commit them; regenerate them with the gate that owns them.
- **No credentials in reports, artifacts, or logs.** If you are adding logging near credentials, follow the redaction rules in [docs/architecture.md](docs/architecture.md).
- **Do not add SDK business semantics to the framework layer.** SDK knowledge belongs in registry sources, protocol operations, and platform providers; the agent core, server, and authoring SDK stay SDK-agnostic.

## Architecture and truth layers

Before changing behaviour, consult the documents relevant to the affected area:

- [CONTEXT.md](CONTEXT.md) — project language and terminology boundaries.
- [AGENTS.md](AGENTS.md) — repository truth layers, collaboration, and writeback rules.
- [Architecture](docs/architecture.md) — execution path and component boundaries. Propose changes to these boundaries in the issue first.

`AGENTS.md` defines truth ownership and collaboration rules. Update the affected truth file in the same pull request when behavior, protocol, schema, report shape, validation, or workflow policy changes; local private notes are not required for public contributions.

## Code style

- C++17, no exceptions across module boundaries; result types are used for recoverable failures.
- Python 3.11 with type hints; `server/app` is type-checked with mypy via `make type-server`.
- Swift 5.9 for the console; SwiftUI views stay thin, logic goes into testable models.
- Code comments follow [docs/development.md#code-style](docs/development.md#code-style) and are written in Chinese unless the file or an external API contract requires otherwise.
- `make format-check` enforces trailing whitespace and trailing newlines on tracked text files.

## Pull requests

- One logical change per pull request; keep unrelated refactors out.
- Use the pull request template: explain the change and record verification commands, actual results, and any relevant limitations.
- Update docs in the same pull request when you change behaviour.
- Expect review to ask for evidence, not for reassurance: point at the report artifact or the test that proves your claim.

## Reporting problems

When opening an issue, include:

- platform and version (`sw_vers`, `python3 -V`, `swift --version`, Agora SDK version),
- the exact command,
- the generated report or the relevant excerpt from `reports/latest/`,
- whether the real SDK environment was present (a `skipped` result is not a reproduction).

Use the repository issue templates to provide reproducible evidence.
