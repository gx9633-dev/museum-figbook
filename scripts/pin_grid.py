# -*- coding: utf-8 -*-
"""标注落点校准图：把原图裁局部、叠百分比网格、打十字，供人眼复核。

坐标一律用「整图相对坐标」(0—1)，与 plates.json 里 pins 的写法完全一致，
所以图上读到的数可以直接抄进记录。绝不要凭页面缩略图目测落点。

用法：
    # 整图带网格，核对已有标注
    python3 pin_grid.py IMG.jpg --out g.png --pins 0.409,0.577 --pins 0.448,0.612

    # 放大局部（裁剪框也用相对坐标）
    python3 pin_grid.py IMG.jpg --out g.png --crop 0.28,0.50,0.62,0.72

    # 纹理定位：在框内找能量最高点（鱼子纹、錾刻这类细密纹饰）
    python3 pin_grid.py IMG.jpg --out g.png --crop 0.30,0.50,0.60,0.72 --texture
"""
import argparse
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps
import numpy as np

TOP, LEFT = 28, 46
GRID_MINOR = (200, 30, 30, 70)
GRID_MAJOR = (200, 30, 30, 150)
CROSS = (200, 20, 20, 255)


def font(size):
    for p in ("/System/Library/Fonts/PingFang.ttc",
              "/System/Library/Fonts/Supplemental/Arial.ttf",
              "/System/Library/Fonts/Helvetica.ttc"):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()


def boxmean(a, k):
    """同尺寸的 k×k 局部均值，积分图实现。"""
    r = k // 2
    p = np.pad(a, ((r, r), (r, r)), mode="reflect")
    ii = np.zeros((p.shape[0] + 1, p.shape[1] + 1), dtype=np.float64)
    ii[1:, 1:] = p.cumsum(0).cumsum(1)
    h, w = a.shape
    y = np.arange(h)
    x = np.arange(w)
    s = (ii[np.ix_(y + k, x + k)] - ii[np.ix_(y, x + k)]
         - ii[np.ix_(y + k, x)] + ii[np.ix_(y, x)])
    return s / (k * k)


def texture_peak(im, box):
    """在 box=(x0,y0,x1,y1) 像素框内找纹理能量最高的点，返回整图相对坐标。
    高通 = 原灰度 − 中值滤波；局部能量用 boxmean；再减去边缘能量作惩罚，
    避免落在器物轮廓线上。最后仍需人眼复核。"""
    W0, H0 = im.size
    work = im.copy()
    if W0 > 900:
        work = work.resize((900, int(H0 * 900 / W0)), Image.LANCZOS)
    g = work.convert("L")
    hi = np.asarray(ImageChops.difference(g, g.filter(ImageFilter.MedianFilter(7))),
                    dtype=np.float32)
    edge = np.asarray(g.filter(ImageFilter.FIND_EDGES), dtype=np.float32)
    score = boxmean(hi, 11) - 0.55 * boxmean(edge, 11)

    sx, sy = work.size[0] / W0, work.size[1] / H0
    x0, y0, x1, y1 = [int(v) for v in box]
    # 内缩半个窗口，避免峰值被框边界的 padding 假象拉走
    pad = 6
    ax0, ay0 = int(x0 * sx) + pad, int(y0 * sy) + pad
    ax1, ay1 = int(x1 * sx) - pad, int(y1 * sy) - pad
    if ax1 - ax0 < 2 * pad or ay1 - ay0 < 2 * pad:
        ax0, ay0 = int(x0 * sx), int(y0 * sy)
        ax1, ay1 = int(x1 * sx), int(y1 * sy)
    sub = score[ay0:ay1, ax0:ax1]
    if sub.size == 0:
        raise SystemExit("裁剪框为空")
    iy, ix = np.unravel_index(int(np.argmax(sub)), sub.shape)
    fx = (ix + ax0) / work.size[0]
    fy = (iy + ay0) / work.size[1]
    return fx, fy


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--out", required=True)
    ap.add_argument("--crop", help="x0,y0,x1,y1 相对坐标，默认整图")
    ap.add_argument("--pins", action="append", default=[], help="fx,fy 可多次给")
    ap.add_argument("--texture", action="store_true", help="在裁剪框内做纹理定位")
    ap.add_argument("--width", type=int, default=1200)
    a = ap.parse_args()

    # 必须先按 EXIF 归正：手机照片常为 Orientation=6，原始像素是横的、
    # 显示才转正。不归正时百分比坐标落在旋转后的错位区域，
    # 读数看着合理、量的却不是那件东西（此前裁片数值错位即因此）。
    im = ImageOps.exif_transpose(Image.open(a.image)).convert("RGB")
    W0, H0 = im.size
    cx0, cy0, cx1, cy1 = (0.0, 0.0, 1.0, 1.0)
    if a.crop:
        cx0, cy0, cx1, cy1 = [float(v) for v in a.crop.split(",")]
    box = (int(cx0 * W0), int(cy0 * H0), int(cx1 * W0), int(cy1 * H0))

    peaks = []
    if a.texture:
        peaks.append(texture_peak(im, box))

    crop = im.crop(box)
    scale = a.width / crop.size[0]
    crop = crop.resize((a.width, max(1, int(crop.size[1] * scale))), Image.LANCZOS)
    W, H = crop.size

    canvas = ImageOps.expand(crop.convert("RGBA"), border=(LEFT, TOP, 2, 2),
                             fill=(255, 255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    f = font(15)

    def px(v):           # 整图相对 x → 画布 x
        return LEFT + (v - cx0) / max(1e-9, cx1 - cx0) * W

    def py(v):
        return TOP + (v - cy0) / max(1e-9, cy1 - cy0) * H

    lo_x, hi_x = int(np.floor(cx0 * 100)), int(np.ceil(cx1 * 100))
    lo_y, hi_y = int(np.floor(cy0 * 100)), int(np.ceil(cy1 * 100))
    for i in range(lo_x, hi_x + 1):
        v = i / 100
        if v < cx0 - 1e-9 or v > cx1 + 1e-9:
            continue
        x = px(v)
        major = (i % 5 == 0)
        draw.line([(x, TOP), (x, TOP + H)], fill=GRID_MAJOR if major else GRID_MINOR,
                  width=2 if major else 1)
        if major:
            t = f"{i}"
            draw.text((x - draw.textlength(t, f) / 2, 6), t, font=f, fill=(90, 40, 40))
    for i in range(lo_y, hi_y + 1):
        v = i / 100
        if v < cy0 - 1e-9 or v > cy1 + 1e-9:
            continue
        y = py(v)
        major = (i % 5 == 0)
        draw.line([(LEFT, y), (LEFT + W, y)], fill=GRID_MAJOR if major else GRID_MINOR,
                  width=2 if major else 1)
        if major:
            t = f"{i}"
            draw.text((4, y - 8), t, font=f, fill=(90, 40, 40))

    def cross(cx, cy, label, color=CROSS):
        L = 15
        draw.line([(cx - L, cy), (cx + L, cy)], fill=color, width=2)
        draw.line([(cx, cy - L), (cx, cy + L)], fill=color, width=2)
        draw.ellipse([cx - 7, cy - 7, cx + 7, cy + 7], outline=color, width=2)
        draw.text((cx + 13, cy - 26), label, font=f, fill=color)

    for s in a.pins:
        fx, fy = [float(v) for v in s.split(",")]
        cross(px(fx), py(fy), f"{fx:.3f},{fy:.3f}")
    for i, (fx, fy) in enumerate(peaks, 1):
        cross(px(fx), py(fy), f"T{i} {fx:.3f},{fy:.3f}", (20, 90, 200, 255))
        print(f"纹理峰 {i}: {fx:.3f}, {fy:.3f}   相对整图")

    canvas.convert("RGB").save(a.out, quality=92)
    print("写出", a.out, f"{canvas.size[0]}×{canvas.size[1]}",
          f"（显示整图 x {cx0:.2f}—{cx1:.2f}，y {cy0:.2f}—{cy1:.2f}）")


if __name__ == "__main__":
    main()
