"""Update the target-runtime checkpoint through the fail-closed control module."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path


import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.support.target_runtime_control import (
    ControlArtifactError,
    advance_checkpoint,
    amend_completed_manifest,
    load_checkpoint,
    manifest_reference,
    select_next_package,
    write_checkpoint,
)


def parse_args() -> argparse.Namespace:
    """Parse the intentionally small checkpoint update surface."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--status")
    action.add_argument("--next-package")
    action.add_argument("--amend-completed-manifest", action="store_true")
    parser.add_argument("--baseline-commit")
    parser.add_argument("--manifest", type=Path)
    return parser.parse_args()


def main() -> int:
    """Apply a validated transition and make no other repository modification."""

    args = parse_args()
    try:
        state = load_checkpoint(args.state)
        updated_at = datetime.now(UTC).isoformat()
        if args.amend_completed_manifest:
            if args.baseline_commit or not args.manifest:
                raise ControlArtifactError("manifest amendment requires --manifest and rejects --baseline-commit")
            updated = amend_completed_manifest(
                state,
                manifest_path=args.manifest,
                manifest_path_reference=manifest_reference(args.state, args.manifest),
                updated_at=updated_at,
            )
        elif args.next_package:
            if args.baseline_commit or args.manifest:
                raise ControlArtifactError("next package selection does not accept baseline or manifest")
            updated = select_next_package(
                state,
                next_package=args.next_package,
                updated_at=updated_at,
            )
        else:
            updated = advance_checkpoint(
                state,
                status=args.status,
                baseline_commit=args.baseline_commit,
                manifest_path=args.manifest,
                manifest_path_reference=(manifest_reference(args.state, args.manifest) if args.manifest else None),
                updated_at=updated_at,
            )
        write_checkpoint(args.state, updated)
    except ControlArtifactError as error:
        raise SystemExit(f"target runtime state rejected: {error}") from error
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
