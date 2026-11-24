#!/bin/zsh
# AI 生图(封面),配置.生图方式 = Codex 时使用:调用 Codex 的生图能力(消耗用户自己的 ChatGPT 额度)。
# 用法: gen_cover.sh <工作目录> <提示词文件> <参考图1> [参考图2 ...]
# 生成的图片由提示词要求写到 <工作目录> 下(如 3x4.png、4x3.png)。
# 代理:优先用环境变量 COVER_PROXY,其次用 配置.json 的 "代理";都为空就直连。
set -e
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
ROOT="${0:A:h}/../.."
PROXY="${COVER_PROXY:-$(python3 -I -c "import json,sys;print(json.load(open(sys.argv[1])).get('代理',''))" "$ROOT/配置.json" 2>/dev/null || true)}"
if [ -n "$PROXY" ]; then
  export HTTPS_PROXY=$PROXY HTTP_PROXY=$PROXY ALL_PROXY=$PROXY
fi
WORK="$1"; PROMPT="$2"; shift 2
[ -d "$WORK" ] || { echo "工作目录不存在: $WORK"; exit 2; }
[ -f "$PROMPT" ] || { echo "提示词文件不存在: $PROMPT"; exit 2; }
IMGS=(); for r in "$@"; do IMGS+=(-i "$r"); done
codex exec --skip-git-repo-check -C "$WORK" --sandbox workspace-write "${IMGS[@]}" < "$PROMPT"
