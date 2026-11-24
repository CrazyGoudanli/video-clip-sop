#!/usr/bin/env python3
"""环节 0 整理:把 `待加工/` 里的录像登记成一场"素材",准备好后续可处理的视频。

用法(在项目根目录):
  python3 3-工具/脚本/intake.py                       只看计划(不改任何文件)
  python3 3-工具/脚本/intake.py --json                同上,输出 JSON
  python3 3-工具/脚本/intake.py --run --source-id 课-20261124 文件1 [文件2 ...]
                                                     把这几个文件归到素材 课-20261124(素材需先用 db.py add-source 建好)

执行后:
  工作区/<素材ID>/转录文件/<名>.mp4   mkv 无损转封装成 mp4;mp4/mov/m4v 不复制,只放一个指向原片的链接
  待加工/已处理/<素材ID>/<原文件>      原片挪到这里(同一磁盘内移动,不复制、不删除)

安全规则:
  - 最近 10 分钟内还在写入、或被程序占用的文件:视为仍在录制,跳过
  - 目标已存在:不覆盖,跳过
  - mkv 先转 mp4 并核对轨道和时长,通过后才挪原片;任何一步失败,原片留在原处
  - 不转码重压,不删除任何原片
只用 Python 标准库 + ffprobe/ffmpeg。
"""
import argparse, json, os, re, subprocess, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ["PATH"] = str(Path.home() / ".local/bin") + os.pathsep + "/opt/homebrew/bin" + os.pathsep + \
    os.environ.get("PATH", "")
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".m4v"}
QUIET_SECONDS = 600
DUR_TOLERANCE = 1.0


def cfg():
    for n in ("配置.json", "配置模板.json"):
        p = ROOT / n
        if p.exists():
            return json.loads(p.read_text())
    return {}


def folder(key, default):
    p = Path(os.path.expanduser(cfg().get(key, default)))
    return p if p.is_absolute() else ROOT / p


INBOX = folder("待加工目录", "待加工")
WORK = folder("工作区目录", "工作区")
DONE = INBOX / "已处理"

# 文件名里的时间:DJI_20261119195939_0115_D.MP4 / 2026-11-24 14-03-22.mkv / IMG_20261124_140322.mp4 / 20261124…
NAME_PATTERNS = [
    re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})[_\- T]?(\d{2})(\d{2})(\d{2})(?!\d)"),
    re.compile(r"(?<!\d)(20\d{2})-(\d{2})-(\d{2})[ _T-](\d{2})[-:.](\d{2})[-:.](\d{2})"),
    re.compile(r"(?<!\d)(20\d{2})[-_.]?(\d{2})[-_.]?(\d{2})(?!\d)"),
]


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "format=duration:format_tags=creation_time:stream=index,codec_type,channels",
                          "-of", "json", str(path)], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError("ffprobe 读不了这个文件: " + out.stderr.strip()[:200])
    d = json.loads(out.stdout)
    st = d.get("streams", [])
    return {
        "duration": float(d.get("format", {}).get("duration") or 0),
        "creation_time": (d.get("format", {}).get("tags") or {}).get("creation_time"),
        "video": sum(1 for s in st if s["codec_type"] == "video"),
        "audio": [s.get("channels") for s in st if s["codec_type"] == "audio"],
    }


def start_time(p, info):
    """录像开始时间 + 依据。文件名 > 视频内的创建时间 > 文件修改时间减时长。"""
    for i, pat in enumerate(NAME_PATTERNS):
        m = pat.search(p.stem)
        if not m:
            continue
        g = list(map(int, m.groups())) + [0, 0, 0]
        try:
            return datetime(*g[:6]), "文件名" if i < 2 else "文件名(只有日期)"
        except ValueError:
            pass
    ct = info.get("creation_time")
    if ct:
        try:
            t = datetime.fromisoformat(ct.replace("Z", "+00:00"))
            if t.year > 2000:
                return t.astimezone().replace(tzinfo=None), "视频内创建时间"
        except ValueError:
            pass
    mt = datetime.fromtimestamp(p.stat().st_mtime)
    return mt - timedelta(seconds=info.get("duration", 0)), "文件修改时间(不太可靠)"


def busy(p):
    if time.time() - p.stat().st_mtime < QUIET_SECONDS:
        return "10 分钟内仍有写入,可能还在录制"
    r = subprocess.run(["lsof", "--", str(p)], capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return "被程序占用,可能还在录制或复制"
    return None


def scan():
    items = []
    if not INBOX.is_dir():
        return items
    for p in sorted(INBOX.iterdir()):
        if not p.is_file() or p.name.startswith(".") or p.suffix.lower() not in VIDEO_EXT:
            continue
        it = {"文件": p.name, "大小GB": round(p.stat().st_size / 1e9, 2)}
        why = busy(p)
        if why:
            it.update(状态="跳过", 原因=why)
            items.append(it)
            continue
        try:
            info = probe(p)
        except RuntimeError as e:
            it.update(状态="跳过", 原因=str(e))
            items.append(it)
            continue
        st, basis = start_time(p, info)
        it.update(状态="可处理", 时长分钟=round(info["duration"] / 60, 1), 开始=st.strftime("%Y-%m-%d %H:%M"),
                  日期=st.strftime("%Y-%m-%d"), 时间依据=basis, 视频轨=info["video"], 音轨=len(info["audio"]))
        if st.hour < 6:
            it["提醒"] = "开始于凌晨,可能属于前一天,请确认"
        items.append(it)
    return items


def print_plan(items):
    print(f"待加工文件夹: {INBOX}")
    if not items:
        print("(没有待处理的录像)")
        return
    ok = [i for i in items if i["状态"] == "可处理"]
    days = {}
    for i in ok:
        days.setdefault(i["日期"], []).append(i)
    for d, lst in sorted(days.items()):
        print(f"\n【{d}】{len(lst)} 个文件(同一天的文件,如果是同一场分段录制,请归到同一个素材)")
        for i in sorted(lst, key=lambda x: x["开始"]):
            note = f"  ⚠ {i['提醒']}" if i.get("提醒") else ""
            print(f"  - {i['文件']}  {i['大小GB']} GB  {i['时长分钟']} 分钟  开始 {i['开始']}(依据:{i['时间依据']}){note}")
    sk = [i for i in items if i["状态"] == "跳过"]
    if sk:
        print(f"\n【跳过 {len(sk)} 个】")
        for i in sk:
            print(f"  - {i['文件']}:{i['原因']}")
    print("\n(仅计划,未改动任何文件。)")


def run(sid, names):
    if not re.fullmatch(r"[^\s/]+-\d{8}(-\d+)?", sid):
        sys.exit(f"素材 ID 格式不对:{sid}(应类似 课-20261124 或 直-20261124-2)")
    dst = WORK / sid / "转录文件"
    done = DONE / sid
    bad = 0
    for n in names:
        src = INBOX / Path(n).name
        if not src.is_file():
            print(f"  [失败] {n}:待加工文件夹里没有这个文件")
            bad += 1
            continue
        why = busy(src)
        if why:
            print(f"  [跳过] {n}:{why}")
            continue
        ext = src.suffix.lower()
        final_raw = done / src.name
        final_mp4 = dst / (src.stem + (".mp4" if ext == ".mkv" else src.suffix))
        if final_raw.exists() or final_mp4.exists() or final_mp4.is_symlink():
            print(f"  [跳过] {n}:目标已存在,未覆盖")
            continue
        dst.mkdir(parents=True, exist_ok=True)
        done.mkdir(parents=True, exist_ok=True)
        try:
            if ext == ".mkv":
                tmp = dst / f".{src.stem}.partial.mp4"
                if tmp.exists():
                    tmp.unlink()
                r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(src), "-map", "0:v", "-map", "0:a?",
                                    "-c", "copy", "-f", "mp4", str(tmp)], capture_output=True, text=True)
                if r.returncode != 0:
                    tmp.unlink(missing_ok=True)
                    raise RuntimeError("无损转封装失败(可能含 mp4 不支持的轨道),需要用户决定: " + r.stderr.strip()[:300])
                a, b = probe(src), probe(tmp)
                if a["video"] != b["video"] or a["audio"] != b["audio"] or abs(a["duration"] - b["duration"]) > DUR_TOLERANCE:
                    tmp.unlink(missing_ok=True)
                    raise RuntimeError(f"转封装后轨道或时长不一致:源 {a} → 新 {b}")
                os.rename(tmp, final_mp4)
                os.rename(src, final_raw)          # 校验通过,最后才挪原片
                print(f"  [完成] {n}:已转成 {final_mp4.relative_to(ROOT)},原片在 {final_raw.relative_to(ROOT)}")
            else:
                os.rename(src, final_raw)          # 同一磁盘内移动,不复制
                os.symlink(os.path.relpath(final_raw, dst), final_mp4)   # 相对链接:项目整体挪位置也不断
                print(f"  [完成] {n}:原片在 {final_raw.relative_to(ROOT)},已在 {final_mp4.relative_to(ROOT)} 建链接")
        except Exception as e:
            bad += 1
            print(f"  [失败] {n}:{e}")
    sys.exit(1 if bad else 0)


def main():
    ap = argparse.ArgumentParser(description="整理 待加工/ 里的录像")
    ap.add_argument("files", nargs="*")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--source-id")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.run:
        if not a.source_id or not a.files:
            sys.exit("--run 需要 --source-id 和至少一个文件名")
        run(a.source_id, a.files)
        return
    items = scan()
    if a.json:
        print(json.dumps(items, ensure_ascii=False, indent=1))
    else:
        print_plan(items)


if __name__ == "__main__":
    main()
