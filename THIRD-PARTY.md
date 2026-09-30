# Third-party components

Beacon's own source code is licensed under the MIT License (see [LICENSE](LICENSE)). This file records the third-party components that Beacon builds against, links, or fetches, and the terms under which they are used.

## Not bundled: Agora RTC SDK

This repository does **not** contain the Agora RTC SDK. The real macOS backend links `AgoraRtcKit.framework`, which is proprietary software distributed by Agora:

- You must obtain the Agora macOS SDK yourself and agree to Agora's own license terms.
- Place it under `third_party/agora/macos/sdk/` (git-ignored) or set `AGORA_MAC_SDK_ROOT`.
- Credentials (`AGORA_APP_ID`, `AGORA_APP_CERT`) belong to your own Agora project and stay local in `local.agora.env` (git-ignored).
- `third_party/agora/reference/API-Examples/` is a local, git-ignored checkout of Agora's public API-Examples repository, also governed by Agora's terms.

Without the Agora SDK and credentials, real-device gates report `skipped` and exit successfully; mock backends and the protocol/Server test suites still run.

## Not bundled: Volcengine RTC SDK

This repository does **not** contain the Volcengine (ByteRTC) macOS SDK. The real macOS backend links `VolcEngineRTC.framework` and its companion frameworks/dylibs, which are proprietary software distributed by Volcengine:

- You must obtain the macOS SDK yourself and agree to Volcengine's own license terms.
- Place it under `third_party/volcengine/macos/sdk/` (git-ignored) or set `VOLCENGINE_MAC_SDK_ROOT`.
- Credentials (`VOLCENGINE_RTC_ID`, `VOLCENGINE_RTC_APPKEY`) belong to your own Volcengine project and stay local in `local.volcengine.env` (git-ignored).

Without the SDK and credentials, the Volcengine real gates report `skipped` and exit successfully; the Volcengine mock variant, the protocol layer and the Server test suites still run.

## Vendored: Volcengine RTC AccessToken (Python)

`server/vendor/volcengine_rtc_token/` is a verbatim copy of Volcengine's official Python token-generation sample, used by the Server to sign room tokens.

| Item | Value |
| --- | --- |
| Source repository | https://github.com/volcengine/rtc-aigc-embedded-demo |
| Source path | `server/src/AccessToken.py` |
| Upstream commit | `2bb1bf2dbbf40bb09ab59c1c0c39c84c797a34db` |
| License | MIT (Copyright (2025) Beijing Volcano Engine Technology Ltd.; SPDX header preserved in the file) |
| Runtime dependencies | none — Python standard library only |

It is vendored rather than declared as a dependency because upstream publishes no installable Python package, and ADR-036 forbids the Server core from hard-depending on any specific SDK's runtime. Upgrade procedure and the recorded `sha256` are documented in `server/vendor/volcengine_rtc_token/README.md`.

## C++ dependencies (fetched at configure time)

Declared in `agent_core/CMakeLists.txt` via CMake `FetchContent` when a system package is not found:

| Component | Version | License | Link |
| --- | --- | --- | --- |
| jsoncpp | 1.9.6 | MIT (or public domain, at your option) | https://github.com/open-source-parsers/jsoncpp |
| spdlog | v1.15.3 | MIT | https://github.com/gabime/spdlog |

No third-party C++ source is vendored into this repository.

## Python dependencies

Declared in `server/pyproject.toml`, locked in `server/uv.lock`.

### Runtime

| Package | Version | License |
| --- | --- | --- |
| agora-token-builder | 1.0.0 | MIT (Copyright (c) 2021 Agora.io) |
| fastapi | 0.136.1 | MIT |
| jsonschema | 4.26.0 | MIT |
| pydantic | 2.13.4 | MIT |
| uvicorn | 0.47.0 | BSD-3-Clause |

Note: `agora-token-builder` is an MIT-licensed helper from Agora that generates RTC/RTM tokens. It is unrelated to the Agora SDK license and does not ship any SDK binary.

### Test and type checking

| Package | Version | License |
| --- | --- | --- |
| pytest | 9.0.3 | MIT |
| httpx | 0.28.1 | BSD-3-Clause |
| pyyaml | 6.0.3 | MIT |
| mypy | 2.3.0 | MIT |
| types-jsonschema | 4.26.0.20260518 | Apache-2.0 |

### Notable transitive dependencies

| Package | Version | License |
| --- | --- | --- |
| annotated-doc | 0.0.4 | MIT |
| annotated-types | 0.7.0 | MIT |
| anyio | 4.13.0 | MIT |
| ast-serialize | 0.6.0 | MIT |
| attrs | 26.1.0 | MIT |
| certifi | 2026.5.20 | MPL-2.0 |
| click | 8.4.1 | BSD-3-Clause |
| colorama | 0.4.6 | BSD-3-Clause |
| h11 | 0.16.0 | MIT |
| httpcore | 1.0.9 | BSD-3-Clause |
| idna | 3.16 | BSD-3-Clause |
| iniconfig | 2.3.0 | MIT |
| jsonschema-specifications | 2025.9.1 | MIT |
| librt | 0.13.0 | MIT |
| mypy-extensions | 1.1.0 | MIT |
| packaging | 26.2 | Apache-2.0 OR BSD-2-Clause |
| pathspec | 1.1.1 | MPL-2.0 |
| pluggy | 1.6.0 | MIT |
| pydantic-core | 2.46.4 | MIT |
| pygments | 2.20.0 | BSD-2-Clause |
| referencing | 0.37.0 | MIT |
| rpds-py | 2026.5.1 | MIT |
| starlette | 1.0.1 | BSD-3-Clause |
| typing-extensions | 4.15.0 | PSF-2.0 |
| typing-inspection | 0.4.2 | MIT |

### Additional locked runtime and test dependencies

Makefile Python targets use the locked Server project environment. These additional dependencies are pinned in `server/uv.lock`:

| Package | Version | License | Used by |
| --- | --- | --- | --- |
| coverage | 7.16.2 | Apache-2.0 | test extra; coverage gates (`make coverage-*`) |
| websockets | 17.1 | BSD-3-Clause | Server runtime WebSocket support and E2E harness |

## Swift

`apps/mac_test_console/Package.swift` declares no external Swift package dependencies. The console builds only against Apple SDK frameworks (SwiftUI, AppKit, Foundation) and XCTest.

## Apple and platform frameworks

The macOS agent and console link Apple system frameworks (AVFoundation, CoreMedia, CoreVideo, Foundation, AppKit, SwiftUI, XCTest). These are covered by the Apple SDK license that comes with Xcode and are not redistributed here.

## Reporting

If you believe a third-party component is listed incorrectly or is missing, open an issue.

## ZEGO and tracked media inventory

The tracked file inventory contains no ZEGO SDK binary. The Mac real gate reads `ZEGO_MAC_SDK_ROOT`; the local `third_party/ZegoExpressDemo_ios_objc.zip` is excluded from Git and remains on the developer's machine.

The repository currently tracks these MP4 fixtures. Their source and redistribution evidence have not been recorded in this file; record that evidence before a public release.

- `agents/mac/resources/beacon_synthetic_loop.mp4`
- `test_cases/sample_1280x720.mp4`
- `test_cases/sample_1280x720_surfing_with_audio.mp4`
- `test_cases/sample_960x400_ocean_with_audio.mp4` (compressed, with the original duration and audio track)
- `test_cases/media/animated_clip.mp4` (transcoded from seconds 60–90 of the local `BigBuckBunny_320x180.mp4`)
- `test_cases/media/grid_segments.mp4` (compressed from the first eight minutes of the local `big_buck_bunny_720p_h264.mov`, with its audio downmixed to stereo AAC)

Local SDKs, private environment files, generated reports, and private `.scratch` specifications remain outside the public file set. Removing them from the current tracked set does not remove their historical Git versions.
