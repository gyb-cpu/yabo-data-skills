#!/usr/bin/env python3
"""pg-function-craft SQL 输出检查器。

只使用 Python 标准库；不连接数据库、不访问网络、不执行 SQL。
按 references/06、07、08、09、11 与固定风格检查一份 SQL 文本：

  F-06     关键字未大写
  F-12     前置逗号仓库出现尾逗号
  F-21     AS 函数体之后缺少中文八字段头或字段为空
  F-32     前置逗号续行缩进未与首项同列
  F-33     连续空行超过 1 个
  F-34     空行或空注释切断列表项
  F-35     分号单独成行
  F-36     *name 未使用 schema 限定或与 CREATE 名称不一致
  F-37     *input 未说明全部参数的业务含义
  F-38     *output 与函数返回行为不一致
  F-39     增量函数未说明水位线/回看/半开区间
  F-40     *CreateDate / *UpdateDate 格式错误
  F-41     函数头分隔线缺失
  STYLE-01 函数名未使用 f_ 前缀
  PERF-29  过滤列被套 ::date / ::timestamp
  INC-05   使用未来哨兵日期代替 NULL 判断
  INC-07   增量业务日期推导过滤了 deleted = 0 / is_deleted = 0
  REV-S01  动态 SQL EXECUTE 拼接值
  REV-S02  EXECUTE 所在函数内 format() 使用 %s
  REV-S03  SECURITY DEFINER 函数未固定 search_path
  REV-S04  SECURITY DEFINER 函数 search_path 配置不安全
  REV-C01  WHEN OTHERS THEN NULL 吞掉异常

用法：
  python scripts/check_sql_output.py --json <file.sql>

JSON 输出：
  {"ok": bool, "database_connected": false, "violation_count": int,
   "violations": [{"rule": "F-12", "line": 12, "message": "..."}],
   "command": [...]}

退出码：0 = 无违规；1 = 有违规；2 = 用法或读取错误。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

HEADER_FIELDS = (
    "name",
    "function",
    "input",
    "output",
    "increment",
    "author",
    "CreateDate",
    "UpdateDate",
)

# F-06：需要大写的 SQL / PL/pgSQL 关键字（类型与内置函数不在其中）。
KEYWORDS = (
    "select",
    "from",
    "where",
    "join",
    "on",
    "group",
    "order",
    "by",
    "with",
    "as",
    "and",
    "or",
    "not",
    "null",
    "true",
    "false",
    "case",
    "when",
    "then",
    "else",
    "end",
    "insert",
    "update",
    "delete",
    "values",
    "into",
    "create",
    "replace",
    "function",
    "procedure",
    "returns",
    "return",
    "language",
    "declare",
    "begin",
    "exception",
    "if",
    "elsif",
    "loop",
    "raise",
    "execute",
    "perform",
    "using",
    "distinct",
    "having",
    "limit",
    "union",
    "intersect",
    "except",
    "set",
    "grant",
    "revoke",
    "call",
    "is",
    "in",
    "exists",
    "between",
    "like",
    "ilike",
    "primary",
    "foreign",
    "references",
    "constraint",
    "default",
    "trigger",
    "before",
    "after",
    "instead",
    "for",
    "each",
    "row",
    "statement",
)

KEYWORD_PATTERN = re.compile(
    r"\b(" + "|".join(KEYWORDS) + r")\b", re.IGNORECASE
)

DOUBLE_QUOTED_PATTERN = re.compile(r'"(?:""|[^"])*"')
RETURNS_BEFORE_TRIGGER = re.compile(r"\bRETURNS\s+$", re.IGNORECASE)

CREATE_PATTERN = re.compile(
    r"(?im)^\s*CREATE\s+(?:OR\s+REPLACE\s+)?(FUNCTION|PROCEDURE)\b"
)

FUNCTION_NAME_PATTERN = re.compile(
    r"(?is)\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:FUNCTION|PROCEDURE)\s+"
    r"(['\"]?[A-Za-z_][\w$]*['\"]?(?:\.['\"]?[A-Za-z_][\w$]*['\"]?)?)\s*\("
)

COLUMN_CAST_PATTERN = re.compile(
    r"(?i)\b([a-z_][\w$]*(?:\.[a-z_][\w$]*)?)\s*::\s*(date|timestamp|timestamptz)\b"
)

EXEMPT_CAST_LEFT = frozenset({
    "null",
    "current_date",
    "current_timestamp",
    "localtimestamp",
    "localtime",
    "true",
    "false",
})

COMPARISON_OP_PATTERN = re.compile(
    r"(?i)(?:<>|!=|<=|>=|<|>|(?<![:<>!])=(?!>)|\bBETWEEN\b|\bIN\b|\bIS\b)"
)

CLAUSE_TOKEN_PATTERN = re.compile(
    r"""(?ix)
    "(?:""|[^"])*"
    | [();]
    | \b(?:
        WHERE|HAVING|ON
        |SELECT|FROM|GROUP|ORDER|LIMIT|OFFSET|UNION|INTERSECT|EXCEPT
        |RETURNING|VALUES|INTO|SET|JOIN|LEFT|RIGHT|FULL|INNER|CROSS
        |INSERT|UPDATE|DELETE|BEGIN|DECLARE|END|IF|ELSIF|ELSE|THEN|LOOP
        |RETURN|RAISE|PERFORM|EXECUTE|FETCH|FOR|WITH
      )\b
    """
)

NON_FILTER_ON_FOLLOWERS = frozenset({
    "COMMIT",
    "CONFLICT",
    "DELETE",
    "UPDATE",
    "INSERT",
    "TRUNCATE",
    "NULL",
    "ALL",
    "ANY",
    "MASTER",
    "INITPLAN",
    "TABLE",
    "COLUMN",
    "FUNCTION",
    "PROCEDURE",
    "SCHEMA",
    "DATABASE",
})

FILTER_EXIT_KEYWORDS = frozenset({
    "SELECT",
    "FROM",
    "GROUP",
    "ORDER",
    "LIMIT",
    "OFFSET",
    "UNION",
    "INTERSECT",
    "EXCEPT",
    "RETURNING",
    "VALUES",
    "INTO",
    "SET",
    "JOIN",
    "LEFT",
    "RIGHT",
    "FULL",
    "INNER",
    "CROSS",
    "INSERT",
    "UPDATE",
    "DELETE",
    "BEGIN",
    "DECLARE",
    "END",
    "IF",
    "ELSIF",
    "ELSE",
    "THEN",
    "LOOP",
    "RETURN",
    "RAISE",
    "PERFORM",
    "EXECUTE",
    "FETCH",
    "FOR",
    "WITH",
})

DOLLAR_TAG_PATTERN = re.compile(r"\$[A-Za-z_]\w*\$|\$\$")

BODY_TAG_PATTERN = re.compile(
    r"(?is)\bAS\s+(\$[A-Za-z_]\w*\$|\$\$)[ \t]*\r?\n"
)

DATE_VALUE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
UPDATE_DATE_VALUE_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:\s*[,，]\s*\d{4}-\d{2}-\d{2})*$"
)

HEADER_START_PATTERN = re.compile(r"(?m)^/\*{10,}[ \t\r]*$")

HEADER_END_PATTERN = re.compile(r"(?m)^\*{10,}/[ \t\r]*$")

INDEX_STATEMENT = re.compile(r"(?is)^\s*CREATE\s+(?:UNIQUE\s+)?INDEX\b")

# INC-05：用未来日期充当“无数据”哨兵（2099-01-01、9999-12-31 一类）。
SENTINEL_DATE = re.compile(r"'(?:2(?:099|[1-9]\d\d)|9{4})-\d{2}-\d{2}'")

CASE_RAW_TOKEN = re.compile(r"(?i)(?<!\.)\bCASE\b")
END_CASE_TOKEN = re.compile(r"(?i)\bEND\s+CASE\b")
END_TOKEN = re.compile(r"(?i)(?<!\.)\bEND\b(?!\s*(?:IF|LOOP|CASE|;))")
# 以运算符起行的续行：上一条列表项被拆开继续写，不是新的列表项。
CONT_OPERATOR = re.compile(r"^(\|\||[-+*/]|AND\b|OR\b)", re.IGNORECASE)

EXECUTE_CONCAT_PATTERN = re.compile(
    r"(?is)\bEXECUTE\b(?!\s+(?:PROCEDURE|FUNCTION)\b)[^;]*\|\|"
)
QUOTE_VAR_CONCAT_PATTERN = re.compile(r"'''\s*\|\|\s*(?:p_|v_)")
FORMAT_CALL_PATTERN = re.compile(r"(?i)\bformat\s*\(")
SINGLE_STRING_LITERAL = re.compile(r"'(?:''|[^'])*'")
FORMAT_PERCENT_S_PATTERN = re.compile(r"%(?:\d+\$)?s")

SECURITY_DEFINER_PATTERN = re.compile(r"(?i)\bSECURITY\s+DEFINER\b")
SET_SEARCH_PATH_PATTERN = re.compile(
    r"(?is)\bSET\s+search_path\s*(?:=|TO)\s*(.+?)"
    r"(?=\s+(?:AS|LANGUAGE|RETURNS|SECURITY|IMMUTABLE|STABLE|VOLATILE|"
    r"STRICT|CALLED|RETURN|COST|ROWS|PARALLEL|EXECUTE|LEAKPROOF|WINDOW)\b|\s*;|$)"
)

WHEN_OTHERS_NULL_PATTERN = re.compile(r"(?is)\bWHEN\s+OTHERS\s+THEN\s+NULL\s*;")

INC_DATE_DERIVE_SIGNAL = re.compile(
    r"(?is)\barray_agg\s*\(|\bmin\s*\(|\bmax\s*\("
    r"|\bINTO\s+v_changed_(?:dates|months)\b|\bINTO\s+v_start_date\b"
)
UPDATE_TIME_PREDICATE = re.compile(
    r"(?i)\b(?:update_time|updated_time)\s*(?:>=|>|<=|<|=|BETWEEN\b)"
)
DELETED_ZERO_PATTERN = re.compile(r"(?i)\b(?:deleted|is_deleted)\s*=\s*0\b")


def _paren_delta(line: str) -> int:
    """该行净开括号数，忽略注释与单引号字符串。"""
    depth = 0
    quote = False
    index = 0
    while index < len(line):
        char = line[index]
        if quote:
            if char == "'":
                quote = False
        elif char == "'":
            quote = True
        elif line.startswith("--", index):
            break
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        index += 1
    return depth


def _expr_delta(line: str) -> int:
    """自下而上回溯时，该行把我们带回多少层外层。

    只统计 SQL 的 CASE / END 表达式（排除 END IF / END LOOP / END CASE / END;），
    使 PL/pgSQL 块边界与注释/字符串不影响同层列表项定位。
    """
    sql_cases = len(CASE_RAW_TOKEN.findall(line)) - len(END_CASE_TOKEN.findall(line))
    return -_paren_delta(line) + len(END_TOKEN.findall(line)) - sql_cases


def check_comma_alignment(
    raw_lines: list[str],
    violations: list[dict],
    sanitized_lines: list[str] | None = None,
) -> None:
    """F-32：前置逗号续行必须与首项同列。

    向上找「同层首项」时同时跟踪括号与 SQL CASE/END（基于清洗后代码），并跳过运算符续行：
    跨行 CASE、被拆开的算术式内部的续行缩进按层级递增是正确写法。
    """
    code_lines = sanitized_lines if sanitized_lines is not None else raw_lines
    for index, raw_line in enumerate(raw_lines, start=1):
        code_line = code_lines[index - 1]
        if not code_line.strip().startswith(","):
            continue
        cursor = index - 2
        depth = 0
        first = None
        while cursor >= 0:
            depth += _expr_delta(code_lines[cursor])
            previous = code_lines[cursor].strip()
            if (
                depth == 0
                and previous
                and not previous.startswith(",")
                and not previous.startswith("--")
                and not CONT_OPERATOR.match(previous)
            ):
                first = cursor
                break
            cursor -= 1
        if first is None:
            continue
        expected = len(raw_lines[first]) - len(raw_lines[first].lstrip(" "))
        actual = len(raw_line) - len(raw_line.lstrip(" "))
        if actual != expected:
            add(
                violations,
                "F-32",
                index,
                f"前置逗号续行缩进为 {actual}，首项为 {expected}，两者必须同列（F-32）",
            )


def check_blank_lines(lines: list[str], violations: list[dict]) -> None:
    """F-33：连续空行压成 1 个。"""
    run_start = 0
    run = 0
    for index, line in enumerate(lines + ["x"], start=1):
        if not line.strip():
            if run == 0:
                run_start = index
            run += 1
            continue
        if run >= 2:
            add(
                violations,
                "F-33",
                run_start,
                f"连续 {run} 个空行，压成 1 个（F-33）",
            )
        run = 0


def check_list_gaps(lines: list[str], violations: list[dict]) -> None:
    """F-34：空行或空注释不得切断列表项。"""
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith("--"):
            continue
        if stripped.startswith("--") and stripped.strip("-").strip():
            continue
        following = index + 1
        while following < len(lines) and not lines[following].strip():
            following += 1
        # 只有“下一条仍是列表项”才算切断；列表结束后的分段空行是正常的。
        next_is_item = following < len(lines) and lines[following].lstrip().startswith(",")
        if next_is_item:
            kind = "空注释行" if stripped else "空行"
            add(
                violations,
                "F-34",
                index + 1,
                f"列表项之间出现{kind}，会切断列清单（F-34）",
            )


def check_standalone_semicolon(lines: list[str], violations: list[dict]) -> None:
    """F-35：分号不单独成行。"""
    for index, line in enumerate(lines, start=1):
        if line.strip() == ";":
            add(
                violations,
                "F-35",
                index,
                "分号单独成行；应贴在上一行语句末尾（F-35）",
            )


def check_sentinel_dates(text: str, violations: list[dict]) -> None:
    for number, line in enumerate(text.splitlines(), start=1):
        for match in SENTINEL_DATE.finditer(line):
            add(
                violations,
                "INC-05",
                number,
                f"用日期 {match.group(0)} 充当空值哨兵；改用 NULL 判断（INC-05）",
            )


def index_statement_lines(lines: list[str]) -> set[int]:
    """返回属于 CREATE INDEX 语句的行号；表达式索引在该上下文内合法。"""
    covered: set[int] = set()
    buffer: list[str] = []
    start = 1
    for number, line in enumerate(lines, start=1):
        buffer.append(line)
        if ";" not in line:
            continue
        if INDEX_STATEMENT.search("\n".join(buffer)):
            covered.update(range(start, number + 1))
        buffer = []
        start = number + 1
    if buffer and INDEX_STATEMENT.search("\n".join(buffer)):
        covered.update(range(start, len(lines) + 1))
    return covered


def header_field_match(field: str, segment: str) -> re.Match[str] | None:
    return re.search(
        r"(?im)^[ \t]*\*[ \t]*" + re.escape(field) + r"[ \t]*:[ \t]*(.*?)[ \t\r]*$",
        segment,
    )


def header_values(segment: str) -> dict[str, str | None]:
    values: dict[str, str | None] = {}
    for field in HEADER_FIELDS:
        match = header_field_match(field, segment)
        values[field] = match.group(1).strip() if match else None
    return values


def matching_paren_end(text: str, open_index: int) -> int:
    depth = 0
    in_single = False
    in_double = False
    index = open_index
    while index < len(text):
        char = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if in_single:
            if char == "'" and following == "'":
                index += 2
                continue
            if char == "'":
                in_single = False
        elif in_double:
            if char == '"' and following == '"':
                index += 2
                continue
            if char == '"':
                in_double = False
        elif char == "'":
            in_single = True
        elif char == '"':
            in_double = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return -1


def _transform_sql_tokens(text: str, *, mask_strings_and_tags: bool) -> str:
    """保留精确字符偏移与换行符，按需屏蔽注释、字符串内容与美元标签。"""
    out: list[str] = []
    index = 0
    length = len(text)
    in_block = False
    in_line_comment = False
    in_string = False
    in_double = False

    while index < length:
        char = text[index]
        following = text[index + 1] if index + 1 < length else ""

        if in_line_comment:
            if char == "\n":
                in_line_comment = False
                out.append(char)
            else:
                out.append(" ")
            index += 1
            continue

        if in_block:
            if char == "*" and following == "/":
                in_block = False
                out.append("  ")
                index += 2
                continue
            out.append(char if char == "\n" else " ")
            index += 1
            continue

        if in_string:
            if char == "'" and following == "'":
                out.append("  " if mask_strings_and_tags else "''")
                index += 2
                continue
            if char == "'":
                in_string = False
                out.append(char)
            elif mask_strings_and_tags:
                out.append(char if char == "\n" else " ")
            else:
                out.append(char)
            index += 1
            continue

        if in_double:
            if char == '"' and following == '"':
                out.append('""')
                index += 2
                continue
            if char == '"':
                in_double = False
            out.append(char)
            index += 1
            continue

        if char == "-" and following == "-":
            in_line_comment = True
            out.append("  ")
            index += 2
            continue

        if char == "/" and following == "*":
            in_block = True
            out.append("  ")
            index += 2
            continue

        if char == "'":
            in_string = True
            out.append(char)
            index += 1
            continue

        if char == '"':
            in_double = True
            out.append(char)
            index += 1
            continue

        if char == "$" and mask_strings_and_tags:
            match = DOLLAR_TAG_PATTERN.match(text, index)
            if match:
                out.append(" " * (match.end() - index))
                index = match.end()
                continue

        out.append(char)
        index += 1

    return "".join(out)


def sanitize(text: str) -> str:
    """把注释、字符串字面量与美元标签替换为空格，保留行号与行数。"""
    return _transform_sql_tokens(text, mask_strings_and_tags=True)


def strip_comments(text: str) -> str:
    """仅把注释替换为空格，保留字符串字面量与美元标签，保持字符偏移一致。"""
    return _transform_sql_tokens(text, mask_strings_and_tags=False)


def add(violations: list[dict], rule: str, line: int, message: str) -> None:
    violations.append({"rule": rule, "line": max(1, line), "message": message})


def check_keywords(lines: list[str], violations: list[dict]) -> None:
    """F-06：关键字必须大写；豁免双引号标识符、成员访问（.kw）及 RETURNS trigger。"""
    masked_text = DOUBLE_QUOTED_PATTERN.sub(
        lambda m: "".join("\n" if ch == "\n" else " " for ch in m.group(0)),
        "\n".join(lines),
    )
    for number, line in enumerate(masked_text.splitlines(), start=1):
        found: set[str] = set()
        for match in KEYWORD_PATTERN.finditer(line):
            word = match.group(0)
            if word == word.upper():
                continue
            if match.start() > 0 and line[match.start() - 1] == ".":
                continue
            if word.lower() == "trigger" and RETURNS_BEFORE_TRIGGER.search(
                line[: match.start()]
            ):
                continue
            found.add(word)
        if found:
            add(
                violations,
                "F-06",
                number,
                "关键字未大写：" + "、".join(sorted(found)) + "（F-06）",
            )


def check_trailing_commas(lines: list[str], violations: list[dict], style: str) -> None:
    if style == "leading":
        for number, line in enumerate(lines, start=1):
            stripped = line.rstrip()
            if not stripped.endswith(","):
                continue
            if stripped.endswith("),"):
                # CTE 之间的 `),` 属于允许写法。
                continue
            add(
                violations,
                "F-12",
                number,
                "本仓库使用前置逗号，不得出现尾逗号（F-12）",
            )
        return

    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped.startswith(","):
            continue
        add(
            violations,
            "F-12",
            number,
            "本仓库使用尾逗号，不得出现前置逗号（F-12）",
        )


def _extract_routines(
    text: str, sanitized: str, comment_stripped: str
) -> list[dict]:
    """扫描所有 CREATE [OR REPLACE] FUNCTION / PROCEDURE 定义并划分各自前缀与体区间。"""
    matches = list(CREATE_PATTERN.finditer(sanitized))
    routines: list[dict] = []
    prev_end = 0

    for index, match in enumerate(matches):
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        create_start = match.start()
        create_line = text[:create_start].count("\n") + 1
        kind = match.group(1).upper()
        prefix = text[prev_end:create_start]

        name_match = FUNCTION_NAME_PATTERN.search(sanitized, create_start, next_start)
        close_index = -1
        if name_match is not None:
            open_index = name_match.end() - 1
            close_index = matching_paren_end(sanitized, open_index)

        search_from = (close_index + 1) if close_index != -1 else match.end()
        body_match = BODY_TAG_PATTERN.search(text, search_from, next_start)

        if body_match is not None:
            tag = body_match.group(1)
            body_start = body_match.end()
            closing = text.find(tag, body_start, next_start)
            body_end = closing if closing != -1 else next_start
            prev_end = (closing + len(tag)) if closing != -1 else next_start
            header_end = body_match.start()
        else:
            body_start = -1
            body_end = -1
            semi = sanitized.find(";", search_from, next_start)
            prev_end = (semi + 1) if semi != -1 else next_start
            header_end = prev_end

        routines.append(
            {
                "kind": kind,
                "create_start": create_start,
                "create_line": create_line,
                "prefix": prefix,
                "name_match": name_match,
                "close_index": close_index,
                "header_end": header_end,
                "body_match": body_match,
                "body_start": body_start,
                "body_end": body_end,
                "raw_body": text[body_start:body_end] if body_start != -1 else "",
                "sanitized_body": (
                    sanitized[body_start:body_end] if body_start != -1 else ""
                ),
                "stripped_body": (
                    comment_stripped[body_start:body_end]
                    if body_start != -1
                    else ""
                ),
                "header_sanitized": sanitized[create_start:header_end],
                "header_stripped": comment_stripped[create_start:header_end],
            }
        )

    return routines


def _check_single_header(
    text: str, routine: dict, violations: list[dict]
) -> None:
    create_line = routine["create_line"]
    kind = routine["kind"]
    name_match = routine["name_match"]
    if name_match is None:
        return
    if routine["body_match"] is None:
        add(
            violations,
            "F-21",
            create_line,
            "找不到 AS 美元引用函数体；函数头必须放在 AS $function$ 之后、"
            "DECLARE/BEGIN 之前（F-21）",
        )
        return

    body = routine["raw_body"]
    body_start = routine["body_start"]

    stop_match = re.search(r"(?im)^[ \t]*(?:DECLARE|BEGIN)\b", body)
    header_segment = body[: stop_match.start()] if stop_match else body
    values = header_values(header_segment)
    missing = [
        field for field in HEADER_FIELDS
        if values[field] is None or not values[field]
    ]

    prefix_values = header_values(routine["prefix"])
    prefix_has_header = any(value is not None for value in prefix_values.values())

    if missing:
        if prefix_has_header:
            message = (
                "函数头只写在 CREATE 之前不会被 pg_get_functiondef 保留；"
                "必须放入 AS $function$ 之后、DECLARE/BEGIN 之前（F-21）"
            )
        else:
            message = "函数体内缺少中文八字段头：" + "、".join(missing) + "（F-21）"
        add(violations, "F-21", create_line, message)
        return

    if not (
        HEADER_START_PATTERN.search(header_segment)
        and HEADER_END_PATTERN.search(header_segment)
    ):
        add(
            violations,
            "F-41",
            create_line,
            "函数头必须使用 /***** 与 *****/ 分隔线（F-41）",
        )

    positions = [
        header_field_match(field, header_segment).start()
        for field in HEADER_FIELDS
        if header_field_match(field, header_segment) is not None
    ]
    if positions != sorted(positions):
        add(
            violations,
            "F-21",
            create_line,
            "函数头字段顺序必须为 name、function、input、output、increment、"
            "author、CreateDate、UpdateDate（F-21）",
        )

    name_value = (values["name"] or "").strip()
    create_name = name_match.group(1).replace('"', "").replace("'", "")
    qualified_match = re.fullmatch(
        r"([A-Za-z_][A-Za-z0-9_$]*)\.([A-Za-z_][A-Za-z0-9_$]*)",
        name_value,
    )
    if qualified_match is None:
        add(
            violations,
            "F-36",
            create_line,
            f"*name 必须使用 schema 全限定名，实际为 {name_value!r}（F-36）",
        )
    elif name_value.lower() != create_name.lower():
        add(
            violations,
            "F-36",
            create_line,
            f"*name {name_value} 与 CREATE {kind} 名称 {create_name} 不一致（F-36）",
        )

    open_index = name_match.end() - 1
    close_index = routine["close_index"]
    signature = text[open_index + 1: close_index] if close_index != -1 else ""
    parameter_names = re.findall(r"(?i)\b(p_[a-z0-9_]*)\b", signature)
    input_value = values["input"] or ""
    missing_params = [
        name for name in parameter_names
        if re.search(rf"(?i)\b{re.escape(name)}\b", input_value) is None
    ]
    if missing_params:
        add(
            violations,
            "F-37",
            create_line,
            "*input 未说明参数业务含义：" + "、".join(missing_params) + "（F-37）",
        )

    output_value = values["output"] or ""
    body_code = routine["sanitized_body"][len(header_segment):]
    diag_vars: list[str] = []
    for diag_match in re.finditer(r"(?is)\bGET\s+DIAGNOSTICS\b([^;]*)", body_code):
        diag_vars.extend(
            re.findall(
                r"(?i)\b([a-z_][a-z0-9_]*)\s*:?=\s*ROW_COUNT\b",
                diag_match.group(1),
            )
        )
    returned_diag = any(
        re.search(rf"(?i)\bRETURN\s+{re.escape(var)}\b", body_code)
        for var in diag_vars
    )
    row_count_signal = returned_diag or bool(
        re.search(
            r"(?is)\bRETURN\s+v_[a-z0-9_]*(?:rows?|row_count|cnt|count|affected)[a-z0-9_]*\b",
            body_code,
        )
    )
    if row_count_signal and not (
        (">=0" in output_value or "≥0" in output_value) and "行数" in output_value
    ):
        add(
            violations,
            "F-38",
            create_line,
            "*output 声明与函数返回行数不一致；应写明 -1参数异常, >=0影响行数（F-38）",
        )
    if re.search(r"(?is)\bRETURN\s+-1\b", body_code) and "-1" not in output_value:
        add(
            violations,
            "F-38",
            create_line,
            "*output 未声明代码实际使用的 -1 参数异常返回码（F-38）",
        )

    increment_value = (values["increment"] or "").strip()
    incremental_body = re.search(
        r"(?i)\b(?:v_changed_dates|v_changed_months|p_lookback_days)\b"
        r"|\b(?:update_time|updated_time)\s*(?:>=|>|<=|<|=|BETWEEN\b)",
        body_code,
    )
    if incremental_body and increment_value.lower() in {"", "不适用", "n/a", "none"}:
        add(
            violations,
            "F-39",
            create_line,
            "增量函数必须说明水位线、回看窗口和半开区间，不能写“不适用”（F-39）",
        )

    create_date = values["CreateDate"] or ""
    if DATE_VALUE_PATTERN.fullmatch(create_date) is None:
        add(
            violations,
            "F-40",
            create_line,
            f"*CreateDate 必须是 YYYY-MM-DD，实际为 {create_date!r}（F-40）",
        )

    update_matches = list(
        re.finditer(
            r"(?im)^[ \t]*\*[ \t]*UpdateDate[ \t]*:[ \t]*(.*?)[ \t\r]*$",
            header_segment,
        )
    )
    for update_match in update_matches:
        val = update_match.group(1).strip()
        if UPDATE_DATE_VALUE_PATTERN.fullmatch(val) is None:
            err_line = text[: body_start + update_match.start()].count("\n") + 1
            add(
                violations,
                "F-40",
                err_line,
                f"*UpdateDate 必须是 YYYY-MM-DD（支持逗号分隔追加多个日期），实际为 {val!r}（F-40）",
            )


def check_header(
    text: str,
    violations: list[dict],
    routines: list[dict] | None = None,
) -> None:
    if routines is None:
        sanitized = sanitize(text)
        routines = _extract_routines(text, sanitized, strip_comments(text))
    for routine in routines:
        _check_single_header(text, routine, violations)


def check_function_name(
    sanitized: str,
    violations: list[dict],
    routines: list[dict] | None = None,
) -> None:
    if routines is None:
        routines = _extract_routines(sanitized, sanitized, sanitized)
    for routine in routines:
        if routine["kind"] != "FUNCTION":
            continue
        name_match = routine["name_match"]
        if name_match is None:
            continue
        qualified = name_match.group(1).replace('"', "").replace("'", "")
        name = qualified.rsplit(".", 1)[-1]
        if not name.lower().startswith("f_"):
            line = sanitized[: name_match.start()].count("\n") + 1
            add(
                violations,
                "STYLE-01",
                line,
                f"函数名 {qualified} 未使用 f_ 前缀（STYLE-01，固定风格默认值；"
                "项目书面约定可覆盖）",
            )


def _filter_clause_mask(lines: list[str]) -> list[tuple[int, int]]:
    """返回处于 WHERE / ON / HAVING 过滤或关联条件上下文中的字符区间列表。"""
    joined = "\n".join(lines)
    spans: list[tuple[int, int]] = []
    in_filter = False
    filter_start = 0
    paren_stack: list[bool] = []

    for match in CLAUSE_TOKEN_PATTERN.finditer(joined):
        tok = match.group(0)
        if tok.startswith('"'):
            continue
        if tok == "(":
            paren_stack.append(in_filter)
            continue
        if tok == ")":
            prev_filter = in_filter
            in_filter = paren_stack.pop() if paren_stack else False
            if prev_filter and not in_filter:
                spans.append((filter_start, match.start()))
            elif not prev_filter and in_filter:
                filter_start = match.end()
            continue
        if tok == ";":
            if in_filter:
                spans.append((filter_start, match.start()))
            in_filter = False
            paren_stack.clear()
            continue

        upper = tok.upper()
        if upper in {"WHERE", "HAVING"}:
            if not in_filter:
                in_filter = True
                filter_start = match.start()
        elif upper == "ON":
            after = joined[match.end():].lstrip()
            next_word_match = re.match(r"([A-Za-z_][\w$]*)", after)
            next_word = next_word_match.group(1).upper() if next_word_match else ""
            if next_word not in NON_FILTER_ON_FOLLOWERS and not in_filter:
                in_filter = True
                filter_start = match.start()
        elif upper in FILTER_EXIT_KEYWORDS:
            if in_filter:
                spans.append((filter_start, match.start()))
                in_filter = False

    if in_filter:
        spans.append((filter_start, len(joined)))
    return spans


def _offset_in_spans(offset: int, spans: list[tuple[int, int]]) -> bool:
    for start, end in spans:
        if start <= offset < end:
            return True
        if offset < start:
            break
    return False


def check_column_casts(
    lines: list[str], violations: list[dict], skip_lines: set[int]
) -> None:
    spans = _filter_clause_mask(lines)
    line_offset = 0
    for number, line in enumerate(lines, start=1):
        if number not in skip_lines:
            has_cmp = bool(COMPARISON_OP_PATTERN.search(line))
            for match in COLUMN_CAST_PATTERN.finditer(line):
                identifier = match.group(1)
                if identifier.lower() in EXEMPT_CAST_LEFT:
                    continue
                last = identifier.rsplit(".", 1)[-1]
                if last.lower().startswith(("p_", "v_")):
                    continue
                abs_offset = line_offset + match.start()
                if not (_offset_in_spans(abs_offset, spans) or has_cmp):
                    continue
                add(
                    violations,
                    "PERF-29",
                    number,
                    f"过滤列 {identifier} 被套 ::{match.group(2)}；"
                    "类型转换应放在参数或常量侧（PERF-29）",
                )
        line_offset += len(line) + 1


def _check_dynamic_sql_in_scope(
    full_text: str,
    base_offset: int,
    sanitized_scope: str,
    stripped_scope: str,
    violations: list[dict],
) -> None:
    """检查单个函数体（或独立 SQL 文件）的 REV-S01 / REV-S02。"""
    has_execute = bool(
        re.search(
            r"(?i)\bEXECUTE\b(?!\s+(?:PROCEDURE|FUNCTION)\b)",
            sanitized_scope,
        )
    )
    if not has_execute:
        return

    s01_lines: set[int] = set()
    for match in EXECUTE_CONCAT_PATTERN.finditer(sanitized_scope):
        line = full_text[: base_offset + match.start()].count("\n") + 1
        s01_lines.add(line)

    for match in QUOTE_VAR_CONCAT_PATTERN.finditer(stripped_scope):
        line = full_text[: base_offset + match.start()].count("\n") + 1
        s01_lines.add(line)

    for line in sorted(s01_lines):
        add(
            violations,
            "REV-S01",
            line,
            "动态 SQL EXECUTE 存在字符串拼接值风险；请改用 EXECUTE ... USING 绑定值或 format('%L')（REV-S01）",
        )

    s02_lines: set[int] = set()
    for match in FORMAT_CALL_PATTERN.finditer(sanitized_scope):
        open_idx = match.end() - 1
        close_idx = matching_paren_end(stripped_scope, open_idx)
        if close_idx == -1:
            continue
        args_text = stripped_scope[open_idx + 1 : close_idx]
        # 只取 format(...) 的首个参数（直到顶层逗号）
        first_arg_end = len(args_text)
        depth = 0
        in_str = False
        idx = 0
        while idx < len(args_text):
            ch = args_text[idx]
            nxt = args_text[idx + 1] if idx + 1 < len(args_text) else ""
            if in_str:
                if ch == "'" and nxt == "'":
                    idx += 2
                    continue
                if ch == "'":
                    in_str = False
            elif ch == "'":
                in_str = True
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                first_arg_end = idx
                break
            idx += 1
        first_arg = args_text[:first_arg_end]
        for lit_match in SINGLE_STRING_LITERAL.finditer(first_arg):
            lit = lit_match.group(0)[1:-1].replace("''", "'").replace("%%", "")
            if FORMAT_PERCENT_S_PATTERN.search(lit):
                line = full_text[: base_offset + match.start()].count("\n") + 1
                s02_lines.add(line)
                break

    for line in sorted(s02_lines):
        add(
            violations,
            "REV-S02",
            line,
            "在含 EXECUTE 的函数中使用 format() 且格式串含 %s；标识符请改用 %I，字面量请改用 %L 或 USING（REV-S02）",
        )


def check_security_and_dynamic_sql(
    text: str,
    sanitized: str,
    comment_stripped: str,
    routines: list[dict],
    violations: list[dict],
) -> None:
    if routines:
        for routine in routines:
            if routine["body_start"] != -1:
                _check_dynamic_sql_in_scope(
                    text,
                    routine["body_start"],
                    routine["sanitized_body"],
                    routine["stripped_body"],
                    violations,
                )
    else:
        _check_dynamic_sql_in_scope(text, 0, sanitized, comment_stripped, violations)

    for routine in routines:
        header_sanitized = routine["header_sanitized"]
        sec_match = SECURITY_DEFINER_PATTERN.search(header_sanitized)
        if sec_match is None:
            continue
        sec_line = text[: routine["create_start"] + sec_match.start()].count("\n") + 1
        sp_match = SET_SEARCH_PATH_PATTERN.search(routine["header_stripped"])
        if sp_match is None:
            add(
                violations,
                "REV-S03",
                sec_line,
                "SECURITY DEFINER 未固定 SET search_path；"
                "请设置 SET search_path = '' 或 pg_catalog, <trusted>, pg_temp（REV-S03）",
            )
            continue

        sp_line = text[: routine["create_start"] + sp_match.start()].count("\n") + 1
        raw_val = sp_match.group(1).strip()
        if raw_val == "''":
            continue
        items = [
            part.strip().strip('"').strip("'").strip().lower()
            for part in raw_val.split(",")
        ]
        valid = (
            bool(items)
            and all(items)
            and "pg_catalog" in items
            and items[-1] == "pg_temp"
            and "public" not in items
        )
        if not valid:
            add(
                violations,
                "REV-S04",
                sp_line,
                f"SECURITY DEFINER 的 search_path={raw_val!r} 不安全；"
                "只允许 '' 或含 pg_catalog、不含 public 且以 pg_temp 结尾的列表（REV-S04）",
            )


def check_when_others_null(sanitized: str, violations: list[dict]) -> None:
    """REV-C01：禁止 WHEN OTHERS THEN NULL; 吞掉异常。"""
    for match in WHEN_OTHERS_NULL_PATTERN.finditer(sanitized):
        line = sanitized[: match.start()].count("\n") + 1
        add(
            violations,
            "REV-C01",
            line,
            "禁止 WHEN OTHERS THEN NULL; 吞掉异常并假成功返回（REV-C01）",
        )


def check_incremental_deleted_filter(
    sanitized: str, violations: list[dict]
) -> None:
    """INC-07：增量业务日期推导 SELECT 语句内禁止过滤 deleted = 0 / is_deleted = 0。"""
    cursor = 0
    for stmt_match in re.finditer(r"[^;]+;?", sanitized):
        stmt = stmt_match.group(0)
        stmt_start = stmt_match.start()
        cursor = stmt_match.end()
        if not re.search(r"(?i)\bSELECT\b", stmt):
            continue
        if not UPDATE_TIME_PREDICATE.search(stmt):
            continue
        if not INC_DATE_DERIVE_SIGNAL.search(stmt):
            continue
        for del_match in DELETED_ZERO_PATTERN.finditer(stmt):
            line = sanitized[: stmt_start + del_match.start()].count("\n") + 1
            add(
                violations,
                "INC-07",
                line,
                "增量业务日期推导阶段过滤了 deleted = 0 / is_deleted = 0，会导致逻辑删除行无法触发目标重算（INC-07）",
            )
    _ = cursor


def check_sql(text: str, comma_style: str = "leading") -> list[dict]:
    sanitized = sanitize(text)
    comment_stripped = strip_comments(text)
    lines = sanitized.splitlines()
    routines = _extract_routines(text, sanitized, comment_stripped)
    violations: list[dict] = []
    check_keywords(lines, violations)
    check_trailing_commas(lines, violations, comma_style)
    check_header(text, violations, routines=routines)
    check_function_name(sanitized, violations, routines=routines)
    check_column_casts(lines, violations, index_statement_lines(lines))
    check_sentinel_dates(text, violations)
    check_security_and_dynamic_sql(
        text, sanitized, comment_stripped, routines, violations
    )
    check_when_others_null(sanitized, violations)
    check_incremental_deleted_filter(sanitized, violations)
    raw_lines = text.splitlines()
    check_comma_alignment(raw_lines, violations, sanitized_lines=lines)
    check_blank_lines(raw_lines, violations)
    check_list_gaps(raw_lines, violations)
    check_standalone_semicolon(raw_lines, violations)
    violations.sort(key=lambda item: (item["line"], item["rule"]))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="检查 SQL 输出是否符合 pg-function-craft 的固定规则（离线，不连库）。"
    )
    parser.add_argument("file", help="待检查的 .sql 文件")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    parser.add_argument(
        "--comma-style",
        choices=("leading", "trailing"),
        default="leading",
        help="仓库的逗号约定：leading（默认，前置逗号）或 trailing（尾逗号）",
    )
    args = parser.parse_args(argv)

    path = pathlib.Path(args.file)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"读取 SQL 文件失败：{exc}", file=sys.stderr)
        return 2

    violations = check_sql(text, args.comma_style)
    result = {
        "ok": not violations,
        "database_connected": False,
        "violation_count": len(violations),
        "violations": violations,
        "command": [
            "python",
            "scripts/check_sql_output.py",
            "--json",
            str(path),
        ],
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"检查文件：{path}")
        for item in violations:
            print(f"[{item['rule']}] 第 {item['line']} 行：{item['message']}")
        if violations:
            print(f"结果：发现 {len(violations)} 项违规")
        else:
            print("结果：通过")

    return 0 if not violations else 1


if __name__ == "__main__":
    sys.exit(main())
