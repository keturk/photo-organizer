#!/bin/bash
# Run photo audit inside the virtual environment
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# shellcheck disable=SC1091
source .venv/bin/activate
trap deactivate EXIT

python3 photo_audit.py "$@"
