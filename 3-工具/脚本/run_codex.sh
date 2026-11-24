#!/bin/zsh
# 用 Codex 无人值守执行一个环节(与 run_claude.sh 对应)。
# - 工作目录 = 项目根目录,Codex 会自动读取根目录的 AGENTS.md。
# - 沙箱 workspace-write:只能写项目内的文件;--add-dir 额外开放剪辑软件工作区和项目外的原片所在目录。
# - 打开沙箱内的网络:ego lite 浏览器、生图都需要。
# - Codex 没有 Claude Code 那样的"禁止清单",红线(不改 1-流程/2-标准、不花钱、只定时发布)靠 AGENTS.md 约束,
#   改动可以用 git 查看和撤回。
# 用法: run_codex.sh "<给 AI 的指令>"
set -e
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
cd "${0:A:h}/../.."
DIRS=()
while IFS= read -r d; do [ -d "$d" ] && DIRS+=(--add-dir "$d"); done < <(python3 -I - <<'PY'
import json, os, sqlite3, pathlib
c = json.load(open("配置.json"))
out = []
if c.get("剪辑工具") == "ChatCut":
    out.append(os.path.expanduser("~/Library/Application Support/ChatCut/projects"))
try:
    db = sqlite3.connect(f"file:{c.get('数据库位置','data/sop.db')}?mode=ro", uri=True)
    for (p,) in db.execute("select distinct 原片位置 from sources where 原片位置 like '/%'"):
        out.append(str(pathlib.Path(p).parent))
except Exception:
    pass
print("\n".join(dict.fromkeys(out)))
PY
)
exec codex exec "$1" -C "$PWD" --skip-git-repo-check --sandbox workspace-write \
  -c sandbox_workspace_write.network_access=true "${DIRS[@]}" --json < /dev/null
