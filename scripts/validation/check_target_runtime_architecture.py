"""Read-only architecture guard for the immediate remote-control runtime."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_PATHS = (ROOT / "server/app", ROOT / "python_sdk/beacon_test")
EXPECTED_INVARIANTS = tuple(f"INV-{number:03d}" for number in range(1, 11))
FORBIDDEN_AUTHORING_PATTERNS = (
    re.compile(r"\bAsyncBeaconSession\b"),
    re.compile(r"\brecord_?replay\b", re.IGNORECASE),
    re.compile(r"\bbatch_call\b", re.IGNORECASE),
)


def validate_invariant_catalog(root: Path) -> list[str]:
    """Ensure later stages cannot silently lose a frozen invariant."""

    path = root / "scripts/contracts/python_immediate_remote_control_invariants.json"
    if not path.is_file():
        return ["INVARIANT-CATALOG missing invariant catalog"]
    loaded = json.loads(path.read_text(encoding="utf-8"))
    identifiers = tuple(item.get("id") for item in loaded.get("invariants", []))
    if loaded.get("schema_version") != 1 or identifiers != EXPECTED_INVARIANTS:
        return ["INVARIANT-CATALOG invariant IDs do not match INV-001 through INV-010"]
    return []


def violations(root: Path = ROOT) -> list[str]:
    """Return invariant failures; never edit files or advance checkpoint state."""

    failures = validate_invariant_catalog(root)
    paths = (root / "server/app", root / "python_sdk/beacon_test")
    for path in paths:
        for source in path.rglob("*.py") if path.exists() else ():
            text = source.read_text(encoding="utf-8")
            generated_facade_is_async = (
                "python_sdk/beacon_test/generated" in source.as_posix()
                and re.search(r"^\s*async\s+def\s+", text, re.MULTILINE) is not None
            )
            if generated_facade_is_async or any(pattern.search(text) for pattern in FORBIDDEN_AUTHORING_PATTERNS):
                failures.append(f"INV-001 {source.relative_to(root)} contains forbidden target authoring surface")
    target_sdk = root / "python_sdk/beacon_test/target_session.py"
    if target_sdk.is_file() and "/api/v1/sdk/call" in target_sdk.read_text(encoding="utf-8"):
        failures.append("INV-002 target BeaconSession calls the legacy SDK endpoint")
    legacy_modules = (
        "server/app/test_run_entry.py",
        "server/app/python_native_context.py",
        "server/app/protocol_operations.py",
        "server/app/thin_protocol_executor.py",
        "server/app/python_native_assertions.py",
        "python_sdk/beacon_test/authoring_core.py",
        "python_sdk/beacon_test/client.py",
        "python_sdk/beacon_test/client.pyi",
        "python_sdk/beacon_test/models.py",
        "python_sdk/beacon_test/models.pyi",
        "python_sdk/beacon_test/registry_facade.py",
    )
    for relative in legacy_modules:
        if (root / relative).exists():
            failures.append(f"INV-010 {relative} remains after cutover")
    if any((root / "python_sdk/beacon_test/target_generated").glob("*.py")):
        failures.append("INV-010 target_generated remains after cutover")
    entry = root / "server/app/main.py"
    if entry.is_file():
        source = entry.read_text(encoding="utf-8")
        if any(endpoint in source for endpoint in ("/api/v1/sdk/call", "/api/v1/sdk/callback-events", "/api/v1/devices/{node_id}/commands", "/api/v1/devices/{node_id}/callbacks")):
            failures.append("INV-010 independent SDK endpoint remains after retirement")
        if "/api/v1/target-test-runs" in source or "BEACON_ENABLE_TARGET_RUNTIME" in source:
            failures.append("INV-004 target-only entry remains after cutover")
        if 'return await runner_supervisor.create_run(payload.case_ids, selector)' not in source:
            failures.append("INV-003 production run entry does not use RunnerSupervisor")
        if '/api/v1/runner/runs/{run_id}/cases/{case_id}/callbacks' not in source:
            failures.append("INV-010 Runner callback registration endpoint is missing")
    for path in paths:
        for source in path.rglob("*.py") if path.exists() else ():
            if any(term in source.read_text(encoding="utf-8") for term in ("ProtocolOperationRecorder", "ThinProtocolExecutor", "BeaconNativeContext", "BeaconTestClient", "BeaconTestSession", "RegistryBackedSDK", "TestOrchestrator", "AssertionEngine")):
                failures.append(f"INV-010 {source.relative_to(root)} references deleted runtime")
    retired_modules = {"beacon_test.client", "beacon_test.registry_facade", "beacon_test.models"}
    retired_exports = {"BeaconTestClient", "BeaconTestSession", "RegistryBackedSDK"}
    for directory in (root / "scripts", root / "test_cases/python", root / "tests", root / "python_sdk/tests"):
        for source in directory.rglob("*.py") if directory.exists() else ():
            for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and (
                    node.module in retired_modules or node.module == "beacon_test" and any(alias.name in retired_exports for alias in node.names)
                ) or isinstance(node, ast.Import) and any(alias.name in retired_modules for alias in node.names):
                    failures.append(f"INV-010 {source.relative_to(root)} imports retired SDK client")
    callback_controller = root / "agent_core/src/callback_controller.cc"
    if callback_controller.is_file() and "OnCallbackRequest" not in callback_controller.read_text(encoding="utf-8"):
        failures.append("INV-010 Native callback registration is missing")
    return failures


def main() -> int:
    failures = violations()
    if failures:
        print("\n".join(failures))
        return 1
    print("target runtime architecture guard: PASS (INV-001, INV-002, INV-003, INV-004, INV-010)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
