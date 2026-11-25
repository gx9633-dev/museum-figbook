# -*- coding: utf-8 -*-
"""展板去斜拍：按板面颜色找出每列的上下边界，拟合成两条直线，再按竖条切片把板面拉正。

博物馆的图解展板常挂在侧墙上，照片难免带一点旋转和梯形。这类板面文字多、
线条细，不校正就上版，字会歪着走。这里不做三维推演，只做一件事：
把每一列像素从「板面的上沿到下沿」重新映射到等高——旋转与上下梯形一并解决。

用法：
    python3 dewarp.py in.jpg out.jpg            # 自动取板面色
    python3 dewarp.py in.jpg out.jpg --size 1600
"""
import argparse

import numpy as np
from PIL import Image, ImageOps


def _board_mask(im):
    a = np.asarray(im, dtype=np.float32)
    H, W = a.shape[:2]
    # 板面色：取画面中部一条带的中位色（板面通常占中部）
    band = a[int(H * 0.35):int(H * 0.65), int(W * 0.2):int(W * 0.8)].reshape(-1, 3)
    ref = np.median(band, axis=0)
    d = np.sqrt(((a - ref) ** 2).sum(axis=2))
    m = d < 46
    # 只保留与中部相连的最大块，去掉同色的杂项
    return m, ref


def _edges(m):
    H, W = m.shape
    top, bot = np.full(W, -1), np.full(W, -1)
    for x in range(W):
        ys = np.nonzero(m[:, x])[0]
        if len(ys) < H * 0.08:
            continue
        # 用分位去掉零星噪点
        top[x] = np.percentile(ys, 0.6)
        bot[x] = np.percentile(ys, 99.4)
    ok = (top >= 0) & (bot > top)
    return top, bot, ok


def dewarp(src, dst, out_w=1800):
    with Image.open(src) as _im:
        im = ImageOps.exif_transpose(_im).convert("RGB")
    m, ref = _board_mask(im)
    top, bot, ok = _edges(m)
    xs = np.nonzero(ok)[0]
    if len(xs) < 50:
        raise SystemExit("没找到板面：底色与背景太接近，请手动给四角。")
    pt = np.polyfit(xs, top[xs], 1)
    pb = np.polyfit(xs, bot[xs], 1)
    H = im.size[1]
    h_med = float(np.median(bot[ok] - top[ok]))
    x0, x1 = int(xs.min()), int(xs.max())
    W_out = out_w
    H_out = int(round(h_med * out_w / (x1 - x0)))
    # 竖条切片：每条按自己的上下沿映射到同一高度
    strips = max(8, min(80, (x1 - x0) // 24))
    mesh = []
    for i in range(strips):
        sx0 = x0 + (x1 - x0) * i / strips
        sx1 = x0 + (x1 - x0) * (i + 1) / strips
        yt0, yt1 = np.polyval(pt, sx0), np.polyval(pt, sx1)
        yb0, yb1 = np.polyval(pb, sx0), np.polyval(pb, sx1)
        # QUAD 顺序：左上、左下、右下、右上（源图坐标）
        quad = (sx0, yt0, sx0, yb0, sx1, yb1, sx1, yt1)
        box = (int(round(W_out * i / strips)), 0,
               int(round(W_out * (i + 1) / strips)), H_out)
        mesh.append((box, quad))
    out = im.transform((W_out, H_out), Image.MESH, mesh, Image.BICUBIC)
    out.save(dst, quality=94, subsampling=0)
    return out.size, (x0, x1, round(float(top[xs.min()])), round(float(bot[xs.max()])))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--size", type=int, default=1800)
    a = ap.parse_args()
    print(a.dst, dewarp(a.src, a.dst, a.size))
