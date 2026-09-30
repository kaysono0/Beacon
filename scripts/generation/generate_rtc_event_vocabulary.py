#!/usr/bin/env python3
"""Generate Mac RTC callback target vocabularies from adapter source."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.generation.sdk_registry_compiler import REPO_ROOT, compile_registry_source, load_yaml


OUTPUT_DIR = REPO_ROOT / "agents" / "mac" / "src" / "generated"
RTC_ADAPTERS = {
    "agora": ("agora_rtc", "agora"),
    "volcengine_rtc": ("volcengine_rtc", "volcengine"),
    "zego": ("zego_express", "zego"),
}


def _routes(adapter: str) -> tuple[list[tuple[str, str, str]], tuple[str, str] | None]:
    source_dir = REPO_ROOT / "sdk_adapters" / adapter
    artifact = compile_registry_source(source_dir)
    by_function: dict[str, tuple[str, str]] = {}
    for item in artifact["interfaces"]:
        if item["kind"] != "callback":
            continue
        target = item["target"]
        route = (target.get("interface", ""), target["class_name"])
        existing = by_function.setdefault(target["function"], route)
        if existing != route:
            raise ValueError(f"{source_dir}: callback {target['function']} has conflicting event targets")

    routing = load_yaml(source_dir / "mappings.yaml", "mappings").get("event_routing", {})
    default = routing.get("default_target")
    default_route = None if default is None else (default.get("interface", ""), default["class_name"])
    return sorted((function, *route) for function, route in by_function.items()), default_route


def _header(adapter: str, sdk: str, output_name: str) -> str:
    routes, default = _routes(adapter)
    namespace = output_name
    lines = [
        "// Generated from sdk_adapters; do not edit by hand.",
        "#pragma once",
        "",
        "#include <array>",
        "#include <optional>",
        "#include <string_view>",
        "",
        '#include "rtc/rtc_vocabulary_common.h"',
        "",
        f"namespace beacon::mac::rtc_commands::{namespace}::generated {{",
        "",
        f"inline constexpr std::array<EventTargetRoute, {len(routes)}> kEventTargetRoutes = {{{{",
    ]
    lines.extend(
        f'    {{"{function}", {{"{interface_name}", "{class_name}"}}}},'
        for function, interface_name, class_name in routes
    )
    lines.extend(["}};", "", "inline std::optional<EventTargetSpec> ResolveEventTarget(std::string_view function_name) {"])
    lines.extend(
        f'  if (function_name == "{function}") return EventTargetSpec{{"{interface_name}", "{class_name}"}};'
        for function, interface_name, class_name in routes
    )
    if default is not None:
        lines.append(f'  return EventTargetSpec{{"{default[0]}", "{default[1]}"}};')
    else:
        lines.append("  return std::nullopt;")
    lines.extend(["}", "", f"}}  // namespace beacon::mac::rtc_commands::{namespace}::generated", ""])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    stale: list[Path] = []
    for adapter, (sdk, output_name) in RTC_ADAPTERS.items():
        path = OUTPUT_DIR / f"rtc_event_targets_{output_name}.h"
        content = _header(adapter, sdk, output_name)
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            stale.append(path)
            if not args.check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
    if stale:
        print("generated RTC event vocabularies are out of date:", file=sys.stderr)
        for path in stale:
            print(f"  {path.relative_to(REPO_ROOT)}", file=sys.stderr)
        return 1 if args.check else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
