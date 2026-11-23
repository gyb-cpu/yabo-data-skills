#!/usr/bin/env python3
"""申能 DWD 技能：时段换算方向规则回归测试。

锁定 2026-11-23 补入的规则（依据原始《售电4表_迁移SOP》§2.6）：

源为 24 点、目标表有 `timeperiod` 时必须展开为 96 点：
  - 电量 `/4.0` 均分；
  - 电价原值沿用；
  - 不得建 `_d24`；
  - 不得把 96 点源降采样成 24 点后复制回 96 槽。

这些规则原本在 SOP 中有明文，整理成技能时遗漏，导致独立推导时
在「价格字段该存 96 点原值还是小时加权值」上产生分叉。

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


class TimeperiodConversionRules(unittest.TestCase):
    """时段换算方向必须在三处文档中可检索到。"""

    @classmethod
    def setUpClass(cls):
        cls.func = FUNC_DOC.read_text(encoding="utf-8")
        cls.flow = FLOW_DOC.read_text(encoding="utf-8")
        cls.skill = SKILL_MD.read_text(encoding="utf-8")

    def test_function_doc_has_conversion_section(self):
        """函数与验收.md 必须有独立的换算方向章节。"""
        self.assertIn("2.1 时段换算方向", self.func)

    def test_energy_divided_by_four(self):
        """24→96 电量必须明确 /4.0 均分。"""
        self.assertIn("energy / 4.0", self.func)
        self.assertIn("/4.0", self.flow)

    def test_price_kept_unchanged(self):
        """24→96 电价必须明确原值沿用，而非加权降采样。"""
        self.assertIn("原值沿用", self.func)
        self.assertIn("原值沿用", self.flow)

    def test_no_d24_table_allowed(self):
        """不得建 _d24 表。"""
        self.assertIn("_d24", self.func)
        self.assertIn("_d24", self.flow)

    def test_no_downsample_then_copy(self):
        """不得把 96 点源降采样后复制回 96 槽。"""
        self.assertIn("降采样", self.func)
        self.assertIn("降采样", self.flow)

    def test_daily_sum_conservation_required(self):
        """展开后必须验算日合计不变。"""
        self.assertIn("日合计不变", self.func)
        self.assertIn("日合计不变", self.flow)

    def test_division_semantics_comment_required(self):
        """必须区分「24 点均分」与「MW×0.25h」两种 /4 语义。"""
        self.assertIn("24 点均分", self.func)
        self.assertIn("MW×0.25h", self.func)

    def test_daily_aggregate_in_d96_is_open_question(self):
        """日粒度汇总列在 96 点表中的存放未在 SOP 规定，须标为待确认。"""
        self.assertIn("2.2 日粒度指标在 96 点表中的存放", self.func)
        self.assertIn("待确认", self.func)
        self.assertIn("放大 96 倍", self.func)

    def test_skill_md_has_entry_hint(self):
        """SKILL.md 入口必须提及时段换算不可选。"""
        self.assertIn("timeperiod", self.skill)
        self.assertIn("/4.0", self.skill)

    def test_return_type_warns_smallint(self):
        """必须提示 smallint 装不下分区行数。"""
        self.assertIn("RETURNS integer", self.func)
        self.assertIn("smallint", self.func)
        self.assertIn("32767", self.func)

if __name__ == "__main__":
    unittest.main(verbosity=2)
