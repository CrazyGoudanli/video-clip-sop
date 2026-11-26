#!/bin/zsh
# 用 Cursor CLI(cursor-agent)无人值守执行一个环节(与 run_claude.sh / run_codex.sh 对应)。
# - 工作目录 = 项目根目录;Cursor 会读取根目录的 AGENTS.md / .cursorrules。
# - --force:允许执行命令(无人值守没人点确认);--trust:信任本项目;--approve-mcps:自动启用 ChatCut 工具接口。
# - Cursor CLI 没有 Claude Code 那样逐条的"禁止清单",红线(不改 1-流程/2-标准、不花钱、只定时发布)靠 AGENTS.md 约束,
#   改动可以用 git 查看和撤回。
# - 输出 stream-json:watch.py 从中读结束行,工作台从中读"最近几步"。
# 用法: run_cursor.sh "<给 AI 的指令>"
set -e
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
cd "${0:A:h}/../.."
PROXY="$(python3 -I -c "import json;print(json.load(open('配置.json')).get('代理',''))" 2>/dev/null || true)"
if [ -n "$PROXY" ]; then export HTTPS_PROXY=$PROXY HTTP_PROXY=$PROXY ALL_PROXY=$PROXY; fi
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
CLI="$(command -v cursor-agent || command -v agent)"
exec "$CLI" -p "$1" --output-format stream-json --force --trust --approve-mcps --workspace "$PWD" "${DIRS[@]}" < /dev/null
