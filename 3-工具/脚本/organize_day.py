#!/usr/bin/env python3
"""⓪ 整理文件：把 ~/Movies 根目录里某一天的原始录制 mkv 归档。

用法:
  organize_day.py YYYYMMDD                 只出计划（不改任何文件）
  organize_day.py YYYYMMDD --run           执行
  --include "文件名" [--include ...]        把「跨天待确认」的文件明确纳入当天（老师确认后才加）
  --root DIR                               录像根目录，默认 ~/Movies（测试用）

结果:
  <root>/YYYYMMDD/原始文件/<名>.mkv   原片（最后才移动）
  <root>/YYYYMMDD/转录文件/<名>.mp4   ffmpeg -c copy 无损转封装

安全规则:
  - 只按文件名里的日期挑选，只处理指定那一天
  - 录制中（10 分钟内写入过 / 被程序占用）→ 跳过
  - 起始时间早于 06:00，或录制跨过午夜 → 标为「跨天待确认」，不处理，除非 --include
  - 同名目标已存在 → 不覆盖，只报告
  - 先转 mp4 并校验，通过后才把 mkv 移到 原始文件/；任何一步失败，原片留在原处
  - 不删除任何原片
"""
import argparse, os, re, subprocess, sys, time, json
from datetime import datetime
from pathlib import Path

os.environ["PATH"] = str(Path.home() / ".local/bin") + os.pathsep + os.environ.get("PATH", "")
NAME_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[ -](\d{2})-(\d{2})-(\d{2})\.mkv$", re.I)
EARLY_HOUR = 6          # 此时刻之前开始的录像，算不算前一天要老师确认
QUIET_SECONDS = 600     # 最近写入不足 10 分钟视为仍在录制
DUR_TOLERANCE = 1.0     # 秒


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=index,codec_type,codec_name,channels",
         "-of", "json", str(path)],
        capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError("ffprobe 失败: " + out.stderr.strip()[:200])
    d = json.loads(out.stdout)
    streams = d.get("streams", [])
    return {
        "duration": float(d["format"]["duration"]),
        "video": sum(1 for s in streams if s["codec_type"] == "video"),
        "audio": [s.get("channels") for s in streams if s["codec_type"] == "audio"],
        "other": sum(1 for s in streams if s["codec_type"] not in ("video", "audio")),
    }


def is_open(path):
    r = subprocess.run(["lsof", "--", str(path)], capture_output=True, text=True)
    return r.returncode == 0 and bool(r.stdout.strip())


def classify(root, day, includes):
    """返回 (待处理, 待确认, 跳过, 其他日期, 无法识别)"""
    todo, ask, skip, other, unknown = [], [], [], [], []
    for p in sorted(root.iterdir()):
        if not p.is_file() or p.suffix.lower() != ".mkv":
            continue
        m = NAME_RE.match(p.name)
        if not m:
            unknown.append(p.name)
            continue
        y, mo, d, hh, mi, ss = map(int, m.groups())
        fday = f"{y:04d}{mo:02d}{d:02d}"
        if fday != day:
            other.append((p.name, fday))
            continue
        st = p.stat()
        size = st.st_size
        start = datetime(y, mo, d, hh, mi, ss)
        end = datetime.fromtimestamp(st.st_mtime)
        info = {"name": p.name, "path": p, "size": size, "start": start, "end": end}
        # 录制中
        if time.time() - st.st_mtime < QUIET_SECONDS:
            skip.append((p.name, "10 分钟内仍有写入，可能还在录制"))
            continue
        if is_open(p):
            skip.append((p.name, "被程序占用，可能还在录制"))
            continue
        # 跨天
        reasons = []
        if hh < EARLY_HOUR:
            reasons.append(f"开始于 {hh:02d}:{mi:02d}，可能属于前一天")
        if end.date() != start.date():
            reasons.append(f"录制跨过午夜（结束于 {end:%m-%d %H:%M}）")
        if reasons and p.name not in includes:
            info["reasons"] = reasons
            ask.append(info)
            continue
        todo.append(info)
    return todo, ask, skip, other, unknown


def gb(n):
    return f"{n/1e9:.2f} GB"


def print_plan(root, day, todo, ask, skip, other, unknown):
    dayd = root / day
    print(f"录像根目录: {root}")
    print(f"目标日期: {day}  →  {dayd}/{{原始文件,转录文件}}")
    print(f"\n【将处理 {len(todo)} 个】")
    for t in todo:
        mp4 = dayd / "转录文件" / (Path(t["name"]).stem + ".mp4")
        mkv = dayd / "原始文件" / t["name"]
        note = ""
        if mp4.exists() or mkv.exists():
            note = "  ⚠ 目标已存在，将跳过不覆盖"
        print(f"  - {t['name']}  {gb(t['size'])}  {t['start']:%H:%M}→{t['end']:%H:%M}{note}")
    if ask:
        print(f"\n【跨天待确认 {len(ask)} 个（不会处理，除非你明确指定归到这一天）】")
        for t in ask:
            print(f"  - {t['name']}  {gb(t['size'])}：" + "；".join(t["reasons"]))
    if skip:
        print(f"\n【已跳过 {len(skip)} 个】")
        for n, why in skip:
            print(f"  - {n}：{why}")
    if unknown:
        print(f"\n【文件名无法识别日期，未处理 {len(unknown)} 个】")
        for n in unknown:
            print(f"  - {n}")
    if other:
        days = sorted({d for _, d in other})
        print(f"\n【根目录里还有其他日期的 mkv {len(other)} 个，未处理】日期: {', '.join(days)}")


def convert_one(t, dayd):
    src = t["path"]
    stem = src.stem
    out_dir, raw_dir = dayd / "转录文件", dayd / "原始文件"
    final_mp4 = out_dir / (stem + ".mp4")
    final_mkv = raw_dir / src.name
    if final_mp4.exists() or final_mkv.exists():
        return "跳过", "目标已存在，未覆盖"
    tmp = out_dir / f".{stem}.partial.mp4"
    if tmp.exists():
        tmp.unlink()
    try:
        r = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-i", str(src),
             "-map", "0", "-c", "copy", "-f", "mp4", str(tmp)],
            capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("无损封装失败（可能含 mp4 不支持的轨道）: " + r.stderr.strip()[:300])
        a, b = probe(src), probe(tmp)
        if a["video"] != b["video"] or a["audio"] != b["audio"] or a["other"] != b["other"]:
            raise RuntimeError(f"轨道不一致 源{a} → 目标{b}")
        if abs(a["duration"] - b["duration"]) > DUR_TOLERANCE:
            raise RuntimeError(f"时长不一致 源{a['duration']:.2f}s → 目标{b['duration']:.2f}s")
        os.rename(tmp, final_mp4)          # 校验通过才正式命名
        os.rename(src, final_mkv)          # 最后才移动原片
        return "完成", f"时长 {b['duration']:.1f}s，视频轨 {b['video']}，音轨 {len(b['audio'])}"
    except Exception as e:
        if tmp.exists():
            tmp.unlink()
        return "失败", str(e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("day", help="YYYYMMDD")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--include", action="append", default=[])
    ap.add_argument("--root", default=str(Path.home() / "Movies"))
    a = ap.parse_args()
    if not re.fullmatch(r"\d{8}", a.day):
        sys.exit("日期必须是 8 位数字 YYYYMMDD")
    try:
        datetime.strptime(a.day, "%Y%m%d")
    except ValueError:
        sys.exit("不是有效日期: " + a.day)
    root = Path(a.root)
    todo, ask, skip, other, unknown = classify(root, a.day, set(a.include))
    print_plan(root, a.day, todo, ask, skip, other, unknown)
    if not a.run:
        print("\n（仅计划，未改动任何文件。确认后加 --run 执行。）")
        return
    if not todo:
        print("\n没有可处理的文件，未创建任何文件夹。")
        return
    dayd = root / a.day
    (dayd / "原始文件").mkdir(parents=True, exist_ok=True)
    (dayd / "转录文件").mkdir(parents=True, exist_ok=True)
    print("\n== 执行结果")
    bad = 0
    for t in todo:
        status, msg = convert_one(t, dayd)
        bad += status == "失败"
        print(f"  [{status}] {t['name']}：{msg}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
