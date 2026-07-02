#!/usr/bin/env python3
"""扫 ~/.claude/projects 和 ~/.codex/sessions 的日志，汇总 token 用量。

设计要点:
- 项目名用共享种子生成稳定代号，对照表只存本地
- 每个会话只取一次累计值,避免重复计数
  - Claude Code: 一个 sessionId 内所有 assistant.usage 累加
  - Codex: 每个 jsonl 取最后一条 token_count.info.total_token_usage
- 真实设备 JSON 写入私有数据仓，本地 data.js 写入代码仓供浏览器读取
"""
import json
import hashlib
import hmac
import os
import socket
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
CODE_REPO = Path(__file__).resolve().parent
CONFIG_FILE = CODE_REPO / "config.local.json"
CC_DIR = HOME / ".claude" / "projects"
CODEX_DIR = HOME / ".codex" / "sessions"
ALIAS_FILE = CODE_REPO / ".project-aliases.json"  # 本地对照表,git 忽略


def resolve_data_repo() -> Path:
    """定位私有数据仓：环境变量 > 本地配置 > 同级默认目录。"""
    configured = os.environ.get("AI_TOKEN_DATA_REPO")
    if not configured and CONFIG_FILE.exists():
        try:
            configured = json.loads(CONFIG_FILE.read_text()).get("data_repo")
        except json.JSONDecodeError as exc:
            raise SystemExit(f"config.local.json 不是合法 JSON: {exc}") from exc
    data_repo = Path(configured).expanduser() if configured else CODE_REPO.parent / "ai-token-dashboard-data"
    return data_repo.resolve()


DATA_REPO = resolve_data_repo()
OUT_DIR = DATA_REPO / "data"
SEED_FILE = DATA_REPO / ".project-hash-seed"


def write_text_atomic(path: Path, content: str) -> None:
    """先写临时文件再替换，避免中断时留下半个 JSON。"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content)
    tmp.replace(path)


def device_name() -> str:
    """设备名优先读环境变量 AI_TOKEN_DEVICE,否则用主机名。"""
    return os.environ.get("AI_TOKEN_DEVICE") or socket.gethostname().split(".")[0]


def load_seed() -> bytes:
    """读取多台电脑共用的项目代号种子。"""
    if not DATA_REPO.exists():
        raise SystemExit(
            f"找不到私有数据仓: {DATA_REPO}\n"
            "请设置 AI_TOKEN_DATA_REPO，或在代码仓同级放置 ai-token-dashboard-data。"
        )
    if not SEED_FILE.exists():
        raise SystemExit(
            "缺少 .project-hash-seed。请先从私有数据仓拉取该文件，再重新扫描。"
        )
    seed = SEED_FILE.read_text().strip()
    if len(seed) < 32:
        raise SystemExit(".project-hash-seed 内容异常，已停止扫描。")
    return seed.encode("utf-8")


def load_aliases() -> dict:
    if ALIAS_FILE.exists():
        return json.loads(ALIAS_FILE.read_text())
    return {}


def save_aliases(aliases: dict) -> None:
    write_text_atomic(ALIAS_FILE, json.dumps(aliases, ensure_ascii=False, indent=2))
    ALIAS_FILE.chmod(0o600)


def anonymize(project_name: str, aliases: dict, seed: bytes) -> str:
    """项目名 → 稳定项目代号；种子只存在私有数据仓。"""
    digest = hmac.new(seed, project_name.encode("utf-8"), hashlib.sha256).hexdigest()[:12]
    alias = f"项目-{digest}"
    aliases[project_name] = alias
    return alias


def parse_iso_to_date(ts: str) -> str:
    """ISO 时间戳 → YYYY-MM-DD (本地时区)。"""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        return "未知"


def scan_claude_code(aliases: dict, seed: bytes) -> list:
    """扫 Claude Code 日志。返回会话级记录:[{date, ai, project, tokens:{...}}]。"""
    records = []
    if not CC_DIR.exists():
        return records

    for proj_dir in CC_DIR.iterdir():
        if not proj_dir.is_dir():
            continue
        for jsonl in proj_dir.glob("*.jsonl"):
            # 一个 jsonl = 一个会话, sessionId 一致
            sums = defaultdict(int)
            session_date = None
            session_cwd = None
            for line in jsonl.open(errors="ignore"):
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not session_cwd:
                    session_cwd = obj.get("cwd")
                if obj.get("type") != "assistant":
                    continue
                msg = obj.get("message") or {}
                usage = msg.get("usage") or {}
                if not usage:
                    continue
                if session_date is None:
                    session_date = parse_iso_to_date(obj.get("timestamp", ""))
                sums["input"] += usage.get("input_tokens", 0) or 0
                sums["output"] += usage.get("output_tokens", 0) or 0
                sums["cache_create"] += usage.get("cache_creation_input_tokens", 0) or 0
                sums["cache_read"] += usage.get("cache_read_input_tokens", 0) or 0

            total = sums["input"] + sums["output"] + sums["cache_create"] + sums["cache_read"]
            if total == 0:
                continue
            project_name = Path(session_cwd).name if session_cwd else proj_dir.name
            alias = anonymize(project_name, aliases, seed)
            records.append({
                "date": session_date or "未知",
                "ai": "Claude Code",
                "project": alias,
                "tokens": dict(sums),
                "total": total,
            })
    return records


def scan_codex(aliases: dict, seed: bytes) -> list:
    """扫 Codex 日志。每个 jsonl 取最后一条 token_count.info 的累计值。"""
    records = []
    if not CODEX_DIR.exists():
        return records

    for jsonl in CODEX_DIR.rglob("rollout-*.jsonl"):
        last_total = None
        session_date = None
        cwd = None
        for line in jsonl.open(errors="ignore"):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = obj.get("payload") or {}
            # session_meta 给项目路径和起始时间
            if obj.get("type") == "session_meta" and not cwd:
                cwd = payload.get("cwd") or payload.get("originator", "未知")
                session_date = parse_iso_to_date(payload.get("timestamp", obj.get("timestamp", "")))
            # token_count 有累计用量
            if payload.get("type") == "token_count":
                info = payload.get("info")
                if info and info.get("total_token_usage"):
                    last_total = info["total_token_usage"]

        if not last_total:
            continue
        proj_name = Path(cwd).name if cwd else "(unknown)"
        alias = anonymize(proj_name, aliases, seed)
        sums = {
            "input": last_total.get("input_tokens", 0) or 0,
            "output": last_total.get("output_tokens", 0) or 0,
            "cache_read": last_total.get("cached_input_tokens", 0) or 0,
            "reasoning": last_total.get("reasoning_output_tokens", 0) or 0,
        }
        total = last_total.get("total_tokens") or sum(sums.values())
        records.append({
            "date": session_date or "未知",
            "ai": "Codex",
            "project": alias,
            "tokens": sums,
            "total": total,
        })
    return records


def aggregate(records: list) -> dict:
    """会话级记录 → 按多维度聚合。"""
    by_date = defaultdict(int)
    by_ai = defaultdict(int)
    by_project = defaultdict(int)
    by_date_ai = defaultdict(lambda: defaultdict(int))
    by_date_io = defaultdict(lambda: defaultdict(int))  # {date: {input, output}}
    by_ai_io = defaultdict(lambda: defaultdict(int))    # {ai: {input, output}}
    grand_total = 0
    total_input = 0
    total_output = 0
    session_count = 0

    for r in records:
        t = r["total"]
        tk = r["tokens"]
        # 输入/输出口径(对齐两家):
        # Claude Code: input_tokens 不含缓存,所以要加上 cache_create + cache_read
        # Codex: input_tokens 已包含 cached_input_tokens,不能再加
        # 所以拿 ai 字段判一下
        if r["ai"] == "Claude Code":
            inp = tk.get("input", 0) + tk.get("cache_create", 0) + tk.get("cache_read", 0)
            out = tk.get("output", 0)
        else:  # Codex
            inp = tk.get("input", 0)  # 已含 cache
            # Codex 的 output_tokens 已包含 reasoning_output_tokens，不能重复相加。
            out = tk.get("output", 0)
        grand_total += t
        total_input += inp
        total_output += out
        session_count += 1
        by_date[r["date"]] += t
        by_ai[r["ai"]] += t
        by_project[r["project"]] += t
        by_date_ai[r["date"]][r["ai"]] += t
        by_date_io[r["date"]]["input"] += inp
        by_date_io[r["date"]]["output"] += out
        by_ai_io[r["ai"]]["input"] += inp
        by_ai_io[r["ai"]]["output"] += out

    return {
        "grand_total": grand_total,
        "total_input": total_input,
        "total_output": total_output,
        "session_count": session_count,
        "by_date": dict(sorted(by_date.items())),
        "by_ai": dict(by_ai),
        "by_project": dict(sorted(by_project.items(), key=lambda x: -x[1])),
        "by_date_ai": {d: dict(v) for d, v in sorted(by_date_ai.items())},
        "by_date_io": {d: dict(v) for d, v in sorted(by_date_io.items())},
        "by_ai_io": {a: dict(v) for a, v in by_ai_io.items()},
    }


def main() -> None:
    aliases = load_aliases()
    seed = load_seed()
    dev = device_name()
    print(f"设备名: {dev}")
    print("扫描 Claude Code...", flush=True)
    cc = scan_claude_code(aliases, seed)
    print(f"  → {len(cc)} 个会话")
    print("扫描 Codex...", flush=True)
    cx = scan_codex(aliases, seed)
    print(f"  → {len(cx)} 个会话")

    save_aliases(aliases)
    summary = aggregate(cc + cx)
    summary["device"] = dev
    summary["scanned_at"] = datetime.now(timezone.utc).astimezone().isoformat()

    OUT_DIR.mkdir(exist_ok=True)
    safe_dev = "".join(c if c.isalnum() or c in "-_." else "_" for c in dev).strip("._")
    safe_dev = safe_dev or "device"
    out = OUT_DIR / f"设备-{safe_dev}.json"
    write_text_atomic(out, json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n写入 {out}")
    print(f"总 token: {summary['grand_total']:,}")
    print(f"总会话: {summary['session_count']}")

    # 生成 data.js (合并所有设备文件,给浏览器直接 <script> 加载用)
    # 浏览器双击打开 HTML 时 fetch 本地 JSON 会被 file:// CORS 拦掉,所以走 .js
    all_devices = []
    for f in sorted(OUT_DIR.glob("设备-*.json")):
        try:
            all_devices.append(json.loads(f.read_text()))
        except json.JSONDecodeError:
            continue
    data_js = CODE_REPO / "data.js"
    write_text_atomic(
        data_js,
        "window.AI_TOKEN_DATA_IS_EXAMPLE = false;\n"
        f"window.AI_TOKEN_LOCAL_DEVICE = {json.dumps(dev, ensure_ascii=False)};\n"
        "window.AI_TOKEN_DATA = "
        + json.dumps(all_devices, ensure_ascii=False, indent=2)
        + ";\n"
    )
    print(f"生成 data.js (包含 {len(all_devices)} 台设备)")


if __name__ == "__main__":
    sys.exit(main())
