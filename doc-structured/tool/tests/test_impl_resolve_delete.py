"""サブコマンド impl-diff-resolve の --match-impl のうち、YAML にあって実装に無い項目を YAML から消す場合のテスト。

決めた経緯は Issue #208 のコメントの 2・6。
"""

import unittest

from test_impl_resolve_cli import LOANS_MIGRATION, MEMBERS_SCHEMA, ResolveTestCase

CATALOG_SCHEMA = "docs/domains/01-catalog/schema.yaml"
LOANS_SCHEMA = "docs/domains/02-loans/schema.yaml"
GENERATE_HINT = "生成したファイルを YAML に合わせるには bin/doc-structured generate を実行する"


class DeleteTest(ResolveTestCase):
    def test_column(self):
        before = self.read(MEMBERS_SCHEMA)
        self.replace(
            MEMBERS_SCHEMA,
            "        attribute: d-members-m-member-a-name\n",
            "        attribute: d-members-m-member-a-name\n"
            "      # 電話番号は、連絡の手段を決めてから実装する\n"
            "      phone:\n        type: text\n        nullable: true\n        definition: 利用者の電話番号。\n",
        )
        result = self.resolve("d-members-t-members-c-phone", "--match-impl")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f"書き換えた: {MEMBERS_SCHEMA}\n{GENERATE_HINT}\n")
        self.assertEqual(self.read(MEMBERS_SCHEMA), before)

    def test_column_reports_links_to_the_deleted_id(self):
        self.replace(LOANS_SCHEMA, "        nullable: true\n        planned: true\n", "        nullable: true\n")
        result = self.resolve("d-loans-t-loans-c-returned_at", "--match-impl")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("returned_at", self.read(LOANS_SCHEMA))
        self.assertEqual(
            result.stdout,
            f"書き換えた: {LOANS_SCHEMA}\n"
            "消した d-loans-t-loans-c-returned_at (とその下の ID) を指すリンクがある。リンクを直す:\n"
            "docs/domains/02-loans/design.md:17:11: d-loans-t-loans-c-returned_at [テーブル `loans` のカラム `returned_at`] "
            "(d-loans-design-h-returned_at)\n"
            f"{GENERATE_HINT}\n",
        )

    def test_column_in_index_needs_the_index_first(self):
        self.replace("migrations/0001_create_catalog_and_members.sql", "  call_number text NOT NULL,\n", "")
        self.replace(CATALOG_SCHEMA, "        in_overview: true\n", "        in_overview: true\n        planned: true\n")
        self.replace(CATALOG_SCHEMA, "  categories:", "    indexes:\n      - columns: [call_number]\n        planned: true\n  categories:")
        self.assertEqual(self.resolve("--list").stdout, "解消する差分は無かった\n")
        self.replace(CATALOG_SCHEMA, "        in_overview: true\n        planned: true\n", "        in_overview: true\n")
        self.replace(CATALOG_SCHEMA, "      - columns: [call_number]\n        planned: true\n", "      - columns: [call_number]\n")
        result = self.resolve("--list")
        self.assertEqual(
            [line.split(" | ")[0] for line in result.stdout.splitlines()],
            ["d-catalog-t-books:call_number", "d-catalog-t-books-c-call_number"],
        )
        result = self.resolve("d-catalog-t-books-c-call_number", "--match-impl")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(
            "d-catalog-t-books-c-call_number は、YAML の主キーかインデックスに含まれている。先に d-catalog-t-books:call_number を解消する",
            result.stderr,
        )
        # インデックスが 1 つだけなら、キー indexes ごと消す
        self.assertEqual(self.resolve("d-catalog-t-books:call_number", "--match-impl").returncode, 0)
        self.assertIn("        definition: 行を作った時刻 (UNIX 時刻のミリ秒)。\n  categories:", self.read(CATALOG_SCHEMA))
        self.assertEqual(self.resolve("d-catalog-t-books-c-call_number", "--match-impl").returncode, 0)
        self.assertNotIn("call_number", self.read(CATALOG_SCHEMA))

    def test_column_in_primary_key_needs_the_table_first(self):
        self.replace(
            "migrations/0001_create_catalog_and_members.sql",
            "  category_id text NOT NULL REFERENCES categories (id),\n  PRIMARY KEY (book_id, category_id)",
            "  PRIMARY KEY (book_id)",
        )
        self.replace("migrations/0001_create_catalog_and_members.sql", "CREATE INDEX book_categories_category_idx ON book_categories (category_id);\n", "")
        result = self.resolve("d-catalog-t-book_categories-c-category_id", "--match-impl")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("先に d-catalog-t-book_categories・d-catalog-t-book_categories:category_id を解消する", result.stderr)

    def test_column_mapped_to_attribute_is_refused_by_check_h(self):
        self.replace(LOANS_MIGRATION, "  member_id text NOT NULL REFERENCES members (id),\n", "")
        self.replace(LOANS_MIGRATION, "CREATE INDEX loans_member_idx ON loans (member_id);\n", "")
        self.assertEqual(self.resolve("d-loans-t-loans:member_id", "--match-impl").returncode, 0)
        before = self.read(LOANS_SCHEMA)
        result = self.resolve("d-loans-t-loans-c-member_id", "--match-impl")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("検査 h:", result.stderr)
        self.assertIn("元に戻した", result.stderr)
        self.assertEqual(self.read(LOANS_SCHEMA), before)

    def test_index(self):
        self.replace(LOANS_MIGRATION, "CREATE INDEX loans_member_idx ON loans (member_id);\n", "")
        result = self.resolve("d-loans-t-loans:member_id", "--match-impl")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("    indexes:\n      - columns: [reservation_id]\n        unique: true\n", self.read(LOANS_SCHEMA))
        self.assert_item_resolved("d-loans-t-loans:member_id")

    def test_table(self):
        self.replace(MEMBERS_SCHEMA, "    planned: true\n    definition: 利用者に発行する", "    definition: 利用者に発行する")
        result = self.resolve("d-members-t-member_cards", "--match-impl")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("member_cards", self.read(MEMBERS_SCHEMA))
        self.assertTrue(self.read(MEMBERS_SCHEMA).endswith("        attribute: d-members-m-member-a-name\n"))
        self.assertEqual(self.resolve("--list").stdout, "解消する差分は無かった\n")

    def test_last_table_of_a_file_deletes_the_file(self):
        relative = "docs/domains/03-members/schema-points.yaml"
        self.write(relative, "tables:\n  points:\n    definition: 利用者のポイント。\n    columns:\n      id:\n        type: text\n        definition: ポイントの ID。\n")
        result = self.resolve("d-members-t-points", "--match-impl")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f"消した: {relative}\n{GENERATE_HINT}\n")
        self.assertFalse((self.project / relative).exists())

    def test_table_referenced_from_another_table_is_refused(self):
        path = "migrations/0002_create_loans.sql"
        text = self.read(path)
        start, end = text.index("CREATE TABLE reservations"), text.index("CREATE TABLE loans")
        self.write(path, text[:start] + text[end:].replace(" REFERENCES reservations (id)", ""))
        relative = "docs/domains/02-loans/reservations/schema.yaml"
        before = self.read(relative)
        result = self.resolve("d-loans-t-reservations", "--match-impl")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("元に戻した", result.stderr)
        self.assertEqual(self.read(relative), before)


if __name__ == "__main__":
    unittest.main()
