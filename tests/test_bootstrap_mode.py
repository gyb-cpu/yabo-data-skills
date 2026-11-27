#!/usr/bin/env python3
"""申能 DWD 技能：首次开发 bootstrap 模式回归测试。

锁定 0.4.0 的行为：
  1. SKILL.md 先判定模式，并路由到 references/首次开发.md；
  2. 首次开发文档限定 BI看 sheet、字段补录必做、源表全限定名、工作区边界与固定产物；
  3. check_shenergy_artifacts.py --kind bootstrap 校验固定产物集合（SH-BOOT-01..04）；
  4. README 首次提示词使用 bootstrap 模式，不再要求执行完整 SOP。

约束：只使用 Python 标准库；不连接数据库、不访问网络。
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "shenergy-dwd-development"
SKILL_MD = SKILL_ROOT / "SKILL.md"
BOOT_DOC = SKILL_ROOT / "references" / "首次开发.md"
CHECKER = SKILL_ROOT / "scripts" / "check_shenergy_artifacts.py"
REPO_README = REPO_ROOT / "README.md"

TABLE = "dwd_ah_retail_settlement_d96"


def build_bootstrap_dir(root: pathlib.Path) -> None:
    files = {
        "README.md": "# 安徽售电\n\nmode: bootstrap\n\n## artifacts\n\n## gates\n\n## open_questions\n\n## next\n",
        "参考资料/指标字段来源对照表.csv": "x\n",
        "参考资料/2026-11-27_BI看快照.xlsx": "x",
        "DDL/安徽售电1表_建表语句.sql": "-- ddl\n",
        f"计算脚本/{TABLE}.sql": "-- func\n",
        "复核验证/安徽售电_平台补录与变更记录.md": "x\n",
        "复核验证/安徽售电_平台原始DDL.sql": "-- raw\n",
        f"复核验证/{TABLE}_spec.json": "{}\n",
        "复核验证/安徽售电_待人工确认清单.md": "x\n",
    }
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def run_checker(path: pathlib.Path) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, str(CHECKER), "--kind", "bootstrap", "--json", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    data = json.loads(proc.stdout) if proc.stdout.strip() else {}
    return proc.returncode, data


def rules_of(data: dict) -> set[str]:
    return {v["rule"] for v in data.get("violations", [])}


class BootstrapDocs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = SKILL_MD.read_text(encoding="utf-8")
        cls.doc = BOOT_DOC.read_text(encoding="utf-8")
        cls.readme = REPO_README.read_text(encoding="utf-8")

    def test_skill_routes_mode_first(self):
        self.assertIn("## 先判定模式", self.skill)
        self.assertIn("references/首次开发.md", self.skill)
        for mode in ("`bootstrap`", "`full`", "`maintenance`"):
            self.assertIn(mode, self.skill)
        self.assertLess(self.skill.index("## 先判定模式"), self.skill.index("## 阶段硬约束"))

    def test_doc_limits_snapshot_to_bi_sheet(self):
        self.assertIn("只读 `BI看` sheet", self.doc)
        self.assertIn("其他 sheet 不打开", self.doc)

    def test_platform_registration_is_mandatory(self):
        self.assertIn("命名与平台补录（阶段 3，必做）", self.doc)
        self.assertIn("0 个「未找到」", self.doc)

    def test_source_tables_fully_qualified_for_lineage(self):
        self.assertIn("全限定名", self.doc)
        self.assertIn("不得用动态 SQL 拼接表名", self.doc)

    def test_workspace_boundary(self):
        for token in ("不扫描", "已存在时先停下", "不安装依赖", "不执行 git 操作", "最多修 2 轮"):
            self.assertIn(token, self.doc)

    def test_bootstrap_excludes_full_stages(self):
        self.assertIn("本模式不做", self.doc)
        self.assertIn("--kind bootstrap", self.doc)

    def test_readme_first_prompt_uses_bootstrap(self):
        self.assertIn("以 bootstrap 模式", self.readme)
        self.assertIn("以 full 模式", self.readme)
        self.assertNotIn("执行完整 SOP", self.readme)


class BootstrapChecker(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name) / "安徽售电"
        self.root.mkdir()
        build_bootstrap_dir(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_complete_set_passes(self):
        code, data = run_checker(self.root)
        self.assertEqual(code, 0, data)
        self.assertTrue(data["ok"])
        self.assertFalse(data["database_connected"])

    def test_missing_required_file(self):
        (self.root / "复核验证" / "安徽售电_平台原始DDL.sql").unlink()
        code, data = run_checker(self.root)
        self.assertEqual(code, 1)
        self.assertIn("SH-BOOT-01", rules_of(data))

    def test_full_stage_file_rejected(self):
        (self.root / "复核验证" / "安徽售电_验收报告.md").write_text("x\n", encoding="utf-8")
        code, data = run_checker(self.root)
        self.assertEqual(code, 1)
        msgs = [v["message"] for v in data["violations"] if v["rule"] == "SH-BOOT-02"]
        self.assertTrue(any("full 阶段" in m for m in msgs), msgs)

    def test_extra_file_rejected(self):
        (self.root / "scratch.py").write_text("print(1)\n", encoding="utf-8")
        _, data = run_checker(self.root)
        self.assertIn("SH-BOOT-02", rules_of(data))

    def test_spec_function_pairing(self):
        (self.root / "计算脚本" / "dwd_other_d.sql").write_text("-- f\n", encoding="utf-8")
        _, data = run_checker(self.root)
        self.assertIn("SH-BOOT-03", rules_of(data))

    def test_readme_requires_mode_and_keys(self):
        (self.root / "README.md").write_text("# 安徽售电\n\nartifacts\n", encoding="utf-8")
        _, data = run_checker(self.root)
        msgs = [v["message"] for v in data["violations"] if v["rule"] == "SH-BOOT-04"]
        self.assertTrue(any("bootstrap" in m for m in msgs), msgs)
        self.assertTrue(any("open_questions" in m for m in msgs), msgs)

    def test_file_path_is_usage_error(self):
        code, _ = run_checker(self.root / "README.md")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    unittest.main(verbosity=2)
