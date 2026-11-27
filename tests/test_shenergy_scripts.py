#!/usr/bin/env python3
"""申能 DWD 技能新增离线脚本的回归测试。

覆盖范围：
  1. skills/shenergy-dwd-development/scripts/verify_offline.py
  2. skills/shenergy-dwd-development/scripts/check_shenergy_artifacts.py
     - ddl (SH-DDL-01..09)
     - func (SH-FN-01..08, --grain, --legacy)
     - csv (SH-CSV-01..04)
     - report (SH-RPT-01..02)
  3. skills/shenergy-dwd-development/scripts/parse_bi_snapshot.py
     - 真实 stdlib 构建的 .xlsx（多 sheet、sharedStrings 富文本、inlineStr、mergeCells）
     - 物理忽略 I/J/K 列（禁止哨兵值不泄露到 JSON 或 CSV）
     - Col L 分类（empty/pending/named 多表拆分）与 12 列 CSV 输出联动 check_shenergy_artifacts.py
  4. skills/shenergy-dwd-development/scripts/generate_validation_sql.py
     - compile / reconcile / sample / missing / blood / all 与 --out

约束：只使用 Python 3.10+ 标准库；不连接数据库、不访问网络。
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
import zipfile

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "shenergy-dwd-development"
SCRIPTS_DIR = SKILL_ROOT / "scripts"

VERIFY_SCRIPT = SCRIPTS_DIR / "verify_offline.py"
CHECKER_SCRIPT = SCRIPTS_DIR / "check_shenergy_artifacts.py"
PARSER_SCRIPT = SCRIPTS_DIR / "parse_bi_snapshot.py"
SQLGEN_SCRIPT = SCRIPTS_DIR / "generate_validation_sql.py"


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


def _valid_ddl() -> str:
    ext_cols = "\n".join(
        f"    , ext_{i} numeric(20,6)" for i in range(1, 11)
    )
    ext_comments = "\n".join(
        f"COMMENT ON COLUMN \"dwd\".\"dwd_elec_settlement_d96\".\"ext_{i}\" IS '扩展字段{i}';"
        for i in range(1, 11)
    )
    return (
        "SET client_encoding = 'UTF8';\n"
        "SET search_path = '';\n\n"
        'DROP TABLE IF EXISTS "dwd"."dwd_elec_settlement_d96";\n'
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
        'COMMENT ON COLUMN "dwd"."dwd_elec_settlement_d96"."settlement_energy" IS \'结算电量\';\n'
        'COMMENT ON COLUMN "dwd"."dwd_elec_settlement_d96"."settlement_price" IS \'结算电价\';\n'
        f"{ext_comments}\n"
        'COMMENT ON COLUMN "dwd"."dwd_elec_settlement_d96"."updated_time" IS \'更新时间\';\n'
    )


def _valid_daily_func() -> str:
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
*author     : 待补充
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
        IF p_start_date IS NULL OR p_end_date IS NULL
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
            RAISE EXCEPTION '日期跨度超过 92 天，请改用 p_flag = 1 分批执行'
                USING ERRCODE = '22023';
        END IF;

        DELETE FROM dwd.dwd_elec_settlement_d96
        WHERE target_date >= v_start_date
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
            , round(coalesce(a.energy, 0) / 4.0, 6) -- 24 点均分
            , CASE WHEN a.price IS NULL THEN NULL ELSE round(a.price, 6) END
        FROM ods.src_elec_24 AS a
        CROSS JOIN dim.dim_timeperiod_change AS t
        WHERE a.target_date >= v_start_date
          AND a.target_date <= v_end_date
          AND a.time_part = t.time_24
          AND a.deleted = 0;

        GET DIAGNOSTICS v_rows = ROW_COUNT;
    ELSE
        v_lookback := v_batch_ts - (p_lookback_days || ' days')::interval;
        SELECT array_agg(DISTINCT a.target_date) FILTER (WHERE a.target_date IS NOT NULL)
        INTO v_changed_dates
        FROM ods.src_elec_24 AS a
        WHERE a.update_time >= v_lookback
          AND a.update_time < v_batch_ts;

        IF v_changed_dates IS NULL OR array_length(v_changed_dates, 1) IS NULL THEN
            RETURN 0;
        END IF;

        DELETE FROM dwd.dwd_elec_settlement_d96
        WHERE target_date = ANY(v_changed_dates);

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
            , CASE WHEN a.price IS NULL THEN NULL ELSE round(a.price, 6) END
        FROM ods.src_elec_24 AS a
        CROSS JOIN dim.dim_timeperiod_change AS t
        WHERE a.target_date = ANY(v_changed_dates)
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
        RAISE EXCEPTION '执行失败: %', v_msg USING ERRCODE = v_state;
END;
$function$;
"""


def _valid_monthly_func() -> str:
    return """\
CREATE OR REPLACE FUNCTION dwd.f_dwd_elec_settlement_m(
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
*name       : dwd.f_dwd_elec_settlement_m
*function   : 月表结算落表
*input      : p_flag 0=增量 1=按月区间, p_start_date=开始月, p_end_date=结束月, p_lookback_days=回看天数
*output     : -1参数异常, >=0影响行数
*increment  : update_time 水位线，半开区间 [clock_timestamp()-p_lookback_days, clock_timestamp())
*author     : 待补充
*CreateDate : 2026-11-27
*UpdateDate : 2026-11-27
******************************************************************/

DECLARE
    v_rows integer := 0;
    v_batch_ts timestamp := clock_timestamp();
    v_lookback timestamp;
    v_changed_months varchar[];
BEGIN
    IF p_flag IS NULL OR p_flag NOT IN (0, 1) THEN
        RETURN -1;
    END IF;
    IF p_lookback_days IS NULL OR p_lookback_days < 0 THEN
        RETURN -1;
    END IF;

    IF p_flag = 1 THEN
        DELETE FROM dwd.dwd_elec_settlement_m
        WHERE target_yearmonth >= '2026-01'
          AND target_yearmonth <= '2026-03';

        INSERT INTO dwd.dwd_elec_settlement_m (
            target_yearmonth
            , settlement_energy
        )
        SELECT
            a.target_yearmonth
            , round(coalesce(a.energy, 0), 6)
        FROM ods.src_elec_m AS a
        WHERE a.target_yearmonth >= '2026-01'
          AND a.target_yearmonth <= '2026-03'
          AND a.deleted = 0;

        GET DIAGNOSTICS v_rows = ROW_COUNT;
    ELSE
        v_lookback := v_batch_ts - (p_lookback_days || ' days')::interval;
        SELECT array_agg(DISTINCT a.target_yearmonth) FILTER (WHERE a.target_yearmonth IS NOT NULL)
        INTO v_changed_months
        FROM ods.src_elec_m AS a
        WHERE a.update_time >= v_lookback
          AND a.update_time < v_batch_ts;

        IF v_changed_months IS NULL OR array_length(v_changed_months, 1) IS NULL THEN
            RETURN 0;
        END IF;

        DELETE FROM dwd.dwd_elec_settlement_m
        WHERE target_yearmonth = ANY(v_changed_months);

        INSERT INTO dwd.dwd_elec_settlement_m (
            target_yearmonth
            , settlement_energy
        )
        SELECT
            a.target_yearmonth
            , round(coalesce(a.energy, 0), 6)
        FROM ods.src_elec_m AS a
        WHERE a.target_yearmonth = ANY(v_changed_months)
          AND a.deleted = 0;

        GET DIAGNOSTICS v_rows = ROW_COUNT;
    END IF;

    RETURN v_rows;
END;
$function$;
"""


def _build_test_xlsx(path: pathlib.Path) -> None:
    """Build a valid multi-sheet .xlsx purely with Python stdlib zipfile."""
    shared_strings = [
        "省区业态",          # 0
        "数据项",            # 1
        "区块",              # 2
        "口径/说明",         # 3
        "单位",              # 4
        "缺值规则",          # 5
        "取值来源表",        # 6
        "湖北新能源",        # 7
        "结算电量",          # 8
        "出清",              # 9
        "kWh",               # 10
        "COALESCE_0",        # 11
        "ods.t_src_a、ods.t_src_b",  # 12
        "结算电价",          # 13 (built via rich text in XML)
        "待补充",            # 14
        "安徽售电",          # 15
        "FORBIDDEN_COL_I_SECRET",  # 16
        "FORBIDDEN_COL_J_SECRET",  # 17
        "FORBIDDEN_COL_K_SECRET",  # 18
    ]

    si_items = []
    for idx, s in enumerate(shared_strings):
        if idx == 13:
            si_items.append("<si><r><t>结算</t></r><r><t>电价</t></r></si>")
        else:
            si_items.append(f"<si><t>{s}</t></si>")

    shared_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'count="{len(shared_strings)}" uniqueCount="{len(shared_strings)}">'
        + "".join(si_items)
        + "</sst>"
    )

    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<sheets>"
        '<sheet name="目录" sheetId="1" r:id="rId1"/>'
        '<sheet name="BI看" sheetId="2" r:id="rId2"/>'
        "</sheets>"
        "</workbook>"
    )

    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>'
        "</Relationships>"
    )

    sheet1_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>目录</t></is></c></row></sheetData>'
        "</worksheet>"
    )

    # Row 1: header; Rows 2-4: 湖北新能源 (A2:A4 merged!); Row 5: 安徽售电
    # Columns I, J, K hold forbidden sentinel values that MUST be physically ignored.
    sheet2_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>"
        '<row r="1">'
        '<c r="A1" t="s"><v>0</v></c>'
        '<c r="B1" t="s"><v>1</v></c>'
        '<c r="C1" t="s"><v>2</v></c>'
        '<c r="D1" t="s"><v>3</v></c>'
        '<c r="E1" t="s"><v>4</v></c>'
        '<c r="F1" t="s"><v>5</v></c>'
        '<c r="G1" t="inlineStr"><is><t>备注1</t></is></c>'
        '<c r="H1" t="inlineStr"><is><t>备注2</t></is></c>'
        '<c r="I1" t="s"><v>16</v></c>'
        '<c r="J1" t="s"><v>17</v></c>'
        '<c r="K1" t="s"><v>18</v></c>'
        '<c r="L1" t="s"><v>6</v></c>'
        "</row>"
        '<row r="2">'
        '<c r="A2" t="s"><v>7</v></c>'
        '<c r="B2" t="s"><v>8</v></c>'
        '<c r="C2" t="s"><v>9</v></c>'
        '<c r="D2" t="inlineStr"><is><t>按96点分摊</t></is></c>'
        '<c r="E2" t="s"><v>10</v></c>'
        '<c r="F2" t="s"><v>11</v></c>'
        '<c r="I2" t="s"><v>16</v></c>'
        '<c r="J2" t="s"><v>17</v></c>'
        '<c r="K2" t="s"><v>18</v></c>'
        '<c r="L2" t="s"><v>12</v></c>'
        "</row>"
        '<row r="3">'
        '<c r="B3" t="s"><v>13</v></c>'
        '<c r="C3" t="s"><v>9</v></c>'
        '<c r="D3" t="inlineStr"><is><t>原值沿用</t></is></c>'
        '<c r="E3" t="inlineStr"><is><t>元/MWh</t></is></c>'
        '<c r="I3" t="inlineStr"><is><t>FORBIDDEN_COL_I_SECRET</t></is></c>'
        '<c r="L3" t="s"><v>14</v></c>'
        "</row>"
        '<row r="4">'
        '<c r="B4" t="inlineStr"><is><t>偏差考核费用</t></is></c>'
        '<c r="C4" t="inlineStr"><is><t>结算</t></is></c>'
        '<c r="K4" t="inlineStr"><is><t>FORBIDDEN_COL_K_SECRET</t></is></c>'
        "</row>"
        '<row r="5">'
        '<c r="A5" t="s"><v>15</v></c>'
        '<c r="B5" t="inlineStr"><is><t>其他省指标</t></is></c>'
        '<c r="L5" t="inlineStr"><is><t>ods.other_prov</t></is></c>'
        "</row>"
        "</sheetData>"
        '<mergeCells count="1"><mergeCell ref="A2:A4"/></mergeCells>'
        "</worksheet>"
    )

    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", rels_xml)
        zf.writestr("xl/sharedStrings.xml", shared_xml)
        zf.writestr("xl/worksheets/sheet1.xml", sheet1_xml)
        zf.writestr("xl/worksheets/sheet2.xml", sheet2_xml)


class VerifyOfflineTest(unittest.TestCase):
    def test_verify_offline_passes(self):
        proc = _run_py(VERIFY_SCRIPT, "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["database_connected"])
        self.assertEqual(payload["issues"], [])
        self.assertGreaterEqual(payload["files_scanned"], 11)

    def test_verify_offline_negative_checks_in_temp_root(self):
        spec = importlib.util.spec_from_file_location("shenergy_verify", VERIFY_SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)

        with tempfile.TemporaryDirectory(prefix="shenergy-vo-") as tmp:
            fake_root = pathlib.Path(tmp) / "shenergy-dwd-development"
            fake_root.mkdir()
            (fake_root / "references").mkdir()
            (fake_root / "scripts").mkdir()
            (fake_root / "SKILL.md").write_bytes(
                b"---\nname: shenergy-dwd-development\nversion: 0.2.0\ndescription: x\n---\n\n[broken](references/missing.md)\n"
            )
            (fake_root / "CHANGELOG.md").write_bytes(b"## 0.1.0\n")
            (fake_root / ".env.example").write_bytes(b"TARGET_PG_PASSWORD=secret123\n")
            (fake_root / "scripts" / "check_shenergy_artifacts.py").write_bytes(
                b"import psycopg2\n"
            )
            old_root = mod.ROOT
            try:
                mod.ROOT = fake_root
                issues, _, _ = mod.run()
            finally:
                mod.ROOT = old_root

            joined = "\n".join(issues)
            self.assertIn("CHANGELOG.md", joined)
            self.assertIn(".env.example", joined)
            self.assertIn("psycopg2", joined)
            self.assertIn("missing.md", joined)


class CheckShenergyArtifactsTest(unittest.TestCase):
    def _check(self, kind: str, content: bytes | str, *extra: str) -> tuple[int, dict]:
        with tempfile.TemporaryDirectory(prefix=f"sh-{kind}-") as tmp:
            suffix = ".csv" if kind == "csv" else (".md" if kind == "report" else ".sql")
            fp = pathlib.Path(tmp) / f"case{suffix}"
            if isinstance(content, bytes):
                fp.write_bytes(content)
            else:
                fp.write_bytes(content.encode("utf-8"))
            proc = _run_py(CHECKER_SCRIPT, "--kind", kind, "--json", *extra, str(fp))
        return proc.returncode, json.loads(proc.stdout)

    # --- Usage / Error exit 2 ---
    def test_missing_file_returns_2(self):
        proc = _run_py(CHECKER_SCRIPT, "--kind", "ddl", "--json", "does_not_exist_123.sql")
        self.assertEqual(proc.returncode, 2)

    # --- DDL rules SH-DDL-01 .. SH-DDL-09 ---
    def test_ddl_valid_passes(self):
        rc, payload = self._check("ddl", _valid_ddl())
        self.assertEqual(rc, 0, payload)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["database_connected"])
        self.assertEqual(payload["violation_count"], 0)
        self.assertEqual(payload["warning_count"], 0)

    def test_ddl_sh_ddl_01_forbids_d24(self):
        bad = _valid_ddl().replace("dwd_elec_settlement_d96", "dwd_elec_settlement_d24")
        rc, payload = self._check("ddl", bad)
        self.assertEqual(rc, 1)
        self.assertIn("SH-DDL-01", {v["rule"] for v in payload["violations"]})

    def test_ddl_sh_ddl_02_identifier_length_warn_and_error(self):
        warn_col = "c" * 60
        ddl_warn = _valid_ddl().replace(
            "    , settlement_price numeric(20,6)",
            f"    , settlement_price numeric(20,6)\n    , {warn_col} numeric(20,6)",
        ).replace(
            'COMMENT ON COLUMN "dwd"."dwd_elec_settlement_d96"."updated_time"',
            f'COMMENT ON COLUMN "dwd"."dwd_elec_settlement_d96"."{warn_col}" IS \'w\';\n'
            'COMMENT ON COLUMN "dwd"."dwd_elec_settlement_d96"."updated_time"',
        )
        rc, payload = self._check("ddl", ddl_warn)
        self.assertEqual(rc, 0, payload)
        self.assertTrue(payload["ok"])
        self.assertIn("SH-DDL-02", {w["rule"] for w in payload["warnings"]})

        err_col = "c" * 64
        ddl_err = _valid_ddl().replace("settlement_price", err_col)
        rc2, payload2 = self._check("ddl", ddl_err)
        self.assertEqual(rc2, 1)
        self.assertIn("SH-DDL-02", {v["rule"] for v in payload2["violations"]})

    def test_ddl_sh_ddl_03_numeric_precision_and_float(self):
        for bad_type in ("float8", "real", "numeric", "numeric(18,2)"):
            bad = _valid_ddl().replace("settlement_energy numeric(20,6)", f"settlement_energy {bad_type}")
            rc, payload = self._check("ddl", bad)
            self.assertEqual(rc, 1, bad_type)
            self.assertIn("SH-DDL-03", {v["rule"] for v in payload["violations"]})

    def test_ddl_sh_ddl_04_target_yearmonth_type(self):
        bad = _valid_ddl().replace("target_yearmonth varchar(10)", "target_yearmonth date")
        rc, payload = self._check("ddl", bad)
        self.assertEqual(rc, 1)
        self.assertIn("SH-DDL-04", {v["rule"] for v in payload["violations"]})

    def test_ddl_sh_ddl_05_mysql_tokens_and_backticks(self):
        for token in (
            "    , extra_col bigint AUTO_INCREMENT",
            "    , extra_col varchar(10) CHARACTER SET utf8mb4",
            "    , `bad_col` numeric(20,6)",
        ):
            bad = _valid_ddl().replace("    , settlement_price numeric(20,6)", token)
            rc, payload = self._check("ddl", bad)
            self.assertEqual(rc, 1)
            self.assertIn("SH-DDL-05", {v["rule"] for v in payload["violations"]})
        bad_eng = _valid_ddl().replace(");", ") ENGINE=InnoDB;")
        rc, payload = self._check("ddl", bad_eng)
        self.assertEqual(rc, 1)
        self.assertIn("SH-DDL-05", {v["rule"] for v in payload["violations"]})

    def test_ddl_sh_ddl_06_ext_and_updated_time_last(self):
        bad_11 = _valid_ddl().replace(
            "    , updated_time timestamp(6)",
            "    , ext_11 numeric(20,6)\n    , updated_time timestamp(6)",
        )
        rc, payload = self._check("ddl", bad_11)
        self.assertEqual(rc, 1)
        self.assertIn("SH-DDL-06", {v["rule"] for v in payload["violations"]})

        bad_order = _valid_ddl().replace(
            "    , updated_time timestamp(6) DEFAULT CURRENT_TIMESTAMP NOT NULL",
            "    , updated_time timestamp(6) DEFAULT CURRENT_TIMESTAMP NOT NULL\n    , tail_col numeric(20,6)",
        )
        rc2, payload2 = self._check("ddl", bad_order)
        self.assertEqual(rc2, 1)
        self.assertIn("SH-DDL-06", {v["rule"] for v in payload2["violations"]})

    def test_ddl_sh_ddl_07_single_pk(self):
        no_pk = _valid_ddl().replace('    , CONSTRAINT "dwd_elec_settlement_d96_pkey" PRIMARY KEY (id)\n', "")
        rc, payload = self._check("ddl", no_pk)
        self.assertEqual(rc, 1)
        self.assertIn("SH-DDL-07", {v["rule"] for v in payload["violations"]})

        two_pk = _valid_ddl().replace("id serial8 NOT NULL", "id serial8 PRIMARY KEY NOT NULL")
        rc2, payload2 = self._check("ddl", two_pk)
        self.assertEqual(rc2, 1)
        self.assertIn("SH-DDL-07", {v["rule"] for v in payload2["violations"]})

    def test_ddl_sh_ddl_08_comments_required(self):
        no_tbl_cmt = _valid_ddl().replace(
            'COMMENT ON TABLE "dwd"."dwd_elec_settlement_d96" IS \'售电结算96点表\';\n', ""
        )
        rc, payload = self._check("ddl", no_tbl_cmt)
        self.assertEqual(rc, 1)
        self.assertIn("SH-DDL-08", {v["rule"] for v in payload["violations"]})

        no_col_cmt = _valid_ddl().replace(
            'COMMENT ON COLUMN "dwd"."dwd_elec_settlement_d96"."settlement_price" IS \'结算电价\';\n', ""
        )
        rc2, payload2 = self._check("ddl", no_col_cmt)
        self.assertEqual(rc2, 1)
        self.assertIn("SH-DDL-08", {v["rule"] for v in payload2["violations"]})

    def test_ddl_sh_ddl_09_set_headers_required(self):
        no_hdr = _valid_ddl().replace("SET search_path = '';\n", "")
        rc, payload = self._check("ddl", no_hdr)
        self.assertEqual(rc, 1)
        self.assertIn("SH-DDL-09", {v["rule"] for v in payload["violations"]})

    # --- Func rules SH-FN-01 .. SH-FN-08 ---
    def test_func_valid_daily_and_monthly_pass(self):
        rc, payload = self._check("func", _valid_daily_func())
        self.assertEqual(rc, 0, payload)
        rc_m, payload_m = self._check("func", _valid_monthly_func(), "--grain", "month")
        self.assertEqual(rc_m, 0, payload_m)

    def test_func_sh_fn_01_smallint_and_legacy(self):
        bad = _valid_daily_func().replace("RETURNS integer", "RETURNS smallint")
        rc, payload = self._check("func", bad)
        self.assertEqual(rc, 1)
        self.assertIn("SH-FN-01", {v["rule"] for v in payload["violations"]})

        rc_leg, payload_leg = self._check("func", bad, "--legacy")
        self.assertEqual(rc_leg, 0, payload_leg)

        bad2 = _valid_daily_func().replace("RETURNS integer", 'RETURNS "pg_catalog"."int2"')
        rc2, payload2 = self._check("func", bad2)
        self.assertEqual(rc2, 1)
        self.assertIn("SH-FN-01", {v["rule"] for v in payload2["violations"]})

    def test_func_sh_fn_02_forbids_generate_series(self):
        bad = _valid_daily_func().replace(
            "CROSS JOIN dim.dim_timeperiod_change AS t",
            "CROSS JOIN generate_series(1, 96) AS gs(n) -- dim.dim_timeperiod_change",
        )
        rc, payload = self._check("func", bad)
        self.assertEqual(rc, 1)
        self.assertIn("SH-FN-02", {v["rule"] for v in payload["violations"]})

    def test_func_sh_fn_03_timeperiod_requires_dim_table(self):
        bad = _valid_daily_func().replace(
            "CROSS JOIN dim.dim_timeperiod_change AS t",
            "CROSS JOIN dim.other_tp AS t",
        )
        rc, payload = self._check("func", bad)
        self.assertEqual(rc, 1)
        self.assertIn("SH-FN-03", {v["rule"] for v in payload["violations"]})

    def test_func_sh_fn_04_forbids_ext_in_insert_select(self):
        bad_insert = _valid_daily_func().replace(
            ", settlement_price\n        )\n        SELECT",
            ", settlement_price\n            , ext_1\n        )\n        SELECT",
        ).replace(
            "ELSE round(a.price, 6) END\n        FROM",
            "ELSE round(a.price, 6) END\n            , NULL::numeric(20,6)\n        FROM",
        )
        rc_ins, payload_ins = self._check("func", bad_insert)
        self.assertEqual(rc_ins, 1)
        self.assertIn("SH-FN-04", {v["rule"] for v in payload_ins["violations"]})

        bad_select = _valid_daily_func().replace(
            ", CASE WHEN a.price IS NULL THEN NULL ELSE round(a.price, 6) END\n        FROM ods.src_elec_24 AS a",
            ", a.ext_10\n        FROM ods.src_elec_24 AS a",
            1,
        )
        rc_sel, payload_sel = self._check("func", bad_select)
        self.assertEqual(rc_sel, 1)
        self.assertIn("SH-FN-04", {v["rule"] for v in payload_sel["violations"]})

        ok_where = _valid_daily_func().replace(
            "AND a.deleted = 0;",
            "AND a.deleted = 0\n          AND a.ext_1 IS NULL;",
        )
        rc_where, payload_where = self._check("func", ok_where)
        self.assertEqual(rc_where, 0, payload_where)
        self.assertEqual(payload_where["violations"], [])

        ok_subquery_where = ok_where.replace(
            ", CASE WHEN a.price IS NULL THEN NULL ELSE round(a.price, 6) END",
            ", CASE WHEN a.price IS NULL THEN NULL ELSE COALESCE((SELECT max(s.val) FROM ods.sub_tbl AS s WHERE s.target_date = a.target_date AND s.ext_1 IS NULL), round(a.price, 6)) END",
            1,
        )
        rc_sub, payload_sub = self._check("func", ok_subquery_where)
        self.assertEqual(rc_sub, 0, payload_sub)
        self.assertEqual(payload_sub["violations"], [])

    def test_func_sh_fn_05_insert_select_column_count(self):
        bad = _valid_daily_func().replace(
            ", CASE WHEN a.price IS NULL THEN NULL ELSE round(a.price, 6) END\n        FROM ods.src_elec_24 AS a\n        CROSS JOIN dim.dim_timeperiod_change AS t\n        WHERE a.target_date >= v_start_date",
            "\n        FROM ods.src_elec_24 AS a\n        CROSS JOIN dim.dim_timeperiod_change AS t\n        WHERE a.target_date >= v_start_date",
        )
        rc, payload = self._check("func", bad)
        self.assertEqual(rc, 1)
        self.assertIn("SH-FN-05", {v["rule"] for v in payload["violations"]})

        # Ensure comments/strings with commas & nested parens don't break SH-FN-05
        tricky = _valid_daily_func().replace(
            "round(coalesce(a.energy, 0) / 4.0, 6)",
            "round(coalesce(a.energy, 0) / 4.0, 6) -- , comma in comment\n"
            "            + CASE WHEN a.province = 'a,b' THEN 0 ELSE 0 END",
        )
        rc_ok, payload_ok = self._check("func", tricky)
        self.assertEqual(rc_ok, 0, payload_ok)

    def test_func_sh_fn_06_pflag_and_92day_guard(self):
        no_span = _valid_daily_func().replace(
            "IF (v_end_date - v_start_date) > 92 THEN\n"
            "            RAISE EXCEPTION '日期跨度超过 92 天，请改用 p_flag = 1 分批执行'\n"
            "                USING ERRCODE = '22023';\n"
            "        END IF;",
            "",
        )
        rc, payload = self._check("func", no_span)
        self.assertEqual(rc, 1)
        self.assertIn("SH-FN-06", {v["rule"] for v in payload["violations"]})

        no_lookback = _valid_daily_func().replace("p_lookback_days < 0", "FALSE")
        rc2, payload2 = self._check("func", no_lookback)
        self.assertEqual(rc2, 1)
        self.assertIn("SH-FN-06", {v["rule"] for v in payload2["violations"]})

    def test_func_sh_fn_07_incremental_and_no_minmax_between(self):
        bad_minmax = _valid_daily_func().replace(
            "SELECT array_agg(DISTINCT a.target_date) FILTER (WHERE a.target_date IS NOT NULL)\n"
            "        INTO v_changed_dates\n"
            "        FROM ods.src_elec_24 AS a\n"
            "        WHERE a.update_time >= v_lookback\n"
            "          AND a.update_time < v_batch_ts;\n\n"
            "        IF v_changed_dates IS NULL OR array_length(v_changed_dates, 1) IS NULL THEN\n"
            "            RETURN 0;\n"
            "        END IF;\n\n"
            "        DELETE FROM dwd.dwd_elec_settlement_d96\n"
            "        WHERE target_date = ANY(v_changed_dates);",
            "SELECT min(a.target_date), max(a.target_date)\n"
            "        INTO v_start_date, v_end_date\n"
            "        FROM ods.src_elec_24 AS a\n"
            "        WHERE a.update_time >= v_lookback\n"
            "          AND a.update_time < v_batch_ts;\n\n"
            "        DELETE FROM dwd.dwd_elec_settlement_d96\n"
            "        WHERE target_date BETWEEN v_start_date AND v_end_date;",
        ).replace(
            "WHERE a.target_date = ANY(v_changed_dates)",
            "WHERE a.target_date BETWEEN v_start_date AND v_end_date",
        )
        rc, payload = self._check("func", bad_minmax)
        self.assertEqual(rc, 1)
        self.assertIn("SH-FN-07", {v["rule"] for v in payload["violations"]})

        rc_leg, payload_leg = self._check("func", bad_minmax, "--legacy")
        self.assertEqual(rc_leg, 0, payload_leg)

    def test_func_sh_fn_08_yearmonth_comparison(self):
        bad1 = _valid_monthly_func().replace(
            "target_yearmonth >= '2026-01'", "target_yearmonth >= '2026-01-01'"
        )
        rc1, payload1 = self._check("func", bad1, "--grain", "month")
        self.assertEqual(rc1, 1)
        self.assertIn("SH-FN-08", {v["rule"] for v in payload1["violations"]})

        bad2 = _valid_monthly_func().replace(
            "target_yearmonth >= '2026-01'", "target_yearmonth::date >= p_start_date::date"
        )
        rc2, payload2 = self._check("func", bad2, "--grain", "month")
        self.assertEqual(rc2, 1)
        self.assertIn("SH-FN-08", {v["rule"] for v in payload2["violations"]})

    def test_func_inc07_owned_by_pg_checker_via_with_pg_checker(self):
        bad = _valid_daily_func().replace(
            "AND a.update_time < v_batch_ts;",
            "AND a.update_time < v_batch_ts\n          AND a.deleted = 0;",
        )
        rc_standalone, payload_standalone = self._check("func", bad)
        self.assertEqual(rc_standalone, 0, payload_standalone)
        self.assertEqual(payload_standalone["violations"], [])

        rc_dual, payload_dual = self._check("func", bad, "--with-pg-checker")
        self.assertEqual(rc_dual, 1, payload_dual)
        by_rule = {v["rule"]: v for v in payload_dual["violations"]}
        self.assertIn("INC-07", by_rule)
        self.assertEqual(by_rule["INC-07"].get("source"), "pg-function-craft")
        self.assertNotIn("SH-FN-09", by_rule)

    # --- CSV rules SH-CSV-01 .. SH-CSV-04 ---
    def test_csv_rules_pos_and_neg(self):
        header = "目标表,区块,物理序号,英文名称,中文名称（BI看）,库注释,BI看行,取值来源表,取值来源表字段,口径/说明,单位,缺值规则\n"
        good_row = "dwd_a,出清,1,settlement_energy,结算电量,01结算电量,2,ods.t,energy,按口径,kWh,COALESCE_0\n"
        rc, payload = self._check("csv", (header + good_row).encode("utf-8"))
        self.assertEqual(rc, 0, payload)

        # SH-CSV-01 BOM
        rc_bom, p_bom = self._check("csv", b"\xef\xbb\xbf" + (header + good_row).encode("utf-8"))
        self.assertEqual(rc_bom, 1)
        self.assertIn("SH-CSV-01", {v["rule"] for v in p_bom["violations"]})

        # SH-CSV-02 wrong header
        rc_hdr, p_hdr = self._check("csv", "目标表,错误头\n1,2\n".encode("utf-8"))
        self.assertEqual(rc_hdr, 1)
        self.assertIn("SH-CSV-02", {v["rule"] for v in p_hdr["violations"]})

        # SH-CSV-03 wrong col count / empty required col
        rc_col, p_col = self._check("csv", (header + "dwd_a,出清,1,col_a,\n").encode("utf-8"))
        self.assertEqual(rc_col, 1)
        self.assertIn("SH-CSV-03", {v["rule"] for v in p_col["violations"]})

        rc_empty, p_empty = self._check(
            "csv",
            (header + ",出清,1,col_a,,注释,2,ods.t,f,口径,kWh,0\n").encode("utf-8"),
        )
        self.assertEqual(rc_empty, 1)
        self.assertIn("SH-CSV-03", {v["rule"] for v in p_empty["violations"]})

        # SH-CSV-04 ext_1 in 英文名称
        rc_ext, p_ext = self._check(
            "csv",
            (header + "dwd_a,出清,1,ext_3,扩展列3,注释,2,ods.t,f,口径,kWh,0\n").encode("utf-8"),
        )
        self.assertEqual(rc_ext, 1)
        self.assertIn("SH-CSV-04", {v["rule"] for v in p_ext["violations"]})

    # --- Report rules SH-RPT-01 .. SH-RPT-02 ---
    def test_report_rules_pos_and_neg(self):
        good_rpt = (
            "# 评审报告\n"
            "- artifacts: 计算脚本/dwd_a.sql\n"
            "- gates: 静态检查通过\n"
            '  `{"ok": true, "violation_count": 0, "violations": []}`\n'
            "  已在事务内编译验证并通过 ROLLBACK 确认。\n"
            "- open_questions: 无\n"
            "- next: 提交验收\n"
        )
        rc, payload = self._check("report", good_rpt)
        self.assertEqual(rc, 0, payload)

        # SH-RPT-01 missing key
        bad1 = "- artifacts: a\n- gates: b\n- next: c\n"
        rc1, p1 = self._check("report", bad1)
        self.assertEqual(rc1, 1)
        self.assertIn("SH-RPT-01", {v["rule"] for v in p1["violations"]})

        # SH-RPT-02 claiming pass without JSON tokens or ROLLBACK
        bad2 = (
            "- artifacts: a\n"
            "- gates: 已完成静态检查\n"
            "- open_questions: 无\n"
            "- next: 下一步\n"
        )
        rc2, p2 = self._check("report", bad2)
        self.assertEqual(rc2, 1)
        self.assertIn("SH-RPT-02", {v["rule"] for v in p2["violations"]})

        # Negated mention should NOT false-positive
        negated_ok = (
            "- artifacts: a\n"
            "- gates: 无检查器输出，不得写「已完成静态检查」\n"
            "- open_questions: 待运行静检\n"
            "- next: 运行 check_sql_output.py\n"
        )
        rc3, p3 = self._check("report", negated_ok)
        self.assertEqual(rc3, 0, p3)


class ParseBiSnapshotTest(unittest.TestCase):
    def test_parse_xlsx_ignores_ijk_merges_and_outputs_valid_csv(self):
        with tempfile.TemporaryDirectory(prefix="sh-xlsx-") as tmp:
            tmp_dir = pathlib.Path(tmp)
            xlsx_path = tmp_dir / "snapshot.xlsx"
            csv_path = tmp_dir / "out.csv"
            _build_test_xlsx(xlsx_path)

            proc = _run_py(
                PARSER_SCRIPT,
                str(xlsx_path),
                "--sheet",
                "BI看",
                "--province",
                "湖北",
                "--business",
                "新能源",
                "--out-csv",
                str(csv_path),
                "--json",
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            payload = json.loads(proc.stdout)

            self.assertTrue(payload["ok"])
            self.assertFalse(payload["database_connected"])
            self.assertEqual(payload["ignored_columns"], ["I", "J", "K"])
            self.assertEqual(payload["header_row"], 1)
            self.assertEqual(payload["merge_ranges"], ["A2:A4"])
            self.assertEqual(payload["row_count"], 3)
            self.assertEqual(
                payload["l_summary"], {"empty": 1, "pending": 1, "named": 1}
            )

            # Verify rich text and merged propagation
            rows = payload["rows"]
            self.assertEqual(rows[0]["cells"]["A"], "湖北新能源")
            self.assertEqual(rows[0]["source_status"], "named")
            self.assertEqual(
                rows[0]["source_tables"], ["ods.t_src_a", "ods.t_src_b"]
            )
            self.assertEqual(rows[1]["cells"]["A"], "湖北新能源")
            self.assertEqual(rows[1]["cells"]["B"], "结算电价")
            self.assertEqual(rows[1]["source_status"], "pending")
            self.assertEqual(rows[2]["cells"]["A"], "湖北新能源")
            self.assertEqual(rows[2]["source_status"], "empty")

            # Verify physical exclusion of I/J/K sentinel strings
            for secret in (
                "FORBIDDEN_COL_I_SECRET",
                "FORBIDDEN_COL_J_SECRET",
                "FORBIDDEN_COL_K_SECRET",
            ):
                self.assertNotIn(secret, proc.stdout)
                csv_text = csv_path.read_text(encoding="utf-8")
                self.assertNotIn(secret, csv_text)

            # Verify CSV encoding (no BOM, LF) and check_shenergy_artifacts --kind csv
            raw_csv = csv_path.read_bytes()
            self.assertFalse(raw_csv.startswith(b"\xef\xbb\xbf"))
            self.assertNotIn(b"\r\n", raw_csv)
            chk = _run_py(CHECKER_SCRIPT, "--kind", "csv", "--json", str(csv_path))
            self.assertEqual(chk.returncode, 0, chk.stdout + chk.stderr)
            chk_payload = json.loads(chk.stdout)
            self.assertTrue(chk_payload["ok"])

    def test_missing_sheet_returns_2(self):
        with tempfile.TemporaryDirectory(prefix="sh-xlsx-err-") as tmp:
            xlsx_path = pathlib.Path(tmp) / "snapshot.xlsx"
            _build_test_xlsx(xlsx_path)
            proc = _run_py(PARSER_SCRIPT, str(xlsx_path), "--sheet", "不存在的Sheet", "--json")
            self.assertEqual(proc.returncode, 2)


class GenerateValidationSqlTest(unittest.TestCase):
    def test_all_kinds_and_file_output(self):
        with tempfile.TemporaryDirectory(prefix="sh-sqlgen-") as tmp:
            out_sql = pathlib.Path(tmp) / "all_checks.sql"
            proc = _run_py(
                SQLGEN_SCRIPT,
                "--kind",
                "all",
                "--target-table",
                "dwd.dwd_elec_settlement_d96",
                "--function-name",
                "dwd.f_dwd_elec_settlement_d96",
                "--key-cols",
                "province,company,transactionunit,target_date,timeperiod",
                "--metric-cols",
                "settlement_energy",
                "settlement_electricfee",
                "--grain",
                "day96",
                "--blood-batch",
                "batch_20261127",
                "--out",
                str(out_sql),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            raw = out_sql.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
            self.assertNotIn(b"\r\n", raw)
            text = raw.decode("utf-8")

            # compile
            self.assertIn("BEGIN;", text)
            self.assertIn("ROLLBACK;", text)
            self.assertIn("pg_get_functiondef", text)
            # reconcile
            self.assertIn("FULL OUTER JOIN", text)
            self.assertIn("1e-6", text)
            self.assertIn("24->96", text)
            self.assertIn("count(DISTINCT timeperiod) <> 96", text)
            # sample
            self.assertIn("SAMPLE_NOT_READY", text)
            self.assertIn("960", text)
            # missing
            for state in (
                "NO_ROWS_IN_MONTH",
                "ALL_NULL",
                "PARTIAL_NULL",
                "HARD_NULL_BY_DESIGN",
                "FIELD_NOT_EXIST",
            ):
                self.assertIn(state, text)
            self.assertIn("CROSS JOIN", text)
            # blood
            self.assertIn("dim.dim_dictionary_blood", text)
            self.assertIn("dim.dim_dictionary_blood2", text)
            self.assertIn("batch_20261127", text)
            self.assertIn("is_deleted = 1", text)

    def test_individual_modes_and_month_grain(self):
        for kind in ("compile", "reconcile", "sample", "missing", "blood"):
            proc = _run_py(
                SQLGEN_SCRIPT,
                "--kind",
                kind,
                "--target-table",
                "dwd.dwd_elec_settlement_m",
                "--function-name",
                "dwd.f_dwd_elec_settlement_m",
                "--grain",
                "month",
            )
            self.assertEqual(proc.returncode, 0, f"{kind}: {proc.stderr}")
            self.assertIn(f"[{kind}]", proc.stdout)
        proc_m = _run_py(
            SQLGEN_SCRIPT,
            "--kind",
            "missing",
            "--target-table",
            "dwd.dwd_elec_settlement_m",
            "--function-name",
            "dwd.f_dwd_elec_settlement_m",
            "--grain",
            "month",
        )
        self.assertIn("target_yearmonth", proc_m.stdout)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    unittest.main(verbosity=2)
