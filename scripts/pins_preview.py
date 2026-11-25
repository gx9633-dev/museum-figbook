#!/usr/bin/env python3
"""把每页的 pins 画在原图上，拼成通检图，核查圆托与特征点是否落在器物上。

用法：
  python3 pins_preview.py 观展图记_全册.json --out-dir _out/pins_check --per-sheet 8
每张最多 per-sheet 页，4 列排布，每格标题为「id 页码 名称」。
红圈＝特征点，白圆＝圆托，细线＝引线，与 render.py 的 overlay() 同构。
"""
import argparse
import json
import os

from PIL import Image, ImageDraw, ImageFont


def load_font(size=20):
    for p in ("/System/Library/Fonts/Helvetica.ttc",
              "/System/Library/Fonts/Supplemental/Arial.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("book")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--per-sheet", type=int, default=8)
    ap.add_argument("--cell", type=int, default=620)
    a = ap.parse_args()

    os.makedirs(a.out_dir, exist_ok=True)
    font = load_font(20)
    book = json.load(open(a.book, encoding="utf-8"))
    pages = [p for p in book["plates"] if p.get("pins")]

    CW = a.cell
    CH = int(a.cell * 1.05)
    for gi in range(0, len(pages), a.per_sheet):
        chunk = pages[gi:gi + a.per_sheet]
        cols = 4
        rows = (len(chunk) + cols - 1) // cols
        sheet = Image.new("RGB", (CW * cols, CH * rows), (255, 255, 255))
        dr = ImageDraw.Draw(sheet)
        for i, p in enumerate(chunk):
            im = Image.open(p["img"]).convert("RGB")
            k = min((CW - 12) / im.width, (CH - 34) / im.height)
            im = im.resize((int(im.width * k), int(im.height * k)))
            W, H = im.size
            dd = ImageDraw.Draw(im)
            R = max(10, int(W * 0.021))
            r = max(4, int(W * 0.010))
            for j, pin in enumerate(p["pins"]):
                cx, cy = pin[1] * W, pin[2] * H
                px, py = pin[3] * W, pin[4] * H
                dd.line([px, py, cx, cy], fill=(150, 110, 70), width=2)
                dd.ellipse([px - r, py - r, px + r, py + r],
                           outline=(190, 30, 30), width=2)
                dd.ellipse([cx - R, cy - R, cx + R, cy + R],
                           fill=(255, 252, 246), outline=(140, 106, 75), width=2)
                dd.text((cx - 3, cy - 6), str(j + 1), fill=(120, 85, 50), font=font)
            ox = (i % cols) * CW + (CW - W) // 2
            oy = (i // cols) * CH + 30 + (CH - 30 - H) // 2
            sheet.paste(im, (ox, oy))
            dr.text(((i % cols) * CW + 6, (i // cols) * CH + 6),
                    "%s %s %s" % (p["id"], p.get("folio", ""), p.get("name", "")[:10]),
                    fill=(0, 0, 0), font=font)
        out = os.path.join(a.out_dir, "pins_%02d.png" % (gi // a.per_sheet))
        sheet.save(out)
        print(out, [p["id"] for p in chunk])


if __name__ == "__main__":
    main()
