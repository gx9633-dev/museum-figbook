#!/usr/bin/env python3
"""把一块展板照片按栏切成图，自动去掉器名色块、栏线与说明文字。

展板照片的问题是：栏与栏之间有细线，每栏顶部有器名色块，底部有说明文字，
整块板还有透视偏转（右栏比左栏高）。固定坐标切必然切到东西。所以这里按
「暗像素在行/列上的分布」找边界，而不是猜百分比。

用法：
  python3 panel_crop.py IMG_7898.JPG --cols 4 --out _derived/pl/music \
      --names 铙,钟,镈,錞于 [--trim-top 0.002]

输出 <out>/1.jpg … ，并打印每栏的裁切框（整图百分比），可直接写进 plates.json。
"""
import argparse
import os
import sys

from PIL import Image, ImageOps


def rowdark(g, x0, x1, y0, y1, thr=150):
    """每一行的暗像素占比（只看 [x0,x1) 这一栏）。"""
    px = g.load()
    out = []
    for y in range(y0, y1):
        c = 0
        for x in range(x0, x1, 2):
            if px[x, y] < thr:
                c += 1
        out.append(c / max(1, len(range(x0, x1, 2))))
    return out


def coldark(g, y0, y1, x0, x1, thr=150):
    px = g.load()
    out = []
    for x in range(x0, x1):
        c = 0
        for y in range(y0, y1, 2):
            if px[x, y] < thr:
                c += 1
        out.append(c / max(1, len(range(y0, y1, 2))))
    return out


def bands(vals, thr):
    """返回连续超过阈值的区间 [(start,end), ...]。"""
    res, s = [], None
    for i, v in enumerate(vals):
        if v > thr and s is None:
            s = i
        elif v <= thr and s is not None:
            res.append((s, i))
            s = None
    if s is not None:
        res.append((s, len(vals)))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--cols", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--names", default="")
    ap.add_argument("--gap", type=float, default=0.035,
                    help="栏间留白占整宽比例，用于分隔相邻栏")
    ap.add_argument("--margin", default="0.05,0.12,0.95,0.88",
                    help="板面在整图中的范围 x0,y0,x1,y1（百分比）")
    a = ap.parse_args()

    im = ImageOps.exif_transpose(Image.open(a.image)).convert("RGB")
    W, H = im.size
    g = im.convert("L")
    mx0, my0, mx1, my1 = [float(v) for v in a.margin.split(",")]
    X0, Y0, X1, Y1 = int(mx0 * W), int(my0 * H), int(mx1 * W), int(my1 * H)
    colw = (X1 - X0) / a.cols
    names = [s.strip() for s in a.names.split(",")] if a.names else []

    os.makedirs(a.out, exist_ok=True)
    boxes = []
    for i in range(a.cols):
        cx0 = int(X0 + i * colw + colw * a.gap)
        cx1 = int(X0 + (i + 1) * colw - colw * a.gap)
        # 1) 行方向：找器名色块（最上方的高暗度带）与说明文字（下方的高暗度带）
        rd = rowdark(g, cx0, cx1, Y0, Y1)
        bs = bands(rd, 0.10)
        yd = Y0
        yb = Y1
        if bs:
            first = bs[0]
            if first[1] - first[0] < (Y1 - Y0) * 0.10:   # 色块：矮而密
                yd = Y0 + first[1] + int((Y1 - Y0) * 0.004)
                bs = bs[1:]
        # 说明文字：从下往上找第一段连续超过 0.02 的行（字虽小但成片）
        bs2 = bands(rd, 0.02)
        for s, e in reversed(bs2):
            if (Y0 + s) > yd + (Y1 - Y0) * 0.45:
                yb = Y0 + s - int((Y1 - Y0) * 0.004)
                break
        # 2) 列方向：去掉左右栏线（边缘 1—2px 的高暗度列）
        cd = coldark(g, yd, yb, cx0, cx1)
        while cd and cd[0] > 0.35:
            cx0 += 1
            cd.pop(0)
        while cd and cd[-1] > 0.35:
            cx1 -= 1
            cd.pop()
        # 3) 再按实际墨迹收紧上下留白，但保留一点余量
        rd2 = rowdark(g, cx0, cx1, yd, yb, thr=170)
        ink = [i for i, v in enumerate(rd2) if v > 0.008]
        if ink:
            yd2 = yd + max(0, ink[0] - int((yb - yd) * 0.02))
            yb2 = yd + min(len(rd2), ink[-1] + int((yb - yd) * 0.02))
            yd, yb = yd2, yb2
        c = im.crop((cx0, yd, cx1, yb))
        name = names[i] if i < len(names) else str(i + 1)
        dst = os.path.join(a.out, f"{i + 1}.jpg")
        c.save(dst, quality=95, subsampling=0)
        boxes.append((cx0 / W, yd / H, cx1 / W, yb / H, c.size, name))
        print(f"{name}  {c.size[0]}×{c.size[1]}  "
              f"crop=[{cx0/W:.3f},{yd/H:.3f},{cx1/W:.3f},{yb/H:.3f}]  {dst}")


if __name__ == "__main__":
    sys.exit(main())
