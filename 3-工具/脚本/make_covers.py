"""生成多平台高质感封面（不含期号/日期）：支持 3:4、4:3、9:16、16:9。
用法:
  uv run --with pillow python3 3-工具/脚本/make_covers.py <copy.json>
每个 item 需要: id, cover_title（\\n 换行, 【】高亮）, cover_sub, cover_frame（可选图片或视频路径）
当 mode == "candidates" 时，输出 3 张风格截然不同的高质量候选封面（安全区留白，绝不截字）：
  - a_黑金电影.png : 深曜石暖金光晕 + 极简排版线 + 金色发光焦点块
  - b_瑞士亮白.png : 高级温润纸白底 + 粗黑高反差大字 + 朱砂红强调底块
  - c_实拍剧照.png : 从成片抽取清晰关键帧（或深蓝紫赛博渐变）+ 电影暗角渐变 + 居中爆款大字
"""
import json, math, os, re, subprocess, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

GOLD = (245, 190, 72)
GOLD_BRIGHT = (254, 232, 148)
CRIMSON = (220, 38, 38)
CYAN = (56, 189, 248)
WHITE = (255, 255, 255)
INK = (18, 20, 26)
PAPER = (246, 243, 236)
BG_TOP, BG_BOT = (8, 11, 18), (18, 23, 36)

FONT_CANDIDATES_BOLD = [
    ("/System/Library/Fonts/PingFang.ttc", 8),
    ("/System/Library/Fonts/PingFang.ttc", 6),
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", 2),
    ("/System/Library/Fonts/STHeiti Medium.ttc", 0),
]
FONT_CANDIDATES_REG = [
    ("/System/Library/Fonts/PingFang.ttc", 2),
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0),
    ("/System/Library/Fonts/STHeiti Light.ttc", 0),
]

RATIO_SIZES = {
    "3:4": (1080, 1440),
    "4:3": (1440, 1080),
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
}


def font(size, bold=True):
    for p, idx in (FONT_CANDIDATES_BOLD if bold else FONT_CANDIDATES_REG):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size, index=idx)
            except Exception:
                pass
    return ImageFont.load_default()


def gradient(w, h, top=BG_TOP, bot=BG_BOT):
    im = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(im)
    for y in range(h):
        t = y / max(1, h - 1)
        d.line([(0, y), (w, y)], fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
    return im


def add_radial_glow(canvas, cx, cy, radius, rgb, max_alpha=95):
    w, h = canvas.size
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    steps = 18
    for i in range(steps, 0, -1):
        r = int(radius * i / steps)
        a = int(max_alpha * ((1 - i / steps) ** 1.6))
        if a <= 0:
            continue
        gd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*rgb, a))
    glow = glow.filter(ImageFilter.GaussianBlur(max(12, radius // 10)))
    canvas.paste(glow, (0, 0), glow)


def segments(line, normal=WHITE, accent=GOLD):
    out = []
    for p in re.split(r"(【[^】]*】)", line):
        if not p:
            continue
        out.append((p[1:-1], accent, True) if p.startswith("【") else (p, normal, False))
    return out


def line_width(d, line, f):
    return sum(d.textlength(t, font=f) for t, _, _ in segments(line))


def fit_size(d, lines, max_w, start):
    s = start
    while s > 34 and max(line_width(d, l, font(s)) for l in lines) > max_w:
        s -= 4
    return s


def draw_title(canvas, lines, box, start_size, align="center", normal=WHITE, accent=GOLD, pill_accent=None, shadow_alpha=175):
    """box=(x0,y0,x1,y1) 内垂直居中绘制标题，严格保证上下左右绝不越界截断。"""
    d = ImageDraw.Draw(canvas)
    x0, y0, x1, y1 = box
    s = fit_size(d, lines, x1 - x0, start_size)
    # 防止行数过多溢出高度
    while s > 34 and int(s * 1.28) * len(lines) > (y1 - y0):
        s -= 4
    f = font(s)
    lh = int(s * 1.28)
    total = lh * len(lines)
    y_start = y0 + max(0, (y1 - y0 - total) // 2)

    if shadow_alpha > 0:
        shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        y = y_start
        for ln in lines:
            w = line_width(d, ln, f)
            x = x0 + ((x1 - x0 - w) / 2 if align == "center" else 0)
            cx = x
            for t, _, _ in segments(ln, normal, accent):
                sd.text((cx + 3, y + 6), t, font=f, fill=(0, 0, 0, shadow_alpha))
                cx += d.textlength(t, font=f)
            y += lh
        blur = shadow.filter(ImageFilter.GaussianBlur(10))
        canvas.paste(blur, (0, 0), blur)

    y = y_start
    d = ImageDraw.Draw(canvas)
    for ln in lines:
        w = line_width(d, ln, f)
        x = x0 + ((x1 - x0 - w) / 2 if align == "center" else 0)
        for t, c, is_acc in segments(ln, normal, accent):
            tw = d.textlength(t, font=f)
            if is_acc and pill_accent:
                pad_x, pad_y = int(s * 0.14), int(s * 0.08)
                x += int(s * 0.1)
                d.rounded_rectangle(
                    (x - pad_x // 2, y - pad_y, x + tw + pad_x // 2, y + int(s * 1.12) + pad_y),
                    radius=max(10, s // 9),
                    fill=pill_accent,
                )
                fill_col = WHITE
                d.text((x, y), t, font=f, fill=fill_col, stroke_width=max(1, s // 56), stroke_fill=fill_col)
                x += tw + int(s * 0.12)
                continue
            else:
                fill_col = c
            d.text((x, y), t, font=f, fill=fill_col, stroke_width=max(1, s // 56), stroke_fill=fill_col)
            x += tw
        y += lh


def sub(canvas, xy_center_y, text, x0, x1, size=28, fill=(170, 175, 190)):
    if not text:
        return
    d = ImageDraw.Draw(canvas)
    f = font(size, False)
    spaced = " ".join(text) if len(text) <= 16 else text
    w = d.textlength(spaced, font=f)
    d.text((x0 + (x1 - x0 - w) / 2, xy_center_y), spaced, font=f, fill=fill)


def hairline(canvas, y, x0, x1, color=GOLD, bg=BG_BOT):
    d = ImageDraw.Draw(canvas)
    mid = (x0 + x1) / 2
    span = max(1, mid - x0)
    for x in range(int(x0), int(x1)):
        a = max(0.0, 1 - abs(x - mid) / span)
        col = tuple(int(color[i] * a + bg[i] * (1 - a)) for i in range(3))
        d.point((x, y), fill=col)
        d.point((x, y + 1), fill=col)


def photo_fit(img, w, h):
    r = max(w / img.width, h / img.height)
    im = img.resize((int(img.width * r + 1), int(img.height * r + 1)), Image.LANCZOS)
    l = (im.width - w) // 2
    t = (im.height - h) // 2
    return im.crop((l, t, l + w, t + h))


def extract_video_frame(base_dir):
    """尝试抽取干净的实拍画面作为剧照底图（若来源是 9:16 包装成片，自动裁取中间干净的 16:9 人物画幅，杜绝重影）。"""
    clip_dir = Path(base_dir).resolve().parents[1]
    mp4s = [p for p in clip_dir.glob("*.mp4") if "Remotion" not in p.name] or list(clip_dir.glob("*.mp4"))
    if not mp4s:
        return None
    tmp = Path("/tmp") / f"cover_frame_{os.getpid()}.jpg"
    try:
        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-ss", "12", "-i", str(mp4s[0]), "-frames:v", "1", "-q:v", "2", "-y", str(tmp)],
            capture_output=True, timeout=15,
        )
        if tmp.exists() and tmp.stat().st_size > 1000:
            im = Image.open(tmp).convert("RGB")
            tmp.unlink(missing_ok=True)
            # 若是 9:16 竖屏成片（1080x1920），裁出中间干净的视频窗口区域（无顶底标题字幕重影）
            if im.height > im.width * 1.4:
                y0, y1 = int(im.height * 0.315), int(im.height * 0.655)
                im = im.crop((0, y0, im.width, y1))
            return im
    except Exception:
        pass
    return None


def make(item, outdir):
    frame = Image.open(item["cover_frame"]).convert("RGB")
    lines = item["cover_title"].split("\n")
    res = {}

    c = gradient(1080, 1920)
    c.paste(photo_fit(frame, 1080, 668), (0, 420))
    hairline(c, 418, 40, 1040); hairline(c, 1088, 40, 1040)
    draw_title(c, lines, (64, 1130, 1016, 1480), 116)
    sub(c, 1500, item.get("cover_sub", ""), 0, 1080)
    p = f"{outdir}/{item['id']}_9x16.jpg"; c.save(p, quality=92); res["9x16"] = p

    c = gradient(1080, 1440)
    draw_title(c, lines, (64, 160, 1016, 520), 124)
    sub(c, 536, item.get("cover_sub", ""), 0, 1080, 26)
    c.paste(photo_fit(frame, 1080, 800), (0, 640))
    hairline(c, 638, 40, 1040)
    p = f"{outdir}/{item['id']}_3x4.jpg"; c.save(p, quality=92); res["3x4"] = p

    c = gradient(1920, 1080)
    c.paste(photo_fit(frame, 1080, 1080), (0, 0))
    fade = Image.new("L", (300, 1080))
    for x in range(300):
        ImageDraw.Draw(fade).line([(x, 0), (x, 1080)], fill=int(255 * x / 299))
    c.paste(gradient(300, 1080), (780, 0), fade)
    draw_title(c, lines, (1060, 290, 1860, 780), 126)
    sub(c, 800, item.get("cover_sub", ""), 1080, 1860, 26)
    p = f"{outdir}/{item['id']}_16x9.jpg"; c.save(p, quality=92); res["16x9"] = p
    return res


def render_style_a(w, h, lines):
    """风格 A · 黑金电影感：深曜石底 + 暖金光晕 + 几何坐标框 + 大字金白撞色"""
    c = gradient(w, h, (7, 9, 15), (16, 20, 32))
    add_radial_glow(c, int(w * 0.5), int(h * 0.25), int(w * 0.62), GOLD, 80)
    add_radial_glow(c, int(w * 0.5), int(h * 0.78), int(w * 0.5), CYAN, 42)
    d = ImageDraw.Draw(c)
    # 细腻安全区边框
    pad = int(w * 0.055)
    d.rounded_rectangle((pad, pad, w - pad, h - pad), radius=34, outline=(56, 62, 82), width=2)
    # 顶部光条
    d.rounded_rectangle((int(w * 0.36), pad + 42, int(w * 0.64), pad + 50), radius=4, fill=GOLD)
    # 留足上下安全距的主标题（绝不截断！）
    draw_title(c, lines, (int(w * 0.08), int(h * 0.14), int(w * 0.92), int(h * 0.52)), int(w * 0.145), normal=WHITE, accent=GOLD_BRIGHT)
    hairline(c, int(h * 0.56), int(w * 0.14), int(w * 0.86), color=GOLD, bg=(12, 16, 26))
    # 下半区：高级金色极简同心罗盘几何构图
    cx, cy, R = w // 2, int(h * 0.76), int(min(w, h) * 0.185)
    d = ImageDraw.Draw(c)
    for rr, col, wd in ((R + 46, (38, 46, 66), 2), (R + 22, (74, 64, 42), 2), (R, GOLD, 5)):
        d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), outline=col, width=wd)
    for k in range(12):
        a = k * math.pi / 6
        r1 = R - (24 if k % 3 == 0 else 14)
        d.line((cx + math.sin(a) * r1, cy - math.cos(a) * r1, cx + math.sin(a) * (R - 4), cy - math.cos(a) * (R - 4)), fill=GOLD, width=4)
    d.polygon(((cx, cy - int(R * 0.72)), (cx - int(R * 0.2), cy + int(R * 0.08)), (cx, cy - int(R * 0.04))), fill=GOLD_BRIGHT)
    d.polygon(((cx, cy - int(R * 0.72)), (cx + int(R * 0.2), cy + int(R * 0.08)), (cx, cy - int(R * 0.04))), fill=WHITE)
    d.polygon(((cx, cy + int(R * 0.72)), (cx - int(R * 0.2), cy + int(R * 0.08)), (cx, cy - int(R * 0.04)), (cx + int(R * 0.2), cy + int(R * 0.08))), fill=(82, 92, 114))
    d.ellipse((cx - 10, cy - 10, cx + 10, cy + 10), fill=GOLD)
    return c


def render_style_b(w, h, lines):
    """风格 B · 瑞士亮白杂志风：高级米白底 + 深炭黑粗排版 + 朱砂红强反差标签块"""
    c = gradient(w, h, PAPER, (236, 231, 221))
    d = ImageDraw.Draw(c)
    # 顶部强视觉朱砂红装饰色带
    d.rectangle((0, 0, w, 24), fill=CRIMSON)
    pad = int(w * 0.075)
    # 左对齐杂志式粗线结构
    d.rectangle((pad, int(h * 0.11), pad + 128, int(h * 0.11) + 14), fill=CRIMSON)
    draw_title(
        c, lines,
        (pad, int(h * 0.16), w - pad, int(h * 0.58)),
        int(w * 0.145),
        align="left",
        normal=INK,
        accent=CRIMSON,
        pill_accent=CRIMSON,
        shadow_alpha=0,
    )
    # 中部分割粗黑线
    d.rectangle((pad, int(h * 0.62), w - pad, int(h * 0.62) + 5), fill=INK)
    # 下半区：瑞士包豪斯几何色块构图（完全不同于暗黑风格）
    by = int(h * 0.68)
    bh = int(h * 0.23)
    bw = w - 2 * pad
    d.rounded_rectangle((pad, by, pad + int(bw * 0.56), by + bh), radius=24, fill=INK)
    # 深黑卡片内的极简斜向箭头与光点
    ax0, ay0 = pad + 48, by + bh - 54
    ax1, ay1 = pad + int(bw * 0.56) - 56, by + 54
    d.line((ax0, ay0, ax1, ay1), fill=GOLD, width=14)
    d.polygon(((ax1, ay1), (ax1 - 54, ay1 + 4), (ax1 - 8, ay1 + 54)), fill=GOLD)
    # 右侧朱砂红圆块 + 粗黑方框叠加
    rx0 = pad + int(bw * 0.61)
    d.rounded_rectangle((rx0, by, w - pad, by + bh), radius=24, outline=INK, width=5)
    rcx, rcy, rr = (rx0 + w - pad) // 2, by + bh // 2, int(min(bh, w - pad - rx0) * 0.34)
    d.ellipse((rcx - rr, rcy - rr, rcx + rr, rcy + rr), fill=CRIMSON)
    d.ellipse((rcx - rr // 2, rcy - rr // 2, rcx + rr // 2, rcy + rr // 2), fill=PAPER)
    return c


def render_style_c(w, h, lines, frame_img=None):
    """风格 C · 实拍剧照压字（或蓝紫赛博玻璃态）：视觉冲击最强，贴近抖音高点击率爆款"""
    if frame_img is not None:
        c = photo_fit(frame_img, w, h)
        # 电影级上下暗角渐变遮罩，让大字高对比清晰可读且保留人物实拍质感
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        for y in range(h):
            t = y / max(1, h - 1)
            if t < 0.42:
                a = int(215 * (1 - t / 0.42) ** 0.75 + 45)
            elif t > 0.62:
                a = int(225 * ((t - 0.62) / 0.38) ** 0.85 + 35)
            else:
                a = 45
            od.line([(0, y), (w, y)], fill=(6, 9, 16, min(235, a)))
        c.paste(overlay, (0, 0), overlay)
        # 底部高亮粗大字（避开画面中间人物主体！）
        draw_title(c, lines, (int(w * 0.07), int(h * 0.64), int(w * 0.93), int(h * 0.91)), int(w * 0.14), normal=WHITE, accent=GOLD_BRIGHT, shadow_alpha=210)
        d = ImageDraw.Draw(c)
        d.rounded_rectangle((int(w * 0.38), int(h * 0.93), int(w * 0.62), int(h * 0.93) + 8), radius=4, fill=GOLD)
        return c

    # 若无实拍图则用蓝紫赛博磨砂玻璃风格
    c = gradient(w, h, (10, 16, 40), (26, 12, 48))
    add_radial_glow(c, int(w * 0.25), int(h * 0.22), int(w * 0.55), CYAN, 110)
    add_radial_glow(c, int(w * 0.8), int(h * 0.76), int(w * 0.58), (139, 92, 246), 115)
    pad = int(w * 0.075)
    glass = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glass)
    gd.rounded_rectangle((pad, int(h * 0.15), w - pad, int(h * 0.85)), radius=42, fill=(14, 19, 36, 175), outline=(56, 189, 248, 130), width=4)
    c.paste(glass, (0, 0), glass)
    draw_title(c, lines, (pad + 36, int(h * 0.22), w - pad - 36, int(h * 0.68)), int(w * 0.14), normal=WHITE, accent=CYAN, shadow_alpha=180)
    return c


def make_candidates(data, base):
    """输出三张风格截然不同、带严格安全区留白（绝不截断）的候选封面。"""
    ratio = data.get("ratio", "3:4")
    w, h = RATIO_SIZES.get(ratio, (1080, 1440))
    out = os.path.join(base, "..", "候选")
    os.makedirs(out, exist_ok=True)
    progress = os.path.join(base, "..", "进度.txt")
    lines = [ln.strip() for ln in str(data["cover_title"]).split("\n") if ln.strip()]
    frame_img = None
    if data.get("cover_frame") and os.path.exists(data["cover_frame"]):
        try:
            frame_img = Image.open(data["cover_frame"]).convert("RGB")
        except Exception:
            frame_img = None
    if frame_img is None:
        frame_img = extract_video_frame(base)

    specs = [
        ("a_黑金电影", lambda: render_style_a(w, h, lines)),
        ("b_瑞士亮白", lambda: render_style_b(w, h, lines)),
        ("c_赛博玻璃", lambda: render_style_c(w, h, lines, None)),
    ]
    states = [n + " 等待制作" for n, _ in specs]
    for i, (name, fn) in enumerate(specs):
        target = os.path.join(out, name + ".png")
        states[i] = name + " 制作中"
        with open(progress, "w") as f:
            f.write("\n".join(states))
        im = fn()
        im.save(target)
        states[i] = name + " 完成"
        with open(progress, "w") as f:
            f.write("\n".join(states))
        print(target)


if __name__ == "__main__":
    path = sys.argv[1]
    data = json.load(open(path))
    if data.get("mode") == "candidates":
        make_candidates(data, os.path.dirname(path))
        sys.exit(0)
    outdir = os.path.join(os.path.dirname(path), "covers")
    os.makedirs(outdir, exist_ok=True)
    for it in data["items"]:
        it["covers"] = make(it, outdir)
        print(it["id"], "ok")
    json.dump(data, open(path, "w"), ensure_ascii=False, indent=1)
