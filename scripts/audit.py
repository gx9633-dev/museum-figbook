# -*- coding: utf-8 -*-
"""内容页容量体检：用 Chrome 实测每页的版心占位，判定是否有溢出。

不靠肉眼、不靠字数估算。render.py 出的 HTML 里带一段只写隐藏 div 的脚本，
这里用 --dump-dom 把实测值取回来。

用法：
    python3 audit.py _out/figbook.html
退出码 1 表示有 ERROR，可直接接入流水线。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SAFE_GAP = 1.5      # 正文底与页脚线的最小间距 mm
SPARSE_GAP = 55.0   # 超过此留白视为内容偏少（仅提示）


def dump(html_path):
    tmp = tempfile.mkdtemp(prefix="figbk-audit-")
    try:
        r = subprocess.run([CHROME, "--headless=new", "--disable-gpu",
                            f"--user-data-dir={os.path.join(tmp, 'prof')}",
                            "--virtual-time-budget=3000",
                            "--dump-dom", "file://" + os.path.abspath(html_path)],
                           capture_output=True, text=True, timeout=180)
        return r.stdout
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def metrics(dom):
    m = re.search(r'id="__metrics"[^>]*>(\[.*?\])</div>', dom, re.S)
    if not m:
        raise SystemExit("取不到实测尺寸：HTML 里的测量脚本没有执行，"
                         "确认是 render.py 生成的页面。")
    return json.loads(m.group(1))


def main():
    if len(sys.argv) < 2:
        raise SystemExit("用法：python3 audit.py <html>")
    path = sys.argv[1]
    rows = metrics(dump(path))

    errs, warns = [], []
    print(f"{'页':>3}  {'页高':>6}  {'图底':>7}  {'正文底':>7}  {'页脚线':>7}  {'余量':>6}  判定")
    for o in rows:
        i = o["i"] + 1
        bb, ft = o.get("body_bottom"), o.get("ft_top")
        gap = (ft - bb) if (bb is not None and ft is not None) else None
        flags = []
        if o.get("sheet_h") and abs(o["sheet_h"] - 297.0) > 0.8:
            flags.append(f"页高异常 {o['sheet_h']}")
            errs.append(f"第 {i} 页 页高 {o['sheet_h']}mm，应为 297mm")
        if gap is None:
            flags.append("缺正文")
            errs.append(f"第 {i} 页 没有正文块")
        else:
            if gap < SAFE_GAP:
                flags.append("正文压页脚")
                errs.append(f"第 {i} 页 正文底 {bb}mm 越过页脚线 {ft}mm（余量 {gap:.1f}mm），须删字或减段")
            elif gap > SPARSE_GAP:
                flags.append("留白偏大")
                warns.append(f"第 {i} 页 正文底到页脚线尚有 {gap:.1f}mm，可补一段或增一条注解")
        if o.get("overflow_px", 0) > 1:
            flags.append(f"栏内溢出 {o['overflow_px']}px")
            errs.append(f"第 {i} 页 有栏内容溢出容器 {o['overflow_px']}px，检查注解条数或图高")
        print(f"{i:>3}  {o.get('sheet_h','-'):>6}  {o.get('fig_bottom','-'):>7}  "
              f"{'-' if bb is None else bb:>7}  {'-' if ft is None else ft:>7}  "
              f"{'-' if gap is None else f'{gap:.1f}':>6}  {' '.join(flags) or 'OK'}")

    print()
    for w in warns:
        print("WARN ", w)
    for e in errs:
        print("ERROR", e)
    if not errs and not warns:
        print("全部通过。")
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
