#!/usr/bin/env python3
"""申能 DWD 技能：《售电4表_迁移SOP》规则覆盖回归测试。

锁定 0.0.6 补回的内容（2026-11-25 按 SOP 逐条检索后确定）：

  §2.6 参数校验与返回码；§2.7 数值、空值与无源列；
  §2.4 与 SOP §5.3 模板的取舍规则（min/max 只用于全量，日常用 date[]）；
  §3 五道闸与长度；§4 类型判定与 MySQL→PG 转换；
  §7 三层对账与抽样；§8 血缘 8 条校验；§9 五维审查与 P0 清单。

约束：只使用 Python 标准库；不连接数据库、不访问网络。
"""

from __future__ import annotations

import pathlib
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "shenergy-dwd-development"
FUNC_DOC = SKILL_ROOT / "references" / "函数与验收.md"
FLOW_DOC = SKILL_ROOT / "references" / "流程与门禁.md"
SKILL_MD = SKILL_ROOT / "SKILL.md"


class SopCoverageRules(unittest.TestCase):
    """SOP 明文规则必须在技能文档中可检索到。"""

    @classmethod
    def setUpClass(cls):
        cls.func = FUNC_DOC.read_text(encoding="utf-8")
        cls.flow = FLOW_DOC.read_text(encoding="utf-8")
        cls.skill = SKILL_MD.read_text(encoding="utf-8")

    # --- §2.6 参数校验 ---

    def test_parameter_validation_section_exists(self):
        self.assertIn("2.6 参数校验与返回码", self.func)

    def test_p_flag_range_validated(self):
        self.assertIn("p_flag", self.func)
        self.assertIn("(0, 1)", self.func)

    def test_lookback_days_validated(self):
        self.assertIn("p_lookback_days", self.func)
        self.assertIn("< 0", self.func)

    def test_date_format_validated(self):
        self.assertIn(r"^\d{4}-\d{2}-\d{2}$", self.func)

    def test_inverted_range_validated(self):
        self.assertIn("区间倒置", self.func)
        self.assertIn("v_start_date > v_end_date", self.func)

    def test_span_guard_raises_22023(self):
        self.assertIn("> 92", self.func)
        self.assertIn("22023", self.func)
        self.assertIn("92", self.flow)

    def test_return_codes_documented(self):
        self.assertIn("`-1` 参数非法", self.func)
        self.assertIn("0 行也算正常", self.func)

    def test_increment_is_not_full_load(self):
        self.assertIn("不得把 `p_flag = 0` 当全量", self.func)
        self.assertIn("`p_flag = 0` 不得当全量", self.skill)

    # --- §2.7 数值与空值 ---

    def test_numeric_and_null_section_exists(self):
        self.assertIn("2.7 数值、空值与无源列", self.func)

    def test_price_not_zero_filled(self):
        self.assertIn("不补 0", self.func)
        self.assertIn("不补 0", self.flow)

    def test_weighted_average_formula(self):
        self.assertIn("NULLIF(sum(energy), 0)", self.func)
        self.assertIn("NULLIF(sum(e),0)", self.flow)

    def test_no_source_column_pattern(self):
        self.assertIn("NULL::numeric(20,6)", self.func)
        self.assertIn("-- 无源", self.func)

    def test_month_key_string_comparison(self):
        self.assertIn("YYYY-MM", self.func)
        self.assertIn("漏删首月", self.func)
        self.assertIn("漏删首月", self.flow)

    # --- §2.4 与 SOP §5.3 模板的取舍 ---

    def test_min_max_vs_changed_dates_tradeoff_documented(self):
        self.assertIn("与 SOP §5.3 模板的关系", self.func)
        self.assertIn("只保证「不漏」", self.func)
        self.assertIn("v_changed_dates date[]", self.func)

    def test_changed_dates_is_default_for_daily_increment(self):
        self.assertIn("默认选它", self.func)

    def test_do_not_revert_to_min_max_for_template(self):
        self.assertIn("不要为了贴合 SOP 模板而改回区间写法", self.func)

    # --- §3 命名 ---

    def test_five_gates_present(self):
        self.assertIn("五道闸", self.flow)
        self.assertIn("命中即停", self.flow)

    def test_name_length_limit(self):
        self.assertIn("≤58", self.flow)
        self.assertIn("63", self.flow)

    def test_auto_tokenization_not_used_for_naming(self):
        self.assertIn("自动拆词", self.flow)
        self.assertIn("不得直接定名", self.flow)

    def test_field_library_coverage_gate(self):
        self.assertIn("0 个未找到", self.flow)

    # --- §4 DDL ---

    def test_numeric_precision_rule(self):
        self.assertIn("numeric(20,6)", self.flow)

    def test_yearmonth_is_varchar_10(self):
        self.assertIn("varchar(10)", self.flow)

    def test_serial8_for_id(self):
        self.assertIn("serial8", self.flow)

    def test_mysql_to_pg_conversion_rules(self):
        for token in ("AUTO_INCREMENT", "decimal(p,s)", "ENGINE=", "COMMENT ON COLUMN"):
            self.assertIn(token, self.flow)
        self.assertIn("search_path = ''", self.flow)

    def test_no_drop_on_populated_table(self):
        self.assertIn("禁止 `DROP`", self.flow)

    def test_ddl_self_check(self):
        self.assertIn("建表后自检", self.flow)

    # --- §7 验收 ---

    def test_three_layer_reconciliation(self):
        self.assertIn("三层对账", self.flow)
        self.assertIn("分主体", self.flow)

    def test_sampling_three_scenarios(self):
        self.assertIn("三类抽样校验", self.flow)
        self.assertIn("SAMPLE_NOT_READY", self.flow)
        self.assertIn("分组核对行数", self.flow)

    def test_missing_field_states(self):
        for state in ("NO_ROWS_IN_MONTH", "ALL_NULL", "PARTIAL_NULL",
                      "HARD_NULL_BY_DESIGN", "FIELD_NOT_EXIST"):
            self.assertIn(state, self.flow)

    def test_acceptance_signoff_list(self):
        self.assertIn("验收签收单", self.flow)

    # --- §8 血缘 ---

    def test_blood_eight_checks(self):
        self.assertIn("登记后逐表校验", self.flow)
        for mark in ("①", "⑧"):
            self.assertIn(mark, self.flow)

    def test_blood_column_name_not_beautified(self):
        self.assertIn("不美化", self.flow)

    def test_blood_rollback_documented(self):
        self.assertIn("回滚", self.flow)
        self.assertIn("is_deleted", self.flow)

    # --- §9 交付 ---

    def test_five_dimension_review(self):
        self.assertIn("五维审查", self.flow)
        self.assertIn("static-risk", self.flow)

    def test_equivalence_needs_result_level_diff(self):
        self.assertIn("等价性验证", self.flow)
        self.assertIn("EXCEPT", self.flow)

    def test_change_separation(self):
        self.assertIn("变更分离", self.flow)
        self.assertIn("两个 diff", self.flow)

    def test_p0_checklist(self):
        self.assertIn("P0 清单", self.flow)

    def test_rolled_back_columns_called_out(self):
        self.assertIn("已回退列", self.flow)

    # --- 入口可达性 ---

    def test_skill_md_routes_to_new_rules(self):
        self.assertIn("§2.6", self.skill)
        self.assertIn("§2.7", self.skill)
        self.assertIn("numeric(20,6)", self.skill)

    def test_version_matches_newest_changelog(self):
        changelog = (SKILL_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        for line in self.skill.splitlines():
            if line.startswith("version:"):
                version = line.split(":", 1)[1].strip()
                break
        else:
            self.fail("SKILL.md 缺少 version 字段")
        headings = [
            ln.strip()[3:].strip()
            for ln in changelog.splitlines()
            if ln.startswith("## ")
        ]
        self.assertTrue(headings, msg="CHANGELOG 没有任何版本条目")
        self.assertEqual(version, headings[0].split(" ")[0])


if __name__ == "__main__":
    import sys

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    unittest.main(verbosity=2)
