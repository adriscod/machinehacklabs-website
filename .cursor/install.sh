#!/usr/bin/env bash
# Idempotent Cloud Agent bootstrap for the mhl-quote CNC rough-quote estimator.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT/mhl-quote"

# Create the project virtualenv. Some base images ship a Python without
# `ensurepip`, so fall back to `virtualenv` (fetched from PyPI) when the stdlib
# `venv` cannot bootstrap pip on its own.
if [ ! -x .venv/bin/python ]; then
  rm -rf .venv
  if python3 -c "import ensurepip" 2>/dev/null; then
    python3 -m venv .venv
  else
    echo "ensurepip unavailable; creating venv via virtualenv from PyPI"
    python3 -m pip install --user --break-system-packages -q virtualenv
    python3 -m virtualenv .venv
  fi
fi

# shellcheck source=/dev/null
. .venv/bin/activate

python -m pip install --upgrade -q pip
python -m pip install -q -r requirements.txt
python -m pip install -q -e ".[dev]"

# STEP import via CadQuery is the preferred CAD path but is a heavy optional
# dependency. Keep it non-fatal so STL quoting still works if it cannot install.
if ! python -m pip install -q -r requirements-step.txt; then
  echo "warning: STEP support (cadquery) failed to install; STL quoting still works"
fi

echo "mhl-quote environment ready:"
python -m mhl_quote --show-config
