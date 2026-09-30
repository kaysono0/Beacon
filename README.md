# Beacon

**Drive real device SDKs with Python and see calls, callbacks, media, and test results in one console.**

Beacon is a Python framework for device SDK testing and test automation. It brings Native SDK calls, declarative callback hooks, multi-device orchestration, and a visual macOS console into one testing workflow. Current integrations cover Agora, Volcengine, and ZEGO Express for real-time communication (RTC) and audio/video testing.

[中文说明](README.zh-CN.md)

## Mac Console App demos

Mac Console App overview:

<img src="https://raw.githubusercontent.com/kaysono0/MyPicList/main/image-20260930095958850.png" alt="Beacon Mac Console App overview" style="zoom:50%;" />

Agora Join and Leave test case demo:
![Agora Join and Leave test case demo](https://raw.githubusercontent.com/kaysono0/MyPicList/main/image-20260930100126344.png)

Agora multi-instance test run:
![Agora multi-instance test run](https://raw.githubusercontent.com/kaysono0/MyPicList/main/image-20260930100154258.png)

Click to [watch the 53-second product demo](https://github.com/user-attachments/assets/bc1f40c0-0c34-48fa-861d-ca6bee3e56c1), with the original audio and Chinese and English subtitles. The video shows:

- **API and callback validation**: run an Agora room-join case in the Console and inspect execution records and actual callbacks.
- **Multiple video streams**: run four-way and nine-way video cases and see the rendered output.
- **Execution through results**: select a case, start a run, and inspect its result in the same interface.

## What Beacon brings

### Write tests in ordinary Python

SDK calls, callback waits, and assertions live in Python cases. Each call executes immediately on the device. Authors can organize cases around their test scenarios and reuse Python conditions, loops, and helper functions.

### Verify both call results and subsequent behavior

Return values, asynchronous callbacks, state, and media metrics are recorded and checked separately. A case can check whether a call succeeded, then verify that the expected callback arrived with the correct fields. Each record retains its test and device context.

### Simplify callback testing with defer

Tests that perform actions when an SDK callback fires need to connect asynchronous events, subsequent calls, and result checks. For supported SDK callbacks and actions, Beacon uses `defer` to register the callback target and actions with the device Agent ahead of time. When a matching callback arrives, the predefined actions execute locally during Native callback handling, without waiting for Python to send another command. This reduces cross-process communication and callback coordination for test authors.

Actions inside callbacks reuse the same invocation executor and interface implementations as ordinary calls. The Agent reports whether the rule matched, along with each action's error code and return value, in the callback record. Python cases wait for that record and assert the results, completing the workflow from registration to local execution to verification.

See the [immediate-call and callback design](docs/architecture.md#callback).

### Coordinate multiple devices in one case

Cases control devices through roles such as primary and peer, coordinating publishers, subscribers, and multiple participants. Each device's calls, callbacks, and resources retain their own context, allowing one test to check behavior across endpoints.

### Make audio/video results visible

The macOS Console brings together cases, run progress, execution records, logs, and report export. Audio/video cases can also show local and remote media and capture view snapshots, bringing API checks and actual media output into the inspection workflow.

### Share a workflow across SDKs and extend it across platforms

Agora, Volcengine, and ZEGO Express share the framework and Console while retaining their native APIs and lifecycles. Adapters handle SDK differences; test authoring, run control, and result inspection follow a shared workflow.

The shared Agent Core owns platform-independent protocols, invocation, and callback handling. Platform adapters own connections, permissions, and SDK hosting, providing a common foundation for additional platforms. macOS is implemented today; iOS and Android Agents have not yet started.

## Quick start

Start with Mock execution, which needs no vendor SDK or credentials, then move to real SDKs as needed.

1. **Prepare a Mac development environment**: run `bash scripts/dev/setup_macos.sh`; to install real SDKs, add `--with-sdks` and provide vendor download links. Then follow the [quickstart](docs/quickstart.md) to run Mock cases and inspect the report.
2. **Try real SDKs and the Console**: follow the [Mac Console guide](docs/mac-console.md) to configure SDKs, credentials, and permissions, then start the services and App.
3. **Write your own case**: use the [Python test authoring guide](docs/python-test-authoring-guide.md) for SDK calls, callback waits, and resource cleanup.

For component responsibilities and the execution path, see the [architecture overview](docs/architecture.md).

## Code map

| Path | Responsibility |
|---|---|
| [`server/`](server/README.md) | FastAPI control plane, device/run lifecycle, Runner supervision, observations, reports |
| `python_sdk/beacon_test/` | `BeaconSession`, generated typed facades, Python Runner |
| `test_cases/python/` | Runnable SDK test cases |
| `agent_core/` | Platform-independent C++ protocol, invocation, resources, logging |
| `agents/mac/` | macOS provider integration, permissions, Native mock and real SDK backends |
| `apps/mac_test_console/` | SwiftUI case browser, run control, observation display, report export |
| `sdk_adapters/`, `sdk_registry/` | Capability sources, schemas, compiled Registry artifacts |
| [`scripts/`](scripts/README.md) | Development, validation, generation, coverage, and shared tools |
| [`tests/`](tests/README.md) | Tool regressions and cross-component contracts |
| `docs/` | Essential developer guides and public demo assets |

Component tests live with their components, such as `server/tests/`, `python_sdk/tests/`, `agent_core/tests/`, and the Console's `Tests/`. Mock E2E is driven by `scripts/validation/`.

## Real SDKs and project status

Beacon is an early-stage project (0.1.0). The macOS integrations cover Agora, Volcengine, and ZEGO. Each has its own SDK, credentials, and validation requirements. Mock success does not prove real SDK or media behaviour.

iOS/Android Agents and real OS-level weak-network injection remain future work. Server storage supports in-memory operation and opt-in JSONL snapshots. Implementation boundaries are summarized in the [architecture guide](docs/architecture.md).

Native macOS development requires macOS 13+, CMake, and an Xcode toolchain compatible with the installed macOS SDK. For SDK setup, Server/App startup, shutdown, camera permissions, and real validation, use the [Mac Console guide](docs/mac-console.md).

## Documentation and contribution

The [documentation map](docs/README.md) routes readers by task. It covers setup, case authoring, SDK integration, architecture, and validation.

Start contributions with [CONTRIBUTING.md](CONTRIBUTING.md). Report security issues according to [SECURITY.md](SECURITY.md). Verification commands and passed/skipped/failed semantics belong to the [development and validation guide](docs/development.md).

## License

[MIT](LICENSE). Vendor SDKs and local credentials are not distributed with this repository; see [THIRD-PARTY.md](THIRD-PARTY.md).
