#!/usr/bin/env bash
# 静默拉取公开代码 + 私有数据仓,并扫描本机日志。
# 由 打开仪表盘.app 在后台异步调用,不需要终端窗口。
# 所有输出重定向到日志文件,失败也不会打断浏览器体验。
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
  echo "  ! 找不到私有数据仓: $DATA_REPO" >&2
  exit 1
fi

if [ -d .git ] && git remote get-url origin >/dev/null 2>&1; then
  git pull --ff-only >/dev/null 2>&1 || echo "  ! 公开代码仓拉取失败(网络/冲突),跳过继续" >&2
fi

git -C "$DATA_REPO" pull --ff-only >/dev/null 2>&1 || echo "  ! 私有数据仓拉取失败(网络/冲突),使用本地已有数据" >&2

python3 "$CODE_REPO/scan.py" >/dev/null 2>&1 || echo "  ! scan.py 执行失败" >&2

echo "done"
