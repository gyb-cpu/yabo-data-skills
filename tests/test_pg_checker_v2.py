#!/usr/bin/env python3
"""pg-function-craft 校验器 v2 回归测试。

覆盖：
  1. 误报修复：F-06（双引号/成员访问/RETURNS trigger）、PERF-29（特殊左值/纯投影）、
     F-38（GET DIAGNOSTICS 仅打日志返回 0）、F-39（非增量列/updated_time/p_lookback_days）、
     F-40（UpdateDate 逗号追加与多行）、STYLE-01（PROCEDURE 不强求 f_ 前缀）；
  2. 漏报修复：多函数文件逐一检查、F-32 在 -- END 与 END IF 之后、
     verify_output_contract._section_body 首尾不漏行；
  3. OUT-EVID-01：代码围栏忽略、同子句否定/禁止豁免、跨子句与肯定断言仍拦截；
  4. 新增高危规则正反例：REV-S01..S04、REV-C01、INC-07（以及项目专属 ext_1..10 不在通用检查器触发）。

约束：只使用 Python 3.10+ 标准库；离线运行，不连库、不访问网络。
"""

from __future__ import annotations

import ast
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import textwrap
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "pg-function-craft"
SQL_CHECKER = SKILL_ROOT / "scripts" / "check_sql_output.py"
CONTRACT_CHECKER = SKILL_ROOT / "scripts" / "verify_output_contract.py"


def _load_module(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    prev = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = prev
    return module


SQL_MOD = _load_module("pgfc_check_sql_v2", SQL_CHECKER)
CONTRACT_MOD = _load_module("pgfc_verify_contract_v2", CONTRACT_CHECKER)


def wrap_routine(
    *,
    kind: str = "FUNCTION",
    name: str = "demo.f_case",
    params: str = "p_flag integer",
    returns: str = "RETURNS integer\n",
    security: str = "SECURITY INVOKER\nSET search_path = ''\n",
    tag: str = "$function$",
    header_name: str | None = None,
    input_doc: str = "p_flag 运行模式",
    output_doc: str = "-1参数异常, 0正常",
    increment_doc: str = "不适用",
    create_date: str = "2026-11-25",
    update_lines: tuple[str, ...] = ("2026-11-25",),
    declare_block: str = "DECLARE\n    v_cnt integer := 0;\n",
    body: str = "    RETURN 0;\n",
    exception_block: str = "",
) -> str:
    h_name = header_name if header_name is not None else name
    update_block = "\n".join(f"*UpdateDate : {u}" for u in update_lines)
    return (
        f"CREATE OR REPLACE {kind} {name}({params})\n"
        f"{returns}"
        "LANGUAGE plpgsql\n"
        f"{security}"
        f"AS {tag}\n"
        "/*****************************************************************\n"
        f"*name       : {h_name}\n"
        "*function   : 回归测试用例\n"
        f"*input      : {input_doc}\n"
        f"*output     : {output_doc}\n"
        f"*increment  : {increment_doc}\n"
        "*author     : <team>\n"
        f"*CreateDate : {create_date}\n"
        f"{update_block}\n"
        "******************************************************************/\n"
        f"{declare_block}"
        "BEGIN\n"
        f"{body}"
        f"{exception_block}"
        "END;\n"
        f"{tag};\n"
    )


class SqlFalsePositiveFixesTest(unittest.TestCase):
    maxDiff = None

    def _rules(self, sql: str) -> set[str]:
        return {item["rule"] for item in SQL_MOD.check_sql(sql)}

    def test_f06_exempts_double_quoted_identifiers_member_access_and_returns_trigger(self):
        sql = (
            'CREATE OR REPLACE FUNCTION "demo"."f_trg_audit"()\n'
            "RETURNS trigger\n"
            "LANGUAGE plpgsql\n"
            "SECURITY INVOKER\n"
            "SET search_path = ''\n"
            "AS $function$\n"
            "/*****************************************************************\n"
            "*name       : demo.f_trg_audit\n"
            "*function   : 触发器测试\n"
            "*input      : 无参数\n"
            "*output     : NEW\n"
            "*increment  : 不适用\n"
            "*author     : <team>\n"
            "*CreateDate : 2026-11-25\n"
            "*UpdateDate : 2026-11-25\n"
            "******************************************************************/\n"
            "BEGIN\n"
            "    SELECT\n"
            '        "default"\n'
            '        , "pg_catalog"."default"\n'
            "        , a.default\n"
            "        , a.values\n"
            "        , a.limit\n"
            "        , a.end\n"
            "    FROM\n"
            "        demo.src AS a;\n"
            "    RETURN NEW;\n"
            "END;\n"
            "$function$;\n"
        )
        violations = SQL_MOD.check_sql(sql)
        self.assertEqual(violations, [], f"不应误报任何规则：{violations}")

    def test_f06_still_flags_lowercase_trigger_ddl_and_returns(self):
        sql = "CREATE trigger trg_x BEFORE INSERT ON demo.t FOR EACH ROW EXECUTE PROCEDURE demo.f_x();\n"
        self.assertIn("F-06", self._rules(sql))
        sql2 = "CREATE OR REPLACE FUNCTION demo.f_x() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END; $$;\n"
        self.assertNotIn("F-06", self._rules(sql2))
        sql3 = "CREATE OR REPLACE FUNCTION demo.f_x() returns trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END; $$;\n"
        self.assertIn("F-06", self._rules(sql3))

    def test_perf29_exempts_special_left_values_and_pure_projections(self):
        sql = wrap_routine(
            params="p_start date",
            input_doc="p_start 起始日期",
            body=(
                "    SELECT\n"
                "        a.created_at::date AS target_date\n"
                "        , NULL::date AS empty_dt\n"
                "        , CURRENT_DATE::timestamp AS cur_ts\n"
                "        , CURRENT_TIMESTAMP::timestamptz AS cur_tz\n"
                "        , LOCALTIMESTAMP::date AS local_d\n"
                "        , LOCALTIME::timestamp AS local_t\n"
                "    FROM\n"
                "        demo.orders AS a\n"
                "    WHERE\n"
                "        a.biz_date >= p_start\n"
                "        AND a.biz_date >= NULL::date\n"
                "        AND a.biz_date <= CURRENT_DATE::date\n"
                "        AND a.biz_date >= CURRENT_TIMESTAMP::date;\n"
                "    RETURN 0;\n"
            ),
        )
        self.assertNotIn("PERF-29", self._rules(sql))
        self.assertEqual(SQL_MOD.check_sql(sql), [])

    def test_perf29_fires_in_where_on_having_and_comparison_lines(self):
        cases = [
            "SELECT a.id FROM demo.t AS a where a.dt::date >= '2026-01-01';\n",
            "SELECT a.id FROM demo.t AS a JOIN demo.b AS b ON b.dt = a.created_at::date;\n",
            "SELECT a.id FROM demo.t AS a GROUP BY a.id, a.created_at HAVING a.created_at::date > '2026-01-01';\n",
            "SELECT a.id FROM demo.t AS a WHERE a.dt::date BETWEEN '2026-01-01' AND '2026-01-31';\n",
            "SELECT a.id FROM demo.t AS a WHERE a.dt::date IS NOT NULL;\n",
            "SELECT CASE WHEN a.dt::date = CURRENT_DATE THEN 1 ELSE 0 END FROM demo.t AS a;\n",
        ]
        for case in cases:
            with self.subTest(case=case.strip()):
                self.assertIn("PERF-29", self._rules(case))

    def test_perf29_does_not_treat_plpgsql_assignment_as_comparison(self):
        sql = wrap_routine(
            declare_block="DECLARE\n    v_dt date;\n",
            body="    v_dt := NEW.created_at::date;\n    RETURN 0;\n",
        )
        self.assertNotIn("PERF-29", self._rules(sql))

    def test_f38_get_diagnostics_logging_only_with_return_zero_is_valid(self):
        sql = wrap_routine(
            output_doc="-1参数异常, 0正常",
            body=(
                "    IF p_flag IS NULL THEN\n"
                "        RETURN -1;\n"
                "    END IF;\n"
                "    DELETE FROM demo.tgt WHERE target_date = CURRENT_DATE;\n"
                "    GET DIAGNOSTICS v_cnt = ROW_COUNT;\n"
                "    RAISE DEBUG 'deleted rows: %', v_cnt;\n"
                "    RETURN 0;\n"
            ),
        )
        self.assertNotIn("F-38", self._rules(sql))
        self.assertEqual(SQL_MOD.check_sql(sql), [])

    def test_f38_fires_when_diag_var_is_returned_without_row_count_output_contract(self):
        sql = wrap_routine(
            declare_block="DECLARE\n    v_total integer := 0;\n",
            output_doc="-1参数异常, 0正常",
            body=(
                "    GET DIAGNOSTICS v_total = ROW_COUNT;\n"
                "    RETURN v_total;\n"
            ),
        )
        self.assertIn("F-38", self._rules(sql))

    def test_f38_allows_minus_one_in_output_on_minimal_stub_and_flags_undeclared_minus_one(self):
        stub = wrap_routine(output_doc="-1参数异常, 0正常", body="    RETURN 0;\n")
        self.assertNotIn("F-38", self._rules(stub))

        undeclared = wrap_routine(output_doc="0正常", body="    RETURN -1;\n")
        self.assertIn("F-38", self._rules(undeclared))

    def test_f39_exempts_plain_update_time_projection_and_catches_updated_time_and_lookback(self):
        non_inc = wrap_routine(
            increment_doc="不适用",
            body=(
                "    INSERT INTO demo.tgt (id, update_time)\n"
                "    SELECT\n"
                "        a.id\n"
                "        , clock_timestamp()\n"
                "    FROM\n"
                "        demo.src AS a;\n"
                "    RETURN 0;\n"
            ),
        )
        self.assertNotIn("F-39", self._rules(non_inc))

        blind1 = wrap_routine(
            increment_doc="不适用",
            body=(
                "    SELECT a.id\n"
                "    FROM demo.src AS a\n"
                "    WHERE a.updated_time >= clock_timestamp() - interval '1 day';\n"
                "    RETURN 0;\n"
            ),
        )
        self.assertIn("F-39", self._rules(blind1))

        blind2 = wrap_routine(
            params="p_lookback_days integer",
            input_doc="p_lookback_days 回看天数",
            increment_doc="不适用",
            body=(
                "    IF p_lookback_days < 0 THEN\n"
                "        RETURN -1;\n"
                "    END IF;\n"
                "    RETURN 0;\n"
            ),
        )
        self.assertIn("F-39", self._rules(blind2))

    def test_f40_update_date_append_formats_and_multiple_lines(self):
        comma_ascii = wrap_routine(update_lines=("2026-11-25, 2026-11-27",))
        self.assertEqual(SQL_MOD.check_sql(comma_ascii), [])

        comma_cjk = wrap_routine(update_lines=("2026-11-25，2026-11-27",))
        self.assertEqual(SQL_MOD.check_sql(comma_cjk), [])

        multi_lines_ok = wrap_routine(update_lines=("2026-11-25", "2026-11-27"))
        self.assertEqual(SQL_MOD.check_sql(multi_lines_ok), [])

        multi_lines_bad = wrap_routine(update_lines=("2026-11-25", "2026/11/27"))
        self.assertIn("F-40", self._rules(multi_lines_bad))

        trailing_comma = wrap_routine(update_lines=("2026-11-25,",))
        self.assertIn("F-40", self._rules(trailing_comma))

        bad_create = wrap_routine(create_date="2026-11-25, 2026-11-27")
        self.assertIn("F-40", self._rules(bad_create))


class FalseNegativeFixesTest(unittest.TestCase):
    maxDiff = None

    def _rules(self, sql: str) -> set[str]:
        return {item["rule"] for item in SQL_MOD.check_sql(sql)}

    def test_multi_function_checks_all_definitions_and_exempts_procedure_from_style01(self):
        good_fn = wrap_routine(name="demo.f_first")
        good_proc = wrap_routine(
            kind="PROCEDURE",
            name="demo.p_batch",
            returns="",
            tag="$procedure$",
            output_doc="无返回值",
            body="    v_cnt := 1;\n",
        )
        self.assertEqual(SQL_MOD.check_sql(good_fn + "\n" + good_proc), [])

        bad_second_fn = (
            good_fn
            + "\n"
            + "CREATE OR REPLACE FUNCTION demo.second_bad(p_flag integer)\n"
            + "RETURNS integer\n"
            + "LANGUAGE plpgsql\n"
            + "AS $function$\n"
            + "BEGIN\n"
            + "    RETURN 0;\n"
            + "END;\n"
            + "$function$;\n"
        )
        rules = self._rules(bad_second_fn)
        self.assertIn("STYLE-01", rules)
        self.assertIn("F-21", rules)

    def test_f32_detects_misalignment_after_comment_end_and_plpgsql_end_if(self):
        sql_comment_end = textwrap.dedent(
            """\
            SELECT
                    a.col1 -- END
                , a.col2
            FROM demo.t AS a;
            """
        )
        self.assertIn("F-32", self._rules(sql_comment_end))

        sql_end_if = textwrap.dedent(
            """\
            CREATE OR REPLACE FUNCTION demo.f_ctrl(p_flag integer)
            RETURNS integer
            LANGUAGE plpgsql
            AS $function$
            /*****************************************************************
            *name       : demo.f_ctrl
            *function   : 控制流后排版
            *input      : p_flag 标志
            *output     : -1参数异常, 0正常
            *increment  : 不适用
            *author     : <team>
            *CreateDate : 2026-11-25
            *UpdateDate : 2026-11-25
            ******************************************************************/
            BEGIN
                IF p_flag = 1 THEN
                    RETURN 0;
                END IF;
                SELECT
                        a.col1
                    , a.col2
                FROM demo.t AS a;
                RETURN 0;
            END;
            $function$;
            """
        )
        self.assertIn("F-32", self._rules(sql_end_if))

    def test_contract_section_body_off_by_one_mid_doc_and_last_line(self):
        # 1. 中间段落：紧贴下一标题前的最后一行（无尾空行）未标证据标签，必须被检出
        mid_doc = textwrap.dedent(
            """\
            ## 假设与缺失输入

            - 假设目标表存在。

            ## SQL

            ```sql
            SELECT 1;
            ```

            ## 静态验证

            - 结构等价。

            ## 风险与未验证项

            - 索引可用性：plan-required。
            - 这条紧贴下一标题的要点没有标签
            ## 自检

            - 通过。
            """
        )
        res_mid = CONTRACT_MOD.check_output("generate", mid_doc)
        self.assertFalse(res_mid["ok"])
        self.assertIn("OUT-LABEL-01", [f["rule"] for f in res_mid["findings"]])

        # 2. 文档最后一行：风险段落位于文档末尾且最后一行无尾换行/无空行，必须被检出
        last_line_doc = (
            "## 假设与缺失输入\n\n- 假设目标表存在。\n\n"
            "## SQL\n\n```sql\nSELECT 1;\n```\n\n"
            "## 静态验证\n\n- 结构等价。\n\n"
            "## 自检\n\n- 通过。\n\n"
            "## 风险与未验证项\n\n"
            "- 索引可用性：plan-required。\n"
            "- 文档最末行缺少标签"
        )
        res_last = CONTRACT_MOD.check_output("generate", last_line_doc)
        self.assertFalse(res_last["ok"])
        rules = [f["rule"] for f in res_last["findings"]]
        self.assertIn("OUT-LABEL-01", rules)
        self.assertIn("OUT-SEQ-02", rules)

        # 文档最末行有标签时应无 OUT-LABEL-01
        last_line_ok = (
            "## 问题表\n\n- 无。\n\n"
            "## 结论\n\n- 无 BLOCKER。\n\n"
            "## 需要 schema / 执行计划 / 负载 / 人工确认的事项\n\n- 无。\n\n"
            "## 性能标签与未验证项\n\n"
            "- 文档最末行已标注：not verified"
        )
        res_last_ok = CONTRACT_MOD.check_output("review", last_line_ok)
        self.assertNotIn("OUT-LABEL-01", [f["rule"] for f in res_last_ok["findings"]])


class OutputContractEvidenceTest(unittest.TestCase):
    maxDiff = None

    @staticmethod
    def _review_with_conclusion(conclusion_body: str) -> str:
        return (
            "## 问题表\n\n- 共 0 条。\n\n"
            f"## 结论\n\n{conclusion_body}\n\n"
            "## 性能标签与未验证项\n\n- 索引可用性：plan-required。\n\n"
            "## 需要 schema / 执行计划 / 负载 / 人工确认的事项\n\n- 需要 DDL。\n"
        )

    def test_fenced_code_claims_are_ignored(self):
        doc = self._review_with_conclusion(
            "- 代码示例内说明不触发。\n\n```sql\n-- 改完之后查询更快，实测通过，已验证，性能已确认\nSELECT 1;\n```"
        )
        res = CONTRACT_MOD.check_output("review", doc)
        self.assertTrue(res["ok"], res)

    def test_negated_and_prohibited_claims_without_backticks_are_exempt(self):
        negated_lines = [
            "- 不得声称更快，收益需负载验证。",
            "- 禁止写实测通过或性能已确认。",
            "- 当前无证据表明已验证。",
            "- 静态检查不代表实测通过，也不可写性能已确认。",
            "- 切勿写成更快，严禁标注已验证。",
        ]
        for line in negated_lines:
            with self.subTest(line=line):
                res = CONTRACT_MOD.check_output("review", self._review_with_conclusion(line))
                self.assertTrue(res["ok"], f"否定语境被误报：{res}")

    def test_positive_and_cross_clause_claims_still_fail(self):
        failing_lines = [
            "- 改完之后查询更快，性能已确认。",
            "- 不能保证无风险，改完之后查询更快。",
            "- 禁止写更快，但实测通过且性能已确认。",
            "- 未来更快属于猜测。",
        ]
        for line in failing_lines:
            with self.subTest(line=line):
                res = CONTRACT_MOD.check_output("review", self._review_with_conclusion(line))
                self.assertFalse(res["ok"], f"未实测断言漏放：{line}")
                self.assertIn("OUT-EVID-01", [f["rule"] for f in res["findings"]])


class HighRiskRulesTest(unittest.TestCase):
    maxDiff = None

    def _rules(self, sql: str) -> set[str]:
        return {item["rule"] for item in SQL_MOD.check_sql(sql)}

    def test_rev_s01_dynamic_sql_value_concat(self):
        bad_direct = wrap_routine(
            params="p_id bigint",
            input_doc="p_id 主键",
            declare_block="DECLARE\n    v_cnt integer := 0;\n",
            body="    EXECUTE 'SELECT count(*) FROM demo.t WHERE id = ' || p_id INTO v_cnt;\n    RETURN 0;\n",
        )
        self.assertIn("REV-S01", self._rules(bad_direct))

        bad_quote_var = wrap_routine(
            params="p_start date",
            input_doc="p_start 日期",
            declare_block="DECLARE\n    v_sql text;\n",
            body=(
                "    v_sql := 'DELETE FROM demo.t WHERE dt >= ''' || p_start || '''';\n"
                "    EXECUTE v_sql;\n"
                "    RETURN 0;\n"
            ),
        )
        self.assertIn("REV-S01", self._rules(bad_quote_var))

        good_using = wrap_routine(
            params="p_start date",
            input_doc="p_start 日期",
            declare_block="DECLARE\n    v_tbl text := 't';\n",
            body=(
                "    EXECUTE format('DELETE FROM demo.%I WHERE dt >= $1', v_tbl)\n"
                "        USING p_start;\n"
                "    RETURN 0;\n"
            ),
        )
        self.assertEqual(SQL_MOD.check_sql(good_using), [])

    def test_rev_s02_format_percent_s_with_execute(self):
        bad = wrap_routine(
            params="p_tbl text",
            input_doc="p_tbl 表名",
            declare_block="DECLARE\n    v_sql text;\n",
            body=(
                "    v_sql := format('DELETE FROM %s WHERE 1 = 1', p_tbl);\n"
                "    EXECUTE v_sql;\n"
                "    RETURN 0;\n"
            ),
        )
        self.assertIn("REV-S02", self._rules(bad))

        good_ident = wrap_routine(
            params="p_tbl text",
            input_doc="p_tbl 表名",
            body=(
                "    EXECUTE format('DELETE FROM %I WHERE 1 = 1', p_tbl);\n"
                "    RETURN 0;\n"
            ),
        )
        self.assertEqual(SQL_MOD.check_sql(good_ident), [])

        good_no_execute = wrap_routine(
            params="p_name text",
            input_doc="p_name 名称",
            declare_block="DECLARE\n    v_msg text;\n",
            body="    v_msg := format('hello %s', p_name);\n    RETURN 0;\n",
        )
        self.assertEqual(SQL_MOD.check_sql(good_no_execute), [])

        good_escaped_pct = wrap_routine(
            params="p_tbl text",
            input_doc="p_tbl 表名",
            body=(
                "    EXECUTE format('SELECT ''%%s'' FROM %I', p_tbl);\n"
                "    RETURN 0;\n"
            ),
        )
        self.assertEqual(SQL_MOD.check_sql(good_escaped_pct), [])

    def test_rev_s03_and_s04_security_definer_search_path(self):
        missing_sp = wrap_routine(security="SECURITY DEFINER\n")
        self.assertIn("REV-S03", self._rules(missing_sp))

        bad_paths = [
            "SECURITY DEFINER\nSET search_path = public, pg_temp\n",
            "SECURITY DEFINER\nSET search_path = demo, pg_temp\n",
            "SECURITY DEFINER\nSET search_path = pg_catalog, pg_temp, demo\n",
            "SECURITY DEFINER\nSET search_path = pg_catalog, public, pg_temp\n",
            "SECURITY DEFINER\nSET search_path = pg_catalog, demo\n",
        ]
        for sec in bad_paths:
            with self.subTest(sec=sec.strip()):
                self.assertIn("REV-S04", self._rules(wrap_routine(security=sec)))

        good_empty = wrap_routine(security="SECURITY DEFINER\nSET search_path = ''\n")
        self.assertEqual(SQL_MOD.check_sql(good_empty), [])

        good_list = wrap_routine(
            security="SECURITY DEFINER\nSET search_path = pg_catalog, demo, pg_temp\n"
        )
        self.assertEqual(SQL_MOD.check_sql(good_list), [])

        good_invoker = wrap_routine(security="SECURITY INVOKER\n")
        self.assertEqual(SQL_MOD.check_sql(good_invoker), [])

    def test_rev_c01_when_others_then_null(self):
        bad = wrap_routine(
            exception_block=(
                "EXCEPTION\n"
                "    WHEN OTHERS THEN\n"
                "        NULL;\n"
            )
        )
        self.assertIn("REV-C01", self._rules(bad))

        good = wrap_routine(
            declare_block="DECLARE\n    v_state text;\n    v_msg text;\n",
            exception_block=(
                "EXCEPTION\n"
                "    WHEN OTHERS THEN\n"
                "        GET STACKED DIAGNOSTICS\n"
                "            v_state = RETURNED_SQLSTATE\n"
                "            , v_msg = MESSAGE_TEXT;\n"
                "        RAISE EXCEPTION 'failed: %', v_msg\n"
                "            USING ERRCODE = v_state;\n"
            ),
        )
        self.assertEqual(SQL_MOD.check_sql(good), [])

        comment_only = wrap_routine(
            body="    -- WHEN OTHERS THEN NULL;\n    RETURN 0;\n"
        )
        self.assertEqual(SQL_MOD.check_sql(comment_only), [])

    def test_generic_pg_checker_does_not_enforce_project_specific_ext_columns(self):
        routine_insert = wrap_routine(
            body=(
                "    INSERT INTO demo.tgt (\n"
                "        target_date\n"
                "        , ext_1\n"
                "    )\n"
                "    SELECT\n"
                "        a.target_date\n"
                "        , NULL\n"
                "    FROM\n"
                "        demo.src AS a;\n"
                "    RETURN 0;\n"
            )
        )
        self.assertNotIn("ENG-31", self._rules(routine_insert))

        routine_select = wrap_routine(
            body=(
                "    SELECT\n"
                "        a.target_date\n"
                "        , a.ext_10\n"
                "    FROM\n"
                "        demo.src AS a;\n"
                "    RETURN 0;\n"
            )
        )
        self.assertNotIn("ENG-31", self._rules(routine_select))

        ddl_only = textwrap.dedent(
            """\
            CREATE TABLE demo.dwd_demo (
                id bigint
                , ext_1 character varying(200)
                , ext_10 character varying(200)
            );
            """
        )
        self.assertNotIn("ENG-31", self._rules(ddl_only))

    def test_inc07_deleted_filter_in_date_derivation_vs_compliant_incremental_template(self):
        bad_array_agg = wrap_routine(
            params="p_lookback_days integer",
            input_doc="p_lookback_days 回看天数",
            increment_doc="update_time 水位线，半开区间 [clock_timestamp()-p_lookback_days, clock_timestamp())",
            declare_block=(
                "DECLARE\n"
                "    v_batch_ts timestamp := clock_timestamp();\n"
                "    v_lookback timestamp;\n"
                "    v_changed_dates date[];\n"
            ),
            body=(
                "    v_lookback := v_batch_ts - (p_lookback_days || ' days')::interval;\n"
                "    SELECT\n"
                "        array_agg(DISTINCT a.target_date)\n"
                "    INTO\n"
                "        v_changed_dates\n"
                "    FROM\n"
                "        demo.src_daily AS a\n"
                "    WHERE\n"
                "        a.update_time >= v_lookback\n"
                "        AND a.update_time < v_batch_ts\n"
                "        AND a.deleted = 0;\n"
                "    RETURN 0;\n"
            ),
        )
        self.assertIn("INC-07", self._rules(bad_array_agg))

        bad_min_updated = wrap_routine(
            params="p_lookback_days integer",
            input_doc="p_lookback_days 回看天数",
            increment_doc="updated_time 水位线",
            declare_block=(
                "DECLARE\n"
                "    v_lookback timestamp := clock_timestamp();\n"
                "    v_start_date date;\n"
            ),
            body=(
                "    SELECT\n"
                "        min(a.target_date)\n"
                "    INTO\n"
                "        v_start_date\n"
                "    FROM\n"
                "        demo.src_daily AS a\n"
                "    WHERE\n"
                "        a.updated_time >= v_lookback\n"
                "        AND a.is_deleted = 0;\n"
                "    RETURN 0;\n"
            ),
        )
        self.assertIn("INC-07", self._rules(bad_min_updated))

        compliant_sparse_incremental = wrap_routine(
            name="demo.f_demo_daily_settlement_d",
            params=(
                "\n    p_flag integer\n"
                "    , p_start_date date\n"
                "    , p_end_date date\n"
                "    , p_lookback_days integer\n"
            ),
            input_doc="p_flag 0=增量 1=按日期区间, p_start_date=开始日期, p_end_date=结束日期, p_lookback_days=回看天数",
            output_doc="-1参数异常, 0正常",
            increment_doc="update_time 水位线，半开区间 [clock_timestamp()-p_lookback_days, clock_timestamp())，按 v_changed_dates 稀疏集合覆盖",
            update_lines=("2026-11-27",),
            declare_block=(
                "DECLARE\n"
                "    v_batch_ts timestamp := clock_timestamp();\n"
                "    v_lookback timestamp;\n"
                "    v_changed_dates date[];\n"
                "    v_state text;\n"
                "    v_msg text;\n"
            ),
            body=(
                "    IF p_flag IS NULL OR p_flag NOT IN (0, 1) THEN\n"
                "        RETURN -1;\n"
                "    END IF;\n"
                "    IF p_lookback_days IS NULL OR p_lookback_days < 0 THEN\n"
                "        RETURN -1;\n"
                "    END IF;\n"
                "    IF p_flag = 1 AND (p_start_date IS NULL OR p_end_date IS NULL OR p_start_date > p_end_date) THEN\n"
                "        RETURN -1;\n"
                "    END IF;\n"
                "\n"
                "    IF p_flag = 0 THEN\n"
                "        v_lookback := v_batch_ts - (p_lookback_days || ' days')::interval;\n"
                "        SELECT\n"
                "            array_agg(DISTINCT a.target_date) FILTER (WHERE a.target_date IS NOT NULL)\n"
                "        INTO\n"
                "            v_changed_dates\n"
                "        FROM\n"
                "            demo.src_daily AS a\n"
                "        WHERE\n"
                "            a.update_time >= v_lookback\n"
                "            AND a.update_time < v_batch_ts;\n"
                "\n"
                "        IF v_changed_dates IS NULL OR array_length(v_changed_dates, 1) IS NULL THEN\n"
                "            RETURN 0;\n"
                "        END IF;\n"
                "\n"
                "        DELETE FROM\n"
                "            demo.dwd_daily_settlement\n"
                "        WHERE\n"
                "            target_date = ANY(v_changed_dates);\n"
                "\n"
                "        INSERT INTO demo.dwd_daily_settlement (\n"
                "            target_date\n"
                "            , company_name\n"
                "            , energy\n"
                "        )\n"
                "        SELECT\n"
                "            a.target_date\n"
                "            , a.company_name\n"
                "            , sum(a.energy)\n"
                "        FROM\n"
                "            demo.src_daily AS a\n"
                "        WHERE\n"
                "            a.target_date = ANY(v_changed_dates)\n"
                "            AND a.deleted = 0\n"
                "        GROUP BY\n"
                "            a.target_date\n"
                "            , a.company_name;\n"
                "    ELSE\n"
                "        DELETE FROM\n"
                "            demo.dwd_daily_settlement\n"
                "        WHERE\n"
                "            target_date >= p_start_date\n"
                "            AND target_date <= p_end_date;\n"
                "\n"
                "        INSERT INTO demo.dwd_daily_settlement (\n"
                "            target_date\n"
                "            , company_name\n"
                "            , energy\n"
                "        )\n"
                "        SELECT\n"
                "            a.target_date\n"
                "            , a.company_name\n"
                "            , sum(a.energy)\n"
                "        FROM\n"
                "            demo.src_daily AS a\n"
                "        WHERE\n"
                "            a.target_date >= p_start_date\n"
                "            AND a.target_date <= p_end_date\n"
                "            AND a.deleted = 0\n"
                "        GROUP BY\n"
                "            a.target_date\n"
                "            , a.company_name;\n"
                "    END IF;\n"
                "    RETURN 0;\n"
            ),
            exception_block=(
                "EXCEPTION\n"
                "    WHEN OTHERS THEN\n"
                "        GET STACKED DIAGNOSTICS\n"
                "            v_state = RETURNED_SQLSTATE\n"
                "            , v_msg = MESSAGE_TEXT;\n"
                "        RAISE EXCEPTION '增量落表执行失败: %', v_msg\n"
                "            USING ERRCODE = v_state;\n"
            ),
        )
        self.assertEqual(SQL_MOD.check_sql(compliant_sparse_incremental), [])


class CliContractPreservedTest(unittest.TestCase):
    def test_sql_checker_cli_json_keys_and_exit_codes(self):
        with tempfile.TemporaryDirectory(prefix="pgfc-cli-") as tmp:
            ok_file = pathlib.Path(tmp) / "ok.sql"
            bad_file = pathlib.Path(tmp) / "bad.sql"
            ok_file.write_bytes(wrap_routine().encode("utf-8"))
            bad_file.write_bytes("SELECT a.id FROM demo.t AS a WHERE a.dt::date >= '2026-01-01';\n".encode("utf-8"))

            ok_proc = subprocess.run(
                [sys.executable, str(SQL_CHECKER), "--json", str(ok_file)],
                capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(ok_proc.returncode, 0, ok_proc.stdout)
            ok_json = json.loads(ok_proc.stdout)
            self.assertEqual(
                set(ok_json.keys()),
                {"ok", "database_connected", "violation_count", "violations", "command"},
            )
            self.assertTrue(ok_json["ok"])
            self.assertFalse(ok_json["database_connected"])
            self.assertEqual(ok_json["violation_count"], 0)

            bad_proc = subprocess.run(
                [sys.executable, str(SQL_CHECKER), "--json", str(bad_file)],
                capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(bad_proc.returncode, 1)
            bad_json = json.loads(bad_proc.stdout)
            self.assertFalse(bad_json["ok"])
            self.assertGreater(bad_json["violation_count"], 0)

            err_proc = subprocess.run(
                [sys.executable, str(SQL_CHECKER), "--json", str(pathlib.Path(tmp) / "missing.sql")],
                capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(err_proc.returncode, 2)

            trailing_file = pathlib.Path(tmp) / "trailing.sql"
            trailing_file.write_bytes("SELECT\n    a.col1,\n    a.col2\nFROM\n    demo.t AS a;\n".encode("utf-8"))
            trailing_proc = subprocess.run(
                [sys.executable, str(SQL_CHECKER), "--json", "--comma-style", "trailing", str(trailing_file)],
                capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(trailing_proc.returncode, 0, trailing_proc.stdout)

    def test_verify_output_contract_cli_and_offline_imports(self):
        forbidden = {
            "psycopg", "psycopg2", "asyncpg", "pg8000", "sqlalchemy",
            "requests", "urllib", "urllib3", "httpx", "http", "socket", "ftplib",
        }
        for script in (SQL_CHECKER, CONTRACT_CHECKER):
            tree = ast.parse(script.read_text(encoding="utf-8"), filename=str(script))
            imported: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
            self.assertEqual(imported & forbidden, set(), script.name)

        doc = (
            "## 问题表\n\n- 无。\n\n"
            "## 结论\n\n- 不得声称更快。\n\n"
            "## 性能标签与未验证项\n\n- 计划：plan-required\n\n"
            "## 需要 schema / 执行计划 / 负载 / 人工确认的事项\n\n- DDL。\n"
        )
        with tempfile.TemporaryDirectory(prefix="pgfc-contract-cli-") as tmp:
            md_path = pathlib.Path(tmp) / "report.md"
            md_path.write_bytes(doc.encode("utf-8"))
            proc = subprocess.run(
                [sys.executable, str(CONTRACT_CHECKER), "--mode", "review", "--file", str(md_path), "--json"],
                capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout)
            data = json.loads(proc.stdout)
            self.assertTrue(data["ok"])
            self.assertEqual(data["findings"], [])


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    unittest.main(verbosity=2)
