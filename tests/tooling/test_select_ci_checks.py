"""UT-CI-SELECTION：确保文档可跳过而执行输入和未知路径不漏检。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


import unittest
from unittest.mock import patch
import subprocess
import io
from contextlib import redirect_stdout
from scripts.validation.select_ci_checks import main, needs_macos


class SelectionTests(unittest.TestCase):
    """验证保守的 macOS 专项选择边界。"""

    def test_documentation_only(self):
        self.assertFalse(needs_macos(["README.md", "docs/development.md", ".scratch/feature/spec.json"]))
        self.assertFalse(needs_macos([]))

    def test_executable_inputs_and_unknown_paths(self):
        for path in ("agent_core/src/a.cc", "agents/mac/src/a.mm", "apps/mac_test_console/Package.swift",
                     "server/app/a.py", "python_sdk/a.py", "test_cases/a.py", "sdk_registry/a.json",
                     "test_cases/protocol_examples/a.json", "scripts/a.py", "Makefile", ".github/workflows/macos.yml",
                     "new-module/config.toml"):
            with self.subTest(path=path):
                self.assertTrue(needs_macos(["README.md", path]))

    def test_git_failure_is_not_skip(self):
        with patch("sys.argv", ["select", "base", "head"]), patch(
            "scripts.validation.select_ci_checks.subprocess.run", side_effect=subprocess.CalledProcessError(1, "git")
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                main()

    def test_rename_paths_and_manual_selection(self):
        result = subprocess.CompletedProcess([], 0, stdout=b"docs/old.md\0agents/mac/new.mm\0")
        output = io.StringIO()
        with patch("sys.argv", ["select", "base", "head"]), patch(
            "scripts.validation.select_ci_checks.subprocess.run", return_value=result
        ) as run, redirect_stdout(output):
            self.assertEqual(main(), 0)
        self.assertIn("--no-renames", run.call_args.args[0])
        self.assertEqual(output.getvalue(), "macos=true\n")
        with patch("sys.argv", ["select", "", "head"]), patch(
            "scripts.validation.select_ci_checks.subprocess.run"
        ) as run, redirect_stdout(io.StringIO()):
            self.assertEqual(main(), 0)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
