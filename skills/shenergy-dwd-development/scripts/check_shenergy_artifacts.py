#!/usr/bin/env python3
"""申能 DWD 产物离线静态检查器（DDL / 函数 / 对照 CSV / 交付报告 / 函数规格 Spec / bootstrap 产物集合）。

只使用 Python 3.10+ 标准库；不连接数据库、不访问网络、不执行任何 SQL。

用法：
  python scripts/check_shenergy_artifacts.py --kind <ddl|func|csv|report|spec> [--grain day|month] [--legacy] [--spec <spec.json>] [--with-pg-checker] [--pg-checker <path>] [--comma-style leading|trailing] [--json] <path>
  python scripts/check_shenergy_artifacts.py --kind bootstrap [--json] <省份业态目录>

退出码：0 = 无错误级违规；1 = 发现错误级违规；2 = 用法或读取错误。
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import io
import json
import pathlib
import re
import sys

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

EXT_COL_PATTERN = re.compile(r"^ext_(?:[1-9]|10)$", re.IGNORECASE)
EXT_ANY_PATTERN = re.compile(r"^ext_\d+$", re.IGNORECASE)
EXT_IN_CODE_PATTERN = re.compile(r"\bext_(?:[1-9]|10)\b", re.IGNORECASE)

DOLLAR_TAG_PATTERN = re.compile(r"\$[A-Za-z_]\w*\$|\$\$")

FLOAT_TYPE_PATTERN = re.compile(
    r"\b(?:float|float4|float8|double\s+precision|real)\b", re.IGNORECASE
)
NUMERIC_TYPE_PATTERN = re.compile(
    r"\b(?:numeric|decimal)\b(?:\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)|\s*\(\s*(\d+)\s*\))?",
    re.IGNORECASE,
)
YEARMONTH_TYPE_PATTERN = re.compile(
    r"^(?:varchar|character\s+varying)\s*\(\s*10\s*\)\s*$", re.IGNORECASE
)

MYSQL_TOKEN_PATTERNS = (
    ("AUTO_INCREMENT", re.compile(r"\bAUTO_INCREMENT\b", re.IGNORECASE)),
    ("ENGINE=", re.compile(r"\bENGINE\s*=", re.IGNORECASE)),
    ("CHARACTER SET", re.compile(r"\bCHARACTER\s+SET\b", re.IGNORECASE)),
)

CREATE_TABLE_PATTERN = re.compile(
    r"(?is)\bCREATE\s+(?:TEMP(?:ORARY)?\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r'((?:"[^"]+"|[A-Za-z_][\w$]*)(?:\s*\.\s*(?:"[^"]+"|[A-Za-z_][\w$]*))?)\s*\('
)
DROP_TABLE_PATTERN = re.compile(
    r"(?is)\bDROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?"
    r'((?:"[^"]+"|[A-Za-z_][\w$]*)(?:\s*\.\s*(?:"[^"]+"|[A-Za-z_][\w$]*))?)'
)
ALTER_PK_PATTERN = re.compile(
    r"(?is)\bALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?"
    r'((?:"[^"]+"|[A-Za-z_][\w$]*)(?:\s*\.\s*(?:"[^"]+"|[A-Za-z_][\w$]*))?)'
    r"\s+ADD\s+(?:CONSTRAINT\s+[^;\n]+?\s+)?PRIMARY\s+KEY\s*\("
)
CREATE_INDEX_PATTERN = re.compile(
    r"(?is)\bCREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?"
    r'("[^"]+"|[A-Za-z_][\w$]*)\s+ON\b'
)
COMMENT_TABLE_PATTERN = re.compile(
    r"(?is)\bCOMMENT\s+ON\s+TABLE\s+"
    r'((?:"[^"]+"|[A-Za-z_][\w$]*)(?:\s*\.\s*(?:"[^"]+"|[A-Za-z_][\w$]*))?)'
    r"\s+IS\s+('(?:''|[^'])*'|NULL)\s*;"
)
COMMENT_COLUMN_PATTERN = re.compile(
    r"(?is)\bCOMMENT\s+ON\s+COLUMN\s+"
    r'((?:"[^"]+"|[A-Za-z_][\w$]*)'
    r'(?:\s*\.\s*(?:"[^"]+"|[A-Za-z_][\w$]*)){1,2})'
    r"\s+IS\s+('(?:''|[^'])*'|NULL)\s*;"
)

CREATE_FUNC_PATTERN = re.compile(
    r"(?im)^\s*CREATE\s+(?:OR\s+REPLACE\s+)?(?:FUNCTION|PROCEDURE)\b"
)
FUNC_SIG_NAME_PATTERN = re.compile(
    r"(?is)\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:FUNCTION|PROCEDURE)\s+"
    r'((?:"[^"]+"|[A-Za-z_][\w$]*)(?:\s*\.\s*(?:"[^"]+"|[A-Za-z_][\w$]*))?)\s*\('
)
BODY_TAG_PATTERN = re.compile(r"(?is)\bAS\s+(\$[A-Za-z_]\w*\$|\$\$)[ \t]*\n?")


def add_finding(
    target: list[dict], rule: str, level: str, line: int, message: str
) -> None:
    target.append(
        {
            "rule": rule,
            "level": level,
            "line": max(1, line),
            "message": message,
        }
    )


def line_of(text: str, pos: int) -> int:
    return text[: max(0, pos)].count("\n") + 1


def mask_sql(text: str) -> tuple[str, str]:
    """Return (no_comments, code_only) preserving exact offsets and line numbers.

    - no_comments: SQL comments (-- and /* */) replaced with spaces.
    - code_only: comments AND single-quoted string contents replaced with spaces.
    """
    no_comments: list[str] = []
    code_only: list[str] = []
    i = 0
    n = len(text)
    in_line = False
    in_block = False
    in_single = False
    in_double = False

    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""

        if in_line:
            if ch == "\n":
                in_line = False
                no_comments.append("\n")
                code_only.append("\n")
            else:
                no_comments.append(" ")
                code_only.append(" ")
            i += 1
            continue

        if in_block:
            if ch == "*" and nxt == "/":
                in_block = False
                no_comments.append("  ")
                code_only.append("  ")
                i += 2
                continue
            out_ch = "\n" if ch == "\n" else " "
            no_comments.append(out_ch)
            code_only.append(out_ch)
            i += 1
            continue

        if in_single:
            if ch == "'" and nxt == "'":
                no_comments.append("''")
                code_only.append("  ")
                i += 2
                continue
            if ch == "'":
                in_single = False
                no_comments.append("'")
                code_only.append("'")
            else:
                no_comments.append(ch)
                code_only.append("\n" if ch == "\n" else " ")
            i += 1
            continue

        if in_double:
            if ch == '"' and nxt == '"':
                no_comments.append('""')
                code_only.append('""')
                i += 2
                continue
            if ch == '"':
                in_double = False
            no_comments.append(ch)
            code_only.append(ch)
            i += 1
            continue

        if ch == "-" and nxt == "-":
            in_line = True
            no_comments.append("  ")
            code_only.append("  ")
            i += 2
            continue

        if ch == "/" and nxt == "*":
            in_block = True
            no_comments.append("  ")
            code_only.append("  ")
            i += 2
            continue

        if ch == "'":
            in_single = True
            no_comments.append("'")
            code_only.append("'")
            i += 1
            continue

        if ch == '"':
            in_double = True
            no_comments.append('"')
            code_only.append('"')
            i += 1
            continue

        no_comments.append(ch)
        code_only.append(ch)
        i += 1

    return "".join(no_comments), "".join(code_only)


def matching_paren_end(text: str, open_index: int) -> int:
    """Find matching ')' from '(' at open_index, ignoring comments and quotes."""
    depth = 0
    i = open_index
    n = len(text)
    in_single = False
    in_double = False
    in_line = False
    in_block = False

    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_line:
            if ch == "\n":
                in_line = False
            i += 1
            continue
        if in_block:
            if ch == "*" and nxt == "/":
                in_block = False
                i += 2
                continue
            i += 1
            continue
        if in_single:
            if ch == "'" and nxt == "'":
                i += 2
                continue
            if ch == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            if ch == '"' and nxt == '"':
                i += 2
                continue
            if ch == '"':
                in_double = False
            i += 1
            continue
        if ch == "-" and nxt == "-":
            in_line = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block = True
            i += 2
            continue
        if ch == "'":
            in_single = True
            i += 1
            continue
        if ch == '"':
            in_double = True
            i += 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def split_top_level_commas(text: str) -> list[tuple[int, str]]:
    """Split text at top-level commas, respecting parens, brackets, quotes, comments."""
    items: list[tuple[int, str]] = []
    start = 0
    i = 0
    n = len(text)
    paren = 0
    bracket = 0
    in_single = False
    in_double = False
    in_line = False
    in_block = False

    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_line:
            if ch == "\n":
                in_line = False
            i += 1
            continue
        if in_block:
            if ch == "*" and nxt == "/":
                in_block = False
                i += 2
                continue
            i += 1
            continue
        if in_single:
            if ch == "'" and nxt == "'":
                i += 2
                continue
            if ch == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            if ch == '"' and nxt == '"':
                i += 2
                continue
            if ch == '"':
                in_double = False
            i += 1
            continue
        if ch == "-" and nxt == "-":
            in_line = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block = True
            i += 2
            continue
        if ch == "'":
            in_single = True
            i += 1
            continue
        if ch == '"':
            in_double = True
            i += 1
            continue
        if ch == "(":
            paren += 1
        elif ch == ")":
            if paren > 0:
                paren -= 1
        elif ch == "[":
            bracket += 1
        elif ch == "]":
            if bracket > 0:
                bracket -= 1
        elif ch == "," and paren == 0 and bracket == 0:
            items.append((start, text[start:i]))
            start = i + 1
        i += 1

    items.append((start, text[start:]))
    return items


def normalize_ident(raw: str) -> str:
    s = raw.strip()
    if s.startswith('"') and s.endswith('"') and len(s) >= 2:
        s = s[1:-1].replace('""', '"')
    return s


def split_qualified(raw: str) -> tuple[str, str]:
    parts = [normalize_ident(p) for p in re.split(r"\s*\.\s*", raw.strip())]
    if len(parts) >= 2:
        return parts[-2].lower(), parts[-1].lower()
    return "", parts[0].lower()


def check_identifier_length(
    ident: str, line: int, kind_label: str, violations: list[dict], warnings: list[dict]
) -> None:
    length = len(ident)
    if length > 63:
        add_finding(
            violations,
            "SH-DDL-02",
            "error",
            line,
            f"{kind_label} {ident!r} 长度为 {length}，超过 PostgreSQL 硬上限 63（SH-DDL-02）",
        )
    elif length >= 59:
        add_finding(
            warnings,
            "SH-DDL-02",
            "warning",
            line,
            f"{kind_label} {ident!r} 长度为 {length}，接近上限 63（目标 <= 58）（SH-DDL-02）",
        )


def _strip_comments_keep_strings(text: str) -> str:
    no_comments, _ = mask_sql(text)
    return no_comments


def _extract_leading_ident(item: str) -> tuple[str, str]:
    s = item.lstrip()
    if s.startswith('"'):
        i = 1
        while i < len(s):
            if s[i] == '"' and i + 1 < len(s) and s[i + 1] == '"':
                i += 2
                continue
            if s[i] == '"':
                return normalize_ident(s[: i + 1]), s[i + 1 :].strip()
            i += 1
    m = re.match(r"([A-Za-z_][\w$]*)\s+(.*)", s, re.DOTALL)
    if m:
        return m.group(1), m.group(2).strip()
    return "", s


def check_ddl(text: str, spec: dict | None = None) -> tuple[list[dict], list[dict]]:
    violations: list[dict] = []
    warnings: list[dict] = []
    no_comments, code_only = mask_sql(text)
    parsed_tables: dict[tuple[str, str], tuple[set[str], int]] = {}
    parsed_tables_unqual: dict[str, tuple[set[str], int]] = {}

    # SH-DDL-05: MySQL tokens and unquoted backticks
    for token_name, pattern in MYSQL_TOKEN_PATTERNS:
        for m in pattern.finditer(code_only):
            add_finding(
                violations,
                "SH-DDL-05",
                "error",
                line_of(text, m.start()),
                f"DDL 包含未转换的 MySQL 关键字 {token_name}（SH-DDL-05）",
            )
    for m in re.finditer(r"`", code_only):
        add_finding(
            violations,
            "SH-DDL-05",
            "error",
            line_of(text, m.start()),
            "DDL 包含未转换的反引号标识符（SH-DDL-05）",
        )

    # SH-DDL-09: SET client_encoding = 'UTF8'; and SET search_path = '';
    has_encoding = bool(
        re.search(
            r"(?i)\bSET\s+client_encoding\s*=\s*'utf-?8'\s*;", no_comments
        )
    )
    has_search_path = bool(
        re.search(r"(?i)\bSET\s+search_path\s*=\s*''\s*;", no_comments)
    )
    if not has_encoding or not has_search_path:
        missing = []
        if not has_encoding:
            missing.append("SET client_encoding = 'UTF8';")
        if not has_search_path:
            missing.append("SET search_path = '';")
        add_finding(
            violations,
            "SH-DDL-09",
            "error",
            1,
            f"DDL 缺少必备会话头设置：{', '.join(missing)}（SH-DDL-09）",
        )

    # SH-DDL-01 on DROP TABLE too
    for m in DROP_TABLE_PATTERN.finditer(code_only):
        _, tbl = split_qualified(m.group(1))
        if tbl.endswith("_d24"):
            add_finding(
                violations,
                "SH-DDL-01",
                "error",
                line_of(text, m.start()),
                f"禁止出现 _d24 目标表：{m.group(1).strip()}（SH-DDL-01）",
            )

    # Index names length (SH-DDL-02)
    for m in CREATE_INDEX_PATTERN.finditer(code_only):
        idx_name = normalize_ident(m.group(1))
        check_identifier_length(
            idx_name, line_of(text, m.start()), "索引名", violations, warnings
        )

    # Collect COMMENT ON TABLE & COMMENT ON COLUMN
    table_comments: dict[tuple[str, str], bool] = {}
    table_comments_unqual: dict[str, bool] = {}
    column_comments: dict[tuple[str, str, str], bool] = {}
    column_comments_unqual: dict[tuple[str, str], bool] = {}

    for m in COMMENT_TABLE_PATTERN.finditer(no_comments):
        schema, tbl = split_qualified(m.group(1))
        val = m.group(2).strip()
        non_empty = val.upper() != "NULL" and len(val) > 2
        if non_empty:
            table_comments[(schema, tbl)] = True
            table_comments_unqual[tbl] = True

    for m in COMMENT_COLUMN_PATTERN.finditer(no_comments):
        parts = [normalize_ident(p).lower() for p in re.split(r"\s*\.\s*", m.group(1).strip())]
        val = m.group(2).strip()
        non_empty = val.upper() != "NULL" and len(val) > 2
        if not non_empty:
            continue
        if len(parts) == 3:
            column_comments[(parts[0], parts[1], parts[2])] = True
            column_comments_unqual[(parts[1], parts[2])] = True
        elif len(parts) == 2:
            column_comments[("", parts[0], parts[1])] = True
            column_comments_unqual[(parts[0], parts[1])] = True

    # Collect ALTER TABLE ... ADD PRIMARY KEY
    alter_pks: dict[tuple[str, str], list[int]] = {}
    alter_pks_unqual: dict[str, list[int]] = {}
    for m in ALTER_PK_PATTERN.finditer(code_only):
        schema, tbl = split_qualified(m.group(1))
        ln = line_of(text, m.start())
        alter_pks.setdefault((schema, tbl), []).append(ln)
        alter_pks_unqual.setdefault(tbl, []).append(ln)

    # Inspect CREATE TABLE blocks
    for m in CREATE_TABLE_PATTERN.finditer(code_only):
        raw_table = m.group(1).strip()
        schema, tbl = split_qualified(raw_table)
        tbl_line = line_of(text, m.start())

        if tbl.endswith("_d24"):
            add_finding(
                violations,
                "SH-DDL-01",
                "error",
                tbl_line,
                f"禁止建立 _d24 表：{raw_table}（SH-DDL-01）",
            )

        if schema:
            check_identifier_length(schema, tbl_line, "Schema 名", violations, warnings)
        check_identifier_length(tbl, tbl_line, "表名", violations, warnings)

        open_idx = m.end() - 1
        close_idx = matching_paren_end(text, open_idx)
        if close_idx == -1:
            add_finding(
                violations,
                "SH-DDL-07",
                "error",
                tbl_line,
                f"CREATE TABLE {raw_table} 括号未闭合，无法解析列定义",
            )
            continue

        body_raw = text[open_idx + 1 : close_idx]
        body_start_offset = open_idx + 1
        items = split_top_level_commas(body_raw)

        cols: list[tuple[str, str, int]] = []
        inline_or_table_pks: list[int] = []

        for rel_off, item_raw in items:
            item_clean = _strip_comments_keep_strings(item_raw).strip()
            if not item_clean:
                continue
            item_line = line_of(text, body_start_offset + rel_off + (len(item_raw) - len(item_raw.lstrip())))

            # Table-level constraints
            if re.match(
                r"(?i)^(?:CONSTRAINT\b|PRIMARY\s+KEY\b|UNIQUE\b|CHECK\b|FOREIGN\s+KEY\b|EXCLUDE\b|LIKE\b)",
                item_clean,
            ):
                con_m = re.match(
                    r'(?i)^CONSTRAINT\s+("[^"]+"|[A-Za-z_][\w$]*)\b', item_clean
                )
                if con_m:
                    check_identifier_length(
                        normalize_ident(con_m.group(1)),
                        item_line,
                        "约束名",
                        violations,
                        warnings,
                    )
                if re.search(r"(?i)\bPRIMARY\s+KEY\b", item_clean):
                    inline_or_table_pks.append(item_line)
                continue

            col_name, rest = _extract_leading_ident(item_clean)
            if not col_name:
                continue
            cols.append((col_name, rest, item_line))
            check_identifier_length(col_name, item_line, "列名", violations, warnings)

            if re.search(r"(?i)\bPRIMARY\s+KEY\b", rest):
                inline_or_table_pks.append(item_line)

            # Extract type portion before column constraints
            type_part = re.split(
                r"(?i)\b(?:NOT\s+NULL|NULL|DEFAULT|CONSTRAINT|PRIMARY|UNIQUE|CHECK|REFERENCES|COLLATE|GENERATED)\b",
                rest,
                maxsplit=1,
            )[0].strip()

            # SH-DDL-03: float / bare numeric / non-(20,6) numeric
            if FLOAT_TYPE_PATTERN.search(type_part):
                add_finding(
                    violations,
                    "SH-DDL-03",
                    "error",
                    item_line,
                    f"列 {col_name} 使用禁止的浮点类型 {type_part!r}，业务量值列须用 numeric(20,6)（SH-DDL-03）",
                )
            else:
                num_m = NUMERIC_TYPE_PATTERN.search(type_part)
                if num_m:
                    p_val, s_val, single_p = num_m.group(1), num_m.group(2), num_m.group(3)
                    if p_val is None or s_val is None or (int(p_val), int(s_val)) != (20, 6):
                        add_finding(
                            violations,
                            "SH-DDL-03",
                            "error",
                            item_line,
                            f"列 {col_name} 类型为 {type_part!r}，须统一为 numeric(20,6)（SH-DDL-03）",
                        )

            # SH-DDL-04: target_yearmonth must be varchar(10)/character varying(10)
            if col_name.lower() == "target_yearmonth":
                if not YEARMONTH_TYPE_PATTERN.match(type_part):
                    add_finding(
                        violations,
                        "SH-DDL-04",
                        "error",
                        item_line,
                        f"target_yearmonth 类型为 {type_part!r}，必须为 varchar(10) 或 character varying(10)（SH-DDL-04）",
                    )

        # SH-DDL-06: ext_1..ext_10 present max 10, updated_time is the last column
        ext_cols = [(c, ln) for c, _, ln in cols if EXT_ANY_PATTERN.match(c)]
        bad_ext = [(c, ln) for c, ln in ext_cols if not EXT_COL_PATTERN.match(c)]
        if bad_ext:
            for c, ln in bad_ext:
                add_finding(
                    violations,
                    "SH-DDL-06",
                    "error",
                    ln,
                    f"扩展列 {c} 超出 ext_1..ext_10 范围（SH-DDL-06）",
                )
        if not ext_cols:
            add_finding(
                violations,
                "SH-DDL-06",
                "error",
                tbl_line,
                f"表 {raw_table} 缺少预留扩展列 ext_1..ext_10（SH-DDL-06）",
            )
        elif len(ext_cols) > 10:
            add_finding(
                violations,
                "SH-DDL-06",
                "error",
                ext_cols[-1][1],
                f"表 {raw_table} ext_ 列数为 {len(ext_cols)}，最多允许 10 列（SH-DDL-06）",
            )

        if not cols or cols[-1][0].lower() != "updated_time":
            last_name = cols[-1][0] if cols else "<空>"
            last_ln = cols[-1][2] if cols else tbl_line
            add_finding(
                violations,
                "SH-DDL-06",
                "error",
                last_ln,
                f"表 {raw_table} 最后一列应为 updated_time，实际为 {last_name}（SH-DDL-06）",
            )
        else:
            # Ensure all ext_ columns appear right before updated_time (no business cols after ext_)
            seen_ext = False
            for c, _, ln in cols[:-1]:
                if EXT_ANY_PATTERN.match(c):
                    seen_ext = True
                elif seen_ext:
                    add_finding(
                        violations,
                        "SH-DDL-06",
                        "error",
                        ln,
                        f"列 {c} 位于 ext_ 预留列之后；ext_1..ext_10 必须位于业务列之后、updated_time 之前（SH-DDL-06）",
                    )

        # SH-DDL-07: exactly 1 PK per table
        alter_list = alter_pks.get((schema, tbl), [])
        if not schema:
            alter_list = alter_pks_unqual.get(tbl, alter_list)
        total_pks = len(inline_or_table_pks) + len(alter_list)
        if total_pks != 1:
            add_finding(
                violations,
                "SH-DDL-07",
                "error",
                tbl_line,
                f"表 {raw_table} 主键数量为 {total_pks}，每表必须有且仅有 1 个主键（SH-DDL-07）",
            )

        # SH-DDL-08: COMMENT ON TABLE and COMMENT ON COLUMN
        has_tbl_comment = (
            table_comments.get((schema, tbl), False)
            if schema
            else table_comments_unqual.get(tbl, False)
        )
        if not has_tbl_comment:
            add_finding(
                violations,
                "SH-DDL-08",
                "error",
                tbl_line,
                f"表 {raw_table} 缺少 COMMENT ON TABLE（SH-DDL-08）",
            )
        for col_name, _, ln in cols:
            col_l = col_name.lower()
            has_col_comment = (
                column_comments.get((schema, tbl, col_l), False)
                if schema
                else column_comments_unqual.get((tbl, col_l), False)
            )
            if not has_col_comment:
                add_finding(
                    violations,
                    "SH-DDL-08",
                    "error",
                    ln,
                    f"列 {raw_table}.{col_name} 缺少 COMMENT ON COLUMN（SH-DDL-08）",
                )

        col_set = {c.lower() for c, _, _ in cols}
        parsed_tables[(schema, tbl)] = (col_set, tbl_line)
        parsed_tables_unqual[tbl] = (col_set, tbl_line)

    # SH-DDL-10: compare against function spec if provided
    if isinstance(spec, dict):
        spec_tbl = str(spec.get("target_table", "")).strip()
        if spec_tbl:
            s_schema, s_tbl = split_qualified(spec_tbl)
            found = parsed_tables.get((s_schema, s_tbl)) if s_schema else None
            if found is None:
                found = parsed_tables_unqual.get(s_tbl)
            if found is None:
                add_finding(
                    violations,
                    "SH-DDL-10",
                    "error",
                    1,
                    f"DDL 中未找到 spec 指定的目标表 {spec_tbl}（SH-DDL-10）",
                )
            else:
                defined_cols, defined_line = found
                for col in spec.get("insert_columns", []) or []:
                    col_norm = normalize_ident(str(col)).lower()
                    if col_norm and col_norm not in defined_cols:
                        add_finding(
                            violations,
                            "SH-DDL-10",
                            "error",
                            defined_line,
                            f"DDL 表 {spec_tbl} 缺少 spec.insert_columns 定义的列 {col}（SH-DDL-10）",
                        )

    violations.sort(key=lambda x: (x["line"], x["rule"]))
    warnings.sort(key=lambda x: (x["line"], x["rule"]))
    return violations, warnings


def _find_select_list_end(body_text: str, select_expr_start: int) -> int:
    """Locate end of top-level SELECT list (before FROM/INTO/UNION/INTERSECT/EXCEPT/;)."""
    i = select_expr_start
    n = len(body_text)
    paren = 0
    bracket = 0
    in_single = False
    in_double = False
    in_line = False
    in_block = False

    stop_words = ("FROM", "INTO", "UNION", "INTERSECT", "EXCEPT", "WHERE", "ORDER", "LIMIT")

    while i < n:
        ch = body_text[i]
        nxt = body_text[i + 1] if i + 1 < n else ""
        if in_line:
            if ch == "\n":
                in_line = False
            i += 1
            continue
        if in_block:
            if ch == "*" and nxt == "/":
                in_block = False
                i += 2
                continue
            i += 1
            continue
        if in_single:
            if ch == "'" and nxt == "'":
                i += 2
                continue
            if ch == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            if ch == '"' and nxt == '"':
                i += 2
                continue
            if ch == '"':
                in_double = False
            i += 1
            continue
        if ch == "-" and nxt == "-":
            in_line = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block = True
            i += 2
            continue
        if ch == "'":
            in_single = True
            i += 1
            continue
        if ch == '"':
            in_double = True
            i += 1
            continue
        if ch == "(":
            paren += 1
        elif ch == ")":
            if paren > 0:
                paren -= 1
            else:
                return i
        elif ch == "[":
            bracket += 1
        elif ch == "]":
            if bracket > 0:
                bracket -= 1
        elif paren == 0 and bracket == 0:
            if ch == ";":
                return i
            if (ch.isalpha() or ch == "_") and (i == 0 or not (body_text[i - 1].isalnum() or body_text[i - 1] == "_")):
                for kw in stop_words:
                    end_kw = i + len(kw)
                    if body_text[i:end_kw].upper() == kw and (
                        end_kw >= n or not (body_text[end_kw].isalnum() or body_text[end_kw] == "_")
                    ):
                        return i
        i += 1
    return n


def _skip_ws_comments(text: str, pos: int) -> int:
    n = len(text)
    while pos < n:
        if text[pos].isspace():
            pos += 1
            continue
        if text.startswith("--", pos):
            nl = text.find("\n", pos)
            pos = n if nl == -1 else nl + 1
            continue
        if text.startswith("/*", pos):
            end = text.find("*/", pos + 2)
            pos = n if end == -1 else end + 2
            continue
        break
    return pos


def _skip_cte_block(text: str, pos: int) -> int:
    """Starting at WITH, skip CTE definitions and return index right before main query."""
    m = re.match(r"(?i)WITH(?:\s+RECURSIVE)?\b", text[pos:])
    if not m:
        return pos
    cur = pos + m.end()
    n = len(text)
    while cur < n:
        cur = _skip_ws_comments(text, cur)
        # Skip CTE name and optional (col1, col2)
        name_m = re.match(r'(?:"[^"]+"|[A-Za-z_][\w$]*)', text[cur:])
        if not name_m:
            return cur
        cur = _skip_ws_comments(text, cur + name_m.end())
        if cur < n and text[cur] == "(":
            end_cols = matching_paren_end(text, cur)
            if end_cols == -1:
                return cur
            cur = _skip_ws_comments(text, end_cols + 1)
        as_m = re.match(r"(?i)AS(?:\s+(?:NOT\s+)?MATERIALIZED)?\b", text[cur:])
        if not as_m:
            return cur
        cur = _skip_ws_comments(text, cur + as_m.end())
        if cur >= n or text[cur] != "(":
            return cur
        end_cte = matching_paren_end(text, cur)
        if end_cte == -1:
            return cur
        cur = _skip_ws_comments(text, end_cte + 1)
        if cur < n and text[cur] == ",":
            cur += 1
            continue
        break
    return cur


def _extract_insert_targets(
    raw_text: str, code_only: str, base_offset: int
) -> list[tuple[int, str, list[str], int]]:
    """Extract (line_no, raw_table, normalized_cols, close_idx) for INSERT INTO tbl (cols)."""
    insert_pat = re.compile(
        r"(?is)\bINSERT\s+INTO\s+"
        r'((?:"[^"]+"|[A-Za-z_][\w$]*)(?:\s*\.\s*(?:"[^"]+"|[A-Za-z_][\w$]*))?)\s*\('
    )
    results: list[tuple[int, str, list[str], int]] = []
    for m in insert_pat.finditer(code_only):
        open_idx = m.end() - 1
        close_idx = matching_paren_end(raw_text, open_idx)
        if close_idx == -1:
            continue
        cols_raw = raw_text[open_idx + 1 : close_idx]
        cols = [
            normalize_ident(_strip_comments_keep_strings(item)).lower()
            for _, item in split_top_level_commas(cols_raw)
            if _strip_comments_keep_strings(item).strip()
        ]
        results.append(
            (
                line_of(raw_text, m.start()) + base_offset,
                m.group(1).strip(),
                cols,
                close_idx,
            )
        )
    return results


def _check_insert_select_alignment(
    raw_text: str, code_only: str, base_offset: int, violations: list[dict]
) -> None:
    """SH-FN-05: check INSERT INTO tbl (cols) SELECT exprs FROM column count equality."""
    for insert_line, _, cols, close_idx in _extract_insert_targets(
        raw_text, code_only, base_offset
    ):
        pos = _skip_ws_comments(raw_text, close_idx + 1)
        if re.match(r"(?i)WITH\b", raw_text[pos:]):
            pos = _skip_cte_block(raw_text, pos)
            pos = _skip_ws_comments(raw_text, pos)

        sel_m = re.match(r"(?i)SELECT\b", raw_text[pos:])
        if not sel_m:
            continue
        expr_start = _skip_ws_comments(raw_text, pos + sel_m.end())
        if re.match(r"(?i)ALL\b", raw_text[expr_start:]):
            expr_start = _skip_ws_comments(raw_text, expr_start + 3)
        elif re.match(r"(?i)DISTINCT\b", raw_text[expr_start:]):
            expr_start = _skip_ws_comments(raw_text, expr_start + 8)
            if re.match(r"(?i)ON\b", raw_text[expr_start:]):
                on_pos = _skip_ws_comments(raw_text, expr_start + 2)
                if on_pos < len(raw_text) and raw_text[on_pos] == "(":
                    end_on = matching_paren_end(raw_text, on_pos)
                    if end_on != -1:
                        expr_start = _skip_ws_comments(raw_text, end_on + 1)

        expr_end = _find_select_list_end(raw_text, expr_start)
        sel_raw = raw_text[expr_start:expr_end]
        exprs = [
            item
            for _, item in split_top_level_commas(sel_raw)
            if _strip_comments_keep_strings(item).strip()
        ]

        if len(cols) != len(exprs):
            add_finding(
                violations,
                "SH-FN-05",
                "error",
                insert_line,
                f"INSERT 列数（{len(cols)}）与 SELECT 表达式数（{len(exprs)}）不一致（SH-FN-05）",
            )


def _extract_p_flag_zero_branch(body_code: str) -> str:
    """Extract IF p_flag = 0 ... ELSIF/ELSE/END IF block if present."""
    m = re.search(r"(?is)\bIF\s+(?:\(\s*)?p_flag\s*=\s*0\b", body_code)
    if not m:
        return ""
    # Find THEN after condition
    then_m = re.search(r"(?i)\bTHEN\b", body_code[m.end() :])
    if not then_m:
        return ""
    start = m.end() + then_m.end()
    # Track IF / END IF nesting (ignoring CASE ... END)
    pos = start
    depth = 1
    token_pat = re.compile(
        r"(?i)\bEND\s+IF\b|\bELSIF\b|\bELSEIF\b|\bELSE\b|\bIF\b"
    )
    for tok in token_pat.finditer(body_code, pos):
        word = re.sub(r"\s+", " ", tok.group(0).upper())
        if word == "IF":
            depth += 1
        elif word == "END IF":
            depth -= 1
            if depth == 0:
                return body_code[start : tok.start()]
        elif depth == 1 and word in {"ELSIF", "ELSEIF", "ELSE"}:
            return body_code[start : tok.start()]
    return body_code[start:]


def _mask_nested_subqueries_in_slice(slice_code: str) -> str:
    """Blank out parenthesized subqueries starting with SELECT/WITH in code_only slice.

    Each nested SELECT has its own SELECT token scanned independently, so blanking
    `(SELECT ... FROM ... WHERE ...)` prevents inner WHERE predicates from leaking into
    the enclosing SELECT projection check while preserving scalar function args like
    `coalesce(a.ext_1, 0)`.
    """
    out = list(slice_code)
    i = 0
    n = len(slice_code)
    in_double = False
    while i < n:
        ch = slice_code[i]
        nxt = slice_code[i + 1] if i + 1 < n else ""
        if in_double:
            if ch == '"' and nxt == '"':
                i += 2
                continue
            if ch == '"':
                in_double = False
            i += 1
            continue
        if ch == '"':
            in_double = True
            i += 1
            continue
        if ch == "(":
            inner_pos = i + 1
            while inner_pos < n and slice_code[inner_pos].isspace():
                inner_pos += 1
            if re.match(r"(?i)(?:SELECT|WITH)\b", slice_code[inner_pos:]):
                end_paren = matching_paren_end(slice_code, i)
                if end_paren != -1:
                    for k in range(i + 1, end_paren):
                        if out[k] != "\n":
                            out[k] = " "
                    i = end_paren + 1
                    continue
        i += 1
    return "".join(out)


def _check_ext_columns_in_insert_select(
    body_raw: str, body_code: str, body_line_offset: int, violations: list[dict]
) -> None:
    """SH-FN-04: forbid ext_1..ext_10 inside INSERT column lists and SELECT projection lists."""
    seen: set[tuple[int, str]] = set()

    # 1. INSERT INTO tbl (col1, ext_1, ...)
    insert_pat = re.compile(
        r"(?is)\bINSERT\s+INTO\s+"
        r'(?:"[^"]+"|[A-Za-z_][\w$]*)(?:\s*\.\s*(?:"[^"]+"|[A-Za-z_][\w$]*))?\s*\('
    )
    for m in insert_pat.finditer(body_code):
        open_idx = m.end() - 1
        close_idx = matching_paren_end(body_raw, open_idx)
        if close_idx == -1:
            continue
        cols_code = body_code[open_idx + 1 : close_idx]
        for em in EXT_IN_CODE_PATTERN.finditer(cols_code):
            line_no = body_line_offset + line_of(body_raw, open_idx + 1 + em.start())
            key = (line_no, em.group(0).lower())
            if key in seen:
                continue
            seen.add(key)
            add_finding(
                violations,
                "SH-FN-04",
                "error",
                line_no,
                f"预留扩展列 {em.group(0)} 不得进入计算脚本的 INSERT 或 SELECT（SH-FN-04）",
            )

    # 2. SELECT [ALL | DISTINCT [ON (...)]] <projection_list> ...
    for sm in re.finditer(r"(?is)\bSELECT\b", body_code):
        expr_start = _skip_ws_comments(body_raw, sm.end())
        if re.match(r"(?i)ALL\b", body_raw[expr_start:]):
            expr_start = _skip_ws_comments(body_raw, expr_start + 3)
        elif re.match(r"(?i)DISTINCT\b", body_raw[expr_start:]):
            expr_start = _skip_ws_comments(body_raw, expr_start + 8)
            if re.match(r"(?i)ON\b", body_raw[expr_start:]):
                on_pos = _skip_ws_comments(body_raw, expr_start + 2)
                if on_pos < len(body_raw) and body_raw[on_pos] == "(":
                    end_on = matching_paren_end(body_raw, on_pos)
                    if end_on != -1:
                        expr_start = _skip_ws_comments(body_raw, end_on + 1)
        expr_end = _find_select_list_end(body_raw, expr_start)
        if expr_end <= expr_start:
            continue
        proj_code = _mask_nested_subqueries_in_slice(body_code[expr_start:expr_end])
        for em in EXT_IN_CODE_PATTERN.finditer(proj_code):
            line_no = body_line_offset + line_of(body_raw, expr_start + em.start())
            key = (line_no, em.group(0).lower())
            if key in seen:
                continue
            seen.add(key)
            add_finding(
                violations,
                "SH-FN-04",
                "error",
                line_no,
                f"预留扩展列 {em.group(0)} 不得进入计算脚本的 INSERT 或 SELECT（SH-FN-04）",
            )


def _check_single_function(
    full_text: str,
    func_start: int,
    func_end: int,
    *,
    grain: str | None,
    legacy: bool,
    spec: dict | None,
    violations: list[dict],
) -> None:
    segment = full_text[func_start:func_end]
    base_line_offset = full_text[:func_start].count("\n")
    no_comments, code_only = mask_sql(segment)

    sig_match = FUNC_SIG_NAME_PATTERN.search(code_only)
    if sig_match:
        func_name = re.sub(r'\s+|"', "", sig_match.group(1)).lower()
        open_idx = sig_match.end() - 1
        close_idx = matching_paren_end(segment, open_idx)
        signature = code_only[open_idx + 1 : close_idx] if close_idx != -1 else ""
        after_sig_start = close_idx + 1 if close_idx != -1 else sig_match.end()
    else:
        func_name = ""
        signature = ""
        after_sig_start = 0

    body_match = BODY_TAG_PATTERN.search(segment, after_sig_start)
    if body_match:
        header_part_code = code_only[after_sig_start : body_match.start()]
        tag = body_match.group(1)
        body_start = body_match.end()
        closing = segment.find(tag, body_start)
        body_end = closing if closing != -1 else len(segment)
        body_raw = segment[body_start:body_end]
        body_no_comments = no_comments[body_start:body_end]
        body_code = code_only[body_start:body_end]
        body_line_offset = base_line_offset + segment[:body_start].count("\n")
    else:
        header_part_code = code_only[after_sig_start:]
        body_raw = segment
        body_no_comments = no_comments
        body_code = code_only
        body_line_offset = base_line_offset

    # Determine effective grain & legacy flag (CLI overrides spec)
    eff_legacy = legacy
    if not eff_legacy and isinstance(spec, dict):
        if spec.get("legacy") is True or spec.get("return_contract") == "status_code":
            eff_legacy = True

    eff_grain = grain
    if eff_grain is None and isinstance(spec, dict) and spec.get("grain") in ("day96", "day", "month"):
        eff_grain = "month" if spec["grain"] == "month" else "day"
    if eff_grain is None:
        short_name = func_name.rsplit(".", 1)[-1]
        if short_name.endswith("_m") or (
            re.search(r"\btarget_yearmonth\b", body_code, re.IGNORECASE)
            and not re.search(r"\btarget_date\b", body_code, re.IGNORECASE)
        ):
            eff_grain = "month"
        else:
            eff_grain = "day"

    # SH-FN-01: RETURNS smallint / "pg_catalog"."int2" unless --legacy
    if not eff_legacy:
        ret_m = re.search(
            r'(?i)\bRETURNS\s+(?:smallint\b|"?pg_catalog"?\s*\.\s*"?int2"?(?=\s|$|;)|int2\b)',
            header_part_code,
        )
        if ret_m:
            add_finding(
                violations,
                "SH-FN-01",
                "error",
                base_line_offset + line_of(segment, after_sig_start + ret_m.start()),
                "禁止使用 RETURNS smallint / int2（上限 32767 易溢出），须改为 RETURNS integer（SH-FN-01）",
            )

    # SH-FN-02: no generate_series(
    for m in re.finditer(r"(?i)\bgenerate_series\s*\(", body_code):
        add_finding(
            violations,
            "SH-FN-02",
            "error",
            body_line_offset + line_of(body_raw, m.start()),
            "禁止用 generate_series 自造时段骨架，须使用 dim.dim_timeperiod_change（SH-FN-02）",
        )

    # SH-FN-03: timeperiod usage must reference dim.dim_timeperiod_change
    tp_m = re.search(r"(?i)\btimeperiod\b", body_code)
    if tp_m:
        has_dim = bool(
            re.search(
                r'(?i)(?:"dim"|dim)\s*\.\s*(?:"dim_timeperiod_change"|dim_timeperiod_change\b)',
                body_code,
            )
        )
        if not has_dim:
            add_finding(
                violations,
                "SH-FN-03",
                "error",
                body_line_offset + line_of(body_raw, tp_m.start()),
                "使用 timeperiod 时必须关联时段维表 dim.dim_timeperiod_change（SH-FN-03）",
            )

    # SH-FN-04: no ext_1..ext_10 in INSERT / SELECT projection lists
    _check_ext_columns_in_insert_select(body_raw, body_code, body_line_offset, violations)

    # SH-FN-05: INSERT INTO (...) SELECT ... column count equality
    _check_insert_select_alignment(body_raw, body_code, body_line_offset, violations)

    # SH-FN-06: standard p_flag validation unless --legacy
    if not eff_legacy and re.search(r"(?i)\bp_flag\b", signature):
        fn_line = base_line_offset + (line_of(segment, sig_match.start()) if sig_match else 1)
        missing_checks: list[str] = []
        has_pflag_check = bool(
            re.search(
                r"(?is)\bp_flag\b[^;]*(?:IS\s+NULL|NOT\s+IN\s*\(|\bIN\s*\(\s*0\s*,\s*1\s*\)|<>|!=)",
                body_code,
            )
            or re.search(r"(?is)\bELSE\s+RETURN\s+-1\b", body_code)
        )
        if not has_pflag_check:
            missing_checks.append("p_flag 合法性校验")
        if not re.search(
            r"(?is)\bp_lookback_days\s*<\s*0\b|\b0\s*>\s*p_lookback_days\b",
            body_code,
        ):
            missing_checks.append("p_lookback_days < 0 校验")
        if not re.search(r"(?is)\bRETURN\s+-1\b", body_code):
            missing_checks.append("参数异常 RETURN -1")
        if eff_grain == "day":
            has_span = bool(re.search(r"(?:>\s*92\b|>=\s*93\b)", body_code))
            has_22023 = bool(re.search(r"'22023'", body_no_comments))
            if not has_span or not has_22023:
                missing_checks.append("日表跨度 > 92 天抛 ERRCODE = '22023'")
        if missing_checks:
            add_finding(
                violations,
                "SH-FN-06",
                "error",
                fn_line,
                "标准 p_flag 函数缺少参数校验：" + "、".join(missing_checks) + "（SH-FN-06）",
            )

    # SH-FN-07: update_time incremental uses v_changed_dates/v_changed_months + = ANY(...)
    # and forbids min(/max( + BETWEEN on p_flag = 0 unless --legacy
    has_update_time = bool(re.search(r"(?i)\bupdate_time\b", body_code))
    p0_branch = _extract_p_flag_zero_branch(body_code)
    if has_update_time and not eff_legacy:
        has_changed_var = bool(
            re.search(r"(?i)\bv_changed_(?:dates|months)\b", body_code)
        )
        has_any = bool(
            re.search(
                r"(?i)=\s*ANY\s*\(\s*v_changed_(?:dates|months)\b",
                body_code,
            )
        )
        if not has_changed_var or not has_any:
            ut_m = re.search(r"(?i)\bupdate_time\b", body_code)
            add_finding(
                violations,
                "SH-FN-07",
                "error",
                body_line_offset + line_of(body_raw, ut_m.start() if ut_m else 0),
                "按 update_time 增量必须使用 v_changed_dates/v_changed_months 配合 = ANY(...)（SH-FN-07）",
            )
    if p0_branch and not eff_legacy:
        has_minmax = bool(re.search(r"(?i)\b(?:min|max)\s*\(", p0_branch))
        has_between = bool(re.search(r"(?i)\bBETWEEN\b", p0_branch))
        if has_minmax and has_between:
            bm = re.search(r"(?i)\bBETWEEN\b", p0_branch)
            # Find approximate offset in body_code
            add_finding(
                violations,
                "SH-FN-07",
                "error",
                body_line_offset + line_of(body_raw, body_code.find(p0_branch) + (bm.start() if bm else 0)),
                "p_flag = 0 增量分支禁止将稀疏变化集合扩为 min/max + BETWEEN 区间重算（SH-FN-07）",
            )

    # SH-FN-08: target_yearmonth must not compare against YYYY-MM-DD or ::date
    for m in re.finditer(
        r"(?i)\b(?:[a-z_][\w$]*\.)?target_yearmonth\s*::\s*(?:date|timestamp|timestamptz)\b"
        r"|\bto_date\s*\(\s*(?:[a-z_][\w$]*\.)?target_yearmonth\b"
        r"|\bcast\s*\(\s*(?:[a-z_][\w$]*\.)?target_yearmonth\s+AS\s+(?:date|timestamp)\b",
        body_no_comments,
    ):
        add_finding(
            violations,
            "SH-FN-08",
            "error",
            body_line_offset + line_of(body_raw, m.start()),
            "target_yearmonth 禁止转换为 date/timestamp，应保持 YYYY-MM 字符串比较（SH-FN-08）",
        )
    ym_cmp_patterns = (
        r"(?i)\b(?:[a-z_][\w$]*\.)?target_yearmonth\b\s*(?:=|!=|<>|>=|<=|>|<|BETWEEN\b)\s*(?:'\d{4}-\d{2}-\d{2}'|[^;\n]*?::\s*date\b)",
        r"(?i)(?:'\d{4}-\d{2}-\d{2}'|\b[a-z_][\w$]*::\s*date\b)\s*(?:=|!=|<>|>=|<=|>|<)\s*(?:[a-z_][\w$]*\.)?target_yearmonth\b",
    )
    for pat in ym_cmp_patterns:
        for m in re.finditer(pat, body_no_comments):
            add_finding(
                violations,
                "SH-FN-08",
                "error",
                body_line_offset + line_of(body_raw, m.start()),
                "target_yearmonth 禁止与 YYYY-MM-DD 或 ::date 比较（会漏删首月），请使用 YYYY-MM（SH-FN-08）",
            )

    # SH-FN-10 & SH-FN-11: validate against --spec if provided
    if isinstance(spec, dict):
        fn_line = base_line_offset + (line_of(segment, sig_match.start()) if sig_match else 1)
        spec_tbl = str(spec.get("target_table", "")).strip()
        expected_cols = [
            normalize_ident(str(c)).lower()
            for c in (spec.get("insert_columns") or [])
            if str(c).strip()
        ]
        if spec_tbl and expected_cols:
            s_schema, s_tbl = split_qualified(spec_tbl)
            targets = _extract_insert_targets(body_raw, body_code, body_line_offset)
            matched_targets = []
            for ins_line, raw_tbl, actual_cols, _ in targets:
                i_schema, i_tbl = split_qualified(raw_tbl)
                if i_tbl == s_tbl and (not i_schema or not s_schema or i_schema == s_schema):
                    matched_targets.append((ins_line, actual_cols))
            if not matched_targets:
                add_finding(
                    violations,
                    "SH-FN-10",
                    "error",
                    fn_line,
                    f"计算脚本未找到写入目标表 {spec_tbl} 的显式列清单 INSERT 语句（SH-FN-10）",
                )
            else:
                for ins_line, actual_cols in matched_targets:
                    if actual_cols != expected_cols:
                        missing_cols = [c for c in expected_cols if c not in actual_cols]
                        extra_cols = [c for c in actual_cols if c not in expected_cols]
                        details: list[str] = []
                        if missing_cols:
                            details.append("缺少列 " + ",".join(missing_cols))
                        if extra_cols:
                            details.append("多出列 " + ",".join(extra_cols))
                        if not details:
                            details.append("列顺序与 spec.insert_columns 不一致")
                        add_finding(
                            violations,
                            "SH-FN-10",
                            "error",
                            ins_line,
                            f"INSERT INTO {spec_tbl} 列清单与 spec 不一致：{'；'.join(details)}（SH-FN-10）",
                        )

        for src in spec.get("sources") or []:
            if not isinstance(src, dict) or src.get("role") != "driver":
                continue
            src_tbl = str(src.get("table", "")).strip()
            if not src_tbl:
                continue
            src_schema, src_short = split_qualified(src_tbl)
            if src_schema:
                src_pat = rf'(?i)(?:"?{re.escape(src_schema)}"?\s*\.\s*)?"?{re.escape(src_short)}"?\b'
            else:
                src_pat = rf'(?i)"?{re.escape(src_short)}"?\b'
            if not re.search(src_pat, body_code):
                add_finding(
                    violations,
                    "SH-FN-11",
                    "error",
                    fn_line,
                    f"函数体未引用 spec 声明的驱动源表 {src_tbl}（SH-FN-11）",
                )


def check_func(
    text: str,
    *,
    grain: str | None = None,
    legacy: bool = False,
    spec: dict | None = None,
) -> tuple[list[dict], list[dict]]:
    violations: list[dict] = []
    warnings: list[dict] = []

    matches = list(CREATE_FUNC_PATTERN.finditer(text))
    if not matches:
        _check_single_function(
            text, 0, len(text), grain=grain, legacy=legacy, spec=spec, violations=violations
        )
    else:
        for idx, m in enumerate(matches):
            start = m.start()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            _check_single_function(
                text,
                start,
                end,
                grain=grain,
                legacy=legacy,
                spec=spec,
                violations=violations,
            )

    violations.sort(key=lambda x: (x["line"], x["rule"]))
    return violations, warnings


def check_spec(data: object) -> tuple[list[dict], list[dict]]:
    violations: list[dict] = []
    warnings: list[dict] = []

    if not isinstance(data, dict):
        add_finding(
            violations,
            "SH-SPEC-01",
            "error",
            1,
            "函数规格 Spec 顶层必须是 JSON 对象（SH-SPEC-01）",
        )
        return violations, warnings

    required_keys = (
        "target_table",
        "function_name",
        "grain",
        "business_keys",
        "insert_columns",
        "sources",
    )
    missing_keys = [
        k for k in required_keys if k not in data or data[k] in (None, "", [])
    ]
    if missing_keys:
        add_finding(
            violations,
            "SH-SPEC-01",
            "error",
            1,
            "Spec 缺少必备字段或字段为空：" + "、".join(missing_keys) + "（SH-SPEC-01）",
        )

    grain = data.get("grain")
    if grain is not None and grain not in ("day96", "day", "month"):
        add_finding(
            violations,
            "SH-SPEC-01",
            "error",
            1,
            f"Spec grain 非法：{grain!r}；仅允许 day96 / day / month（SH-SPEC-01）",
        )

    mode = data.get("mode")
    if mode is not None and mode not in ("generate", "rewrite"):
        add_finding(
            violations,
            "SH-SPEC-01",
            "error",
            1,
            f"Spec mode 非法：{mode!r}；仅允许 generate / rewrite（SH-SPEC-01）",
        )

    ret_contract = data.get("return_contract")
    if ret_contract is not None and ret_contract not in ("row_count", "status_code"):
        add_finding(
            violations,
            "SH-SPEC-01",
            "error",
            1,
            f"Spec return_contract 非法：{ret_contract!r}；仅允许 row_count / status_code（SH-SPEC-01）",
        )

    inc_mode = data.get("increment_mode", "update_time")
    if inc_mode not in ("update_time", "date_slice", "full"):
        add_finding(
            violations,
            "SH-SPEC-01",
            "error",
            1,
            f"Spec increment_mode 非法：{inc_mode!r}；仅允许 update_time / date_slice / full（SH-SPEC-01）",
        )

    # SH-SPEC-02: schema-qualified target_table (no _d24) & function_name
    target_table = data.get("target_table")
    if isinstance(target_table, str) and target_table.strip():
        t_schema, t_short = split_qualified(target_table)
        if not t_schema or not t_short:
            add_finding(
                violations,
                "SH-SPEC-02",
                "error",
                1,
                f"Spec target_table 必须使用 schema 全限定名：{target_table!r}（SH-SPEC-02）",
            )
        if t_short.endswith("_d24"):
            add_finding(
                violations,
                "SH-SPEC-02",
                "error",
                1,
                f"Spec target_table 禁止使用 _d24 表：{target_table!r}（SH-SPEC-02）",
            )

    function_name = data.get("function_name")
    if isinstance(function_name, str) and function_name.strip():
        f_schema, f_short = split_qualified(function_name)
        if not f_schema or not f_short:
            add_finding(
                violations,
                "SH-SPEC-02",
                "error",
                1,
                f"Spec function_name 必须使用 schema 全限定名：{function_name!r}（SH-SPEC-02）",
            )

    # SH-SPEC-03 & SH-SPEC-04: columns checks
    raw_insert = data.get("insert_columns")
    raw_keys = data.get("business_keys")
    raw_metrics = data.get("metric_columns")

    insert_norm: list[str] = []
    if isinstance(raw_insert, list):
        seen_ins: set[str] = set()
        for col in raw_insert:
            if not isinstance(col, str) or not col.strip():
                add_finding(
                    violations,
                    "SH-SPEC-04",
                    "error",
                    1,
                    "Spec insert_columns 中存在空列名或非字符串项（SH-SPEC-04）",
                )
                continue
            cn = normalize_ident(col).lower()
            if EXT_ANY_PATTERN.match(cn):
                add_finding(
                    violations,
                    "SH-SPEC-03",
                    "error",
                    1,
                    f"Spec insert_columns 禁止包含预留扩展列 {col!r}（SH-SPEC-03）",
                )
            if cn in seen_ins:
                add_finding(
                    violations,
                    "SH-SPEC-04",
                    "error",
                    1,
                    f"Spec insert_columns 存在重复列名：{col!r}（SH-SPEC-04）",
                )
            seen_ins.add(cn)
            insert_norm.append(cn)
    elif raw_insert is not None:
        add_finding(
            violations,
            "SH-SPEC-01",
            "error",
            1,
            "Spec insert_columns 必须是字符串列表（SH-SPEC-01）",
        )

    keys_norm: list[str] = []
    if isinstance(raw_keys, list):
        for col in raw_keys:
            if not isinstance(col, str) or not col.strip():
                add_finding(
                    violations,
                    "SH-SPEC-04",
                    "error",
                    1,
                    "Spec business_keys 中存在空列名或非字符串项（SH-SPEC-04）",
                )
                continue
            cn = normalize_ident(col).lower()
            if EXT_ANY_PATTERN.match(cn):
                add_finding(
                    violations,
                    "SH-SPEC-03",
                    "error",
                    1,
                    f"Spec business_keys 禁止包含预留扩展列 {col!r}（SH-SPEC-03）",
                )
            keys_norm.append(cn)
    elif raw_keys is not None:
        add_finding(
            violations,
            "SH-SPEC-01",
            "error",
            1,
            "Spec business_keys 必须是字符串列表（SH-SPEC-01）",
        )

    if isinstance(raw_metrics, list):
        for col in raw_metrics:
            if isinstance(col, str) and EXT_ANY_PATTERN.match(normalize_ident(col).lower()):
                add_finding(
                    violations,
                    "SH-SPEC-03",
                    "error",
                    1,
                    f"Spec metric_columns 禁止包含预留扩展列 {col!r}（SH-SPEC-03）",
                )

    insert_set = set(insert_norm)
    keys_set = set(keys_norm)
    if insert_set and keys_set:
        missing_in_insert = [k for k in keys_norm if k not in insert_set]
        if missing_in_insert:
            add_finding(
                violations,
                "SH-SPEC-04",
                "error",
                1,
                "Spec business_keys 必须是 insert_columns 的子集，缺少："
                + "、".join(missing_in_insert)
                + "（SH-SPEC-04）",
            )
    if grain == "day96":
        if "timeperiod" not in keys_set or "timeperiod" not in insert_set:
            add_finding(
                violations,
                "SH-SPEC-04",
                "error",
                1,
                "grain 为 day96 时，timeperiod 必须同时出现在 business_keys 与 insert_columns 中（SH-SPEC-04）",
            )

    # SH-SPEC-05: sources validation & INC-15 driver/incremental alignment
    sources = data.get("sources")
    if isinstance(sources, list) and sources:
        has_driver = False
        for idx, src in enumerate(sources, start=1):
            if not isinstance(src, dict):
                add_finding(
                    violations,
                    "SH-SPEC-05",
                    "error",
                    1,
                    f"Spec sources[{idx}] 必须是对象（SH-SPEC-05）",
                )
                continue
            tbl = str(src.get("table", "")).strip()
            role = src.get("role")
            if not tbl:
                add_finding(
                    violations,
                    "SH-SPEC-05",
                    "error",
                    1,
                    f"Spec sources[{idx}] 缺少 table（SH-SPEC-05）",
                )
            if role not in ("driver", "supplement"):
                add_finding(
                    violations,
                    "SH-SPEC-05",
                    "error",
                    1,
                    f"Spec sources[{idx}] role={role!r} 非法，仅允许 driver / supplement（SH-SPEC-05）",
                )
                continue
            if role == "driver":
                has_driver = True
                if inc_mode == "update_time" and src.get("incremental") is not True:
                    add_finding(
                        violations,
                        "SH-SPEC-05",
                        "error",
                        1,
                        f"update_time 增量下驱动源 {tbl or f'#{idx}'} 必须设置 incremental: true（满足 INC-15）（SH-SPEC-05）",
                    )
        if not has_driver:
            add_finding(
                violations,
                "SH-SPEC-05",
                "error",
                1,
                "Spec sources 必须至少包含一个 role 为 driver 的主驱动源（SH-SPEC-05）",
            )
    elif sources is not None:
        add_finding(
            violations,
            "SH-SPEC-05",
            "error",
            1,
            "Spec sources 必须是非空数组（SH-SPEC-05）",
        )

    violations.sort(key=lambda x: (x["line"], x["rule"]))
    return violations, warnings


def check_csv(raw_bytes: bytes) -> tuple[list[dict], list[dict]]:
    violations: list[dict] = []
    warnings: list[dict] = []

    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        add_finding(
            violations,
            "SH-CSV-01",
            "error",
            1,
            "CSV 文件含 UTF-8 BOM，必须使用无 BOM 的 UTF-8（SH-CSV-01）",
        )
        raw_bytes = raw_bytes[3:]

    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        add_finding(
            violations,
            "SH-CSV-01",
            "error",
            1,
            f"CSV 文件不是合法 UTF-8 编码：{exc}（SH-CSV-01）",
        )
        return violations, warnings

    reader = csv.reader(io.StringIO(text, newline=""))
    rows = list(reader)
    if not rows:
        add_finding(
            violations,
            "SH-CSV-02",
            "error",
            1,
            "CSV 文件为空，缺少 12 列标准表头（SH-CSV-02）",
        )
        return violations, warnings

    header = rows[0]
    if header != CSV_HEADER:
        add_finding(
            violations,
            "SH-CSV-02",
            "error",
            1,
            f"CSV 表头不符合 12 列契约，期望 {','.join(CSV_HEADER)}，实际 {','.join(header)}（SH-CSV-02）",
        )

    for line_no, row in enumerate(rows[1:], start=2):
        if len(row) != 12:
            add_finding(
                violations,
                "SH-CSV-03",
                "error",
                line_no,
                f"第 {line_no} 行列数为 {len(row)}，必须严格为 12 列（SH-CSV-03）",
            )
            continue
        if not row[0].strip() or not row[4].strip():
            add_finding(
                violations,
                "SH-CSV-03",
                "error",
                line_no,
                f"第 {line_no} 行「目标表」或「中文名称（BI看）」为空（SH-CSV-03）",
            )
        en_name = row[3].strip()
        if EXT_COL_PATTERN.match(en_name) or EXT_IN_CODE_PATTERN.search(en_name):
            add_finding(
                violations,
                "SH-CSV-04",
                "error",
                line_no,
                f"第 {line_no} 行英文名称包含预留扩展字段 {en_name!r}，不得进入业务字段对照（SH-CSV-04）",
            )

    violations.sort(key=lambda x: (x["line"], x["rule"]))
    return violations, warnings


NEGATED_CLAIM_CUE = re.compile(
    r"(?:不得写|不能写|不可写|勿写|不要写|未|不能|不得|禁止|尚未)\s*[「\"']?$"
)


def _has_positive_static_claim(text: str) -> int | None:
    """Return 1-based line number of a positive claim of passing static check, else None."""
    claim_pat = re.compile(r"已完成静态检查|静态检查通过")
    for line_no, line in enumerate(text.splitlines(), start=1):
        for m in claim_pat.finditer(line):
            prefix = line[: m.start()]
            # Split at Chinese/ASCII sentence separators to scope negation locally
            clause_prefix = re.split(r"[，。；,;：:]", prefix)[-1]
            if NEGATED_CLAIM_CUE.search(clause_prefix):
                continue
            return line_no
    return None


def check_report(text: str) -> tuple[list[dict], list[dict]]:
    violations: list[dict] = []
    warnings: list[dict] = []

    # SH-RPT-01: must contain artifacts, gates, open_questions, next
    required_tokens = ("artifacts", "gates", "open_questions", "next")
    for tok in required_tokens:
        if not re.search(rf"(?i)\b{re.escape(tok)}\b", text):
            add_finding(
                violations,
                "SH-RPT-01",
                "error",
                1,
                f"交付/验收报告缺少必备段落或键 `{tok}`（SH-RPT-01）",
            )

    # SH-RPT-02: if claiming 已完成静态检查 or 静态检查通过, require JSON tokens + compile check
    claim_line = _has_positive_static_claim(text)
    if claim_line is not None:
        has_ok = bool(re.search(r'"ok"\s*:', text))
        has_viol = bool(re.search(r'"(?:violations|violation_count)"\s*:', text))
        has_compile = bool(
            re.search(r"\bROLLBACK\b", text, re.IGNORECASE) or "编译验证" in text
        )
        missing: list[str] = []
        if not has_ok:
            missing.append('check_sql_output.py JSON 字段 "ok"')
        if not has_viol:
            missing.append('check_sql_output.py JSON 字段 "violations"/"violation_count"')
        if not has_compile:
            missing.append("数据库编译验证证据（ROLLBACK/编译验证）")
        if missing:
            add_finding(
                violations,
                "SH-RPT-02",
                "error",
                claim_line,
                "报告声称静态检查已完成/通过，但缺少留痕证据："
                + "、".join(missing)
                + "（SH-RPT-02）",
            )

    violations.sort(key=lambda x: (x["line"], x["rule"]))
    return violations, warnings


# 已在规范与检查器源头消除重叠（ext_1..ext_10 仅由 SH-FN-04 承担；INC-07 仅由 pg-function-craft 承担）。
# 保留 deduplicated 输出字段以维持 JSON 结构稳定（当前固定返回 []）。
OVERLAP_RULES: dict[str, str] = {}


BOOTSTRAP_REQUIRED = (
    ("README.md", "README.md", "根 README"),
    ("参考资料/指标字段来源对照表.csv", "参考资料/指标字段来源对照表.csv", "字段对照 CSV"),
    ("DDL/*建表语句.sql", "DDL/<省份><业态><N>表_建表语句.sql", "建表 DDL"),
    ("计算脚本/*.sql", "计算脚本/<目标表名>.sql", "计算函数"),
    ("复核验证/*_平台补录与变更记录.md", "复核验证/<省份业态>_平台补录与变更记录.md", "平台补录记录"),
    ("复核验证/*_平台原始DDL.sql", "复核验证/<省份业态>_平台原始DDL.sql", "平台原始 DDL"),
    ("复核验证/*_spec.json", "复核验证/<目标表名>_spec.json", "函数规格 Spec"),
    ("复核验证/*_待人工确认清单.md", "复核验证/<省份业态>_待人工确认清单.md", "待确认清单"),
)

BOOTSTRAP_OPTIONAL = ("参考资料/*.xlsx",)

BOOTSTRAP_FULL_ONLY = (
    "执行与验收",
    "验收报告",
    "评审报告",
    "血缘登记",
    "源表登记与同步清单",
)


def check_bootstrap(root: pathlib.Path) -> tuple[list[dict], list[dict]]:
    """校验 bootstrap 模式的固定产物集合（只看文件名与 README 文本，不解析 SQL）。"""
    violations: list[dict] = []
    warnings: list[dict] = []

    files = sorted(
        p
        for p in root.rglob("*")
        if p.is_file() and not any(part.startswith(".") for part in p.relative_to(root).parts)
    )
    rels = [p.relative_to(root).as_posix() for p in files]

    matched: set[str] = set()
    for pattern, display, label in BOOTSTRAP_REQUIRED:
        hits = [r for r in rels if pathlib.PurePosixPath(r).match(pattern) and r.count("/") == pattern.count("/")]
        if not hits:
            add_finding(
                violations,
                "SH-BOOT-01",
                "error",
                1,
                f"缺少 bootstrap 必备产物：{label}（{display}）（SH-BOOT-01）",
            )
        matched.update(hits)
    for pattern in BOOTSTRAP_OPTIONAL:
        matched.update(
            r for r in rels if pathlib.PurePosixPath(r).match(pattern) and r.count("/") == pattern.count("/")
        )

    for r in rels:
        if r in matched:
            continue
        full_only = next((tok for tok in BOOTSTRAP_FULL_ONLY if tok in r), None)
        if full_only:
            msg = f"bootstrap 模式不应产出 full 阶段文件：{r}（命中「{full_only}」）（SH-BOOT-02）"
        else:
            msg = f"bootstrap 固定清单之外的文件：{r}（SH-BOOT-02）"
        add_finding(violations, "SH-BOOT-02", "error", 1, msg)

    spec_names = {
        pathlib.PurePosixPath(r).name[: -len("_spec.json")]
        for r in rels
        if r.startswith("复核验证/") and r.endswith("_spec.json") and r.count("/") == 1
    }
    func_names = {
        pathlib.PurePosixPath(r).stem
        for r in rels
        if r.startswith("计算脚本/") and r.endswith(".sql") and r.count("/") == 1
    }
    for name in sorted(spec_names - func_names):
        add_finding(
            violations,
            "SH-BOOT-03",
            "error",
            1,
            f"Spec {name}_spec.json 没有对应的计算脚本/{name}.sql（SH-BOOT-03）",
        )
    for name in sorted(func_names - spec_names):
        add_finding(
            violations,
            "SH-BOOT-03",
            "error",
            1,
            f"计算脚本/{name}.sql 没有对应的复核验证/{name}_spec.json（SH-BOOT-03）",
        )

    readme = root / "README.md"
    if readme.is_file():
        try:
            text = readme.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            add_finding(violations, "SH-BOOT-04", "error", 1, f"README.md 读取失败：{exc}（SH-BOOT-04）")
        else:
            if not re.search(r"(?i)\bbootstrap\b", text):
                add_finding(
                    violations,
                    "SH-BOOT-04",
                    "error",
                    1,
                    "README.md 未写明当前模式 `bootstrap`（SH-BOOT-04）",
                )
            for tok in ("artifacts", "gates", "open_questions", "next"):
                if not re.search(rf"(?i)\b{re.escape(tok)}\b", text):
                    add_finding(
                        violations,
                        "SH-BOOT-04",
                        "error",
                        1,
                        f"README.md 缺少汇报键 `{tok}`（SH-BOOT-04）",
                    )

    return violations, warnings


def _default_pg_checker_path() -> pathlib.Path:
    return (
        pathlib.Path(__file__).resolve().parents[2]
        / "pg-function-craft"
        / "scripts"
        / "check_sql_output.py"
    )


def _load_pg_checker(path: pathlib.Path):
    spec = importlib.util.spec_from_file_location("pgfc_check_sql_embedded", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载检查器：{path}")
    module = importlib.util.module_from_spec(spec)
    prev = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = prev
    if not hasattr(module, "check_sql"):
        raise ImportError(f"检查器缺少 check_sql 接口：{path}")
    return module


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass

    parser = argparse.ArgumentParser(
        description="申能 DWD 产物离线静态检查（不连数据库、不访问网络）。"
    )
    parser.add_argument(
        "--kind",
        required=True,
        choices=("ddl", "func", "csv", "report", "spec", "bootstrap"),
        help="检查产物类型：ddl | func | csv | report | spec | bootstrap（bootstrap 传省份业态目录）",
    )
    parser.add_argument(
        "--grain",
        choices=("day", "month"),
        default=None,
        help="仅用于 func：指定日表或月表粒度；未指定时优先按 spec / 函数名自动推断",
    )
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="仅用于 func：按既有函数契约豁免 smallint/RETURN 0/min-max 等历史约束",
    )
    parser.add_argument(
        "--spec",
        default=None,
        help="可选：函数规格 JSON 路径，供 ddl / func 校验目标表、列清单与驱动源",
    )
    parser.add_argument(
        "--with-pg-checker",
        action="store_true",
        help="仅用于 func：联合调用同级 pg-function-craft/scripts/check_sql_output.py 并合并双层结果",
    )
    parser.add_argument(
        "--pg-checker",
        default=None,
        help="显式指定 check_sql_output.py 路径（隐含启用 --with-pg-checker）",
    )
    parser.add_argument(
        "--comma-style",
        choices=("leading", "trailing"),
        default="leading",
        help="透传给 pg-function-craft 检查器的逗号约定：leading（默认）或 trailing",
    )
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    parser.add_argument("path", help="待检查的文件路径（--kind bootstrap 时为省份业态目录）")
    args = parser.parse_args(argv)

    target = pathlib.Path(args.path)
    if args.kind == "bootstrap":
        if not target.is_dir():
            print(f"读取产物失败：目录不存在或不是目录：{target}", file=sys.stderr)
            return 2
    elif not target.is_file():
        print(f"读取产物失败：文件不存在或不是常规文件：{target}", file=sys.stderr)
        return 2

    spec_data: dict | None = None
    if args.spec:
        spec_path = pathlib.Path(args.spec)
        if not spec_path.is_file():
            print(f"读取 Spec 文件失败：文件不存在或不是常规文件：{spec_path}", file=sys.stderr)
            return 2
        try:
            loaded_spec = json.loads(spec_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            print(f"读取或解析 Spec 文件失败：{exc}", file=sys.stderr)
            return 2
        if not isinstance(loaded_spec, dict):
            print("Spec 文件顶层必须是 JSON 对象", file=sys.stderr)
            return 2
        spec_data = loaded_spec

    use_pg_checker = bool(args.with_pg_checker or args.pg_checker)
    pg_checker_path: pathlib.Path | None = None
    pg_module = None
    if use_pg_checker and args.kind == "func":
        pg_checker_path = (
            pathlib.Path(args.pg_checker)
            if args.pg_checker
            else _default_pg_checker_path()
        )
        if not pg_checker_path.is_file():
            print(
                f"未找到 pg-function-craft 检查器：{pg_checker_path}；"
                "请先安装 pg-function-craft 或通过 --pg-checker 指定路径",
                file=sys.stderr,
            )
            return 2
        try:
            pg_module = _load_pg_checker(pg_checker_path)
        except Exception as exc:
            print(f"加载 pg-function-craft 检查器失败：{exc}", file=sys.stderr)
            return 2

    text_for_pg = ""
    try:
        if args.kind == "bootstrap":
            violations, warnings = check_bootstrap(target)
        elif args.kind == "csv":
            raw_bytes = target.read_bytes()
            violations, warnings = check_csv(raw_bytes)
        elif args.kind == "spec":
            raw_spec = json.loads(target.read_text(encoding="utf-8-sig"))
            violations, warnings = check_spec(raw_spec)
        else:
            text = target.read_text(encoding="utf-8")
            text_for_pg = text
            if args.kind == "ddl":
                violations, warnings = check_ddl(text, spec=spec_data)
            elif args.kind == "func":
                violations, warnings = check_func(
                    text, grain=args.grain, legacy=args.legacy, spec=spec_data
                )
            else:
                violations, warnings = check_report(text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"读取产物失败：{exc}", file=sys.stderr)
        return 2

    deduplicated: list[dict] = []
    pg_violations: list[dict] = []
    if use_pg_checker and args.kind == "func" and pg_module is not None:
        sh_rules_present = {v["rule"] for v in violations}
        for v in violations:
            v["source"] = "shenergy-dwd-development"
        pg_violations = pg_module.check_sql(text_for_pg, comma_style=args.comma_style)
        for item in pg_violations:
            pg_rule = item.get("rule", "")
            covered_by = OVERLAP_RULES.get(pg_rule)
            if covered_by and covered_by in sh_rules_present:
                deduplicated.append(
                    {
                        "rule": pg_rule,
                        "covered_by": covered_by,
                        "line": item.get("line", 1),
                        "message": item.get("message", ""),
                    }
                )
                continue
            violations.append(
                {
                    "rule": pg_rule,
                    "level": "error",
                    "line": item.get("line", 1),
                    "message": item.get("message", ""),
                    "source": "pg-function-craft",
                }
            )
        violations.sort(key=lambda x: (x["line"], x["rule"]))

    result: dict = {
        "ok": not violations,
        "kind": args.kind,
        "database_connected": False,
        "violation_count": len(violations),
        "violations": violations,
        "warning_count": len(warnings),
        "warnings": warnings,
    }
    if use_pg_checker and args.kind == "func":
        result["pg_checker_ran"] = True
        result["pg_checker_path"] = str(pg_checker_path)
        result["pg_violation_count"] = len(pg_violations)
        result["deduplicated"] = deduplicated

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"检查产物（{args.kind}）：{target}")
        for w in warnings:
            print(f"[WARN][{w['rule']}] 第 {w['line']} 行：{w['message']}")
        for v in violations:
            print(f"[FAIL][{v['rule']}] 第 {v['line']} 行：{v['message']}")
        print("结果：" + ("通过" if not violations else f"失败（{len(violations)} 项错误）"))

    return 0 if not violations else 1


if __name__ == "__main__":
    sys.exit(main())
