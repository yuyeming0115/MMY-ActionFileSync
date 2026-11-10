#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "[ERROR] build_dmg.sh must be run on macOS (Darwin)." >&2
    exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

echo "========================================"
echo "  MMY-ActionFileSync - macOS DMG build"
echo "========================================"
echo

if [[ -z "${PYTHON:-}" ]]; then
    PYTHON="$ROOT/.venv/bin/python"
    if [[ ! -x "$PYTHON" ]]; then
        echo "[1/6] Creating local virtual environment..."
        if ! command -v python3 >/dev/null 2>&1; then
            echo "[ERROR] python3 not found. Please install Python 3 or set PYTHON." >&2
            exit 1
        fi
        python3 -m venv "$ROOT/.venv"
        if [[ ! -x "$PYTHON" ]]; then
            echo "[ERROR] Failed to create .venv. Please install Python 3 and try again." >&2
            exit 1
        fi
    else
        echo "[1/6] Using local virtual environment: $PYTHON"
    fi
else
    echo "[1/6] Using custom PYTHON: $PYTHON"
    if [[ ! -x "$PYTHON" ]] && ! command -v "$PYTHON" >/dev/null 2>&1; then
        echo "[ERROR] Specified PYTHON is not executable: $PYTHON" >&2
        exit 1
    fi
fi
echo

if [[ "${SKIP_PIP_INSTALL:-0}" == "1" ]]; then
    echo "[2/6] Skipping pip install (SKIP_PIP_INSTALL=1)."
    if ! "$PYTHON" -m PyInstaller --version >/dev/null 2>&1; then
        echo "[ERROR] PyInstaller is not installed in $PYTHON while SKIP_PIP_INSTALL=1." >&2
        exit 1
    fi
else
    echo "[2/6] Installing project dependencies..."
    "$PYTHON" -m pip install -r "$ROOT/requirements.txt"
    if ! "$PYTHON" -m PyInstaller --version >/dev/null 2>&1; then
        echo "PyInstaller is not installed. Installing..."
        "$PYTHON" -m pip install pyinstaller
    else
        echo "PyInstaller is already installed."
    fi
fi
echo

echo "[3/6] Resolving version, timestamp, and architecture..."
STAMP="$("$PYTHON" -m utils.build_stamp)"
read -r VER TS <<< "$STAMP"
if [[ -z "${VER:-}" || -z "${TS:-}" ]]; then
    echo "[ERROR] Failed to read APP_VERSION / timestamp from utils.build_stamp." >&2
    exit 1
fi

ARCH="$(uname -m)"
if [[ -z "${ARCH:-}" ]]; then
    echo "[ERROR] Failed to detect macOS architecture via uname -m." >&2
    exit 1
fi

RELEASE_NAME="v${VER}_${TS}"
RELEASE_DIR="$ROOT/releases/$RELEASE_NAME"
WORK_DIR="$ROOT/build/pyinstaller-macos"
STAGE_DIR="$WORK_DIR/dmg-stage"
ICON_SRC="$ROOT/assets/icon.png"
ICONSET_DIR="$WORK_DIR/app_icon.iconset"
ICNS_PATH="$WORK_DIR/app_icon.icns"
DMG_NAME="MMY-ActionFileSync-v${VER}-macOS-${ARCH}.dmg"
DMG_PATH="$RELEASE_DIR/$DMG_NAME"

echo "    Version : v${VER}"
echo "    Arch    : ${ARCH}"
echo "    Release : releases/${RELEASE_NAME}"
echo

if [[ ! -f "$ICON_SRC" ]]; then
    echo "[ERROR] Missing icon source: $ICON_SRC" >&2
    exit 1
fi

rm -rf "$WORK_DIR"
mkdir -p "$ICONSET_DIR" "$STAGE_DIR" "$RELEASE_DIR"

echo "[4/6] Generating temporary .icns from assets/icon.png..."
sips -s format png -z 16 16     "$ICON_SRC" --out "$ICONSET_DIR/icon_16x16.png" >/dev/null
sips -s format png -z 32 32     "$ICON_SRC" --out "$ICONSET_DIR/icon_16x16@2x.png" >/dev/null
sips -s format png -z 32 32     "$ICON_SRC" --out "$ICONSET_DIR/icon_32x32.png" >/dev/null
sips -s format png -z 64 64     "$ICON_SRC" --out "$ICONSET_DIR/icon_32x32@2x.png" >/dev/null
sips -s format png -z 128 128   "$ICON_SRC" --out "$ICONSET_DIR/icon_128x128.png" >/dev/null
sips -s format png -z 256 256   "$ICON_SRC" --out "$ICONSET_DIR/icon_128x128@2x.png" >/dev/null
sips -s format png -z 256 256   "$ICON_SRC" --out "$ICONSET_DIR/icon_256x256.png" >/dev/null
sips -s format png -z 512 512   "$ICON_SRC" --out "$ICONSET_DIR/icon_256x256@2x.png" >/dev/null
sips -s format png -z 512 512   "$ICON_SRC" --out "$ICONSET_DIR/icon_512x512.png" >/dev/null
sips -s format png -z 1024 1024 "$ICON_SRC" --out "$ICONSET_DIR/icon_512x512@2x.png" >/dev/null

iconutil -c icns "$ICONSET_DIR" -o "$ICNS_PATH"
if [[ ! -f "$ICNS_PATH" ]]; then
    echo "[ERROR] Failed to generate $ICNS_PATH." >&2
    exit 1
fi
echo

echo "[5/6] Building .app bundle with PyInstaller..."
"$PYTHON" -m PyInstaller \
    --noconfirm \
    --clean \
    --windowed \
    --onedir \
    --name "MMY-ActionFileSync" \
    --distpath "$WORK_DIR/dist" \
    --workpath "$WORK_DIR/work" \
    --specpath "$WORK_DIR" \
    --add-data "assets:assets" \
    --icon "$ICNS_PATH" \
    --osx-bundle-identifier "com.mmy-tools.actionfilesync" \
    main.py

APP_BUNDLE="$WORK_DIR/dist/MMY-ActionFileSync.app"
if [[ ! -d "$APP_BUNDLE" ]]; then
    echo "[ERROR] Expected .app bundle not found: $APP_BUNDLE" >&2
    exit 1
fi

INFO_PLIST="$APP_BUNDLE/Contents/Info.plist"
if [[ ! -f "$INFO_PLIST" ]]; then
    echo "[ERROR] Info.plist not found in app bundle: $INFO_PLIST" >&2
    exit 1
fi

/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VER" "$INFO_PLIST" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string $VER" "$INFO_PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $VER" "$INFO_PLIST" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Add :CFBundleVersion string $VER" "$INFO_PLIST"

echo "Re-signing .app bundle after Info.plist update..."
codesign --force --deep --sign - "$APP_BUNDLE"
codesign --verify --deep --strict "$APP_BUNDLE"
echo

echo "[6/6] Packaging compressed .dmg..."
ditto "$APP_BUNDLE" "$STAGE_DIR/MMY-ActionFileSync.app"
ln -s /Applications "$STAGE_DIR/Applications"

for attempt in 1 2 3; do
    if hdiutil create -volname "MMY-ActionFileSync v${VER}" -srcfolder "$STAGE_DIR" -ov -format UDZO "$DMG_PATH"; then
        break
    fi
    if [[ "$attempt" -eq 3 ]]; then
        echo "[ERROR] hdiutil create failed after 3 attempts." >&2
        exit 1
    fi
    echo "[WARN] hdiutil create failed (attempt $attempt/3), retrying in 3s..." >&2
    sleep 3
done

if [[ ! -f "$DMG_PATH" ]]; then
    echo "[ERROR] Expected DMG output not found: $DMG_PATH" >&2
    exit 1
fi

GIT_HASH="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
if [[ -z "$GIT_HASH" ]]; then
    GIT_HASH="unknown"
fi

cat > "$RELEASE_DIR/build_info.txt" <<EOF
app=MMY-ActionFileSync
version=v${VER}
build_time=${TS}
arch=${ARCH}
platform=macOS
bundle_format=dmg+app
git_commit=${GIT_HASH}
EOF

echo
echo "========================================"
echo "  Build completed."
echo "  Output: releases/${RELEASE_NAME}/${DMG_NAME}"
echo "  Info  : releases/${RELEASE_NAME}/build_info.txt"
echo "========================================"
