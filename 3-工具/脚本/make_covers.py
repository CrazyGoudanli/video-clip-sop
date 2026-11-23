"""生成多平台封面（不含期号/日期）：9:16（抖音/视频号）、3:4（小红书）、16:9（B站）。
用法: uv run --with pillow python3 make_covers.py <copy.json>
每个 item 需要: id, cover_title（\\n 换行, 【】金色）, cover_sub, cover_frame（图片路径，视频窗口区域截图）
输出到 copy.json 同级的 covers/<id>_<比例>.jpg
"""
import json, sys, os, re
from PIL import Image, ImageDraw, ImageFont, ImageFilter

GOLD = (233, 185, 73)
WHITE = (255, 255, 255)
BG_TOP, BG_BOT = (8, 8, 11), (21, 21, 27)
FONT_BOLD = "/System/Library/Fonts/Hiragino Sans GB.ttc"   # index 2 = W6
FONT_MED = "/System/Library/Fonts/STHeiti Medium.ttc"


def font(size, bold=True):
    try:
        return ImageFont.truetype(FONT_BOLD, size, index=2 if bold else 0)
    except Exception:
        return ImageFont.truetype(FONT_MED, size)


def gradient(w, h):
    im = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(im)
    for y in range(h):
        t = y / max(1, h - 1)
        d.line([(0, y), (w, y)], fill=tuple(int(BG_TOP[i] + (BG_BOT[i] - BG_TOP[i]) * t) for i in range(3)))
    return im


def segments(line):
    out = []
    for p in re.split(r"(【[^】]*】)", line):
        if not p:
            continue
        out.append((p[1:-1], GOLD) if p.startswith("【") else (p, WHITE))
    return out


def line_width(d, line, f):
    return sum(d.textlength(t, font=f) for t, _ in segments(line))


def fit_size(d, lines, max_w, start):
    s = start
    while s > 30 and max(line_width(d, l, font(s)) for l in lines) > max_w:
        s -= 4
    return s


def draw_title(canvas, lines, box, start_size, align="center"):
    """box=(x0,y0,x1,y1) 垂直居中绘制多行标题"""
    d = ImageDraw.Draw(canvas)
    x0, y0, x1, y1 = box
    s = fit_size(d, lines, x1 - x0, start_size)
    f = font(s)
    lh = int(s * 1.25)
    total = lh * len(lines)
    y = y0 + (y1 - y0 - total) // 2
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    for ln in lines:
        w = line_width(d, ln, f)
        x = x0 + ((x1 - x0 - w) / 2 if align == "center" else 0)
        cx = x
        for t, c in segments(ln):
            sd.text((cx + 3, y + 6), t, font=f, fill=(0, 0, 0, 180))
            cx += d.textlength(t, font=f)
        y += lh
    canvas.paste(shadow.filter(ImageFilter.GaussianBlur(8)), (0, 0), shadow.filter(ImageFilter.GaussianBlur(8)))
    y = y0 + (y1 - y0 - total) // 2
    for ln in lines:
        w = line_width(d, ln, f)
        x = x0 + ((x1 - x0 - w) / 2 if align == "center" else 0)
        for t, c in segments(ln):
            d.text((x, y), t, font=f, fill=c, stroke_width=max(1, s // 50), stroke_fill=c)
            x += d.textlength(t, font=f)
        y += lh


def tag(canvas, xy, issue, date, size=34):
    d = ImageDraw.Draw(canvas)
    f = font(size)
    x, y = xy
    tw = d.textlength(issue, font=f)
    d.rounded_rectangle([x, y, x + tw + 32, y + size + 18], radius=8, fill=GOLD)
    d.text((x + 16, y + 6), issue, font=f, fill=(17, 17, 17))
    d.text((x + tw + 56, y + 8), date, font=font(size - 4, False), fill=(200, 200, 200))


def sub(canvas, xy_center_y, text, x0, x1, size=28):
    d = ImageDraw.Draw(canvas)
    f = font(size, False)
    spaced = " ".join(text)
    w = d.textlength(spaced, font=f)
    d.text((x0 + (x1 - x0 - w) / 2, xy_center_y), spaced, font=f, fill=(170, 170, 170))


def hairline(canvas, y, x0, x1):
    d = ImageDraw.Draw(canvas)
    mid = (x0 + x1) / 2
    for x in range(int(x0), int(x1)):
        a = 1 - abs(x - mid) / (mid - x0)
        d.point((x, y), fill=tuple(int(GOLD[i] * a + BG_BOT[i] * (1 - a)) for i in range(3)))
        d.point((x, y + 1), fill=tuple(int(GOLD[i] * a + BG_BOT[i] * (1 - a)) for i in range(3)))


def photo_fit(img, w, h):
    r = max(w / img.width, h / img.height)
    im = img.resize((int(img.width * r + 1), int(img.height * r + 1)), Image.LANCZOS)
    l = (im.width - w) // 2
    t = (im.height - h) // 2
    return im.crop((l, t, l + w, t + h))


def make(item, outdir):
    frame = Image.open(item["cover_frame"]).convert("RGB")
    lines = item["cover_title"].split("\n")
    res = {}

    # 9:16 —— 文字放在中间安全区（抖音主页 3:4 裁切仍可见）
    c = gradient(1080, 1920)
    c.paste(photo_fit(frame, 1080, 668), (0, 400))
    hairline(c, 398, 40, 1040); hairline(c, 1068, 40, 1040)
    draw_title(c, lines, (50, 1110, 1030, 1460), 118)
    sub(c, 1480, item["cover_sub"], 0, 1080)
    p = f"{outdir}/{item['id']}_9x16.jpg"; c.save(p, quality=92); res["9x16"] = p

    # 3:4 —— 小红书：大字优先
    c = gradient(1080, 1440)
    draw_title(c, lines, (40, 140, 1040, 520), 130)
    sub(c, 530, item["cover_sub"], 0, 1080, 26)
    c.paste(photo_fit(frame, 1080, 820), (0, 620))
    hairline(c, 618, 40, 1040)
    p = f"{outdir}/{item['id']}_3x4.jpg"; c.save(p, quality=92); res["3x4"] = p

    # 16:9 —— B站：左图右字
    c = gradient(1920, 1080)
    c.paste(photo_fit(frame, 1080, 1080), (0, 0))
    fade = Image.new("L", (300, 1080))
    for x in range(300):
        ImageDraw.Draw(fade).line([(x, 0), (x, 1080)], fill=int(255 * x / 299))
    c.paste(gradient(300, 1080), (780, 0), fade)
    draw_title(c, lines, (1060, 300, 1890, 790), 132)
    sub(c, 800, item["cover_sub"], 1080, 1880, 26)
    p = f"{outdir}/{item['id']}_16x9.jpg"; c.save(p, quality=92); res["16x9"] = p
    return res


if __name__ == "__main__":
    path = sys.argv[1]
    data = json.load(open(path))
    outdir = os.path.join(os.path.dirname(path), "covers")
    os.makedirs(outdir, exist_ok=True)
    for it in data["items"]:
        it["covers"] = make(it, outdir)
        print(it["id"], "ok")
    json.dump(data, open(path, "w"), ensure_ascii=False, indent=1)
