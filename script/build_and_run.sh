#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="$ROOT_DIR/app"
PRODUCT="SudoBrain"
BUNDLE_ID="com.sudobrain.app"
BINARY="$APP_DIR/.build/debug/$PRODUCT"
BUNDLE="$ROOT_DIR/dist/$PRODUCT.app"
MODE="${1:-run}"

usage() {
  echo "usage: $0 [run|--debug|debug|--logs|logs|--telemetry|telemetry|--verify|verify]" >&2
}

echo "Stopping existing $PRODUCT processes..."
pkill -x "$PRODUCT" 2>/dev/null || true

echo "Building $PRODUCT..."
swift build --package-path "$APP_DIR"

echo "Staging $BUNDLE..."
rm -rf "$BUNDLE"
mkdir -p "$BUNDLE/Contents/MacOS" "$BUNDLE/Contents/Resources"
cp "$BINARY" "$BUNDLE/Contents/MacOS/$PRODUCT"
chmod +x "$BUNDLE/Contents/MacOS/$PRODUCT"

cat > "$BUNDLE/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>SudoBrain</string>
    <key>CFBundleIdentifier</key>
    <string>com.sudobrain.app</string>
    <key>CFBundleName</key>
    <string>SudoBrain</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>13.0</string>
    <key>NSPrincipalClass</key>
    <string>NSApplication</string>
</dict>
</plist>
PLIST

open_app() {
  SUDOBRAIN_PROJECT_DIR="$ROOT_DIR" /usr/bin/open -n "$BUNDLE"
}

case "$MODE" in
  run)
    echo "Launching $PRODUCT..."
    open_app
    ;;
  --debug|debug)
    lldb -- "$BUNDLE/Contents/MacOS/$PRODUCT"
    ;;
  --logs|logs)
    echo "Launching $PRODUCT and streaming process logs..."
    open_app
    /usr/bin/log stream --info --style compact --predicate "process == \"$PRODUCT\""
    ;;
  --telemetry|telemetry)
    echo "Launching $PRODUCT and streaming telemetry logs..."
    open_app
    /usr/bin/log stream --info --style compact --predicate "subsystem == \"$BUNDLE_ID\""
    ;;
  --verify|verify)
    echo "Launching $PRODUCT..."
    open_app
    echo "Verifying process launch..."
    for _ in {1..20}; do
      if pgrep -x "$PRODUCT" >/dev/null; then
        echo "$PRODUCT is running."
        exit 0
      fi
      sleep 0.5
    done
    echo "$PRODUCT did not appear in the process list." >&2
    exit 1
    ;;
  *)
    usage
    exit 2
    ;;
esac
