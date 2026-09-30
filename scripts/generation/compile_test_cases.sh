#!/bin/sh
set -eu
uv run --python 3.11 --with pyyaml --with jsonschema python scripts/generation/compile_test_cases.py
