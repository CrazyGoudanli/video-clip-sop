#!/usr/bin/env python3
"""监测数据库状态变化,决定要不要启动 AI 去做下一个环节。

原理:每隔 N 秒(配置.json 的 监测间隔秒)跑一次 db.py 的待办检查。
- 只有 AI 能做的待办(ACTION)才会触发;人工待办(看片、审核等)只提示,写进 data/待办.md。
- 同一时间只跑一个任务(锁文件 data/.watch.lock)。
- 待办内容没有变化就不重复触发;同一环节失败后 60 分钟内不重试;同一环节一天最多触发 3 次。
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
ORDER = ["0-整理", "1-复盘选片", "2-剪辑", "4-文案", "5-封面", "6-发布", "7-数据复盘"]


def stamp():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def load_state():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


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
            "人工关卡(挑选、看片、审核发布、同意改标准)绝不代做。最后一行按 AGENTS.md 的格式输出结束行。")


def run_once(dry, force=False):
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
    st.setdefault("失败时间", {})
    st.setdefault("上次指纹", {})

    for x in todo:
        if x["执行者"] != "AI":
            print(f"[{stamp()}] 👤 {x['环节']}:{len(x['对象'])} 条等你处理(见 data/待办.md)")
    actions = sorted([x for x in todo if x["执行者"] == "AI"], key=lambda x: ORDER.index(x["环节"]))
    if not actions:
        print(f"[{stamp()}] 没有 AI 待办")
        save_state(st)
        return
    x = actions[0]  # 一次只做一个环节,按流程顺序
    stage, ids = x["环节"], x["对象"]
    fp = hashlib.sha1(json.dumps(ids, ensure_ascii=False).encode()).hexdigest()
    if not force:
        if st["上次指纹"].get(stage) == fp:
            print(f"[{stamp()}] {stage}:待办和上次一样,不重复触发(状态没有变化)")
            save_state(st); return
        ft = st["失败时间"].get(stage)
        if ft and time.time() - ft < 3600:
            print(f"[{stamp()}] {stage}:上次失败不到 60 分钟,暂不重试")
            save_state(st); return
        if st["今日次数"].get(stage, 0) >= 3:
            print(f"[{stamp()}] {stage}:今天已触发 3 次,不再触发,请人工查看 data/运行日志/")
            save_state(st); return

    cmd_tpl = db.CFG.get("驱动命令", "")
    auto = db.CFG.get("自动执行", False)
    prompt = prompt_for(stage, ids)
    if dry or not auto or not cmd_tpl:
        why = "演练模式" if dry else ("配置里 自动执行=false" if not auto else "配置里没有驱动命令")
        print(f"[{stamp()}] 🤖 待执行 {stage}({len(ids)} 条)。{why},未启动 AI。")
        print("    要执行的指令:" + prompt)
        if not dry:
            st["上次指纹"][stage] = fp
        save_state(st)
        return
    if LOCK.exists() and time.time() - LOCK.stat().st_mtime < 4 * 3600:
        print(f"[{stamp()}] 已有任务在运行(锁文件 {LOCK.name}),本轮跳过")
        return
    LOCK.write_text(f"{stage} {stamp()} pid={os.getpid()}")
    LOGDIR.mkdir(exist_ok=True)
    logf = LOGDIR / f"{datetime.now(TZ).strftime('%Y%m%d-%H%M%S')}_{stage}.log"
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
        if ok:
            st["失败时间"].pop(stage, None)
            st["上次指纹"][stage] = fp
        else:
            st["失败时间"][stage] = time.time()
    except subprocess.TimeoutExpired:
        print(f"[{stamp()}] ❌ {stage} 超过 3 小时未结束,已停止等待")
        st["失败时间"][stage] = time.time()
    finally:
        LOCK.unlink(missing_ok=True)
        save_state(st)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true", help="忽略'没变化/失败冷却/次数上限',立即触发(调试用)")
    a = p.parse_args()
    if a.once:
        run_once(a.dry_run, a.force)
        return
    gap = int(db.CFG.get("监测间隔秒", 300))
    print(f"开始监测,每 {gap} 秒检查一次。Ctrl+C 停止。")
    while True:
        try:
            run_once(a.dry_run, a.force)
        except SystemExit:
            pass
        except Exception as e:
            print(f"[{stamp()}] 监测出错:{e}")
        time.sleep(gap)


if __name__ == "__main__":
    main()
