# Agora SDK (not bundled)

Beacon's real macOS backend links the Agora RTC SDK, which is proprietary software distributed by Agora. **This repository does not contain the SDK and does not redistribute it.** Obtain the Agora macOS SDK yourself from Agora and accept Agora's own license terms before using the real-device gates.

The SDK drop-in path and the reference checkout are git-ignored; only this README is tracked.

## Expected layout

Place the unpacked macOS SDK so that `AgoraRtcKit.framework` or `AgoraRtcKit.xcframework` is reachable from the SDK root:

```text
third_party/agora/
├── README.md            # this file (tracked)
├── macos/sdk/           # git-ignored — put the Agora macOS SDK here
│   └── Shengwang_Native_SDK_for_Mac_FULL/
│       └── libs/        # this directory is the AGORA_MAC_SDK_ROOT value
└── reference/
    └── API-Examples/    # git-ignored — optional local checkout of Agora's public examples
```

Create the ignored directories yourself, then unpack the SDK into place:

```bash
mkdir -p third_party/agora/macos/sdk
# unpack the Agora macOS SDK you downloaded so that
# third_party/agora/macos/sdk/<sdk>/libs/AgoraRtcKit.framework (or .xcframework) exists
```

The real backend is enabled when the SDK root contains `AgoraRtcKit.framework` or `AgoraRtcKit.xcframework`. Point Beacon at it either by using the layout above or by setting `AGORA_MAC_SDK_ROOT` directly:

```bash
export AGORA_MAC_SDK_ROOT="$PWD/third_party/agora/macos/sdk/Shengwang_Native_SDK_for_Mac_FULL/libs"
```

`AGORA_MAC_SDK_ROOT` and the `AGORA_APP_ID` / `AGORA_APP_CERT` credentials belong to your own Agora project. Credentials stay local in `local.agora.env` (git-ignored, template in `local.agora.env.example`) and must never be committed.

## When the SDK is absent

The mock backends, the protocol/Server test suites, and every coverage gate that does not need a real SDK keep working. Real-device gates report `skipped` and exit successfully when the SDK or credentials are missing:

- `make test-mac-agora-real`
- `make test-mac-console-agora`
- `make coverage-cpp-agora-real`
- `make test-mac-direct-agent-agora-real`

Skipped means "not verified in this environment", not "passed". See `THIRD-PARTY.md` for the full dependency and license inventory.
