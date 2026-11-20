#!/usr/bin/env python3
"""参考文献一致性回归测试（RED → GREEN）。

锁定 2026-11-13 第一性原理审查后的收敛结论：

  1. 冲突优先级只在 `references/00-风格与边界.md` 定义一次；
  2. `search_path` 的两种合格写法在各文件口径一致；
  3. 返回码契约限定适用范围，不套用到所有返回形态；
  4. `*author` 不再要求写真实个人；
  5. 版本事实只有一份（`10-PLpgSQL语法与函数形态.md` §1.1），
     `08-PostgreSQL审查规则.md` 只保留审查定级；
  6. 每个完整函数示例满足 F-21，或显式标注“节选”；
  7. 检查器与文档口径一致：尾逗号可切换、表达式索引豁免、
     命名规则不再冒用 `REV-M02`。

约束：只使用 Python 标准库；不连接数据库、不访问网络、不执行 SQL。

运行：
    python tests/test_reference_consistency_red.py -v
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "pg-function-craft"
REFS = SKILL_ROOT / "references"
SKILL_MD = SKILL_ROOT / "SKILL.md"
SKILL_README = SKILL_ROOT / "README.md"
REPO_README = REPO_ROOT / "README.md"
CHECKER = SKILL_ROOT / "scripts" / "check_sql_output.py"

ALL_DOCS = sorted(REFS.glob("*.md")) + [SKILL_MD, SKILL_README, REPO_README]

PRIORITY_LEVELS = (
    "安全与正确性",
    "项目已确认的书面约定",
    "排版 `MUST`",
    "本技能默认值",
)


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def sql_blocks(path: pathlib.Path):
    """返回 [(块前最近 3 行, 块内行列表)]。"""
    blocks = []
    before: list[str] = []
    current: list[str] | None = None
    start = 0
    for line in read(path).splitlines():
        if line.strip() == "```sql":
            current = []
            start = len(before)
            continue
        if current is not None and line.strip() == "```":
            blocks.append((before[max(0, start - 3):], current))
            current = None
            continue
        if current is not None:
            current.append(line)
        else:
            before.append(line)
    return blocks


class ReferenceConsistencyTest(unittest.TestCase):
    maxDiff = None

    def test_priority_is_defined_exactly_once(self):
        boundary = REFS / "00-风格与边界.md"
        text = read(boundary)
        self.assertIn(
            "## 6. 冲突优先级",
            text,
            msg="00-风格与边界.md 必须承载唯一的冲突优先级定义。",
        )
        positions = [text.find(level) for level in PRIORITY_LEVELS]
        self.assertTrue(
            all(position >= 0 for position in positions),
            msg=f"优先级层级缺失：{dict(zip(PRIORITY_LEVELS, positions))}",
        )
        self.assertEqual(
            positions,
            sorted(positions),
            msg="优先级层级顺序必须是：安全 > 项目约定 > 排版 MUST > 默认值。",
        )

    def test_no_competing_priority_claim(self):
        for path in ALL_DOCS:
            with self.subTest(path=path.name):
                self.assertNotIn("固定风格 > 项目已确认的", read(path))
                self.assertNotIn("固定风格 > 项目约定", read(path))

    def test_author_does_not_require_real_person(self):
        for path in ALL_DOCS:
            with self.subTest(path=path.name):
                self.assertNotIn(
                    "实际用户",
                    read(path),
                    msg="作者字段必须写团队名或占位符，不能要求填真实个人。",
                )

    def test_search_path_forms_are_consistent(self):
        baseline = read(REFS / "01-基线规范.md")
        self.assertIn("二选一", baseline)
        self.assertIn("search_path = ''", baseline)

        engineering = read(REFS / "09-工程与函数结构规范.md")
        eng_line = next(
            (line for line in engineering.splitlines() if line.startswith("| ENG-05")),
            "",
        )
        self.assertIn("二选一", eng_line, msg=f"ENG-05 口径未统一：{eng_line!r}")

    def test_return_code_contract_is_scoped(self):
        style = read(REFS / "04-固定风格.md")
        self.assertIn(
            "返回标量状态码",
            style,
            msg="返回码契约必须限定为标量状态码函数，否则触发器/过程无法满足。",
        )

    def test_version_facts_have_single_source(self):
        review = read(REFS / "08-PostgreSQL审查规则.md")
        self.assertNotIn(
            "| `ON CONFLICT` | 9.5 |",
            review,
            msg="08 不应重复版本事实表，应引用 10 §1.1。",
        )
        self.assertIn("10-PLpgSQL语法与函数形态.md", review)
        self.assertIn("§1.1", review)

    def test_complete_function_examples_satisfy_header_rule(self):
        for path in sorted(REFS.glob("*.md")):
            for index, (before, block) in enumerate(sql_blocks(path)):
                body = "\n".join(block)
                if "CREATE OR REPLACE FUNCTION" not in body:
                    continue
                if any("-- *name" in line for line in block):
                    continue
                with self.subTest(path=path.name, block=index):
                    self.assertIn(
                        "节选",
                        "\n".join(before),
                        msg=(
                            f"{path.name} 第 {index} 个示例含 CREATE OR REPLACE FUNCTION，"
                            "但既无七字段头（F-21），也未标注“节选”。"
                        ),
                    )


class CheckerAlignmentTest(unittest.TestCase):
    maxDiff = None

    def _run(self, sql: str, *args: str):
        with tempfile.TemporaryDirectory(prefix="pgfc-align-") as tmp:
            path = pathlib.Path(tmp) / "case.sql"
            path.write_bytes(sql.encode("utf-8"))
            proc = subprocess.run(
                [sys.executable, str(CHECKER), "--json", *args, str(path)],
                cwd=str(SKILL_ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
        payload = json.loads(proc.stdout) if proc.stdout.strip() else {}
        return proc, payload, {item.get("rule") for item in payload.get("violations", [])}

    def test_trailing_comma_style_can_be_selected(self):
        sql = "SELECT\n    a.col1,\n    a.col2\nFROM\n    demo.t AS a;\n"
        _, _, default_rules = self._run(sql)
        self.assertIn("F-12", default_rules, msg="默认前置逗号仓库应报尾逗号。")
        _, _, trailing_rules = self._run(sql, "--comma-style", "trailing")
        self.assertNotIn(
            "F-12",
            trailing_rules,
            msg="06 允许仓库统一用尾逗号，检查器必须能按仓库约定切换。",
        )

    def test_expression_index_is_exempt_from_sargability_rule(self):
        sql = (
            "CREATE INDEX idx_orders_dt\n"
            "    ON demo.orders ((created_at::date));\n"
        )
        _, _, rules = self._run(sql)
        self.assertNotIn(
            "PERF-29",
            rules,
            msg="07 §2.3 明确允许表达式索引，PERF-29 不应判它违规。",
        )

    def test_naming_violation_uses_style_rule_id(self):
        sql = (
            "-- *name : get_orders\n"
            "-- *function : 取订单\n"
            "-- *input : 1:起始日期\n"
            "-- *output : 0正常\n"
            "-- *author : <team>\n"
            "-- *CreateDate : 2026-01-01\n"
            "-- *UpdateDate : 2026-01-01\n"
            "CREATE OR REPLACE FUNCTION demo.get_orders(p_start date)\n"
            "RETURNS bigint\n"
            "LANGUAGE plpgsql\n"
            "AS $function$\n"
            "BEGIN\n"
            "    RETURN 0;\n"
            "END;\n"
            "$function$;\n"
        )
        _, _, rules = self._run(sql)
        self.assertIn(
            "STYLE-01",
            rules,
            msg="命名属于固定风格默认值，应报 STYLE-01；REV-M02 只判命名不一致。",
        )
        self.assertNotIn("REV-M02", rules)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    unittest.main(verbosity=2)
