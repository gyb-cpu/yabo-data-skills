#!/usr/bin/env python3
"""函数头导出契约测试：头部必须位于 AS 美元引用之后、DECLARE/BEGIN 之前。"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
CHECKER = REPO_ROOT / "skills" / "pg-function-craft" / "scripts" / "check_sql_output.py"


def header(
    *,
    name: str = "dwd.f_demo",
    input_value: str = "p_flag 0=增量 1=按日期区间, p_start_date=开始日期",
    output_value: str = "-1参数异常, 0正常",
    increment: str = "update_time 水位线，半开区间 [clock_timestamp()-p_lookback_days, clock_timestamp())",
    create_date: str = "2026-11-25",
    update_date: str = "2026-11-25",
    include_increment: bool = True,
) -> str:
    lines = [
        "/*****************************************************************",
        f"*name       : {name}",
        "*function   : 演示函数",
        f"*input      : {input_value}",
        f"*output     : {output_value}",
    ]
    if include_increment:
        lines.append(f"*increment  : {increment}")
    lines.extend(
        [
            "*author     : 待补充",
            f"*CreateDate : {create_date}",
            f"*UpdateDate : {update_date}",
            "******************************************************************/",
        ]
    )
    return "\n".join(lines)


def sql(
    *,
    header_block: str | None = None,
    body: str = "RETURN 0;",
    name: str = "dwd.f_demo",
) -> str:
    return (
        f"CREATE OR REPLACE FUNCTION {name}(\n"
        "    p_flag integer\n"
        "    , p_start_date character varying\n"
        ")\n"
        "RETURNS integer\n"
        "LANGUAGE plpgsql\n"
        "SECURITY INVOKER\n"
        "SET search_path = ''\n"
        "AS $function$\n"
        f"{header_block if header_block is not None else header()}\n"
        "\n"
        "DECLARE\n"
        "    v_rows integer := 0;\n"
        "BEGIN\n"
        f"    {body}\n"
        "END;\n"
        "$function$;\n"
    )


class FunctionHeaderContractTest(unittest.TestCase):
    maxDiff = None

    def _run(self, sql_text: str) -> tuple[subprocess.CompletedProcess[str], dict]:
        with tempfile.TemporaryDirectory(prefix="pgfc-header-") as tmp:
            file_path = pathlib.Path(tmp) / "case.sql"
            file_path.write_text(sql_text, encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(CHECKER), "--json", str(file_path)],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
        return proc, json.loads(proc.stdout)

    def _rules(self, sql_text: str) -> set[str]:
        _, payload = self._run(sql_text)
        self.assertIn("violation_count", payload)
        self.assertEqual(payload["violation_count"], len(payload["violations"]))
        return {item["rule"] for item in payload["violations"]}

    def test_standard_header_inside_body_passes(self):
        proc, payload = self._run(sql())
        self.assertEqual(proc.returncode, 0, payload)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["violation_count"], 0)

    def test_header_only_before_create_fails(self):
        prefix = (
            "/* " + header() + " */\n"
            f"CREATE OR REPLACE FUNCTION dwd.f_demo(\n"
            "    p_flag integer\n"
            "    , p_start_date character varying\n"
            ")\n"
            "RETURNS integer\n"
            "LANGUAGE plpgsql\n"
            "AS $function$\n"
            "DECLARE\n"
            "    v_rows integer := 0;\n"
            "BEGIN\n"
            "    RETURN 0;\n"
            "END;\n"
            "$function$;\n"
        )
        self.assertIn("F-21", self._rules(prefix))

    def test_missing_increment_field_fails(self):
        self.assertIn("F-21", self._rules(sql(header_block=header(include_increment=False))))

    def test_name_without_schema_fails(self):
        self.assertIn("F-36", self._rules(sql(header_block=header(name="f_demo"))))

    def test_name_mismatch_fails(self):
        self.assertIn("F-36", self._rules(sql(header_block=header(name="dwd.f_other"))))

    def test_input_only_types_fails(self):
        self.assertIn(
            "F-37",
            self._rules(sql(header_block=header(input_value="integer, character varying"))),
        )

    def test_output_row_count_contract_mismatch_fails(self):
        rules = self._rules(
            sql(
                body=(
                    "GET DIAGNOSTICS v_rows = ROW_COUNT;\n"
                    "    RETURN v_rows;"
                )
            )
        )
        self.assertIn("F-38", rules)

    def test_invalid_date_format_fails(self):
        self.assertIn(
            "F-40",
            self._rules(sql(header_block=header(create_date="2026/11/25"))),
        )

    def test_increment_function_cannot_mark_increment_not_applicable(self):
        rules = self._rules(
            sql(
                header_block=header(increment="不适用"),
                body=(
                    "SELECT a.id FROM demo.src AS a WHERE a.update_time >= now() - interval '1 day';\n"
                    "    RETURN 0;"
                    "    RETURN 0;"
                ),
            )
        )
        self.assertIn("F-39", rules)

    def test_non_increment_function_with_not_applicable_passes(self):
        rules = self._rules(sql(header_block=header(increment="不适用")))
        self.assertNotIn("F-39", rules)

    def test_missing_separator_lines_fail(self):
        block = header().replace("/*****************************************************************\n", "").replace("\n******************************************************************/", "")
        self.assertIn("F-41", self._rules(sql(header_block=block)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
