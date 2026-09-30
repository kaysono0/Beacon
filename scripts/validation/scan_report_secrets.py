"""上传前扫描报告文本；仅输出位置，不回显凭证。

用法：python3 scripts/validation/scan_report_secrets.py [reports/latest]。
保守规则不替代源头脱敏；媒体与二进制内容须另行审查。
"""

import json
import os
from pathlib import Path
import re
import sys
import stat

PATTERNS = {
    "authorization": re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    "credential": re.compile(
        r'''(?i)["']?(?:token|app_cert|app_certificate|app_key|app_sign|'''
        r'''AGORA_APP_CERT|VOLCENGINE_APP_KEY|ZEGO_APP_SIGN|'''
        r'''(?:AGORA|VOLCENGINE|ZEGO)_[A-Z0-9_]*TOKEN|BEACON_AUTH_TOKEN)'''
        r'''["']?\s*[:=]\s*["']?([A-Za-z0-9._~+/=-]{16,})'''
    ),
    "user-directory": re.compile(r"/(?:Users|home)/[^/\s\"<>]+/"),
}
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".mp4", ".wav", ".zip", ".profraw", ".profdata"}


def report_paths(root: Path, findings: list[dict]):
    """显式记录目录遍历失败，避免漏扫后错误允许上传。"""
    def onerror(error: OSError) -> None:
        findings.append({"path": Path(error.filename).relative_to(root).as_posix(),
                         "line": 0, "rule": "unreadable-directory"})

    for directory, folders, files in os.walk(root, onerror=onerror, followlinks=False):
        for name in sorted(folders + files):
            yield Path(directory) / name


def scan(root: Path, environment: dict[str, str]) -> dict:
    """返回无敏感正文的结果；读取失败及符号链接阻止上传。"""
    findings = []
    scanned = 0
    secrets = [value for key, value in environment.items() if value and
               re.search(r"(?:TOKEN|CERT|APP_KEY|APP_SIGN)$", key) and
               value not in {"local-test-token", "test-token"}]
    if not root.is_dir() or root.is_symlink():
        return {"status": "failed", "scanned_files": 0,
                "findings": [{"path": ".", "line": 0, "rule": "missing-or-linked-root"}]}
    for path in report_paths(root, findings):
        relative = path.relative_to(root).as_posix()
        try:
            mode = path.lstat().st_mode
        except OSError:
            findings.append({"path": relative, "line": 0, "rule": "unreadable-entry"})
            continue
        if stat.S_ISLNK(mode):
            findings.append({"path": relative, "line": 0, "rule": "symlink"})
            continue
        if stat.S_ISDIR(mode) or relative == "report-secrets.json":
            continue
        if not stat.S_ISREG(mode):
            findings.append({"path": relative, "line": 0, "rule": "non-regular-file"})
            continue
        if path.suffix.lower() in BINARY_SUFFIXES:
            continue
        try:
            data = path.read_bytes()
            content = data.decode("utf-8", errors="replace" if data.startswith(b"SQLite format 3\x00") else "strict")
        except (OSError, UnicodeError):
            findings.append({"path": relative, "line": 0, "rule": "unreadable-text"})
            continue
        scanned += 1
        for number, line in enumerate(content.splitlines(), 1):
            rules = [name for name, pattern in PATTERNS.items() if pattern.search(line) and
                     (name != "credential" or pattern.search(line).group(1) not in
                      {"local-test-token", "test-token"})]
            if any(secret in line for secret in secrets):
                rules.append("environment-secret")
            findings.extend({"path": relative, "line": number, "rule": rule} for rule in rules)
    return {"status": "failed" if findings else "passed", "scanned_files": scanned,
            "findings": findings}


def main() -> int:
    """写出结果，以非零退出码拒绝不安全上传。"""
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "reports/latest")
    result = scan(root, dict(os.environ))
    if root.is_dir() and not root.is_symlink():
        output = root / "report-secrets.json"
        if output.is_symlink():
            print("report-secrets: failed (linked output)")
            return 1
        output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"report-secrets: {result['status']} ({len(result['findings'])} findings)")
    return int(result["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
