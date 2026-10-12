# Embed the analysis engine next to F1Lap.exe (run publish.ps1 first): copies uv's relocatable
# Python into windows\dist\F1Lap\python and installs the locked dependencies plus f1lap into it,
# so the installed app needs neither the repository nor a Python install.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$repo = Split-Path -Parent $root
$dest = Join-Path $root "dist\F1Lap\python"

uv python install 3.13
$managed = (uv python find --managed-python ">=3.13").Trim()
$base = (& $managed -c "import sys; print(sys.base_prefix)").Trim()
if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
Copy-Item -Recurse $base $dest
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $dest "Lib\test"), (Join-Path $dest "Lib\idlelib")
Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $dest "Lib\EXTERNALLY-MANAGED")

$py = Join-Path $dest "python.exe"
$reqs = New-TemporaryFile
Push-Location $repo
try { uv export --frozen --no-dev --no-emit-project --format requirements.txt -o $reqs -q } finally { Pop-Location }
uv pip install -q --python $py -r $reqs
uv pip install -q --python $py --no-deps $repo
Remove-Item $reqs
& $py -m compileall -q -j 0 (Join-Path $dest "Lib") | Out-Null  # the app runs with no bytecode writes
& $py -c "import f1lap.server"  # fail the build, not the first launch, if the env is broken
if ($LASTEXITCODE -ne 0) { throw "embedded Python cannot import f1lap.server" }
Write-Host $dest
