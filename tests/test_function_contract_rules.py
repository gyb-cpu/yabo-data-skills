#!/usr/bin/env python3
"""申能 DWD 技能：函数契约规则回归测试。

锁定 0.0.3 补入的三条规则（2026-11-23 干净环境比对目标库既有实现后确定）：

  §2.1 时段骨架只能取自 dim.dim_timeperiod_change，禁止 generate_series 自造；
  §2.4 增量按 update_time 收变化日期集合，禁止扩成 min/max 区间；
  §2.5 保留既有函数的参数校验返回方式、EXCEPTION 包装、头部字段与观测点。

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


class FunctionContractRules(unittest.TestCase):
    """三条规则必须在函数规范、流程门禁与技能入口中可检索到。"""

    @classmethod
    def setUpClass(cls):
        cls.func = FUNC_DOC.read_text(encoding="utf-8")
        cls.flow = FLOW_DOC.read_text(encoding="utf-8")
        cls.skill = SKILL_MD.read_text(encoding="utf-8")

    def test_no_handmade_timeperiod_skeleton(self):
        """禁止用 generate_series 自造 96 点骨架。"""
        self.assertIn("禁止自造时段骨架", self.func)
        self.assertIn("generate_series", self.func)
        self.assertIn("generate_series", self.flow)

    def test_dim_timeperiod_change_is_only_source(self):
        """时段维表是唯一来源。"""
        self.assertIn("dim.dim_timeperiod_change", self.func)
        self.assertIn("dim.dim_timeperiod_change", self.flow)
        self.assertIn("dim.dim_timeperiod_change", self.skill)

    def test_dim_timeperiod_change_columns_documented(self):
        """须写明该维表承载 24/48/96 三套编码。"""
        self.assertIn("time_24", self.func)
        self.assertIn("time_48", self.func)

    def test_incremental_uses_changed_date_set(self):
        """增量必须收 date[] 变化集合。"""
        self.assertIn("2.4 增量必须按变化集合", self.func)
        self.assertIn("array_agg(DISTINCT", self.func)
        self.assertIn("date[]", self.func)
        self.assertIn("= ANY(v_changed_dates)", self.func)

    def test_incremental_forbids_min_max_expansion(self):
        """禁止把稀疏变化集合扩成 min/max 区间。"""
        self.assertIn("min/max", self.func)
        self.assertIn("禁止把稀疏变化集合扩成", self.func)
        self.assertIn("min/max", self.flow)

    def test_watermark_is_half_open(self):
        """水位线必须是半开区间。"""
        self.assertIn("clock_timestamp()", self.func)
        self.assertIn("半开区间", self.func)

    def test_external_contract_preserved(self):
        """外部契约保留小节必须存在。"""
        self.assertIn("2.5 保留既有函数的外部契约", self.func)
        self.assertIn("RETURN -1", self.func)
        self.assertIn("RETURN -1", self.flow)
        self.assertIn("ERRCODE", self.func)

    def test_increment_header_field_kept(self):
        """头部既有字段只增不减。"""
        self.assertIn("*increment", self.func)

    def test_raise_exception_swap_forbidden(self):
        """把 RETURN -1 改成 RAISE EXCEPTION 属破坏调用方。"""
        self.assertIn("RAISE EXCEPTION", self.func)
        self.assertIn("破坏调用方", self.func)
        self.assertIn("RAISE EXCEPTION", self.flow)

    def test_physical_delete_limitation_documented(self):
        """逻辑删除可捕获、物理删除不能，须写明。"""
        self.assertIn("物理删除", self.func)
        self.assertIn("物理删除", self.flow)

    def test_skill_md_lists_three_items(self):
        """技能入口必须列出三条不可自行发挥项。"""
        self.assertIn("update_time", self.skill)
        self.assertIn("dim_timeperiod_change", self.skill)
        self.assertIn("RETURN -1", self.skill)

    def test_skill_md_warns_f32_scope(self):
        """入口须说明 F-32 只校验同层列表项，避免为过检压行。"""
        self.assertIn("F-32", self.skill)
        self.assertIn("同层列表项", self.skill)

    def test_version_matches_newest_changelog(self):
        """SKILL.md 版本号必须等于 CHANGELOG 最新条目。"""
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
        newest = headings[0].split(" ")[0]
        self.assertEqual(
            version,
            newest,
            msg=f"SKILL.md version={version} 与 CHANGELOG 最新 {newest} 不一致",
        )


if __name__ == "__main__":
    import sys

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    unittest.main(verbosity=2)
