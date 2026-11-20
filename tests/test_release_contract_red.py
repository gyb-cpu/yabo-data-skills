import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "pg-function-craft" / "SKILL.md"
VERIFY = ROOT / "skills" / "pg-function-craft" / "scripts" / "verify_offline.py"
CHANGELOG = ROOT / "skills" / "pg-function-craft" / "CHANGELOG.md"


class ReleaseContractRedTest(unittest.TestCase):
    def test_skill_declares_semver_and_changelog(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^version:\s*\d+\.\d+\.\d+\s*$")
        self.assertTrue(CHANGELOG.is_file(), "技能缺少 CHANGELOG.md")

    def test_offline_verifier_checks_version_contract(self):
        text = VERIFY.read_text(encoding="utf-8")
        self.assertIn("version", text)
        self.assertIn("CHANGELOG.md", text)
        self.assertRegex(text, r"(?m)^VERSION_PATTERN\s*=")

    def test_skill_documents_both_output_checkers(self):
        text = SKILL.read_text(encoding="utf-8")
        for script in ("scripts/check_sql_output.py", "scripts/verify_output_contract.py"):
            self.assertIn(script, text)
        self.assertRegex(text, r"退出码.*0.*1.*2")
        self.assertIn("离线启发式", text)


if __name__ == "__main__":
    unittest.main()
