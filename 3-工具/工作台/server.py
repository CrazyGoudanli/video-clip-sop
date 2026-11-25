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
import argparse, json, mimetypes, os, re, sqlite3, subprocess, sys, threading, webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

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


def state():
    c = db.conn()
    todo = db.pending(c)
    sources = rows(c, "select * from sources order by 日期 desc, source_id desc")
    for s in sources:
        s["文件"] = source_files(s["source_id"])
    clips = rows(c, "select * from clips order by source_id desc, clip_id")
    for k in clips:
        files = source_files(k["source_id"])["视频"]
        want = re.search(r"来源文件[::]\s*([^\s;;,,]+)", k.get("理由") or "")
        src = next((f for f in files if want and want[1] in f), files[0] if files else None)
        k["预览"] = {"文件": src, "起": secs(k["起始"]), "止": secs(k["结束"])}
        k["成片"] = rel(k.get("成片文件"))
        k["封面候选"] = cover_candidates(k.get("本地文件夹"))
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
    events = rows(c, "select * from events order by id desc limit 30")
    groups = {}
    for dim in ("标题句式", "封面类型", "选题类型", "钩子类型"):
        groups[dim] = rows(c, f"select coalesce({dim},'未标注') 分组, count(*) 条数, round(avg(播放)) 平均播放, "
                              f"round(avg(完播率),4) 平均完播率, round(avg(涨粉),1) 平均涨粉 from v_performance "
                              f"where 时间档 in ('72h','7d') group by 1 order by 平均播放 desc")
    c.close()
    return {"文件夹": folder_info(), "项目路径": str(ROOT), "待办": todo, "素材": sources, "切片": clips, "发布": pubs, "最近操作": events, "分组": groups,
            "配置": {k: db.CFG.get(k) for k in ("发布平台", "成片时长", "驱动AI", "剪辑工具", "自动执行", "封面图形风格", "发布排期", "AI代审")},
            "可选设置": settings_options(), "自动处理": auto_status()}


# ---------------- 写:只通过 db.py ----------------
CLIP_STATES = {"待剪", "放弃", "候选"}
PUB_STATES = {"待发布", "已废弃", "草稿"}
PUB_FIELDS = {"标题", "简介", "标签", "选用"}
ID_RE = re.compile(r"^[^\s/\\]{3,80}$")


def run_db(*args):
    r = subprocess.run([sys.executable, "-I", str(DBPY), *args], cwd=ROOT, capture_output=True, text=True, timeout=60)
    out = (r.stdout + r.stderr).strip()
    return r.returncode == 0, out


def action(a):
    kind, oid = a.get("动作"), a.get("id", "")
    if kind == "打开":
        return open_path(a)
    if kind == "设置":
        return change_setting(a)
    if kind == "代审":
        return set_gate(a)
    if kind == "自动处理":
        return set_auto(bool(a.get("开启")))
    if kind == "批量切片状态":
        ids = [i for i in (a.get("ids") or []) if ID_RE.match(i)]
        if a.get("状态") not in CLIP_STATES or not ids:
            return False, "参数不对"
        outs, ok = [], True
        for i in ids:
            o, t = run_db("set", "clip", i, a["状态"], "--by", "人工", "--note", "工作台")
            ok &= o
            outs.append(t)
        return ok, "\n".join(outs)
    if not ID_RE.match(oid):
        return False, "ID 不合法"
    note = "工作台:" + (a.get("备注") or "").strip()
    if kind == "切片状态":
        if a.get("状态") not in CLIP_STATES:
            return False, "不支持的状态"
        return run_db("set", "clip", oid, a["状态"], "--by", "人工", "--note", note)
    if kind == "看片":
        res = a.get("结论")
        if res not in ("通过", "打回"):
            return False, "结论只能是通过或打回"
        args = ["review", oid, res, "--by", "人工", "--reviewer", "工作台"]
        if a.get("原因"):
            args += ["--reason", a["原因"]]
        return run_db(*args)
    if kind == "发布状态":
        if a.get("状态") not in PUB_STATES:
            return False, "不支持的状态"
        return run_db("set", "pub", oid, a["状态"], "--by", "人工", "--note", note)
    if kind == "改文案":
        pairs = [f"{k}={v}" for k, v in (a.get("字段") or {}).items() if k in PUB_FIELDS]
        if not pairs:
            return False, "没有可改的字段"
        return run_db("update", "pub", oid, *pairs, "--by", "人工")
    if kind == "选封面":
        p = rel(a.get("文件"))
        if not p or Path(p).suffix.lower() not in IMG_EXT or "/封面/候选/" not in "/" + p:
            return False, "只能选 封面/候选/ 里的图片"
        return run_db("update", "pub", oid, f"封面竖={p}", "封面横=", f"备注=工作台选定封面 {Path(p).name}", "--by", "人工")
    if kind == "打开":
        return open_path(a)
    return False, "未知动作"


# 左下角设置:只允许改这几项,值只能从列表里选
SETTINGS = {
    "驱动AI": {"Claude Code": {"驱动命令": "zsh 3-工具/脚本/run_claude.sh {prompt}"},
               "Codex": {"驱动命令": "zsh 3-工具/脚本/run_codex.sh {prompt}"}},
    "剪辑工具": {"ChatCut": {}, "ffmpeg": {}},
}


def settings_options():
    import shutil
    os.environ["PATH"] = os.pathsep.join([str(Path.home() / ".local/bin"), "/opt/homebrew/bin", os.environ.get("PATH", "")])
    have = {"Claude Code": bool(shutil.which("claude")), "Codex": bool(shutil.which("codex")),
            "ChatCut": Path("/Applications/ChatCut.app").exists(), "ffmpeg": bool(shutil.which("ffmpeg"))}
    note = {"Claude Code": "推荐", "Codex": "", "ChatCut": "有标题栏、金句卡等动效包装", "ffmpeg": "免费,只做基础剪辑和字幕"}
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
    """自动处理开关的实际状态:配置里的 自动执行 + 定时检查任务是否在跑;以及 AI 此刻在不在干活。"""
    r = subprocess.run(["zsh", str(AUTORUN), "status"], capture_output=True, text=True, timeout=20)
    m = re.search(r"监测:\s*(\S+)\s*/\s*(\S+)", r.stdout)
    running_task = m and m[2] == "在跑"
    lock = ROOT / "data" / ".watch.lock"
    busy = lock.read_text().split(" ")[0] if lock.exists() else ""
    logs = sorted((ROOT / "data" / "运行日志").glob("*.log"), key=lambda p: p.stat().st_mtime) if (ROOT / "data" / "运行日志").is_dir() else []
    last = [p for p in logs if p.name != "autorun.log"]
    return {"开启": bool(db.CFG.get("自动执行")) and bool(running_task), "配置": bool(db.CFG.get("自动执行")),
            "定时任务": bool(running_task), "间隔秒": db.CFG.get("监测间隔秒", 300), "正在做": busy,
            "最近一次": last[-1].name if last else ""}


def set_auto(on):
    cfg_path = ROOT / "配置.json"
    if not cfg_path.exists():
        return False, "还没有 配置.json,先让 AI 按启动问卷生成"
    cfg = json.loads(cfg_path.read_text())
    if on and not cfg.get("驱动命令"):
        return False, "还没设置驱动 AI,先在左下角选一个"
    r = subprocess.run(["zsh", str(AUTORUN), "install" if on else "uninstall"], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return False, (r.stdout + r.stderr).strip()[-400:]
    cfg["自动执行"] = bool(on)
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=1) + "\n")
    db.CFG.clear()
    db.CFG.update(cfg)
    return True, ("自动处理已开启:每 %s 秒检查一次,有活就让 AI 接着做" % cfg.get("监测间隔秒", 300)) if on else "自动处理已关闭"


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
            if u.path == "/api/state":
                return self._send(200, state())
            if u.path == "/file":
                return self._file(unquote(q.get("path", [""])[0]))
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
        if self.path != "/api/action" or "json" not in (self.headers.get("Content-Type") or ""):
            return self._send(400, {"错误": "请求不合法"})
        n = int(self.headers.get("Content-Length") or 0)
        try:
            a = json.loads(self.rfile.read(min(n, 100_000)) or b"{}")
            ok, out = action(a)
        except Exception as e:
            ok, out = False, str(e)
        self._send(200 if ok else 400, {"成功": ok, "输出": out})

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


def main():
    ap = argparse.ArgumentParser(description="视频剪辑 SOP 本地工作台")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-open", action="store_true")
    a = ap.parse_args()
    if not db.DB.exists():
        sys.exit("还没有数据库,先运行:python3 3-工具/db.py init")
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
