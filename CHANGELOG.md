# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). While the version stays below `1.0.0`, minor releases may contain breaking changes.

## [Unreleased]

Initial public release preparation.

### Added

- C++ Agent Core: protocol codec and validation, auth and TLS policy, WebSocket connection orchestration, invocation and callback controllers, resource lifecycle management, and structured logging.
- macOS agent adapter with a single RTC backend abstraction covering a mock backend and a real Agora backend, plus main-thread dispatch, permission management, view registry, visual probe, and platform log bridge.
- Beacon Server (FastAPI + WebSocket): device registration, command dispatch, evidence store, Python-native case execution, RTC token issuing, and test report generation.
- Python authoring SDK (`python_sdk/beacon_test`): client, sessions with `run_id/case_id/step_id` trace context, typed SDK facades, callback waiting, and evidence assertions.
- SDK Registry: sources, schemas, and compiled artifacts describing methods, callbacks, states, and metrics per SDK, used by the server for target validation and by agents for provider assembly.
- Mac Test Console: SwiftUI app that browses SDK capabilities and cases, runs suites, polls results, displays artifacts and logs, and exports run reports.
- Cooperative test-run cancellation: authenticated `POST /api/v1/test-runs/{run_id}/cancel` registers a cancellation request in `ServerRunRuntime` and returns the current run snapshot (idempotent for a run that is already terminal). The Python-native executor honours the request at case and step boundaries: in-flight SDK calls and steps finish, cleanup steps still run, un-started non-cleanup steps are skipped without fabricating a step result, and the run reaches the `cancelled` terminal status. The Mac Test Console exposes a Cancel action and never invents a terminal status locally. See ADR-038, which supersedes ADR-025.
- Verification and coverage gates covering protocol compilation, agent core, logging, server, mock E2E, macOS mock adapter, Swift console, and real-SDK paths, with `skipped` semantics for missing SDK environments.
- Documentation set: architecture overview and rules, ADRs, quickstart and authoring guides, and the CI validation contract.
- `BEACON_SDK_REGISTRY_DIR` overrides the compiled SDK registry directory for readers, so an installed Python SDK or a relocated artifact set can be pointed at the right registry. Compilation still writes into the repository's `sdk_registry/compiled`.
- Mac Test Console SDK routing: `BEACON_CONSOLE_SDK_ROUTES` / `--sdk-routes` (`sdk=url#node,sdk=url`) maps each SDK to a server; clicking an SDK in the sidebar switches the console's server URL and node and reloads, an unreachable target keeps the current connection with a visible reason, and startup aligns the selected SDK to the server it is already connected to.
- `scripts/run_manual_env.sh`: one-command tmux manual-testing environment for one Server (:8000), seven real Agents (Agora ×3, Volcengine ×2, ZEGO ×2), and one SDK-routed Console (`up` / `status` / `down`).

### Changed

- Architecture decoupling (B-010): the canonical SDK target key, log redaction and wire JSON encoding now have exactly one owner per language instead of a copy per component, and the compiled SDK registry root is resolved only by `beacon_test.registry_paths.registry_dir()`.
- Agent target validation rejects target objects carrying fields the Target Contract does not declare, matching the rule the server gateway has always enforced.
- The Python and C++ Target Contract implementations now report the same field for a target with multiple defects, and both reject an explicit `null` `interface` or `overload`; the Python control plane previously treated `null` as "field absent" and accepted payloads the agent would then refuse.
- The WebSocket gateway validates targets through the shared Target Contract instead of its own copy of the field list.
- Compiling an SDK registry source fails when a callback target has no event binding, instead of publishing an artifact whose evidence capability is silently empty.
- Log redaction uses a single `<redacted>` placeholder everywhere; the Python-side `***REDACTED***` and `<local-path>` spellings are retired.
- Agent Core redacts only a platform-agnostic baseline (`token`, `app_cert`, `authorization`, `Bearer`). Platform-specific keys and path patterns are injected by the agent adapter through `LogReporter::RegisterPlatformRedaction` before the first event can reach a sink.
- macOS runtime isolation is declaration-first: a case can carry a `runtime-isolation:required` or `runtime-isolation:not-required` tag, and an undeclared case falls back to the SDK assembly default while emitting a `native.runtime_isolation.undeclared` log record.
- SDK-specific control-plane behavior — runtime placeholder resolution, the runtime isolation default and SDK test endpoints — is declared in a single assembly module (`server/app/sdk_extensions.py`), so adding an SDK no longer means editing the control plane. `/api/v1/agora/token` behavior is unchanged.
- Python device handles resolve SDK accessors through the compiled registry artifact (`beacon_test.registry_facade.typed_sdk_facade`) instead of hand-written per-SDK properties, and the committed generated facades are verified against `sdk_registry/compiled` on every server test run.
- Server core dependencies no longer include SDK-specific packages: `agora-token-builder` moved to the optional extra `beacon-server[agora]`. Core test runs skip the optional token-signing test when the extra is absent; the formal gates (`test-server`, `test-server-quiet`, `coverage-server`) install the extra so real-signing paths stay covered.
- Mac Test Console autorun is metadata-driven: the server projects `requires_runtime_isolation` per case (tag declaration first, SDK assembly default as fallback), the console selects the runtime cleanup baseline by the `runtime-reset-baseline` tag among cases sharing the triggering case's SDK (fail closed unless exactly one candidate), orders cases by `autorun-order:` tags (untagged cases run in case-ID order), and only resolves generic `{{ENV_NAME}}` placeholders — SDK-specific placeholders such as tokens are resolved by the server at execution time. The App no longer hardcodes SDK names or case IDs.
- Real-SDK depth validation entrypoints carry the SDK name explicitly: `make test-mac-agora-real`, `test-mac-direct-agent-agora-real`, `coverage-cpp-agora-real`, and `scripts/run_mac_*agora*_*.py`. The cross-SDK Console environment and coexistence gates use the platform-level `run-mac-console-real-server`, `test-mac-console-real`, and `scripts/run_mac_console_real_validation.py`, with no compatibility aliases. Platform-level clauses in `.private/docs/architecture/contracts.md` are generalized to "no concrete SDK (currently Agora)" wording.

### Removed

- `beacon_test.sdks`, including `beacon_test.sdks.agora_rtc.AgoraRtcSDK`: a hand-written facade whose embedded protocol targets duplicated the registry-driven one. Use `beacon_test.generated.AgoraRtcFacade` over `client.sdk("agora_rtc")`, or the `.agora` accessor on an authoring device handle. `wait_callbacks` stays on the underlying `client.sdk("agora_rtc")` handle, not on the typed facade.
- The Mac Test Console's App-side Agora token surgery: the `BEACON_AGORA_RTC_TOKEN_MAP` decode/replace path and the hardcoded autorun priority switch and cleanup case entry. Cleanup baseline selection and case ordering are driven by case metadata (`runtime-reset-baseline`, `autorun-order:`), and token placeholders are resolved by the server at execution time.

### Security

- The Python control plane redacts `AGORA_APP_CERT`, `AGORA_APP_ID` and `app_cert`; previously an app certificate could reach an ingested log event in cleartext.

### Known limitations

- iOS and Android agents are not implemented (roadmap phases 6 and 7).
- Server state is primarily in-memory; persistence is limited to opt-in JSONL snapshots.
- Real OS-level weak-network fault injection requires a privileged test machine and is not enabled by default.
- The Agora SDK is not distributed with this repository; real-device gates report `skipped` without it.
- Continuous integration does not verify real-SDK paths; those gates require a local macOS environment with the Agora SDK and credentials.
