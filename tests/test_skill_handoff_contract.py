#!/usr/bin/env python3
"""双技能协同契约回归测试（Function Spec / 一键无重叠双检 / 可移植路径 / Profile）。

覆盖：
  1. check_shenergy_artifacts.py --kind spec (SH-SPEC-01..05)；
  2. check_shenergy_artifacts.py --kind ddl --spec (SH-DDL-10)；
  3. check_shenergy_artifacts.py --kind func --spec (SH-FN-10, SH-FN-11, 自动推断 grain/legacy)；
  4. check_shenergy_artifacts.py --kind func --with-pg-checker (无重叠双层合并：pg-function-craft 与 shenergy-dwd-development)；
  5. generate_validation_sql.py --spec (默认填充 + CLI 覆盖 + 缺失校验)；
  6. 文档契约：shenergy-dwd-development 无写死仓库路径；pg-function-craft 含调用上下文 Profile。

约束：只使用 Python 3.10+ 标准库；不连接数据库、不访问网络。
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
PG_SKILL = REPO_ROOT / "skills" / "pg-function-craft"
SH_SKILL = REPO_ROOT / "skills" / "shenergy-dwd-development"
CHECKER = SH_SKILL / "scripts" / "check_shenergy_artifacts.py"
SQLGEN = SH_SKILL / "scripts" / "generate_validation_sql.py"


def _run_py(script: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )


def _valid_spec() -> dict:
    return {
        "schema_version": "1.0",
        "target_table": "dwd.dwd_elec_settlement_d96",
        "function_name": "dwd.f_dwd_elec_settlement_d96",
        "grain": "day96",
        "date_col": "target_date",
        "unit_col": "transactionunit",
        "target_engine": "pg14",
        "mode": "generate",
        "return_contract": "row_count",
        "legacy": False,
        "increment_mode": "update_time",
        "business_keys": [
            "province",
            "company",
            "transactionunit",
            "target_date",
            "timeperiod",
        ],
        "insert_columns": [
            "province",
            "company",
            "transactionunit",
            "target_date",
            "timeperiod",
            "settlement_energy",
            "settlement_price",
        ],
        "metric_columns": ["settlement_energy", "settlement_price"],
        "sources": [
            {"table": "ods.src_elec_24", "role": "driver", "incremental": True},
            {"table": "dim.dim_public_price", "role": "supplement", "incremental": False},
        ],
        "blood_batch": "batch_20261127",
    }


def _valid_ddl() -> str:
    ext_cols = "\n".join(f"    , ext_{i} numeric(20,6)" for i in range(1, 11))
    ext_comments = "\n".join(
        f'COMMENT ON COLUMN "dwd"."dwd_elec_settlement_d96"."ext_{i}" IS \'扩展{i}\';'
        for i in range(1, 11)
    )
    return (
        "SET client_encoding = 'UTF8';\n"
        "SET search_path = '';\n\n"
        'CREATE TABLE "dwd"."dwd_elec_settlement_d96" (\n'
        "    id serial8 NOT NULL\n"
        '    , province varchar(30) COLLATE "pg_catalog"."default" NOT NULL\n'
        '    , company varchar(256) COLLATE "pg_catalog"."default" NOT NULL\n'
        '    , transactionunit varchar(256) COLLATE "pg_catalog"."default" NOT NULL\n'
        "    , target_date date NOT NULL\n"
        "    , target_yearmonth varchar(10) NOT NULL\n"
        "    , timeperiod varchar(10) NOT NULL\n"
        "    , settlement_energy numeric(20,6)\n"
        "    , settlement_price numeric(20,6)\n"
        f"{ext_cols}\n"
        "    , updated_time timestamp(6) DEFAULT CURRENT_TIMESTAMP NOT NULL\n"
        '    , CONSTRAINT "dwd_elec_settlement_d96_pkey" PRIMARY KEY (id)\n'
        ");\n\n"
        'COMMENT ON TABLE "dwd"."dwd_elec_settlement_d96" IS \'售电结算96点表\';\n'
        'COMMENT ON COLUMN "dwd"."dwd_elec_settlement_d96"."id" IS \'主键\';\n'
        'COMMENT ON COLUMN "dwd"."dwd_elec_settlement_d96"."province" IS \'省份\';\n'
        'COMMENT ON COLUMN "dwd"."dwd_elec_settlement_d96"."company" IS \'公司\';\n'
        'COMMENT ON COLUMN "dwd"."dwd_elec_settlement_d96"."transactionunit" IS \'交易单元\';\n'
        'COMMENT ON COLUMN "dwd"."dwd_elec_settlement_d96"."target_date" IS \'日期\';\n'
        'COMMENT ON COLUMN "dwd"."dwd_elec_settlement_d96"."target_yearmonth" IS \'年月\';\n'
        'COMMENT ON COLUMN "dwd"."dwd_elec_settlement_d96"."timeperiod" IS \'时段\';\n'
        'COMMENT ON COLUMN "dwd"."dwd_elec_settlement_d96"."settlement_energy" IS \'电量\';\n'
        'COMMENT ON COLUMN "dwd"."dwd_elec_settlement_d96"."settlement_price" IS \'电价\';\n'
        f"{ext_comments}\n"
        'COMMENT ON COLUMN "dwd"."dwd_elec_settlement_d96"."updated_time" IS \'更新时间\';\n'
    )


def _compliant_96_func() -> str:
    return """\
CREATE OR REPLACE FUNCTION dwd.f_dwd_elec_settlement_d96(
    p_flag integer
    , p_start_date character varying
    , p_end_date character varying
    , p_lookback_days integer
)
RETURNS integer
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $function$
/*****************************************************************
*name       : dwd.f_dwd_elec_settlement_d96
*function   : 售电结算96点增量与重算
*input      : p_flag 0=增量 1=按日期区间, p_start_date=开始日期, p_end_date=结束日期, p_lookback_days=回看天数
*output     : -1参数异常, >=0影响行数
*increment  : update_time 水位线，半开区间 [clock_timestamp()-p_lookback_days, clock_timestamp())
*author     : <team>
*CreateDate : 2026-11-27
*UpdateDate : 2026-11-27
******************************************************************/

DECLARE
    v_rows integer := 0;
    v_batch_ts timestamp := clock_timestamp();
    v_lookback timestamp;
    v_start_date date;
    v_end_date date;
    v_changed_dates date[];
    v_state text;
    v_msg text;

BEGIN
    IF p_flag IS NULL OR p_flag NOT IN (0, 1) THEN
        RETURN -1;
    END IF;
    IF p_lookback_days IS NULL OR p_lookback_days < 0 THEN
        RETURN -1;
    END IF;

    IF p_flag = 1 THEN
        IF p_start_date IS NULL
           OR p_end_date IS NULL
           OR p_start_date !~ '^\\d{4}-\\d{2}-\\d{2}$'
           OR p_end_date !~ '^\\d{4}-\\d{2}-\\d{2}$' THEN
            RETURN -1;
        END IF;
        v_start_date := p_start_date::date;
        v_end_date := p_end_date::date;
        IF v_start_date > v_end_date THEN
            RETURN -1;
        END IF;
        IF (v_end_date - v_start_date) > 92 THEN
            RAISE EXCEPTION '日期跨度超过 92 天'
                USING ERRCODE = '22023';
        END IF;

        DELETE FROM dwd.dwd_elec_settlement_d96
        WHERE
            target_date >= v_start_date
            AND target_date <= v_end_date;

        INSERT INTO dwd.dwd_elec_settlement_d96 (
            province
            , company
            , transactionunit
            , target_date
            , timeperiod
            , settlement_energy
            , settlement_price
        )
        SELECT
            a.province
            , a.company
            , a.transactionunit
            , a.target_date
            , t.time_part
            , round(coalesce(a.energy, 0) / 4.0, 6)
            , coalesce(round(a.price, 6), p.pub_price)
        FROM
            ods.src_elec_24 AS a
            CROSS JOIN dim.dim_timeperiod_change AS t
            LEFT JOIN dim.dim_public_price AS p
                ON p.target_date = a.target_date
        WHERE
            a.target_date >= v_start_date
            AND a.target_date <= v_end_date
            AND a.time_part = t.time_24
            AND a.deleted = 0;

        GET DIAGNOSTICS v_rows = ROW_COUNT;
    ELSE
        v_lookback := v_batch_ts - (p_lookback_days || ' days')::interval;
        SELECT
            array_agg(DISTINCT a.target_date) FILTER (WHERE a.target_date IS NOT NULL)
        INTO
            v_changed_dates
        FROM
            ods.src_elec_24 AS a
        WHERE
            a.update_time >= v_lookback
            AND a.update_time < v_batch_ts;

        IF v_changed_dates IS NULL OR array_length(v_changed_dates, 1) IS NULL THEN
            RETURN 0;
        END IF;

        DELETE FROM dwd.dwd_elec_settlement_d96
        WHERE
            target_date = ANY(v_changed_dates);

        INSERT INTO dwd.dwd_elec_settlement_d96 (
            province
            , company
            , transactionunit
            , target_date
            , timeperiod
            , settlement_energy
            , settlement_price
        )
        SELECT
            a.province
            , a.company
            , a.transactionunit
            , a.target_date
            , t.time_part
            , round(coalesce(a.energy, 0) / 4.0, 6)
            , coalesce(round(a.price, 6), p.pub_price)
        FROM
            ods.src_elec_24 AS a
            CROSS JOIN dim.dim_timeperiod_change AS t
            LEFT JOIN dim.dim_public_price AS p
                ON p.target_date = a.target_date
        WHERE
            a.target_date = ANY(v_changed_dates)
            AND a.time_part = t.time_24
            AND a.deleted = 0;

        GET DIAGNOSTICS v_rows = ROW_COUNT;
    END IF;

    RETURN v_rows;
EXCEPTION
    WHEN OTHERS THEN
        GET STACKED DIAGNOSTICS
            v_state = RETURNED_SQLSTATE
            , v_msg = MESSAGE_TEXT;
        RAISE EXCEPTION '执行失败: %', v_msg
            USING ERRCODE = v_state;
END;
$function$;
"""


class FunctionSpecCheckTest(unittest.TestCase):
    maxDiff = None

    def _run_spec(self, payload_obj: object) -> tuple[subprocess.CompletedProcess[str], dict]:
        with tempfile.TemporaryDirectory(prefix="sh-spec-") as tmp:
            p = pathlib.Path(tmp) / "spec.json"
            p.write_text(json.dumps(payload_obj, ensure_ascii=False, indent=2), encoding="utf-8")
            proc = _run_py(CHECKER, "--kind", "spec", "--json", str(p))
        return proc, json.loads(proc.stdout)

    def test_valid_spec_passes(self):
        proc, res = self._run_spec(_valid_spec())
        self.assertEqual(proc.returncode, 0, res)
        self.assertTrue(res["ok"])

    def test_spec_rules_sh_spec_01_to_05(self):
        # SH-SPEC-01: missing keys + bad grain/mode
        bad1 = _valid_spec()
        del bad1["sources"]
        bad1["grain"] = "hour"
        bad1["mode"] = "optimize"
        _, r1 = self._run_spec(bad1)
        self.assertIn("SH-SPEC-01", {v["rule"] for v in r1["violations"]})

        # SH-SPEC-02: _d24 table + unqualified fn
        bad2 = _valid_spec()
        bad2["target_table"] = "dwd.dwd_elec_d24"
        bad2["function_name"] = "f_only"
        _, r2 = self._run_spec(bad2)
        self.assertEqual(
            len([v for v in r2["violations"] if v["rule"] == "SH-SPEC-02"]), 2
        )

        # SH-SPEC-03: ext_1 in insert_columns
        bad3 = _valid_spec()
        bad3["insert_columns"].append("ext_1")
        _, r3 = self._run_spec(bad3)
        self.assertIn("SH-SPEC-03", {v["rule"] for v in r3["violations"]})

        # SH-SPEC-04: day96 missing timeperiod & duplicate col
        bad4 = _valid_spec()
        bad4["business_keys"] = ["province", "company", "target_date"]
        bad4["insert_columns"] = ["province", "company", "province"]
        _, r4 = self._run_spec(bad4)
        self.assertIn("SH-SPEC-04", {v["rule"] for v in r4["violations"]})

        # SH-SPEC-05: driver with incremental=False under update_time, or no driver
        bad5 = _valid_spec()
        bad5["sources"] = [{"table": "ods.src_elec_24", "role": "driver", "incremental": False}]
        _, r5 = self._run_spec(bad5)
        self.assertIn("SH-SPEC-05", {v["rule"] for v in r5["violations"]})


class SpecCrossArtifactAndDualGateTest(unittest.TestCase):
    maxDiff = None

    def test_ddl_with_spec_passes_and_catches_missing_col(self):
        with tempfile.TemporaryDirectory(prefix="sh-ddl-spec-") as tmp:
            t = pathlib.Path(tmp)
            spec_p = t / "spec.json"
            ddl_p = t / "ddl.sql"
            spec_p.write_text(json.dumps(_valid_spec()), encoding="utf-8")
            ddl_p.write_text(_valid_ddl(), encoding="utf-8")
            ok_proc = _run_py(CHECKER, "--kind", "ddl", "--spec", str(spec_p), "--json", str(ddl_p))
            self.assertEqual(ok_proc.returncode, 0, ok_proc.stdout)

            bad_spec = _valid_spec()
            bad_spec["insert_columns"].append("missing_metric")
            spec_p.write_text(json.dumps(bad_spec), encoding="utf-8")
            fail_proc = _run_py(CHECKER, "--kind", "ddl", "--spec", str(spec_p), "--json", str(ddl_p))
            self.assertEqual(fail_proc.returncode, 1)
            rules = {v["rule"] for v in json.loads(fail_proc.stdout)["violations"]}
            self.assertIn("SH-DDL-10", rules)

    def test_func_with_spec_checks_column_order_and_drivers(self):
        with tempfile.TemporaryDirectory(prefix="sh-fn-spec-") as tmp:
            t = pathlib.Path(tmp)
            spec_p = t / "spec.json"
            fn_p = t / "func.sql"
            spec_p.write_text(json.dumps(_valid_spec()), encoding="utf-8")
            fn_p.write_text(_compliant_96_func(), encoding="utf-8")

            ok_proc = _run_py(CHECKER, "--kind", "func", "--spec", str(spec_p), "--json", str(fn_p))
            self.assertEqual(ok_proc.returncode, 0, ok_proc.stdout)

            # Reordered columns + missing driver -> SH-FN-10 & SH-FN-11
            bad_spec = _valid_spec()
            bad_spec["insert_columns"] = list(reversed(bad_spec["insert_columns"]))
            bad_spec["sources"].append(
                {"table": "ods.src_missing_driver", "role": "driver", "incremental": True}
            )
            spec_p.write_text(json.dumps(bad_spec), encoding="utf-8")
            fail_proc = _run_py(CHECKER, "--kind", "func", "--spec", str(spec_p), "--json", str(fn_p))
            self.assertEqual(fail_proc.returncode, 1)
            rules = {v["rule"] for v in json.loads(fail_proc.stdout)["violations"]}
            self.assertIn("SH-FN-10", rules)
            self.assertIn("SH-FN-11", rules)

    def test_func_with_spec_auto_infers_legacy_and_month(self):
        monthly_legacy = """\
CREATE OR REPLACE FUNCTION dwd.f_legacy_m(
    p_flag integer
    , p_start_date character varying
    , p_end_date character varying
    , p_lookback_days integer
)
RETURNS smallint
LANGUAGE plpgsql
AS $function$
/*****************************************************************
*name       : dwd.f_legacy_m
*function   : 存量月表
*input      : p_flag 0=增量 1=按月, p_start_date, p_end_date, p_lookback_days
*output     : -1参数异常, 0正常
*increment  : update_time 水位线
*author     : <team>
*CreateDate : 2026-01-01
*UpdateDate : 2026-01-01
******************************************************************/
BEGIN
    DELETE FROM dwd.dwd_legacy_m WHERE target_yearmonth = '2026-01';
    INSERT INTO dwd.dwd_legacy_m (target_yearmonth, energy)
    SELECT target_yearmonth, sum(energy) FROM ods.src_m GROUP BY target_yearmonth;
    RETURN 0;
END;
$function$;
"""
        spec = {
            "target_table": "dwd.dwd_legacy_m",
            "function_name": "dwd.f_legacy_m",
            "grain": "month",
            "return_contract": "status_code",
            "legacy": True,
            "business_keys": ["target_yearmonth"],
            "insert_columns": ["target_yearmonth", "energy"],
            "sources": [{"table": "ods.src_m", "role": "driver", "incremental": True}],
        }
        with tempfile.TemporaryDirectory(prefix="sh-legacy-") as tmp:
            t = pathlib.Path(tmp)
            spec_p = t / "spec.json"
            fn_p = t / "func.sql"
            spec_p.write_text(json.dumps(spec), encoding="utf-8")
            fn_p.write_text(monthly_legacy, encoding="utf-8")
            proc = _run_py(CHECKER, "--kind", "func", "--spec", str(spec_p), "--json", str(fn_p))
            self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_unified_dual_gate_passes_and_deduplicates_overlaps(self):
        with tempfile.TemporaryDirectory(prefix="sh-dual-") as tmp:
            t = pathlib.Path(tmp)
            spec_p = t / "spec.json"
            fn_p = t / "func.sql"
            spec_p.write_text(json.dumps(_valid_spec()), encoding="utf-8")
            fn_p.write_text(_compliant_96_func(), encoding="utf-8")

            # Clean compliant function passes unified dual gate
            ok_proc = _run_py(
                CHECKER,
                "--kind",
                "func",
                "--with-pg-checker",
                "--spec",
                str(spec_p),
                "--json",
                str(fn_p),
            )
            self.assertEqual(ok_proc.returncode, 0, ok_proc.stdout)
            ok_res = json.loads(ok_proc.stdout)
            self.assertTrue(ok_res["ok"])
            self.assertTrue(ok_res["pg_checker_ran"])
            self.assertEqual(ok_res["violation_count"], 0)
            self.assertEqual(ok_res["deduplicated"], [])

            # Combined violation file: PG-only (REV-S03, REV-C01, INC-07) + SH-only (SH-FN-02, SH-FN-04)
            bad_sql = """\
CREATE OR REPLACE FUNCTION dwd.f_dwd_elec_settlement_d96(
    p_flag integer
    , p_start_date character varying
    , p_end_date character varying
    , p_lookback_days integer
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
AS $function$
/*****************************************************************
*name       : dwd.f_dwd_elec_settlement_d96
*function   : 含跨层与重叠违规函数
*input      : p_flag, p_start_date, p_end_date, p_lookback_days
*output     : -1参数异常, >=0影响行数
*increment  : update_time 水位线，半开区间
*author     : <team>
*CreateDate : 2026-11-27
*UpdateDate : 2026-11-27
******************************************************************/
DECLARE
    v_rows integer := 0;
    v_changed_dates date[];
BEGIN
    IF p_flag IS NULL OR p_flag NOT IN (0, 1) OR p_lookback_days < 0 THEN
        RETURN -1;
    END IF;
    IF (p_end_date::date - p_start_date::date) > 92 THEN
        RAISE EXCEPTION 'over 92' USING ERRCODE = '22023';
    END IF;
    SELECT array_agg(DISTINCT a.target_date)
    INTO v_changed_dates
    FROM ods.src_elec_24 AS a
    WHERE a.update_time >= clock_timestamp() - interval '1 day'
      AND a.deleted = 0;

    INSERT INTO dwd.dwd_elec_settlement_d96 (
        province
        , company
        , transactionunit
        , target_date
        , timeperiod
        , settlement_energy
        , ext_1
    )
    SELECT
        a.province
        , a.company
        , a.transactionunit
        , a.target_date
        , t.time_part
        , a.energy
        , NULL::numeric(20,6)
    FROM ods.src_elec_24 AS a
    CROSS JOIN dim.dim_timeperiod_change AS t
    CROSS JOIN generate_series(1, 2) AS g;
    RETURN v_rows;
EXCEPTION
    WHEN OTHERS THEN
        NULL;
END;
$function$;
"""
            bad_p = t / "bad.sql"
            bad_p.write_text(bad_sql, encoding="utf-8")
            fail_proc = _run_py(
                CHECKER,
                "--kind",
                "func",
                "--with-pg-checker",
                "--json",
                str(bad_p),
            )
            self.assertEqual(fail_proc.returncode, 1)
            fail_res = json.loads(fail_proc.stdout)
            by_rule = {v["rule"]: v for v in fail_res["violations"]}

            # Both layers present with single-owner rules (no cross-skill overlap)
            self.assertIn("REV-S03", by_rule)
            self.assertIn("REV-C01", by_rule)
            self.assertIn("INC-07", by_rule)
            self.assertEqual(by_rule["INC-07"].get("source"), "pg-function-craft")
            self.assertIn("SH-FN-02", by_rule)
            self.assertIn("SH-FN-04", by_rule)
            self.assertEqual(by_rule["SH-FN-02"].get("source"), "shenergy-dwd-development")
            self.assertEqual(by_rule["SH-FN-04"].get("source"), "shenergy-dwd-development")
            self.assertNotIn("ENG-31", by_rule)
            self.assertNotIn("SH-FN-09", by_rule)
            self.assertEqual(fail_res["deduplicated"], [])

            # Merged JSON output satisfies report SH-RPT-02 evidence check
            rep_p = t / "report.md"
            rep_p.write_text(
                f"artifacts: bad.sql\ngates: 静态检查通过\n"
                f"```json\n{fail_proc.stdout}\n```\n"
                f"编译验证: ROLLBACK 成功\nopen_questions: 无\nnext: 部署\n",
                encoding="utf-8",
            )
            rep_proc = _run_py(CHECKER, "--kind", "report", "--json", str(rep_p))
            self.assertEqual(rep_proc.returncode, 0, rep_proc.stdout)

    def test_missing_pg_checker_returns_2(self):
        with tempfile.TemporaryDirectory(prefix="sh-missing-pg-") as tmp:
            fn_p = pathlib.Path(tmp) / "func.sql"
            fn_p.write_text(_compliant_96_func(), encoding="utf-8")
            proc = _run_py(
                CHECKER,
                "--kind",
                "func",
                "--pg-checker",
                str(pathlib.Path(tmp) / "no_such_checker.py"),
                "--json",
                str(fn_p),
            )
            self.assertEqual(proc.returncode, 2)


class ValidationSqlSpecTest(unittest.TestCase):
    def test_generate_sql_from_spec_and_override(self):
        with tempfile.TemporaryDirectory(prefix="sh-sqlgen-spec-") as tmp:
            spec_p = pathlib.Path(tmp) / "spec.json"
            spec_p.write_text(json.dumps(_valid_spec()), encoding="utf-8")
            proc = _run_py(
                SQLGEN,
                "--kind",
                "all",
                "--spec",
                str(spec_p),
                "--blood-batch",
                "override_batch_99",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = proc.stdout
            self.assertIn("dwd.dwd_elec_settlement_d96", out)
            self.assertIn("dwd.f_dwd_elec_settlement_d96", out)
            self.assertIn("settlement_energy", out)
            self.assertIn("override_batch_99", out)
            self.assertNotIn("batch_20261127", out)

    def test_missing_spec_and_target_table_returns_2(self):
        proc = _run_py(SQLGEN, "--kind", "compile")
        self.assertEqual(proc.returncode, 2)


class SkillBoundaryDocContractTest(unittest.TestCase):
    def test_shenergy_docs_have_no_hardcoded_repo_script_paths(self):
        for md in sorted(SH_SKILL.rglob("*.md")):
            if md.name == "CHANGELOG.md":
                continue
            text = md.read_text(encoding="utf-8")
            self.assertNotIn(
                "skills/shenergy-dwd-development/scripts/",
                text,
                msg=f"{md.name} 仍硬编码仓库路径 skills/shenergy-dwd-development/scripts/",
            )
            self.assertNotIn(
                "skills/pg-function-craft/scripts/",
                text,
                msg=f"{md.name} 仍硬编码仓库路径 skills/pg-function-craft/scripts/",
            )

    def test_pg_skill_documents_invocation_profile(self):
        text = (PG_SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("调用上下文（Profile）", text)
        for key in ("target_engine", "return_contract", "comma_style", "project_overrides"):
            self.assertIn(key, text)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    unittest.main(verbosity=2)
