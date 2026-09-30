"""根据 Git 改动选择 macOS 专项；未知路径保守执行，差异读取失败不静默跳过。

用法：python3 scripts/validation/select_ci_checks.py BASE HEAD；无 BASE 或手动运行时选择全量。
"""

import subprocess
import sys


def needs_macos(paths: list[str]) -> bool:
    """纯说明文档不触发 macOS，测试输入与未知路径均保守执行。"""
    return any(not (path.endswith(".md") or path.startswith(".scratch/")) or
               path.startswith("test_cases/protocol_examples/") for path in paths)


def main() -> int:
    """输出 GitHub job output；Git 失败时直接失败而非选择空任务。"""
    base, head = sys.argv[1:3]
    if not base or set(base) == {"0"}:
        selected = True
    else:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--no-renames", "-z", base, head],
            capture_output=True, check=True,
        )
        paths = result.stdout.decode("utf-8").rstrip("\0").split("\0") if result.stdout else []
        selected = needs_macos(paths)
    print(f"macos={str(selected).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
