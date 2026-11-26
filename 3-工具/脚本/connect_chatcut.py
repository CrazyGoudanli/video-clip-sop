#!/usr/bin/env python3
"""把 ChatCut 的工具接口(MCP)接入 Cursor CLI 或 Pi。已接入的不会重复添加,也不改动其他已有配置。
用法: python3 3-工具/脚本/connect_chatcut.py cursor|pi
(Claude Code / Codex 用它们自带的命令,见 3-工具/工具说明/剪辑_ChatCut.md)
"""
import json, sys
from pathlib import Path

HOME = Path.home()
MCP = HOME / "Library/Application Support/ChatCut/chatcut-mcp"
TARGET = {"cursor": (HOME / ".cursor/mcp.json", "cursor"), "pi": (HOME / ".pi/agent/mcp.json", "pi")}

if len(sys.argv) != 2 or sys.argv[1] not in TARGET:
    sys.exit(__doc__)
if not MCP.exists():
    sys.exit(f"找不到 {MCP}:请先打开一次 ChatCut 并登录")
path, client = TARGET[sys.argv[1]]
cfg = json.loads(path.read_text()) if path.exists() else {}
servers = cfg.setdefault("mcpServers", {})
# ChatCut 启动文件在 "Application Support"(带空格)里,Cursor 会按空格截断 command,
# 所以用 /bin/sh 启动、把路径放进 args。
want = {"command": "/bin/sh", "args": [str(MCP)], "env": {"CHATCUT_MCP_CLIENT": client}}
old = servers.get("chatcut_desktop")
if old == want:
    print(f"已接入,不重复添加:{path}")
    sys.exit(0)
if old and " " not in str(old.get("command", "")):
    print(f"已有 chatcut_desktop 配置(非本脚本写入),不改动:{path}")
    sys.exit(0)
servers["chatcut_desktop"] = want
path.parent.mkdir(parents=True, exist_ok=True)
if path.exists():
    path.with_suffix(".json.bak").write_text(path.read_text())
path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")
print(f"✅ 已把 ChatCut 接入 {sys.argv[1]}:{path}")
