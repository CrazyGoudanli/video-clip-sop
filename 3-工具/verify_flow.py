#!/usr/bin/env python3
"""项目自检:能不能跑通。不处理真实视频,真实数据库不会被修改。
A 文件与配置  B 数据库一致性(只读)  C 在数据库副本上用 db.py 模拟一条切片走完全流程(含应被拒绝的操作)
D 本机环境(按 配置.json 选择的工具检查)
用法: python3 3-工具/verify_flow.py
"""
import json, os, pathlib, re, shutil, sqlite3, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
DBPY = ROOT / "3-工具" / "db.py"
res = []


def check(name, ok, detail="", level="❌"):
    res.append((name, ok, level))
    print(("✅ " if ok else level + " ") + name + (f"  —— {detail}" if detail else ""))


print("== A 文件与配置")
need = ["AGENTS.md", "CLAUDE.md", "README.md", "配置模板.json", "启动问卷.md", "1-流程/业务流程.md",
        *[f"2-标准/{n}.md" for n in ("选题标准", "剪辑标准", "文案标准", "封面标准", "复盘标准", "平台规则", "标准修改规则")],
        *[f"3-工具/环节/{n}.md" for n in ("0-整理", "1-复盘选片", "2-剪辑", "3-看片", "4-文案", "5-封面", "6-发布", "7-数据复盘")],
        "3-工具/db.py", "3-工具/watch.py", "3-工具/脚本/intake.py", "3-工具/check_env.py", "3-工具/脚本/transcribe.sh",
        "3-工具/脚本/compact.py", "3-工具/脚本/segs.py", "3-工具/脚本/make_covers.py", "3-工具/模板/cover_prompt.md",
        "3-工具/工作台/server.py", "3-工具/工作台/index.html", "3-工具/脚本/autorun.sh"]
miss = [f for f in need if not (ROOT / f).exists()]
check("A1 必需文件齐全", not miss, "缺:" + ",".join(miss) if miss else f"{len(need)} 个")
cfgp = ROOT / "配置.json"
check("A2 已生成 配置.json(否则先按启动问卷询问用户)", cfgp.exists())
cfg = json.loads(cfgp.read_text()) if cfgp.exists() else {}
tpl = json.loads((ROOT / "配置模板.json").read_text())
lack = [k for k in tpl if k not in ("版本", "说明") and k not in cfg]
check("A3 配置.json 含模板的全部变量", not lack, "缺:" + ",".join(lack) if lack else "")
tool = cfg.get("剪辑工具", "ffmpeg")
check("A4 选定剪辑工具有对应说明", (ROOT / f"3-工具/工具说明/剪辑_{tool}.md").exists(), tool)
txt = "\n".join((ROOT / f).read_text() for f in need if f.startswith(("1-流程/业务流程", "2-标准/")))
leak = sorted(set(re.findall(r"(?i)chatcut|notion|codex|claude|mcp|ffmpeg|whisper|sqlite", txt)))
check("A5 流程层和标准层不含工具名(换工具不用改)", not leak, ",".join(leak))

print("\n== B 数据库一致性(只读)")
sys.path.insert(0, str(ROOT / "3-工具"))
import db  # noqa: E402
if not db.DB.exists():
    check("B0 数据库已建好", False, "先运行 python3 3-工具/db.py init(或 check_env.py --fix),再重新自检")
    print("\n数据库还没建,后面的检查跳过。")
    sys.exit(1)
c = sqlite3.connect(f"file:{db.DB}?mode=ro", uri=True)
q = lambda s, *a: c.execute(s, a).fetchall()
have = [r[1] for r in q("pragma table_info(clips)")]
miss = [k for k in db.NEW_COLUMNS["clips"] if k not in have]
check("B1 数据库已迁移到最新结构", not miss and q("select count(*) from sqlite_master where name='events'")[0][0] == 1,
      "请运行 db.py migrate" if miss else "")
for name, t, flow in (("素材", "sources", db.SOURCE_FLOW), ("切片", "clips", db.CLIP_FLOW), ("发布", "publishes", db.PUB_FLOW)):
    bad = [r[0] for r in q(f"select distinct 状态 from {t}") if r[0] not in flow]
    check(f"B2 {name}状态都在状态机定义里", not bad, ",".join(map(str, bad)))
check("B3 每条发布都对应切片", q("select count(*) from publishes p left join clips k on k.clip_id=p.clip_id where k.clip_id is null")[0][0] == 0)
check("B4 每条切片都挂在素材下", q("select count(*) from clips k left join sources s on s.source_id=k.source_id where s.source_id is null")[0][0] == 0)
rows = q("select distinct p.clip_id from publishes p join clips k on k.clip_id=p.clip_id where k.状态!='已通过' and p.状态!='已废弃'")
check("B5 有效发布记录的切片都已通过看片", not rows, ",".join(r[0] for r in rows))
n = q("select count(*) from publishes where 状态='已发布' and coalesce(作品链接,'')=''")[0][0]
check("B6 已发布记录都有作品链接", n == 0, f"{n} 条缺链接(历史数据;待办里会提示补)", level="⚠️")
n = q("select count(*) from clips where 状态='已通过' and 成片时长_秒 is null")[0][0]
check("B7 已通过的切片都有成片时长", n == 0, f"{n} 条缺")
c.close()

print("\n== C 在数据库副本上模拟全流程(调用 db.py,真实库不动)")
tmpd = pathlib.Path(tempfile.mkdtemp())
sim = tmpd / "sim.db"
shutil.copy(db.DB, sim)
env = {**os.environ, "SOP_DB": str(sim)}


def run(*args):
    p = subprocess.run([sys.executable, "-I", str(DBPY), *args], capture_output=True, text=True, env=env)
    return p.returncode, (p.stdout + p.stderr).strip()


def expect(label, args, ok=True, contains=None):
    rc, out = run(*args)
    good = (rc == 0) == ok and (contains is None or contains in out)
    check("C " + label, good, "" if good else out.splitlines()[-1][:150] if out else f"rc={rc}")


def state(kind, oid):
    s = sqlite3.connect(sim)
    t, k, _ = db.FLOWS[kind]
    r = s.execute(f"select 状态 from {t} where {k}=?", (oid,)).fetchone()
    s.close()
    return r[0] if r else None


def in_next(stage, oid):
    rc, out = run("next", "--json")
    return any(x["环节"] == stage and oid in x["对象"] for x in json.loads(out))


def j(name, obj):
    (tmpd / name).write_text(json.dumps(obj, ensure_ascii=False))
    return str(tmpd / name)
expect("新建素材", ["add-source", "--来源", "课程", "--日期", "2099-01-01", "--标题", "模拟", "--状态", "已整理"])
check("C 素材已整理 → 待办出现 1-复盘选片", in_next("1-复盘选片", "课-20990101"))
clip = {"标题": "模拟切片", "起始": "00:01:00", "结束": "00:02:20", "选题类型": "故事", "钩子类型": "提问"}
expect("写入候选切片(编号自动带来源前缀)", ["add-clips", j("c.json", {"source_id": "课-20990101", "clips": [clip]})], contains="课-20990101-01")
T = "课-20990101-01"
expect("复盘完成", ["set", "source", "课-20990101", "已复盘", "--by", "AI"])
check("C 候选 → 出现在'人工-挑选',不在剪辑待办", in_next("人工-挑选", T) and not in_next("2-剪辑", T))
expect("AI 不能代替用户挑选(候选→待剪 被拒)", ["set", "clip", T, "待剪", "--by", "AI"], ok=False, contains="人工关卡")
expect("用户挑选:候选→待剪", ["set", "clip", T, "待剪", "--by", "人工"])
check("C 待剪 → 出现在 2-剪辑 待办", in_next("2-剪辑", T))
expect("AI 领取:待剪→剪辑中", ["set", "clip", T, "剪辑中", "--by", "AI"])
check("C 剪辑中 → 不重复出现在剪辑待办", not in_next("2-剪辑", T))
expect("没登记成片文件不能提交看片", ["set", "clip", T, "已剪辑", "--by", "AI"], ok=False, contains="成片文件")
expect("登记成片(时长 45 秒)", ["update", "clip", T, "成片文件=/tmp/x.mp4", "成片时长_秒=45", "--by", "AI"])
expect("时长 45 秒不达标,不能提交看片", ["set", "clip", T, "已剪辑", "--by", "AI"], ok=False, contains="不得提交看片")
expect("时长不达标 → 重剪(计入重剪次数)", ["set", "clip", T, "待剪", "--by", "AI", "--note", "时长不达标"])
expect("再次领取", ["set", "clip", T, "剪辑中", "--by", "AI"])
expect("登记成片(时长 75 秒)", ["update", "clip", T, "成片时长_秒=75", "--by", "AI"])
expect("提交看片:剪辑中→已剪辑", ["set", "clip", T, "已剪辑", "--by", "AI"])
check("C 已剪辑 → 出现在'3-看片'(人工),文案环节不拾取", in_next("3-看片", T) and not in_next("4-文案", T))
expect("AI 不能代替看片(review --by AI 被拒)", ["review", T, "通过", "--by", "AI"], ok=False)
expect("打回必须写原因", ["review", T, "打回", "--by", "人工"], ok=False, contains="原因")
expect("看片打回(第 2 次重剪)", ["review", T, "打回", "--by", "人工", "--reason", "00:10 字幕错字"])
check("C 打回后回到'待剪',并带打回原因", state("clip", T) == "待剪")
expect("领取", ["set", "clip", T, "剪辑中", "--by", "AI"])
expect("提交", ["set", "clip", T, "已剪辑", "--by", "AI"])
expect("看片通过", ["review", T, "通过", "--by", "人工", "--reviewer", "测试"])
check("C 通过 → 4-文案 待办", in_next("4-文案", T))
pub = {"clip_id": T, "publishes": [{"平台": "抖音", "标题": "模拟标题", "候选标题": ["A", "B", "C"], "推荐": "A"}],
       "封面字候选": [{"文字": "两行\n【字】", "道具": "方案册"}]}
expect("写发布草稿", ["add-pub", j("p.json", pub)])
P = T + "@抖音"
check("C 草稿 → 不再出现在文案待办,出现在 5-封面", not in_next("4-文案", T) and in_next("5-封面", P))
# 封面三步:无候选 → 5-封面;有候选未选 → 人工-选封面;已选竖缺横 → 5-封面;竖横齐 → 人工-审核发布
cover_home = tmpd / "成片模拟"
(cover_home / "封面" / "候选").mkdir(parents=True)
expect("设定切片本地文件夹(绝对路径)", ["update", "clip", T, f"本地文件夹={cover_home}", "--by", "AI"])
check("C 无候选图 → 出现在 5-封面", in_next("5-封面", P) and not in_next("人工-选封面", P))
(cover_home / "封面" / "候选" / "x.png").write_bytes(b"")
check("C 有候选未选 → 出现在'人工-选封面'", in_next("人工-选封面", P) and not in_next("5-封面", P))
v_pick = str(cover_home / "封面" / "候选" / "x.png")
expect("用户选定竖封面", ["update", "pub", P, f"封面竖={v_pick}", "--by", "人工"])
check("C 已选竖缺横 → 又出现在 5-封面", in_next("5-封面", P) and not in_next("人工-选封面", P) and not in_next("人工-审核发布", P))
expect("登记横版封面", ["update", "pub", P, "封面横=/tmp/b.jpg", "包装标准版本=v2", "--by", "AI"])
check("C 封面齐 → 出现在'人工-审核发布',发布环节不拾取", in_next("人工-审核发布", P) and not in_next("6-发布", P))
expect("AI 不能代替用户授权发布(草稿→待发布 被拒)", ["set", "pub", P, "待发布", "--by", "AI"], ok=False, contains="人工关卡")
expect("用户授权:草稿→待发布", ["set", "pub", P, "待发布", "--by", "人工"])
check("C 待发布 → 6-发布 待办", in_next("6-发布", P))
rc, out = run("plan-slots")
check("C 排期给出时间", rc == 0 and f"SLOT {P}" in out, out.splitlines()[0] if out else "")
expect("不能跳过定时直接'已发布'", ["set", "pub", P, "已发布", "--by", "AI"], ok=False)
expect("记录定时时间(过去时间,模拟已到点)", ["update", "pub", P, "发布时间=2000-01-01T10:00:00+08:00", "--by", "AI"])
expect("待发布→已定时", ["set", "pub", P, "已定时", "--by", "AI"])
check("C 到点 → 7-数据复盘 待办(回填链接)", in_next("7-数据复盘", P))
expect("回填链接", ["update", "pub", P, "作品链接=https://example.test/v", "--by", "AI"])
expect("已定时→已发布", ["set", "pub", P, "已发布", "--by", "AI"])
expect("写入 72h 数据", ["add-metrics", j("m.json", [{"publish_id": P, "时间档": "24h", "播放": 100}])])
s = sqlite3.connect(sim)
v = s.execute("select 来源,平台,选题类型,播放 from v_performance where publish_id=?", (P,)).fetchone()
check("C 分析视图能按来源/平台/选题查到这条作品的数据", v is not None and v[3] == 100, str(v))
# 重剪上限
s.execute("insert into clips (clip_id,来源,source_id,状态,重剪次数) values ('课-20990101-02','课程','课-20990101','剪辑中',2)")
s.commit(); s.close()
expect("累计第 3 次重剪 → 自动转需人工", ["set", "clip", "课-20990101-02", "待剪", "--by", "AI"])
check("C 重剪上限生效", state("clip", "课-20990101-02") == "需人工")
check("C 需人工 → 出现在'人工-需人工'提示", in_next("人工-需人工", "切片 课-20990101-02"))
# 已废弃
s = sqlite3.connect(sim)
s.execute("insert into publishes (publish_id,clip_id,来源,平台,状态) values ('课-20990101-01@测试','课-20990101-01','课程','抖音','草稿')")
s.commit(); s.close()
expect("用户废弃草稿:草稿→已废弃", ["set", "pub", "课-20990101-01@测试", "已废弃", "--by", "人工"])
check("C 已废弃 → 不出现在封面/审核/发布待办", not any(in_next(st, "课-20990101-01@测试") for st in ("5-封面", "人工-审核发布", "6-发布")))
s = sqlite3.connect(sim)
n = s.execute("select count(*) from events where 对象ID like '%20990101%'").fetchone()[0]
s.close()
check("C 每次修改都留了记录(events)", n >= 20, f"{n} 条")
# AI 代审:开关关着时 AI 代审被拒;打开后才放行,并记为 AI代审
s = sqlite3.connect(sim)
s.execute("insert into clips (clip_id,来源,source_id,状态,重剪次数) values ('课-20990101-03','课程','课-20990101','候选',0)")
s.commit(); s.close()
gcfg = tmpd / "cfg.json"
base = json.loads((ROOT / ("配置.json" if (ROOT / "配置.json").exists() else "配置模板.json")).read_text())
gcfg.write_text(json.dumps({**base, "AI代审": {"挑选": False}}, ensure_ascii=False))
env["SOP_CFG"] = str(gcfg)
expect("代审开关关着:AI代审 挑选 → 被拒绝", ["set", "clip", "课-20990101-03", "待剪", "--by", "AI代审"], ok=False)
check("C 代审开关关着 → 待办仍是'人工-挑选'", in_next("人工-挑选", "课-20990101-03"))
gcfg.write_text(json.dumps({**base, "AI代审": {"挑选": True}}, ensure_ascii=False))
check("C 代审开关打开 → 待办变成'代审-挑选'(AI)", in_next("代审-挑选", "课-20990101-03") and not in_next("人工-挑选", "课-20990101-03"))
expect("代审开关打开:AI代审 挑选 → 放行", ["set", "clip", "课-20990101-03", "待剪", "--by", "AI代审"])
s = sqlite3.connect(sim)
s.execute("insert into publishes (publish_id,clip_id,来源,平台,状态) values ('课-20990101-03@测试','课-20990101-03','课程','抖音','草稿')")
s.commit(); s.close()
expect("只开了挑选:AI代审 确认发布 → 仍被拒绝", ["set", "pub", "课-20990101-03@测试", "待发布", "--by", "AI代审"], ok=False,
       contains="人工关卡")
s = sqlite3.connect(sim)
who = s.execute("select 操作者 from events where 对象ID='课-20990101-03' order by id desc limit 1").fetchone()[0]
s.close()
check("C 代审的操作记为'AI代审'", who == "AI代审", who)
env.pop("SOP_CFG")
shutil.rmtree(tmpd)

print("\n== D 本机环境(详见 python3 3-工具/check_env.py)")
r = subprocess.run([sys.executable, str(ROOT / "3-工具" / "check_env.py"), "--json"], capture_output=True, text=True)
try:
    for it in json.loads(r.stdout):
        check(f"D {it['分组']}:{it['项目']}", it["通过"],
              "" if it["通过"] else f"[{it['谁来']}] {it['处理']}", level=it["级别"] if it["级别"] != "✅" else "❌")
except Exception as e:
    check("D 运行 check_env.py", False, str(e))

fails = [r for r in res if not r[1] and r[2] == "❌"]
warns = [r for r in res if not r[1] and r[2] == "⚠️"]
print(f"\n共 {len(res)} 项:通过 {len(res) - len(fails) - len(warns)},警告 {len(warns)},失败 {len(fails)}。真实数据库未被修改。")
sys.exit(1 if fails else 0)
