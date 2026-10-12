#!/usr/bin/env bash
# Package app/build/F1Lap.app (from bundle.sh) as a drag-to-Applications disk image:
# app/build/F1Lap-<version>-mac-arm64.dmg. Usage: dmg.sh [version]
set -euo pipefail
cd "$(dirname "$0")/.."
version="${1:-0.1.0}"
app=build/F1Lap.app
[ -d "$app" ] || { echo "run scripts/bundle.sh first" >&2; exit 1; }

stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
cp -R "$app" "$stage/"
ln -s /Applications "$stage/Applications"
dmg="build/F1Lap-$version-mac-arm64.dmg"
rm -f "$dmg"
hdiutil create -quiet -volname "F1 Lap Analyser" -srcfolder "$stage" -fs APFS -format UDZO "$dmg"
echo "$PWD/$dmg"
