#!/usr/bin/env python3
"""pg-function-craft SQL 输出检查器。

只使用 Python 标准库；不连接数据库、不访问网络、不执行任何 SQL。
按 references/06、07、08 的既有规则编号检查一份 SQL 文本：

  F-06     关键字未大写
  F-12     前置逗号仓库出现尾逗号
  F-21     CREATE 之前缺少中文七字段头
  REV-M02  函数名未使用 f_ 前缀
  PERF-29  过滤列被套 ::date / ::timestamp

用法：
  python scripts/check_sql_output.py --json <file.sql>

JSON 输出：
  {"ok": bool, "database_connected": false,
   "violations": [{"rule": "F-12", "line": 12, "message": "..."}]}

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

CREATE_PATTERN = re.compile(
    r"(?im)^\s*CREATE\s+(?:OR\s+REPLACE\s+)?(?:FUNCTION|PROCEDURE)\b"
)

FUNCTION_NAME_PATTERN = re.compile(
    r"(?is)\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:FUNCTION|PROCEDURE)\s+"
    r"(['\"]?[A-Za-z_][\w$]*['\"]?(?:\.['\"]?[A-Za-z_][\w$]*['\"]?)?)\s*\("
)

COLUMN_CAST_PATTERN = re.compile(
    r"(?i)\b([a-z_][\w$]*(?:\.[a-z_][\w$]*)?)\s*::\s*(date|timestamp|timestamptz)\b"
)

DOLLAR_TAG_PATTERN = re.compile(r"\$[A-Za-z_]\w*\$|\$\$")

INDEX_STATEMENT = re.compile(r"(?is)^\s*CREATE\s+(?:UNIQUE\s+)?INDEX\b")

# INC-05：用未来日期充当“无数据”哨兵（2099-01-01、9999-12-31 一类）。
SENTINEL_DATE = re.compile(r"'(?:2(?:099|[1-9]\d\d)|9{4})-\d{2}-\d{2}'")


CLAUSE_LINE = re.compile(r"^(SELECT|GROUP BY|ORDER BY|VALUES)\s*$", re.IGNORECASE)
ITEM_END = re.compile(
    r"^(FROM|WHERE|GROUP BY|ORDER BY|HAVING|UNION|EXCEPT|INTERSECT|JOIN|LEFT|RIGHT|FULL"
    r"|INNER|CROSS|ON|RETURNING|INTO|SET)",
    re.IGNORECASE,
)


CASE_TOKEN = re.compile(r"\bCASE\b")
END_TOKEN = re.compile(r"\bEND\b")


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
    """自下而上回溯时该行开启的表达式块数：括号净开数 + CASE/END 净未闭合数。

    `END` 表示我们正从某个 CASE 的内部往上走（+1），`CASE` 表示找到了它的开头（-1）。
    """
    return _paren_delta(line) + len(END_TOKEN.findall(line)) - len(CASE_TOKEN.findall(line))


def check_comma_alignment(lines: list[str], violations: list[dict]) -> None:
    """F-32：前置逗号续行必须与首项同列。

    向上找「同层首项」时同时跟踪括号与 CASE/END：跨行 CASE、被拆开的算术式
    内部的续行缩进按层级递增是正确写法。规范 06 §1.5、§3 明确要求这类表达式
    展开，检查器不得因此惩罚展开写法、逼迫把代码压成超长行。
    """
    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped.startswith(","):
            continue
        cursor = index - 2
        depth = 0
        first = None
        while cursor >= 0:
            depth += _expr_delta(lines[cursor])
            previous = lines[cursor].strip()
            if (
                depth <= 0
                and previous
                and not previous.startswith(",")
                and not previous.startswith("--")
            ):
                first = cursor
                break
            cursor -= 1
        if first is None:
            continue
        expected = len(lines[first]) - len(lines[first].lstrip(" "))
        actual = len(line) - len(line.lstrip(" "))
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
        preceding = index - 1
        while preceding >= 0 and not lines[preceding].strip():
            preceding -= 1
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


def header_field_pattern(field: str) -> re.Pattern[str]:
    return re.compile(
        r"(?im)^\s*(?:--\s*)?(?:\*\s*){0,2}" + re.escape(field) + r"\s*:"
    )


def sanitize(text: str) -> str:
    """把注释、字符串字面量与美元标签替换为空格，保留行号与行数。"""
    out: list[str] = []
    index = 0
    length = len(text)
    in_block = False
    in_line_comment = False
    in_string = False

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
                out.append("  ")
                index += 2
                continue
            if char == "'":
                in_string = False
                out.append(char)
            else:
                out.append(char if char == "\n" else " ")
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

        if char == "$":
            match = DOLLAR_TAG_PATTERN.match(text, index)
            if match:
                out.append(" " * (match.end() - index))
                index = match.end()
                continue

        out.append(char)
        index += 1

    return "".join(out)


def add(violations: list[dict], rule: str, line: int, message: str) -> None:
    violations.append({"rule": rule, "line": max(1, line), "message": message})


def check_keywords(lines: list[str], violations: list[dict]) -> None:
    for number, line in enumerate(lines, start=1):
        found = sorted(
            {
                match.group(0)
                for match in KEYWORD_PATTERN.finditer(line)
                if match.group(0) != match.group(0).upper()
            }
        )
        if found:
            add(
                violations,
                "F-06",
                number,
                "关键字未大写：" + "、".join(found) + "（F-06）",
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


def check_header(text: str, violations: list[dict]) -> None:
    match = CREATE_PATTERN.search(text)
    if match is None:
        return

    def missing_in(segment: str) -> list[str]:
        return [
            field
            for field in HEADER_FIELDS
            if header_field_pattern(field).search(segment) is None
        ]

    # F-21 首选：头部在 CREATE 之前。
    prefix = text[: match.start()]
    missing = missing_in(prefix)
    if not missing:
        return

    # 导出件（pg_get_functiondef）：头部落在 AS $tag$ 之后、DECLARE/BEGIN 之前，同样合规。
    body_start = match.end()
    stops = [
        position
        for position in (
            text.find(chr(10) + "DECLARE", body_start),
            text.find(chr(10) + "BEGIN", body_start),
        )
        if position != -1
    ]
    body_head = text[match.start(): min(stops) if stops else len(text)]
    if not missing_in(body_head):
        return

    if missing:
        line = text[: match.start()].count("\n") + 1
        add(
            violations,
            "F-21",
            line,
            "CREATE 之前缺少中文七字段头：" + "、".join(missing) + "（F-21）",
        )


def check_function_name(text: str, violations: list[dict]) -> None:
    match = FUNCTION_NAME_PATTERN.search(text)
    if match is None:
        return
    qualified = match.group(1).replace('"', "")
    name = qualified.rsplit(".", 1)[-1]
    if not name.lower().startswith("f_"):
        line = text[: match.start()].count("\n") + 1
        add(
            violations,
            "STYLE-01",
            line,
            f"函数名 {qualified} 未使用 f_ 前缀（STYLE-01，固定风格默认值；"
            "项目书面约定可覆盖）",
        )


def check_column_casts(
    lines: list[str], violations: list[dict], skip_lines: set[int]
) -> None:
    for number, line in enumerate(lines, start=1):
        if number in skip_lines:
            # CREATE INDEX 里的表达式索引是 07 §2.3 明确允许的写法。
            continue
        for match in COLUMN_CAST_PATTERN.finditer(line):
            identifier = match.group(1)
            last = identifier.rsplit(".", 1)[-1]
            if last.lower().startswith(("p_", "v_")):
                # 参数/变量侧的转换是推荐写法。
                continue
            add(
                violations,
                "PERF-29",
                number,
                f"过滤列 {identifier} 被套 ::{match.group(2)}；"
                "类型转换应放在参数或常量侧（PERF-29）",
            )


def check_sql(text: str, comma_style: str = "leading") -> list[dict]:
    sanitized = sanitize(text)
    lines = sanitized.splitlines()
    violations: list[dict] = []
    check_keywords(lines, violations)
    check_trailing_commas(lines, violations, comma_style)
    check_header(text, violations)
    check_function_name(sanitized, violations)
    check_column_casts(lines, violations, index_statement_lines(lines))
    check_sentinel_dates(text, violations)
    raw_lines = text.splitlines()
    check_comma_alignment(raw_lines, violations)
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
        "violations": violations,
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
