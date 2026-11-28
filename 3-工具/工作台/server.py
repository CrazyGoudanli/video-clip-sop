#!/usr/bin/env python3
"""本地网页工作台:看待办、看复盘、挑切片、看片、选封面、授权发布、看数据。

用法(在项目根目录):
  python3 3-工具/工作台/server.py            启动并自动打开浏览器(默认端口 8765)
  python3 3-工具/工作台/server.py --port 9000 --no-open

安全:
  - 只监听本机 127.0.0.1,别的电脑访问不到。
  - 只读项目文件夹里的文件;写操作只走 3-工具/db.py(状态规则、人工关卡、留痕都由它把关)。
  - 工作台里点的按钮,一律记为 --by 人工,备注"工作台"。
只用 Python 标准库。
"""
import argparse, base64, hashlib, json, mimetypes, os, re, shutil, sqlite3, subprocess, sys, threading, time, webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote, quote

os.environ["PATH"] = os.pathsep.join([str(Path.home() / ".local/bin"), "/opt/homebrew/bin", "/usr/local/bin", os.environ.get("PATH", "")])

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DBPY = ROOT / "3-工具" / "db.py"
sys.path.insert(0, str(ROOT / "3-工具"))
import db  # noqa: E402

IMG_EXT = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv"}
SEC = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2}(?:\.\d+)?)$")


# ---------------- 读 ----------------
def rows(c, sql, *a):
    return [dict(r) for r in c.execute(sql, a)]


def rel(p):
    """项目内路径 → 相对路径字符串;项目外或不存在返回 None。"""
    if not p:
        return None
    q = Path(os.path.expanduser(p))
    q = q if q.is_absolute() else ROOT / q
    try:
        q.resolve().relative_to(ROOT.resolve())
    except ValueError:
        try:
            q.relative_to(ROOT)          # 链接本身在项目内也行(指向 待加工/已处理)
        except ValueError:
            return None
    return str(q.relative_to(ROOT)) if q.exists() else None


def secs(t):
    m = SEC.match(t or "")
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else None


def source_files(sid):
    d = ROOT / "工作区" / sid
    out = {"视频": [], "文档": []}
    if (d / "转录文件").is_dir():
        out["视频"] = sorted(str(p.relative_to(ROOT)) for p in (d / "转录文件").iterdir() if p.suffix.lower() in VIDEO_EXT)
    if (d / "复盘").is_dir():
        out["文档"] = sorted(str(p.relative_to(ROOT)) for p in (d / "复盘").glob("*.md"))
    return out


def cover_candidates(folder):
    if not folder:
        return []
    d = ROOT / folder / "封面" / "候选"
    if not d.is_dir():
        return []
    return sorted(str(p.relative_to(ROOT)) for p in d.iterdir() if p.suffix.lower() in IMG_EXT)


def _cover_dir(folder, sub):
    if not folder:
        return None
    d = ROOT / os.path.expanduser(folder) / "封面" / sub
    try:
        d.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return None
    return d


def cover_refs(folder):
    d = _cover_dir(folder, "参考")
    return sorted(str(p.relative_to(ROOT)) for p in d.iterdir() if p.suffix.lower() in IMG_EXT) if d and d.is_dir() else []


def cover_notes(folder):
    d = _cover_dir(folder, "")
    f = d / "要求.md" if d else None
    return f.read_text()[-2000:] if f and f.exists() else ""


def cover_progress(folder):
    d = _cover_dir(folder, "")
    f = d / "进度.txt" if d else None
    if not f or not f.exists() or time.time() - f.stat().st_mtime > 3 * 3600:
        return []
    return [l.strip() for l in f.read_text(errors="ignore").splitlines() if l.strip()][:6]


def cover_rounds(folder):
    d = _cover_dir(folder, "历史")
    return len([p for p in d.iterdir() if p.is_dir()]) if d and d.is_dir() else 0


FOLDERS = [  # (键, 显示名, 相对路径, 说明)
    ("待加工", "待加工", "待加工", "把要处理的长录像放这里(课程、直播、访谈都行),AI 会自动整理"),
    ("成片", "成片", "成片", "剪好的视频:每条一个文件夹,里面有视频、字幕、文案、封面"),
    ("参考封面", "参考封面", "参考/封面", "放你喜欢的封面截图,AI 会学它的风格"),
    ("参考视频", "参考视频", "参考/视频风格", "放你喜欢的短视频,AI 会学它的节奏和包装"),
    ("学习", "学习", "学习", "AI 从参考里总结的风格档案,你确认后才生效"),
]


def folder_info():
    out = []
    for key, name, relp, note in FOLDERS:
        d = ROOT / relp
        items = [p for p in d.iterdir() if not p.name.startswith(".") and p.name != "README.md"] if d.is_dir() else []
        if key == "待加工":
            items = [p for p in items if p.is_file() and p.suffix.lower() in VIDEO_EXT]
        out.append({"键": key, "名称": name, "路径": str(d), "说明": note, "数量": len(items),
                    "示例": [p.name for p in sorted(items, key=lambda x: -x.stat().st_mtime)[:3]]})
    return out


def last_line(note):
    ls = [l for l in (note or "").splitlines() if l.strip()]
    return ls[-1] if ls else ""


def before_help(c, kind, oid):
    """'需人工'之前是什么状态(决定卡片留在哪一列、"重试"回到哪)。"""
    r = c.execute("select 旧值 from events where 对象=? and 对象ID=? and 新值='需人工' and 动作 in ('改状态','看片打回') "
                  "order by id desc limit 1", (kind, oid)).fetchone()
    return r[0] if r else None


def watch_state():
    try:
        st = json.loads((ROOT / "data" / ".watch_state.json").read_text())
    except Exception:
        return {}
    out = {}
    for stage, m in (st.get("失败时间") or {}).items():
        m = m if isinstance(m, dict) else {"*": m}
        for o, t in m.items():
            if time.time() - t < 3600:
                out.setdefault(o, {})["冷却"] = {"环节": stage, "重试时间": time.strftime("%H:%M", time.localtime(t + 3600))}
    for o, r in (st.get("最近结果") or {}).items():
        out.setdefault(o, {})["最近结果"] = {**r, "时间": time.strftime("%m-%d %H:%M", time.localtime(r.get("时间", 0)))}
    return out


_PROBE_CACHE = {}


def _probe_video(p):
    """快速读取视频时长与分辨率并做内存缓存,供工作台卡片显示封面与规格。"""
    try:
        st = p.stat()
    except OSError:
        return {"时长秒": 0, "分辨率": ""}
    key = (str(p), st.st_size, int(st.st_mtime))
    if key in _PROBE_CACHE:
        return _PROBE_CACHE[key]
    meta = {"时长秒": 0, "分辨率": ""}
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-show_entries", "stream=codec_type,width,height", "-of", "json", str(p)],
            capture_output=True, text=True, timeout=8
        )
        if r.returncode == 0:
            d = json.loads(r.stdout or "{}")
            dur = float((d.get("format") or {}).get("duration") or 0)
            v = next((s for s in (d.get("streams") or []) if s.get("codec_type") == "video"), {})
            w, h = v.get("width"), v.get("height")
            meta = {"时长秒": round(dur), "分辨率": f"{w}×{h}" if w and h else ""}
    except Exception:
        pass
    _PROBE_CACHE[key] = meta
    return meta


def inbox_files():
    """待加工根目录里还没整理的录像:录制/拷贝中、排队、整理中,附带缩略图与视频规格。"""
    inbox = db.folder("待加工目录", "待加工")
    lock = ROOT / "data" / ".watch.lock"
    busy = []
    if lock.exists():
        try:
            info = json.loads(lock.read_text().splitlines()[1])
            if info.get("环节") == "0-整理":
                busy = info.get("对象", [])
        except (IndexError, ValueError):
            pass
    out = []
    if inbox.is_dir():
        for f in sorted(inbox.iterdir()):
            if f.is_file() and not f.name.startswith(".") and f.suffix.lower() in VIDEO_EXT:
                st = f.stat()
                age = time.time() - st.st_mtime
                rel_p = rel(str(f)) or f"待加工/{f.name}"
                meta = _probe_video(f)
                dur = meta["时长秒"]
                at = round(min(3.0, max(0.5, dur * 0.08)), 1) if dur > 1 else 0
                out.append({
                    "文件": f.name,
                    "路径": rel_p,
                    "大小MB": round(st.st_size / 1e6, 1) if st.st_size < 10_000_000 else round(st.st_size / 1e6),
                    "时长秒": dur,
                    "分辨率": meta["分辨率"],
                    "缩略图": f"/thumb?path={quote(rel_p)}&at={at}",
                    "状态": "整理中" if f.name in busy else ("还在写入" if age < 600 else "排队"),
                    "可开始秒": max(0, int(600 - age)),
                })
    return out


def state():
    c = db.conn()
    todo = db.pending(c)
    ws = watch_state()
    ov = db.overlaps(c)
    sources = rows(c, "select * from sources order by 日期 desc, source_id desc")
    for s in sources:
        s["文件"] = source_files(s["source_id"])
        v0 = (s["文件"]["视频"] or [None])[0]
        s["缩略图"] = f"/thumb?path={quote(v0)}&at=3" if v0 else None
        s["原因"] = last_line(s.get("备注"))
        s["之前"] = before_help(c, "source", s["source_id"]) if s["状态"] == "需人工" else None
        s["监测"] = ws.get(s["source_id"])
    clips = rows(c, "select * from clips order by source_id desc, clip_id")
    for k in clips:
        files = source_files(k["source_id"])["视频"]
        want = re.search(r"来源文件[::]\s*([^\s;;,,]+)", k.get("理由") or "")
        src = next((f for f in files if want and want[1] in f), files[0] if files else None)
        s0 = secs(k["起始"])
        k["预览"] = {"文件": src, "起": s0, "止": secs(k["结束"])}
        k["成片"] = rel(k.get("成片文件"))
        if k["成片"]:
            k["视频缩略图"] = f"/thumb?path={quote(k['成片'])}&at=2"
        elif src:
            k["视频缩略图"] = f"/thumb?path={quote(src)}&at={round((s0 or 0) + 2, 1)}"
        else:
            k["视频缩略图"] = None
        k["封面候选"] = cover_candidates(k.get("本地文件夹"))
        k["封面参考"] = cover_refs(k.get("本地文件夹"))
        k["封面要求"] = cover_notes(k.get("本地文件夹"))
        k["封面重做"] = cover_rounds(k.get("本地文件夹"))
        k["封面进度"] = cover_progress(k.get("本地文件夹"))
        k["重叠"] = ov.get(k["clip_id"], [])
        k["原因"] = last_line(k.get("备注"))
        k["之前"] = before_help(c, "clip", k["clip_id"]) if k["状态"] == "需人工" else None
        k["监测"] = ws.get(k["clip_id"])
    pubs = rows(c, "select * from publishes order by 更新时间 desc")
    met = {}
    for m in rows(c, "select * from metrics"):
        met.setdefault(m["publish_id"], {})[m["时间档"]] = m
    for p in pubs:
        p["封面竖文件"], p["封面横文件"] = rel(p.get("封面竖")), rel(p.get("封面横"))
        try:
            p["候选标题列表"] = json.loads(p.get("候选标题") or "[]")
        except ValueError:
            p["候选标题列表"] = []
        p["数据"] = met.get(p["publish_id"], {})
        p["后台链接"] = p.get("后台链接") or db.ADMIN_URL.get(p["平台"])
        p["登录链接"] = db.LOGIN_URL.get(p["平台"])
        p["原因"] = last_line(p.get("备注"))
        p["之前"] = before_help(c, "pub", p["publish_id"]) if p["状态"] == "需人工" else None
        p["监测"] = ws.get(p["publish_id"])
    events = rows(c, "select * from events order by id desc limit 30")
    groups = {}
    for dim in ("标题句式", "封面类型", "选题类型", "钩子类型"):
        groups[dim] = rows(c, f"select coalesce({dim},'未标注') 分组, count(*) 条数, round(avg(播放)) 平均播放, "
                              f"round(avg(完播率),4) 平均完播率, round(avg(涨粉),1) 平均涨粉 from v_performance "
                              f"where 时间档 in ('72h','7d') group by 1 order by 平均播放 desc")
    pref = prefs(c)
    c.close()
    return {"文件夹": folder_info(), "项目路径": str(ROOT), "待办": todo, "素材": sources, "切片": clips, "发布": pubs, "最近操作": events, "分组": groups,
            "收件": inbox_files(), "偏好": pref,
            "配置": {k: db.CFG.get(k) for k in ("发布平台", "成片时长", "驱动AI", "剪辑工具", "自动执行", "封面图形风格", "发布排期", "AI代审", "重剪上限")},
            "可选设置": settings_options(), "自动处理": auto_status()}


# ---------------- 我的偏好 ----------------
def prefs(c):
    try:
        ds = rows(c, "select * from decisions order by id desc limit 500")
    except sqlite3.OperationalError:
        ds = []
    gates = {}
    tags = {}
    for d in ds:
        g = gates.setdefault(d["关卡"], {"次数": 0, "采纳": 0, "否定": 0})
        g["次数"] += 1
        g["采纳"] += 1 if d["采纳"] else 0
        g["否定"] += 1 if d["否定"] else 0
        for t in (d["标签"] or "").replace(",", ",").split(","):
            if t.strip():
                tags.setdefault(d["关卡"], {}).setdefault(t.strip(), 0)
                tags[d["关卡"]][t.strip()] += 1
    # 挑片段:按选题类型/钩子类型/优先级看你选中的比例(只算已经挑过的)
    pick = {}
    for dim in ("选题类型", "钩子类型", "优先级"):
        pick[dim] = rows(c, f"select coalesce({dim},'未标注') 分组, count(*) 条数, "
                            f"sum(case when 状态 not in ('候选','放弃') then 1 else 0 end) 选中 "
                            f"from clips where 状态!='候选' group by 1 order by 条数 desc")
    hi = rows(c, "select count(*) n, sum(case when 状态 not in ('候选','放弃') then 1 else 0 end) y from clips "
                 "where 状态!='候选' and 优先级='高'")[0]
    props = []
    for d in (ROOT / "学习" / "提案", ROOT / "data" / "数据复盘"):
        if d.is_dir():
            props += [str(p.relative_to(ROOT)) for p in sorted(d.glob("*.md"), key=lambda x: -x.stat().st_mtime)[:10]]
    return {"关卡": gates, "标签": tags, "挑片": pick, "高优先级": hi, "最近": ds[:30], "提案": props,
            "偏好文件": "学习/我的偏好.md" if (ROOT / "学习" / "我的偏好.md").exists() else None}


PREF_MARK = "<!-- 以下是你自己写的偏好:工作台不会覆盖,AI 会一起读 -->"


def write_pref_file():
    """短期偏好:把最近的采纳/否定例子写进 学习/我的偏好.md,下一次 AI 生成时照着来。不改标准。"""
    c = db.conn()
    try:
        ds = rows(c, "select * from decisions order by id desc limit 60")
    except sqlite3.OperationalError:
        ds = []
    title = {r["clip_id"]: r["标题"] for r in rows(c, "select clip_id,标题 from clips")}
    c.close()
    f = ROOT / "学习" / "我的偏好.md"
    f.parent.mkdir(exist_ok=True)
    mine = f.read_text().split(PREF_MARK, 1)[1] if f.exists() and PREF_MARK in f.read_text() else "\n(在这里写,例如:不想露脸的片段别选;标题别用感叹号)\n"
    name = lambda i: f"{i}《{title.get(i.split('@')[0], '')}》" if title.get(i.split("@")[0]) else i
    out = ["# 我的偏好(工作台自动整理,最近 60 次决定)", "",
           "> AI 做挑片段、剪辑、文案、封面前先读这份:照着用户最近的采纳/否定来。这里只是例子,不是标准;",
           "> 同一规律反复出现,才在「8-偏好复盘」里提标准修改提案,用户同意后才改 2-标准/。", ""]
    for g in db.GATE_NAMES:
        items = [d for d in ds if d["关卡"] == g][:15]
        if not items:
            continue
        out.append(f"## {g}")
        for d in items:
            bits = []
            if d["采纳"]:
                bits.append("✅ 采纳 " + "、".join(name(x) for x in d["采纳"].split("|")))
            if d["否定"]:
                bits.append("❌ 否定 " + "、".join(name(x) for x in d["否定"].split("|")))
            if d["标签"]:
                bits.append("标签:" + d["标签"])
            if d["备注"]:
                bits.append("备注:" + d["备注"].replace("\n", " ")[:200])
            out.append(f"- {d['时间'][5:16].replace('T', ' ')} " + ";".join(bits))
        out.append("")
    f.write_text("\n".join(out) + "\n" + PREF_MARK + mine)


def decide(gate, oid, adopt="", reject="", tags="", note="", files=""):
    ok, out = run_db("decide", "--关卡", gate, "--对象", oid, "--采纳", adopt, "--否定", reject, "--标签", tags,
                     "--备注", note, "--附件", files, "--by", "人工")
    if ok:
        try:
            write_pref_file()
        except Exception:
            pass
    return ok


def clear_cooldown(ids):
    """用户在工作台处理过这些对象:让监测脚本下一轮立即可以重试,并马上检查一次。"""
    ids = [i for i in ids if i]
    if not ids:
        return
    f = ROOT / "data" / ".watch_clear.json"
    try:
        have = json.loads(f.read_text()).get("对象", [])
    except Exception:
        have = []
    f.write_text(json.dumps({"对象": sorted(set(have) | set(ids))}, ensure_ascii=False))
    kick()


_last_kick = [0.0]


def kick(manual=False):
    """自动处理开着时(或用户在工作台点'立即运行'时),马上跑一次检查。已有任务在跑就什么也不做。"""
    if not manual and (not db.CFG.get("自动执行") or os.environ.get("SOP_NO_KICK") or time.time() - _last_kick[0] < 30):
        return False, "未满足自动触发条件"
    lock = ROOT / "data" / ".watch.lock"
    if lock.exists() and time.time() - lock.stat().st_mtime < 4 * 3600:
        alive = True
        try:
            m = re.search(r"pid=(\d+)", lock.read_text(errors="ignore"))
            if m:
                os.kill(int(m.group(1)), 0)
        except ProcessLookupError:
            alive = False
            lock.unlink(missing_ok=True)
        except Exception:
            pass
        if alive:
            return False, "当前已有 AI 任务正在运行中"
    _last_kick[0] = time.time()
    log = ROOT / "data" / "运行日志" / "autorun.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(ROOT / "3-工具" / "watch.py"), "--once"] + (["--manual"] if manual else [])
    subprocess.Popen(cmd, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=open(log, "a"), stderr=subprocess.STDOUT, start_new_session=True)
    return True, "已启动本机 AI 执行下一步"


def run_now():
    """工作台点击'立即运行 AI':对刚放进待加工且未被程序占用的视频解除 10 分钟静默等待,并立刻拉起 watch.py --once --manual。"""
    inbox = db.folder("待加工目录", "待加工")
    lsof = shutil.which("lsof") or ("/usr/sbin/lsof" if os.path.exists("/usr/sbin/lsof") else None)
    if inbox.is_dir():
        for f in inbox.iterdir():
            if f.is_file() and not f.name.startswith(".") and f.suffix.lower() in VIDEO_EXT:
                if time.time() - f.stat().st_mtime < 600:
                    in_use = False
                    if lsof:
                        r = subprocess.run([lsof, "--", str(f)], capture_output=True, text=True)
                        in_use = (r.returncode == 0 and bool(r.stdout.strip()))
                    if not in_use:
                        t = time.time() - 605
                        os.utime(f, (t, t))
    return kick(manual=True)


# ---------------- 写:只通过 db.py ----------------
CLIP_STATES = {"待剪", "放弃", "候选"}
PUB_STATES = {"待发布", "已废弃", "草稿"}
PUB_FIELDS = {"标题", "简介", "标签", "选用"}
ID_RE = re.compile(r"^[^\s/\\]{3,80}$")


def remove_inbox(a):
    """把误拖入待加工的视频移到 待加工/已移出/(遵守绝不删除原始录像红线)。"""
    name = Path(str(a.get("文件") or "")).name
    inbox = db.folder("待加工目录", "待加工")
    src = inbox / name
    if not name or not src.is_file() or src.suffix.lower() not in VIDEO_EXT:
        return False, "找不到该待加工视频"
    out_dir = inbox / "已移出"
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / f"{time.strftime('%m%d-%H%M%S')}_{name}"
    os.rename(src, dst)
    return True, f"已移出队列(原文件保留在 待加工/已移出/{dst.name})"


def paste_clipboard_video(a):
    """支持用户在访达 Command+C 复制视频文件后,在工作台直接 Command+V 秒级导入本地 待加工/ 目录。"""
    raw = str(a.get("路径") or "").strip()
    paths = []
    if raw:
        for line in raw.splitlines():
            p = line.strip().strip('"').strip("'")
            if p.startswith("file://"):
                p = unquote(urlparse(p).path)
            if p:
                paths.append(Path(os.path.expanduser(p)))
    else:
        # 从 macOS 剪贴板读取访达复制的文件 URL(支持单文件或多文件)
        script = (
            'try\n'
            '  set p to POSIX path of (the clipboard as «class furl»)\n'
            '  return p\n'
            'on error\n'
            '  try\n'
            '    return (the clipboard as text)\n'
            '  on error\n'
            '    return ""\n'
            '  end try\n'
            'end try'
        )
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5)
        for line in (r.stdout or "").splitlines():
            p = line.strip().strip('"').strip("'")
            if p.startswith("file://"):
                p = unquote(urlparse(p).path)
            if p:
                paths.append(Path(os.path.expanduser(p)))
    valid = [p for p in paths if p.is_file() and p.suffix.lower() in VIDEO_EXT]
    if not valid:
        return False, "剪贴板里没有检测到 mp4 / mov / mkv / m4v 视频文件（请先在访达里复制视频文件再按 ⌘V）"
    inbox = db.folder("待加工目录", "待加工")
    inbox.mkdir(parents=True, exist_ok=True)
    added = []
    for src in valid:
        safe = re.sub(r"[^\w.\-\u4e00-\u9fff ]", "_", src.name).strip()
        dest = inbox / safe
        if dest.exists():
            dest = inbox / f"{dest.stem}_{time.strftime('%H%M%S')}{dest.suffix}"
        part = inbox / f".uploading_{dest.name}"
        try:
            shutil.copy2(src, part)
            os.rename(part, dest)
            t = time.time() - 605
            os.utime(dest, (t, t))
            added.append(dest.name)
        except Exception as e:
            part.unlink(missing_ok=True)
            return False, f"导入 {src.name} 失败:{e}"
    return True, f"已从剪贴板导入：{', '.join(added)}"


def run_db(*args):
    r = subprocess.run([sys.executable, "-I", str(DBPY), *args], cwd=ROOT, capture_output=True, text=True, timeout=60)
    out = (r.stdout + r.stderr).strip()
    return r.returncode == 0, out


def action(a):
    kind, oid = a.get("动作"), a.get("id", "")
    if kind == "打开":
        return open_path(a)
    if kind == "打开平台":
        return open_platform(a)
    if kind == "设置":
        return change_setting(a)
    if kind == "代审":
        return set_gate(a)
    if kind == "自动处理":
        return set_auto(bool(a.get("开启")))
    if kind == "立即执行":
        return run_now()
    if kind == "移出待加工":
        return remove_inbox(a)
    if kind == "粘贴剪贴板视频":
        return paste_clipboard_video(a)
    if kind == "批量切片状态":
        a = {**a, "动作": "挑片段", "items": [{"id": i} for i in (a.get("ids") or [])]}
        kind = "挑片段"
    if kind == "挑片段":
        return pick_clips(a)
    if kind == "其余不剪":
        return rest_off(a)
    if kind == "恢复":
        return resume(a)
    if kind == "删除记录":
        return delete_record(a)
    if kind == "现在重试":
        ids = [i for i in (a.get("对象") or []) if ID_RE.match(i)]
        clear_cooldown(ids)
        return True, "已解除等待,下一次检查就会重试"
    if kind == "封面重做":
        return cover_redo(a)
    if kind == "上传参考":
        return upload_ref(a)
    if not ID_RE.match(oid):
        return False, "ID 不合法"
    note = "工作台:" + (a.get("备注") or "").strip()
    if kind == "切片状态":
        if a.get("状态") not in CLIP_STATES:
            return False, "不支持的状态"
        if a["状态"] in ("待剪", "放弃") and clip_state(oid) == "候选":
            return pick_clips({**a, "items": [{"id": oid, "剪辑要求": a.get("剪辑要求", "")}]})
        ok, out = run_db("set", "clip", oid, a["状态"], "--by", "人工", "--note", note)
        clear_cooldown([oid])
        return ok, out
    if kind == "看片":
        res = a.get("结论")
        if res not in ("通过", "打回"):
            return False, "结论只能是通过或打回"
        tags = [t for t in (a.get("标签") or []) if isinstance(t, str)][:10]
        reason = (("【" + "、".join(tags) + "】") if tags else "") + (a.get("原因") or "").strip()
        args = ["review", oid, res, "--by", "人工", "--reviewer", "工作台"]
        if reason:
            args += ["--reason", reason]
        ok, out = run_db(*args)
        if ok:
            decide("看片", oid, oid if res == "通过" else "", oid if res == "打回" else "", ",".join(tags), (a.get("原因") or "").strip())
            clear_cooldown([oid])
        return ok, out
    if kind == "发布状态":
        if a.get("状态") not in PUB_STATES:
            return False, "不支持的状态"
        ok, out = run_db("set", "pub", oid, a["状态"], "--by", "人工", "--note", note)
        if ok and a["状态"] in ("待发布", "已废弃"):
            decide("确认发布", oid, oid if a["状态"] == "待发布" else "", oid if a["状态"] == "已废弃" else "",
                   "", pub_edit_note(oid))
        if ok:
            clear_cooldown([oid])
        return ok, out
    if kind == "改文案":
        pairs = [f"{k}={v}" for k, v in (a.get("字段") or {}).items() if k in PUB_FIELDS]
        if not pairs:
            return False, "没有可改的字段"
        return run_db("update", "pub", oid, *pairs, "--by", "人工")
    if kind == "选封面":
        return pick_cover(a, oid)
    if kind == "打开":
        return open_path(a)
    return False, "未知动作"


def clip_state(cid):
    c = db.conn()
    r = c.execute("select 状态 from clips where clip_id=?", (cid,)).fetchone()
    c.close()
    return r[0] if r else None


def clip_row(cid):
    c = db.conn()
    r = c.execute("select * from clips where clip_id=?", (cid,)).fetchone()
    pubs = rows(c, "select * from publishes where clip_id=?", cid)
    c.close()
    return (dict(r) if r else None), pubs


def pick_clips(a):
    """挑片段:剪/不剪,每条可带"给 AI 的剪辑要求";不剪可带原因标签。每条都记一条挑选决策。"""
    st = a.get("状态")
    if st not in ("待剪", "放弃"):
        return False, "状态只能是待剪或放弃"
    items = [x for x in (a.get("items") or []) if isinstance(x, dict) and ID_RE.match(str(x.get("id", "")))]
    if not items:
        return False, "没有选中的片段"
    tags = ",".join(t for t in (a.get("标签") or []) if isinstance(t, str))
    outs, ok = [], True
    for it in items:
        cid, req = it["id"], (it.get("剪辑要求") or "").strip()[:1000]
        if st == "待剪" and req:
            o, t = run_db("update", "clip", cid, f"剪辑要求={req}", "--by", "人工")
            ok &= o
            outs.append(t)
        o, t = run_db("set", "clip", cid, st, "--by", "人工", "--note", "工作台:" + ("剪辑要求:" + req if req else (a.get("备注") or "挑选")))
        ok &= o
        outs.append(t)
        if o:
            decide("挑选", cid, cid if st == "待剪" else "", cid if st == "放弃" else "", tags, req or (a.get("备注") or ""))
    clear_cooldown([x["id"] for x in items])
    return ok, "\n".join(outs)


def rest_off(a):
    """这一场录像挑完了:没勾的候选明确记为"不剪(未选)",以后分析偏好时能分清"不要"和"还没看"。"""
    sid = a.get("source_id", "")
    if not ID_RE.match(sid):
        return False, "素材 ID 不合法"
    c = db.conn()
    ids = [r[0] for r in c.execute("select clip_id from clips where source_id=? and 状态='候选'", (sid,))]
    c.close()
    if not ids:
        return True, "这场录像没有剩下的候选"
    return pick_clips({"状态": "放弃", "items": [{"id": i} for i in ids], "标签": ["未选"], "备注": "挑选完成时没勾(未选)"})


RESUME = {  # (对象, 当前状态) -> 允许的去向 {目标状态: 按钮说明}
    ("source", "需人工"): {"待整理": "重新整理", "已整理": "重新转写复盘", "已复盘": "我处理好了(复盘已写好)"},
    ("clip", "需人工"): {"待剪": "让 AI 重剪", "已剪辑": "我处理好了,去看片", "候选": "退回候选", "放弃": "不剪了"},
    ("pub", "需人工"): {"待发布": "让 AI 重试发布", "已定时": "我已在平台设好定时", "已发布": "已经发出去了",
                     "草稿": "退回草稿", "已废弃": "这个平台不发了"},
}


def resume(a):
    k, oid, to = a.get("对象"), a.get("id", ""), a.get("状态")
    cur = {"source": "sources", "clip": "clips", "pub": "publishes"}.get(k)
    if not cur or not ID_RE.match(oid):
        return False, "参数不对"
    key = {"source": "source_id", "clip": "clip_id", "pub": "publish_id"}[k]
    c = db.conn()
    r = c.execute(f"select 状态 from {cur} where {key}=?", (oid,)).fetchone()
    c.close()
    if not r:
        return False, "找不到记录"
    allowed = RESUME.get((k, r[0]), {})
    if to not in allowed:
        return False, f"现在是「{r[0]}」,不能直接改成「{to}」"
    ok, out = run_db("set", k, oid, to, "--by", "人工", "--note", "工作台:" + allowed[to] + ((":" + a["备注"]) if a.get("备注") else ""))
    if ok:
        clear_cooldown([oid])
    return ok, out


def delete_record(a):
    k, oid = a.get("对象"), a.get("id", "")
    if k not in ("source", "clip", "pub") or not ID_RE.match(oid):
        return False, "参数不对"
    note = "工作台:" + ((a.get("备注") or "").strip() or "人工移除不合格或不需要的记录")
    ok, out = run_db("delete", k, oid, "--by", "人工", "--note", note)
    if ok:
        clear_cooldown([oid])
    return ok, out


def pub_edit_note(pid):
    """确认发布时,标题和 AI 推荐的有没有不同(改动本身是最强的偏好信号)。"""
    c = db.conn()
    r = c.execute("select 标题,推荐,候选标题 from publishes where publish_id=?", (pid,)).fetchone()
    c.close()
    if not r:
        return ""
    try:
        cands = {x.split("|")[0]: x.split("|")[-1] for x in json.loads(r["候选标题"] or "[]")}
    except ValueError:
        cands = {}
    rec = cands.get(r["推荐"] or "")
    if rec and rec != r["标题"]:
        used = next((k for k, v in cands.items() if v == r["标题"]), None)
        return f"标题没用推荐:推荐「{rec}」→ 用了" + (f"候选 {used}" if used else "自己改的") + f"「{r['标题']}」"
    return ""


def pick_cover(a, oid):
    """选封面:同一条视频的所有平台草稿一起用这张竖版;可带备注(出横版时照着微调)。"""
    p = rel(a.get("文件"))
    if not p or Path(p).suffix.lower() not in IMG_EXT or "/封面/候选/" not in "/" + p:
        return False, "只能选 封面/候选/ 里的图片"
    c = db.conn()
    r = c.execute("select clip_id from publishes where publish_id=?", (oid,)).fetchone() if "@" in oid else None
    cid = r[0] if r else oid
    targets = [x[0] for x in c.execute("select publish_id from publishes where clip_id=? and 状态='草稿' "
                                       "and coalesce(封面竖,'')=''", (cid,))] or ([oid] if "@" in oid else [])
    k = c.execute("select 本地文件夹 from clips where clip_id=?", (cid,)).fetchone()
    c.close()
    if not targets:
        return False, "这条视频没有等选封面的草稿"
    note = (a.get("备注") or "").strip()[:1000]
    outs, ok = [], True
    for pid in targets:
        o, t = run_db("update", "pub", pid, f"封面竖={p}", "封面横=", f"备注=工作台选定封面 {Path(p).name}" + (f";要求:{note}" if note else ""), "--by", "人工")
        ok &= o
        outs.append(t)
    others = [x for x in cover_candidates(k[0] if k else None) if x != p]
    if note and k:
        add_cover_note(k[0], f"选了 {Path(p).name},出横版时照这个改:{note}")
    decide("选封面", cid, p, "|".join(others), ",".join(a.get("标签") or []), note)
    clear_cooldown([cid, *targets])
    return ok, "\n".join(outs)


def add_cover_note(folder, text):
    d = _cover_dir(folder, "")
    if not d:
        return
    d.mkdir(parents=True, exist_ok=True)
    f = d / "要求.md"
    head = "" if f.exists() else "# 你对这条封面的要求(AI 做封面前先读)\n\n"
    with open(f, "a") as fh:
        fh.write(head + f"- {time.strftime('%m-%d %H:%M')} {text}\n")


def cover_redo(a):
    """都不满意:按备注/参考图重做三张候选。旧候选挪到 封面/历史/第N轮/(不删)。"""
    cid = a.get("id", "")
    k, pubs = clip_row(cid)
    if not k or not k.get("本地文件夹"):
        return False, "找不到这条视频的文件夹"
    note = (a.get("备注") or "").strip()[:1000]
    refs = cover_refs(k["本地文件夹"])
    if not note and not refs:
        return False, "写一下想怎么改,或者先上传一张参考图"
    cand = _cover_dir(k["本地文件夹"], "候选")
    old = cover_candidates(k["本地文件夹"])
    n = cover_rounds(k["本地文件夹"]) + 1
    if cand and cand.is_dir():
        hist = _cover_dir(k["本地文件夹"], "历史") / f"第{n}轮"
        hist.mkdir(parents=True, exist_ok=True)
        for f in cand.iterdir():
            if f.is_file():
                shutil.move(str(f), str(hist / f.name))
    add_cover_note(k["本地文件夹"], f"第 {n} 次重做三张候选:" + (note or "按参考图的风格") +
                   (f"(参考图:{', '.join(Path(r).name for r in refs)})" if refs else ""))
    decide("选封面", cid, "", "|".join(old), ",".join(a.get("标签") or []), note, "|".join(refs))
    clear_cooldown([cid, *[p["publish_id"] for p in pubs]])
    return True, f"已送回 AI 重做(第 {n} 次),旧候选放在 封面/历史/第{n}轮/"


def upload_ref(a):
    """上传参考图:存到 <成片文件夹>/封面/参考/;勾了"以后都学这个"再复制一份到全局 参考/封面/。"""
    cid = a.get("id", "")
    k, _ = clip_row(cid)
    if not k or not k.get("本地文件夹"):
        return False, "找不到这条视频的文件夹"
    name = re.sub(r"[^\w.\-\u4e00-\u9fff]", "_", Path(a.get("文件名") or "参考.png").name)[-60:]
    if Path(name).suffix.lower() not in IMG_EXT:
        return False, "只支持 png / jpg / webp 图片"
    try:
        data = base64.b64decode((a.get("数据") or "").split(",")[-1], validate=True)
    except ValueError:
        return False, "图片数据不对"
    if not data or len(data) > 10_000_000:
        return False, "图片不能超过 10 MB"
    d = _cover_dir(k["本地文件夹"], "参考")
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{time.strftime('%m%d-%H%M%S')}_{name}"
    f.write_bytes(data)
    msg = f"已上传参考图:{f.name}"
    if a.get("全局"):
        g = ROOT / "参考" / "封面"
        g.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, g / f.name)
        msg += ",也放进了全局「参考/封面」"
    return True, msg


# 左下角设置:只允许改这几项,值只能从列表里选
SETTINGS = {
    "驱动AI": {"Claude Code": {"驱动命令": "zsh 3-工具/脚本/run_claude.sh {prompt}"},
               "Codex": {"驱动命令": "zsh 3-工具/脚本/run_codex.sh {prompt}"},
               "Cursor CLI": {"驱动命令": "zsh 3-工具/脚本/run_cursor.sh {prompt}"},
               "Pi": {"驱动命令": "zsh 3-工具/脚本/run_pi.sh {prompt}"}},
    "剪辑工具": {"ChatCut": {}, "ffmpeg": {}},
}


def settings_options():
    import shutil
    os.environ["PATH"] = os.pathsep.join([str(Path.home() / ".local/bin"), "/opt/homebrew/bin", os.environ.get("PATH", "")])
    have = {"Claude Code": bool(shutil.which("claude")), "Codex": bool(shutil.which("codex")),
            "Cursor CLI": bool(shutil.which("cursor-agent") or shutil.which("agent")), "Pi": bool(shutil.which("pi")),
            "ChatCut": Path("/Applications/ChatCut.app").exists(), "ffmpeg": bool(shutil.which("ffmpeg"))}
    note = {"Claude Code": "推荐", "Codex": "", "Cursor CLI": "用 Cursor 账号额度", "Pi": "开源,自带模型账号;看不到逐步过程", "ChatCut": "有标题栏、金句卡等动效包装", "ffmpeg": "免费,只做基础剪辑和字幕"}
    return {k: [{"值": v, "已安装": have.get(v, True), "说明": note.get(v, "")} for v in opts] for k, opts in SETTINGS.items()}


def change_setting(a):
    key, val = a.get("项"), a.get("值")
    if key not in SETTINGS or val not in SETTINGS[key]:
        return False, "不支持的设置"
    cfg_path = ROOT / "配置.json"
    if not cfg_path.exists():
        return False, "还没有 配置.json,先让 AI 按启动问卷生成"
    cfg = json.loads(cfg_path.read_text())
    old = cfg.get(key)
    cfg[key] = val
    cfg.update(SETTINGS[key][val])
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=1) + "\n")
    db.CFG.clear()
    db.CFG.update(cfg)
    extra = "(只对之后新剪的视频生效)" if key == "剪辑工具" else "(下次启动 AI 时生效)"
    return True, f"{key}:{old} → {val} {extra}"


AUTORUN = ROOT / "3-工具" / "脚本" / "autorun.sh"


def auto_status():
    """自动处理开关的实际状态:由工作台内置巡检线程或系统定时任务驱动。"""
    on = bool(db.CFG.get("自动执行"))
    lock = ROOT / "data" / ".watch.lock"
    busy = lock.read_text().split(" ")[0] if lock.exists() else ""
    logs = sorted((ROOT / "data" / "运行日志").glob("*.log"), key=lambda p: p.stat().st_mtime) if (ROOT / "data" / "运行日志").is_dir() else []
    last = [p for p in logs if p.name != "autorun.log"]
    return {"开启": on, "配置": on, "定时任务": on, "间隔秒": db.CFG.get("监测间隔秒", 300),
            "正在做": busy, "最近一次": last[-1].name if last else ""}


STAGE_NAME = {"8-偏好复盘": "总结你的偏好", "0-整理": "整理录像", "1-复盘选片": "转写、复盘、挑片段", "2-剪辑": "剪辑成片", "4-文案": "写标题文案",
              "5-封面": "做封面", "6-发布": "在平台设定时发布", "7-数据复盘": "看数据、回填链接",
              "代审-挑选": "代你挑片段", "代审-看片": "代你看成片", "代审-选封面": "代你选封面", "代审-发布": "代你确认发布"}


def _tail_lines(path, n=400_000):
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - n))
        return f.read().decode("utf-8", "ignore").splitlines()


def _steps(logf, k=6):
    """从 AI 的运行日志里挑最近几步,翻成人话。兼容 Claude Code / Codex 的 JSON 流。"""
    out = []
    for ln in _tail_lines(logf):
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        if d.get("type") == "assistant":                      # Claude Code
            for c in d.get("message", {}).get("content", []):
                if c.get("type") == "text" and c.get("text", "").strip():
                    out.append(("说", c["text"].strip()))
                elif c.get("type") == "tool_use":
                    inp = c.get("input") or {}
                    name = c.get("name", "").replace("mcp__chatcut_desktop__", "ChatCut·")
                    desc = inp.get("description") or inp.get("command") or inp.get("file_path") or ""
                    out.append(("做", f"{name} {desc}".strip()))
        if d.get("type") == "tool_call" and d.get("subtype") == "started":   # Cursor CLI
            tc = d.get("tool_call") or {}
            kind = next(iter(tc), "")
            args = (tc.get(kind) or {}).get("args") or {}
            if kind == "mcpToolCall":
                name = str(args.get("name", "")).replace("chatcut_desktop-", "ChatCut·")
                out.append(("做", name))
            elif kind != "getMcpToolsToolCall":
                desc = args.get("command") or args.get("path") or args.get("pattern") or ""
                out.append(("做", f"{kind.replace('ToolCall', '')} {desc}".strip()))
        item = d.get("item") if isinstance(d.get("item"), dict) else None   # Codex
        if item:
            if item.get("type") == "agent_message":
                out.append(("说", item.get("text", "")))
            elif item.get("type") == "command_execution":
                out.append(("做", item.get("command", "")))
    return [{"类型": t, "内容": re.sub(r"\s+", " ", x)[:160]} for t, x in out[-k:]]


def live():
    """左下角实时状态:AI 在不在干活、在做哪一步、最近几步、上次结果、下次检查时间。"""
    from datetime import datetime, timedelta
    lock = ROOT / "data" / ".watch.lock"
    logdir = ROOT / "data" / "运行日志"
    res = {"在干活": False, "开启": bool(db.CFG.get("自动执行")), "间隔秒": int(db.CFG.get("监测间隔秒", 300))}
    if lock.exists():
        lines = lock.read_text(errors="ignore").splitlines()
        info = {}
        if len(lines) > 1:
            try:
                info = json.loads(lines[1])
            except ValueError:
                pass
        stage = info.get("环节") or (lines[0].split(" ")[0] if lines else "")
        pid = info.get("pid") or (re.search(r"pid=(\d+)", lines[0] or "") or [None, None])[1]
        alive = True
        if pid:
            try:
                os.kill(int(pid), 0)
            except (OSError, ValueError):
                alive = False
        if alive:
            res.update(在干活=True, 环节=stage, 说明="本机转写(不用 AI)" if info.get("步骤") == "转写" else STAGE_NAME.get(stage, stage),
                       对象=info.get("对象", []), 开始=info.get("开始"))
            lf = logdir / info["日志"] if info.get("日志") else None
            if lf and lf.exists():
                res["最近几步"] = _steps(lf)
                res["日志"] = str(lf.relative_to(ROOT))
                # 同时读取纯文本/进度条最后一行(如本机转写下载进度或 Pi 输出),让前端动画条展示实时状态
                raw_tail = _tail_lines(lf, 12000)
                prog = ""
                for ln in reversed(raw_tail):
                    clean = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", ln.split("\r")[-1]).strip()
                    if clean and not clean.startswith("{") and len(clean) > 2:
                        prog = clean[:140]
                        break
                if prog:
                    res["实时进度"] = prog
    al = logdir / "autorun.log"
    if al.exists():
        rows = [l for l in _tail_lines(al, 20000) if l.startswith("[")]
        ends = [l for l in rows if " 结束" in l or "超过 3 小时" in l]
        if ends:
            m = re.match(r"\[(.+?)\] (\S+) (\S+) 结束\(返回码 (\d+)\):(.*)", ends[-1])
            res["上次"] = {"时间": m[1][5:16], "结果": m[2], "环节": STAGE_NAME.get(m[3], m[3]), "说明": m[5][:200]} if m \
                else {"说明": ends[-1][:200]}
        if rows:
            t0 = re.match(r"\[(.+?)\]", rows[-1])
            try:
                last = datetime.strptime(t0[1], "%Y-%m-%d %H:%M:%S")
                nxt = last + timedelta(seconds=res["间隔秒"])
                res["上次检查"] = last.strftime("%H:%M")
                res["下次检查秒"] = max(0, int((nxt - datetime.now()).total_seconds()))
            except (TypeError, ValueError):
                pass
            res["最近一句"] = re.sub(r"^\[.+?\] ", "", rows[-1])[:200]
    res["下一步"] = next_up()
    return res


def next_up():
    """监测脚本下一次会做什么(去掉冷却中的对象):给左下角和卡片写"下一步:谁、大约何时"。"""
    try:
        c = db.conn()
        todo = db.pending(c)
        c.close()
    except SystemExit:
        return None
    ws = watch_state()
    order = ["0-整理", "1-复盘选片", "代审-挑选", "2-剪辑", "代审-看片", "4-文案", "5-封面", "代审-选封面", "代审-发布",
             "6-发布", "7-数据复盘", "8-偏好复盘"]
    ai = sorted([x for x in todo if x["执行者"] == "AI"], key=lambda x: order.index(x["环节"]) if x["环节"] in order else 99)
    for x in ai:
        live = [i for i in x["对象"] if not (ws.get(i) or {}).get("冷却")]
        if live:
            return {"环节": x["环节"], "说明": STAGE_NAME.get(x["环节"], x["环节"]), "对象": live[:5], "共": len(live)}
    return None


def set_auto(on):
    cfg_path = ROOT / "配置.json"
    if not cfg_path.exists():
        return False, "还没有 配置.json,先让 AI 按启动问卷生成"
    cfg = json.loads(cfg_path.read_text())
    if on and not cfg.get("驱动命令"):
        return False, "还没设置驱动 AI,先在设置里选一个"
    cfg["自动执行"] = bool(on)
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=1) + "\n")
    db.CFG.clear()
    db.CFG.update(cfg)
    if on:
        kick()
    return True, ("自动巡检已开启:每 %s 秒自动检查一次,有活就让 AI 接着做" % cfg.get("监测间隔秒", 300)) if on else "自动巡检已关闭"


def set_gate(a):
    g, on = a.get("关卡"), bool(a.get("开启"))
    if g not in db.GATES:
        return False, "未知关卡"
    cfg_path = ROOT / "配置.json"
    if not cfg_path.exists():
        return False, "还没有 配置.json"
    cfg = json.loads(cfg_path.read_text())
    gates = {k: False for k in db.GATES}
    gates.update(cfg.get("AI代审") or {})
    gates[g] = on
    cfg["AI代审"] = gates
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=1) + "\n")
    db.CFG.clear()
    db.CFG.update(cfg)
    c = db.conn()
    db.log(c, "config", "AI代审", f"{'打开' if on else '关闭'} {g}", None, str(on), "人工", "工作台")
    c.commit()
    c.close()
    return True, f"AI 代审·{g} 已{'打开:之后这一步由 AI 替你决定' if on else '关闭:这一步回到由你决定'}"


def open_platform(a):
    """在发布用的浏览器里打开平台的登录页/作品管理页(登录态要留在 AI 发布用的那个浏览器里)。只认内置的网址。"""
    plat, which = a.get("平台"), a.get("页面")
    url = (db.LOGIN_URL if which == "登录" else db.ADMIN_URL).get(plat)
    if not url:
        return False, "未知平台"
    what = "登录页" if which == "登录" else "作品管理页"
    app = {"ego lite": "ego lite"}.get(db.CFG.get("发布浏览器") or "")
    if app and Path(f"/Applications/{app}.app").exists():
        subprocess.run(["open", "-a", app, url])
        return True, f"已在 {app} 里打开{plat}{what}"
    subprocess.run(["open", url])
    return True, f"已打开{plat}{what}"


def open_path(a):
    """在访达里打开项目内的文件夹,或在访达里选中某个文件。只认项目里的路径。"""
    key = a.get("文件夹")
    if key:
        hit = next((f for f in FOLDERS if f[0] == key), None)
        if not hit:
            return False, "未知文件夹"
        d = ROOT / hit[2]
        d.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(d)])
        return True, f"已在访达打开:{hit[1]}"
    p = rel(a.get("路径"))
    if not p:
        return False, "路径不在项目里或不存在"
    full = ROOT / p
    subprocess.run(["open", str(full)] if full.is_dir() else ["open", "-R", str(full)])
    return True, "已在访达打开"


# ---------------- HTTP ----------------
class H(BaseHTTPRequestHandler):
    server_version = "SOP-Workbench"

    def log_message(self, *a):
        pass

    def _ok_host(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._ok_host():
            return self._send(403, {"错误": "只允许本机访问"})
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path in ("/", "/index.html"):
                return self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
            if u.path == "/api/live":
                return self._send(200, live())
            if u.path == "/api/state":
                return self._send(200, state())
            if u.path == "/file":
                return self._file(unquote(q.get("path", [""])[0]))
            if u.path == "/thumb":
                return self._thumb(unquote(q.get("path", [""])[0]), (q.get("at") or ["1"])[0])
        except SystemExit:
            return self._send(500, {"错误": "数据库不可用,先运行 python3 3-工具/db.py init"})
        except Exception as e:
            return self._send(500, {"错误": str(e)})
        self._send(404, {"错误": "没有这个页面"})

    def do_POST(self):
        if not self._ok_host():
            return self._send(403, {"错误": "只允许本机访问"})
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).hostname not in ("127.0.0.1", "localhost"):
            return self._send(403, {"错误": "来源不允许"})
        u = urlparse(self.path)
        if u.path == "/api/upload":
            return self._upload(parse_qs(u.query))
        if u.path != "/api/action" or "json" not in (self.headers.get("Content-Type") or ""):
            return self._send(400, {"错误": "请求不合法"})
        n = int(self.headers.get("Content-Length") or 0)
        try:
            if n > 15_000_000:
                return self._send(413, {"错误": "太大了"})
            a = json.loads(self.rfile.read(n) or b"{}")
            ok, out = action(a)
        except Exception as e:
            ok, out = False, str(e)
        self._send(200 if ok else 400, {"成功": ok, "输出": out})

    def _upload(self, q):
        """流式接收浏览器拖入/选中的视频文件,直接写入本地 待加工/ 目录,不占内存。"""
        raw_name = unquote((q.get("name") or [""])[0]).strip()
        safe = re.sub(r"[^\w.\-\u4e00-\u9fff ]", "_", Path(raw_name).name).strip()
        if not safe or Path(safe).suffix.lower() not in VIDEO_EXT:
            return self._send(400, {"成功": False, "输出": "只支持 mp4 / mov / mkv / m4v 视频文件"})
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return self._send(400, {"成功": False, "输出": "视频文件为空"})
        inbox = db.folder("待加工目录", "待加工")
        inbox.mkdir(parents=True, exist_ok=True)
        dest = inbox / safe
        if dest.exists():
            stem, suf = dest.stem, dest.suffix
            dest = inbox / f"{stem}_{time.strftime('%H%M%S')}{suf}"
        part = inbox / f".uploading_{dest.name}"
        left = n
        try:
            with open(part, "wb") as fh:
                while left > 0:
                    chunk = self.rfile.read(min(1 << 20, left))
                    if not chunk:
                        break
                    fh.write(chunk)
                    left -= len(chunk)
            if left > 0:
                part.unlink(missing_ok=True)
                return self._send(400, {"成功": False, "输出": "上传中断,未保存残缺文件"})
            os.rename(part, dest)
            t = time.time() - 605
            os.utime(dest, (t, t))
            return self._send(200, {"成功": True, "输出": f"已存入待加工/{dest.name}", "文件": dest.name})
        except Exception as e:
            part.unlink(missing_ok=True)
            return self._send(500, {"成功": False, "输出": f"写入失败:{e}"})

    def _thumb(self, p, at_str):
        """用 ffmpeg 截取视频指定秒数的缩略帧并落盘缓存到 data/.thumbs/。"""
        r = rel(p)
        if not r:
            return self._send(404, {"错误": "视频不存在"})
        f = (ROOT / r).resolve()
        if f.suffix.lower() not in VIDEO_EXT or not f.is_file():
            return self._send(400, {"错误": "不是受支持的视频文件"})
        try:
            at = max(0.0, float(at_str or 0))
        except ValueError:
            at = 1.0
        st = f.stat()
        tdir = ROOT / "data" / ".thumbs"
        tdir.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha1(f"{r}:{st.st_size}:{int(st.st_mtime)}:{at:.1f}".encode()).hexdigest()[:20]
        jpg = tdir / f"{key}.jpg"
        if not jpg.exists():
            tmp = tdir / f".{key}.{os.getpid()}.jpg"
            for seek in (at, 0.0):
                cmd = ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{seek:.2f}", "-i", str(f),
                       "-frames:v", "1", "-vf", "scale=480:-2", "-q:v", "3", "-y", str(tmp)]
                subprocess.run(cmd, capture_output=True, timeout=15)
                if tmp.exists() and tmp.stat().st_size > 0:
                    os.replace(tmp, jpg)
                    break
            tmp.unlink(missing_ok=True)
        if not jpg.exists():
            return self._send(404, {"错误": "无法生成缩略图"})
        data = jpg.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(data)

    def _file(self, p):
        r = rel(p)
        if not r:
            return self._send(404, {"错误": "文件不在项目里或不存在"})
        f = (ROOT / r).resolve()
        ext = f.suffix.lower()
        if ext not in IMG_EXT | VIDEO_EXT | {".md", ".srt", ".txt", ".json"}:
            return self._send(403, {"错误": "不支持的文件类型"})
        size = f.stat().st_size
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        if ext in {".md", ".srt", ".txt", ".json"}:
            ctype = "text/plain; charset=utf-8"
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        m = re.match(r"bytes=(\d*)-(\d*)", rng or "")
        if m:
            if m[1]:
                start = int(m[1])
                end = int(m[2]) if m[2] else min(size - 1, start + 8 * 1024 * 1024)
            elif m[2]:
                start = max(0, size - int(m[2]))
        end = min(end, size - 1)
        if start > end:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return
        self.send_response(206 if m else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if m:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with open(f, "rb") as fh:
            fh.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = fh.read(min(1 << 20, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                left -= len(chunk)


def _patrol_loop():
    """内置后台巡检线程(避免项目放在 ~/Desktop 时 macOS launchd 被 TCC 拦截)。"""
    while True:
        time.sleep(15)
        try:
            if db.CFG.get("自动执行"):
                gap = max(30, int(db.CFG.get("监测间隔秒", 300)))
                if time.time() - _last_kick[0] >= gap:
                    kick()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser(description="视频剪辑 SOP 本地工作台")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-open", action="store_true")
    a = ap.parse_args()
    if not db.DB.exists():
        sys.exit("还没有数据库,先运行:python3 3-工具/db.py init")
    threading.Thread(target=_patrol_loop, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    url = f"http://127.0.0.1:{a.port}/"
    print(f"工作台已启动:{url}  (Ctrl+C 停止)")
    if not a.no_open:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
