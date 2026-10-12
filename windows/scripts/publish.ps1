# Build F1Lap.exe for Windows into windows\dist\F1Lap\: self-contained (no .NET install needed),
# x64 by default (-Arch arm64 for Windows on Arm). Personal use: unsigned. The analysis engine runs
# from this checkout's .venv (found next to the build, or set F1LAP_REPO).
param([ValidateSet("x64", "arm64")][string]$Arch = "x64")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$out = Join-Path $root "dist\F1Lap"
dotnet publish (Join-Path $root "F1Lap.App\F1Lap.App.csproj") -c Release -r "win-$Arch" `
    --self-contained true -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true `
    -p:DebugType=none -o $out
Write-Host (Join-Path $out "F1Lap.exe")
