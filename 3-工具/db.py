#!/usr/bin/env python3
"""数据库操作入口。任何 AI 或人都只通过这个脚本读写 data/sop.db,不要直接写 SQL 改状态。

它负责:状态流转是否合法、人工关卡只能由人工通过、重剪计数、每次修改留痕(events 表)。
只用 Python 标准库。所有输出为中文 + 可读的 JSON。

常用命令(在项目根目录执行):
  python3 3-工具/db.py init                          新用户:建空数据库(已存在则不动)
  python3 3-工具/db.py migrate                       补字段/规整旧数据(可重复运行)
  python3 3-工具/db.py summary                       各表状态汇总
  python3 3-工具/db.py next                          现在每个环节有什么待办(监测脚本也用它)
  python3 3-工具/db.py show clip 课-20261119-08      看一条记录(clip / pub / source)
  python3 3-工具/db.py list clip --status 待剪       列出记录

  python3 3-工具/db.py add-source --来源 课程 --日期 2026-11-24 --标题 "..." [--原片位置 ...] [--本地文件夹 ...]
  python3 3-工具/db.py add-clips 候选.json           批量写入候选切片(格式见 3-工具/环节/1-复盘选片.md)
  python3 3-工具/db.py add-pub 文案.json             写入发布草稿(格式见 3-工具/环节/4-文案.md)
  python3 3-工具/db.py add-metrics 数据.json         写入发布数据(格式见 3-工具/环节/7-数据复盘.md)

  python3 3-工具/db.py set clip <ID> <新状态> --by AI|人工 [--note "..."]
  python3 3-工具/db.py set pub  <ID> <新状态> --by AI|人工 [--note "..."]
  python3 3-工具/db.py set source <ID> <新状态> --by AI|人工 [--note "..."]
  python3 3-工具/db.py update clip|pub|source <ID> 字段=值 [字段=值 ...] --by AI|人工
  python3 3-工具/db.py review <切片ID> 通过|打回 --by 人工 [--reason "..."] [--reviewer 名字]
  python3 3-工具/db.py plan-slots                    给"待发布"的记录排定时时间(只读,不写库)
"""
import argparse, json, pathlib, sqlite3, sys
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "配置.json").read_text()) if (ROOT / "配置.json").exists() else \
    json.loads((ROOT / "配置模板.json").read_text())
import os
DB = pathlib.Path(os.environ["SOP_DB"]) if os.environ.get("SOP_DB") else ROOT / CFG.get("数据库位置", "data/sop.db")
TZ = timezone(timedelta(hours=8))
MAX_REDO = int(CFG.get("重剪上限", 3))
PREFIX = {"课程": "课", "直播": "直", "访谈": "访", "论坛": "论"}

# ---------------- 状态机 ----------------
# 每个状态 -> 允许转到的状态。标 * 的流转是人工关卡,只能 --by 人工。
SOURCE_FLOW = {
    "待整理": {"已整理", "需人工"},
    "已整理": {"已复盘", "需人工"},
    "已复盘": {"需人工"},
    "需人工": {"待整理", "已整理", "已复盘"},
}
CLIP_FLOW = {
    "候选": {"待剪*", "放弃*"},
    "待剪": {"剪辑中", "放弃*", "候选*"},
    "剪辑中": {"已剪辑", "需人工", "待剪"},          # 剪辑中 -> 待剪 只用于"时长不达标/失败重剪",会计入重剪次数
    "已剪辑": {"已通过*", "待剪*", "需人工"},        # 看片关卡:通过 / 打回(请用 review 命令)
    "已通过": {"放弃*"},
    "放弃": {"候选*"},
    "需人工": {"候选*", "待剪*", "已剪辑*", "放弃*"},
}
PUB_FLOW = {
    "草稿": {"待发布*", "已废弃*", "需人工"},
    "待发布": {"已定时", "需人工", "草稿*", "已废弃*"},
    "已定时": {"已发布", "需人工", "已撤回*"},
    "已发布": {"已撤回*"},
    "已撤回": set(),
    "已废弃": {"草稿*"},
    "需人工": {"草稿*", "待发布*", "已定时*", "已发布*", "已废弃*"},
}
FLOWS = {"source": ("sources", "source_id", SOURCE_FLOW),
         "clip": ("clips", "clip_id", CLIP_FLOW),
         "pub": ("publishes", "publish_id", PUB_FLOW)}

# 需要补的字段(迁移时自动添加,已有则跳过)
NEW_COLUMNS = {
    "sources": {"创建时间": "TEXT", "更新时间": "TEXT"},
    "clips": {
        "重剪次数": "INTEGER DEFAULT 0", "看片结论": "TEXT", "打回原因": "TEXT", "看片人": "TEXT", "看片时间": "TEXT",
        "成片文件": "TEXT", "字幕文件": "TEXT", "剪辑工具": "TEXT", "剪辑工程": "TEXT",
        "封面字候选": "TEXT", "封面字": "TEXT", "封面道具": "TEXT", "剪辑标准版本": "TEXT",
        "创建时间": "TEXT", "更新时间": "TEXT"},
    "publishes": {"包装标准版本": "TEXT", "封面竖": "TEXT", "封面横": "TEXT", "创建时间": "TEXT", "更新时间": "TEXT"},
}
EVENTS = """CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, 时间 TEXT, 对象 TEXT, 对象ID TEXT,
  动作 TEXT, 旧值 TEXT, 新值 TEXT, 操作者 TEXT, 备注 TEXT)"""
META = "CREATE TABLE IF NOT EXISTS meta (键 TEXT PRIMARY KEY, 值 TEXT)"


def now():
    return datetime.now(TZ).isoformat(timespec="seconds")


def die(msg, code=2):
    print("❌ " + msg)
    sys.exit(code)


def conn():
    if not DB.exists():
        die(f"找不到数据库 {DB}")
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


def cols(c, table):
    return [r[1] for r in c.execute(f"pragma table_info({table})")]


def log(c, obj, oid, action, old, new, by, note=""):
    c.execute("insert into events (时间,对象,对象ID,动作,旧值,新值,操作者,备注) values (?,?,?,?,?,?,?,?)",
              (now(), obj, oid, action, old, new, by, note))


def row(c, kind, oid):
    table, key, _ = FLOWS[kind]
    r = c.execute(f"select * from {table} where {key}=?", (oid,)).fetchone()
    if not r:
        die(f"找不到 {kind} {oid}")
    return r


def append_note(old, note):
    if not note:
        return old
    stamp = datetime.now(TZ).strftime("%m-%d %H:%M")
    return ((old + "\n") if old else "") + f"[{stamp}] {note}"


# ---------------- 命令 ----------------
def cmd_migrate(a):
    c = conn()
    c.execute(EVENTS)
    c.execute(META)
    added = []
    for t, spec in NEW_COLUMNS.items():
        have = cols(c, t)
        for k, typ in spec.items():
            if k not in have:
                c.execute(f'alter table {t} add column "{k}" {typ}')
                added.append(f"{t}.{k}")
    c.execute("update clips set 重剪次数=0 where 重剪次数 is null")
    # 旧数据规整:素材状态"已生成"(旧复盘池)= 已复盘
    for r in c.execute("select source_id,状态 from sources where 状态='已生成'").fetchall():
        c.execute("update sources set 状态='已复盘' where source_id=?", (r[0],))
        log(c, "source", r[0], "迁移规整状态", "已生成", "已复盘", "迁移脚本")
    # 旧 Notion 里备注"废弃·绝不发布"、但当时没有废弃状态只能留草稿的记录 -> 已废弃
    for r in c.execute("select publish_id,状态 from publishes where 状态='草稿' and 备注 like '%废弃%绝不发布%'").fetchall():
        c.execute("update publishes set 状态='已废弃' where publish_id=?", (r[0],))
        log(c, "pub", r[0], "迁移规整状态", "草稿", "已废弃", "迁移脚本", "旧备注写明老师审核'绝不发布'")
    # 已剪辑但成片时长为空的,尝试从扩展字段补
    for r in c.execute("select clip_id,扩展 from clips where 成片时长_秒 is null and 扩展 is not null").fetchall():
        try:
            v = json.loads(r[1]).get("成片时长(秒)")
            if v not in (None, ""):
                c.execute("update clips set 成片时长_秒=? where clip_id=?", (float(v), r[0]))
                log(c, "clip", r[0], "迁移补成片时长", None, str(v), "迁移脚本")
        except Exception:
            pass
    # 从发布记录的汇总字段补(旧发布池里有"切片·成片时长(秒)")
    for r in c.execute("select p.clip_id, p.扩展 from publishes p join clips k on k.clip_id=p.clip_id "
                       "where k.成片时长_秒 is null").fetchall():
        try:
            v = json.loads(r[1] or "{}").get("切片·成片时长(秒)")
            if v not in (None, ""):
                c.execute("update clips set 成片时长_秒=? where clip_id=? and 成片时长_秒 is null", (float(v), r[0]))
                log(c, "clip", r[0], "迁移补成片时长", None, str(v), "迁移脚本", "取自发布记录")
        except Exception:
            pass
    c.execute("insert or replace into meta values ('结构版本','2')")
    c.execute("insert or replace into meta values ('迁移时间',?)", (now(),))
    c.commit()
    print("✅ 迁移完成。新增字段:" + (", ".join(added) if added else "无(已是最新)"))


def cmd_init(a):
    """新用户:建一个空数据库(已存在则不动)。"""
    if DB.exists():
        print(f"数据库已存在:{DB},不覆盖。如需补字段请运行 migrate。")
        return
    DB.parent.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT / "3-工具" / "脚本"))
    try:
        from schema import SCHEMA
    except ImportError:
        from import_from_archive import SCHEMA
    c = sqlite3.connect(DB)
    c.executescript(SCHEMA)
    c.commit(); c.close()
    DB.chmod(0o600)
    cmd_migrate(a)
    print(f"✅ 已建空数据库:{DB}")


def cmd_summary(a):
    c = conn()
    out = {}
    for kind, (t, key, _) in FLOWS.items():
        out[t] = {r[0]: r[1] for r in c.execute(f"select 状态,count(*) from {t} group by 1")}
    out["metrics"] = c.execute("select count(*) from metrics").fetchone()[0]
    print(json.dumps(out, ensure_ascii=False, indent=1))


def parse_t(s):
    if not s:
        return None
    try:
        t = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=TZ)
    except ValueError:
        return None


def pending(c):
    """返回待办清单:[{环节, 执行者, 对象: [...], 说明}]。监测脚本靠它判断有没有活。"""
    platforms = CFG.get("发布平台", ["抖音"])
    t = datetime.now(TZ)
    q = lambda s, *p: [r[0] for r in c.execute(s, p)]
    todo = []

    def add(stage, who, ids, note):
        if ids:
            todo.append({"环节": stage, "执行者": who, "对象": ids, "说明": note})

    # 0 整理:原始录像目录根部有未整理的录像文件(按文件名日期分组)
    raw = pathlib.Path(CFG.get("原始录像目录", "~/Movies")).expanduser()
    days = set()
    if raw.is_dir():
        import re
        for f in raw.iterdir():
            m = re.match(r"^(\d{4})-(\d{2})-(\d{2})[ -]\d{2}-\d{2}-\d{2}\.mkv$", f.name, re.I)
            if m and (t.timestamp() - f.stat().st_mtime) > 600:
                days.add("".join(m.groups()))
    add("0-整理", "AI", sorted(days), "原始录像目录里有已录完、未整理的录像(按日期)")
    add("1-复盘选片", "AI", q("select source_id from sources where 状态='已整理'"), "素材已整理,待转写、复盘、挑候选切片")
    add("人工-挑选", "人工", q("select clip_id from clips where 状态='候选'"), "候选切片等你挑:要剪的改'待剪'")
    stale = (t - timedelta(hours=3)).isoformat()
    add("2-剪辑", "AI", q("select clip_id from clips where 状态='待剪'") +
        q("select clip_id from clips where 状态='剪辑中' and coalesce(更新时间,'')<?", stale),
        "待剪的切片(含中断超过 3 小时的'剪辑中')")
    add("3-看片", "人工", q("select clip_id from clips where 状态='已剪辑'"), "成片等看片人看:通过 / 打回")
    miss = []
    for cid in q("select clip_id from clips where 状态='已通过'"):
        have = set(q("select 平台 from publishes where clip_id=?", cid))
        if any(p not in have for p in platforms):
            miss.append(cid)
    add("4-文案", "AI", miss, "看片已通过,还没有目标平台的发布草稿")
    ph = ",".join("?" * len(platforms))
    add("5-封面", "AI", q(f"select publish_id from publishes where 状态='草稿' and 平台 in ({ph}) "
                         "and coalesce(封面竖,'')='' and coalesce(封面,'')=''", *platforms), "草稿还没有封面")
    add("人工-审核发布", "人工", q(f"select publish_id from publishes where 状态='草稿' and 平台 in ({ph}) "
                              "and (coalesce(封面竖,'')!='' or coalesce(封面,'')!='')", *platforms),
        "草稿已齐(文案+封面),等你审核:要发的改'待发布'")
    add("6-发布", "AI", q(f"select publish_id from publishes where 状态='待发布' and 平台 in ({ph})", *platforms),
        "已授权,待设定时发布")
    due_fill, due_metric = [], []
    other = []
    for r in c.execute("select publish_id,平台,状态,发布时间,作品链接 from publishes where 状态 in ('已定时','已发布')"):
        pt = parse_t(r["发布时间"])
        if r["平台"] not in platforms:
            if r["状态"] == "已定时" and pt and pt <= t:
                other.append(r["publish_id"])
            continue
        if r["状态"] == "已定时" and pt and pt <= t:
            due_fill.append(r["publish_id"])
        if r["状态"] == "已发布" and r["作品链接"] and pt:
            have = set(q("select 时间档 from metrics where publish_id=?", r["publish_id"]))
            for tier, h in (("24h", 24), ("72h", 72), ("7d", 168)):
                if pt + timedelta(hours=h) <= t and tier not in have:
                    due_metric.append(r["publish_id"])
                    break
    add("7-数据复盘", "AI", due_fill + due_metric, "到点的定时作品待回填链接;已发布满 24h/72h/7d 待采集数据")
    add("人工-非启用平台", "人工", other, "未启用平台(配置.发布平台 之外)上已到点的定时作品:需人工确认,或在配置里启用该平台")
    add("人工-补链接", "人工", q("select publish_id from publishes where 状态='已发布' and coalesce(作品链接,'')=''"),
        "已发布但没有作品链接,没法采集数据(可让 AI 去平台后台找)")
    need = q("select '素材 '||source_id from sources where 状态='需人工'") + \
        q("select '切片 '||clip_id from clips where 状态='需人工'") + \
        q("select '发布 '||publish_id from publishes where 状态='需人工'")
    add("人工-需人工", "人工", need, "看备注里的原因,处理后把状态改回上一个状态")
    return todo


def cmd_next(a):
    c = conn()
    todo = pending(c)
    if a.json:
        print(json.dumps(todo, ensure_ascii=False, indent=1))
        return
    if not todo:
        print("NONE 没有待办")
    for x in todo:
        tag = "ACTION" if x["执行者"] == "AI" else "NOTICE"
        print(f"{tag} {x['环节']} ({len(x['对象'])}) {x['说明']}: " + ", ".join(x["对象"][:8]) +
              (" …" if len(x["对象"]) > 8 else ""))


def cmd_show(a):
    c = conn()
    r = row(c, a.kind, a.id)
    d = {k: r[k] for k in r.keys() if r[k] not in (None, "")}
    ev = [dict(e) for e in c.execute("select 时间,动作,旧值,新值,操作者,备注 from events where 对象=? and 对象ID=? "
                                     "order by id desc limit 10", (a.kind, a.id))]
    print(json.dumps({"记录": d, "最近操作": ev}, ensure_ascii=False, indent=1))


def cmd_list(a):
    c = conn()
    table, key, _ = FLOWS[a.kind]
    sql, p = f"select * from {table} where 1=1", []
    if a.status:
        sql += " and 状态=?"; p.append(a.status)
    if a.source_type:
        sql += " and 来源=?"; p.append(a.source_type)
    show = {"source": ["source_id", "来源", "日期", "状态", "标题"],
            "clip": ["clip_id", "状态", "成片时长_秒", "重剪次数", "标题"],
            "pub": ["publish_id", "平台", "状态", "发布时间", "标题"]}[a.kind]
    for r in c.execute(sql + f" order by {key}", p):
        print(" | ".join(str(r[k] if r[k] is not None else "") for k in show))


def check_by(by):
    if by not in ("AI", "人工"):
        die("--by 只能是 AI 或 人工")


def transition(c, kind, oid, new, by, note=""):
    table, key, flow = FLOWS[kind]
    r = row(c, kind, oid)
    old = r["状态"]
    if old == new:
        return old
    allowed = flow.get(old)
    if allowed is None:
        die(f"{oid} 当前状态'{old}'不在流程定义里,请人工处理")
    plain = {s.rstrip("*") for s in allowed}
    if new not in plain:
        die(f"{oid}:不允许从'{old}'改到'{new}'。允许:" + "、".join(sorted(s.rstrip('*') + ('(仅人工)' if s.endswith('*') else '') for s in allowed)))
    if (new + "*") in allowed and by != "人工":
        die(f"{oid}:'{old}'→'{new}'是人工关卡,只能由人工执行(--by 人工)。AI 不得代替用户执行。")
    extra = {}
    if kind == "clip" and new == "已剪辑":
        lo, hi = CFG.get("成片时长", [60, 90])
        d = r["成片时长_秒"]
        if not r["成片文件"]:
            die(f"{oid}:还没登记成片文件(update clip {oid} 成片文件=...),不能提交看片")
        if d is None or not (lo <= float(d) <= hi):
            die(f"{oid}:成片时长 {d} 秒不在 {lo}–{hi} 秒内,不得提交看片。请重剪(set clip {oid} 待剪,会计入重剪次数)")
    if kind == "clip" and old == "剪辑中" and new == "待剪":
        n = (r["重剪次数"] or 0) + 1
        extra["重剪次数"] = n
        if n >= MAX_REDO:
            new = "需人工"
            note = append_note(note, f"累计重剪 {n} 次仍未通过,按规则转需人工")
    sets = {"状态": new, "更新时间": now(), **extra}
    if note:
        sets["备注"] = append_note(r["备注"], note)
    c.execute(f"update {table} set " + ",".join(f'"{k}"=?' for k in sets) + f" where {key}=?", (*sets.values(), oid))
    log(c, kind, oid, "改状态", old, new, by, note)
    return new


def cmd_set(a):
    check_by(a.by)
    c = conn()
    new = transition(c, a.kind, a.id, a.status, a.by, a.note or "")
    c.commit()
    print(f"✅ {a.id} → {new}")


def cmd_update(a):
    check_by(a.by)
    c = conn()
    table, key, _ = FLOWS[a.kind]
    r = row(c, a.kind, a.id)
    have = cols(c, table)
    sets = {}
    for kv in a.pairs:
        if "=" not in kv:
            die(f"参数格式应为 字段=值:{kv}")
        k, v = kv.split("=", 1)
        if k in ("状态", key):
            die(f"'{k}'不能用 update 改;改状态请用 set / review 命令")
        if k not in have:
            die(f"表 {table} 没有字段'{k}'。可用字段:" + "、".join(have))
        sets[k] = None if v == "" else v
    if "备注" in sets:
        sets["备注"] = append_note(r["备注"], sets["备注"])
    sets["更新时间"] = now()
    c.execute(f"update {table} set " + ",".join(f'"{k}"=?' for k in sets) + f" where {key}=?", (*sets.values(), a.id))
    for k, v in sets.items():
        if k != "更新时间":
            log(c, a.kind, a.id, "改字段 " + k, str(r[k]) if k in r.keys() else None, v, a.by)
    c.commit()
    print(f"✅ {a.id} 已更新:" + "、".join(k for k in sets if k != "更新时间"))


def cmd_review(a):
    if a.by != "人工":
        die("看片是人工关卡,只能 --by 人工。AI 不得代替看片人做结论。")
    c = conn()
    r = row(c, "clip", a.id)
    if r["状态"] != "已剪辑":
        die(f"{a.id} 当前是'{r['状态']}',只有'已剪辑'的切片能看片")
    if a.result == "通过":
        lo, hi = CFG.get("成片时长", [60, 90])
        d = r["成片时长_秒"]
        if d is None or not (lo <= float(d) <= hi):
            die(f"{a.id} 成片时长 {d} 秒不在 {lo}–{hi} 秒内,按规则不能通过,请打回重剪")
        transition(c, "clip", a.id, "已通过", "人工", a.reason or "")
    else:
        if not a.reason:
            die("打回必须写原因:--reason '哪个时间点、什么问题'")
        n = (r["重剪次数"] or 0) + 1
        c.execute("update clips set 重剪次数=? where clip_id=?", (n, a.id))
        if n >= MAX_REDO:
            c.execute("update clips set 状态='需人工', 更新时间=?, 备注=? where clip_id=?",
                      (now(), append_note(r["备注"], f"看片打回:{a.reason};累计重剪 {n} 次,按规则转需人工"), a.id))
            log(c, "clip", a.id, "看片打回", "已剪辑", "需人工", "人工", a.reason)
        else:
            transition(c, "clip", a.id, "待剪", "人工", "看片打回:" + a.reason)
    c.execute("update clips set 看片结论=?, 打回原因=?, 看片人=?, 看片时间=? where clip_id=?",
              (a.result, a.reason if a.result == "打回" else None, a.reviewer or "老师", now(), a.id))
    c.commit()
    print(f"✅ {a.id} 看片{a.result}" + (f",当前状态:{c.execute('select 状态 from clips where clip_id=?', (a.id,)).fetchone()[0]}"))


def load_json(p):
    try:
        return json.loads(pathlib.Path(p).read_text())
    except Exception as e:
        die(f"读取 {p} 失败:{e}")


def cmd_add_source(a):
    check_by(a.by)
    c = conn()
    pre = PREFIX.get(a.来源)
    if not pre:
        die(f"未知来源'{a.来源}'。配置里的来源类型:{CFG.get('来源类型')};新来源请先在 db.py 的 PREFIX 里加缩写")
    sid = f"{pre}-{a.日期.replace('-', '')}" + (f"-{a.序号}" if a.序号 else "")
    if c.execute("select 1 from sources where source_id=?", (sid,)).fetchone():
        die(f"素材 {sid} 已存在(同一天同来源有多场时请加 --序号 2)")
    c.execute("insert into sources (source_id,来源,日期,标题,原片位置,本地文件夹,状态,创建时间,更新时间) values (?,?,?,?,?,?,?,?,?)",
              (sid, a.来源, a.日期, a.标题, a.原片位置, a.本地文件夹, a.状态, now(), now()))
    log(c, "source", sid, "新建", None, a.状态, a.by)
    c.commit()
    print(f"✅ 新建素材 {sid}")


CLIP_FIELDS = ["标题", "开头钩子", "概要", "理由", "起始", "结束", "原始时长_秒", "优先级", "选题类型", "钩子类型", "时效性"]


def cmd_add_clips(a):
    data = load_json(a.file)
    c = conn()
    src = row(c, "source", data["source_id"])
    pre = PREFIX[src["来源"]]
    day = src["日期"].replace("-", "")
    start = c.execute("select count(*) from clips where source_id=?", (src["source_id"],)).fetchone()[0]
    made = []
    for i, it in enumerate(data["clips"], start + 1):
        miss = [k for k in ("标题", "起始", "结束", "选题类型", "钩子类型") if not it.get(k)]
        if miss:
            die(f"第 {i - start} 条缺字段:{miss}")
        cid = f"{pre}-{day}-{i:02d}"
        c.execute("insert into clips (clip_id,来源,source_id,原编号,状态,重剪次数,创建时间,更新时间," +
                  ",".join(CLIP_FIELDS) + ") values (" + ",".join("?" * (8 + len(CLIP_FIELDS))) + ")",
                  (cid, src["来源"], src["source_id"], f"{day}-{i:02d}", "候选", 0, now(), now(),
                   *[it.get(k) for k in CLIP_FIELDS]))
        log(c, "clip", cid, "新建", None, "候选", "AI")
        made.append(cid)
    c.commit()
    print(f"✅ 写入 {len(made)} 条候选:" + ", ".join(made))


PUB_FIELDS = ["标题", "简介", "标签", "推荐", "标题句式", "封面类型", "文案标准版本"]


def cmd_add_pub(a):
    data = load_json(a.file)
    c = conn()
    clip = row(c, "clip", data["clip_id"])
    if clip["状态"] != "已通过":
        die(f"{clip['clip_id']} 是'{clip['状态']}',只有看片'已通过'的切片才能写文案")
    for it in data["publishes"]:
        pid = f"{clip['clip_id']}@{it['平台']}"
        if c.execute("select 1 from publishes where publish_id=?", (pid,)).fetchone():
            print(f"⚠️ {pid} 已存在,跳过(不覆盖用户可能改过的标题)")
            continue
        cands = it.get("候选标题", [])
        if len(cands) < 3:
            die(f"{pid}:候选标题至少 3 个")
        c.execute("insert into publishes (publish_id,clip_id,来源,平台,状态,候选标题,创建时间,更新时间," +
                  ",".join(PUB_FIELDS) + ") values (" + ",".join("?" * (8 + len(PUB_FIELDS))) + ")",
                  (pid, clip["clip_id"], clip["来源"], it["平台"], "草稿", json.dumps(cands, ensure_ascii=False),
                   now(), now(), *[it.get(k) for k in PUB_FIELDS]))
        log(c, "pub", pid, "新建", None, "草稿", "AI")
        print(f"✅ 新建发布草稿 {pid}")
    if data.get("封面字候选"):
        c.execute("update clips set 封面字候选=?, 封面字=coalesce(封面字,?), 封面道具=coalesce(封面道具,?), 更新时间=? where clip_id=?",
                  (json.dumps(data["封面字候选"], ensure_ascii=False), data["封面字候选"][0].get("文字"),
                   data["封面字候选"][0].get("道具"), now(), clip["clip_id"]))
    c.commit()


def cmd_add_metrics(a):
    data = load_json(a.file)
    c = conn()
    for m in data:
        row(c, "pub", m["publish_id"])
        if m.get("时间档") not in ("24h", "72h", "7d", "未标注"):
            die(f"{m['publish_id']}:时间档只能是 24h / 72h / 7d / 未标注")
        keys = ["播放", "完播率", "平均播放时长", "点赞", "评论", "收藏", "转发", "涨粉"]
        c.execute("insert or replace into metrics (publish_id,时间档," + ",".join(keys) + ",采集时间) values (" +
                  ",".join("?" * (len(keys) + 3)) + ")",
                  (m["publish_id"], m["时间档"], *[m.get(k) for k in keys], now()))
        log(c, "pub", m["publish_id"], "写入数据 " + m["时间档"], None, json.dumps({k: m.get(k) for k in keys}, ensure_ascii=False), "AI")
    c.commit()
    print(f"✅ 写入 {len(data)} 条数据")


def cmd_plan_slots(a):
    c = conn()
    s = CFG.get("发布排期", {"时间点": ["10:00", "12:00"], "最少提前小时": 2, "最多天数": 14})
    t = datetime.now(TZ)
    earliest, latest = t + timedelta(hours=s["最少提前小时"]), t + timedelta(days=s["最多天数"])
    taken = {}
    for r in c.execute("select 平台,发布时间 from publishes where 状态 in ('已定时','已发布') and 发布时间 is not null"):
        pt = parse_t(r[1])
        if pt:
            taken.setdefault(r[0], set()).add(pt.strftime("%Y-%m-%d %H:%M"))
    for r in c.execute("select publish_id,平台,发布时间 from publishes where 状态='待发布' order by 更新时间,publish_id"):
        pt = parse_t(r["发布时间"])
        if pt and earliest <= pt <= latest:
            print(f"SLOT {r['publish_id']} {pt.strftime('%Y-%m-%d %H:%M')} 已填(用户手填,原样尊重)")
            taken.setdefault(r["平台"], set()).add(pt.strftime("%Y-%m-%d %H:%M"))
            continue
        got = None
        for day in range(s["最多天数"] + 1):
            for hm in s["时间点"]:
                h, m = map(int, hm.split(":"))
                cand = (t + timedelta(days=day)).replace(hour=h, minute=m, second=0, microsecond=0)
                k = cand.strftime("%Y-%m-%d %H:%M")
                if earliest <= cand <= latest and k not in taken.get(r["平台"], set()):
                    got = k
                    break
            if got:
                break
        if got:
            taken.setdefault(r["平台"], set()).add(got)
            print(f"SLOT {r['publish_id']} {got} 排定")
        else:
            print(f"FULL {r['publish_id']} {s['最多天数']} 天内没有空位,应标需人工")


def main():
    p = argparse.ArgumentParser(description="视频剪辑 SOP 数据库操作入口")
    sp = p.add_subparsers(dest="cmd", required=True)
    sp.add_parser("migrate").set_defaults(f=cmd_migrate)
    sp.add_parser("init").set_defaults(f=cmd_init)
    sp.add_parser("summary").set_defaults(f=cmd_summary)
    x = sp.add_parser("next"); x.add_argument("--json", action="store_true"); x.set_defaults(f=cmd_next)
    x = sp.add_parser("show"); x.add_argument("kind", choices=FLOWS); x.add_argument("id"); x.set_defaults(f=cmd_show)
    x = sp.add_parser("list"); x.add_argument("kind", choices=FLOWS); x.add_argument("--status"); x.add_argument("--来源", dest="source_type"); x.set_defaults(f=cmd_list)
    x = sp.add_parser("set"); x.add_argument("kind", choices=FLOWS); x.add_argument("id"); x.add_argument("status")
    x.add_argument("--by", required=True); x.add_argument("--note"); x.set_defaults(f=cmd_set)
    x = sp.add_parser("update"); x.add_argument("kind", choices=FLOWS); x.add_argument("id"); x.add_argument("pairs", nargs="+")
    x.add_argument("--by", required=True); x.set_defaults(f=cmd_update)
    x = sp.add_parser("review"); x.add_argument("id"); x.add_argument("result", choices=["通过", "打回"])
    x.add_argument("--by", required=True); x.add_argument("--reason"); x.add_argument("--reviewer"); x.set_defaults(f=cmd_review)
    x = sp.add_parser("add-source")
    for k in ("来源", "日期", "标题"):
        x.add_argument("--" + k, required=True)
    for k in ("原片位置", "本地文件夹", "序号"):
        x.add_argument("--" + k)
    x.add_argument("--状态", default="已整理"); x.add_argument("--by", default="AI"); x.set_defaults(f=cmd_add_source)
    x = sp.add_parser("add-clips"); x.add_argument("file"); x.set_defaults(f=cmd_add_clips)
    x = sp.add_parser("add-pub"); x.add_argument("file"); x.set_defaults(f=cmd_add_pub)
    x = sp.add_parser("add-metrics"); x.add_argument("file"); x.set_defaults(f=cmd_add_metrics)
    sp.add_parser("plan-slots").set_defaults(f=cmd_plan_slots)
    a = p.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
