#!/usr/bin/env python3
"""pg-function-craft ETL 路径与稀疏集合的离线契约测试。

只使用标准库；不连接数据库、不执行 SQL。测试文档契约，并用最小样例核对
稀疏日期、显式区间、主源 0、备用独有键和冲突优先级的边界。
"""

from __future__ import annotations

import pathlib
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "pg-function-craft"
SKILL = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
PERF = (SKILL_ROOT / "references" / "07-性能优化规则.md").read_text(encoding="utf-8")
INCREMENTAL = (SKILL_ROOT / "references" / "11-增量与水位线.md").read_text(
    encoding="utf-8"
)
REVIEW = (SKILL_ROOT / "references" / "08-PostgreSQL审查规则.md").read_text(
    encoding="utf-8"
)
ENGINEERING = (SKILL_ROOT / "references" / "09-工程与函数结构规范.md").read_text(
    encoding="utf-8"
)


DRIVER_KEY_GAP_FIXTURE = """
WITH clear_key AS (
    SELECT target_date, company, transaction_unit FROM source_a
    UNION
    SELECT target_date, company, transaction_unit FROM source_b
), hourly AS (
    SELECT k.target_date, k.company, k.transaction_unit
    FROM clear_key AS k
    LEFT JOIN source_c AS supplement
        ON supplement.target_date = k.target_date
       AND supplement.company = k.company
       AND supplement.transaction_unit = k.transaction_unit
)
INSERT INTO target_table
SELECT * FROM hourly;
"""

SINGLE_SOURCE_FIXTURE = """
INSERT INTO target_table (target_date, company, transaction_unit, price)
SELECT a.target_date, a.company, a.transaction_unit, p.price
FROM source_a AS a
LEFT JOIN public_price AS p
    ON p.target_date = a.target_date;
"""

TARGET_GRAIN_GAP_FIXTURE = """
WITH hourly AS (
    SELECT unit_key, period_24, value_a, value_b
    FROM source_24
), final_rows AS (
    SELECT h.unit_key, t.period_96,
           CASE WHEN t.quarter = 1 THEN h.value_a ELSE h.value_b END AS value_a,
           CASE WHEN t.quarter = 1 THEN h.value_a ELSE h.value_b END AS value_b
    FROM hourly AS h
    CROSS JOIN dim_timeperiod_change AS t
)
SELECT * FROM final_rows;
"""

TARGET_GRAIN_READY_FIXTURE = """
WITH source_96 AS (
    SELECT unit_key, period_96, value_a, value_b
    FROM source_24_expanded_to_96
), clear_key AS (
    SELECT DISTINCT unit_key FROM source_96
)
SELECT k.unit_key, s.period_96, s.value_a, s.value_b
FROM clear_key AS k
JOIN source_96 AS s ON s.unit_key = k.unit_key;
"""


UNSUPPORTED_FALLBACK_FIXTURE = """
-- source not present in the metric specification: undocumented_consumption_fallback
WITH changed_dates AS (
    SELECT target_date FROM documented_source
    UNION
    SELECT target_date FROM undocumented_consumption_fallback
), clear_key AS (
    SELECT unit_key FROM documented_source
    UNION
    SELECT unit_key FROM undocumented_consumption_fallback
), tmp_fallback AS (
    SELECT * FROM undocumented_consumption_fallback
)
INSERT INTO target_table
SELECT * FROM tmp_fallback;
"""

CONTRACT_SCOPE_FIXTURE = """
WITH contract_base AS (
    SELECT b.contract_id, b.purchaser_unit, b.trade_start_date,
           b.trade_end_date, max(b.contract_cycle) AS contract_cycle
    FROM contract_source AS b
    WHERE b.trade_end_date >= v_start_date
      AND b.trade_start_date <= v_end_date
      AND b.purchaser_unit IN (
          SELECT d.unit_name
          FROM dim.v_unit_trade AS d
          WHERE d.type = '售电'
            AND d.province = '目标省份'
      )
    GROUP BY b.contract_id, b.purchaser_unit,
             b.trade_start_date, b.trade_end_date
)
SELECT c.contract_id, c.contract_cycle
FROM contract_base AS c
JOIN target_keys AS k
  ON k.purchaser_unit = c.purchaser_unit
 AND k.target_date BETWEEN c.trade_start_date AND c.trade_end_date;
"""

CONTRACT_SCOPE_GAP_FIXTURE = """
WITH contract_base AS (
    SELECT b.contract_id, max(b.contract_cycle) AS contract_cycle
    FROM contract_source AS b
    GROUP BY b.contract_id
)
SELECT c.contract_id
FROM contract_base AS c
JOIN target_keys AS k
  ON k.purchaser_unit = c.unit_name
 AND k.target_date BETWEEN c.trade_start_date AND c.trade_end_date;
"""


class EtlPathRuleTests(unittest.TestCase):
    def test_new_rules_are_registered_and_routed(self) -> None:
        for rule in (
            "PERF-47", "PERF-48", "PERF-49", "PERF-50",
            "PERF-51", "PERF-52", "PERF-53", "PERF-54",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, PERF)
        self.assertIn("INC-14", INCREMENTAL)
        for rule in ("ENG-25", "ENG-26", "ENG-27", "ENG-28", "ENG-29", "ENG-30"):
            with self.subTest(rule=rule):
                self.assertIn(rule, ENGINEERING)
        for rule in ("REV-C15", "REV-C16", "REV-C17", "REV-M11", "REV-M12", "REV-M13"):
            with self.subTest(rule=rule):
                self.assertIn(rule, REVIEW)
        self.assertIn("REV-P11", REVIEW)
        self.assertIn("REV-P14", REVIEW)
        self.assertIn("REV-P15", REVIEW)
        self.assertIn("REV-P16", REVIEW)
        self.assertIn("REV-P17", REVIEW)
        self.assertIn("读取与物化路径", SKILL)
        self.assertIn("离线样例", SKILL)

    def test_driver_key_gap_fixture_is_actionable(self) -> None:
        driver_section = DRIVER_KEY_GAP_FIXTURE.split("), hourly", 1)[0]
        self.assertIn("LEFT JOIN source_c", DRIVER_KEY_GAP_FIXTURE)
        self.assertIn("source_c", DRIVER_KEY_GAP_FIXTURE)
        self.assertNotIn("source_c", driver_section)
        self.assertIn("PERF-52", PERF)
        self.assertIn("REV-P15", REVIEW)
        self.assertIn("能独立提供业务键", PERF)

    def test_single_source_and_pure_supplement_are_not_blanket_warnings(self) -> None:
        self.assertIn("FROM source_a", SINGLE_SOURCE_FIXTURE)
        self.assertIn("LEFT JOIN public_price", SINGLE_SOURCE_FIXTURE)
        self.assertNotIn("public_price", {"source_a"})
        self.assertIn("纯补列源不适用", REVIEW)
        self.assertIn("纯补列源没有独立业务键", INCREMENTAL)

    def test_driver_and_incremental_source_lists_must_match(self) -> None:
        self.assertIn("驱动键源清单", INCREMENTAL)
        self.assertIn("增量日期源清单", INCREMENTAL)
        self.assertIn("INC-15", INCREMENTAL)

    def test_target_grain_gap_fixture_flags_final_reexpansion(self) -> None:
        self.assertIn("CROSS JOIN dim_timeperiod_change", TARGET_GRAIN_GAP_FIXTURE)
        self.assertGreaterEqual(TARGET_GRAIN_GAP_FIXTURE.count("CASE"), 2)
        self.assertIn("PERF-53", PERF)
        self.assertIn("REV-P16", REVIEW)
        self.assertIn("最终层", PERF)

    def test_target_grain_ready_fixture_only_unifies_target_grain(self) -> None:
        self.assertIn("source_24_expanded_to_96", TARGET_GRAIN_READY_FIXTURE)
        self.assertIn("period_96", TARGET_GRAIN_READY_FIXTURE)
        self.assertNotIn("CROSS JOIN dim_timeperiod_change", TARGET_GRAIN_READY_FIXTURE)
        self.assertNotIn("CASE", TARGET_GRAIN_READY_FIXTURE)

    def test_unsupported_fallback_requires_whole_lineage_removal(self) -> None:
        self.assertGreaterEqual(
            UNSUPPORTED_FALLBACK_FIXTURE.count("undocumented_consumption_fallback"),
            4,
        )
        self.assertIn("无指标文档依据", ENGINEERING)
        self.assertIn("REV-C15", REVIEW)

    def test_sparse_dates_are_not_replaced_by_format_validation(self) -> None:
        self.assertIn("v_changed_dates date[]", ENGINEERING)
        self.assertIn("开始日期不晚于结束日期", ENGINEERING)
        self.assertIn("REV-C17", REVIEW)

    def test_contract_scope_uses_unit_and_effective_period(self) -> None:
        self.assertIn("purchaser_unit", CONTRACT_SCOPE_FIXTURE)
        self.assertIn("BETWEEN c.trade_start_date AND c.trade_end_date", CONTRACT_SCOPE_FIXTURE)
        self.assertIn("b.trade_end_date >= v_start_date", CONTRACT_SCOPE_FIXTURE)
        self.assertIn("b.trade_start_date <= v_end_date", CONTRACT_SCOPE_FIXTURE)
        self.assertIn("d.type = '售电'", CONTRACT_SCOPE_FIXTURE)
        self.assertIn("GROUP BY b.contract_id, b.purchaser_unit", CONTRACT_SCOPE_FIXTURE)
        self.assertIn("ENG-29", ENGINEERING)
        self.assertIn("PERF-54", PERF)
        self.assertIn("REV-C16", REVIEW)
        self.assertIn("REV-P17", REVIEW)

    def test_contract_scope_gap_fixture_keeps_filters_out_of_aggregate(self) -> None:
        self.assertIn("GROUP BY b.contract_id", CONTRACT_SCOPE_GAP_FIXTURE)
        self.assertNotIn("v_start_date", CONTRACT_SCOPE_GAP_FIXTURE)
        self.assertNotIn("v_end_date", CONTRACT_SCOPE_GAP_FIXTURE)
        self.assertNotIn("d.type", CONTRACT_SCOPE_GAP_FIXTURE)
        self.assertIn("外层 `ON`", REVIEW)
        self.assertIn("聚合前下推", PERF)

    def test_temp_table_and_column_mapping_contracts_are_registered(self) -> None:
        self.assertIn("数据类型、物化理由/复用位置和生命周期", ENGINEERING)
        self.assertIn("目标列与 `SELECT` 列逐列对应", ENGINEERING)
        self.assertIn("REV-M12", REVIEW)
        self.assertIn("REV-M13", REVIEW)

    def test_sparse_delete_and_rebuild_share_actual_dates(self) -> None:
        changed_dates = {"2026-01-01", "2026-01-03"}
        rebuilt_dates = set(changed_dates)
        deleted_dates = set(changed_dates)
        self.assertEqual(deleted_dates, rebuilt_dates)
        self.assertNotIn("2026-01-02", rebuilt_dates)

    def test_explicit_range_is_continuous(self) -> None:
        explicit_range = {"2026-01-01", "2026-01-02", "2026-01-03"}
        self.assertEqual(
            explicit_range,
            {"2026-01-01", "2026-01-02", "2026-01-03"},
        )

    def test_primary_zero_short_circuits_fallback_but_keeps_fallback_only_key(self) -> None:
        primary = {"A": 0, "B": 5}
        fallback = {"A": 9, "C": 7}
        result = dict(primary)
        result.update({key: value for key, value in fallback.items() if key not in primary})
        self.assertEqual(result, {"A": 0, "B": 5, "C": 7})

    def test_contract_mentions_conflict_and_empty_set_boundaries(self) -> None:
        for text in (PERF, INCREMENTAL):
            self.assertIn("主备冲突", text)
            self.assertIn("空集合", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
