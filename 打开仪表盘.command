#!/usr/bin/env bash
# 双击运行：拉取公开代码与私有数据 → 扫描本机 → 打开仪表盘
set -euo pipefail
CODE_REPO="$(cd "$(dirname "$0")" && pwd)"
cd "$CODE_REPO"

DATA_REPO=$(python3 - <<'PY'
import json, os
from pathlib import Path
code_repo = Path.cwd()
configured = os.environ.get("AI_TOKEN_DATA_REPO")
config = code_repo / "config.local.json"
if not configured and config.exists():
    configured = json.loads(config.read_text()).get("data_repo")
path = Path(configured).expanduser() if configured else code_repo.parent / "ai-token-dashboard-data"
print(path.resolve())
PY
)

if [ ! -d "$DATA_REPO/.git" ]; then
  echo "  ! 找不到私有数据仓: $DATA_REPO"
  echo "    请设置 AI_TOKEN_DATA_REPO，或把 ai-token-dashboard-data 放在代码仓同级。"
  exit 1
fi

echo "==> 拉取公开代码仓..."
if [ -d .git ] && git remote get-url origin >/dev/null 2>&1; then
  if ! git pull --ff-only; then
    echo "  ! 公开代码仓拉取失败，已停止。请先处理网络、登录或冲突问题。"
    exit 1
  fi
else
  echo "  (公开目录还没有 origin，跳过拉取)"
fi

echo "==> 拉取私有数据仓..."
if ! git -C "$DATA_REPO" pull --ff-only; then
  echo "  ! 私有数据仓拉取失败，已停止。请先处理网络、登录或冲突问题。"
  exit 1
fi

echo ""
echo "==> 扫一次本机..."
python3 "$CODE_REPO/scan.py"

echo ""
echo "==> 打开浏览器..."
open dashboard.html

echo ""
echo "✓ 完成"
sleep 2
