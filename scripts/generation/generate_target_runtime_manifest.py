"""Validate and write an execution manifest without running any verification command."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError


import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.support.target_runtime_control import ControlArtifactError, validate_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--schema",
        type=Path,
        default=Path(__file__).resolve().parents[2]
        / "scripts/contracts/python_immediate_remote_control_execution_manifest.schema.json",
    )
    args = parser.parse_args()
    try:
        manifest = json.loads(args.input.read_text(encoding="utf-8"))
        schema = json.loads(args.schema.read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(manifest)
        validate_manifest(manifest)
    except (ControlArtifactError, json.JSONDecodeError, ValidationError) as error:
        raise SystemExit(f"target runtime manifest rejected: {error}") from error
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
