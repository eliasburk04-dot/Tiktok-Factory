#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

"$PROJECT_ROOT/.venv/bin/tictoc-factory" cycle --project-root "$PROJECT_ROOT"
"$PROJECT_ROOT/.venv/bin/tictoc-factory" publish-due --project-root "$PROJECT_ROOT"
