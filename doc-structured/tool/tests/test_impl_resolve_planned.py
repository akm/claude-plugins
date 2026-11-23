"""サブコマンド impl-diff-resolve の --planned と --unplanned のテスト。

YAML の書き換えの結果と、解消した件の検査 j が成功する (件の一覧から消える) ことを確認する。決めた経緯は Issue #208 のコメントの 2・6。
"""

import unittest

from test_impl_resolve_cli import LOANS_MIGRATION, MEMBERS_SCHEMA, ResolveTestCase

LOANS_SCHEMA = "docs/domains/02-loans/schema.yaml"
CARDS_TABLE = """\
  member_cards:
    planned: true
    definition: 利用者に発行する利用者カード 1 枚の行。
    primary_key: [id]
    columns:
      id:
        type: text
        definition: 利用者カードを識別する値。
      member_id:
        type: text
        definition: カードを持つ利用者。
        references: d-members-t-members-c-id
    indexes:
      - columns: [member_id]
"""


class PlannedTest(ResolveTestCase):
    def test_column(self):
        self.replace(
            MEMBERS_SCHEMA,
            "        attribute: d-members-m-member-a-name\n",
            "        attribute: d-members-m-member-a-name\n"
            "      phone:\n        type: text\n        nullable: true\n        definition: 利用者の電話番号。\n",
        )
        result = self.resolve("d-members-t-members-c-phone", "--planned")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            f"書き換えた: {MEMBERS_SCHEMA}\n生成したファイルを YAML に合わせるには bin/doc-structured generate を実行する\n",
        )
        self.assertIn(
            "      phone:\n        type: text\n        nullable: true\n        planned: true\n        definition: 利用者の電話番号。\n",
            self.read(MEMBERS_SCHEMA),
        )
        self.assert_item_resolved("d-members-t-members-c-phone")

    def test_index(self):
        self.replace(LOANS_MIGRATION, "CREATE INDEX loans_member_idx ON loans (member_id);\n", "")
        result = self.resolve("d-loans-t-loans:member_id", "--planned")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("      - columns: [member_id]\n        planned: true\n      - columns: [reservation_id]\n", self.read(LOANS_SCHEMA))
        self.assert_item_resolved("d-loans-t-loans:member_id")

    def test_table_removes_planned_of_its_columns_and_indexes(self):
        # テーブルの planned を外し、カラムとインデックスに planned を付けた YAML。テーブルは実装に無い
        self.replace(MEMBERS_SCHEMA, "    planned: true\n    definition: 利用者に発行する", "    definition: 利用者に発行する")
        self.replace(MEMBERS_SCHEMA, "        definition: カードを持つ利用者。\n", "        planned: true\n        definition: カードを持つ利用者。\n")
        self.replace(MEMBERS_SCHEMA, "      - columns: [member_id]\n", "      - columns: [member_id]\n        planned: true\n")
        result = self.resolve("d-members-t-member_cards", "--planned")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.read(MEMBERS_SCHEMA).endswith(CARDS_TABLE), self.read(MEMBERS_SCHEMA))
        self.assert_item_resolved("d-members-t-member_cards")

    def test_refused_when_check_h_fails(self):
        # 実装済みの貸出のカラム reservation_id が参照する予約のテーブルを、未実装にはできない
        text = self.read(LOANS_MIGRATION)
        start = text.index("CREATE TABLE reservations")
        end = text.index("CREATE TABLE loans")
        self.write(LOANS_MIGRATION, text[:start] + text[end:].replace(" REFERENCES reservations (id)", ""))
        schema = "docs/domains/02-loans/reservations/schema.yaml"
        before = self.read(schema)
        result = self.resolve("d-loans-t-reservations", "--planned")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("未実装", result.stderr)
        self.assertIn("書き換えた後の YAML に", result.stderr)
        self.assertIn("の誤り (検査 h) があるので、元に戻した", result.stderr)
        self.assertEqual(self.read(schema), before)


class UnplannedTest(ResolveTestCase):
    def test_table(self):
        self.write(
            "migrations/0003_cards.sql",
            "CREATE TABLE member_cards (id text PRIMARY KEY NOT NULL, member_id text NOT NULL REFERENCES members (id));\n"
            "CREATE INDEX member_cards_member_idx ON member_cards (member_id);\n",
        )
        result = self.resolve("d-members-t-member_cards", "--unplanned")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("  member_cards:\n    definition: 利用者に発行する", self.read(MEMBERS_SCHEMA))
        result = self.resolve("--list")
        self.assertEqual(result.stdout, "解消する差分は無かった\n")

    def test_column_and_then_its_difference_is_reported(self):
        # 貸出のカラム returned_at (planned) を、型を変えて実装する
        self.replace(LOANS_MIGRATION, "  status text DEFAULT 'on_loan' NOT NULL,", "  status text DEFAULT 'on_loan' NOT NULL,\n  returned_at text,")
        result = self.resolve("d-loans-t-loans-c-returned_at", "--unplanned")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("      returned_at:\n        type: integer\n        nullable: true\n        definition: 図書が返った", self.read(LOANS_SCHEMA))
        result = self.resolve("--list")
        self.assertIn("d-loans-t-loans-c-returned_at | --match-impl | カラム d-loans-t-loans-c-returned_at の型が違う", result.stdout)

    def test_index(self):
        self.replace(LOANS_SCHEMA, "      - columns: [member_id]\n", "      - columns: [member_id]\n        planned: true\n")
        result = self.resolve("d-loans-t-loans:member_id", "--unplanned")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("      - columns: [member_id]\n      - columns: [reservation_id]\n", self.read(LOANS_SCHEMA))
        self.assert_item_resolved("d-loans-t-loans:member_id")


if __name__ == "__main__":
    unittest.main()
