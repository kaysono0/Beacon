"""Fail-closed control artifacts for the Python immediate remote-control migration."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml


WORK_PACKAGES = tuple(f"IR-{number:02d}" for number in range(13))
STATUSES = frozenset({"not_started", "in_progress", "verification_failed", "blocked", "completed"})
DEPENDENCIES = {
    "IR-00": (),
    "IR-01": ("IR-00",),
    "IR-02": ("IR-01",),
    "IR-03": ("IR-02",),
    "IR-04": ("IR-00",),
    "IR-05": ("IR-04",),
    "IR-06": ("IR-03", "IR-05"),
    "IR-07": ("IR-04",),
    "IR-08": ("IR-02", "IR-06", "IR-07"),
    "IR-09": ("IR-08",),
    "IR-10": ("IR-08", "IR-09"),
    "IR-11": ("IR-10",),
    "IR-12": ("IR-11",),
}
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
UNSAFE_MANIFEST_PATTERNS = (
    re.compile(r"(?i)authorization\s*[:=]"),
    re.compile(r"(?i)bearer\s+[a-z0-9._-]+"),
    re.compile(r"/Users/[^/\s]+/"),
)


class ControlArtifactError(ValueError):
    """Raised when a checkpoint or manifest would overstate verified progress."""


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of an artifact without interpreting its contents."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_reference(checkpoint_path: Path, manifest_path: Path) -> str:
    """Return a stable repository-relative manifest path or reject external evidence."""

    repository_root = Path(__file__).resolve().parents[2]
    try:
        checkpoint_path.resolve().relative_to(repository_root)
        return str(manifest_path.resolve().relative_to(repository_root))
    except ValueError as error:
        raise ControlArtifactError("checkpoint and manifest must be stored inside the repository") from error


def load_checkpoint(path: Path) -> dict[str, Any]:
    """Load and validate the small continuation pointer, never a task plan."""

    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ControlArtifactError("checkpoint must be a YAML object")
    required = {
        "schema_version",
        "plan_revision",
        "active_package",
        "status",
        "baseline_commit",
        "latest_manifest",
        "completed_packages",
        "production_runtime",
        "target_endpoint_enabled",
        "production_cutover_completed",
        "blocker",
        "updated_at",
    }
    if set(loaded) != required:
        raise ControlArtifactError("checkpoint fields do not match the frozen contract")
    if loaded["schema_version"] != 1 or loaded["plan_revision"] != 1:
        raise ControlArtifactError("unsupported checkpoint schema or plan revision")
    if loaded["active_package"] not in WORK_PACKAGES or loaded["status"] not in STATUSES:
        raise ControlArtifactError("checkpoint package or status is invalid")
    if not isinstance(loaded["completed_packages"], list):
        raise ControlArtifactError("completed_packages must be a list")
    if any(package not in WORK_PACKAGES for package in loaded["completed_packages"]):
        raise ControlArtifactError("completed_packages contains an unknown package")
    if not isinstance(loaded["latest_manifest"], dict) or set(loaded["latest_manifest"]) != {"path", "sha256"}:
        raise ControlArtifactError("latest_manifest shape is invalid")
    if not isinstance(loaded["blocker"], dict) or set(loaded["blocker"]) != {"kind", "description"}:
        raise ControlArtifactError("blocker shape is invalid")
    return loaded


def validate_manifest(manifest: dict[str, Any], expected_package: str | None = None) -> None:
    """Reject manifests that hide a failed criterion behind a passed top-level status."""

    required = {
        "schema_version", "work_package", "status", "baseline_commit", "verified_commit", "diff_digest",
        "production_entry_changed", "changed_files", "invariants", "verification", "exit_criteria", "skipped",
        "not_run", "blockers", "dirty_files_preserved", "next_allowed_packages",
    }
    if set(manifest) != required:
        raise ControlArtifactError("manifest fields do not match the frozen contract")
    if manifest["schema_version"] != 1 or manifest["work_package"] not in WORK_PACKAGES:
        raise ControlArtifactError("manifest schema or work package is invalid")
    if expected_package is not None and manifest["work_package"] != expected_package:
        raise ControlArtifactError("manifest work package does not match checkpoint")
    if manifest["status"] not in {"passed", "failed", "skipped", "not_run"}:
        raise ControlArtifactError("manifest status is invalid")
    if not all(isinstance(manifest[name], list) for name in ("invariants", "verification", "exit_criteria", "skipped", "not_run", "blockers", "dirty_files_preserved", "next_allowed_packages")):
        raise ControlArtifactError("manifest collection field is invalid")
    if not SHA256_PATTERN.fullmatch(manifest["diff_digest"]):
        raise ControlArtifactError("manifest diff_digest must be SHA-256")
    verification_failed = any(
        not isinstance(item, dict)
        or item.get("result") != "passed"
        or item.get("exit_code") != 0
        for item in manifest["verification"]
    )
    unmet_criterion = any(item.get("result") != "passed" for item in manifest["exit_criteria"])
    if manifest["status"] == "passed" and (
        not manifest["verification"]
        or not manifest["exit_criteria"]
        or verification_failed
        or unmet_criterion
        or manifest["blockers"]
    ):
        raise ControlArtifactError("passed manifest contains failed evidence or blockers")
    for value in _string_values(manifest):
        if any(pattern.search(value) for pattern in UNSAFE_MANIFEST_PATTERNS):
            raise ControlArtifactError("manifest contains a sensitive value or user absolute path")


def _string_values(value: Any) -> list[str]:
    """Flatten JSON string values for the manifest-specific safety gate."""

    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for child in value for item in _string_values(child)]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _string_values(child)]
    return []


def unlocked_packages(completed_packages: list[str]) -> list[str]:
    """Return only packages whose complete dependency set has verified completion."""

    completed = set(completed_packages)
    if any(package not in WORK_PACKAGES for package in completed):
        raise ControlArtifactError("completed package set contains an unknown package")
    return [
        package
        for package in WORK_PACKAGES
        if package not in completed and set(DEPENDENCIES[package]).issubset(completed)
    ]


def advance_checkpoint(
    state: dict[str, Any],
    *,
    status: str,
    baseline_commit: str | None = None,
    manifest_path: Path | None = None,
    manifest_path_reference: str | None = None,
    updated_at: str | None = None,
) -> dict[str, Any]:
    """Apply only allowed state transitions; completion requires a verified manifest."""

    if status not in STATUSES or status == "not_started":
        raise ControlArtifactError("requested checkpoint status is invalid")
    current = state["status"]
    allowed = {
        "not_started": {"in_progress", "blocked"},
        "in_progress": {"verification_failed", "blocked", "completed"},
        "verification_failed": {"in_progress", "blocked"},
        "blocked": {"in_progress", "verification_failed"},
        "completed": set(),
    }
    if status not in allowed[current]:
        raise ControlArtifactError(f"illegal checkpoint transition: {current} -> {status}")
    updated = dict(state)
    updated["status"] = status
    if status == "in_progress":
        if not baseline_commit:
            raise ControlArtifactError("starting a work package requires baseline_commit")
        if state["baseline_commit"] not in (None, baseline_commit):
            raise ControlArtifactError("baseline commit conflicts with the checkpoint")
        updated["baseline_commit"] = baseline_commit
    if status == "completed":
        if manifest_path is None or not manifest_path.is_file():
            raise ControlArtifactError("completion requires an existing manifest")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        validate_manifest(manifest, updated["active_package"])
        if manifest["status"] != "passed" or manifest["baseline_commit"] != updated["baseline_commit"]:
            raise ControlArtifactError("manifest cannot prove this package completed")
        completed_packages = [*updated["completed_packages"], updated["active_package"]]
        if manifest["next_allowed_packages"] != unlocked_packages(completed_packages):
            raise ControlArtifactError("manifest next packages do not match the dependency graph")
        if not manifest_path_reference:
            raise ControlArtifactError("completion requires a repository-relative manifest reference")
        updated["latest_manifest"] = {"path": manifest_path_reference, "sha256": sha256_file(manifest_path)}
        updated["completed_packages"] = completed_packages
        if updated["active_package"] == "IR-10":
            updated["production_runtime"] = "immediate_remote_control"
            updated["target_endpoint_enabled"] = False
            updated["production_cutover_completed"] = True
    updated["updated_at"] = updated_at
    return updated


def amend_completed_manifest(
    state: dict[str, Any], *, manifest_path: Path, manifest_path_reference: str, updated_at: str
) -> dict[str, Any]:
    """用修正后已验证的证据替换已完成工作包的 manifest 引用。"""

    if state["status"] != "completed" or state["active_package"] not in state["completed_packages"]:
        raise ControlArtifactError("manifest amendment requires the completed active package")
    if not manifest_path.is_file():
        raise ControlArtifactError("manifest amendment requires an existing manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_manifest(manifest, state["active_package"])
    if manifest["status"] != "passed" or manifest["baseline_commit"] != state["baseline_commit"]:
        raise ControlArtifactError("amended manifest cannot prove this package completed")
    if manifest["next_allowed_packages"] != unlocked_packages(state["completed_packages"]):
        raise ControlArtifactError("amended manifest next packages do not match the dependency graph")
    if not manifest_path_reference:
        raise ControlArtifactError("manifest amendment requires a repository-relative reference")
    return {
        **state,
        "latest_manifest": {"path": manifest_path_reference, "sha256": sha256_file(manifest_path)},
        "updated_at": updated_at,
    }


def select_next_package(
    state: dict[str, Any],
    *,
    next_package: str,
    updated_at: str | None = None,
) -> dict[str, Any]:
    """Point a completed checkpoint at one dependency-unlocked successor."""

    if state["status"] != "completed":
        raise ControlArtifactError("next package selection requires a completed checkpoint")
    if next_package not in unlocked_packages(state["completed_packages"]):
        raise ControlArtifactError("next package is not unlocked by the dependency graph")
    updated = dict(state)
    updated["active_package"] = next_package
    updated["status"] = "not_started"
    updated["baseline_commit"] = None
    updated["blocker"] = {"kind": None, "description": None}
    updated["updated_at"] = updated_at
    return updated


def write_checkpoint(path: Path, state: dict[str, Any]) -> None:
    """Atomically replace the YAML checkpoint after its caller has validated it."""

    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(yaml.safe_dump(state, allow_unicode=True, sort_keys=False), encoding="utf-8")
    temporary.replace(path)
