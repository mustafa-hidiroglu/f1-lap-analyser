#!/usr/bin/env bash
# Build a release F1Lap.app into app/build/. Personal use: unsigned apart from an ad-hoc signature.
# The app embeds its own Python and sidecar, so it runs from anywhere; F1LAP_REPO still overrides.
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
  <key>CFBundleIconFile</key><string>F1Lap</string>
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

# Self-contained sidecar: copy uv's relocatable Python into Resources/python and install the
# locked dependencies plus f1lap itself into it, so the .app runs without this checkout.
res="$app/Contents/Resources"
mkdir -p "$res"
cp Resources/F1Lap.icns "$res/"  # from assets/brand/build-icons.sh
managed="$(uv python find --managed-python '>=3.13')"
base="$("$managed" -c 'import sys; print(sys.base_prefix)')"
cp -R "$base" "$res/python"
rm -rf "$res/python/lib/python3."*/test "$res/python/lib/python3."*/idlelib
rm -f "$res/python/lib/python3."*/EXTERNALLY-MANAGED
py="$res/python/bin/python3"
reqs="$(mktemp)"
(cd .. && uv export --frozen --no-dev --no-emit-project --format requirements.txt -o "$reqs" -q)
uv pip install -q --python "$py" -r "$reqs"
uv pip install -q --python "$py" --no-deps ..
rm -f "$reqs"
"$py" -m compileall -q -j 0 "$res/python/lib" >/dev/null || true  # the app runs with no bytecode writes
"$py" -c 'import f1lap.server'  # fail the build, not the first launch, if the env is broken

codesign --force --sign - "$app"
echo "$PWD/$app"
