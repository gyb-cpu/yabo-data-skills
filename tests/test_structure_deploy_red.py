"""RED 阶段测试：pg-function-craft 的“结构与部署校验”契约。

背景
----
`skills/pg-function-craft/scripts/verify_offline.py` 目前只校验必备文件、禁用词、
编码与换行。它不校验技能包能否被正确安装和路由：

1. 安装布局：仓库根 README 要求安装目录保留 `assets/`，但自检不要求；
2. 文档引用完整性：README 内嵌的 `assets/*.svg`、SKILL.md 引用的
   `references/*.md`、以及 `README.md 第 N 节` 这类章节交叉引用，都没有被解析；
3. 发现元数据：frontmatter 的 `description` 与“目录名 == name”对 skill 安装/发现
   同样关键，自检只匹配 `name:` 一行前缀。

这些测试通过复制技能包并注入单点缺陷，断言离线自检必须拒绝该副本（退出码 1、
JSON `ok: false`、`issues` 指出具体路径或字段）。当前实现没有这些检查，所以
所有带缺口的用例都会失败——这是预期的 RED 状态，不要通过放宽断言或修改生产
文件来“修复”它。

夹具会先把副本 `tests/` 下除 `README.md` 以外的内容清掉：`verify_offline.py`
把技能包内任何额外 `.py` 视为“夹带连库脚本”，而并行工作的测试文件不属于
发布包，保留它们会让失败原因失真。

运行
----
    python -m unittest tests.test_structure_deploy_red -v
    python -m unittest discover -s tests -p "test_structure_deploy_red.py" -v

只使用 Python 标准库；不连接数据库、不访问网络、不执行 SQL。
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILL_ROOT = REPO_ROOT / "skills" / "pg-function-craft"
VERIFY_REL = pathlib.Path("scripts") / "verify_offline.py"


class StructureDeployContractTests(unittest.TestCase):
    maxDiff = None

    # ------------------------------------------------------------------ 工具

    def _copy_skill(self, dir_name: str = "pg-function-craft") -> pathlib.Path:
        """把技能包复制到临时目录，返回副本根路径。

        自检脚本以自身位置推导 ROOT，因此在副本中运行不会触碰生产目录。
        """
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="pgfc-structure-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        dest = tmp / dir_name
        shutil.copytree(SKILL_ROOT, dest)

        # 并行 agent 可能在技能包 tests/ 下放自己的测试文件；verify_offline.py
        # 会把额外 .py 判为污染，导致本组用例在错误原因上失败。
        tests_dir = dest / "tests"
        for child in tests_dir.iterdir():
            if child.name == "README.md":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        return dest

    def _run_verify(self, root: pathlib.Path) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run(
            [sys.executable, str(root / VERIFY_REL), "--json"],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=60,
        )

    def _read_issues(self, proc: subprocess.CompletedProcess) -> tuple[dict, str]:
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            self.fail(
                "--json 输出不是合法 JSON："
                f"{exc}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
            )
        issues = "\n".join(payload.get("issues", [])).replace("\\", "/")
        return payload, issues

    def _assert_structure_failure(
        self, proc: subprocess.CompletedProcess, *needles: str
    ) -> None:
        payload, issues = self._read_issues(proc)
        self.assertEqual(
            proc.returncode,
            1,
            "结构/部署缺陷没有被离线自检拒绝：期望退出码 1，实际 "
            f"{proc.returncode}；issues={issues!r}",
        )
        self.assertFalse(
            payload.get("ok", True),
            f"期望 ok=false，实际 {payload.get('ok')!r}；issues={issues!r}",
        )
        for needle in needles:
            self.assertIn(
                needle,
                issues,
                f"issues 未指出 {needle!r}；实际 issues：\n{issues}",
            )

    # ------------------------------------------------------------ 基线（守卫）

    def test_verify_script_emits_json_on_package_copy(self) -> None:
        """守卫：副本中的自检可按 `--json` 运行，失败来自注入的缺口而非夹具。"""
        proc = self._run_verify(self._copy_skill())
        payload, _ = self._read_issues(proc)
        self.assertIn(proc.returncode, (0, 1))
        self.assertFalse(payload.get("database_connected", True))

    # ------------------------------------------------------- 安装布局 / 资源

    def test_install_layout_requires_assets_directory(self) -> None:
        """仓库根 README 要求安装目录保留 assets/，缺失时应拒绝。"""
        skill = self._copy_skill()
        shutil.rmtree(skill / "assets")
        proc = self._run_verify(skill)
        self._assert_structure_failure(proc, "assets")

    def test_readme_referenced_asset_must_exist(self) -> None:
        """README 以 `assets/...svg` 内嵌图示，文件缺失时应拒绝。"""
        skill = self._copy_skill()
        (skill / "assets" / "pg-function-craft-hero.svg").unlink()
        proc = self._run_verify(skill)
        self._assert_structure_failure(
            proc, "assets/pg-function-craft-hero.svg"
        )

    # --------------------------------------------------- 文档引用完整性

    def test_cited_reference_file_must_exist(self) -> None:
        """SKILL.md 引用的 references/*.md 必须真实存在，供按需路由。"""
        skill = self._copy_skill()
        skill_md = skill / "SKILL.md"
        text = skill_md.read_text(encoding="utf-8")
        addition = "\n另见 `references/11-实验规则.md`。\n"
        skill_md.write_bytes((text + addition).encode("utf-8"))
        proc = self._run_verify(skill)
        self._assert_structure_failure(proc, "references/11-实验规则.md")

    def test_section_cross_reference_must_resolve(self) -> None:
        """`README.md 第 N 节` 必须能在 README 的章节结构中解析到。"""
        skill = self._copy_skill()
        skill_md = skill / "SKILL.md"
        text = skill_md.read_text(encoding="utf-8")
        addition = "\n排版速查表见 `README.md` 第 99 节。\n"
        skill_md.write_bytes((text + addition).encode("utf-8"))
        proc = self._run_verify(skill)
        self._assert_structure_failure(proc, "第 99 节")

    # ----------------------------------------------------- 发现元数据

    def test_frontmatter_requires_description(self) -> None:
        """frontmatter 缺少 description 时，skill 无法被正确发现。"""
        skill = self._copy_skill()
        skill_md = skill / "SKILL.md"
        text = skill_md.read_text(encoding="utf-8")
        stripped = re.sub(
            r"^description:.*\n", "", text, count=1, flags=re.MULTILINE
        )
        self.assertNotEqual(
            stripped, text, "夹具构造失败：SKILL.md 中没有 description 行"
        )
        skill_md.write_bytes(stripped.encode("utf-8"))
        proc = self._run_verify(skill)
        self._assert_structure_failure(proc, "description")

    def test_install_dir_name_must_match_frontmatter_name(self) -> None:
        """安装目录名应与 frontmatter `name` 一致，否则路由/更新会错位。"""
        skill = self._copy_skill("pg-function-craft-renamed")
        proc = self._run_verify(skill)
        self._assert_structure_failure(proc, "pg-function-craft-renamed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
