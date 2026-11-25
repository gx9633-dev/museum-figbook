#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""大册分批打印：把一份 plates.json 拆成若干批，逐批交给 render.py 打印，再合并成册。

Chrome headless 一次打印几十页时渲染进程会崩（V8 Empty MaybeLocal /
Abnormal renderer termination），12 页量级一直稳定。本脚本不改 render.py 的
版式，只在打印环节分批：每批独立 user-data-dir、独立输出目录，互不干扰。

用法：
  python3 render_book.py 观展图记_全册.json --out 观展图记_全册.pdf [--batch 12]

依赖：pypdf（合并用），render.py 同目录。
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
RENDER = os.path.join(HERE, "render.py")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plates")
    ap.add_argument("--out", required=True)
    ap.add_argument("--batch", type=int, default=12, help="每批页数，默认 12")
    ap.add_argument("--render-args", default="", help="透传给 render.py 的额外参数")
    a = ap.parse_args()

    plates_path = os.path.abspath(a.plates)
    root = os.path.dirname(plates_path)
    data = json.load(open(plates_path, encoding="utf-8"))
    ids = [str(p["id"]) for p in data["plates"]]
    stem = data.get("meta", {}).get("stem", "figbook")
    total = len(ids)
    print(f"全册 {total} 页，分 {(total + a.batch - 1) // a.batch} 批打印（每批 {a.batch} 页）", flush=True)

    try:
        from pypdf import PdfWriter
    except ImportError:
        raise SystemExit("缺少 pypdf，请先执行：python3 -m pip install pypdf")

    tmp = tempfile.mkdtemp(prefix="figbk-book-")
    parts = []
    try:
        # 先打印目录页（单页），置于册首
        tocdir = os.path.join(tmp, "toc")
        os.makedirs(tocdir, exist_ok=True)
        cmd = [sys.executable, RENDER, plates_path,
               "--toc-only", "--pdf", "--out-dir", tocdir]
        r = subprocess.run(cmd, capture_output=True, text=True)
        toc_pdf = os.path.join(tocdir, stem + ".pdf")
        if r.returncode or not os.path.exists(toc_pdf):
            print("目录页打印失败：\n%s\n%s" % (r.stdout[-600:], r.stderr[-600:]),
                  file=sys.stderr)
        else:
            parts.append(toc_pdf)
            print("  目录页：1 页", flush=True)

        for bi in range(0, total, a.batch):
            batch = ids[bi:bi + a.batch]
            outdir = os.path.join(tmp, "b%02d" % (bi // a.batch))
            os.makedirs(outdir, exist_ok=True)
            cmd = [sys.executable, RENDER, plates_path,
                   "--only", ",".join(batch), "--pdf", "--out-dir", outdir]
            if a.render_args:
                cmd += a.render_args.split()
            r = subprocess.run(cmd, capture_output=True, text=True)
            pdf = os.path.join(outdir, stem + ".pdf")
            if r.returncode or not os.path.exists(pdf):
                print("第 %d 批失败：\n%s\n%s" % (bi // a.batch + 1,
                      r.stdout[-800:], r.stderr[-800:]), file=sys.stderr)
                raise SystemExit("分批打印中止")
            parts.append(pdf)
            print("  批 %d：%s（%d 页）" % (bi // a.batch + 1,
                  " ".join(batch[:3]) + ("…" if len(batch) > 3 else ""), len(batch)), flush=True)

        writer = PdfWriter()
        for p in parts:
            writer.append(p)
        os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
        with open(a.out, "wb") as f:
            writer.write(f)
        print("合并完成：%s（%d 页）" % (a.out, len(writer.pages)), flush=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
