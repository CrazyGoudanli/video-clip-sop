import json,sys
def hms(t): return f"{int(t)//3600}:{int(t)%3600//60:02d}:{t%60:05.2f}"
def sec(s):
    p=[float(x) for x in s.split(":")]; return p[0]*3600+p[1]*60+p[2]
f=sys.argv[1]; d=json.load(open(f))
for rng in sys.argv[2:]:
    a,b=[sec(x) for x in rng.split("-")]
    print(f"=== {rng}")
    for s in d["segments"]:
        if s["end"]>=a-8 and s["start"]<=b+8: print(f"{hms(s['start'])}-{hms(s['end'])} {s['text']}")
