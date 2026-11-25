# -*- coding: utf-8 -*-
"""裁切可行性校验：给定原图与若干裁切框，输出裁片并报「可印宽度」。

用法：
    python3 crop_check.py IMG_7837.JPG --out /tmp/c --box 0.32,0.02,0.58,0.27 \
            --box 0.38,0.33,0.56,0.47 --names 39,40 --sheet /tmp/c/sheet.png

判定口径（印刷用）：
    long_px / 300 * 25.4  = 300dpi 下可印长边 mm
    long_px / 240 * 25.4  = 240dpi 下可印长边 mm
    图录正文图建议 ≥ 240dpi；细节图 ≥ 300dpi 更好。
    可印长边 < 40mm 的单件，不足以独立成页，只能进注解小图。
"""
import argparse
import os

from PIL import Image, ImageDraw, ImageOps

DPI_OK, DPI_MIN = 300, 240
MM_IN = 25.4


def parse_box(s):
    v = [float(x) for x in s.split(",")]
    if len(v) != 4:
        raise argparse.ArgumentTypeError("box 需要 4 个数：x0,y0,x1,y1（0—1 相对坐标）")
    x0, y0, x1, y1 = v
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise argparse.ArgumentTypeError("box 必须 x0<x1、y0<y1，且都在 0—1 内")
    return v


def mm(px, dpi):
    return px / dpi * MM_IN


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--out", default="_crop")
    ap.add_argument("--box", action="append", type=parse_box, required=True)
    ap.add_argument("--names", default="")
    ap.add_argument("--sheet", help="把全部裁片拼成一张校验图")
    ap.add_argument("--label", action="store_true", help="在裁片上标注像素与可印宽度")
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    names = [s for s in a.names.split(",") if s] or [str(i + 1) for i in range(len(a.box))]

    im = ImageOps.exif_transpose(Image.open(a.image)).convert("RGB")
    W0, H0 = im.size
    rows, thumbs = [], []
    print(f"原图 {os.path.basename(a.image)}  {W0}×{H0}")
    print(f"{'名':<6}{'裁片像素':>13}{'300dpi':>10}{'240dpi':>10}  判定")
    for name, (x0, y0, x1, y1) in zip(names, a.box):
        box = (int(x0 * W0), int(y0 * H0), int(x1 * W0), int(y1 * H0))
        c = im.crop(box)
        cw, ch = c.size
        long_px = max(cw, ch)
        m300, m240 = mm(long_px, DPI_OK), mm(long_px, DPI_MIN)
        if m240 >= 76:
            verdict = "可独立成页"
        elif m240 >= 52:
            verdict = "可作并列细节图"
        elif m240 >= 40:
            verdict = "仅可作小图"
        else:
            verdict = "不可用"
        p = os.path.join(a.out, f"{name}.jpg")
        c.save(p, quality=95)
        rows.append((name, cw, ch, m300, m240, verdict, p))
        print(f"{name:<6}{cw:>6}×{ch:<6}{m300:>8.0f}mm{m240:>8.0f}mm  {verdict}")

    if a.sheet:
        cell, pad = 300, 18
        cols = min(4, len(rows))
        rws = (len(rows) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * (cell + pad) + pad, rws * (cell + pad + 26) + pad), "#F5F2EB")
        d = ImageDraw.Draw(sheet)
        for i, (name, cw, ch, m300, m240, verdict, p) in enumerate(rows):
            t = Image.open(p)
            t.thumbnail((cell, cell), Image.LANCZOS)
            cx = pad + (i % cols) * (cell + pad) + (cell - t.size[0]) // 2
            cy = pad + (i // cols) * (cell + pad + 26) + (cell - t.size[1]) // 2
            sheet.paste(t, (cx, cy))
            d.text((pad + (i % cols) * (cell + pad), cy + cell // 2 + 4),
                   f"{name}  {cw}x{ch}px  {m240:.0f}mm", fill="#1F1C18")
        sheet.save(a.sheet)
        print("拼版", a.sheet)

    print("\n判据：≥76mm 可独立成页；52—76mm 作并列细节图；40—52mm 只能作注解小图（240dpi 计）")
    return rows


if __name__ == "__main__":
    main()
