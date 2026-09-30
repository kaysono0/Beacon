#!/usr/bin/env python3
"""拒绝 pytest 源目录内重复的模块级测试函数声明。"""

from __future__ import annotations

import argparse
import ast
import sys
import tempfile
from collections import defaultdict
from pathlib import Path


def find_duplicate_test_declarations(source_dir: Path) -> list[tuple[Path, str, list[int]]]:
    duplicates: list[tuple[Path, str, list[int]]] = []
    for path in sorted(source_dir.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeDecodeError, SyntaxError) as error:
            print(f"pytest declaration check: cannot parse {path}: {error}", file=sys.stderr)
            duplicates.append((path, "<parse-error>", []))
            continue

        declarations: dict[str, list[int]] = defaultdict(list)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                declarations[node.name].append(node.lineno)
        duplicates.extend(
            (path, name, lines) for name, lines in declarations.items() if len(lines) > 1
        )
    return duplicates


def check(source_dir: Path) -> bool:
    duplicates = find_duplicate_test_declarations(source_dir)
    if not duplicates:
        print(f"pytest declaration check: PASS {source_dir}")
        return True

    for path, name, lines in duplicates:
        if name != "<parse-error>":
            print(
                f"pytest declaration check: duplicate {name} in {path} at lines {', '.join(map(str, lines))}",
                file=sys.stderr,
            )
    return False


def run_self_test() -> bool:
    with tempfile.TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory)
        (root / "clean.py").write_text(
            "def test_top_level():\n    pass\n\n"
            "class TestNested:\n    def test_method(self):\n        pass\n\n"
            "def helper():\n    def test_nested():\n        pass\n",
            encoding="utf-8",
        )
        if find_duplicate_test_declarations(root):
            print("pytest declaration check self-test: clean fixture failed unexpectedly", file=sys.stderr)
            return False

        (root / "duplicate.py").write_text(
            "def test_duplicate():\n    pass\n\n"
            "async def test_duplicate():\n    pass\n",
            encoding="utf-8",
        )
        duplicates = find_duplicate_test_declarations(root)
        if duplicates != [(root / "duplicate.py", "test_duplicate", [1, 4])]:
            print("pytest declaration check self-test: duplicate fixture was not detected", file=sys.stderr)
            return False
    print("pytest declaration check self-test: PASS")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if not args.source_dir.is_dir():
        print(f"pytest declaration check: missing directory {args.source_dir}", file=sys.stderr)
        return 2
    if args.self_test and not run_self_test():
        return 1
    return 0 if check(args.source_dir) else 1


if __name__ == "__main__":
    raise SystemExit(main())
