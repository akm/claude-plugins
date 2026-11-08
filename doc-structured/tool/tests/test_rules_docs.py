"""プラグインの規則の文書とスキルの本文のテスト。

- 規則の文書 rules/doc-structured-docs.md の「限定付きの名前」の表が、ツールの表 (モジュール names) と同じであること
- 規則の文書とスキルの本文で、スキル名を接頭辞付き (doc-structured:generate) で書いていること
"""

import re
import unittest

from doc_structured import names
from tooltest import PLUGIN_DIR

RULES_DIR = PLUGIN_DIR / "rules"
SKILLS_DIR = PLUGIN_DIR / "skills"


def name_table_rows() -> list[list[str]]:
    text = (RULES_DIR / "doc-structured-docs.md").read_text(encoding="utf-8")
    section = text.split("## 限定付きの名前\n", 1)[1].split("\n## ", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("| ")]
    return [[cell.strip() for cell in row.strip("|").split("|")] for row in rows[1:]]  # 先頭は見出しの行


class NameTableTest(unittest.TestCase):
    def test_table_matches_tool(self):
        rows = name_table_rows()
        kind_rows = {}
        file_row = None
        for label, symbols, form, _example in rows:
            found = re.findall(r"`([^`]+)`", symbols)
            if label == names.FILE_KIND_LABEL:
                file_row = (found, form)
            else:
                self.assertEqual(len(found), 1, f"記号は 1 つ: {symbols}")
                kind_rows[found[0]] = (label, form)
        self.assertEqual(sorted(kind_rows), sorted(names.KINDS))
        for symbol, (label, form) in kind_rows.items():
            kind = names.KINDS[symbol]
            with self.subTest(symbol=symbol):
                self.assertEqual(label, kind.label)
                placeholder = "<日本語名>" if kind.user_level else "<英語名>"
                self.assertEqual(form, names.format_part(symbol, placeholder))
        self.assertIsNotNone(file_row)
        self.assertEqual(file_row[0], list(names.FILE_KINDS))
        self.assertEqual(file_row[1], names.format_part("models", "<ファイル名>"))


class SkillNamePrefixTest(unittest.TestCase):
    def test_skill_names_have_plugin_prefix(self):
        files = sorted(RULES_DIR.glob("*.md")) + sorted(SKILLS_DIR.glob("*/SKILL.md"))
        self.assertTrue(files)
        for path in files:
            text = path.read_text(encoding="utf-8")
            for name in re.findall(r"スキル\s*`([^`]+)`", text):
                with self.subTest(file=path.name, skill=name):
                    self.assertTrue(name.startswith("doc-structured:"), f"{path}: スキル `{name}` に接頭辞が無い")


if __name__ == "__main__":
    unittest.main()
