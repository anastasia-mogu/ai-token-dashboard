#!/usr/bin/env bash
# 从公开代码仓扫描本机日志，把真实设备数据提交到私有数据仓。
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

# 关闭 git 对非 ASCII 文件名的转义,不然 "data/设备-xxx.json" 在 diff --name-only 里会变成 "data/\350\256\276\..."
# 影响脚本里 STAGED_FILES 检查和二进制文件正则比较
git -C "$DATA_REPO" config core.quotepath false >/dev/null

REMOTE=$(git -C "$DATA_REPO" remote get-url origin 2>/dev/null || echo "")
BRANCH=$(git -C "$DATA_REPO" branch --show-current)
if [ -z "$REMOTE" ] || [ -z "$BRANCH" ]; then
  echo "  ! 私有数据仓缺少 origin 或当前分支，已停止。"
  exit 1
fi

case "$REMOTE" in
  https://github.com/*) DATA_REPO_SLUG=${REMOTE#https://github.com/} ;;
  git@github.com:*) DATA_REPO_SLUG=${REMOTE#git@github.com:} ;;
  ssh://git@github.com/*) DATA_REPO_SLUG=${REMOTE#ssh://git@github.com/} ;;
  *)
    echo "  ! 数据仓 origin 不是受支持的 GitHub 地址: $REMOTE"
    exit 1
    ;;
esac
DATA_REPO_SLUG=${DATA_REPO_SLUG%.git}
if [ "${DATA_REPO_SLUG##*/}" != "ai-token-dashboard-data" ]; then
  echo "  ! 数据仓名称不是 ai-token-dashboard-data，已停止。"
  echo "    当前: $DATA_REPO_SLUG"
  exit 1
fi
EXPECTED_DATA_REPO_SLUG=${AI_TOKEN_DATA_REPO_EXPECTED_SLUG:-}
if [ -z "$EXPECTED_DATA_REPO_SLUG" ]; then
  CODE_REMOTE=$(git remote get-url origin 2>/dev/null || echo "")
  case "$CODE_REMOTE" in
    https://github.com/*) CODE_REPO_SLUG=${CODE_REMOTE#https://github.com/} ;;
    git@github.com:*) CODE_REPO_SLUG=${CODE_REMOTE#git@github.com:} ;;
    ssh://git@github.com/*) CODE_REPO_SLUG=${CODE_REMOTE#ssh://git@github.com/} ;;
    *) CODE_REPO_SLUG="" ;;
  esac
  CODE_REPO_SLUG=${CODE_REPO_SLUG%.git}
  if [ -n "$CODE_REPO_SLUG" ] && [ "${CODE_REPO_SLUG##*/}" = "ai-token-dashboard" ]; then
    EXPECTED_DATA_REPO_SLUG="${CODE_REPO_SLUG%/*}/ai-token-dashboard-data"
  fi
fi
if [ -z "$EXPECTED_DATA_REPO_SLUG" ]; then
  echo "  ! 无法从公开仓 origin 推导私有数据仓身份。"
  echo "    请设置 AI_TOKEN_DATA_REPO_EXPECTED_SLUG，例如 owner/ai-token-dashboard-data。"
  exit 1
fi
if [ "$DATA_REPO_SLUG" != "$EXPECTED_DATA_REPO_SLUG" ]; then
  echo "  ! 数据仓身份不匹配，已停止。"
  echo "    预期: $EXPECTED_DATA_REPO_SLUG"
  echo "    当前: $DATA_REPO_SLUG"
  exit 1
fi
if ! command -v gh >/dev/null 2>&1; then
  echo "  ! 缺少 GitHub CLI（gh），无法验证数据仓可见性，已停止。"
  exit 1
fi
if ! VISIBILITY=$(gh repo view "$DATA_REPO_SLUG" --json visibility --jq '.visibility' 2>/dev/null); then
  echo "  ! 无法验证数据仓可见性。请先运行 gh auth status，确认已登录。"
  exit 1
fi
if [ "$VISIBILITY" != "PRIVATE" ]; then
  echo "  ! 数据仓不是 Private，已停止，绝不写入或推送真实数据。"
  exit 1
fi
if ! git -C "$DATA_REPO" diff --cached --quiet; then
  echo "  ! 私有数据仓已有暂存内容，已停止，避免混入本次设备数据："
  git -C "$DATA_REPO" diff --cached --name-status
  exit 1
fi

if [ -d .git ] && git remote get-url origin >/dev/null 2>&1; then
  echo "==> 拉取公开代码仓..."
  git pull --ff-only
fi

echo "==> 拉取私有数据仓..."
git -C "$DATA_REPO" pull --ff-only

echo "==> 扫描日志..."
python3 "$CODE_REPO/scan.py"

echo ""
echo "==> 检查私有数据仓..."
DEVICE_NAME=${AI_TOKEN_DEVICE:-$(python3 -c "import socket; print(socket.gethostname().split('.')[0])")}
SAFE_DEVICE_NAME=$(DEVICE_NAME="$DEVICE_NAME" python3 -c 'import os; dev=os.environ["DEVICE_NAME"]; safe="".join(c if c.isalnum() or c in "-_." else "_" for c in dev).strip("._"); print(safe or "device")')
DEVICE_DATA="data/设备-${SAFE_DEVICE_NAME}.json"
if [ ! -f "$DATA_REPO/$DEVICE_DATA" ]; then
  echo "  ! 未找到本机数据文件: $DATA_REPO/$DEVICE_DATA"
  exit 1
fi

git -C "$DATA_REPO" add "$DEVICE_DATA"
if git -C "$DATA_REPO" diff --cached --quiet; then
  echo "  没有变更，跳过 commit"
  exit 0
fi
STAGED_FILES=$(git -C "$DATA_REPO" diff --cached --name-only)
if [ "$STAGED_FILES" != "$DEVICE_DATA" ]; then
  echo "  ! 暂存区不只包含本机设备数据，已停止："
  git -C "$DATA_REPO" diff --cached --name-status
  exit 1
fi

echo ""
echo "==> 推送前检查"
echo "  数据仓: $DATA_REPO"
echo "  远端: $REMOTE"
echo "  分支: $BRANCH"
echo "  本次文件:"
git -C "$DATA_REPO" diff --cached --name-status
echo ""
git -C "$DATA_REPO" diff --cached --stat

SENSITIVE_PATTERN='password|secret|api[_-]?key|sk-|ghp_|AKIA|BEGIN .* PRIVATE KEY|(^|/)\.env($|\.)'
TOKEN_PATTERN='token'
SENSITIVE_HITS=$(git -C "$DATA_REPO" diff --cached -U0 -- | grep -Ein "$SENSITIVE_PATTERN" || true)
TOKEN_HITS=$(git -C "$DATA_REPO" diff --cached -U0 -- | grep -Ein "$TOKEN_PATTERN" || true)
if [ -n "$TOKEN_HITS" ]; then
  echo ""
  echo "==> Token 词命中（业务字段常见，请人工分类）"
  echo "$TOKEN_HITS" | sed -E 's/^([^:]+:[^:]+:).*/\1 <内容已隐藏>/'
fi
if [ -n "$SENSITIVE_HITS" ]; then
  echo ""
  echo "  ! 发现疑似高风险敏感信息，已停止。命中文件和行号如下:"
  echo "$SENSITIVE_HITS" | sed -E 's/^([^:]+:[^:]+:).*/\1 <内容已隐藏>/'
  exit 1
fi

LARGE_FILES=$(DATA_REPO="$DATA_REPO" python3 - <<'PY'
import os, subprocess
from pathlib import Path
repo = Path(os.environ["DATA_REPO"])
names = subprocess.check_output(['git', '-C', str(repo), 'diff', '--cached', '--name-only', '-z']).split(b'\0')
for raw in names:
    if not raw:
        continue
    path = repo / raw.decode()
    if path.exists() and path.stat().st_size > 1024 * 1024:
        print(path.relative_to(repo))
PY
)
BINARY_FILES=$(git -C "$DATA_REPO" diff --cached --name-only | grep -Ei '\.(zip|sqlite|db|mp4|mov|pdf)$' || true)
if [ -n "$LARGE_FILES" ] || [ -n "$BINARY_FILES" ]; then
  echo ""
  echo "  ! 发现大文件或二进制文件，已停止。请先确认是否应加入 .gitignore。"
  [ -n "$LARGE_FILES" ] && echo "$LARGE_FILES"
  [ -n "$BINARY_FILES" ] && echo "$BINARY_FILES"
  exit 1
fi

echo ""
read -r -p "确认提交并推送以上私有数据？请输入“推送”：" CONFIRM
if [ "$CONFIRM" != "推送" ]; then
  git -C "$DATA_REPO" restore --staged -- "$DEVICE_DATA"
  echo "  已取消并取消暂存；数据文件修改仍保留在本机。"
  exit 0
fi

DATE=$(date "+%Y-%m-%d %H:%M")
git -C "$DATA_REPO" commit -m "更新设备数据 $DEVICE_NAME $DATE" -- "$DEVICE_DATA"
git -C "$DATA_REPO" push origin "$BRANCH"
echo "  ✓ 已推送到 $REMOTE"
