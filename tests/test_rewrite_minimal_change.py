#!/usr/bin/env python3
"""改写纪律回归测试：最小改动、保留导出形态、保留原作者。

锁定 2026-11-16 的调整（来自实际函数改写反馈）：

  1. `05-重写协议.md` 有“最小改动原则”，并点名三样必须原样保留的东西：
     调用示例注释、DDL 前导形态、原作者署名；
  2. `00`/`04`/`SKILL` 的 `*author` 规则是“保留原作者 / 新增写占位符”；
  3. `06` 的 F-21/F-22/F-26 接受 `pg_get_functiondef` 导出形态；
  4. `11` 的 INC-03/INC-07/INC-13 不再把建议当强制；
  5. 检查器对“头部在 `AS $BODY$` 之后”的函数不报 F-21。

约束：只使用 Python 标准库；不连接数据库、不访问网络、不执行 SQL。
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "pg-function-craft"
REFS = SKILL_ROOT / "references"
SKILL_MD = SKILL_ROOT / "SKILL.md"
CHECKER = SKILL_ROOT / "scripts" / "check_sql_output.py"


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


class MinimalChangeRulesTest(unittest.TestCase):
    maxDiff = None

    def test_rewrite_protocol_has_minimal_change_section(self):
        text = read(REFS / "05-重写协议.md")
        self.assertIn("最小改动原则", text)
        for keyword in ("调用示例注释", "$BODY$", "原作者署名"):
            with self.subTest(keyword=keyword):
                self.assertIn(
                    keyword,
                    text,
                    msg=f"05 的“必须原样保留”清单缺少：{keyword}",
                )

    def test_author_rule_preserves_existing_author(self):
        for path in (REFS / "00-风格与边界.md", REFS / "04-固定风格.md", SKILL_MD):
            with self.subTest(path=path.name):
                self.assertIn(
                    "保留原作者",
                    read(path),
                    msg="改写既有函数时应保留原作者，不能用占位符覆盖。",
                )

    def test_layout_rules_accept_exported_ddl_form(self):
        text = read(REFS / "06-SQL排版规范.md")
        self.assertIn(
            "`AS $function$` 之后",
            text,
            msg="F-21 应要求函数头位于 AS $function$ 之后。",
        )
        self.assertIn(
            "pg_get_functiondef",
            text,
            msg="F-21 应解释 CREATE 前注释不会由 pg_get_functiondef 保留。",
        )
        self.assertIn("`$BODY$`", text, msg="F-26 应允许导出件的 $BODY$ 标签。")
        self.assertIn("int4", text, msg="F-22 应保留导出件的类型拼写。")

    def test_temp_table_lifetime_not_changed_silently(self):
        text = read(REFS / "05-重写协议.md")
        self.assertIn(
            "不动临时表的生命周期",
            text,
            msg="改写既有函数时不应擅自给临时表加 ON COMMIT DROP。",
        )

    def test_increment_rules_are_not_forced_on_existing_code(self):
        text = read(REFS / "11-增量与水位线.md")
        self.assertIn("改造既有函数时", text)
        self.assertIn("属于语义变更", text)
        self.assertIn("不要塞进函数头", text)
        self.assertIn("分片是结构变更", text)


class LayoutCheckerTest(unittest.TestCase):
    """F-32/F-33：前置逗号对齐与连续空行。"""

    def _rules(self, sql: str) -> set[str]:
        with tempfile.TemporaryDirectory(prefix="pgfc-layout-") as tmp:
            path = pathlib.Path(tmp) / "case.sql"
            path.write_bytes(sql.encode("utf-8"))
            proc = subprocess.run(
                [sys.executable, str(CHECKER), "--json", str(path)],
                cwd=str(SKILL_ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
        payload = json.loads(proc.stdout)
        return {item["rule"] for item in payload["violations"]}

    def test_misaligned_comma_is_reported(self):
        sql = chr(10).join([
            "SELECT",
            "        a.col1",
            "    , a.col2",
            "FROM demo.t a;",
            "",
        ])
        self.assertIn("F-32", self._rules(sql))

    def test_aligned_comma_is_clean(self):
        sql = chr(10).join([
            "SELECT",
            "        a.col1",
            "        , a.col2",
            "FROM demo.t a;",
            "",
        ])
        self.assertNotIn("F-32", self._rules(sql))

    def test_blank_line_inside_list_is_reported(self):
        sql = chr(10).join([
            "SELECT",
            "        a.col1",
            "",
            "        , a.col2",
            "FROM demo.t a;",
            "",
        ])
        self.assertIn("F-34", self._rules(sql))

    def test_blank_line_after_list_is_clean(self):
        sql = chr(10).join([
            "SELECT",
            "        a.col1",
            "        , a.col2",
            "",
            "FROM demo.t a;",
            "",
        ])
        self.assertNotIn("F-34", self._rules(sql))

    def test_standalone_semicolon_is_reported(self):
        sql = chr(10).join([
            "SELECT",
            "        a.col1",
            "FROM demo.t a",
            ";",
            "",
        ])
        self.assertIn("F-35", self._rules(sql))

    def test_consecutive_blank_lines_are_reported(self):
        sql = chr(10).join([
            "SELECT",
            "",
            "",
            "a.col1",
            "FROM demo.t a;",
            "",
        ])
        self.assertIn("F-33", self._rules(sql))


class ExportedFormCheckerTest(unittest.TestCase):
    SQL = (
        'CREATE OR REPLACE FUNCTION "dwd"."f_demo"("p_flag" int4)\n'
        ' RETURNS "pg_catalog"."int2"\n'
        ' LANGUAGE "plpgsql"\n'
        "AS $BODY$\n"
        "/*****************************************************************\n"
        "*name       : dwd.f_demo\n"
        "*function   : 演示\n"
        "*input      : p_flag 标志\n"
        "*output     : -1参数异常,0正常\n"
        "*increment  : 不适用\n"
        "*author     : 张三\n"
        "*CreateDate : 2026-01-01\n"
        "*UpdateDate : 2026-01-01\n"
        "******************************************************************/\n"
        "DECLARE\n"
        "    v_cnt bigint := 0;\n"
        "BEGIN\n"
        "    RETURN 0;\n"
        "END;\n"
        "$BODY$;\n"
    )

    def test_header_after_body_tag_is_not_reported(self):
        with tempfile.TemporaryDirectory(prefix="pgfc-export-") as tmp:
            path = pathlib.Path(tmp) / "case.sql"
            path.write_bytes(self.SQL.encode("utf-8"))
            proc = subprocess.run(
                [sys.executable, str(CHECKER), "--json", str(path)],
                cwd=str(SKILL_ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
        payload = json.loads(proc.stdout)
        rules = {item["rule"] for item in payload["violations"]}
        self.assertNotIn(
            "F-21",
            rules,
            msg="导出件的头部在 AS $BODY$ 之后，不应判 F-21。",
        )


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    unittest.main(verbosity=2)
