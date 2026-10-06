#!/usr/bin/env bash
# Run the Swift test suite. Live tests (real sidecar) run when the repo's .venv exists.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/env.sh
F1LAP_REPO="${F1LAP_REPO:-$(cd .. && pwd)}" swift test "${F1LAP_TEST_FLAGS[@]}" "$@"
