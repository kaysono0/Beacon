#!/bin/sh
set -eu
python3 scripts/support/generate_report.py "${1:-passed}" "${2:-P1-REPORT}" "${3:-generate-report}"
