"""UT-REPORT-SECRETS：报告文本检查回归测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys
from unittest.mock import patch

from scripts.validation.scan_report_secrets import scan


class ReportSecretsTests(unittest.TestCase):
    """覆盖凭证、脱敏结果和拒绝路径。"""

    def test_vendor_siblings_without_echo(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for vendor in ("AGORA", "VOLCENGINE", "ZEGO"):
                (root / f"{vendor}.json").write_text(json.dumps({f"{vendor}_TOKEN": "private-token-0123456789"}))
            result = scan(root, {})
            self.assertEqual(len(result["findings"]), 3)
            self.assertEqual(result["status"], "failed")
            self.assertNotIn("private-token", json.dumps(result))

    def test_redacted_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "safe.log").write_text('token="[REDACTED]"\nBEACON_AUTH_TOKEN=local-test-token')
            self.assertEqual(scan(root, {"BEACON_AUTH_TOKEN": "local-test-token"})["status"], "passed")

    def test_nested_auth_path_and_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "logs").mkdir()
            (root / "logs" / "server.log").write_text("Bearer abcdefghijklmnop\n/Users/alice/private/file\nopaque-secret")
            rules = {item["rule"] for item in scan(root, {"ZEGO_USER1_TOKEN": "opaque-secret"})["findings"]}
            self.assertEqual(rules, {"authorization", "user-directory", "environment-secret"})

    def test_missing_link_and_unreadable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(scan(root / "missing", {})["status"], "failed")
            (root / "linked").symlink_to(root, target_is_directory=True)
            (root / "broken.log").write_bytes(b"\xff")
            (root / "image.jpg").write_bytes(b"\xff")
            rules = {item["rule"] for item in scan(root, {})["findings"]}
            self.assertEqual(rules, {"symlink", "unreadable-text"})

    def test_coverage_sqlite_ascii_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".coverage.server").write_bytes(b"SQLite format 3\x00\xff/Users/alice/repo/file.py")
            self.assertEqual(scan(root, {})["findings"][0]["rule"], "user-directory")

    def test_cli_failure_and_safe_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "private.log").write_text("Bearer private-token-0123456789")
            completed = subprocess.run(
                [sys.executable, str(Path(__file__).resolve().parents[2] / "scripts/validation/scan_report_secrets.py"), directory],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 1)
            result = json.loads((root / "report-secrets.json").read_text())
            self.assertEqual(result["status"], "failed")
            self.assertNotIn("private-token", completed.stdout + completed.stderr + json.dumps(result))

    def test_directory_traversal_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def failing_walk(path, onerror, followlinks):
                onerror(PermissionError(13, "permission denied", str(root / "private")))
                return iter([])

            with patch("scripts.validation.scan_report_secrets.os.walk", side_effect=failing_walk):
                result = scan(root, {})
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["findings"][0]["rule"], "unreadable-directory")


if __name__ == "__main__":
    unittest.main()
