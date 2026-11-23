#!/bin/zsh
# 用 Claude Code 无人值守执行一个环节。
# - 把 .claude/settings.json 的允许/禁止清单直接作为命令行参数传入(文件夹未被"信任"时也生效,不改全局设置)。
# - 用 --add-dir 开放流程需要的目录:剪辑软件工作区、原始录像目录、成片目录、素材原片所在目录。
# 用法: run_claude.sh "<给 AI 的指令>"
set -e
cd "${0:A:h}/../.."
ALLOW=$(python3 -I -c "import json;print(','.join(json.load(open('.claude/settings.json'))['permissions']['allow']))")
DENY=$(python3 -I -c "import json;print(','.join(json.load(open('.claude/settings.json'))['permissions']['deny']))")
DIRS=()
while IFS= read -r d; do [ -d "$d" ] && DIRS+=(--add-dir "$d"); done < <(python3 -I - <<'PY'
import json, os, sqlite3, pathlib
c = json.load(open("配置.json"))
out = [os.path.expanduser(c.get("原始录像目录", "~/Movies")), os.path.expanduser(c.get("成片目录", "~/Movies/剪辑成片"))]
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
exec claude -p "$1" "${DIRS[@]}" --allowedTools "$ALLOW" --disallowedTools "$DENY" --output-format stream-json --verbose < /dev/null
