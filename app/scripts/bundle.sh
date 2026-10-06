#!/usr/bin/env bash
# Build a release F1Lap.app into app/build/. Personal use: unsigned apart from an ad-hoc signature,
# and the sidecar runs from this checkout's .venv (path baked in at build time, or F1LAP_REPO).
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
swift build -c release --product F1Lap
bin="$(swift build -c release --show-bin-path)/F1Lap"

app=build/F1Lap.app
rm -rf "$app"
mkdir -p "$app/Contents/MacOS"
cp "$bin" "$app/Contents/MacOS/F1Lap"
cat > "$app/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key><string>F1Lap</string>
  <key>CFBundleIdentifier</key><string>local.f1lap.app</string>
  <key>CFBundleName</key><string>F1 Lap Analyser</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>15.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST
codesign --force --sign - "$app"
echo "$PWD/$app"
