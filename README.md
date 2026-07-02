# AI Token 仪表盘

在本机统计 Claude Code 与 Codex 的 Token 用量，并用离线网页展示趋势。公开仓只放程序和虚构示例；真实设备统计、项目代号种子与本机项目名对照表不会进入公开仓。

## 先看虚构示例

直接双击 `dashboard.html`。页面会读取 `data.example.js`，无需联网，也不会扫描电脑。

## 使用真实数据

准备两个同级目录：

```text
AI/
├── ai-token-dashboard/       # 本公开代码仓
└── ai-token-dashboard-data/  # 你自己的私有数据仓
```

私有数据仓至少需要 `.project-hash-seed`（至少 32 个字符，仅保存在私有仓）和 `data/` 目录。

日常使用时双击 `打开仪表盘.command`。它会依次拉取公开代码仓和私有数据仓、扫描本机日志、生成已忽略的本地 `data.js`，然后打开仪表盘。真实数据会覆盖虚构示例。

如果私有数据仓不在默认同级位置，可设置环境变量 `AI_TOKEN_DATA_REPO`，或新建已忽略的 `config.local.json`：

```json
{"data_repo": "你的私有数据仓绝对路径"}
```

需要更新私有数据仓时，先安装并登录 GitHub CLI（`gh`），再运行 `./update.sh`。脚本会从公开仓 `origin` 推导同一账号下的 `ai-token-dashboard-data`，并强制确认它是 Private；如需使用不同账号，可显式设置 `AI_TOKEN_DATA_REPO_EXPECTED_SLUG=owner/ai-token-dashboard-data`。脚本还会拒绝已有暂存内容，并只允许提交本机设备数据。只有人工输入“推送”后才会提交并推送。

## 隐私边界

- 扫描器只汇总用量字段，不保存或上传对话正文。
- 项目名使用私有共享种子生成稳定代号；原名对照表只留在本机。
- `data.js`、本机配置、项目映射、共享种子和 `data/` 已被公开仓忽略。
- `scripts/check-public-safety.py` 检查当前文件和完整 Git 历史中的禁入文件、凭据特征、本机绝对路径、意外大文件和二进制内容。
- GitHub Actions 会在公开仓的提交和拉取请求中重复执行检查。

本项目采用 [MIT License](LICENSE)。
