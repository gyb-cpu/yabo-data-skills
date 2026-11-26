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

    def test_pg_skill_is_mandatory_not_optional(self):
        """pg-function-craft 必须是必调项，「外部工具可选」不得覆盖它。"""
        self.assertIn("必调项", self.func)
        self.assertIn("必调", self.flow)
        self.assertIn("必调", self.skill)
        self.assertNotIn("引用外部工具是可选的", self.func)

    def test_optional_applies_only_to_third_party_tools(self):
        """「可选」只能覆盖包外工具，须点名 sqlglot/sqlfluff/pg_format。"""
        self.assertIn("包外第三方工具", self.func)
        for name in ("sqlglot", "sqlfluff", "pg_format"):
            self.assertIn(name, self.func)

    def test_checker_output_required_as_evidence(self):
        """交付须附检查器实际输出，不能只写「已完成静态检查」。"""
        self.assertIn("check_sql_output.py --json", self.func)
        self.assertIn("check_sql_output.py --json", self.flow)
        self.assertIn("check_sql_output.py --json", self.skill)

    def test_checker_pass_is_not_syntax_proof(self):
        """检查器通过不等于语法正确，必须再做数据库编译验证。"""
        self.assertIn("不代表语法正确", self.func)
        self.assertIn("ROLLBACK", self.func)
        self.assertIn("编译验证", self.flow)

    def test_acceptance_has_skill_invocation_check(self):
        """验收清单必须有一项核对技能调用留痕。"""
        self.assertIn("技能调用留痕", self.func)
        self.assertIn("技能调用留痕", self.flow)
        self.assertIn("不得写「已完成静态检查」", self.func)

    def test_existing_table_columns_win_over_platform_entries(self):
        """目标表已存在时，列名以既有列名为准，平台条目不得覆盖。"""
        self.assertIn("存量表列名优先", self.flow)
        self.assertIn("以既有列名为准", self.skill)
        self.assertIn("以现库既有列名为准", self.flow)

    def test_rename_requires_authorization(self):
        """改名属破坏性变更：须单独提出影响面并获授权，不得与口径变更混交付。"""
        self.assertIn("改名属破坏性变更", self.flow)
        self.assertIn("获授权后才执行", self.flow)
        self.assertIn("不得把改名混进口径变更一起交付", self.flow)
        self.assertIn("改名属破坏性变更", self.skill)

    def test_ddl_forbids_swapping_column_names(self):
        """§4 DDL 不得因平台条目不同而更换既有列名。"""
        self.assertIn("既有对象的列名不因平台条目不同而更换", self.flow)

    def test_extension_fields_not_inserted_by_calculation_script(self):
        """扩展字段只用于 DDL 预留，不进入计算脚本。"""
        self.assertIn("2.9 扩展字段不进入计算脚本", self.func)
        self.assertIn("不进入计算脚本的 `INSERT` 或 `SELECT`", self.skill)
        self.assertIn("计算脚本列清单与目标表业务列集合的差集不包含", self.flow)
        self.assertIn("ext_1..ext_10", self.flow)
        self.assertIn("扩展字段只作为 DDL 预留列", self.flow)

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
