#!/usr/bin/env bash
# Build the app icons from the 1024 px master (f1lap-icon-1024.png, rendered from f1lap-icon.svg):
#   app/Resources/F1Lap.icns          macOS app + disk image icon (sips + iconutil)
#   windows/F1Lap.App/F1Lap.ico       Windows exe, window and installer icon (ImageMagick)
# The outputs are committed, so CI needs neither tool. macOS only (sips, iconutil); needs `magick`.
set -euo pipefail
cd "$(dirname "$0")"
master=f1lap-icon-1024.png
root=../..

set_dir="$(mktemp -d)/F1Lap.iconset"
trap 'rm -rf "$(dirname "$set_dir")"' EXIT
mkdir -p "$set_dir"
for s in 16 32 128 256 512; do
  sips -z "$s" "$s" "$master" --out "$set_dir/icon_${s}x${s}.png" >/dev/null
  sips -z $((s * 2)) $((s * 2)) "$master" --out "$set_dir/icon_${s}x${s}@2x.png" >/dev/null
done
mkdir -p "$root/app/Resources"
iconutil -c icns "$set_dir" -o "$root/app/Resources/F1Lap.icns"

magick "$master" -define icon:auto-resize=256,128,64,48,32,24,16 "$root/windows/F1Lap.App/F1Lap.ico"
echo "wrote app/Resources/F1Lap.icns and windows/F1Lap.App/F1Lap.ico"
