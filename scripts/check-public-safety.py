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

def forbidden_path(rel: str, path: Path) -> bool:
    return path.name in FORBIDDEN_NAMES or path.name.startswith(".env.") or rel.startswith("data/")

def candidate_files() -> list[Path]:
    if (ROOT / ".git").exists():
        result = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            check=True, capture_output=True,
        )
        paths = [ROOT / name.decode() for name in result.stdout.split(b"\0") if name]
        return [path for path in paths if path.exists() or path.is_symlink()]
    return [path for path in ROOT.rglob("*") if path.is_file() and ".git" not in path.parts]

def risky_patterns() -> list[re.Pattern[str]]:
    parts = [
        "pass" + "word", "sec" + "ret", "api" + r"[_-]?" + "key",
        "s" + "k-", "g" + "hp_", "A" + "KIA",
        bytes.fromhex("424547494e202e2a2050524956415445204b4559").decode(),
        bytes.fromhex("2f55736572732f").decode(),
    ]
    return [re.compile(part, re.IGNORECASE) for part in parts]

def scan_text(rel: str, text: str, failures: list[tuple[str, int | None, str]], prefix: str = "") -> None:
    path = Path(rel)
    for number, line in enumerate(text.splitlines(), 1):
        detector_rule = path.name == "update.sh" and line.lstrip().startswith(("SENSITIVE_PATTERN=", "TOKEN_PATTERN="))
        if not detector_rule and any(pattern.search(line) for pattern in risky_patterns()):
            failures.append((prefix + rel, number, "疑似凭据或本机绝对路径"))

def scan_history(failures: list[tuple[str, int | None, str]]) -> None:
    if not (ROOT / ".git").exists():
        return
    seen: set[tuple[str, str]] = set()
    commits = subprocess.run(
        ["git", "-C", str(ROOT), "rev-list", "--all"],
        check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    for commit in commits:
        tree = subprocess.run(
            ["git", "-C", str(ROOT), "ls-tree", "-rl", "-z", commit],
            check=True, capture_output=True,
        ).stdout
        for entry in tree.split(b"\0"):
            if not entry:
                continue
            metadata, raw_path = entry.split(b"\t", 1)
            _mode, kind, object_id, raw_size = metadata.decode("ascii").split()
            if kind != "blob":
                continue
            try:
                rel = raw_path.decode("utf-8")
            except UnicodeDecodeError:
                failures.append(("历史:<非 UTF-8 路径>", None, "公开仓历史含非 UTF-8 路径"))
                continue
            if (object_id, rel) in seen:
                continue
            seen.add((object_id, rel))
            path = Path(rel)
            location = f"历史:{rel}"
            if forbidden_path(rel, path):
                failures.append((location, None, "公开仓历史含禁入文件"))
            if path.suffix.lower() in BINARY_SUFFIXES:
                failures.append((location, None, "公开仓历史含禁止的二进制文件"))
            if int(raw_size) > MAX_SIZE:
                failures.append((location, None, "公开仓历史含超过 1 MB 的文件"))
            content = subprocess.run(
                ["git", "-C", str(ROOT), "cat-file", "blob", object_id],
                check=True, capture_output=True,
            ).stdout
            if b"\0" in content:
                failures.append((location, None, "公开仓历史含未识别二进制内容"))
                continue
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                failures.append((location, None, "公开仓历史含非 UTF-8 内容"))
                continue
            scan_text(rel, text, failures, prefix="历史:")

def main() -> int:
    failures: list[tuple[str, int | None, str]] = []
    files = candidate_files()
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        if path.is_symlink():
            failures.append((rel, None, "公开仓不允许符号链接"))
            continue
        if forbidden_path(rel, path):
            failures.append((rel, None, "公开仓禁入文件"))
        if path.suffix.lower() in BINARY_SUFFIXES:
            failures.append((rel, None, "禁止的二进制文件"))
        if path.stat().st_size > MAX_SIZE:
            failures.append((rel, None, "文件超过 1 MB"))
        content = path.read_bytes()
        if b"\0" in content:
            failures.append((rel, None, "未识别的二进制内容"))
            continue
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            failures.append((rel, None, "非 UTF-8 内容"))
            continue
        scan_text(rel, text, failures)

    scan_history(failures)

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
    print(f"公开仓安全检查通过：已检查当前 {len(files)} 个文件及完整 Git 历史。")
    print("普通 Token 业务字段不作为凭据自动拦截；推送前仍需人工查看完整差异。")
    return 0

if __name__ == "__main__":
    sys.exit(main())
