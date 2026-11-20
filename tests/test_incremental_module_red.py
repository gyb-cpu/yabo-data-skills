#!/usr/bin/env python3
"""增量模块回归测试（RED → GREEN）。

锁定“按更新时间（update_time）做增量”的模块契约：

  1. 存在 `references/11-增量与水位线.md`，并定义 INC-01…INC-14；
  2. 覆盖回看窗、上界、逻辑删除/物理删除、哨兵日期四个关键点；
  3. `SKILL.md` 的路由表指向该文件；
  4. `09`/`10` 的编号分配表登记 `INC-xx`；
  5. `verify_offline.py` 把它列为必备文件；
  6. 检查器能识别哨兵日期（INC-05）。

约束：只使用 Python 标准库；不连接数据库、不访问网络、不执行 SQL。

运行：
    python tests/test_incremental_module_red.py -v
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
MODULE = SKILL_ROOT / "references" / "11-增量与水位线.md"
SKILL_MD = SKILL_ROOT / "SKILL.md"
ENG = SKILL_ROOT / "references" / "09-工程与函数结构规范.md"
PLS = SKILL_ROOT / "references" / "10-PLpgSQL语法与函数形态.md"
VERIFY = SKILL_ROOT / "scripts" / "verify_offline.py"
CHECKER = SKILL_ROOT / "scripts" / "check_sql_output.py"

REQUIRED_IDS = tuple(f"INC-{n:02d}" for n in range(1, 15))


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


class IncrementalModuleTest(unittest.TestCase):
    maxDiff = None

    def test_module_exists_with_rule_ids(self):
        self.assertTrue(
            MODULE.is_file(),
            msg="缺少增量模块：references/11-增量与水位线.md",
        )
        text = read(MODULE)
        missing = [rule for rule in REQUIRED_IDS if rule not in text]
        self.assertEqual(missing, [], msg=f"增量模块缺少规则 ID：{missing}")

    def test_module_covers_the_four_traps(self):
        text = read(MODULE)
        for keyword in ("回看", "上界", "逻辑删除", "物理删除", "2099"):
            with self.subTest(keyword=keyword):
                self.assertIn(
                    keyword,
                    text,
                    msg=f"增量模块未覆盖关键点：{keyword}",
                )

    def test_skill_routes_to_module(self):
        text = read(SKILL_MD)
        self.assertIn(
            "11-增量与水位线.md",
            text,
            msg="SKILL.md 的参考文档路由必须指向增量模块，否则不会被加载。",
        )

    def test_id_registered_in_both_tables(self):
        for path in (ENG, PLS):
            with self.subTest(path=path.name):
                self.assertRegex(
                    read(path),
                    r"\|[^|\n]*\|[^|\n]*`INC-xx`",
                    msg=f"{path.name} 的编号分配表未登记 INC-xx。",
                )

    def test_offline_verifier_requires_module(self):
        self.assertIn(
            "references/11-增量与水位线.md",
            read(VERIFY),
            msg="verify_offline.py 必须把增量模块列为必备文件。",
        )


class ModuleExampleTest(unittest.TestCase):
    """模块里的完整示例必须通过本技能自己的检查器。"""

    def test_template_sql_passes_checker(self):
        text = read(MODULE)
        blocks = [
            block
            for block in re.findall(r"```sql\n(.*?)```", text, re.S)
            if "CREATE OR REPLACE FUNCTION" in block
        ]
        self.assertTrue(blocks, msg="增量模块缺少完整函数示例。")
        for index, block in enumerate(blocks):
            with tempfile.TemporaryDirectory(prefix="pgfc-example-") as tmp:
                path = pathlib.Path(tmp) / "example.sql"
                path.write_bytes(block.encode("utf-8"))
                proc = subprocess.run(
                    [sys.executable, str(CHECKER), "--json", str(path)],
                    cwd=str(SKILL_ROOT),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=60,
                )
            self.assertEqual(
                proc.returncode,
                0,
                msg=(
                    f"模块第 {index} 个完整示例未通过检查器：\n{proc.stdout}\n{proc.stderr}"
                ),
            )


class SentinelDateCheckerTest(unittest.TestCase):
    def _run(self, sql: str):
        with tempfile.TemporaryDirectory(prefix="pgfc-inc-") as tmp:
            path = pathlib.Path(tmp) / "case.sql"
            path.write_bytes(sql.encode("utf-8"))
            proc = subprocess.run(
                [sys.executable, str(CHECKER), "--json", str(path)],
                cwd=str(SKILL_ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
        payload = json.loads(proc.stdout) if proc.stdout.strip() else {}
        return {item.get("rule") for item in payload.get("violations", [])}

    def test_sentinel_date_is_reported(self):
        sql = (
            "SELECT COALESCE(min(a.target_date), '2099-01-01') AS min_date\n"
            "FROM demo.src AS a\n"
            "WHERE a.update_time >= '2026-01-01';\n"
        )
        rules = self._run(sql)
        self.assertIn(
            "INC-05",
            rules,
            msg="用 '2099-01-01' 当空值哨兵应报 INC-05，改用 NULL 判断。",
        )

    def test_normal_null_handling_is_not_reported(self):
        sql = (
            "SELECT min(a.target_date) AS min_date\n"
            "FROM demo.src AS a\n"
            "WHERE a.update_time >= '2026-01-01';\n"
        )
        rules = self._run(sql)
        self.assertNotIn("INC-05", rules)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    unittest.main(verbosity=2)
