"""モジュール yamlio (ruamel.yaml の round-trip) が、コメント・記述の順序・空行を保って書き換えられることのテスト。

sub-issue 1 (#193) の条件「YAML のコメントと記述の順序を保って書き換えられる言語とライブラリであることを確認している」の確認。
"""

import unittest

from doc_structured import yamlio

# 架空の題材「図書館の貸出」のドメインの YAML (形式は後の sub-issue で決めるので、ここでは書き方の例にすぎない)
SOURCE = """\
# 図書館の貸出のドメイン
domain: loans   # 貸出

# モデル
models:
  - name: loan        # 貸出
    attrs: [id, due_on, returned_at]

  - name: patron
    attrs:
      - id
      # 利用者の氏名
      - name
"""


class YamlioTest(unittest.TestCase):
    def test_round_trip_keeps_everything_when_nothing_changes(self):
        self.assertEqual(yamlio.dump(yamlio.load(SOURCE)), SOURCE)

    def test_changing_one_value_changes_only_that_line(self):
        data = yamlio.load(SOURCE)
        data["models"][1]["name"] = "member"
        expected = SOURCE.replace("  - name: patron\n", "  - name: member\n")
        self.assertEqual(yamlio.dump(data), expected)

    def test_adding_a_key_keeps_order_of_existing_keys(self):
        data = yamlio.load(SOURCE)
        data["models"][0]["planned"] = True
        out = yamlio.dump(data)
        self.assertIn("    attrs: [id, due_on, returned_at]\n    planned: true\n", out)
        self.assertLess(out.index("domain:"), out.index("models:"))
        # 変えていない部分 (コメント・空行) はそのまま
        self.assertIn("# 貸出\n\n# モデル\n", out)
        self.assertIn("      # 利用者の氏名\n      - name\n", out)


if __name__ == "__main__":
    unittest.main()
