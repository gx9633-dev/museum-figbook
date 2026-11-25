# -*- coding: utf-8 -*-
"""照片索引：EXIF 时间 + 感知哈希去重 + 模糊度 + 拼版联系表。

给选片用的第一道物料：不判断器物是什么，只回答「哪些是同一组的重复」
「哪张更清楚」「横构图还是竖构图」。器物识别与定名在人工复核阶段做。

用法：
    python3 index_photos.py 照片目录 --out _derived/sheets
产出：
    index.csv            每张一行，可直接在表格里做减法
    sheet-NN.png         4×5 拼版，每格带文件名、时间、组号
"""
import argparse
import csv
import datetime
import glob
import os
from collections import Counter

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps, ImageStat

CELL_W, CELL_H = 420, 316      # 图区
LABEL_H = 26
COLS, ROWS = 4, 5
PER_SHEET = COLS * ROWS


def font(size):
    for p in ("/System/Library/Fonts/PingFang.ttc",
              "/System/Library/Fonts/Supplemental/Arial.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()


def exif_time(im):
    from PIL.ExifTags import TAGS
    d = {TAGS.get(k, k): v for k, v in im.getexif().items()}
    t = d.get("DateTimeOriginal") or d.get("DateTime")
    try:
        return datetime.datetime.strptime(t, "%Y:%m:%d %H:%M:%S")
    except Exception:
        return None


def dhash(im, s=8):
    g = im.convert("L").resize((s + 1, s), Image.LANCZOS)
    px = list(g.getdata())
    bits = 0
    for r in range(s):
        for c in range(s):
            bits = (bits << 1) | (px[r * (s + 1) + c] < px[r * (s + 1) + c + 1])
    return bits


def sharpness(im):
    """拉普拉斯近似：边缘强度方差。低于 8 基本可判虚焦。"""
    g = im.convert("L").resize((min(im.width, 1000),
                                int(min(im.width, 1000) * im.height / im.width)),
                               Image.LANCZOS)
    st = ImageStat.Stat(g.filter(ImageFilter.FIND_EDGES))
    return round(st.stddev[0], 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--out", default="_derived/sheets")
    ap.add_argument("--dup-distance", type=int, default=7)
    ap.add_argument("--dup-seconds", type=int, default=120)
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    files = sorted(glob.glob(os.path.join(a.dir, "*.JPG"))
                   + glob.glob(os.path.join(a.dir, "*.jpg")))
    if not files:
        raise SystemExit("目录里没有 jpg")

    rows = []
    for f in files:
        # 必须先按 EXIF 归正：手机照片常为 Orientation=6，原始像素是横的、
        # 显示才转正。不归正会把竖构图记成横构图（158 张里错了 121 张）。
        im = ImageOps.exif_transpose(Image.open(f))
        w, h = im.size
        t = exif_time(Image.open(f))
        im.draft("L", (96, 96))
        rows.append({"file": os.path.basename(f), "time": t,
                     "w": w, "h": h, "hash": dhash(im),
                     "sharp": sharpness(Image.open(f).convert("RGB"))})
    rows.sort(key=lambda r: r["time"] or datetime.datetime(2000, 1, 1))

    # 贪心聚类：哈希距离与时间窗同时满足才算同组
    groups = []
    for r in rows:
        for g in groups:
            if (bin(g["hash"] ^ r["hash"]).count("1") <= a.dup_distance
                    and abs((r["time"] - g["time"]).total_seconds()) <= a.dup_seconds):
                g["members"].append(r)
                break
        else:
            groups.append({"hash": r["hash"], "time": r["time"], "members": [r]})

    for gi, g in enumerate(groups):
        for m in g["members"]:
            m["group"] = gi
            m["dup"] = len(g["members"])

    csv_path = os.path.join(a.out, "index.csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as fh:
        wtr = csv.writer(fh)
        wtr.writerow(["序号", "文件", "时间", "组", "同组张数", "宽", "高",
                      "构图", "清晰度", "建议"])
        for i, r in enumerate(rows, 1):
            orient = "竖" if r["h"] > r["w"] else "横"
            hint = []
            if r["dup"] > 1:
                hint.append("同组多拍")
            if r["sharp"] < 8:
                hint.append("疑虚焦")
            wtr.writerow([i, r["file"], r["time"].strftime("%H:%M:%S"),
                          r["group"] + 1, r["dup"], r["w"], r["h"], orient,
                          r["sharp"], " / ".join(hint) or "候选"])

    # 拼版
    f_label = font(15)
    f_head = font(18)
    n_sheets = (len(rows) + PER_SHEET - 1) // PER_SHEET
    for si in range(n_sheets):
        chunk = rows[si * PER_SHEET:(si + 1) * PER_SHEET]
        W = COLS * (CELL_W + 8) + 8
        H = ROWS * (CELL_H + LABEL_H + 8) + 8 + 34
        sheet = Image.new("RGB", (W, H), (255, 255, 255))
        d = ImageDraw.Draw(sheet)
        d.text((10, 8), f"索引 {si+1}/{n_sheets}　共 {len(rows)} 张", font=f_head, fill=(0, 0, 0))
        for k, r in enumerate(chunk):
            cx = 8 + (k % COLS) * (CELL_W + 8)
            cy = 34 + 8 + (k // COLS) * (CELL_H + LABEL_H + 8)
            im = ImageOps.exif_transpose(
                Image.open(os.path.join(a.dir, r["file"]))).convert("RGB")
            im.thumbnail((CELL_W, CELL_H), Image.LANCZOS)
            ox = cx + (CELL_W - im.width) // 2
            oy = cy + (CELL_H - im.height) // 2
            sheet.paste(im, (ox, oy))
            d.rectangle([cx, cy, cx + CELL_W, cy + CELL_H], outline=(200, 200, 200))
            seq = rows.index(r) + 1
            tag = (f"{seq:03d}  {r['file'].replace('.JPG','').replace('IMG_','')}  "
                   f"{r['time'].strftime('%H:%M')}  G{r['group']+1}")
            if r["sharp"] < 8:
                tag += "  虚"
            d.text((cx + 3, cy + CELL_H + 4), tag, font=f_label, fill=(0, 0, 0))
        p = os.path.join(a.out, f"sheet-{si+1:02d}.png")
        sheet.save(p, quality=90)

    print(f"张数 {len(rows)}　组数 {len(groups)}　可合并 {len(rows)-len(groups)}")
    print("组规模", dict(sorted(Counter(r['dup'] for r in rows).items())))
    print("虚焦", sum(1 for r in rows if r['sharp'] < 8))
    print("构图 竖", sum(1 for r in rows if r['h'] > r['w']),
          "横", sum(1 for r in rows if r['h'] <= r['w']))
    print("写出", csv_path, f"与 {n_sheets} 张拼版")


if __name__ == "__main__":
    main()
