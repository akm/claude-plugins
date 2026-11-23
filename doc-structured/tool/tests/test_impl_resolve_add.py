"""サブコマンド impl-diff-resolve の --match-impl のうち、実装にだけある項目を YAML に足す場合のテスト。

決めた経緯は Issue #208 のコメントの 3・4・5・7。
"""

import unittest

from test_impl_resolve_cli import CATALOG_MIGRATION, ResolveTestCase

CATALOG_SCHEMA = "docs/domains/01-catalog/schema.yaml"
LOANS_SCHEMA = "docs/domains/02-loans/schema.yaml"
GENERATE_HINT = "生成したファイルを YAML に合わせるには bin/doc-structured generate を実行する"
FINES_MIGRATION = """\
CREATE TABLE fines (
  id text PRIMARY KEY NOT NULL,
  loan_id text NOT NULL REFERENCES loans (id),
  amount integer DEFAULT 0 NOT NULL,
  CHECK (amount >= 0)
);
CREATE INDEX fines_loan_idx ON fines (loan_id);
CREATE UNIQUE INDEX fines_open_idx ON fines (loan_id, id) WHERE amount > 0;
"""
FINES_OPTIONS = (
    "--definition", "d-loans-t-fines", "延滞金 1 件の行。",
    "--definition", "d-loans-t-fines-c-id", "延滞金を識別する値。",
    "--definition", "d-loans-t-fines-c-loan_id", "延滞した貸出。",
    "--definition", "d-loans-t-fines-c-amount", "延滞金の額 (円)。",
)
FINES_TABLE = """\
  fines:
    definition: 延滞金 1 件の行。
    primary_key: [id]
    columns:
      id:
        type: text
        definition: 延滞金を識別する値。
      loan_id:
        type: text
        references: d-loans-t-loans-c-id
        definition: 延滞した貸出。
      amount:
        type: integer
        default: "0"
        definition: 延滞金の額 (円)。
    indexes:
      - columns: [loan_id]
      - columns: [loan_id, id]
        unique: true
"""


class AddTableTest(ResolveTestCase):
    def setUp(self):
        super().setUp()
        self.write("migrations/0003_fines.sql", FINES_MIGRATION)

    def test_table_with_definitions(self):
        before = self.read(LOANS_SCHEMA)
        result = self.resolve("d-loans-t-fines", "--match-impl", *FINES_OPTIONS)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read(LOANS_SCHEMA), before + FINES_TABLE)
        self.assertEqual(
            result.stdout,
            f"書き換えた: {LOANS_SCHEMA}\n"
            "テーブル fines の CHECK 制約 `amount >= 0` は YAML に書けない。値の持ち方と条件の意味は design.md に書く\n"
            "テーブル fines のインデックス (loan_id, id) の条件 `amount > 0` は YAML に書けない。条件の意味は design.md に書く\n"
            f"{GENERATE_HINT}\n",
        )
        self.assertEqual(self.resolve("--list").stdout, "解消する差分は無かった\n")

    def test_missing_definitions(self):
        before = self.read(LOANS_SCHEMA)
        result = self.resolve("d-loans-t-fines", "--match-impl", *FINES_OPTIONS[:6])
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(
            "定義の文 (--definition) か対応 (--model・--attribute) が無い: d-loans-t-fines-c-loan_id・d-loans-t-fines-c-amount",
            result.stderr,
        )
        self.assertEqual(self.read(LOANS_SCHEMA), before)

    def test_new_file(self):
        relative = "docs/domains/02-loans/schema-fines.yaml"
        result = self.resolve("d-loans-t-fines", "--match-impl", "--file", relative, *FINES_OPTIONS)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith(f"作った: {relative}\n"), result.stdout)
        self.assertEqual(self.read(relative), "tables:\n" + FINES_TABLE)

    def test_file_outside_the_domain(self):
        result = self.resolve("d-loans-t-fines", "--match-impl", "--file", CATALOG_SCHEMA, *FINES_OPTIONS)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(
            f"--file {CATALOG_SCHEMA} は、ドメイン loans のディレクトリ docs/domains/02-loans の下の、"
            "ファイル名が schema で始まる YAML でない",
            result.stderr,
        )

    def test_option_errors(self):
        for args, message in (
            (("--definition", "d-loans-t-other", "x"), "--definition の d-loans-t-other は、この件で足すテーブルかカラムでない"),
            (("--model", "d-loans-t-fines-c-id", "d-loans-m-loan"), "--model は、足すテーブル d-loans-t-fines にだけ指定できる"),
            (("--definition", "d-loans-t-fines", "y"), "--definition に d-loans-t-fines が 2 回ある"),
        ):
            with self.subTest(args=args):
                result = self.resolve("d-loans-t-fines", "--match-impl", *FINES_OPTIONS, *args)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(message, result.stderr)

    def test_options_only_for_additions(self):
        self.replace(CATALOG_MIGRATION, "  call_number text NOT NULL,", "  call_number integer NOT NULL,")
        result = self.resolve("d-catalog-t-books-c-call_number", "--match-impl", "--definition", "d-catalog-t-books-c-call_number", "x")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("--definition・--model・--attribute・--file は、実装にだけあるテーブルかカラムを YAML に足すときだけ使える", result.stderr)

    def test_table_with_model(self):
        # モデル「貸出」の属性は、テーブル loans のカラムがすべて対応を持つので、2 つ目のテーブルにも書ける
        result = self.resolve("d-loans-t-fines", "--match-impl", "--model", "d-loans-t-fines", "d-loans-m-loan", *FINES_OPTIONS[3:])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("  fines:\n    model: d-loans-m-loan\n    primary_key: [id]\n", self.read(LOANS_SCHEMA))

    def test_attribute_of_column_in_table_without_model_is_refused_by_check_h(self):
        before = self.read(LOANS_SCHEMA)
        result = self.resolve(
            "d-loans-t-fines", "--match-impl", *FINES_OPTIONS[:9],
            "--attribute", "d-loans-t-fines-c-amount", "d-loans-m-loan-a-status",
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("元に戻した", result.stderr)
        self.assertEqual(self.read(LOANS_SCHEMA), before)

    def test_reference_to_table_not_in_yaml(self):
        self.write("migrations/0004_payments.sql", "CREATE TABLE payments (id text PRIMARY KEY NOT NULL, fine_id text REFERENCES fines (id));\n")
        result = self.resolve(
            "d-loans-t-payments", "--match-impl", "--definition", "d-loans-t-payments", "支払い。",
            "--definition", "d-loans-t-payments-c-id", "支払いの ID。", "--definition", "d-loans-t-payments-c-fine_id", "延滞金。",
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("先に d-<ドメイン>-t-fines を解消する", result.stderr)


class AddOtherTablesTest(ResolveTestCase):
    def test_intermediate_table_with_attribute_and_self_reference(self):
        self.write(
            "migrations/0003_tree.sql",
            "CREATE TABLE category_tree (\n  id text PRIMARY KEY NOT NULL,\n  parent_id text REFERENCES category_tree (id)\n);\n",
        )
        result = self.resolve(
            "d-catalog-t-category_tree", "--match-impl",
            "--definition", "d-catalog-t-category_tree", "分類の親子。",
            "--definition", "d-catalog-t-category_tree-c-id", "分類の ID。",
            "--definition", "d-catalog-t-category_tree-c-parent_id", "親の分類。",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(
            self.read(CATALOG_SCHEMA).endswith(
                "  category_tree:\n    definition: 分類の親子。\n    primary_key: [id]\n    columns:\n      id:\n        type: text\n"
                "        definition: 分類の ID。\n      parent_id:\n        type: text\n        nullable: true\n"
                "        references: d-catalog-t-category_tree-c-id\n        definition: 親の分類。\n"
            ),
            self.read(CATALOG_SCHEMA),
        )

    def test_table_with_attribute(self):
        self.write(
            "migrations/0003_featured.sql",
            "CREATE TABLE featured_categories (\n  book_id text NOT NULL REFERENCES books (id),\n"
            "  category_id text NOT NULL REFERENCES categories (id),\n  PRIMARY KEY (book_id, category_id)\n);\n",
        )
        result = self.resolve(
            "d-catalog-t-featured_categories", "--match-impl",
            "--attribute", "d-catalog-t-featured_categories", "d-catalog-m-book-a-categories",
            "--definition", "d-catalog-t-featured_categories-c-book_id", "図書。",
            "--definition", "d-catalog-t-featured_categories-c-category_id", "分類。",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("  featured_categories:\n    attribute: d-catalog-m-book-a-categories\n    primary_key: [book_id, category_id]\n", self.read(CATALOG_SCHEMA))


class AddColumnAndIndexTest(ResolveTestCase):
    def test_column_after_the_preceding_column_of_the_implementation(self):
        self.replace(CATALOG_MIGRATION, "  title text NOT NULL,\n", "  title text NOT NULL,\n  rank integer CHECK (rank > 0),\n")
        result = self.resolve("d-catalog-t-books-c-rank", "--match-impl", "--definition", "d-catalog-t-books-c-rank", "図書の順位。")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "        attribute: d-catalog-m-book-a-title\n      rank:\n        type: integer\n        nullable: true\n"
            "        definition: 図書の順位。\n      shelf_status:\n",
            self.read(CATALOG_SCHEMA),
        )
        self.assertEqual(
            result.stdout,
            f"書き換えた: {CATALOG_SCHEMA}\n"
            "テーブル books の CHECK 制約 `rank > 0` は YAML に書けない。値の持ち方と条件の意味は design.md に書く\n"
            f"{GENERATE_HINT}\n",
        )
        self.assert_item_resolved("d-catalog-t-books-c-rank")

    def test_column_with_attribute_at_the_head(self):
        self.replace(CATALOG_MIGRATION, "CREATE TABLE books (\n", "CREATE TABLE books (\n  title_kana text DEFAULT '' NOT NULL,\n")
        result = self.resolve(
            "d-catalog-t-books-c-title_kana", "--match-impl", "--attribute", "d-catalog-t-books-c-title_kana", "d-catalog-m-book-a-title"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "    columns:\n      title_kana:\n        type: text\n        default: \"''\"\n        attribute: d-catalog-m-book-a-title\n"
            "      id:\n",
            self.read(CATALOG_SCHEMA),
        )

    def test_index_needs_its_columns(self):
        self.replace(CATALOG_MIGRATION, "  title text NOT NULL,\n", "  title text NOT NULL,\n  rank integer,\n")
        self.write("migrations/0003_index.sql", "CREATE INDEX books_rank_idx ON books (rank) WHERE rank IS NOT NULL;\n")
        result = self.resolve("d-catalog-t-books:rank", "--match-impl")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("d-catalog-t-books:rank のカラム rank が YAML に無い。先に d-catalog-t-books-c-rank を解消する", result.stderr)
        self.assertEqual(self.resolve("d-catalog-t-books-c-rank", "--match-impl", "--definition", "d-catalog-t-books-c-rank", "順位。").returncode, 0)
        result = self.resolve("d-catalog-t-books:rank", "--match-impl")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("テーブル books のインデックス (rank) の条件 `rank IS NOT NULL` は YAML に書けない", result.stdout)
        self.assertIn("        definition: 行を作った時刻 (UNIX 時刻のミリ秒)。\n    indexes:\n      - columns: [rank]\n  categories:", self.read(CATALOG_SCHEMA))
        self.assertEqual(self.resolve("--list").stdout, "解消する差分は無かった\n")

    def test_index_appended(self):
        self.write("migrations/0003_index.sql", "CREATE UNIQUE INDEX loans_book_idx ON loans (book_id, member_id);\n")
        result = self.resolve("d-loans-t-loans:book_id,member_id", "--match-impl")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.read(LOANS_SCHEMA).endswith("        unique: true\n      - columns: [book_id, member_id]\n        unique: true\n"))


if __name__ == "__main__":
    unittest.main()
