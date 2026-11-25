# -*- coding: utf-8 -*-
"""博物馆观展图记 · 内容页渲染器

数据驱动：读 plates.json，出 HTML / PDF / PNG。版式与标注几何写在本文件里，
不随内容改动。新增一张图 = 往 plates.json 追加一条记录。

用法：
    python3 render.py plates.json                 # 只出 HTML
    python3 render.py plates.json --pdf           # 出 HTML + PDF
    python3 render.py plates.json --pdf --png     # 再加逐页 PNG（供校验）
    python3 render.py plates.json --only 012      # 只渲染某页（调试用）
"""
import argparse
import json
import os
import shutil
import subprocess
import tempfile

from PIL import Image, ImageOps

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# ---------- 版式常量（改版从这里动手，不要散落在模板里） ----------
PAGE_W, PAGE_H = 210.0, 297.0
PAD = "14mm 18mm 16mm"          # 版心 174 × 267
COL_L, COL_R, GUTTER = 118.0, 48.0, 8.0   # 竖版两列
COL_LAND = 174.0                # 横版通栏
BADGE_R = 2.4                   # 标注圆托半径 mm
TARGET_R = 1.15                 # 特征点空心环半径 mm

# ---------- 固定样式 ----------
CSS = """
@page{size:A4;margin:0}
*{margin:0;padding:0;box-sizing:border-box}
:root{
 --paper:#F5F2EB; --ink:#1F1C18; --ink2:#4B463E; --ink3:#857D70;
 --tea:#8A6A4B; --rule:#D8D1C3; --pend:#8A6A4B;
}
body{background:#fff;-webkit-print-color-adjust:exact;print-color-adjust:exact}
.sheet{
 width:210mm;height:297mm;background:var(--paper);color:var(--ink);
 padding:14mm 18mm 16mm;display:grid;
 font-family:"Songti SC","Times New Roman",serif;
 page-break-after:always;overflow:hidden;
}
.sheet:last-child{page-break-after:auto}

/* 标题：名称 21pt 宋体，副题与图注走苹方小字 */
.hd{grid-column:1/-1;grid-row:1;padding-bottom:4.6mm;border-bottom:.4pt solid var(--rule)}
.hd h1{font-size:21pt;font-weight:600;letter-spacing:.05em;line-height:1.16}
.hd .sub{margin-top:2.4mm;display:flex;align-items:center;gap:3mm;
 font-size:6.2pt;color:var(--ink3);letter-spacing:.18em;
 font-family:"PingFang SC","Helvetica Neue",sans-serif}
.hd .sub .ln{width:22mm;height:.5pt;background:var(--tea);display:inline-block;flex:0 0 auto}
.hd .sub em{font-style:normal;color:var(--pend);letter-spacing:.1em}

/* 图：overlay 用整图百分比坐标，图容器高度由原图像素比算出 */
.left,.right{display:flex;flex-direction:column;min-height:0;overflow:hidden}
.fig{position:relative;overflow:hidden;background:#E8E3D8}
.fig img{width:100%;height:100%;object-fit:cover;display:block}
.figwrap{position:relative;overflow:hidden;background:#E8E3D8}
.figwrap img{width:100%;height:auto;display:block}
.ln{position:absolute;left:0;top:0;width:100%;height:100%;overflow:visible}

/* 标注圆托：白底圆 + 茶色细边 + 居中阿拉伯数字。禁止直接写 ①②③ 字形 */
.bdg{position:absolute;border-radius:50%;background:var(--paper);
 border:.5pt solid #FFFFFF;box-shadow:0 0 0 .6pt rgba(42,34,26,.35);
 display:flex;align-items:center;justify-content:center;
 font-family:"PingFang SC",sans-serif;font-size:2.9mm;line-height:1;
 color:var(--tea);font-weight:600}

.cap{font-size:6.2pt;color:var(--ink3);letter-spacing:.09em;
 display:flex;align-items:center;
 font-family:"PingFang SC","Helvetica Neue",sans-serif}

/* 右栏档案 */
.sp{display:flex;flex-direction:column}
.sp .i{border-top:.4pt solid var(--rule);padding:3.4mm 0 3mm}
.sp .i:first-child{border-top:.9pt solid var(--tea)}
/* 展页（左主图 + 右注释）：标题下的通栏细线不画，顶部只留右栏那条深线。
   深线在原位，不横向延伸，不与主图连接。*/
.arcpg > .hd{border-bottom:none}
.sp .i span{display:block;font-size:6.2pt;color:var(--ink3);letter-spacing:.16em;
 font-family:"PingFang SC",sans-serif;margin-bottom:1.2mm}
.sp .i b{display:block;font-size:10pt;font-weight:500;line-height:1.3;letter-spacing:.01em}
.sp .i b em{font-style:normal;font-size:7.2pt;color:var(--pend);letter-spacing:.05em}

/* 注解：一条连续底栏，条间只用细线分隔，不做 flex:1 均布 */
.nts{display:flex;flex-direction:column;
 background:rgba(138,106,75,.05);border-left:1.1pt solid var(--tea)}
.nt{padding:3.2mm 3mm 3.4mm 3.2mm}
.nt+.nt{border-top:.4pt solid rgba(138,106,75,.16)}
.nt .h{font-size:8.4pt;font-weight:600;color:var(--tea);letter-spacing:.04em;
 font-family:"PingFang SC",sans-serif;line-height:1.3}
.nt .h i{font-style:normal;margin-right:1.4mm}
.nt .b{font-size:8.6pt;line-height:1.78;color:var(--ink2);margin-top:1.1mm;
 font-family:"Songti SC",serif;letter-spacing:.01em}

/* 正文：双栏独立流。绝不加 overflow:hidden——那会静默吃掉末段 */
.bodywrap{flex:1;display:flex;flex-direction:column;justify-content:flex-start;min-height:0}
.ntwrap{min-height:0;display:flex;flex-direction:column;margin-top:7mm}
.body{display:grid;grid-template-columns:1fr 1fr;column-gap:9mm;font-size:7.8pt;line-height:2.0;
 color:var(--ink2);text-align:justify}
.body .col{min-width:0}
.body p{text-indent:2em;margin-bottom:3.4mm;break-inside:avoid}
.body p:last-child{margin-bottom:0}

.ft{display:flex;justify-content:space-between;align-items:flex-end;
 border-top:.4pt solid var(--rule);padding-top:2.8mm;
 font-size:6.2pt;color:var(--ink3);letter-spacing:.14em;
 font-family:"PingFang SC",sans-serif}
.ft .mid{letter-spacing:.3em}
"""

# ---------- 细节图（第二张图）样式 ----------
CSS_DETAIL = """
.dt{border-top:.9pt solid var(--tea);padding-top:3.2mm;margin-bottom:1mm}
.dt .cap2{font-size:5.8pt;color:var(--ink3);letter-spacing:.08em;line-height:1.55;
 margin-top:1.7mm;font-family:"PingFang SC",sans-serif}
.dt .cap2 b{font-weight:600;color:var(--tea);letter-spacing:.14em}
.lwm{position:relative;overflow:hidden;background:#E8E3D8;border:.4pt solid rgba(138,106,75,.35)}
.lwm img{width:100%;height:100%;object-fit:cover;display:block}
/* 横版：主图与细节图并排，图注落在细节图下方 */
.row2{display:flex;align-items:flex-start}
"""

# 打印时不起作用，仅供 audit.py 读取实测尺寸
METRICS_JS = """
<script>
(function(){
 var PX=96/25.4, rows=[];
 document.querySelectorAll('.sheet').forEach(function(s,i){
   var sr=s.getBoundingClientRect(), o={i:i};
   var ft=s.querySelector('.ft'), bd=s.querySelector('.body'),
       fg=s.querySelector('.fig, .figwrap'), cap=s.querySelector('.left > .cap');
   o.sheet_h=+(sr.height/PX).toFixed(2);
   o.ft_top=ft?+((ft.getBoundingClientRect().top-sr.top)/PX).toFixed(2):null;
   if(bd) o.body_bottom=+((bd.getBoundingClientRect().bottom-sr.top)/PX).toFixed(2);
   if(fg) o.fig_bottom=+((fg.getBoundingClientRect().bottom-sr.top)/PX).toFixed(2);
   if(cap)o.cap_bottom=+((cap.getBoundingClientRect().bottom-sr.top)/PX).toFixed(2);
   var ov=0, box=s.querySelectorAll('.left, .right, .nts');
   for(var k=0;k<box.length;k++){ ov=Math.max(ov, box[k].scrollHeight-box[k].clientHeight); }
   o.overflow_px=+ov.toFixed(1);
   rows.push(o);
 });
 var d=document.createElement('div');
 d.id='__metrics'; d.style.display='none';
 d.textContent=JSON.stringify(rows);
 document.body.appendChild(d);
})();
</script>
"""


def fig_h(path, w_mm):
    """按原图像素比算图高。禁止写死。"""
    with Image.open(path) as im:
        return w_mm * im.size[1] / im.size[0]


def overlay(pins, W, H, ring=TARGET_R):
    """pins 每项 (label, bx, by, fx, fy)，均为整图相对坐标。
    引线起点在特征点空心环外缘，终点在圆托边缘；圆托不透明，正好截断线头。"""
    svg, badges = [], []
    for i, p in enumerate(pins):
        lab, bx, by, fx, fy = p[0], float(p[1]), float(p[2]), float(p[3]), float(p[4])
        cx, cy = bx * W, by * H
        px, py = fx * W, fy * H
        dx, dy = cx - px, cy - py
        L = (dx * dx + dy * dy) ** .5 or 1
        ux, uy = dx / L, dy / L
        x1, y1 = px + ux * (ring + .35), py + uy * (ring + .35)
        x2, y2 = cx - ux * (BADGE_R + .25), cy - uy * (BADGE_R + .25)
        # 引线双层：底层深色晕边（保证任何底上都可见），上层白线
        svg.append(f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
                   f'stroke="rgba(42,34,26,.55)" stroke-width=".85"/>')
        svg.append(f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
                   f'stroke="#FFFFFF" stroke-width=".42"/>')
        # 特征点空心环：同样双层
        svg.append(f'<circle cx="{px:.2f}" cy="{py:.2f}" r="{ring}" fill="none" '
                   f'stroke="rgba(42,34,26,.55)" stroke-width="1.0"/>')
        svg.append(f'<circle cx="{px:.2f}" cy="{py:.2f}" r="{ring}" fill="none" '
                   f'stroke="#FFFFFF" stroke-width=".55"/>')
        # 圆托里放阿拉伯数字；pins 的 label 仅供人读，渲染一律用序号
        badges.append(f'<span class="bdg" style="left:{cx - BADGE_R:.2f}mm;'
                      f'top:{cy - BADGE_R:.2f}mm;width:{2 * BADGE_R}mm;'
                      f'height:{2 * BADGE_R}mm">{i + 1}</span>')
    return (f'<svg class="ln" viewBox="0 0 {W:.2f} {H:.2f}" preserveAspectRatio="none">'
            + ''.join(svg) + '</svg>' + ''.join(badges))


def sub_html(sub, pending=False):
    tail = '<em>（定名待核）</em>' if pending else ''
    return f'<div class="sub"><span class="ln"></span>{sub}{tail}</div>'


def head(r, pending):
    cap = (f'<div class="cap" style="margin-top:1.9mm">{r["caption"]}</div>'
           if r.get('cap_head') else '')
    return (f'<div class="hd"><h1>{r["name"]}</h1>'
            f'{sub_html(r.get("sub", ""), pending)}{cap}</div>')


def page_toc(plates, footer):
    from collections import OrderedDict

    def num(f):
        try:
            return "%02d" % int(str(f).lstrip("P"))
        except Exception:
            return f

    chs = OrderedDict()
    for p in plates:
        ch = p.get("chapter") or "其他"
        chs.setdefault(ch, []).append((p.get("folio", ""), p.get("name", "")))
    items = list(chs.items())
    total = sum(len(v) for _, v in items)
    per = total / 4.0  # 分四栏，每栏约四分之一

    # 分组：章尽量完整，长章拆分，每栏接近 per 条
    cols, cur, cur_n = [], [], 0
    for ch, its in items:
        L = len(its)
        if cur_n + L <= per + 4 or cur_n == 0:
            cur.append((ch, its)); cur_n += L
        else:
            room = int(per - cur_n)
            if room >= 4:
                cur.append((ch, its[:room])); cur_n += room
                cols.append(cur); cur = [(ch + "（续）", its[room:])]; cur_n = L - room
            else:
                cols.append(cur); cur = [(ch, its)]; cur_n = L
    if cur:
        cols.append(cur)

    def rows_html(its):
        return "".join(
            f'<div class="it"><span class="nm">{n}</span>'
            f'<span class="dots"></span><span class="pg">{num(f)}</span></div>'
            for f, n in its)

    def col_html(chapters):
        g = ""
        for ch, its in chapters:
            g += f'<div class="grp"><h3>{ch}</h3>{rows_html(its)}</div>'
        return g

    sheets = ""
    npages = (len(cols) + 1) // 2
    for pi in range(0, len(cols), 2):
        left = col_html(cols[pi]) if pi < len(cols) else ""
        right = col_html(cols[pi + 1]) if pi + 1 < len(cols) else ""
        sheets += ('<div class="sheet toc"><div class="th">目　录</div>'
                   f'<div class="cols"><div class="col">{left}</div><div class="col">{right}</div></div>'
                   f'<div class="ft"><span>{footer}</span><span>{pi // 2 + 1} / {npages}</span></div></div>')
    return sheets


def page_cover(footer):
    return ('<div class="sheet cover"><div class="cframe"></div><div class="cframe2"></div>'
            '<div class="ctop"><div class="csub">观展图记</div>'
            '<div class="ctitle">陕西历史博物馆</div></div>'
            '<div class="cdate">二〇二六年四月记</div></div>')


def foot(r, row, footer):
    return (f'<div class="ft" style="grid-column:1/-1;grid-row:{row}">'
            f'<span>{footer}</span>'
            f'<span class="mid">{r.get("chapter", "")}</span>'
            f'<span>{r.get("folio", "")}</span></div>')


def specs_html(items):
    return ''.join(f'<div class="i"><span>{k}</span><b>{v}</b></div>' for k, v in items)


def notes_col(notes):
    cards = ''.join(f'<div class="nt"><div class="h"><i>{l}</i>{t}</div>'
                    f'<div class="b">{x}</div></div>' for l, t, x in notes)
    return f'<div class="nts">{cards}</div>'


def body_html(r):
    paras = r.get('body', [])
    if not paras:
        return ''
    n = len(paras)
    left = (n + 1) // 2  # 左栏取多：三=左2右1，四=左2右2，五=左3右2
    lp = ''.join(f'<p>{p}</p>' for p in paras[:left])
    rp = ''.join(f'<p>{p}</p>' for p in paras[left:])
    return f'<div class="col">{lp}</div><div class="col">{rp}</div>'


def extras_col(extras, width):
    """附属图列：竖版放在右栏顶部，档案之下。张数多则压高度，不滚出页面。"""
    n = len(extras)
    cap = {1: 46.0, 2: 33.0}.get(n, 26.0)
    out = []
    for d in extras:
        h = min(fig_h(d["_path"], width), cap)
        out.append(
            '<div class="dt" style="width:%gmm">'
            '<div class="lwm" style="height:%.2fmm;background:#FBF8F1;display:flex;'
            'align-items:center;justify-content:center">'
            '<img src="%s" style="width:100%%;height:100%%;object-fit:contain"></div>'
            '<div class="cap2"><b>%s</b>　%s</div></div>'
            % (width, h, os.path.basename(d["_path"]),
               d.get("kind", "细节"), d.get("caption", "")))
    return '<div class="dts">%s</div>' % "".join(out)


def page_portrait(r, img, footer):
    """竖图页：左列 图 → 图注 → 正文；右列 档案 → 注解。两列各成一流，结构上不会重叠。
    图宽可另给 `w`，右栏随之收窄，用来把偏空的页面撑满。"""
    W = r.get("w", COL_L)
    RW = COL_LAND - W - GUTTER
    H = fig_h(img, W)
    return f'''<div class="sheet arcpg" style="grid-template-columns:{W:g}mm {RW:g}mm;column-gap:{GUTTER:g}mm;
     grid-template-rows:auto 1fr 7mm">
{head(r, r.get('pending'))}
<div class="left" style="grid-column:1;grid-row:2">
  <div class="fig" style="flex:0 0 auto;height:{H:.2f}mm">
    <img src="{os.path.basename(img)}">{overlay(r.get('pins', []), W, H, r.get('ring', TARGET_R))}
  </div>
  <div class="cap" style="flex:0 0 auto;margin-top:2.2mm">{r.get("caption", "")}</div>
  <div class="bodywrap" style="padding-top:8.5mm"><div class="body">{body_html(r)}</div></div>
</div>
<div class="right arc" style="grid-column:2;grid-row:2">
  {extras_col(r['extras'], RW) if r.get('extras') else ''}
  <div class="sp">{specs_html(r.get('specs', []))}</div>
  <div class="ntwrap">{notes_col(r.get('notes', []))}</div>
</div>
{foot(r, 3, footer)}
</div>'''


def page_landscape(r, img, footer):
    """横图页：图通栏不裁切，档案条横排、注解横栏、正文通栏。"""
    W = r.get("w", COL_LAND)
    H = fig_h(img, W)
    spec_bar = ''.join(
        f'<div style="flex:1;border-left:.4pt solid var(--rule);padding-left:4mm">'
        f'<div style="font-size:6.2pt;color:var(--ink3);letter-spacing:.16em;'
        f'font-family:\'PingFang SC\',sans-serif;margin-bottom:1.1mm">{k}</div>'
        f'<div style="font-size:10pt;line-height:1.32">{v}</div></div>'
        for k, v in r.get('specs', []))
    cards = ''.join(
        f'<div class="nt" style="flex:1;padding:3mm 4mm;'
        f'border-left:{"none" if i == 0 else ".4pt solid rgba(138,106,75,.16)"}">'
        f'<div class="h"><i>{l}</i>{t}</div><div class="b">{x}</div></div>'
        for i, (l, t, x) in enumerate(r.get('notes', [])))
    ex = r.get('extras') or []
    if len(ex) > 1:
        raise SystemExit(
            f"横版一页只能带 1 张附属图（id={r.get('id')}）：注解栏右端只有一格。"
            f"要放两张及以上，改 layout=portrait，主图 118mm、右栏可叠两张。")
    if ex:
        d = ex[0]
        cards += (
            '<div class="nt exx" style="display:flex;flex-direction:column">'
            '<div class="lwm" style="height:30mm;background:#FBF8F1;display:flex;'
            'align-items:center;justify-content:center">'
            '<img src="%s" style="width:100%%;height:100%%;object-fit:contain"></div>'
            '<div class="cap2"><b>%s</b>　%s</div></div>'
            % (os.path.basename(d["_path"]), d.get("kind", "细节"),
               d.get("caption", "")))
    return f'''<div class="sheet" style="grid-template-columns:1fr;
     grid-template-rows:auto {H:.2f}mm auto auto 1fr 7mm">
{head(r, r.get('pending'))}
<div class="figwrap" style="grid-column:1;grid-row:2">
  <img src="{os.path.basename(img)}">{overlay(r.get('pins', []), W, H, r.get('ring', TARGET_R))}
</div>
<div style="grid-column:1;grid-row:3;display:flex;border-top:.9pt solid var(--tea);
     padding-top:3.2mm;margin-top:2.6mm">{spec_bar}</div>
<div class="nts" style="grid-column:1;grid-row:4;flex-direction:row;margin-top:4.5mm">{cards}</div>
<div class="bodywrap" style="grid-column:1;grid-row:5;padding-top:4mm">
  <div class="body">{body_html(r)}</div>
</div>
{foot(r, 6, footer)}
</div>'''


def normalize(src, out, pid, crop=None):
    """EXIF 归正 + 可选裁切，产出物写进输出目录，原图只读不动。

    iPhone 照片多为 Orientation=6：原始像素是横的，显示时要转 90°。不归正会有两个后果
    ——图被转了 90°，且 fig_h() 用原始宽高算出错误的长宽比。只有确实需要转或要裁时才
    重编码；orientation=1 且不裁切的原图直接返回，避免无谓的 JPEG 重压。
    """
    dst = os.path.join(out, "p%s.jpg" % pid)
    with Image.open(src) as im:
        orient = im.getexif().get(274, 1)
        if not crop and orient in (0, 1):
            # 原样使用，但仍要给一个按页唯一的文件名：不同目录下同名的
            # 1.jpg、2.jpg 会在输出目录里互相覆盖，页面上就会串图。
            if os.path.lexists(dst):
                os.remove(dst)
            os.symlink(os.path.abspath(src), dst)
            return dst
        im2 = ImageOps.exif_transpose(im).convert("RGB")
        if crop:
            W, H = im2.size
            x0, y0, x1, y1 = [float(v) for v in crop]
            im2 = im2.crop((int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H)))
        im2.save(dst, quality=96, subsampling=0)
        return dst


def detail_block(d, width, max_h=None):
    """细节图：图 + 小图注。宽固定，高度按裁片比例算，超过 max_h 时改按 cover 截取。"""
    p = d["_path"]
    h = fig_h(p, width)
    capped = max_h and h > max_h
    h = min(h, max_h) if max_h else h
    cap = d.get("caption", "")
    return (f'<div class="dt" style="width:{width:g}mm">'
            f'<div class="lwm" style="height:{h:.2f}mm">'
            f'<img src="{os.path.basename(p)}"'
            f'{" style=\"object-position:center\" " if capped else " "}>'
            f'</div>'
            f'<div class="cap2"><b>细节</b>　{cap}</div></div>')


def page_portrait_detail(r, img, footer):
    """竖图 + 细节图：主图占满左栏（不动已定稿的左栏结构）；细节图放右栏顶部 48mm。
    48mm 是右栏净宽，方形裁片正好占满；细节图不占版面高度之外的空间，
    因为右栏本来就有 40—50mm 的余量（档案 4 项 + 注解 3 条约 190mm）。
    """
    W = COL_L
    H = fig_h(img, W)
    det = detail_block(r["detail"], COL_R)
    return f'''<div class="sheet arcpg" style="grid-template-columns:{COL_L:g}mm {COL_R:g}mm;column-gap:{GUTTER:g}mm;
     grid-template-rows:auto 1fr 7mm">
{head(r, r.get('pending'))}
<div class="left" style="grid-column:1;grid-row:2">
  <div class="fig" style="flex:0 0 auto;height:{H:.2f}mm">
    <img src="{os.path.basename(img)}">{overlay(r.get('pins', []), W, H, r.get('ring', TARGET_R))}
  </div>
  <div class="cap" style="flex:0 0 auto;margin-top:2.2mm">{r.get("caption", "")}</div>
  <div class="bodywrap" style="padding-top:6mm"><div class="body">{body_html(r)}</div></div>
</div>
<div class="right arc" style="grid-column:2;grid-row:2">
  {det}
  <div class="sp" style="margin-top:4.5mm">{specs_html(r.get('specs', []))}</div>
  <div class="ntwrap">{notes_col(r.get('notes', []))}</div>
</div>
{foot(r, 3, footer)}
</div>'''


def page_landscape_detail(r, img, footer):
    """横版不放细节图——这是版面算术的结论，不是偏好。

    横版通栏 174mm 的 4:3 主图高 130mm，加上标题 30、档案 14、注解 40、正文 30、
    页脚 7 与行距 12，已经 263mm，只剩 4mm。硬塞 48mm 细节图，只能把主图缩到 120mm
    （高 90mm），页面下半必然空出 60—70mm，比不放细节图更差。
    横图需要放大某处时，做法是「裁切成页」：把那一处裁出来，用竖版单独成页。
    """
    raise SystemExit(f"横版不支持 detail（id={r.get('id')}）。"
                     "横图请改用 layout=portrait 承载细节，或把需要放大的局部裁出单独成页。")


# ---------- 附属图（细节／另一角度／背面／线图） ----------
CSS_EXTRA = """
.dts{display:flex;flex-direction:column;gap:3.2mm;margin-bottom:1mm}
.dts .dt{margin-bottom:0}
.nt .exx{flex:0 0 46mm;padding:3mm 3mm 2.4mm 4mm;border-left:.4pt solid rgba(138,106,75,.16)}
.nt .exx .lwm{height:30mm}
.nt.exx .cap2,.nt .exx .cap2{font-size:5.6pt;line-height:1.45;color:var(--ink3);
 letter-spacing:.06em;margin-top:2mm;font-family:"PingFang SC",sans-serif}
"""

# ---------- 组页：多件小器同页（图列＋底部案语带） ----------
CSS_SET = """
.st{grid-column:1/-1;grid-row:2;display:flex;gap:5mm;align-items:flex-start;padding-top:2mm}
.st-i{display:flex;flex-direction:column;min-width:0}
/* 三片裁成同一比例（3:4），列宽相等则框高相等；不再贴底对齐，免得出现高差 */
.st-fw{display:block;overflow:hidden}
.st-fw img{width:100%;height:auto;display:block}
.st-fw img.flat{mix-blend-mode:multiply}
.st-n{font-size:13.6pt;letter-spacing:.06em;margin-top:3.4mm;line-height:1.3}
.st-n span{font-size:6.8pt;color:var(--ink3);letter-spacing:.05em;margin-left:1.6mm;
 font-family:"PingFang SC",sans-serif}
.st-d{font-size:7.4pt;line-height:1.95;color:var(--ink2);margin-top:1.9mm;text-align:justify}
/* 案语：通栏、双栏流、贴页脚——不留右侧与下方的空当 */
.set-tail{display:flex;gap:8mm;border-top:.9pt solid var(--tea);padding-top:4.2mm}
.set-tail .lab{flex:0 0 15mm;font-size:6.2pt;color:var(--tea);letter-spacing:.26em;
 font-family:"PingFang SC",sans-serif;padding-top:.8mm}
.set-tail .tx{flex:1;min-width:0}
.set-tail .tx p{font-size:8.1pt;line-height:2.08;color:var(--ink2);text-align:justify;
 text-indent:2em;margin-bottom:2.4mm;break-inside:avoid}
/* 只有一段时不缩进：段首缩进是分段标记，独此一段无须标记，缩了反而与标签错开 */
.set-tail .tx.one p{text-indent:0}
.set-tail .tx p:only-child{text-indent:0}
.set-tail .tx p:last-child{margin-bottom:0}
.set-tail .tx.two{column-count:2;column-gap:9mm}
"""


# ---------- 图鉴页：一格一件，格内两视图 ----------
CSS_PGRID = """
.pg{display:grid;grid-template-columns:1fr 1fr;gap:9.5mm 8mm;padding-top:4mm;
 align-items:start}
.pg.c3{grid-template-columns:repeat(3,1fr)}
.pg.wf .pgi:first-child{grid-column:1/-1}
.pgi{display:flex;flex-direction:column;min-width:0}
/* 图框仿展板：细线方框，器名压在框线上做签条；框高随图定，不在框里留空 */
.pgf{position:relative;border:.35pt solid var(--rule);
 padding:6.8mm 4.2mm 3.2mm;display:flex;align-items:flex-end;justify-content:center;gap:3.4mm}
/* 窄格：两视图上下叠放，横向居中 */
.pgf.stk{flex-direction:column;justify-content:flex-end;align-items:center;gap:2.4mm}
.pgt{position:absolute;top:-2.9mm;left:3.6mm;background:var(--paper);padding:0 2.2mm;
 font-size:9.4pt;letter-spacing:.14em;line-height:1.85}
.pgt i{font-style:normal;font-size:6.4pt;color:var(--ink3);letter-spacing:.05em;
 margin-left:1.2mm;font-family:"PingFang SC",sans-serif}
/* 同一件的两个视图同一高度：底边齐平，大小相若，像立在同一道地平线上 */
.pgf img{width:auto;display:block}
.pgd{font-size:7.3pt;line-height:1.95;color:var(--ink2);margin-top:2.6mm;text-align:justify}
/* 案语若落进格子里，就占空着的那一格，省得留一个洞 */
.pgtx{justify-content:flex-start;padding-top:1mm}
.pgtx .lab{font-size:6.4pt;color:var(--ink3);letter-spacing:.3em;margin-bottom:3mm}
.pgtx .tx{font-size:7.6pt;line-height:2.05;color:var(--ink2);text-align:justify}
"""


def page_pgroup(r, footer):
    """图鉴页：一格一件，件下释文；格内正、背两视图，宽格并立、窄格叠放。

    框高由线图本身定：不再给死高度再让图去贴底，否则宽扁器（盘、鉴）
    会在框里空出一大截，图与释文之间也跟着拉开。同一页共用一个框高，
    图一律底边齐平，读起来像立在同一道地平线上。
    """
    cols = r.get("cols", 2)
    stack = r.get("stack", cols >= 3)
    pad_t, pad_b = 6.8, 3.2
    gapx, gap_sbs, gap_stk = 8.0, 3.4, 2.4
    cell_w = (174.0 - gapx * (cols - 1)) / cols
    avail_w = cell_w - 8.4
    h_limit = r.get("fig_h", 78.0 if cols >= 3 else 82.0)   # 图高上限

    def ars(it):
        out = []
        for pth in it["_paths"]:
            with Image.open(pth) as im0:
                out.append(im0.width / im0.height)
        return out

    def nat_stk(it, w):
        """叠放：两个视图各取格宽，纵向相加。"""
        a = ars(it)
        return sum(w / x for x in a) + gap_stk * (len(a) - 1)

    def nat_row(it, w):
        """并立：两视图同高并排，高由格宽反算。"""
        a = ars(it)
        return (w - gap_sbs * (len(a) - 1)) / sum(a)

    wide_first = bool(r.get("wide_first")) and len(r["items"]) > 1
    body_items = r["items"][1:] if wide_first else r["items"]
    stk = stack

    # 整页统一框高：叠放页让图铺满上限，并立页取各格自然高里的最大值
    if stk:
        h = h_limit
    else:
        nat = [nat_row(it, avail_w) for it in body_items]
        h = min(h_limit, max(nat)) if nat else h_limit
    fh = h + pad_t + pad_b

    cells = []
    if wide_first:
        it = r["items"][0]
        w = 174.0 - 8.4
        wh = min(nat_row(it, w), h_limit)
        wfh = wh + pad_t + pad_b
        imgs = "".join('<img src="%s" style="height:%.2fmm">'
                       % (os.path.basename(pth), wh) for pth in it["_paths"])
        cells.append(
            '<div class="pgi"><div class="pgf" style="height:%.1fmm">'
            '<div class="pgt">%s<i>%s</i></div>%s</div>'
            '<div class="pgd">%s</div></div>'
            % (wfh, it["name"], it.get("py", ""), imgs, it.get("desc", "")))

    for it in body_items:
        if stk:
            a = ars(it)
            k = min(1.0, (h - gap_stk * (len(a) - 1)) / sum(avail_w / x for x in a))
            imgs = "".join('<img src="%s" style="width:%.2fmm">'
                           % (os.path.basename(pth), avail_w * k) for pth in it["_paths"])
        else:
            imgs = "".join('<img src="%s" style="height:%.2fmm">'
                           % (os.path.basename(pth), min(h, nat_row(it, avail_w)))
                           for pth in it["_paths"])
        cells.append(
            '<div class="pgi"><div class="pgf%s" style="height:%.1fmm">'
            '<div class="pgt">%s<i>%s</i></div>%s</div>'
            '<div class="pgd">%s</div></div>'
            % (" stk" if stk else "", fh, it["name"], it.get("py", ""), imgs,
               it.get("desc", "")))
    paras = r.get("body", [])
    if r.get("tail_cell") and paras:
        cells.append('<div class="pgi pgtx"><div class="lab">%s</div>'
                     '<div class="tx">%s</div></div>'
                     % (r.get("tail_label", "案语"),
                        "".join("<p>%s</p>" % x for x in paras)))
        tail_html = ""
    else:
        # 单段不缩进（段首缩进是分段标记，独一段无须标记）；直接写行内样式，
        # 组合类与伪类在打印流程里不一定吃得准
        ind = ' style="text-indent:0"' if len(paras) == 1 else ""
        tail = "".join("<p%s>%s</p>" % (ind, x) for x in paras)
        cls_tx = " two" if len(paras) > 1 else " one"
        tail_html = ('<div class="set-tail"><div class="lab">%s</div>'
                     '<div class="tx%s">%s</div></div>'
                     % (r.get("tail_label", "案语"), cls_tx, tail)) if paras else ""
    lede = "".join("<p>%s</p>" % x for x in r.get("lede", []))
    cls = ("pg" + (" c3" if cols >= 3 else "") + (" wf" if wide_first else ""))
    # 案语紧接图版，不再用弹性空白把它推到页底——页底留白交给最后那段弹性空白
    tail_block = ('<div style="margin-top:9mm">%s</div>\n' % tail_html) if tail_html else ""
    return (('<div class="sheet" style="display:flex;flex-direction:column">\n%s\n'
             '%s\n'
             '<div class="%s">%s</div>\n'
             '%s'
             '<div style="flex:1"></div>\n'
             '<div style="margin-top:7mm">%s</div>\n</div>')
            % (head(r, r.get("pending")),
               ('<div class="tb-h">%s</div>' % lede) if lede else "",
               cls, "".join(cells), tail_block, foot(r, 5, footer)))


# ---------- 双件页：同名两器，各给档案 ----------
CSS_PAIR = """
.pr{display:flex;flex-direction:column;padding-top:4mm}
.pr-i{display:flex;gap:9mm;align-items:flex-start}
.pr-i+.pr-i{margin-top:8mm;padding-top:7mm;border-top:.4pt solid var(--rule)}
.pr-fw{flex:0 0 108mm;background:transparent;display:flex;align-items:flex-end;
 justify-content:center;overflow:hidden}
.pr-fw img{width:100%;height:auto;display:block}
.pr-tx{flex:1;min-width:0;padding-top:1mm}
.pr-tag{font-size:6.2pt;color:var(--tea);letter-spacing:.22em;
 font-family:"PingFang SC",sans-serif}
.pr-sp{margin-top:1.6mm}
.pr-sp .i{display:flex;gap:3mm;padding:1.9mm 0;border-top:.4pt solid var(--rule)}
.pr-sp .i:first-child{border-top:.9pt solid var(--tea)}
.pr-sp .k{flex:0 0 12mm;font-size:6.2pt;color:var(--ink3);letter-spacing:.12em;
 font-family:"PingFang SC",sans-serif;padding-top:.6mm}
.pr-sp .v{flex:1;font-size:8.4pt;line-height:1.5}
.pr-d{font-size:7.6pt;line-height:1.95;color:var(--ink2);margin-top:3mm;text-align:justify}
"""

# ---------- 表页：多列书籍表 ----------
CSS_TB2 = """
.t2{grid-column:1/-1;grid-row:3;width:100%;border-collapse:collapse;align-self:start}
.t2 th{font-size:6.2pt;color:var(--ink3);letter-spacing:.14em;font-weight:400;
 text-align:left;padding:0 2mm 2.2mm 0;border-bottom:.9pt solid var(--tea);
 font-family:"PingFang SC",sans-serif}
.t2 td{font-size:8.6pt;padding:2.5mm 2mm 2.6mm 0;border-bottom:.4pt solid var(--rule);
 color:var(--ink);vertical-align:middle}
.t2 td.nm{font-size:10pt;letter-spacing:.06em;white-space:nowrap}
.t2 td.sm{font-size:7.2pt;color:var(--ink2);font-family:"PingFang SC",sans-serif;
 letter-spacing:.02em}
.t2 tr:last-child td{border-bottom:none}
.t2 td:last-child,.t2 th:last-child{padding-right:0}
"""

# ---------- 科普页：文字＋算筹数字样 ----------
CSS_EXP = """
.xp-h{grid-column:1/-1;grid-row:2;font-size:8.6pt;line-height:2.05;color:var(--ink2);
 max-width:158mm;text-align:justify;padding:4mm 0 0}
.xp-h p{text-indent:2em}
.xp-fig{grid-column:1/-1;grid-row:3;margin-top:7mm;padding:5.5mm 0 3mm;
 border-top:.9pt solid var(--tea)}
.xp-row{display:flex;align-items:center;gap:0}
.xp-row+.xp-row{margin-top:3.2mm}
.xp-lab{flex:0 0 22mm;font-size:6.4pt;color:var(--tea);letter-spacing:.2em;
 font-family:"PingFang SC",sans-serif}
.xp-cell{flex:1;display:flex;flex-direction:column;align-items:center;gap:2mm}
.xp-dg{font-size:7pt;color:var(--ink3);font-family:"PingFang SC",sans-serif}
.rod{display:flex;flex-direction:column;align-items:center;justify-content:flex-end;
 height:20mm;gap:1.4mm}
.rod .r{background:var(--ink);border-radius:.35mm}
.rod .rv{width:.75mm;height:6.6mm}
.rod .rh{width:7.4mm;height:.75mm}
.rod .row{display:flex;gap:1.3mm;align-items:flex-end}
.rod .col{display:flex;flex-direction:column;gap:1.5mm;align-items:center}
.xp-ex{margin-top:5mm;display:flex;align-items:flex-end;gap:4mm}
.xp-ex+.xp-ex{margin-top:4mm;padding-top:3mm;border-top:.4pt solid var(--rule)}
.xp-ex .num{display:flex;gap:4mm;align-items:flex-end}
.xp-ex .cap2{font-size:6.2pt;color:var(--ink3);letter-spacing:.05em;margin-left:auto;
 font-family:"PingFang SC",sans-serif}
.xp-b{grid-column:1/-1;grid-row:5;margin-top:11mm;padding-top:6.5mm;
 border-top:.9pt solid var(--tea);font-size:7.8pt;line-height:2.0;
 color:var(--ink2);column-count:2;column-gap:9mm;text-align:justify}
.xp-b p{text-indent:2em;margin-bottom:2.6mm;break-inside:avoid}
.xp-note{grid-column:1/-1;grid-row:7;font-size:6.2pt;color:var(--ink3);line-height:1.75;
 border-top:.4pt solid var(--rule);padding-top:3.2mm;letter-spacing:.04em;margin-bottom:5mm;
 font-family:"PingFang SC",sans-serif}
"""

# ---------- 跨页：左图右文 ----------
CSS_SPREAD = """
.sp-l{grid-column:1/-1;grid-row:2;display:flex;flex-direction:column;justify-content:flex-end;
 align-items:center;min-height:0}
.sp-l .lwm{background:transparent;overflow:hidden;display:flex;align-items:flex-end;
 justify-content:center}
.sp-l img{width:100%;height:auto;display:block}
.sp-cap{grid-column:1/-1;grid-row:3;font-size:6.2pt;color:var(--ink3);letter-spacing:.09em;
 margin-top:3mm;font-family:"PingFang SC",sans-serif;text-align:center}
.sp-lede{grid-column:1/-1;grid-row:2;font-size:9.6pt;line-height:2.15;color:var(--ink2);
 text-align:justify;padding-top:4mm}
.sp-lede p{text-indent:2em;margin-bottom:3mm}
.sp-b{grid-column:1/-1;grid-row:3;align-self:end;padding-bottom:6mm;font-size:8.6pt;line-height:2.15;color:var(--ink2);
 column-count:2;column-gap:9mm;text-align:justify;margin-top:5mm;
 border-top:.9pt solid var(--tea);padding-top:4mm}
.sp-b p{text-indent:2em;margin-bottom:2.6mm;break-inside:avoid}
.sp-note{grid-column:1/-1;grid-row:4;font-size:6.2pt;color:var(--ink3);line-height:1.75;
 border-top:.4pt solid var(--rule);padding-top:3.2mm;letter-spacing:.04em;
 font-family:"PingFang SC",sans-serif}
"""


def _rods(n, vertical=True):
    """算筹数字：1—5 为同向并列，6—9 为上面一横（或一竖）加下面相应根数。"""
    if n <= 0:
        return '<div class="rod"></div>'
    perp, para = ("h", "v") if vertical else ("v", "h")
    cls = {"v": "rv", "h": "rh"}
    if n <= 5:
        if vertical:
            bars = ['<div class="r %s"></div>' % cls['v']] * n
            return '<div class="rod"><div class="row">%s</div></div>' % "".join(bars)
        bars = ['<div class="r %s"></div>' % cls['h']] * n
        return '<div class="rod">%s</div>' % "".join(bars)
    top = '<div class="r %s"></div>' % cls[perp]
    rest = ['<div class="r %s"></div>' % cls[para]] * (n - 5)
    if vertical:
        return ('<div class="rod">%s<div class="row">%s</div></div>'
                % (top, "".join(rest)))
    return ('<div class="rod">%s<div class="col">%s</div></div>'
            % (top, "".join(rest)))


def page_set(r, footer):
    """组页：一页两三件小器，各占一列，图贴底对齐；案语通栏贴页脚。"""
    items = r["items"]
    n = len(items)
    w = (COL_LAND - 6 * (n - 1)) / n
    cells = []
    for it in items:
        cells.append(
            '<div class="st-i" style="flex:0 0 %.2fmm">'
            '<div class="st-fw"><img class="%s" src="%s"></div>'
            '<div class="st-n">%s<span>%s</span></div>'
            '<div class="st-d">%s</div></div>'
            % (w, "flat" if it.get("flat") else "", os.path.basename(it["_path"]),
               it["name"], it.get("py", ""), it.get("desc", "")))
    paras = r.get("body", [])
    tail = "".join("<p>%s</p>" % p for p in paras)
    two = " two" if len(paras) > 1 else ""
    tail_html = (
        '<div class="set-tail"><div class="lab">%s</div>'
        '<div class="tx%s">%s</div></div>' % (r.get("tail_label", "案语"), two, tail)
    ) if paras else ""
    return (('<div class="sheet" style="display:flex;flex-direction:column">\n%s\n'
             '<div class="st">%s</div>\n'
             '<div style="margin-top:12mm">%s</div>\n'
             '<div style="flex:1"></div>\n'
             '<div style="margin-top:0">%s</div>\n</div>')
            % (head(r, r.get("pending")), "".join(cells), tail_html,
               foot(r, 5, footer)))


def page_pair(r, footer):
    """双件页：同名两器并置，各给档案与简释；正文通栏。"""
    items = r["items"]
    cells = []
    for k, it in enumerate(items):
        sp = "".join('<div class="i"><div class="k">%s</div><div class="v">%s</div></div>'
                     % (a, b) for a, b in it.get("specs", []))
        cells.append(
            '<div class="pr-i"><div class="pr-fw">'
            '<img src="%s"></div>'
            '<div class="pr-tx"><div class="pr-tag">%s</div>'
            '<div class="pr-sp">%s</div>'
            '<div class="pr-d">%s</div></div></div>'
            % (os.path.basename(it["_path"]),
               it.get("tag", "其%d" % (k + 1)), sp, it.get("desc", "")))
    paras = r.get("body", [])
    tail = "".join("<p>%s</p>" % p for p in paras) if not isinstance(paras, str) else paras
    return (('<div class="sheet" style="grid-template-columns:1fr;'
             'display:flex;flex-direction:column">\n%s\n'
             '<div class="pr">%s</div>\n'
             '<div style="margin-top:auto"><div class="set-tail">'
             '<div class="lab">释文</div><div class="tx two">%s</div></div></div>\n'
             '<div style="margin-top:9mm">%s</div>\n</div>')
            % (head(r, r.get("pending")), "".join(cells), tail, foot(r, 5, footer)))


def page_table(r, footer):
    """表页：多列书籍表，列宽由数据给定。"""
    lede = "".join("<p>%s</p>" % x for x in r.get("lede", []))
    cols = r["cols"]
    th = "".join('<th style="width:%s">%s</th>' % (c.get("w", "auto"), c["t"])
                 for c in cols)
    rows = []
    for row in r["rows"]:
        tds = []
        for i, (c, v) in enumerate(zip(cols, row)):
            tds.append('<td class="%s">%s</td>' % (c.get("cls", ""), v))
        rows.append("<tr>%s</tr>" % "".join(tds))
    return (('<div class="sheet" style="grid-template-columns:1fr;'
             'grid-template-rows:auto auto auto 1fr 7mm">\n%s\n'
             '<div class="tb-h">%s</div>\n'
             '<table class="t2" style="height:%s"><thead><tr>%s</tr></thead><tbody>%s</tbody></table>\n'
             '<div class="tb-note">%s</div>\n%s\n</div>')
            % (head(r, r.get("pending")), lede,
               ("%gmm" % r["h"]) if r.get("h") else "auto", th, "".join(rows),
               r.get("note", ""), foot(r, 5, footer)))


# ---------- 世系图：中轴一线，诸帝左右交替，名号贴轴、六项向外 ----------
CSS_TREE = """
.tr{position:relative;width:174mm}
.tr .ax{position:absolute;left:87mm;width:.6pt;background:var(--tea);opacity:.45}
/* 一条：整条横排，名号在近轴一侧，六项在它外侧；纵横都居中，不与邻条相犯 */
.tr .nd{position:absolute;display:flex;align-items:center;gap:2.6mm}
.tr .nd .rows{flex:1 1 auto;min-width:0;display:flex;flex-direction:column;justify-content:center}
.tr .nd .nm{flex:0 0 auto;border:.35pt solid rgba(138,106,75,.55);
 padding:.75mm 2.3mm .85mm;font-size:13.4pt;letter-spacing:.1em;line-height:1.12;
 white-space:nowrap}
/* 六项：行高定死，标签与值同基线；标签一律贴近名号，值向外 */
.tr .nd .g{display:flex;gap:1.9mm;align-items:baseline;height:4.04mm}
.tr .nd .k{flex:0 0 7.0mm;font-size:6.6pt;color:var(--tea);letter-spacing:.1em;
 line-height:4.04mm;font-family:"PingFang SC",sans-serif}
.tr .nd .v{flex:0 1 auto;font-size:7.7pt;color:var(--ink2);line-height:4.04mm;
 letter-spacing:.01em;font-family:"PingFang SC",sans-serif;white-space:nowrap}
.tr .nd .g{justify-content:flex-end}
.tr .nd .k{text-align:right}
.tr .nd.rg .g{justify-content:flex-start}
.tr .nd.rg .k{text-align:left}
"""


def page_tree(r, footer):
    """世系图：中轴一线，诸帝左右交替；每条横排，名号贴轴，六项列于其外侧。"""
    nodes = r["nodes"]
    n = len(nodes)
    row_h = r.get("row_h", 4.04)
    pitch = r.get("pitch", 16.6)
    rib = r.get("rib", 16.0)                     # 中轴到名号框的距离，即横线长度
    edge = r.get("edge", 9.0)                    # 页面左右外边距
    entry_h = round(n * row_h + 1.0, 2)          # 六行高度，名号纵向居中于其中
    nd_w = 87.0 - rib - edge
    y0 = 1.0
    H = y0 + entry_h + (n - 1) * pitch + 1.5
    ribs, divs = [], []
    fields = [("世系", "rel"), ("庙谥", "temple"), ("生卒", "life"),
              ("在位", "reign"), ("陵号", "tomb"), ("葬地", "place")]
    for i, nd in enumerate(nodes):
        top = y0 + i * pitch
        yl = top + entry_h / 2                   # 横线对准整条中腰
        left = i % 2 == 0
        x = edge if left else 87.0 + rib
        ex = (x + nd_w) if left else x
        ribs.append('<line x1="87" y1="%.2f" x2="%.2f" y2="%.2f" stroke="#8A6A4B" '
                    'stroke-width=".4" opacity=".62"/>' % (yl, ex, yl))
        ribs.append('<circle cx="87" cy="%.2f" r=".52" fill="#8A6A4B" opacity=".5"/>' % yl)
        items = [(k, nd.get(key, "")) for k, key in fields if nd.get(key)]
        rows = "".join(
            '<div class="g"><span class="v">%s</span><span class="k">%s</span></div>' % (v, k)
            if left else
            '<div class="g"><span class="k">%s</span><span class="v">%s</span></div>' % (k, v)
            for k, v in items)
        if left:                                 # 左条：行在外、名号在轴侧
            inner = '<div class="rows">%s</div><div class="nm">%s</div>' % (rows, nd["name"])
        else:
            inner = '<div class="nm">%s</div><div class="rows">%s</div>' % (nd["name"], rows)
        divs.append('<div class="nd%s" style="left:%.2fmm;top:%.2fmm;width:%.2fmm;height:%.2fmm">'
                    '%s</div>'
                    % ("" if left else " rg", x, top, nd_w, entry_h, inner))
    lede = "".join("<p>%s</p>" % x for x in r.get("lede", []))
    note = ('<div class="tb-note">%s</div>' % r["note"]) if r.get("note") else '<div></div>'
    return (('<div class="sheet" style="grid-template-columns:1fr;'
             'grid-template-rows:auto auto auto 1fr auto 7mm">\n%s\n'
             '<div class="tb-h">%s</div>\n'
             '<div class="tr" style="height:%.2fmm">'
             '<div class="ax" style="top:%.2fmm;height:%.2fmm"></div>'
             '<svg class="ln" viewBox="0 0 174 %.2f" preserveAspectRatio="none">%s</svg>'
             '%s</div>\n'
             '<div></div>\n'
             '%s\n%s\n</div>')
            % (head(r, r.get("pending")), lede, H,
               y0 + entry_h / 2, (n - 1) * pitch,
               H, "".join(ribs), "".join(divs),
               note, foot(r, 6, footer)))


# ---------- 竖图＋右栏＋通栏正文：单页容纳大片幅展品照 ----------
CSS_TALL = """
.tl-fw{position:relative;overflow:hidden;background:#E8E3D8}
.tl-fw img{width:100%;height:100%;object-fit:cover;display:block}
.tl-cap{font-size:6.2pt;color:var(--ink3);letter-spacing:.08em;margin-top:2.8mm;
 font-family:"PingFang SC",sans-serif}
.tl-b{font-size:8pt;line-height:2.05;color:var(--ink2);column-count:2;column-gap:9mm;
 text-align:justify;border-top:.9pt solid var(--tea);padding-top:6mm;margin-top:7mm}
.tl-b p{text-indent:2em;margin-bottom:3mm;break-inside:avoid}
.tl-b p:last-child{margin-bottom:0}
"""

CSS_TOC = """
.toc{padding:13mm 17mm 11mm;display:flex;flex-direction:column}
.toc .th{font-size:14pt;letter-spacing:.4em;color:var(--ink);border-bottom:1.1pt solid var(--tea);padding-bottom:4mm;margin-bottom:6mm}
.toc .cols{display:grid;grid-template-columns:1fr 1fr;column-gap:0;flex:1}
.toc .col{min-width:0}
.toc .col:first-child{border-right:.4pt solid #D8D1C3;padding-right:6mm}
.toc .col:last-child{padding-left:6mm}
.toc .grp{margin-bottom:6mm;break-inside:auto}
.toc .grp h3{font-size:9pt;color:var(--tea);letter-spacing:.2em;font-weight:600;margin:0 0 2.4mm;padding-bottom:1.4mm;border-bottom:.6pt solid var(--tea);break-after:avoid}
.toc .it{display:flex;align-items:baseline;font-size:9pt;color:var(--ink);line-height:1.9}
.toc .it .nm{flex:0 1 auto}
.toc .it .dots{flex:1;border-bottom:1pt dotted #C9C0AE;margin:0 2.5mm;transform:translateY(-0.8mm)}
.toc .it .pg{flex:0 0 auto;color:var(--ink3);font-size:7.8pt;letter-spacing:.06em}
.toc .ft{margin-top:6mm;display:flex;justify-content:space-between;font-size:6.5pt;color:var(--ink3);letter-spacing:.14em}
"""

CSS_COVER = """
.cover{position:relative;display:flex;align-items:center;justify-content:center}
.cover .cframe{position:absolute;left:13mm;top:13mm;right:13mm;bottom:13mm;border:1.1pt solid var(--tea)}
.cover .cframe2{position:absolute;left:16.5mm;top:16.5mm;right:16.5mm;bottom:16.5mm;border:.5pt solid #C8B899}
.cover .ctop{display:flex;align-items:center;gap:16mm}
.cover .ctitle{writing-mode:vertical-rl;font-family:"Kaiti SC","STKaiti","Songti SC",serif;font-size:30pt;color:#3A2E20;letter-spacing:.16em}
.cover .csub{writing-mode:vertical-rl;font-family:"Kaiti SC","STKaiti","Songti SC",serif;font-size:15pt;color:var(--tea);letter-spacing:.3em}
.cover .cdate{position:absolute;right:22mm;bottom:24mm;writing-mode:vertical-rl;font-family:"Kaiti SC","STKaiti","Songti SC",serif;font-size:10.5pt;color:var(--tea);letter-spacing:.2em}
"""


def page_tall(r, img, footer):
    """竖图大页：左列整幅展品照，右栏档案与注解，正文通栏落页脚。"""
    W = r.get("w", 106.0)
    H = fig_h(img, W)
    return (('<div class="sheet arcpg" style="grid-template-columns:%.2fmm minmax(0,1fr);'
             'column-gap:8mm;grid-template-rows:auto %.2fmm auto auto 1fr 7mm">\n%s\n'
             '<div class="tl-fw" style="grid-column:1;grid-row:2">'
             '<img src="%s"></div>\n'
             '<div class="tl-cap" style="grid-column:1;grid-row:3">%s</div>\n'
             '<div class="right arc" style="grid-column:2;grid-row:2/4">%s'
             '<div class="sp">%s</div>'
             '<div class="ntwrap">%s</div></div>\n'
             '<div class="tl-b" style="grid-column:1/-1;grid-row:4">%s</div>\n'
             '%s\n</div>')
            % (W, H, head(r, r.get("pending")), os.path.basename(img),
               r.get("caption", ""),
               extras_col(r["extras"], 60) if r.get("extras") else "",
               specs_html(r.get("specs", [])),
               notes_col(r.get("notes", [])),
               body_html(r), foot(r, 6, footer)))


def page_explain(r, footer):
    """科普页：文字为主，附图由本页画（算筹数字按纵式、横式规则排）。"""
    lede = "".join("<p>%s</p>" % x for x in r.get("lede", []))
    rows = ""
    if r.get("specimen"):
        line1 = "".join('<div class="xp-cell">%s<div class="xp-dg">%d</div></div>'
                        % (_rods(d, True), d) for d in range(1, 10))
        line2 = "".join('<div class="xp-cell">%s<div class="xp-dg">%d</div></div>'
                        % (_rods(d, False), d) for d in range(1, 10))
        rows = ('<div class="xp-row"><div class="xp-lab">纵式</div>%s</div>'
                '<div class="xp-row"><div class="xp-lab">横式</div>%s</div>'
                % (line1, line2))
    ex = ""
    exs = r.get("examples") or ([r["example"]] if r.get("example") else [])
    for e in exs:
        cells = "".join('<div class="xp-cell">%s<div class="xp-dg">%s</div></div>'
                        % (_rods(int(d), v), lab)
                        for d, lab, v in zip(e["digits"], e["labels"], e["vertical"]))
        ex += ('<div class="xp-ex"><div class="xp-lab" style="flex:0 0 22mm">%s</div>'
               '<div class="num">%s</div><div class="cap2">%s</div></div>'
               % (e.get("head", "示例"), cells, e.get("caption", "")))
    body = "".join("<p>%s</p>" % x for x in r.get("body", []))
    # 注记压在页脚之上：与正文之间留出整段空白，不贴着末段
    return (('<div class="sheet" style="grid-template-columns:1fr;'
             'grid-template-rows:auto auto auto auto auto 1fr auto 7mm">\n%s\n'
             '<div class="xp-h">%s</div>\n'
             '<div class="xp-fig">%s</div>\n'
             '<div style="grid-column:1/-1;grid-row:4">%s</div>\n'
             '<div class="xp-b">%s</div>\n'
             '<div></div>\n'
             '<div class="xp-note">%s</div>\n%s\n</div>')
            % (head(r, r.get("pending")), lede, rows, ex, body,
               r.get("note", ""), foot(r, 8, footer)))


def page_spread(r, img, footer):
    """跨页：左页只放一张小图与图注，右页承载标题与正文。两页同一版心。"""
    w = r.get("w", 108.0)
    p = img
    left = (('<div class="sheet" style="grid-template-columns:1fr;'
             'grid-template-rows:1fr auto 7mm">\n'
             '<div class="sp-l" style="grid-row:1">'
             '<div class="lwm" style="width:%gmm"><img src="%s"></div></div>\n'
             '<div class="sp-cap" style="grid-row:2">%s</div>\n%s\n</div>')
            % (w, os.path.basename(p), r.get("caption", ""),
               foot(r, 3, footer + "　上")))
    lede = "".join("<p>%s</p>" % x for x in r.get("lede", []))
    body = "".join("<p>%s</p>" % x for x in r.get("body", []))
    right = (('<div class="sheet" style="grid-template-columns:1fr;'
              'grid-template-rows:auto auto 1fr auto 7mm">\n%s\n'
              '<div class="sp-lede">%s</div>\n'
              '<div class="sp-b">%s</div>\n'
              '<div class="sp-note">%s</div>\n%s\n</div>')
             % (head(r, r.get("pending")), lede, body, r.get("note", ""),
                foot(r, 5, footer + "　下")))
    return left + right


# ---------- 延伸页：类型图鉴 ----------
CSS_PANEL = """
.ex-h{grid-column:1/-1;grid-row:2;font-size:8.6pt;line-height:2.05;color:var(--ink2);
 max-width:158mm;text-align:justify;padding:4mm 0 2mm}
.ex-h p{text-indent:2em}
.ex{grid-column:1/-1;grid-row:3;display:flex;gap:0;align-items:flex-start;padding-top:4mm;
 justify-content:flex-start}
.ex-i{flex:1;display:flex;flex-direction:column;padding:0 3.2mm;min-width:0}
.ex-i+.ex-i{border-left:.4pt solid var(--rule)}
.ex-i:first-child{padding-left:0}
.ex-i:last-child{padding-right:0}
.ex-fw{position:relative;height:74mm;background:transparent;overflow:hidden}
.ex-fw img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;
 object-position:center bottom;display:block;mix-blend-mode:multiply}
.ex-n{font-size:14pt;letter-spacing:.1em;margin-top:3.2mm;line-height:1.2}
.ex-n span{font-size:7pt;color:var(--tea);letter-spacing:.04em;margin-left:1.6mm;
 font-family:"PingFang SC",sans-serif}
.ex-d{font-size:7.3pt;line-height:1.95;color:var(--ink2);margin-top:1.8mm;text-align:justify}
.ex-tail{grid-column:1/-1;grid-row:4;font-size:7.6pt;line-height:2.0;color:var(--ink2);
 max-width:160mm;text-align:justify;margin-top:5mm;padding-top:3.8mm;
 border-top:.4pt solid var(--rule)}
.ex-tail p{text-indent:2em}
.ex-tail p:only-child{text-indent:0}
.ex-note{grid-column:1/-1;grid-row:5;font-size:6.2pt;color:var(--ink3);letter-spacing:.05em;
 border-top:.4pt solid var(--rule);padding-top:3.2mm;line-height:1.7;
 font-family:"PingFang SC",sans-serif}
"""

# ---------- 延伸页：数据表 ----------
CSS_TB = """
.tb-h{grid-column:1/-1;grid-row:2;font-size:8.4pt;line-height:2.2;color:var(--ink2);
 max-width:160mm;text-align:justify;padding:4mm 0 1mm}
.tb-h p{text-indent:2em;margin-bottom:3mm}
.tb-h p:last-child{margin-bottom:0}
.tb{grid-column:1/-1;grid-row:3;width:100%;border-collapse:collapse;
 font-family:"PingFang SC",sans-serif;align-self:start}
.tb th{font-size:6.4pt;color:var(--ink3);letter-spacing:.16em;font-weight:400;
 text-align:left;padding:0 0 2.4mm;border-bottom:.9pt solid var(--tea)}
.tb td{font-size:10pt;padding:4.3mm 0 4.5mm;border-bottom:.4pt solid var(--rule);
 color:var(--ink);vertical-align:middle;font-family:"Songti SC",serif}
.tb td.dy{font-size:7pt;color:var(--ink3);font-family:"PingFang SC",sans-serif;letter-spacing:.03em}
.tb td.tm,.tb td.dur{font-size:7.4pt;color:var(--ink2);font-family:"PingFang SC",sans-serif}
.tb td.dur{text-align:right}
.tb .cap{display:inline;color:var(--tea);font-size:6.4pt;letter-spacing:.06em;margin-left:1.4mm;
 font-family:"PingFang SC",sans-serif;white-space:nowrap}
.tb th:first-child,.tb td:first-child{width:32mm;white-space:nowrap}
.tb-note{grid-column:1/-1;grid-row:4;font-size:6.4pt;color:var(--ink3);line-height:1.75;
 border-top:.4pt solid var(--rule);padding-top:3.2mm;letter-spacing:.04em;
 font-family:"PingFang SC",sans-serif}
"""


def page_ext_panel(r, footer):
    """延伸页·类型图鉴：一页一类器物，若干竖条（线图＋器名＋释义）。"""
    lede = "".join("<p>%s</p>" % x for x in r.get("lede", []))
    tail = r.get("tail", "")
    if isinstance(tail, (list, tuple)):
        tail = "".join("<p>%s</p>" % x for x in tail)
    cells = []
    for it in r["items"]:
        cells.append(
            '<div class="ex-i">'
            '<div class="ex-fw"><img src="%s"></div>'
            '<div class="ex-n">%s<span>%s</span></div>'
            '<div class="ex-d">%s</div></div>'
            % (os.path.basename(it["_path"]), it["name"],
               it.get("py", ""), it.get("desc", "")))
    return (('<div class="sheet" style="grid-template-columns:1fr;'
             'grid-template-rows:auto auto auto auto auto 1fr 7mm">\n%s\n'
             '<div class="ex-h">%s</div>\n'
             '<div class="ex">%s</div>\n'
             '<div class="ex-tail">%s</div>\n'
             '<div class="ex-note">%s</div>\n<div></div>\n%s\n</div>')
            % (head(r, r.get("pending")), lede, "".join(cells),
               tail, r.get("note", ""), foot(r, 7, footer)))


def page_ext_table(r, footer):
    """延伸页·数据表：把展板上的表按书版重排。"""
    lede = "".join("<p>%s</p>" % x for x in r.get("lede", []))
    rows = []
    for t in r["rows"]:
        cap = ('<span class="cap">%s</span>' % t["cap"]) if t.get("cap") else ""
        rows.append('<tr><td>%s%s</td><td class="dy">%s</td>'
                    '<td class="tm">%s</td><td class="dur">%s</td></tr>'
                    % (t["a"], cap, t["b"], t["c"], t["d"]))
    heads = r.get("cols", ["朝代", "都城", "建立时间", "历时"])
    th = "".join('<th style="%s">%s</th>'
                 % ("text-align:right" if i == len(heads) - 1 else "", h)
                 for i, h in enumerate(heads))
    return (('<div class="sheet" style="grid-template-columns:1fr;'
             'grid-template-rows:auto auto auto auto 1fr 7mm">\n%s\n'
             '<div class="tb-h">%s</div>\n'
             '<table class="tb"><thead><tr>%s</tr></thead><tbody>%s</tbody></table>\n'
             '<div class="tb-note">%s</div>\n%s\n</div>')
            % (head(r, r.get("pending")), lede, th, "".join(rows),
               r.get("note", ""), foot(r, 6, footer)))


CSS_FIG = """
.fg{grid-column:1/-1;grid-row:3;display:flex;justify-content:center;padding:2mm 0 0}
.fg .lwm{background:#FBF8F1;border:.3pt solid rgba(138,106,75,.26);
 display:flex;align-items:center;justify-content:center}
.fg .lwm img{width:100%;height:100%;object-fit:contain}
.fg-cap{grid-column:1/-1;grid-row:4;font-size:6.2pt;color:var(--ink3);letter-spacing:.06em;
 margin-top:3.4mm;font-family:"PingFang SC",sans-serif}
.fg-note{grid-column:1/-1;grid-row:6;font-size:6.4pt;color:var(--ink3);line-height:1.75;
 margin-top:8mm;border-top:.4pt solid var(--rule);padding-top:4mm;letter-spacing:.04em;
 font-family:"PingFang SC",sans-serif}
.fg-b{grid-column:1/-1;grid-row:5;margin-top:9mm;padding-top:8mm;
 border-top:.9pt solid var(--tea);font-size:8.2pt;line-height:2.28;
 color:var(--ink2);column-count:2;column-gap:9mm;text-align:justify}
.fg-b p{text-indent:2em;margin-bottom:4.6mm;break-inside:avoid}
"""


def page_ext_figure(r, footer):
    """延伸页·单幅图：一张图（展板、地图、线图）＋导语＋图注。
    图宽按可用高度反算，避免竖图顶到页脚。"""
    lede = "".join("<p>%s</p>" % x for x in r.get("lede", []))
    p = r["_path"]
    max_h = r.get("max_h", 152.0)
    w = r.get("w")
    if not w:
        h_at_full = fig_h(p, COL_LAND)
        w = COL_LAND if h_at_full <= max_h else COL_LAND * max_h / h_at_full
    h = fig_h(p, w)
    return (('<div class="sheet" style="grid-template-columns:1fr;'
             'grid-template-rows:auto auto auto auto auto auto 1fr 7mm">\n%s\n'
             '<div class="tb-h">%s</div>\n'
             '<div class="fg"><div class="lwm" style="width:%.2fmm;height:%.2fmm">'
             '<img src="%s"></div></div>\n'
             '<div class="fg-cap">%s</div>\n'
             '<div class="fg-b">%s</div>\n'
             '<div class="fg-note">%s</div>\n%s\n</div>')
            % (head(r, r.get("pending")), lede, w, h,
               os.path.basename(p), r.get("caption", ""),
               "".join("<p>%s</p>" % x for x in r.get("body", [])),
               r.get("note", ""), foot(r, 8, footer)))

CSS_GUIDE = """
.gd-map{grid-column:1/-1;grid-row:2;padding-top:4mm;display:flex;
 align-items:center;justify-content:center;min-height:0}
.gd-map svg{display:block;width:100%;height:auto}
.gd-leg{grid-column:1/-1;grid-row:3;display:flex;flex-direction:column;gap:1.9mm;
 margin-top:6mm;padding-top:4mm;border-top:.4pt solid var(--rule);
 font-size:6.4pt;color:var(--ink3);letter-spacing:.05em;line-height:1.5;
 font-family:"PingFang SC",sans-serif}
.gd-lede{grid-column:1/-1;grid-row:2;font-size:8.6pt;line-height:2.05;color:var(--ink2);
 max-width:152mm;margin-bottom:8mm;text-align:justify}
.gd-lede p{text-indent:2em;margin-bottom:2.6mm}
.gd-tb{grid-column:1/-1;grid-row:3;width:100%;border-collapse:collapse;
 font-family:"PingFang SC",sans-serif}
.gd-tb th{font-size:6.4pt;color:var(--ink3);letter-spacing:.16em;font-weight:400;
 text-align:left;padding:0 0 2.6mm;border-bottom:.9pt solid var(--tea)}
.gd-tb td{font-size:9pt;padding:3.6mm 0 3.8mm;border-bottom:.4pt solid var(--rule);
 color:var(--ink);vertical-align:middle}
.gd-tb td.nm{font-family:"Songti SC",serif;font-size:10.5pt;letter-spacing:.03em}
.gd-tb td.yr,.gd-tb td.n,.gd-tb td.pg{font-size:7.4pt;color:var(--ink2);letter-spacing:.05em}
.gd-tb td.n,.gd-tb td.pg,.gd-tb th.n,.gd-tb th.pg{text-align:right;padding-right:3mm}
.gd-tb tr.tot td{border-bottom:none;border-top:.9pt solid var(--tea);
 font-size:7.4pt;color:var(--ink3);padding-top:3mm}
.gd-tb .hall{color:var(--tea);letter-spacing:.12em;font-size:6.6pt}
.gd-note{grid-column:1/-1;grid-row:4;margin-top:8mm;font-size:7.4pt;line-height:1.95;
 color:var(--ink2);max-width:152mm;text-align:justify}
.gd-note b{color:var(--tea);font-weight:600}
"""


def _map_svg(halls):
    """示意平面：只表相对位置与四厅归属。不画比例尺、不画未经核实的动线。"""
    def box(h):
        x, y, w, hh = h["x"], h["y"], h["w"], h["h"]
        on = h.get("cls") == "on"
        sub = h.get("sub", "")
        t = (f'<text x="{x + w / 2:.1f}" y="{y + hh / 2 - (1.8 if sub else 0):.1f}" '
             f'text-anchor="middle" font-size="4.6" '
             f'fill="{"#1F1C18" if on else "#9A9184"}" '
             f'font-family="PingFang SC">{h["label"]}</text>')
        if sub:
            t += (f'<text x="{x + w / 2:.1f}" y="{y + hh / 2 + 3.6:.1f}" text-anchor="middle" '
                  f'font-size="3.4" fill="#857D70" font-family="PingFang SC">{sub}</text>')
        fill = "rgba(138,106,75,.10)" if on else "none"
        stroke = "#8A6A4B" if on else "#D8D1C3"
        return (f'<rect x="{x}" y="{y}" width="{w}" height="{hh}" fill="{fill}" '
                f'stroke="{stroke}" stroke-width="{0.7 if on else 0.4}"/>' + t)

    def num(h):
        x, y = h["x"] + 6.4, h["y"] + 6.4
        return (f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.4" fill="#8A6A4B"/>'
                f'<text x="{x:.1f}" y="{y + 1.5:.1f}" text-anchor="middle" font-size="4.1" '
                f'fill="#F5F2EB" font-family="PingFang SC">{h["no"]}</text>')

    s = ['<svg viewBox="0 0 174 204" xmlns="http://www.w3.org/2000/svg">']
    s.append('<rect x="50" y="42" width="74" height="108" fill="none" stroke="#D8D1C3" '
             'stroke-width=".4"/>')
    s.append('<text x="87" y="98" text-anchor="middle" font-size="4.4" fill="#857D70" '
             'font-family="PingFang SC">序厅</text>')
    for h in halls:
        s.append(box(h))
        if h.get("no"):
            s.append(num(h))
    s.append('<path d="M83 172 L87 165 L91 172 Z" fill="#8A6A4B"/>')
    s.append('<text x="87" y="180" text-anchor="middle" font-size="3.8" fill="#857D70" '
             'font-family="PingFang SC">入口</text>')
    s.append('</svg>')
    return ''.join(s)


def page_guide_map(r, footer):
    svg = _map_svg(r["halls"])
    leg = ''.join(f'<span>{x}</span>' for x in r.get("legend", []))
    return f'''<div class="sheet" style="grid-template-columns:1fr;
     grid-template-rows:auto 1fr auto 7mm">
<div class="hd"><h1>{r["name"]}</h1>{sub_html(r.get("sub", ""))}</div>
<div class="gd-map">{svg}</div>
<div class="gd-leg">{leg}</div>
{foot(r, 4, footer)}
</div>'''


def page_guide_table(r, footer):
    rows, tot = [], 0
    for t in r["rows"]:
        tot += t["n"]
        rows.append(
            f'<tr><td><span class="hall">{t["hall"]}</span></td>'
            f'<td class="nm">{t["unit"]}</td>'
            f'<td class="yr">{t["era"]}</td>'
            f'<td class="n">{t["n"]}</td>'
            f'<td class="pg">{t.get("pg", "—")}</td></tr>')
    lede = ''.join(f'<p>{x}</p>' for x in r.get("lede", []))
    return f'''<div class="sheet" style="grid-template-columns:1fr;
     grid-template-rows:auto auto 1fr auto 7mm">
<div class="hd"><h1>{r["name"]}</h1>{sub_html(r.get("sub", ""))}</div>
<div class="gd-lede">{lede}</div>
<table class="gd-tb">
<thead><tr><th style="width:26mm">展厅</th><th>单元</th><th style="width:34mm">年代</th>
<th class="n" style="width:16mm">收录</th><th class="pg" style="width:18mm">页码</th></tr></thead>
<tbody>{''.join(rows)}
<tr class="tot"><td></td><td>{r.get("total_label", "合计")}</td><td></td>
<td class="n">{tot}</td><td class="pg"></td></tr></tbody></table>
<div class="gd-note">{r.get("note", "")}</div>
{foot(r, 5, footer)}
</div>'''


CSS_ROUTE = """
.rt{grid-column:1/-1;grid-row:2;position:relative;display:flex;
 flex-direction:column;min-height:0}
.rt::before{content:"";position:absolute;left:8.4mm;top:9mm;bottom:9mm;width:.5pt;
 background:var(--rule)}
.rt-row{display:flex;align-items:center;gap:7mm;padding:7mm 0;position:relative;flex:1}
.rt-row+.rt-row{border-top:.4pt solid rgba(138,106,75,.16)}
.rt-no{flex:0 0 auto;width:20mm;display:flex;justify-content:center;padding-top:.4mm}
.rt-no i{width:8.4mm;height:8.4mm;border-radius:50%;background:var(--paper);
 border:.6pt solid var(--tea);color:var(--tea);display:flex;align-items:center;
 justify-content:center;font-style:normal;font-size:4.1mm;font-weight:600;
 font-family:"PingFang SC",sans-serif;position:relative;z-index:1}
.rt-main{flex:1}
.rt-h{font-family:"Songti SC",serif;font-size:13pt;font-weight:600;letter-spacing:.04em}
.rt-h span{font-family:"PingFang SC",sans-serif;font-size:6.6pt;font-weight:400;
 color:var(--ink3);letter-spacing:.16em;margin-left:3.4mm}
.rt-units{font-family:"PingFang SC",sans-serif;font-size:8pt;color:var(--tea);
 letter-spacing:.14em;margin-top:2.6mm}
.rt-desc{font-size:7.8pt;line-height:1.9;color:var(--ink2);margin-top:2.4mm;
 max-width:104mm;text-align:justify}
.rt-rep{font-family:"PingFang SC",sans-serif;font-size:6.6pt;color:var(--ink3);
 letter-spacing:.08em;margin-top:2.8mm}
.rt-rep b{color:var(--tea);font-weight:400;letter-spacing:.16em;margin-right:2.4mm}
.rt-meta{flex:0 0 22mm;text-align:right;padding-top:1.6mm}
.rt-meta b{font-family:"Songti SC",serif;font-size:15pt;font-weight:600;letter-spacing:.02em}
.rt-meta em{font-style:normal;font-family:"PingFang SC",sans-serif;font-size:6.2pt;
 color:var(--ink3);letter-spacing:.1em;margin-left:1mm}
.rt-meta .pg{display:block;font-family:"PingFang SC",sans-serif;font-size:6.2pt;
 color:var(--ink3);letter-spacing:.12em;margin-top:2.2mm}
"""


def page_guide_route(r, footer):
    rows = []
    for h in r["halls"]:
        rows.append(
            f'<div class="rt-row"><div class="rt-no"><i>{h["no"]}</i></div>'
            f'<div class="rt-main"><div class="rt-h">{h["label"]}<span>{h.get("en", "")}</span></div>'
            f'<div class="rt-units">{h["units"]}</div>'
            f'<div class="rt-desc">{h["desc"]}</div>'
            f'<div class="rt-rep"><b>代表</b>{h.get("rep", "")}</div></div>'
            f'<div class="rt-meta"><b>{h["n"]}</b><em>组图版</em>'
            f'<span class="pg">页码 {h.get("pg", "—")}</span></div></div>')
    return f'''<div class="sheet" style="grid-template-columns:1fr;
     grid-template-rows:auto 1fr auto 7mm">
<div class="hd"><h1>{r["name"]}</h1>{sub_html(r.get("sub", ""))}</div>
<div class="rt">{''.join(rows)}</div>
<div class="gd-leg">{''.join(f'<span>{x}</span>' for x in r.get("legend", []))}</div>
{foot(r, 4, footer)}
</div>'''


def html_doc(body):
    return (f'<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
            f'<style>{CSS}{CSS_DETAIL}{CSS_GUIDE}{CSS_ROUTE}{CSS_EXTRA}{CSS_SET}{CSS_PANEL}{CSS_PGRID}{CSS_TB}{CSS_FIG}{CSS_PAIR}{CSS_TB2}{CSS_EXP}{CSS_SPREAD}{CSS_TREE}{CSS_TALL}{CSS_TOC}{CSS_COVER}</style></head><body>{body}{METRICS_JS}</body></html>')


def chrome(args, timeout=180):
    if not os.path.exists(CHROME):
        raise SystemExit(f"未找到 Chrome：{CHROME}")
    return subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
                           "--disable-dev-shm-usage",
                           "--no-first-run", "--no-default-browser-check"] + args,
                          capture_output=True, text=True, timeout=timeout)


def to_pdf(html_path, pdf_path):
    """独立 user-data-dir 是必须的，否则沙箱清理规则会拦掉渲染进程。
    先写临时文件再搬，直接写目标路径会静默失败。"""
    tmpdir = tempfile.mkdtemp(prefix="figbk-")
    tmp_pdf = os.path.join(tmpdir, "out.pdf")
    try:
        r = chrome([f"--user-data-dir={os.path.join(tmpdir, 'prof')}",
                    "--no-pdf-header-footer",
                    f"--print-to-pdf={tmp_pdf}",
                    "file://" + os.path.abspath(html_path)])
        if not os.path.exists(tmp_pdf):
            raise SystemExit("PDF 未生成：\n" + (r.stderr or "")[-800:])
        os.makedirs(os.path.dirname(pdf_path) or ".", exist_ok=True)
        shutil.copy(tmp_pdf, pdf_path)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def to_png(html_path, png_path, pages=1):
    """整册截图后按页切。窗口高度按页数给，否则只有第一页进画面。"""
    tmpdir = tempfile.mkdtemp(prefix="figbk-")
    tall = 1123 * max(1, pages)
    try:
        r = chrome([f"--user-data-dir={os.path.join(tmpdir, 'prof')}",
                    "--hide-scrollbars",
                    "--window-size=794,%d" % tall,
                    "--force-device-scale-factor=2",
                    f"--screenshot={png_path}",
                    "file://" + os.path.abspath(html_path)])
        if not os.path.exists(png_path):
            raise SystemExit("PNG 未生成：\n" + (r.stderr or "")[-800:])
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    if pages > 1:
        from PIL import Image as _I
        im = _I.open(png_path)
        w, h = im.size
        step = h // pages
        base = os.path.splitext(png_path)[0]
        for i in range(pages):
            im.crop((0, i * step, w, (i + 1) * step)).save("%s-%d.png" % (base, i + 1))
        im.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plates")
    ap.add_argument("--out-dir")
    ap.add_argument("--only", help="只渲染指定 id，逗号分隔")
    ap.add_argument("--toc-only", action="store_true", help="只渲染目录页")
    ap.add_argument("--pdf", action="store_true")
    ap.add_argument("--png", action="store_true")
    ap.add_argument("--audit", action="store_true", help="出页后自动跑容量体检")
    a = ap.parse_args()

    src = os.path.abspath(a.plates)
    root = os.path.dirname(src)
    out = os.path.abspath(a.out_dir or os.path.join(root, "_out"))
    os.makedirs(out, exist_ok=True)

    data = json.load(open(src, encoding="utf-8"))
    meta = data.get("meta", {})
    footer = meta.get("footer", meta.get("title", ""))
    plates = data["plates"]
    if a.only:
        keep = {s.strip() for s in a.only.split(",")}
        plates = [p for p in plates if str(p.get("id")) in keep]
    if a.toc_only:
        plates = []

    pages = []
    for p in plates:
        pid = str(p.get("id", "x"))

        # 导览页与数据表页：不取图，直接出版面
        tp = p.get("type")
        if tp in ("guide_map", "guide_table", "guide_route"):
            fn = {"guide_map": page_guide_map, "guide_table": page_guide_table,
                  "guide_route": page_guide_route}[tp]
            pages.append(fn(p, footer))
            continue

        def resolve(v):
            return v if os.path.isabs(v) else os.path.join(root, v)

        def link(path):
            """HTML 用相对路径取图，故把图链进输出目录（原图只读，不动）。"""
            if os.path.dirname(os.path.abspath(path)) == os.path.abspath(out):
                return
            d = os.path.join(out, os.path.basename(path))
            if not os.path.exists(d):
                os.symlink(os.path.abspath(path), d)

        if tp == "ext_figure":
            s0 = resolve(p["img"])
            if not os.path.exists(s0):
                raise SystemExit(f"图片不存在：{s0}（id={pid}）")
            p["_path"] = normalize(s0, out, pid, p.get("crop"))
            link(p["_path"])
            pages.append(page_ext_figure(p, footer))
            continue

        if tp == "ext_table":
            pages.append(page_ext_table(p, footer))
            continue

        if tp == "table":
            pages.append(page_table(p, footer))
            continue

        if tp == "explain":
            pages.append(page_explain(p, footer))
            continue

        if tp == "tree":
            pages.append(page_tree(p, footer))
            continue

        if tp == "pgroup":
            items = []
            for k, it in enumerate(p["items"]):
                it = dict(it)
                paths = []
                for j, v in enumerate(it["imgs"]):
                    s0 = resolve(v)
                    if not os.path.exists(s0):
                        raise SystemExit(f"图片不存在：{s0}（id={pid} 第{k+1}件第{j+1}图）")
                    pp = normalize(s0, out, "%s%d%d" % (pid, k, j), None)
                    link(pp)
                    paths.append(pp)
                it["_paths"] = paths
                items.append(it)
            p["items"] = items
            pages.append(page_pgroup(p, footer))
            continue

        if tp == "tall":
            s0 = resolve(p["img"])
            if not os.path.exists(s0):
                raise SystemExit(f"图片不存在：{s0}（id={pid}）")
            p["_path"] = normalize(s0, out, pid, p.get("crop"))
            link(p["_path"])
            pages.append(page_tall(p, p["_path"], footer))
            continue

        # 组页与延伸页：items 里每件各自取图（裁切坐标相对各自原图）
        if tp in ("set", "ext_panel", "pair"):
            items = []
            for k, it in enumerate(p["items"]):
                s0 = resolve(it["img"])
                if not os.path.exists(s0):
                    raise SystemExit(f"图片不存在：{s0}（id={pid} 第{k+1}件）")
                it = dict(it)
                it["_path"] = normalize(s0, out, f"{pid}{k}", it.get("crop"))
                link(it["_path"])
                items.append(it)
            p["items"] = items
            fn = {"set": page_set, "ext_panel": page_ext_panel, "pair": page_pair}[tp]
            pages.append(fn(p, footer))
            continue

        img = resolve(p["img"])
        if not os.path.exists(img):
            raise SystemExit(f"图片不存在：{img}（记录 id={p.get('id')}）")
        img = normalize(img, out, pid, p.get("crop"))
        link(img)

        if p.get("detail"):
            d = dict(p["detail"])
            # 细节图只接受独立拍摄的特写照片，禁止从主图裁。
            # 广角原图放大到 48mm 时，錾刻纹样已经糊了，落点也难核准，
            # 曾据此裁出「说明写禽鸟、画面实为忍冬花」的错图。
            # 宁可这页没有细节图，也不要出一张错图。
            if d.get("crop"):
                raise SystemExit(
                    f"detail 不接受 crop（id={pid}）：细节图必须是另拍的特写照片。"
                    f"主图是广角，放大到 48mm 纹样已糊且位置难核，裁出来常是错内容。"
                    f"没有特写照片就不写 detail。")
            src = resolve(d["img"])
            if not os.path.exists(src):
                raise SystemExit(f"细节图不存在：{src}（记录 id={pid}）")
            if os.path.abspath(src) == os.path.abspath(resolve(p["img"])):
                raise SystemExit(
                    f"detail.img 与主图是同一张（id={pid}）：细节图必须是另一张照片。")
            d["_path"] = normalize(src, out, pid + "d", None)
            link(d["_path"])
            p["detail"] = d

        if p.get("extras"):
            ex = []
            for k, d in enumerate(p["extras"]):
                d = dict(d)
                s0 = resolve(d["img"])
                if not os.path.exists(s0):
                    raise SystemExit(f"附属图不存在：{s0}（id={pid}）")
                if os.path.abspath(s0) == os.path.abspath(resolve(p["img"])):
                    raise SystemExit(
                        f"附属图与主图是同一张（id={pid}）：附属图必须是另一张照片。")
                d["_path"] = normalize(s0, out, f"{pid}e{k}", d.get("crop"))
                d.setdefault("kind", "细节")
                link(d["_path"])
                ex.append(d)
            p["extras"] = ex

        if tp == "spread":
            pages.append(page_spread(p, img, footer))
            continue

        layout = p.get("layout", "portrait")
        table = {(False, "portrait"): page_portrait,
                 (True, "portrait"): page_portrait_detail,
                 (False, "landscape"): page_landscape,
                 (True, "landscape"): page_landscape_detail}
        fn = table.get((bool(p.get("detail")), layout))
        if p.get("extras"):
            fn = page_portrait if layout == "portrait" else page_landscape
        if not fn:
            raise SystemExit(f"未知 layout：{layout}（id={p.get('id')}）")
        pages.append(fn(p, img, footer))

    stem = meta.get("stem", "figbook")
    one = os.path.join(out, stem + ".html")
    cover = page_cover(footer) if not a.only else ""
    toc = page_toc(data["plates"], footer) if (a.toc_only or not a.only) else ""
    body = cover + toc + "".join(pages)
    open(one, "w", encoding="utf-8").write(html_doc(body))
    n_sheet = body.count('class="sheet')
    print("HTML", one, f"({n_sheet} 页)", flush=True)

    if a.pdf or a.png:
        if a.pdf:
            pdf = os.path.join(out, stem + ".pdf")
            to_pdf(one, pdf)
            print("PDF ", pdf, flush=True)
        if a.png:
            png = os.path.join(out, "preview.png")
            to_png(one, png, n_sheet)
            print("PNG ", png, flush=True)

    if a.audit:
        import subprocess as sp
        import sys
        rc = sp.call([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                   "audit.py"), one])
        if rc:
            sys.exit(rc)


if __name__ == "__main__":
    main()
