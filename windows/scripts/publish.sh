#!/usr/bin/env bash
# Cross-build F1Lap.exe for Windows from macOS or Linux (same output as publish.ps1):
# windows/dist/F1Lap/F1Lap.exe, self-contained, x64 by default (pass arm64 for Windows on Arm).
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
arch="${1:-x64}"
dotnet publish "$root/F1Lap.App/F1Lap.App.csproj" -c Release -r "win-$arch" \
  --self-contained true -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true \
  -p:DebugType=none -o "$root/dist/F1Lap"
echo "$root/dist/F1Lap/F1Lap.exe"
