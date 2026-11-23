import json,sys,pathlib
def ts(t): t=int(t); return f"{t//3600:01d}:{t%3600//60:02d}:{t%60:02d}"
for f in sys.argv[1:]:
    d=json.load(open(f)); segs=d["segments"]; name=pathlib.Path(f).stem
    out=[f"##### FILE {name}"]; gaps=[]; buf=[]; bstart=None; prev_end=0
    for s in segs:
        if s["start"]-prev_end>60: gaps.append((ts(prev_end),ts(s["start"])))
        prev_end=s["end"]
        if bstart is None: bstart=s["start"]
        buf.append(s["text"].strip())
        if s["end"]-bstart>20:
            out.append(f"[{ts(bstart)}] "+" ".join(buf)); buf=[]; bstart=None
    if buf: out.append(f"[{ts(bstart)}] "+" ".join(buf))
    out.append(f"##### 静默>60s 区间: {gaps}")
    pathlib.Path(f).with_suffix(".compact.txt").write_text("\n".join(out))
    print(name, len(segs), "segs", "gaps:", len(gaps), gaps[:15])
