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
cp Resources/F1Lap.icns "$stage/.VolumeIcon.icns"
dmg="build/F1Lap-$version-mac-arm64.dmg"
rm -f "$dmg"

# The volume icon only shows if the volume root has the custom-icon Finder flag, which
# -srcfolder doesn't carry over: build read-write, set the flag on the mounted root, compress.
rw="$stage.rw.dmg"
hdiutil create -quiet -volname "F1 Lap Analyser" -srcfolder "$stage" -fs APFS -format UDRW "$rw"
mnt="$(mktemp -d)"
hdiutil attach -quiet -nobrowse -noautoopen -mountpoint "$mnt" "$rw"
xcrun SetFile -a C "$mnt"
hdiutil detach -quiet "$mnt"
hdiutil convert -quiet "$rw" -format UDZO -o "$dmg"
rm -f "$rw"
echo "$PWD/$dmg"
