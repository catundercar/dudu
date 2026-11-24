#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROBE='import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'

if command -v python3 >/dev/null 2>&1 && python3 -c "$PROBE" >/dev/null 2>&1; then
  exec python3 -B "$REPO_ROOT/install.py" "$@"
fi
if command -v py >/dev/null 2>&1 && py -3 -c "$PROBE" >/dev/null 2>&1; then
  exec py -3 -B "$REPO_ROOT/install.py" "$@"
fi
if command -v python >/dev/null 2>&1 && python -c "$PROBE" >/dev/null 2>&1; then
  exec python -B "$REPO_ROOT/install.py" "$@"
fi

echo "Install failed: Python 3.9+ is required (tried python3, py -3, python)." >&2
exit 1
