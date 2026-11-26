#!/usr/bin/env python3
"""监测数据库状态变化,决定要不要启动 AI 去做下一个环节。

原理:每隔 N 秒(配置.json 的 监测间隔秒)跑一次 db.py 的待办检查。
- 只有 AI 能做的待办(ACTION)才会触发;人工待办(看片、审核等)只提示,写进 data/待办.md。
- 同一时间只跑一个任务(锁文件 data/.watch.lock)。
- 待办内容没有变化就不重复触发;失败的对象 60 分钟内不重试(按对象算,不拖累同环节的其他对象);
  同一环节一天最多触发 3 次。用户在工作台处理过的对象(data/.watch_clear.json)会立即解除冷却。
- 一步做完立刻检查下一步,连续做到需要人工的关卡或没有活为止(每轮最多 8 步)。
- 「1-复盘选片」开工前,转写由本脚本直接跑(固定命令,不需要 AI;也避开 Codex 沙箱用不了 GPU 的问题)。
- 配置.json 里 自动执行=false 时,只提示不启动(默认,首次使用建议保持)。
- 驱动命令是模板,{prompt} 会被替换成给 AI 的指令。例:
    Claude Code: "claude -p {prompt}"
    Codex CLI:   "codex exec {prompt}"
    其他 AI:     任何能接收一段文字指令、在本项目目录里执行的命令行。

用法(在项目根目录):
  python3 3-工具/watch.py --once      检查一次就退出(适合交给系统定时器 / OpenBot 例行任务)
  python3 3-工具/watch.py             持续监测(Ctrl+C 停止)
  python3 3-工具/watch.py --once --dry-run   只显示会做什么,不启动 AI
"""
import argparse, hashlib, json, os, pathlib, shlex, subprocess, sys, time
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "3-工具"))
import db  # noqa: E402

TZ = timezone(timedelta(hours=8))
STATE = ROOT / "data" / ".watch_state.json"
LOCK = ROOT / "data" / ".watch.lock"
TODO_MD = ROOT / "data" / "待办.md"
LOGDIR = ROOT / "data" / "运行日志"
ORDER = ["0-整理", "1-复盘选片", "代审-挑选", "2-剪辑", "代审-看片", "4-文案", "5-封面", "代审-选封面", "代审-发布",
         "6-发布", "7-数据复盘", "8-偏好复盘"]
CLEAR = ROOT / "data" / ".watch_clear.json"
COOL = 3600
MAX_CHAIN = 8
STUCK_WORDS = ("需要权限", "需要批准", "等待批准", "权限被拒", "permission", "requires approval", "not allowed")


def stamp():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def load_state():
    try:
        st = json.loads(STATE.read_text())
    except Exception:
        st = {}
    # 旧格式:失败时间 = {环节: 时间戳} → 新格式 {环节: {对象: 时间戳}}("*" 表示整个环节)
    ft = st.get("失败时间") or {}
    st["失败时间"] = {k: (v if isinstance(v, dict) else {"*": v}) for k, v in ft.items()}
    return st


def apply_clear(st):
    """工作台上用户处理过的对象:解除冷却,并允许同一批待办再触发一次。"""
    try:
        objs = set(json.loads(CLEAR.read_text()).get("对象", []))
    except Exception:
        return
    CLEAR.unlink(missing_ok=True)
    if not objs:
        return
    for stage, m in st["失败时间"].items():
        for o in list(m):
            if o in objs or o == "*" or o.split("@")[0] in objs:
                m.pop(o, None)
    for stage, ids in (st.get("上次对象") or {}).items():
        if any(i in objs or i.split("@")[0] in objs for i in ids):
            st["上次指纹"].pop(stage, None)
    for o in objs:
        (st.get("最近结果") or {}).pop(o, None)
    print(f"[{stamp()}] 工作台处理过 {len(objs)} 个对象,已解除冷却")


def cooling(st, stage, oid):
    m = st["失败时间"].get(stage, {})
    t = m.get(oid) or m.get("*")
    return bool(t and time.time() - t < COOL)


def note_result(st, ids, stage, kind, text):
    """每个对象最近一次 AI 处理的结果,工作台卡片上显示(失败原因、几点重试)。"""
    r = st.setdefault("最近结果", {})
    for i in ids:
        r[i] = {"环节": stage, "结果": kind, "说明": text[:300], "时间": time.time()}


def save_state(s):
    STATE.write_text(json.dumps(s, ensure_ascii=False, indent=1))


def write_todo(todo):
    lines = [f"# 待办(自动生成,{stamp()})", ""]
    if not todo:
        lines.append("没有待办。")
    for x in todo:
        who = "🤖 AI" if x["执行者"] == "AI" else "👤 需要你"
        lines.append(f"- **{x['环节']}**({who},{len(x['对象'])} 条):{x['说明']}")
        for o in x["对象"][:15]:
            lines.append(f"  - {o}")
        if len(x["对象"]) > 15:
            lines.append(f"  - …共 {len(x['对象'])} 条")
    TODO_MD.write_text("\n".join(lines) + "\n")


def end_line(logf):
    """从运行日志里找最后一个结束行(【完成】/【需人工】/【失败】/【无事】)。
    兼容纯文本输出和 Claude Code / Codex 的 JSON 流输出。
    只看 AI 自己说的话(Claude Code 的 result、Codex 的 agent_message、纯文本行),
    不看工具结果——AI 读过的说明文件里也有结束行的格式示例,不能算数。"""
    import re
    texts = []
    for ln in logf.read_text(errors="ignore").splitlines():
        try:
            d = json.loads(ln)
        except ValueError:
            texts.append(ln)
            continue
        if not isinstance(d, dict):
            continue
        if d.get("type") == "result" and isinstance(d.get("result"), str):       # Claude Code
            texts.append(d["result"])
        item = d.get("item") if isinstance(d.get("item"), dict) else {}
        if item.get("type") == "agent_message" and isinstance(item.get("text"), str):  # Codex
            texts.append(item["text"])
    found = []
    for t in texts:
        found += re.findall(r"【(?:完成|需人工|失败|无事)】[^\n]*", t)
    return found[-1].strip() if found else ""


def prompt_for(stage, ids):
    return (f"你在执行项目「视频剪辑SOP」(当前目录)。先读 AGENTS.md,然后只执行一个环节:{stage}。"
            f"对象:{', '.join(ids[:20])}。按 3-工具/环节/{stage}.md 的步骤做,所有状态修改只用 3-工具/db.py。"
            "人工关卡(挑选、看片、选封面、审核发布、同意改标准)绝不代做;只有环节名以「代审-」开头时,才按该环节文件代用户决定,并用 --by AI代审。最后一行按 AGENTS.md 的格式输出结束行。")


def take_lock(stage):
    """原子地拿锁(工作台和定时任务可能同时触发检查)。超过 4 小时的旧锁视为残留。"""
    LOCK.parent.mkdir(exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(fd, f"{stage} {stamp()} pid={os.getpid()}".encode())
            os.close(fd)
            return True
        except FileExistsError:
            if time.time() - LOCK.stat().st_mtime < 4 * 3600:
                return False
            LOCK.unlink(missing_ok=True)
    return False


def need_transcribe(sid):
    src = ROOT / "工作区" / sid / "转录文件"
    out = ROOT / "工作区" / sid / "复盘" / "transcript"
    if not src.is_dir():
        return False
    vids = [p for p in src.iterdir() if p.suffix.lower() in db.VIDEO_EXT]
    return any(not (out / (p.stem + ".json")).exists() for p in vids)


def pre_transcribe(ids, st):
    """在启动 AI 之前,由监测脚本直接转写(沙箱外、能用 GPU)。返回转写失败的素材。"""
    bad = []
    for sid in ids:
        if not need_transcribe(sid):
            continue
        LOGDIR.mkdir(exist_ok=True)
        logf = LOGDIR / f"{datetime.now(TZ).strftime('%Y%m%d-%H%M%S')}_转写_{sid}.log"
        LOCK.write_text(f"1-复盘选片 {stamp()} pid={os.getpid()}\n" + json.dumps(
            {"环节": "1-复盘选片", "步骤": "转写", "对象": [sid], "开始": datetime.now(TZ).isoformat(timespec="seconds"),
             "日志": logf.name, "pid": os.getpid()}, ensure_ascii=False))
        print(f"[{stamp()}] ▶ 转写 {sid}(本机,不交给 AI)")
        try:
            with open(logf, "w") as lf:
                rc = subprocess.run(["zsh", str(ROOT / "3-工具/脚本/transcribe.sh"), f"工作区/{sid}/转录文件", f"工作区/{sid}/复盘"],
                                    cwd=ROOT, stdout=lf, stderr=subprocess.STDOUT, timeout=3 * 3600).returncode
        except subprocess.TimeoutExpired:
            rc = -1
        if rc != 0 or need_transcribe(sid):
            tail = [l for l in logf.read_text(errors="ignore").splitlines() if l.strip()][-3:]
            why = "本机转写失败:" + (" / ".join(tail) or f"返回码 {rc}")
            print(f"[{stamp()}] ❌ 1-复盘选片 结束(返回码 {rc}):转写 {sid} 失败")
            subprocess.run([sys.executable, "-I", str(ROOT / "3-工具/db.py"), "set", "source", sid, "需人工", "--by", "AI",
                            "--note", why[:300]], cwd=ROOT, capture_output=True)
            note_result(st, [sid], "1-复盘选片", "失败", why)
            bad.append(sid)
        else:
            print(f"[{stamp()}] ✅ 转写 {sid} 完成")
    return bad


def run_once(dry, force=False):
    """检查一次;做了一步并且成功返回 True(调用方会接着检查下一步)。"""
    c = db.conn()
    todo = db.pending(c)
    c.close()
    write_todo(todo)
    st = load_state()
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    st.setdefault("今日", today)
    if st["今日"] != today:
        st.update({"今日": today, "今日次数": {}})
    st.setdefault("今日次数", {})
    st.setdefault("上次指纹", {})
    st.setdefault("上次对象", {})
    apply_clear(st)

    for x in todo:
        if x["执行者"] != "AI":
            print(f"[{stamp()}] 👤 {x['环节']}:{len(x['对象'])} 条等你处理(见 data/待办.md)")
    actions = sorted([x for x in todo if x["执行者"] == "AI"], key=lambda x: ORDER.index(x["环节"]) if x["环节"] in ORDER else 99)
    if not actions:
        print(f"[{stamp()}] 没有 AI 待办")
        save_state(st)
        return False
    # 一次只做一个环节,按流程顺序;冷却中的对象跳过,不拖住同环节的其他对象
    stage, ids = None, []
    for x in actions:
        live = x["对象"] if force else [i for i in x["对象"] if not cooling(st, x["环节"], i)]
        if not live:
            print(f"[{stamp()}] {x['环节']}:{len(x['对象'])} 个对象上次失败不到 60 分钟,暂不重试")
            continue
        fp = hashlib.sha1(json.dumps(live, ensure_ascii=False).encode()).hexdigest()
        if not force and st["上次指纹"].get(x["环节"]) == fp:
            print(f"[{stamp()}] {x['环节']}:待办和上次一样,不重复触发(状态没有变化)")
            continue
        if not force and st["今日次数"].get(x["环节"], 0) >= 3:
            print(f"[{stamp()}] {x['环节']}:今天已触发 3 次,不再触发,请人工查看 data/运行日志/")
            continue
        stage, ids = x["环节"], live
        break
    if not stage:
        save_state(st)
        return False

    cmd_tpl = db.CFG.get("驱动命令", "")
    auto = db.CFG.get("自动执行", False)
    prompt = prompt_for(stage, ids)
    if dry or not auto or not cmd_tpl:
        why = "演练模式" if dry else ("配置里 自动执行=false" if not auto else "配置里没有驱动命令")
        print(f"[{stamp()}] 🤖 待执行 {stage}({len(ids)} 条)。{why},未启动 AI。")
        print("    要执行的指令:" + prompt)
        if not dry:
            st["上次指纹"][stage] = fp
            st["上次对象"][stage] = ids[:50]
        save_state(st)
        return False
    if not take_lock(stage):
        print(f"[{stamp()}] 已有任务在运行(锁文件 {LOCK.name}),本轮跳过")
        return False
    if stage == "1-复盘选片":
        bad = pre_transcribe(ids, st)
        ids = [i for i in ids if i not in bad]
        if not ids:
            LOCK.unlink(missing_ok=True)
            save_state(st)
            return True          # 转写失败的已标需人工;接着看别的活
        prompt = prompt_for(stage, ids)
    LOGDIR.mkdir(exist_ok=True)
    logf = LOGDIR / f"{datetime.now(TZ).strftime('%Y%m%d-%H%M%S')}_{stage}.log"
    # 锁文件第一段是环节名(兼容旧读法),后面带一行 JSON 给工作台显示实时状态
    LOCK.write_text(f"{stage} {stamp()} pid={os.getpid()}\n" + json.dumps(
        {"环节": stage, "对象": ids[:20], "开始": datetime.now(TZ).isoformat(timespec="seconds"),
         "日志": logf.name, "pid": os.getpid()}, ensure_ascii=False))
    args = [a.replace("{prompt}", prompt) for a in shlex.split(cmd_tpl)]
    print(f"[{stamp()}] ▶ 启动 {stage}:{args[0]} …(日志 {logf.relative_to(ROOT)})")
    st["今日次数"][stage] = st["今日次数"].get(stage, 0) + 1
    try:
        with open(logf, "w") as lf:
            rc = subprocess.run(args, cwd=ROOT, stdout=lf, stderr=subprocess.STDOUT, timeout=3 * 3600).returncode
        end = end_line(logf)
        kind = end[1:3] if end else ""
        ok = rc == 0 and kind in ("完成", "无事", "需人")
        mark = {"完成": "✅", "无事": "✅", "需人": "👤"}.get(kind, "❌") if rc == 0 else "❌"
        print(f"[{stamp()}] {mark} {stage} 结束(返回码 {rc}):{(end or '没有找到结束行')[:200]}")
        if kind == "需人" and any(w in end.lower() for w in STUCK_WORDS):
            kind = "卡权限"
        elif not end:
            tail = logf.read_text(errors="ignore")[-4000:].lower()
            if any(w in tail for w in STUCK_WORDS):
                kind, end = "卡权限", "AI 停在等权限批准(无人值守时没人能批),请看运行日志"
        fm = st["失败时间"].setdefault(stage, {})
        fm.pop("*", None)
        if ok and kind != "卡权限":
            for i in ids:
                fm.pop(i, None)
            st["上次指纹"][stage] = fp
            st["上次对象"][stage] = ids[:50]
        else:
            for i in ids:
                fm[i] = time.time()
        note_result(st, ids, stage, {"完成": "完成", "无事": "完成", "需人": "需人工"}.get(kind, kind or "失败"), end or "没有找到结束行")
        return ok and kind != "卡权限"
    except subprocess.TimeoutExpired:
        print(f"[{stamp()}] ❌ {stage} 超过 3 小时未结束,已停止等待")
        for i in ids:
            st["失败时间"].setdefault(stage, {})[i] = time.time()
        note_result(st, ids, stage, "失败", "超过 3 小时未结束")
        return False
    finally:
        LOCK.unlink(missing_ok=True)
        save_state(st)


def chain(dry, force=False):
    """做完一步立刻看下一步,直到没活、要等人或失败(最多 MAX_CHAIN 步)。"""
    for n in range(MAX_CHAIN):
        if not run_once(dry, force and n == 0):
            return
        print(f"[{stamp()}] → 接着检查下一步")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true", help="忽略'没变化/失败冷却/次数上限',立即触发(调试用)")
    a = p.parse_args()
    if a.once:
        chain(a.dry_run, a.force)
        return
    gap = int(db.CFG.get("监测间隔秒", 300))
    print(f"开始监测,每 {gap} 秒检查一次。Ctrl+C 停止。")
    while True:
        try:
            chain(a.dry_run, a.force)
        except SystemExit:
            pass
        except Exception as e:
            print(f"[{stamp()}] 监测出错:{e}")
        time.sleep(gap)


if __name__ == "__main__":
    main()
