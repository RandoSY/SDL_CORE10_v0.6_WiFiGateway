#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 launch.py --demo --open-browser "$@"
