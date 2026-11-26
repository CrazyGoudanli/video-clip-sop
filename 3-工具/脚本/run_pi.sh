#!/bin/zsh
# 用 Pi coding agent(pi)无人值守执行一个环节(与 run_claude.sh / run_codex.sh 对应)。
# - 工作目录 = 项目根目录;Pi 会读取根目录的 AGENTS.md。
# - --print:跑完输出最后的回复就退出;watch.py 从中读结束行(Pi 没有逐步事件,工作台看不到"最近几步")。
# - Pi 在 print 模式下直接执行 read/bash/edit/write,不逐条确认;红线靠 AGENTS.md 约束,改动可以用 git 查看和撤回。
# - ChatCut 工具接口要先接入 Pi:python3 3-工具/脚本/connect_chatcut.py pi
# 用法: run_pi.sh "<给 AI 的指令>"
set -e
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"
cd "${0:A:h}/../.."
PROXY="$(python3 -I -c "import json;print(json.load(open('配置.json')).get('代理',''))" 2>/dev/null || true)"
if [ -n "$PROXY" ]; then export HTTPS_PROXY=$PROXY HTTP_PROXY=$PROXY ALL_PROXY=$PROXY; fi
exec pi --print "$1" < /dev/null
