# -*- coding: utf-8 -*-
"""主体居中裁切：先找展品外接框，再按目标长宽比向外扩出**四边等宽**的留白。

为什么不用手写 crop 坐标：手写坐标只能保证「框住」，保证不了「居中、四边留白平均」，
换一张照片就要重算。这里改成先量再框——

1. 以画面四周为底色，算每个像素与底色的色距，得到前景掩模；
2. 开运算去掉玻璃反光细丝与投影边缘，取最大连通块，即展品本体；
3. 用该块的 1%—99% 分位框作为本体框（避开零星锈点、暗角）；
4. 以本体框中心为中心，四边留白 m×本体长边，再按目标长宽比补到刚好；
5. 若补出的框越出原图，用镜像＋模糊补边（补的是墙面色，不引入假物件）。

用法：
    python3 subject_crop.py in.jpg out.jpg --aspect 0.42 --margin 0.12
    python3 subject_crop.py in.jpg out.jpg --aspect 1.4 --margin 0.10 --debug
"""
import argparse
import os
from collections import deque

import numpy as np
from PIL import Image, ImageFilter, ImageOps


def _mask(im, scale=240):
    """降采样求前景掩模。返回 (mask, bg, thr)。"""
    w, h = im.size
    s = scale / max(w, h)
    sm = np.asarray(im.resize((max(1, int(w * s)), max(1, int(h * s))),
                              Image.BILINEAR), dtype=np.float32)
    H, W = sm.shape[:2]
    b = max(2, int(min(W, H) * 0.06))
    ring = np.concatenate([sm[:b].reshape(-1, 3), sm[-b:].reshape(-1, 3),
                           sm[:, :b].reshape(-1, 3), sm[:, -b:].reshape(-1, 3)])
    bg = np.median(ring, axis=0)
    d = np.sqrt(((sm - bg) ** 2).sum(axis=2))
    med = float(np.median(d))
    mad = float(np.median(np.abs(d - med))) or 1.0
    thr = min(95.0, max(24.0, med + 2.6 * mad))
    mask = d > thr
    return mask, bg, thr


def _open(mask, k=2, it=1):
    m = mask.copy()
    for _ in range(it):
        e = m.copy()
        e[1:, :] &= m[:-1, :]
        e[:-1, :] &= m[1:, :]
        e[:, 1:] &= m[:, :-1]
        e[:, :-1] &= m[:, 1:]
        m = e
    for _ in range(it):
        d = m.copy()
        d[1:, :] |= m[:-1, :]
        d[:-1, :] |= m[1:, :]
        d[:, 1:] |= m[:, :-1]
        d[:, :-1] |= m[:, 1:]
        m = d
    return m


def _components(mask):
    """连通块列表，每项 (pts, bbox)。4 邻域 BFS，降采样后跑，规模可控。"""
    H, W = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    out = []
    ys, xs = np.nonzero(mask)
    for y0, x0 in zip(ys, xs):
        if seen[y0, x0]:
            continue
        q = deque([(y0, x0)])
        seen[y0, x0] = True
        pts = []
        while q:
            y, x = q.popleft()
            pts.append((y, x))
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < H and 0 <= nx < W and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    q.append((ny, nx))
        yy, xx = zip(*pts)
        out.append((pts, (min(xx), min(yy), max(xx) + 1, max(yy) + 1)))
    return out


def _subject_mask(mask):
    """挑出展品本体：面积×靠近画面中心的权重最大者，再把与之重叠的碎块并进来。

    不能用「最大连通块」：展柜玻璃的高光边条常常又长又亮，面积比展品还大；
    头模的发髻也常被一道阴影切成两块，只取一块就会把发顶切掉。
    """
    comps = _components(mask)
    if not comps:
        return np.zeros_like(mask)
    H, W = mask.shape
    cx, cy = W / 2, H / 2
    diag = (W * W + H * H) ** .5
    best, best_s = None, -1
    for pts, (x0, y0, x1, y1) in comps:
        if len(pts) < 0.004 * W * H:
            continue
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        d = ((mx - cx) ** 2 + (my - cy) ** 2) ** .5 / diag
        s = len(pts) * (1.0 - 0.9 * d)
        if s > best_s:
            best, best_s = (x0, y0, x1, y1), s
    if best is None:
        return np.zeros_like(mask)
    boxes = [best]
    changed = True
    while changed:
        changed = False
        bx0, by0, bx1, by1 = (min(b[0] for b in boxes), min(b[1] for b in boxes),
                              max(b[2] for b in boxes), max(b[3] for b in boxes))
        for pts, b in comps:
            if b in boxes:
                continue
            # 顶到画框的碎块多半是邻柜的器物或玻璃边条，并进来会把主体挤偏
            if b[0] <= 0 or b[1] <= 0 or b[2] >= W or b[3] >= H:
                continue
            ix = max(0, min(bx1, b[2]) - max(bx0, b[0]))
            iy = max(0, min(by1, b[3]) - max(by0, b[1]))
            if ix * iy > 0.18 * min((b[2] - b[0]) * (b[3] - b[1]),
                                    (bx1 - bx0) * (by1 - by0)):
                boxes.append(b)
                changed = True
    out = np.zeros_like(mask, dtype=bool)
    for pts, b in comps:
        if b in boxes:
            for y, x in pts:
                out[y, x] = True
    return out


def subject_box(im, min_frac=0.02):
    """返回原图像素坐标下的展品外接框 (x0, y0, x1, y1)。"""
    mask, bg, thr = _mask(im)
    m = _open(mask, 2, 1)
    if m.sum() < 8:
        m = mask
    m = _subject_mask(m)
    if m.sum() < 8:
        w, h = im.size
        return 0, 0, w, h
    ys, xs = np.nonzero(m)
    x0, x1 = np.percentile(xs, [1, 99])
    y0, y1 = np.percentile(ys, [1, 99])
    W, H = im.size
    sx, sy = W / mask.shape[1], H / mask.shape[0]
    x0, x1, y0, y1 = x0 * sx, x1 * sx, y0 * sy, y1 * sy
    # 留 1% 余量，防止边缘锈迹、发丝被切掉
    pad = 0.012 * max(x1 - x0, y1 - y0)
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    x1, y1 = min(W, x1 + pad), min(H, y1 + pad)
    if (x1 - x0) * (y1 - y0) < min_frac * W * H:
        return 0, 0, W, H
    return x0, y0, x1, y1


def _pad_reflect(im, box, fw, fh):
    """把 im 的 box 区域扩到 fw×fh；越界处补墙面色（取画面边缘的中位色）。

    补边的目的只是让四边留白等宽，不能凭空造出器物，所以补的是纯底色，
    不用镜像——镜像会把器物翻出来一块，看着像多了一件。
    """
    W, H = im.size
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    sx0, sy0 = max(0, x0), max(0, y0)
    sx1, sy1 = min(W, x1), min(H, y1)
    piece = im.crop((sx0, sy0, sx1, sy1))
    b = max(2, int(min(piece.size) * 0.04))
    arr = np.asarray(piece, dtype=np.float32)
    ring = np.concatenate([arr[:b].reshape(-1, 3), arr[-b:].reshape(-1, 3),
                           arr[:, :b].reshape(-1, 3), arr[:, -b:].reshape(-1, 3)])
    fill = tuple(int(v) for v in np.median(ring, axis=0))
    canvas = Image.new("RGB", (fw, fh), fill)
    canvas.paste(piece, (int(sx0 - x0), int(sy0 - y0)))
    return canvas


def crop(src, dst, aspect, margin=0.12, max_px=1600, box=None):
    """aspect = 宽/高；margin 为本体长边的留白比例（四边相同）。
    box 给定时（相对坐标 x0,y0,x1,y1）跳过自动识别——用于构图特殊、
    主体与邻柜器物连成一片、自动框会连带进来的照片。"""
    with Image.open(src) as _im:
        im = ImageOps.exif_transpose(_im).convert("RGB")
        W, H = im.size
        if box:
            x0, y0, x1, y1 = [float(v) * s for v, s in zip(box, (W, H, W, H))]
        else:
            x0, y0, x1, y1 = subject_box(im)
        bw, bh = x1 - x0, y1 - y0
        pad = margin * max(bw, bh)
        cw, ch = bw + 2 * pad, bh + 2 * pad
        if aspect:
            if cw / ch > aspect:
                ch = cw / aspect
            else:
                cw = ch * aspect
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        box = (cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2)
        fw, fh = int(round(cw)), int(round(ch))
        out = _pad_reflect(im, box, fw, fh)
        if max_px and max(out.size) > max_px:
            out = out.resize((int(out.size[0] * max_px / max(out.size)),
                              int(out.size[1] * max_px / max(out.size))), Image.LANCZOS)
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        out.save(dst, quality=94, subsampling=0)
        return out.size, (x0, y0, x1, y1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--aspect", type=float, default=0)
    ap.add_argument("--margin", type=float, default=0.12)
    ap.add_argument("--max-px", type=int, default=1600)
    a = ap.parse_args()
    size, box = crop(a.src, a.dst, a.aspect or None, a.margin, a.max_px)
    print(a.dst, size, "subject", tuple(round(v) for v in box))
