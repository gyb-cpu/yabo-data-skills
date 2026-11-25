import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PG_SKILL = ROOT / "skills" / "pg-function-craft" / "SKILL.md"
SHENERGY_SKILL = ROOT / "skills" / "shenergy-dwd-development" / "SKILL.md"
README = ROOT / "README.md"
VERIFY = ROOT / "skills" / "pg-function-craft" / "scripts" / "verify_offline.py"
CHANGELOG = ROOT / "skills" / "pg-function-craft" / "CHANGELOG.md"


class ReleaseContractRedTest(unittest.TestCase):
    def test_skill_declares_semver_and_changelog(self):
        text = PG_SKILL.read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^version:\s*\d+\.\d+\.\d+\s*$")
        self.assertTrue(CHANGELOG.is_file(), "技能缺少 CHANGELOG.md")

    def test_offline_verifier_checks_version_contract(self):
        text = VERIFY.read_text(encoding="utf-8")
        self.assertIn("version", text)
        self.assertIn("CHANGELOG.md", text)
        self.assertRegex(text, r"(?m)^VERSION_PATTERN\s*=")

    @staticmethod
    def _frontmatter_version(path: Path) -> str:
        text = path.read_text(encoding="utf-8")
        match = re.search(r"(?m)^version:\s*(\d+\.\d+\.\d+)\s*$", text)
        if not match:
            raise AssertionError(f"{path} 缺少合法 version")
        return match.group(1)

    @staticmethod
    def _readme_version(skill_name: str) -> str:
        text = README.read_text(encoding="utf-8")
        match = re.search(
            rf"(?m)^\| `{re.escape(skill_name)}` \| (\d+\.\d+\.\d+) \|",
            text,
        )
        if not match:
            raise AssertionError(f"README 技能表缺少 {skill_name} 版本")
        return match.group(1)

    def test_readme_skill_versions_match_skill_frontmatter(self):
        for skill_path in (PG_SKILL, SHENERGY_SKILL):
            skill_name = skill_path.parent.name
            with self.subTest(skill=skill_name):
                self.assertEqual(
                    self._readme_version(skill_name),
                    self._frontmatter_version(skill_path),
                    msg="README 技能表版本必须与 SKILL.md frontmatter 一致",
                )

    def test_skill_documents_both_output_checkers(self):
        text = PG_SKILL.read_text(encoding="utf-8")
        for script in ("scripts/check_sql_output.py", "scripts/verify_output_contract.py"):
            self.assertIn(script, text)
        self.assertRegex(text, r"退出码.*0.*1.*2")
        self.assertIn("离线启发式", text)


if __name__ == "__main__":
    unittest.main()
