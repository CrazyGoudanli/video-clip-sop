#!/usr/bin/env python3
"""环境检查:这台 Mac 能不能跑这套流程,缺什么、谁来装。

用法(在项目根目录):
  python3 3-工具/check_env.py           逐项检查,给出处理办法
  python3 3-工具/check_env.py --fix     顺手做"零风险"的事:建项目文件夹、建空数据库
  python3 3-工具/check_env.py --json    输出 JSON(给 AI 或网页工作台用)

每一项的"谁来":
  AI   = 驱动 AI 可以直接运行给出的命令安装
  用户 = 需要用户本人操作(装应用、登录、输入密码、存密钥),AI 只引导
只读检查,不会读取或显示任何密钥。只用 Python 标准库。
"""
import json, os, platform, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()
EXTRA_PATH = [str(HOME / ".local/bin"), "/opt/homebrew/bin", "/usr/local/bin"]
os.environ["PATH"] = os.pathsep.join(EXTRA_PATH + [os.environ.get("PATH", "")])
CHATCUT_MCP = HOME / "Library/Application Support/ChatCut/chatcut-mcp"

cfg_path = ROOT / "配置.json"
CFG = json.loads(cfg_path.read_text()) if cfg_path.exists() else json.loads((ROOT / "配置模板.json").read_text())
res = []


def add(group, name, ok, who="AI", fix="", detail="", level="❌"):
    res.append({"分组": group, "项目": name, "通过": bool(ok), "级别": "✅" if ok else level,
                "谁来": who, "处理": "" if ok else fix, "详情": detail})


def run(cmd, timeout=20):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return 1, str(e)


def which(x):
    return shutil.which(x)


def folder(key, default):
    p = Path(os.path.expanduser(CFG.get(key, default)))
    return p if p.is_absolute() else ROOT / p


fix_mode = "--fix" in sys.argv
has_brew = bool(which("brew"))

# ---------- 系统 ----------
G = "系统"
add(G, "macOS", platform.system() == "Darwin", "用户", "这套流程目前只支持 Mac", platform.platform())
add(G, "Apple 芯片(本机转写需要)", platform.machine() == "arm64", "用户",
    "Intel Mac 不能用本机转写 mlx_whisper,需要换转写方式(暂不支持)", platform.machine())
add(G, "Python 3.9+", sys.version_info >= (3, 9), "AI",
    "运行 `xcode-select --install` 装苹果命令行工具(会弹窗,需用户点安装)", sys.version.split()[0])
add(G, "配置.json", cfg_path.exists(), "AI", "按 `启动问卷.md` 问用户后生成", level="⚠️")

# ---------- 基础工具(AI 可装) ----------
G = "基础工具"
add(G, "Homebrew(可选)", has_brew, "用户",
    "可选。装了以后其他工具更好装:到 https://brew.sh 复制安装命令,在终端运行(需要输入开机密码)", level="⚠️")
add(G, "uv(Python 工具管理)", which("uv"), "AI", "`curl -LsSf https://astral.sh/uv/install.sh | sh`")
ff_fix = "`brew install ffmpeg`" if has_brew else \
    "没有 Homebrew:下载 Apple 芯片的 ffmpeg 和 ffprobe 静态版,放到 `~/.local/bin/` 并 `chmod +x`;或先装 Homebrew 再 `brew install ffmpeg`"
add(G, "ffmpeg", which("ffmpeg"), "AI", ff_fix)
add(G, "ffprobe", which("ffprobe"), "AI", ff_fix)
if CFG.get("转写方式", "本机转写") == "本机转写":
    add(G, "本机转写 mlx_whisper", which("mlx_whisper"), "AI",
        "`uv tool install mlx-whisper --with socksio`(带上 SOCKS 代理支持;首次转写会自动下载约 1.6 GB 模型)")

# ---------- 驱动 AI ----------
G = "驱动 AI"
drv = CFG.get("驱动AI", "Claude Code")
if drv == "Codex":
    ok = bool(which("codex"))
    add(G, "Codex 已安装", ok, "用户", "按 OpenAI 官方说明安装 Codex 命令行版")
    if ok:
        code, out = run(["codex", "login", "status"])
        add(G, "Codex 已登录", code == 0 and "Logged in" in out, "用户", "在终端运行 `codex login` 并登录", out[:60])
    # Codex 在沙箱里跑,看不到 GPU:本机转写(mlx_whisper)不能交给它。watch.py 会在启动 AI 前自己转写。
    add(G, "Codex 沙箱用不了 GPU(已由监测脚本先转写)", False, "AI",
        "知悉即可:转写由 watch.py 在沙箱外直接跑;手动叫 Codex 做「1-复盘选片」前,先在终端跑 transcribe.sh", level="⚠️")
elif drv == "Cursor CLI":
    ok = bool(which("cursor-agent") or which("agent"))
    add(G, "Cursor CLI 已安装", ok, "AI", "`curl https://cursor.com/install -fsS | bash`(装好后命令是 cursor-agent)")
    if ok:
        code, out = run([which("cursor-agent") or which("agent"), "status"])
        add(G, "Cursor CLI 已登录", code == 0 and "Logged in" in out, "用户", "在终端运行 `cursor-agent login` 并在浏览器里登录")
elif drv == "Pi":
    ok = bool(which("pi"))
    add(G, "Pi coding agent 已安装", ok, "AI", "`npm install -g @earendil-works/pi-coding-agent`(需要 Node.js)")
    if ok:
        add(G, "Pi 已配置模型账号(只能真实跑一次确认)", False, "用户",
            "在终端运行 `pi`,输入 /login 登录,或设置 ANTHROPIC_API_KEY / OPENAI_API_KEY 等环境变量", level="⚠️")
    add(G, "Pi 看不到逐步过程", False, "AI", "知悉即可:Pi 只输出最后结果,工作台左下角看不到\"最近几步\"", level="⚠️")
else:
    ok = bool(which("claude"))
    add(G, "Claude Code 已安装", ok, "用户", "按 Anthropic 官方说明安装 Claude Code")
    if ok:
        code, out = run(["claude", "auth", "status"])
        add(G, "Claude Code 已登录", code == 0 and '"loggedIn": true' in out, "用户", "在终端运行 `claude` 按提示登录")
dcmd = (CFG.get("驱动命令") or "").split(" ")[:2]
add(G, "驱动命令已设置", bool(dcmd and dcmd[0]), "AI",
    "按驱动AI 填:`zsh 3-工具/脚本/run_<claude|codex|cursor|pi>.sh {prompt}`", level="⚠️")

# ---------- 剪辑:ChatCut ----------
G = "剪辑 ChatCut"
if CFG.get("剪辑工具", "ChatCut") == "ChatCut":
    app = Path("/Applications/ChatCut.app").exists()
    add(G, "ChatCut 应用已安装", app, "用户", "从 ChatCut 官网下载安装,打开并登录")
    add(G, "ChatCut 工具接口程序", CHATCUT_MCP.exists(), "用户",
        "打开一次 ChatCut 并登录,它会生成这个程序", str(CHATCUT_MCP))
    if drv == "Codex":
        try:
            linked = "[mcp_servers.chatcut_desktop]" in (HOME / ".codex/config.toml").read_text()
        except Exception:
            linked = False
        fix = 'codex mcp add chatcut_desktop --env CHATCUT_MCP_CLIENT=codex_app -- "$HOME/Library/Application Support/ChatCut/chatcut-mcp"'
    elif drv in ("Cursor CLI", "Pi"):
        f = HOME / (".cursor/mcp.json" if drv == "Cursor CLI" else ".pi/agent/mcp.json")
        try:
            s = json.loads(f.read_text()).get("mcpServers", {}).get("chatcut_desktop")
            # 旧写法把带空格的路径直接放进 command,Cursor 会启动失败,算未接入
            linked = bool(s) and " " not in str(s.get("command", ""))
        except Exception:
            linked = False
        fix = f"python3 3-工具/脚本/connect_chatcut.py {'cursor' if drv == 'Cursor CLI' else 'pi'}"
    else:
        try:
            linked = "chatcut_desktop" in json.loads((HOME / ".claude.json").read_text()).get("mcpServers", {})
        except Exception:
            linked = False
        fix = 'claude mcp add -s user chatcut_desktop -e CHATCUT_MCP_CLIENT=claude_code -- "$HOME/Library/Application Support/ChatCut/chatcut-mcp"'
    add(G, f"{drv} 已接入 ChatCut", linked, "AI", f"`{fix}`")
else:
    add(G, "剪辑工具", True, detail=CFG.get("剪辑工具"))

# ---------- 封面生图 ----------
G = "封面生图"
mode = CFG.get("生图方式", "Codex")
if mode == "Codex":
    ok = bool(which("codex"))
    add(G, "Codex 已安装(用于生图)", ok, "用户", "按 OpenAI 官方说明安装 Codex;或把 生图方式 改成 模板", level="⚠️")
    if ok:
        code, out = run(["codex", "login", "status"])
        add(G, "Codex 已登录", code == 0 and "Logged in" in out, "用户", "在终端运行 `codex login`", level="⚠️")
elif mode == "API Key":
    code, _ = run(["security", "find-generic-password", "-s", "video-clip-sop", "-a", "image-api-key"])
    add(G, "钥匙串里有生图 API Key", code == 0, "用户",
        "请用户自己在终端运行:`security add-generic-password -s video-clip-sop -a image-api-key -w`,回车后输入密钥", level="⚠️")
add(G, "后备模板封面所需 uv", which("uv"), "AI", "`curl -LsSf https://astral.sh/uv/install.sh | sh`", level="⚠️")

# ---------- 发布浏览器 ----------
G = "发布浏览器"
if CFG.get("发布浏览器", "ego lite") == "ego lite":
    add(G, "ego lite 应用已安装", Path("/Applications/ego lite.app").exists(), "用户", "从 ego lite 官网下载安装")
    add(G, "ego-browser 命令可用", which("ego-browser"), "用户",
        "让用户打开一次 ego lite 应用后再检查;仍然没有,告诉用户这一项需要他确认 ego lite 的命令行工具怎么装", level="⚠️")
plats = CFG.get("发布平台", ["抖音"])
add(G, "平台已登录(只能真实打开一次确认)", False, "用户",
    f"在 ego lite 里登录这些平台的创作者中心:{'、'.join(plats)}", level="⚠️")

# ---------- 项目文件夹与数据库 ----------
G = "项目文件夹"
for key, default in (("待加工目录", "待加工"), ("成片目录", "成片"), ("工作区目录", "工作区"),
                     ("参考目录", "参考"), ("学习目录", "学习")):
    p = folder(key, default)
    if fix_mode and not p.exists():
        p.mkdir(parents=True, exist_ok=True)
    add(G, f"{default}/ 存在且可写", p.is_dir() and os.access(p, os.W_OK), "AI", "运行 `python3 3-工具/check_env.py --fix`", str(p))
for sub in ("封面", "视频风格"):
    p = folder("参考目录", "参考") / sub
    if fix_mode:
        p.mkdir(parents=True, exist_ok=True)
    add(G, f"参考/{sub}/ 存在", p.is_dir(), "AI", "运行 `python3 3-工具/check_env.py --fix`")
db = ROOT / CFG.get("数据库位置", "data/sop.db")
if fix_mode and not db.exists():
    run([sys.executable, str(ROOT / "3-工具/db.py"), "init"])
add(G, "数据库已建好", db.exists(), "AI", "`python3 3-工具/db.py init`")

# ---------- 输出 ----------
if "--json" in sys.argv:
    print(json.dumps(res, ensure_ascii=False, indent=1))
else:
    cur = None
    for r in res:
        if r["分组"] != cur:
            cur = r["分组"]
            print(f"\n== {cur}")
        line = f"  {r['级别']} {r['项目']}"
        if r["详情"] and r["通过"]:
            line += f"({r['详情']})"
        print(line)
        if not r["通过"]:
            print(f"      → [{r['谁来']}] {r['处理']}")
    bad = [r for r in res if not r["通过"] and r["级别"] == "❌"]
    warn = [r for r in res if not r["通过"] and r["级别"] == "⚠️"]
    print(f"\n共 {len(res)} 项:通过 {len(res) - len(bad) - len(warn)},提醒 {len(warn)},缺失 {len(bad)}。")
    if bad:
        print("先处理标 ❌ 的项:[AI] 的直接运行命令,[用户] 的告诉用户怎么做并等待。")
sys.exit(1 if any(not r["通过"] and r["级别"] == "❌" for r in res) else 0)
