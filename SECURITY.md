# Security policy

## Supported versions

Beacon is pre-1.0. Security fixes are applied to the `main` branch only; there are no maintained release branches yet.

| Version | Supported |
| --- | --- |
| `main` (0.1.x) | yes |
| older tags | no |

## Reporting a vulnerability

Please report suspected vulnerabilities privately through GitHub's security advisory feature on this repository ("Security" tab → "Report a vulnerability"). Do not open a public issue, and do not include credentials or personal data in any report.

Useful reports include:

- the affected component (`agent_core`, `agents/mac`, `server`, `python_sdk`, `apps/mac_test_console`) and version or commit,
- a description of the impact and the conditions required to trigger it,
- a minimal reproduction, ideally a failing test or a command sequence,
- any suggested fix or mitigation.

This is a volunteer-maintained project, so responses are best-effort; there is no response-time guarantee. You will be credited in the advisory unless you prefer otherwise.

## Scope

In scope:

- Authentication and token handling between the server, the harness, and device agents.
- TLS and WebSocket transport handling in the agent core.
- Credential leakage into logs, reports, artifacts, or evidence records.
- Privilege boundaries in the macOS adapter (permission handling, privileged network fault injection).
- Server API endpoints reachable by a device agent or by the console (`/api/v1`).
- Path handling and file access for artifacts, logs, and exported reports.

Out of scope:

- Vulnerabilities in the Agora SDK itself or in Agora's services — report those to Agora.
- Vulnerabilities in third-party dependencies; report them upstream. If a dependency issue requires a Beacon-side change, tell us anyway.
- Findings that require an already-compromised machine, or that only affect a local mock configuration.

## Handling of credentials

Beacon reads Agora and auth credentials from the environment, typically loaded from a git-ignored `local.agora.env` at the repository root. Credentials must never be committed, printed in logs, embedded in report bodies, or copied into artifact metadata. If you find a path where a credential can leak, treat it as in-scope and report it privately.

If you believe a credential has been committed or exposed, rotate it immediately at its source (Agora console, local token configuration) before reporting.
