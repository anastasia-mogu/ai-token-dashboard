#!/usr/bin/env python3
"""公开仓提交前安全检查；只报告文件与行号，不回显命中内容。"""
from __future__ import annotations
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_SIZE = 1024 * 1024
BINARY_SUFFIXES = {".zip", ".sqlite", ".db", ".mp4", ".mov"}
FORBIDDEN_NAMES = {"data.js", ".project-hash-seed", ".project-aliases.json", ".env"}

def candidate_files() -> list[Path]:
    if (ROOT / ".git").exists():
        result = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            check=True, capture_output=True,
        )
        return [ROOT / name.decode() for name in result.stdout.split(b"\0") if name]
    return [path for path in ROOT.rglob("*") if path.is_file() and ".git" not in path.parts]

def risky_patterns() -> list[re.Pattern[str]]:
    parts = [
        "pass" + "word", "sec" + "ret", "api" + r"[_-]?" + "key",
        "s" + "k-", "g" + "hp_", "A" + "KIA",
        bytes.fromhex("424547494e202e2a2050524956415445204b4559").decode(),
        bytes.fromhex("2f55736572732f").decode(),
    ]
    return [re.compile(part, re.IGNORECASE) for part in parts]

def main() -> int:
    failures: list[tuple[str, int | None, str]] = []
    files = candidate_files()
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        if path.name in FORBIDDEN_NAMES or rel.startswith("data/"):
            failures.append((rel, None, "公开仓禁入文件"))
        if path.suffix.lower() in BINARY_SUFFIXES:
            failures.append((rel, None, "禁止的二进制文件"))
        if path.stat().st_size > MAX_SIZE:
            failures.append((rel, None, "文件超过 1 MB"))
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            detector_rule = path.name == "update.sh" and line.lstrip().startswith(("SENSITIVE_PATTERN=", "TOKEN_PATTERN="))
            if not detector_rule and any(pattern.search(line) for pattern in risky_patterns()):
                failures.append((rel, number, "疑似凭据或本机绝对路径"))

    configured = os.environ.get("AI_TOKEN_PUBLIC_EXTRA_PATTERNS_FILE")
    pattern_path = Path(configured).expanduser() if configured else ROOT / ".public-safety-patterns.local"
    if pattern_path.exists():
        extras = [line.strip() for line in pattern_path.read_text().splitlines() if line.strip() and not line.startswith("#")]
        for path in files:
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for number, line in enumerate(lines, 1):
                if any(re.search(pattern, line, re.IGNORECASE) for pattern in extras):
                    failures.append((path.relative_to(ROOT).as_posix(), number, "命中本机私密规则"))

    example = ROOT / "data.example.js"
    markers = ("AI_TOKEN_DATA_IS_EXAMPLE = true", "示例设备-甲")
    if not example.exists() or not all(marker in example.read_text() for marker in markers):
        failures.append(("data.example.js", None, "缺少明确标记的虚构示例数据"))
    if failures:
        print("公开仓安全检查未通过：")
        for rel, line, reason in sorted(set(failures)):
            location = rel + (f":{line}" if line else "")
            print(f"- {location}：{reason}")
        return 1
    print(f"公开仓安全检查通过：已检查 {len(files)} 个文件。")
    print("普通 Token 业务字段不作为凭据自动拦截；推送前仍需人工查看完整差异。")
    return 0

if __name__ == "__main__":
    sys.exit(main())
