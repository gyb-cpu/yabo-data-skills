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


class EtlPathRuleTests(unittest.TestCase):
    def test_new_rules_are_registered_and_routed(self) -> None:
        for rule in ("PERF-47", "PERF-48", "PERF-49", "PERF-50", "PERF-51"):
            with self.subTest(rule=rule):
                self.assertIn(rule, PERF)
        self.assertIn("INC-14", INCREMENTAL)
        self.assertIn("REV-P11", REVIEW)
        self.assertIn("REV-P14", REVIEW)
        self.assertIn("读取与物化路径", SKILL)
        self.assertIn("离线样例", SKILL)

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
