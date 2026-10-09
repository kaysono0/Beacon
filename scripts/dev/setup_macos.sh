#!/bin/bash
# Prepare Beacon's macOS development toolchain and, optionally, vendor RTC SDKs.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WITH_SDKS=0
WITH_AGORA=0
AGORA_URL="${BEACON_AGORA_MAC_SDK_URL:-}"
VOLCENGINE_URL="${BEACON_VOLCENGINE_MAC_SDK_URL:-}"

usage() {
  cat <<'EOF'
Usage: scripts/dev/setup_macos.sh [--with-agora | --with-sdks]

Installs Homebrew dependencies and Beacon's locked Python environment.
With --with-agora, prepares only Agora; --with-sdks prepares both vendors.
Reuses SDKs from the exported SDK root, local env file, third_party/, or a
previous setup download before prompting for official SDK ZIP download
URLs, downloads and installs them under .build/vendor-sdks/, and updates only
the SDK root fields in local.agora.env and local.volcengine.env.

To avoid the URL prompts, set BEACON_AGORA_MAC_SDK_URL and/or
BEACON_VOLCENGINE_MAC_SDK_URL to vendor-provided direct download URLs.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --with-sdks) WITH_SDKS=1 ;;
    --with-agora) WITH_AGORA=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if [ "$(uname -s)" != "Darwin" ]; then
  echo "This setup script supports macOS only." >&2
  exit 1
fi

if ! xcode-select -p >/dev/null 2>&1; then
  echo "Install Xcode Command Line Tools with: xcode-select --install" >&2
  exit 1
fi

for package in cmake uv; do
  if ! command -v "$package" >/dev/null 2>&1; then
    if ! command -v brew >/dev/null 2>&1; then
      echo "Install $package or install Homebrew from https://brew.sh, then rerun this script." >&2
      exit 1
    fi
    brew install "$package"
  fi
done

if ! command -v swift >/dev/null 2>&1; then
  echo "Swift is missing from the selected Xcode toolchain. Check xcode-select -p." >&2
  exit 1
fi

cd "$ROOT"
for media in test_cases/media/animated_clip.mp4 test_cases/media/grid_segments.mp4 \
  test_cases/sample_960x400_ocean_with_audio.mp4 test_cases/sample_960x400_ocean_audio.m4a; do
  if [ ! -s "$media" ]; then
    echo "Required repository media is missing or empty: $media. Restore it from Git before running setup." >&2
    exit 1
  fi
done
uv python install 3.11
uv sync --project server --locked --python 3.11 --extra test --extra agora --extra type

update_env_path() {
  local vendor="$1" key="$2" sdk_root="$3"
  local env_file="$ROOT/local.$vendor.env"
  if [ ! -f "$env_file" ]; then
    cp "$ROOT/local.$vendor.env.example" "$env_file"
    chmod 600 "$env_file"
  fi

  "$ROOT/server/.venv/bin/python" - "$env_file" "$key" "$sdk_root" <<'PY'
from pathlib import Path
import shlex
import sys

path = Path(sys.argv[1])
key = sys.argv[2]
value = shlex.quote(sys.argv[3])
lines = path.read_text().splitlines()
replacement = f"{key}={value}"
found = False
for index, line in enumerate(lines):
    prefix = "export " if line.startswith(f"export {key}=") else ""
    if line.startswith(f"{prefix}{key}="):
        lines[index] = f"{prefix}{replacement}"
        found = True
if not found:
    lines.append(replacement)
path.write_text("\n".join(lines) + "\n")
PY
}

find_local_sdk() {
  "$ROOT/server/.venv/bin/python" - "$ROOT" "$1" "$2" "$3" <<'PYSDK'
from pathlib import Path
import os
import shlex
import sys

root, vendor, key, framework = sys.argv[1:]
root = Path(root)
configured = os.environ.get(key, "")
env_file = root / f"local.{vendor}.env"
if not configured and env_file.is_file():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line.startswith((f"{key}=", f"export {key}=")):
            continue
        fields = shlex.split(line, comments=True)
        if fields and fields[0] == "export":
            fields = fields[1:]
        if fields and fields[0].startswith(f"{key}="):
            configured = fields[0].split("=", 1)[1]
search_roots = ([Path(configured).expanduser()] if configured else []) + [
    root / "third_party" / vendor / "macos" / "sdk",
    *sorted((root / ".build" / "vendor-sdks").glob(f"{vendor}-*"), reverse=True),
]
for directory in search_roots:
    if not directory.is_dir():
        continue
    bundles = sorted(directory.rglob(f"{framework}.xcframework"))
    bundles += sorted(directory.rglob(f"{framework}.framework"))
    for bundle in bundles:
        if any(part.endswith(".xcframework") for part in bundle.parent.parts):
            continue
        if bundle.suffix == ".xcframework" and not any(
            "macos" in child.name and (child / f"{framework}.framework").is_dir()
            for child in bundle.iterdir()
        ):
            continue
        print(bundle.parent.resolve())
        sys.exit(0)
PYSDK
}

install_sdk() {
  local vendor="$1" key="$2" url="$3" archive_url="$3" framework="$4"
  local stage archive unpack found preferred relative destination sdk_root

  sdk_root="$(find_local_sdk "$vendor" "$key" "$framework")"
  if [ -n "$sdk_root" ]; then
    update_env_path "$vendor" "$key" "$sdk_root"
    echo "Reusing $vendor SDK at: $sdk_root"
    return 0
  fi

  if [ -z "$url" ]; then
    case "$vendor" in
      agora)
        echo "Agora macOS SDK: download an SDK ZIP from https://docs.agora.io/en/api-reference/sdks" >&2
        ;;
      volcengine)
        echo "Volcengine RTC SDK: download the macOS SDK ZIP from your Volcengine console or vendor delivery page." >&2
        ;;
    esac
    printf 'Paste the vendor-provided direct ZIP URL (blank to skip): '
    IFS= read -r archive_url || true
  fi
  if [ -z "$archive_url" ]; then
    echo "Skipping $vendor SDK download."
    return 0
  fi
  case "$archive_url" in
    https://*) ;;
    *) echo "SDK download URLs must use HTTPS." >&2; exit 2 ;;
  esac

  printf 'Confirm you have obtained permission and accepted the %s SDK terms before downloading [y/N]: ' "$vendor"
  local consent
  IFS= read -r consent || true
  case "$consent" in y|Y|yes|YES) ;; *) echo "Skipping $vendor SDK; vendor terms were not confirmed."; return 0 ;; esac

  mkdir -p "$ROOT/.build/vendor-sdks"
  stage="$(mktemp -d "$ROOT/.build/vendor-sdks/.setup-${vendor}.XXXXXX")"
  archive="$stage/sdk.zip"
  unpack="$stage/unpacked"
  mkdir -p "$unpack"
  echo "Downloading $vendor SDK from the supplied vendor URL..."
  curl --fail --location --retry 2 --output "$archive" "$archive_url"
  ditto -x -k "$archive" "$unpack"

  preferred="$(find "$unpack" -type d -name "$framework.xcframework" -print -quit)"
  if [ -n "$preferred" ]; then
    found="$preferred"
  else
    found="$(find "$unpack" -type d -name "$framework.framework" -print -quit)"
  fi
  if [ -z "${found:-}" ] || [ ! -d "$found" ]; then
    rm -rf "$stage"
    echo "The downloaded archive does not contain $framework.xcframework or $framework.framework." >&2
    exit 1
  fi

  relative="${found#"$unpack"/}"
  destination="$ROOT/.build/vendor-sdks/$vendor-$(date +%Y%m%d%H%M%S)-$$"
  mv "$unpack" "$destination"
  sdk_root="$destination/$(dirname "$relative")"
  update_env_path "$vendor" "$key" "$sdk_root"
  rm -rf "$stage"
  echo "$vendor SDK installed at: $sdk_root"
}

if [ "$WITH_SDKS" -eq 1 ] || [ "$WITH_AGORA" -eq 1 ]; then
  install_sdk agora AGORA_MAC_SDK_ROOT "$AGORA_URL" AgoraRtcKit
fi
if [ "$WITH_SDKS" -eq 1 ]; then
  install_sdk volcengine VOLCENGINE_MAC_SDK_ROOT "$VOLCENGINE_URL" VolcEngineRTC
fi

cat <<EOF

Beacon's macOS development environment and repository media are ready.
Run the Mock path with: make test-e2e-mock
Agora verification needs credentials in local.agora.env: make test-mac-agora-real
The unified real Console also needs Volcengine and ZEGO SDKs and credentials.
See docs/mac-console.md for the SDK and credential setup steps.
EOF
