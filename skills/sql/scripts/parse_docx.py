"""
解析 CDC 管理表结构说明.docx，生成：
  设计相关/表目录.md      — 表名索引
  设计相关/表结构/*.md    — 每表完整字段清单

用法: py .claude/skills/sql/scripts/parse_docx.py <docx路径> [输出目录]
默认输出目录: docx 所在目录

依赖: pip install python-docx lxml
"""

import sys
import os
import re
from pathlib import Path
from zipfile import ZipFile
from lxml import etree

# ── OOXML 命名空间 ────────────────────────────────────────────────
NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _text_of_element(elem):
    """递归提取元素中所有 <w:t> 文本, 按文档顺序拼接。"""
    parts = []
    for t in elem.iter("{%s}t" % NS):
        if t.text:
            parts.append(t.text)
    return "".join(parts)


def _cell_texts(row):
    """提取表格行中每个单元格的文本列表。"""
    cells = row.findall("{%s}tc" % NS)
    return [_text_of_element(c).strip() for c in cells]


def parse_docx(docx_path: str, out_dir: str):
    """
    解析 docx, 生成 表目录.md 和 表结构/<表名>.md。
    返回解析到的表数量。
    """

    # ── 1. 读取文档 body, 按顺序遍历段落和表格 ──────────────────
    with ZipFile(docx_path, "r") as zf:
        with zf.open("word/document.xml") as f:
            tree = etree.parse(f)

    body = tree.find("{%s}body" % NS)
    if body is None:
        raise ValueError("文档中未找到 <w:body> 元素")

    tables_data = []          # 解析结果列表
    current_category = ""     # 当前 Heading 1 分类
    pending_heading = None    # 等待下一个 table 关联的 Heading 2 数据
    table_name_counts = {}    # 处理重名表

    for child in body:
        tag = child.tag.split("}")[-1]

        if tag == "p":
            # 检查段落样式 (Heading 1 / Heading 2)
            ps = child.find("{%s}pPr/{%s}pStyle" % (NS, NS))
            if ps is None:
                continue
            style_val = ps.get("{%s}val" % NS)

            if style_val == "2":  # Heading 1 — 分类
                text = _text_of_element(child).strip()
                if text:
                    current_category = text

            elif style_val == "3":  # Heading 2 — 表名 + 中文说明
                raw = _text_of_element(child).strip()
                if not raw:
                    continue

                # 提取英文表名 (大写字母开头, 含下划线和数字)
                en_match = re.search(r"([A-Z][A-Z_0-9]+)", raw)
                if not en_match:
                    continue
                en_name = en_match.group(1)

                # 提取中文说明 (全角/半角括号内)
                cn_name = ""
                cn_match = re.search(r"[（(](.+?)[）)]", raw)
                if cn_match:
                    cn_name = cn_match.group(1)
                else:
                    # 去掉英文表名后的剩余文本作为中文说明
                    rest = raw.replace(en_name, "", 1).strip()
                    cn_name = rest

                # 处理重名表 (如两个 CDC_RECORDFORM_BINDING)
                if en_name in table_name_counts:
                    table_name_counts[en_name] += 1
                    en_name_unique = f"{en_name}_{table_name_counts[en_name]}"
                else:
                    table_name_counts[en_name] = 1
                    en_name_unique = en_name

                pending_heading = {
                    "category": current_category,
                    "name_en": en_name,
                    "name_en_unique": en_name_unique,
                    "name_cn": cn_name,
                    "heading_raw": raw,
                }

        elif tag == "tbl":
            if pending_heading is None:
                # 表格前没有 Heading 2, 跳过 (如目录页的表格)
                continue

            rows = child.findall(".//{%s}tr" % NS)
            if len(rows) < 2:
                # 至少需要表头 + 1 行数据
                pending_heading = None
                continue

            fields = []
            for row in rows[1:]:  # 跳过表头行
                cell_texts = _cell_texts(row)
                # 需要至少 7 列且有字段名 (第3列)
                if len(cell_texts) >= 7 and cell_texts[2]:
                    fields.append({
                        "seq": cell_texts[0],
                        "name_cn": cell_texts[1],
                        "name_en": cell_texts[2],
                        "type": cell_texts[3],
                        "length": cell_texts[4],
                        "nullable": cell_texts[5] if cell_texts[5] else "Y",
                        "comment": cell_texts[6] if len(cell_texts) > 6 else "",
                    })

            if not fields:
                pending_heading = None
                continue

            # 提取外键关系 (从字段说明中匹配 "FK → 表名.字段" 或类似模式)
            foreign_keys = []
            for f in fields:
                # 匹配 "FK → TABLE.FIELD" 或 "外键 → TABLE.FIELD"
                fk_match = re.search(
                    r"(?:FK|外键)\s*[→>-]\s*(\w+)\.(\w+)",
                    f["comment"],
                    re.IGNORECASE,
                )
                if fk_match:
                    foreign_keys.append({
                        "field": f["name_en"],
                        "ref_table": fk_match.group(1),
                        "ref_field": fk_match.group(2),
                    })
                else:
                    # 匹配 "关联 XXX表" 或 "引用 XXX.FIELD" (仅大写英文表名)
                    ref_match = re.search(
                        r"(?:关联|引用)\s*([A-Z][A-Z_0-9]+)(?:表|\.([A-Z][A-Z_0-9]+))?",
                        f["comment"],
                    )
                    if ref_match:
                        ref_table = ref_match.group(1)
                        ref_field = ref_match.group(2) if ref_match.group(2) else ""
                        if ref_table.upper() != pending_heading["name_en"]:
                            foreign_keys.append({
                                "field": f["name_en"],
                                "ref_table": ref_table,
                                "ref_field": ref_field if ref_field else "",
                            })

            tables_data.append({
                **pending_heading,
                "fields": fields,
                "foreign_keys": foreign_keys,
            })

            pending_heading = None  # 消费完毕

    # ── 2. 确保输出目录存在 ─────────────────────────────────────
    out_path = Path(out_dir)
    struct_dir = out_path / "表结构"
    struct_dir.mkdir(parents=True, exist_ok=True)

    # ── 3. 生成 表目录.md ─────────────────────────────────────────
    catalog_lines = ["# 表目录\n"]
    last_cat = None
    for t in tables_data:
        if t["category"] != last_cat:
            catalog_lines.append(f"\n## {t['category']}\n")
            catalog_lines.append("| 表名 | 说明 | 详情 |\n|---|---|---|\n")
            last_cat = t["category"]

        fk_info = ""
        if t["foreign_keys"]:
            fk_parts = []
            for fk in t["foreign_keys"]:
                ref = f"{fk['ref_table']}.{fk['ref_field']}" if fk["ref_field"] else fk["ref_table"]
                fk_parts.append(f"{fk['field']} → {ref}")
            fk_info = f"（外键: {'; '.join(fk_parts)}）"

        catalog_lines.append(
            f"| {t['name_en']} | {t['name_cn']}{fk_info} | "
            f"[表结构/{t['name_en_unique']}.md](表结构/{t['name_en_unique']}.md) |\n"
        )

    catalog_path = out_path / "表目录.md"
    catalog_path.write_text("".join(catalog_lines), encoding="utf-8")

    # ── 4. 生成 表结构/<表名>.md ─────────────────────────────────
    for t in tables_data:
        lines = [f"# {t['name_en']}（{t['name_cn']}）\n\n"]

        # 分类信息
        lines.append(f"> 分类: {t['category']}\n\n")

        # 主键信息 — 从字段说明中识别
        pks = [
            f["name_en"]
            for f in t["fields"]
            if re.search(r"\bPK\b", f["comment"], re.IGNORECASE)
        ]
        if pks:
            lines.append(f"**主键:** {', '.join(pks)}\n\n")

        # 外键信息
        if t["foreign_keys"]:
            lines.append("**外键:**\n")
            for fk in t["foreign_keys"]:
                ref = f"{fk['ref_table']}.{fk['ref_field']}" if fk["ref_field"] else fk["ref_table"]
                lines.append(f"- `{fk['field']}` → `{ref}`\n")
            lines.append("\n")

        # 字段表格
        lines.append("| 序号 | 字段名 | 中文名 | 类型 | 长度 | NULL | 说明 |\n")
        lines.append("|---|---|---|---|---|---|---|\n")
        for f in t["fields"]:
            nullable = "Y" if f["nullable"].upper() not in ("N", "NO", "NOT NULL") else "N"
            lines.append(
                f"| {f['seq']} | {f['name_en']} | {f['name_cn']} | "
                f"{f['type']} | {f['length']} | {nullable} | {f['comment']} |\n"
            )

        table_path = struct_dir / f"{t['name_en_unique']}.md"
        table_path.write_text("".join(lines), encoding="utf-8")

    return len(tables_data)


# ── CLI 入口 ──────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: py parse_docx.py <docx路径> [输出目录]")
        sys.exit(1)

    docx_path = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else str(Path(docx_path).parent)
    out_dir = str(Path(out_dir).resolve())

    if not Path(docx_path).exists():
        print(f"错误: 文件不存在 — {docx_path}")
        sys.exit(1)

    count = parse_docx(docx_path, out_dir)
    print(f"完成: 生成 {count} 张表的文档 → {out_dir}")
