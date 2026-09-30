# Volcengine RTC SDK (not bundled)

Beacon's real macOS backend links the Volcengine (ByteRTC) SDK, which is proprietary software distributed by Volcengine. **This repository does not contain the SDK and does not redistribute it.** Obtain the macOS SDK yourself from Volcengine and accept Volcengine's own license terms before using the real-device gates.

The SDK drop-in path is git-ignored; only this README is tracked.

## Expected layout

Place the unpacked macOS SDK under `macos/sdk/`. Unlike the Agora SDK, this one is a bundle of frameworks plus dylibs (the layout below is from `VolcEngineRTC_3.60.103.2000`), so a variant build must link all of them and resolve them at runtime:

```text
third_party/volcengine/
├── README.md                 # this file (tracked)
└── macos/sdk/                # git-ignored - put the Volcengine macOS SDK here
    └── VolcEngineRTC_<ver>/
        ├── VolcEngineRTC.framework
        ├── RTCFFmpeg.framework
        ├── ByteRTC*Extension.framework
        ├── libbytevc0.dylib
        └── ...
```

Create the ignored directory yourself, then unpack into place:

```bash
mkdir -p third_party/volcengine/macos/sdk
# unpack the zip you downloaded so that
# third_party/volcengine/macos/sdk/<sdk>/VolcEngineRTC.framework exists
```

Point Beacon at it either by using the layout above or by setting `VOLCENGINE_MAC_SDK_ROOT` to the directory that contains `VolcEngineRTC.framework`:

```bash
export VOLCENGINE_MAC_SDK_ROOT="$PWD/third_party/volcengine/macos/sdk/VolcEngineRTC_3.60.103.2000"
```

`VOLCENGINE_MAC_SDK_ROOT` and the `VOLCENGINE_RTC_ID` / `VOLCENGINE_RTC_APPKEY` credentials belong to your own Volcengine project. Credentials stay local in `local.volcengine.env` (git-ignored, template in `local.volcengine.env.example`) and must never be committed.

## Environment traps (macOS)

Two issues show up the first time this SDK is used on macOS, both unrelated to Beacon's code:

1. **Quarantine attributes.** The zip you download carries `com.apple.quarantine` on every file. While they are present, dyld refuses to load the frameworks and macOS may tell you the framework "is damaged and can't be opened". Symptoms: the agent binary aborts at launch with `Library not loaded: @rpath/VolcEngineRTC.framework/...` even though the file exists, and Finder offers to move the framework to the Trash (which deletes the extracted copy — re-extract from the zip afterwards). Fix by clearing the attribute on every entry (macOS ships a BSD `xattr` **without** `-r`, so recurse yourself):

   ```bash
   cd third_party/volcengine/macos/sdk/<sdk-dir>
   find . -print0 | xargs -0 xattr -d com.apple.quarantine
   ```

2. **Duplicate Objective-C classes.** `libeffect.dylib` embeds its own copies of several Metal classes, so the runtime prints `Class MTL... is implemented in both ... and .../libeffect.dylib` at startup. These are vendor-packaging warnings; the real-backend tests pass with them present. Vulkan/DirectX-style messages (`espresso version: ...`, `mobilecv2: ...`) are likewise the SDK's own logging.

The framework's embedded signature is ad-hoc (`linker-signed`) and macOS reports `code has no resources but signature indicates they must be present` when you ask `spctl` to assess it. Loading works once the quarantine attributes are gone; if a future macOS release refuses the framework outright, re-sign the SDK locally with `codesign --force --deep --sign - <framework>` (this modifies your local, git-ignored copy only).

## When the SDK is absent

The mock variants, the protocol/Server test suites, and every coverage gate that does not need a real SDK keep working. Volcengine real gates report `skipped` and exit successfully when the SDK or credentials are missing. Skipped means "not verified in this environment", not "passed".

See `THIRD-PARTY.md` for the full dependency and license inventory, including the vendored Python AccessToken sample.
