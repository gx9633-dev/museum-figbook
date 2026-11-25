#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从「裁决数据」+「定稿样张」生成全册 plates.json（数据驱动，不改 render.py）。

这是「一批新图到成册」的编排层：把逐张裁决（去留、定名、换主图）翻译成
render.py 能读的页记录，并按展厅·单元分章、并入已定稿样张、去重、连续编页。

用法：
  python3 build_book.py --adjudication 裁决数据.json --sample samples3.json \
      --spec 全册_spec.json --images-root <原图目录> --out 观展图记_全册.json

  --dry-name  只打印定名提取结果，供人工复核，不写文件。

输入约定见 SKILL.md「一批新图到成册」。裁决数据.json 由 tencent-docs 在线表
导出脚本产生；sample 为已定稿页（原样并入，仅重编 folio）。
"""
import argparse
import json
import os
import re
import sys

# 版式稿预览用的派生缩略图：原图不动（硬约束），只在 _derived/book 下另存
THUMB_DIR = "_derived/book"
_THUMB_CACHE = {}


def make_thumb(src, images_root, long_edge):
    """按长边重采样并归正 EXIF，返回相对 plates.json 目录的路径。"""
    from PIL import Image, ImageOps
    key = (src, long_edge)
    if key in _THUMB_CACHE:
        return _THUMB_CACHE[key]
    base = os.path.splitext(os.path.basename(src))[0]
    rel = os.path.join(THUMB_DIR, "%s_%d.jpg" % (base, long_edge))
    dst = os.path.join(images_root, rel)
    if not os.path.exists(dst):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with Image.open(os.path.join(images_root, src)) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            w, h = im.size
            s = long_edge / float(max(w, h))
            if s < 1:
                im = im.resize((round(w * s), round(h * s)), Image.LANCZOS)
            im.save(dst, quality=86, optimize=True, subsampling=2)
    _THUMB_CACHE[key] = rel
    return rel

# 制作指令关键词：这些行不是器物定名，不能当作标题
CRAFT = ("裁剪", "留白", "去掉下方", "放大", "拆出", "拆出来", "分别为页",
         "分别裁剪", "作为主图", "主图", "细节图", "同页", "跨页", "排版",
         "搞混", "不要", "留空", "舍弃不使用", "介绍", "简介在", "出图信息",
         "参考", "可采用", "可选", "不用裁剪", "没有", "不是同一件", "不重要")
# 定名行：冒号前含这些词，冒号后即定名
NAMING_HINT = ("定名", "名称", "为", "写", "称", "左图", "右图", "前中", "左后", "右后")
# 纯裁决词/待核说明：不是器物定名，绝不能当标题（曾把「留用」提成页名）
JUNK_NAME = ("留用", "去掉", "舍弃", "舍弃不使用", "去掉下方", "展签未录入",
             "名称不确定", "定名不详", "定名待核", "名称待核", "留空", "待核")


def clean_name(s):
    s = s.strip()
    # 先去尾随的说明性从句，再清尾部标点（顺序不可反，否则留下孤零零的逗号）
    s = re.sub(r"(出图|简介|介绍|并且|可追加|注明|稍加|四周|仅保留|去掉下方).*$", "", s)
    # 数字开头的括号是批注噪声（如「7839的42号名字」）；注音括号（guǐ）保留
    s = re.sub(r"（\d[^）]*）", "", s)
    s = re.sub(r"\([^)]*\d[^)]*\)", "", s)
    s = re.sub(r"[，。；、,:\s]+$", "", s)
    return s.strip()


def extract_names(verdict):
    """从裁决逐行抽出所有器物定名；返回 (定名列表, 是否含拆分指令)。

    裁决里定名有三种写法：
      「定名在 7888，为：四足调色器」  冒号式
      「定名在 7908，为 鎏金铜虎镇」   无冒号式
      「彩绘跪射俑」                   补充条目：整段裁决即定名
    """
    names, split = [], False
    for line in verdict.splitlines():
        ln = line.strip()
        if not ln:
            continue
        if any(k in ln for k in ("拆出", "拆出来", "分别为页", "分别裁剪")):
            split = True
        cand = None
        m = re.search(r"[：:]\s*(.+)$", ln)
        if m and any(h in ln[:m.start()] for h in NAMING_HINT):
            cand = m.group(1)
        else:
            m2 = re.search(r"定名[^，,]{0,12}[，,]?\s*(?:为|是)\s*(.+)$", ln)
            if m2:
                cand = m2.group(1)
        if not cand:
            continue
        nm = clean_name(cand)
        if not nm or len(nm) > 24 or nm in JUNK_NAME:
            continue
        # 「定名没问题」「留用，定名没问题」是对现有暂定名的确认，不是新定名
        if any(j in nm for j in ("名称不确定", "定名不详", "展签未录入", "没问题", "留用")):
            continue
        if any(c in nm for c in ("裁剪", "留白", "主图", "细节", "放大", "拆", "页")) and "纹" not in nm:
            continue
        if nm not in names:
            names.append(nm)
    # 补充条目常见：裁决整段就是一个短定名，无「定名…为」句式
    if not names and verdict.strip():
        first = clean_name(verdict.splitlines()[0])
        if (first and len(first) <= 16 and first not in JUNK_NAME
                and not any(c in first for c in CRAFT)
                and not any(j in first for j in ("名称不确定", "定名不详", "展签未录入",
                                                 "没问题", "留用"))):
            names.append(first)
    return names, split


def main_photo(verdict, rec_main):
    """裁决里指定了换主图则采用之；返回 (IMG文件名, 是否换过)。"""
    pats = [
        r"(?:主图(?:展示)?(?:采用|使用|取|用))\s*(\d{4})",
        r"(?:采用|使用)\s*(\d{4})\s*的图",
        r"(?:将|把)\s*(\d{4})\s*作为主图",
        r"(\d{4})\s*作为主图",
        r"主图取两张[：:]\s*(\d{4})",
        r"主图(?:适当裁剪|不裁剪)",
    ]
    for ln in verdict.splitlines():
        for p in pats:
            m = re.search(p, ln)
            if m and m.lastindex:
                return "IMG_%s.JPG" % m.group(1), True
    return rec_main, False


def rec_key(r):
    """规则表的键：组号；补充条目录为「补+主图四位号」。"""
    if r["类型"] == "组":
        return r["组号"]
    m = re.search(r"(\d{4})", r["主图"])
    return "补" + m.group(1) if m else "补" + r["主图"].strip()


def norm_chapter(s):
    return (s or "").replace(" ", "").replace("　", "")


def img_of(rec):
    m = rec.get("主图", "")
    hit = re.search(r"(?:IMG_)?(\d{4})", m)
    return "IMG_%s.JPG" % hit.group(1) if hit else None


def ar_of(path, images_root):
    """归正后的宽/高；用于判定竖版还是横版，避免撑破页面。"""
    from PIL import Image
    with Image.open(os.path.join(images_root, path)) as im:
        o = im.getexif().get(274, 1)
        w, h = im.size
        if o in (6, 8):
            w, h = h, w
    return w / h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adjudication", required=True)
    ap.add_argument("--sample", required=True)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--images-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--rules", default="",
                    help="成册规则 JSON：crop_map（组号→精裁图）与 overrides（合并／拆分／主图＋细节）")
    ap.add_argument("--dry-name", action="store_true")
    ap.add_argument("--pins", default="",
                    help="图上标注表 JSON（id → {pins, notes}），按 id 覆盖，含样张页")
    ap.add_argument("--text", default="",
                    help="页面文字表 JSON（id → {specs, caption, body}），按 id 覆盖")
    ap.add_argument("--thumb-long-edge", type=int, default=1600,
                    help="版式稿页缩略图长边像素（0=不缩，直接引用原图）。默认 1600，约 230dpi@174mm，PDF 体积可控")
    a = ap.parse_args()

    adj = json.load(open(a.adjudication, encoding="utf-8"))
    sample = json.load(open(a.sample, encoding="utf-8"))
    spec = json.load(open(a.spec, encoding="utf-8"))
    recs = adj["归并记录"]

    chapters = spec["chapters"]
    chapter_of = {}
    for r in recs:
        if r["类型"] == "组" and r["展厅·单元"]:
            chapter_of.setdefault(r["组号"], norm_chapter(r["展厅·单元"]))
    # 补充条目继承上一组的章节（它们是插在组之间的独立器物）
    last_ch = None
    for r in recs:
        ch = norm_chapter(r["展厅·单元"]) or last_ch
        if r["类型"] == "组" and ch:
            last_ch = ch
        r["_chapter"] = ch

    cover = spec.get("sample_cover", {})       # {样张id: 被替换的组号}
    drop_verdicts = set(spec.get("drop_verdicts", ["去掉"]))
    pend_verdicts = set(spec.get("pending_verdicts", ["留空待定"]))
    covered_groups = set(cover.values())

    print("==== 定名提取复核 ====")
    for r in recs:
        names, split = extract_names(r["裁决"])
        r["_names"] = names
        r["_split"] = split
        nm = " · ".join(names) if names else r["暂定名"]
        flag = "定名" if names else "暂用"
        print(f"  {r['组号'] or '补'+r['主图']:8} [{flag}] {nm[:34]:36} "
              f"{'拆分页' if split else '':6} {r['归类']}")

    if a.dry_name:
        return

    # 样张页：原样并入，id 保留，chapter 归一，folio 待全册重编
    sample_pages = []
    for p in sample["plates"]:
        q = dict(p)
        q["_chapter"] = norm_chapter(p.get("chapter", ""))
        q["_origin"] = "定稿样张"
        sample_pages.append(q)
    covered_ids = set(cover.keys())

    # 成册规则：精裁图替换、合并页、拆分页、主图＋细节同页
    rules = {}
    if a.rules:
        if not os.path.exists(a.rules):
            sys.exit("规则文件不存在：%s" % a.rules)
        rules = json.load(open(a.rules, encoding="utf-8"))
    crop_map = rules.get("crop_map", {})
    overrides = rules.get("overrides", {})
    # 章节归位：规则里的 chapters（组号→展厅·单元）优先于归并表的「展厅·单元」列。
    # 归并表该列由拍摄时段粗分，边界常错一位；展线本身以章序＋章内次序保证。
    chapter_map = rules.get("chapters", {})
    merged_into = set()
    for _k, _ov in overrides.items():
        for _g in _ov.get("merge_with", []):
            merged_into.add(_g)

    def thumb(p):
        return make_thumb(p, a.images_root, a.thumb_long_edge) if a.thumb_long_edge else p

    def build_page(r, ov, key):
        """一页一记录；ov 可覆盖图源、标题、副题、版式与附属图。"""
        # 图源优先级：规则指定 ＞ 精裁图 ＞ 裁决换主图 ＞ 原主图
        img = ov.get("img") or crop_map.get(key)
        if not img:
            img, _ = main_photo(r["裁决"], img_of(r))
        if not img or not os.path.exists(os.path.join(a.images_root, img)):
            print("  [警告] 图片缺失，跳过：", key, img, file=sys.stderr)
            return None
        ar = ar_of(img, a.images_root)
        if ov.get("layout"):
            layout = ov["layout"]
        elif ov.get("landscape"):
            layout = "landscape"
        elif ov.get("extra"):
            # 主图＋细节/另一角度同页：横版会把附属图挤进注解栏成一条灰带，
            # 与 render.py 的版面算术一致，改竖版（主图 118mm、右栏叠附属图）。
            layout = "portrait"
        else:
            layout = "portrait" if ar < 0.92 else "landscape"
        names = r["_names"]
        nm = ov["name"] if "name" in ov else (" · ".join(names) if names else r["暂定名"])
        # 「定名没问题」视为已核定名：沿用暂定名且不再标待核
        confirmed = "定名没问题" in r["裁决"] or bool(ov.get("name", "").strip())
        pending = (ov["pending"] if "pending" in ov
                   else ((r["归类"] in pend_verdicts) or (not names and not confirmed)))
        extras = []
        if ov.get("extra"):
            e = ov["extra"]
            if os.path.exists(os.path.join(a.images_root, e["img"])):
                extras.append({"img": thumb(e["img"]),
                               "kind": e.get("kind", "细节"),
                               "caption": e.get("caption", "")})
            else:
                print("  [警告] 附属图缺失：", key, e["img"], file=sys.stderr)
        pid = ov.get("id") or (("G%s" % r["组号"]) if r["类型"] == "组" else ("X%s" % key[1:]))
        return {
            "id": pid,
            "layout": layout,
            "img": thumb(img),
            "name": nm,
            "sub": ov.get("sub", ""),
            "chapter": ov.get("chapter") or chapter_map.get(key) or r["_chapter"],
            "caption": ov.get("caption", ""),
            # 图上圆托引线标注：[标签, 圆托x, 圆托y, 特征x, 特征y]，均为整图相对坐标。
            # 有 pins 时注解首列用 ①②③，两者一一对应（见 render.overlay）。
            "pins": ov.get("pins", []),
            "specs": ov.get("specs", []),
            "notes": ov.get("notes", []),
            "body": ov.get("body", []),
            "extras": extras,
            "pending": pending,
            "_origin": "裁决版式稿",
            "_verdict": r["裁决"][:80],
        }

    # 器物页
    group_pages = []
    for r in recs:
        if r["归类"] in drop_verdicts:
            continue
        if r["类型"] == "组" and r["组号"] in covered_groups:
            continue                      # 该组已由定稿样张承载
        if r["类型"] == "组" and r["组号"] in merged_into:
            continue                      # 已并入合并页
        key = rec_key(r)
        ov = overrides.get(key, {})
        if ov.get("drop"):
            continue                      # 该页不收入成册
        if ov.get("split"):
            for sp in ov["split"]:
                g = build_page(r, sp, key)
                if g:
                    group_pages.append(g)
        else:
            g = build_page(r, ov, key)
            if g:
                group_pages.append(g)

    # 按章分桶，章内先定稿样张、后版式稿；章序由 spec 给定
    buckets = {c: {"sample": [], "group": []} for c in chapters}
    for q in sample_pages:
        c = q["_chapter"]
        if c not in buckets:
            buckets[c] = {"sample": [], "group": []}
            chapters.append(c)
        buckets[c]["sample"].append(q)
    for g in group_pages:
        c = g["chapter"]
        if c not in buckets:
            buckets[c] = {"sample": [], "group": []}
            chapters.append(c)
        buckets[c]["group"].append(g)

    pins_map = json.load(open(a.pins, encoding="utf-8")) if a.pins else {}
    text_map = json.load(open(a.text, encoding="utf-8")) if a.text else {}

    plates = []
    for c in chapters:
        for q in buckets[c]["sample"] + buckets[c]["group"]:
            q = dict(q)
            q["chapter"] = spec["chapter_display"].get(c, c)
            q["folio"] = "P%03d" % (len(plates) + 1)
            if a.pins and q["id"] in pins_map:
                q["pins"] = pins_map[q["id"]]["pins"]
                q["notes"] = pins_map[q["id"]]["notes"]
            if a.text and q["id"] in text_map:
                for k in ("specs", "caption", "body"):
                    q[k] = text_map[q["id"]].get(k, q.get(k, "" if k == "caption" else []))
            for k in ("_chapter", "_origin", "_verdict"):
                q.pop(k, None)
            plates.append(q)

    out = {
        "meta": {
            "title": spec.get("title", "观展图记"),
            "footer": spec.get("footer", "观展图记"),
            "stem": spec.get("stem", "观展图记_全册"),
        },
        "plates": plates,
    }
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    from collections import Counter
    print("\n==== 编排结果 ====")
    print("总页数", len(plates))
    print("样张页", sum(1 for q in sample_pages if q["id"] in covered_ids),
          "（另 %d 页非覆盖样张同章并入）" % (len(sample_pages) - len(covered_ids)))
    print("版式稿页", len(group_pages))
    print("页型", dict(Counter(q.get("type") or q.get("layout") for q in plates)))
    print("分章", {c: len(buckets[c]["sample"]) + len(buckets[c]["group"]) for c in chapters})
    print("输出", a.out)


if __name__ == "__main__":
    main()
