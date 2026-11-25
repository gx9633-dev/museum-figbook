#!/usr/bin/env python3
"""为全册器物页生成带坐标网格的图，供定 pins 坐标用。

用法：
  python3 pins_grid.py 观展图记_全册.json --out-dir _derived/book/pin_grid
每页一张 <id>.png，叠 0.1 步长红线，上边与左边标 0.0–1.0 数值。
"""
import argparse
import json
import os

from PIL import Image, ImageDraw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("book", help="全册 JSON（render.py 的输入）")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--width", type=int, default=900)
    ap.add_argument("--max-height", type=int, default=700)
    ap.add_argument("--types", default="portrait,landscape",
                    help="只处理这些页型，逗号分隔")
    a = ap.parse_args()

    types = set(t.strip() for t in a.types.split(",") if t.strip())
    os.makedirs(a.out_dir, exist_ok=True)
    book = json.load(open(a.book, encoding="utf-8"))

    n = 0
    missing = []
    for p in book["plates"]:
        tp = p.get("type") or p.get("layout")
        if tp not in types:
            continue
        src = p.get("img")
        if not src or not os.path.exists(src):
            missing.append((p["id"], src))
            continue
        im = Image.open(src).convert("RGB")
        k = min(a.width / im.width, a.max_height / im.height)
        im = im.resize((int(im.width * k), int(im.height * k)))
        W, H = im.size
        dr = ImageDraw.Draw(im, "RGBA")
        for i in range(11):
            x, y = int(W * i / 10), int(H * i / 10)
            dr.line([(x, 0), (x, H)], fill=(255, 0, 0, 80), width=1)
            dr.line([(0, y), (W, y)], fill=(255, 0, 0, 80), width=1)
            dr.text((x + 2, 3), "%.1f" % (i / 10), fill=(200, 0, 0, 255))
            dr.text((3, y + 2), "%.1f" % (i / 10), fill=(200, 0, 0, 255))
        im.save(os.path.join(a.out_dir, "%s.png" % p["id"]))
        n += 1

    print("网格图 %d 张 → %s" % (n, a.out_dir))
    if missing:
        print("缺图：", missing)


if __name__ == "__main__":
    main()
