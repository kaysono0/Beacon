#!/bin/sh
set -eu

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PACKAGE="$ROOT/apps/mac_test_console"
APP_DIR="$ROOT/dist/BeaconMacTestConsole.app"
EXECUTABLE="$PACKAGE/.build/debug/BeaconMacTestConsole"

swift build --package-path "$PACKAGE"

rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources"
cp "$EXECUTABLE" "$APP_DIR/Contents/MacOS/BeaconMacTestConsole"
cat > "$APP_DIR/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>
  <string>BeaconMacTestConsole</string>
  <key>CFBundleIdentifier</key>
  <string>ai.beacon.MacTestConsole</string>
  <key>CFBundleName</key>
  <string>Beacon Mac Test Console</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>0.1.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSMinimumSystemVersion</key>
  <string>13.0</string>
</dict>
</plist>
PLIST

if command -v xattr >/dev/null 2>&1; then
  find "$APP_DIR" -exec xattr -c {} + 2>/dev/null || true
fi

if command -v codesign >/dev/null 2>&1; then
  codesign --force --deep --sign - "$APP_DIR" >/dev/null
fi

printf '%s\n' "$APP_DIR"
