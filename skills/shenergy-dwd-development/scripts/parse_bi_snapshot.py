#!/usr/bin/env python3
"""申能 BI看 Excel 快照离线解析器（纯标准库，物理隔离 I/J/K 列）。

只使用 Python 3.10+ 标准库（zipfile / xml.etree.ElementTree / csv / json）；
不连接数据库、不访问网络。

硬约束：
  仅允许读取列 ("A", "B", "C", "D", "E", "F", "G", "H", "L")，
  物理忽略 I、J、K（以及 L 之后的任何列），不读取也不保留其单元格内容。

用法：
  python scripts/parse_bi_snapshot.py <snapshot.xlsx> [--sheet BI看] [--province <省>] [--business <业态>] [--header-row N] [--out-csv <out.csv>] [--json]

退出码：0 = 成功；2 = 参数、文件读取或 sheet 缺失错误。
"""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

ALLOWED_COLUMNS = ("A", "B", "C", "D", "E", "F", "G", "H", "L")
ALLOWED_SET = set(ALLOWED_COLUMNS)
IGNORED_COLUMNS = ["I", "J", "K"]

CSV_HEADER = [
    "目标表",
    "区块",
    "物理序号",
    "英文名称",
    "中文名称（BI看）",
    "库注释",
    "BI看行",
    "取值来源表",
    "取值来源表字段",
    "口径/说明",
    "单位",
    "缺值规则",
]

CELL_REF_RE = re.compile(r"^([A-Z]+)(\d+)$")
RANGE_REF_RE = re.compile(r"^([A-Z]+)(\d+):([A-Z]+)(\d+)$")

PENDING_EXACT = {
    "待补充",
    "待确认",
    "待定",
    "暂无",
    "无",
    "空",
    "未命名",
    "tbd",
    "todo",
    "-",
    "--",
    "/",
    "n/a",
}

PENDING_PREFIX_RE = re.compile(r"^(?:待补充|待确认|待定|未命名)(?:[：:（(].*)?$")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _attr(elem: ET.Element, name: str) -> str:
    if name in elem.attrib:
        return elem.attrib[name]
    suffix = "}" + name
    for k, v in elem.attrib.items():
        if k.endswith(suffix):
            return v
    return ""


def _col_to_num(col: str) -> int:
    num = 0
    for ch in col:
        num = num * 26 + (ord(ch) - ord("A") + 1)
    return num


def _num_to_col(num: int) -> str:
    letters: list[str] = []
    while num > 0:
        num, rem = divmod(num - 1, 26)
        letters.append(chr(ord("A") + rem))
    return "".join(reversed(letters))


def _extract_text_no_phonetic(elem: ET.Element) -> str:
    """Collect text from <t> descendants while skipping <rPh> phonetic runs."""
    parts: list[str] = []

    def walk(node: ET.Element) -> None:
        lname = _local(node.tag)
        if lname == "rPh":
            return
        if lname == "t":
            if node.text:
                parts.append(node.text)
            return
        for child in node:
            walk(child)

    walk(elem)
    return "".join(parts)


def _read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    candidates = [n for n in zf.namelist() if n.lower() == "xl/sharedstrings.xml"]
    if not candidates:
        return []
    root = ET.fromstring(zf.read(candidates[0]))
    strings: list[str] = []
    for child in root:
        if _local(child.tag) == "si":
            strings.append(_extract_text_no_phonetic(child))
    return strings


def _resolve_sheet_path(zf: zipfile.ZipFile, sheet_name: str) -> str:
    if "xl/workbook.xml" not in zf.namelist():
        raise ValueError("无效的 .xlsx：缺少 xl/workbook.xml")
    wb_root = ET.fromstring(zf.read("xl/workbook.xml"))

    target_rid = ""
    available: list[str] = []
    for elem in wb_root.iter():
        if _local(elem.tag) == "sheet":
            name = elem.attrib.get("name", "")
            available.append(name)
            if name == sheet_name:
                target_rid = _attr(elem, "id")
                break

    if not target_rid:
        raise ValueError(
            f"未找到目标 sheet {sheet_name!r}；可用 sheet：{', '.join(available) or '<空>'}"
        )

    rels_name = "xl/_rels/workbook.xml.rels"
    if rels_name not in zf.namelist():
        raise ValueError("无效的 .xlsx：缺少 xl/_rels/workbook.xml.rels")
    rels_root = ET.fromstring(zf.read(rels_name))
    target_path = ""
    for elem in rels_root.iter():
        if _local(elem.tag) == "Relationship" and elem.attrib.get("Id") == target_rid:
            target_path = elem.attrib.get("Target", "")
            break

    if not target_path:
        raise ValueError(f"workbook.xml.rels 中未找到关系 {target_rid}")

    norm = target_path.lstrip("/")
    if not norm.startswith("xl/"):
        norm = "xl/" + norm
    if norm not in zf.namelist():
        raise ValueError(f"工作表文件不存在：{norm}")
    return norm


def _read_cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    ctype = cell.attrib.get("t", "")
    if ctype == "inlineStr":
        for child in cell:
            if _local(child.tag) == "is":
                return _extract_text_no_phonetic(child)
        return ""

    v_text = ""
    for child in cell:
        if _local(child.tag) == "v":
            v_text = child.text or ""
            break

    if ctype == "s":
        if not v_text:
            return ""
        idx = int(v_text)
        return shared_strings[idx] if 0 <= idx < len(shared_strings) else ""
    if ctype == "b":
        return "TRUE" if v_text == "1" else "FALSE"
    return v_text


def classify_l_value(raw_val: str) -> tuple[str, list[str]]:
    """Classify Col L into ('empty' | 'pending' | 'named', source_tables)."""
    text = raw_val.strip()
    if not text:
        return "empty", []
    if text.lower() in PENDING_EXACT or PENDING_PREFIX_RE.match(text):
        return "pending", []

    tokens: list[str] = []
    for chunk in re.split(r"[\r\n,，;；、]+", text):
        cleaned = re.sub(r"^\s*(?:\d+[.、)）]|[-*•])\s*", "", chunk).strip()
        if not cleaned:
            continue
        if cleaned.lower() in PENDING_EXACT or PENDING_PREFIX_RE.match(cleaned):
            continue
        if cleaned not in tokens:
            tokens.append(cleaned)

    if not tokens:
        return "pending", []
    return "named", tokens


def _detect_header_row(grid: dict[int, dict[str, str]], max_row: int) -> int:
    keywords = (
        "省",
        "业态",
        "目标表",
        "区块",
        "数据项",
        "指标",
        "中文",
        "来源",
        "口径",
        "单位",
        "缺值",
    )
    best_row = 1
    best_score = -1
    for r in range(1, min(max_row, 25) + 1):
        row_cells = grid.get(r, {})
        if not any(v.strip() for v in row_cells.values()):
            continue
        joined = " ".join(v.strip() for v in row_cells.values() if v.strip())
        score = sum(1 for kw in keywords if kw in joined)
        if score > best_score:
            best_score = score
            best_row = r
    return best_row


def _match_header_col(
    headers: dict[str, str], patterns: tuple[str, ...], exclude: tuple[str, ...] = ()
) -> str | None:
    for col in ALLOWED_COLUMNS:
        h = headers.get(col, "").strip()
        if not h:
            continue
        if any(ex in h for ex in exclude):
            continue
        if any(re.search(pat, h, re.IGNORECASE) for pat in patterns):
            return col
    return None


def _build_csv_rows(
    headers: dict[str, str], parsed_rows: list[dict]
) -> list[list[str]]:
    col_target = _match_header_col(headers, (r"目标表", r"dwd表"), exclude=("来源",))
    col_section = _match_header_col(headers, (r"区块", r"图表", r"模块", r"分类", r"板块"))
    col_seq = _match_header_col(headers, (r"物理序号", r"^序号$"))
    col_en = _match_header_col(headers, (r"英文名称", r"英文名", r"字段英文"))
    col_cn = _match_header_col(
        headers, (r"中文名称", r"数据项", r"指标名称", r"指标名", r"字段中文")
    )
    if col_cn is None:
        col_cn = "B"
    col_comment = _match_header_col(headers, (r"库注释", r"字段注释", r"^注释$"))
    col_src_tbl = _match_header_col(headers, (r"取值来源表", r"来源表"), exclude=("字段",))
    if col_src_tbl is None:
        col_src_tbl = "L"
    col_src_col = _match_header_col(headers, (r"取值来源表字段", r"来源表字段", r"来源字段", r"取值字段"))
    col_caliber = _match_header_col(headers, (r"口径", r"说明", r"逻辑", r"规则", r"公式", r"计算"), exclude=("缺值",))
    col_unit = _match_header_col(headers, (r"单位",))
    col_missing = _match_header_col(headers, (r"缺值",))

    csv_rows: list[list[str]] = [list(CSV_HEADER)]
    for item in parsed_rows:
        cells: dict[str, str] = item["cells"]

        def val(col: str | None, fallback: str = "待确认") -> str:
            if col is None:
                return fallback
            v = cells.get(col, "").strip()
            return v if v else fallback

        src_tbl_val = (
            "; ".join(item["source_tables"])
            if item["source_status"] == "named" and col_src_tbl == "L"
            else val(col_src_tbl)
        )
        cn_val = val(col_cn, "")
        if not cn_val:
            for alt_col in ("B", "C", "D", "E", "F", "G", "H"):
                if cells.get(alt_col, "").strip():
                    cn_val = cells[alt_col].strip()
                    break
        if not cn_val:
            cn_val = "待确认"

        csv_rows.append(
            [
                val(col_target),
                val(col_section),
                val(col_seq),
                val(col_en),
                cn_val,
                val(col_comment),
                str(item["row"]),
                src_tbl_val,
                val(col_src_col),
                val(col_caliber),
                val(col_unit),
                val(col_missing),
            ]
        )
    return csv_rows


def parse_snapshot(
    xlsx_path: pathlib.Path,
    *,
    sheet_name: str = "BI看",
    province: str | None = None,
    business: str | None = None,
    header_row: int | None = None,
) -> dict:
    with zipfile.ZipFile(xlsx_path, "r") as zf:
        shared_strings = _read_shared_strings(zf)
        sheet_xml_path = _resolve_sheet_path(zf, sheet_name)
        ws_root = ET.fromstring(zf.read(sheet_xml_path))

    raw_grid: dict[int, dict[str, str]] = {}
    max_row = 0

    for elem in ws_root.iter():
        if _local(elem.tag) == "c":
            ref = elem.attrib.get("r", "")
            m = CELL_REF_RE.match(ref)
            if not m:
                continue
            col, row_idx = m.group(1), int(m.group(2))
            # 硬白名单：物理忽略 I/J/K 及一切非允许列，完全不读取其内容
            if col not in ALLOWED_SET:
                continue
            val = _read_cell_value(elem, shared_strings)
            raw_grid.setdefault(row_idx, {})[col] = val
            if row_idx > max_row:
                max_row = row_idx

    merge_ranges: list[str] = []
    cell_merge_map: dict[tuple[int, str], str] = {}
    for elem in ws_root.iter():
        if _local(elem.tag) == "mergeCell":
            ref = elem.attrib.get("ref", "")
            m = RANGE_REF_RE.match(ref)
            if not m:
                continue
            c1, r1, c2, r2 = m.group(1), int(m.group(2)), m.group(3), int(m.group(4))
            n1, n2 = _col_to_num(c1), _col_to_num(c2)
            allowed_in_merge = [
                _num_to_col(cn)
                for cn in range(n1, n2 + 1)
                if _num_to_col(cn) in ALLOWED_SET
            ]
            if not allowed_in_merge:
                continue
            merge_ranges.append(ref)
            top_val = raw_grid.get(r1, {}).get(c1, "") if c1 in ALLOWED_SET else ""
            for r in range(r1, r2 + 1):
                if r > max_row:
                    max_row = r
                for c in allowed_in_merge:
                    cell_merge_map[(r, c)] = ref
                    if c1 in ALLOWED_SET and top_val and not raw_grid.get(r, {}).get(c, ""):
                        raw_grid.setdefault(r, {})[c] = top_val

    eff_header_row = (
        header_row if header_row is not None else _detect_header_row(raw_grid, max_row)
    )
    headers = {
        col: raw_grid.get(eff_header_row, {}).get(col, "").strip()
        for col in ALLOWED_COLUMNS
    }

    parsed_rows: list[dict] = []
    l_summary = {"empty": 0, "pending": 0, "named": 0}

    for r in range(eff_header_row + 1, max_row + 1):
        row_raw = raw_grid.get(r, {})
        cells = {col: row_raw.get(col, "").strip() for col in ALLOWED_COLUMNS}
        if not any(cells.values()):
            continue

        col_a = cells["A"]
        if province and province.lower() not in col_a.lower():
            continue
        if business and business.lower() not in col_a.lower():
            continue

        status, src_tables = classify_l_value(cells["L"])
        l_summary[status] += 1
        merged_info = {
            col: cell_merge_map[(r, col)]
            for col in ALLOWED_COLUMNS
            if (r, col) in cell_merge_map
        }
        parsed_rows.append(
            {
                "row": r,
                "cells": cells,
                "merged_cells": merged_info,
                "source_status": status,
                "source_tables": src_tables,
            }
        )

    return {
        "ok": True,
        "database_connected": False,
        "snapshot": str(xlsx_path),
        "sheet": sheet_name,
        "header_row": eff_header_row,
        "ignored_columns": list(IGNORED_COLUMNS),
        "allowed_columns": list(ALLOWED_COLUMNS),
        "filters": {"province": province, "business": business},
        "headers": headers,
        "merge_ranges": merge_ranges,
        "row_count": len(parsed_rows),
        "l_summary": l_summary,
        "rows": parsed_rows,
    }


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass

    parser = argparse.ArgumentParser(
        description="离线解析申能 BI看 Excel 快照（仅读取 A-H 与 L 列，物理忽略 I/J/K）。"
    )
    parser.add_argument("snapshot", help="任务当天快照 .xlsx 路径")
    parser.add_argument("--sheet", default="BI看", help="工作表名，默认 BI看")
    parser.add_argument("--province", default=None, help="按 A 列筛选省份关键词")
    parser.add_argument("--business", default=None, help="按 A 列筛选业态关键词")
    parser.add_argument(
        "--header-row", type=int, default=None, help="显式指定表头行号（1 基）"
    )
    parser.add_argument(
        "--out-csv", default=None, help="可选：输出符合 12 列契约的 UTF-8 无 BOM CSV 骨架"
    )
    parser.add_argument("--json", action="store_true", help="以 JSON 输出解析结果")
    args = parser.parse_args(argv)

    xlsx_path = pathlib.Path(args.snapshot)
    if not xlsx_path.is_file():
        print(f"读取快照失败：文件不存在：{xlsx_path}", file=sys.stderr)
        return 2

    if args.header_row is not None and args.header_row < 1:
        print("--header-row 必须 >= 1", file=sys.stderr)
        return 2

    try:
        result = parse_snapshot(
            xlsx_path,
            sheet_name=args.sheet,
            province=args.province,
            business=args.business,
            header_row=args.header_row,
        )
    except (OSError, zipfile.BadZipFile, ET.ParseError, ValueError) as exc:
        print(f"解析快照失败：{exc}", file=sys.stderr)
        return 2

    out_csv_str: str | None = None
    if args.out_csv:
        csv_path = pathlib.Path(args.out_csv)
        csv_rows = _build_csv_rows(result["headers"], result["rows"])
        try:
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            with csv_path.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh, lineterminator="\n")
                writer.writerows(csv_rows)
            out_csv_str = str(csv_path)
        except OSError as exc:
            print(f"写入 CSV 失败：{exc}", file=sys.stderr)
            return 2

    result["out_csv"] = out_csv_str

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"快照：{xlsx_path}（sheet={args.sheet}，表头行={result['header_row']}）")
        print(f"物理忽略列：{', '.join(IGNORED_COLUMNS)}")
        print(
            f"有效行：{result['row_count']}；"
            f"L 列分类：named={result['l_summary']['named']}, "
            f"pending={result['l_summary']['pending']}, "
            f"empty={result['l_summary']['empty']}"
        )
        if out_csv_str:
            print(f"已写入 12 列 CSV 骨架：{out_csv_str}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
