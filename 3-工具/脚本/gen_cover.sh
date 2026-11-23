#!/bin/zsh
# AI 生图(封面)。走本机代理调用 Codex 的生图能力。
# 用法: gen_cover.sh <工作目录> <提示词文件> <参考图1> [参考图2 ...]
# 生成的图片由提示词要求写到 <工作目录> 下(如 3x4.png、4x3.png)。
set -e
export PATH="$HOME/.local/bin:$PATH"
PROXY="${COVER_PROXY:-http://127.0.0.1:7890}"
export HTTPS_PROXY=$PROXY HTTP_PROXY=$PROXY ALL_PROXY=$PROXY
WORK="$1"; PROMPT="$2"; shift 2
[ -d "$WORK" ] || { echo "工作目录不存在: $WORK"; exit 2; }
[ -f "$PROMPT" ] || { echo "提示词文件不存在: $PROMPT"; exit 2; }
IMGS=(); for r in "$@"; do IMGS+=(-i "$r"); done
codex exec --skip-git-repo-check -C "$WORK" --sandbox workspace-write "${IMGS[@]}" < "$PROMPT"
