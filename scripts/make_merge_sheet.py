# -*- coding: utf-8 -*-
"""归并表初稿：把照片按器物归组，生成一张供人工裁定的 CSV。

分工约定（这是本 skill 的核心原则）：
- 人工做高耗 token 的判断：选主图、核实定名（对照展签）、核实照片内容、
  判去留、填展厅·单元。
- AI 做重复性执行：按时间＋哈希归组、建议主图（取清晰度最高）、建议构图与页型，
  其余列留空。

用法：
    python3 make_merge_sheet.py 照片目录 --out 归并表.csv [--dup-seconds 120]
产出：
    归并表.csv   每件器物一行，列见下；人工在表上裁定后交回
列：
    组号, 照片清单, 主图, 暂定名, 定名, 拼音, 展厅·单元, 去留, 构图, 页型, 照片内容核实, 备注
"""
import argparse
import csv
import datetime
import glob
import os

from PIL import Image, ImageOps

from index_photos import dhash, exif_time, sharpness


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--out", default="归并表.csv")
    ap.add_argument("--dup-distance", type=int, default=7)
    ap.add_argument("--dup-seconds", type=int, default=120)
    a = ap.parse_args()

    files = sorted(glob.glob(os.path.join(a.dir, "*.JPG"))
                   + glob.glob(os.path.join(a.dir, "*.jpg")))
    if not files:
        raise SystemExit("目录里没有 jpg")

    rows = []
    for f in files:
        im = ImageOps.exif_transpose(Image.open(f))
        w, h = im.size
        t = exif_time(Image.open(f))
        rows.append({"file": os.path.basename(f), "time": t, "w": w, "h": h,
                     "hash": dhash(im), "sharp": sharpness(Image.open(f))})
    rows.sort(key=lambda r: r["time"] or datetime.datetime(2000, 1, 1))

    groups = []
    for r in rows:
        for g in groups:
            if (bin(g["hash"] ^ r["hash"]).count("1") <= a.dup_distance
                    and abs((r["time"] - g["time"]).total_seconds()) <= a.dup_seconds):
                g["members"].append(r)
                break
        else:
            groups.append({"hash": r["hash"], "time": r["time"], "members": [r]})

    with open(a.out, "w", newline="", encoding="utf-8-sig") as fh:
        wtr = csv.writer(fh)
        wtr.writerow(["组号", "照片清单", "主图", "暂定名", "定名", "拼音",
                      "展厅·单元", "去留", "构图", "页型", "照片内容核实", "备注"])
        for gi, g in enumerate(groups, 1):
            ms = sorted(g["members"], key=lambda m: -m["sharp"])
            main = ms[0]["file"]
            names = " / ".join(m["file"] for m in ms)
            # 构图与页型是建议，人工可改
            orient = "竖" if ms[0]["h"] > ms[0]["w"] else "横"
            page = "portrait" if orient == "竖" else "landscape"
            wtr.writerow([gi, names, main, "", "", "", "", "", orient, page, "", ""])

    print("组数", len(groups), "张数", len(rows))
    print("写出", a.out)
    print("请在表上裁定：选主图、核实定名、核实照片内容、判去留；其余交回由 AI 执行。")


if __name__ == "__main__":
    main()
