"""サブコマンド impl-diff-resolve の入口と件の一覧 (--list) のテスト。サンプルのプロジェクトのコピーに差分を入れて確認する。

決めた経緯は Issue #208 のコメントの 1・2・10・12。
"""

import subprocess
import unittest

from tooltest import PYTHON, ProjectTestCase, clean_env

CATALOG_MIGRATION = "migrations/0001_create_catalog_and_members.sql"
LOANS_MIGRATION = "migrations/0002_create_loans.sql"
MEMBERS_SCHEMA = "docs/domains/03-members/schema.yaml"

# 実装にだけあるテーブル・カラム・インデックスと、planned のテーブルの実装
EXTRA_MIGRATION = """\
CREATE TABLE fines (
  id text PRIMARY KEY NOT NULL,
  loan_id text NOT NULL REFERENCES loans (id),
  amount integer DEFAULT 0 NOT NULL,
  CHECK (amount >= 0)
);
ALTER TABLE books ADD COLUMN isbn text;
CREATE INDEX books_title_idx ON books (title);
CREATE TABLE member_cards (id text PRIMARY KEY NOT NULL, member_id text NOT NULL REFERENCES members (id));
CREATE INDEX member_cards_member_idx ON member_cards (member_id);
"""


class ResolveTestCase(ProjectTestCase):
    """サンプルのプロジェクトのコピーで impl-diff-resolve を実行するテストの基底。"""

    def setUp(self) -> None:
        super().setUp()
        self.copy_sample()
        self.disable_schema_actual()

    def run_tool(self, *args: str):
        return subprocess.run(
            [PYTHON, "-m", "doc_structured", *args], cwd=self.project, env=clean_env(), capture_output=True, text=True
        )

    def resolve(self, *args: str):
        return self.run_tool("impl-diff-resolve", *args)

    def replace(self, relative: str, old: str, new: str) -> None:
        path = self.project / relative
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1), encoding="utf-8")

    def read(self, relative: str) -> str:
        return (self.project / relative).read_text(encoding="utf-8")

    def add_differences(self) -> None:
        """差分を 7 件入れる (実装だけのテーブル・カラム 2 つ・インデックス、planned のテーブルの実装、型と NULL の違い、
        実装に無いカラム)。"""
        self.write("migrations/0003_extra.sql", EXTRA_MIGRATION)
        self.replace(CATALOG_MIGRATION, "  call_number text NOT NULL,", "  call_number integer,")
        self.replace(CATALOG_MIGRATION, "  name text NOT NULL\n);", "  name text NOT NULL,\n  email text\n);")
        self.replace(
            MEMBERS_SCHEMA,
            "        attribute: d-members-m-member-a-name\n",
            "        attribute: d-members-m-member-a-name\n"
            "      phone:\n        type: text\n        nullable: true\n        definition: 利用者の電話番号。\n",
        )

    def assert_item_resolved(self, item_id: str) -> None:
        """件の一覧に、その ID の件が無い (その件の検査 j が成功する)。"""
        result = self.resolve("--list")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(f"{item_id} |", result.stdout)


class ListTest(ResolveTestCase):
    def test_no_difference(self):
        result = self.resolve("--list")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "解消する差分は無かった\n")

    def test_lists_cases_in_resolving_order(self):
        self.add_differences()
        result = self.resolve("--list")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                "d-<ドメイン>-t-fines | --match-impl | テーブル fines が実装にあるが YAML に無い。YAML に足す (または実装を戻す)",
                "d-members-t-member_cards | --unplanned --match-impl | "
                "テーブル d-members-t-member_cards は実装されたので、planned を外す",
                "d-catalog-t-books-c-call_number | --match-impl | "
                "カラム d-catalog-t-books-c-call_number の型が違う (設計 text、実装 integer)。YAML か実装を直す "
                "カラム d-catalog-t-books-c-call_number の NULL を許可するかが違う (設計 許可しない、実装 許可する)。YAML か実装を直す",
                "d-catalog-t-books-c-isbn | --match-impl | "
                "テーブル d-catalog-t-books のカラム isbn が実装にあるが YAML に無い。YAML に足す (または実装を戻す)",
                "d-members-t-members-c-phone | --planned --match-impl | "
                "カラム d-members-t-members-c-phone が実装に無い。planned: true を付けるか、YAML から消す",
                "d-members-t-members-c-email | --match-impl | "
                "テーブル d-members-t-members のカラム email が実装にあるが YAML に無い。YAML に足す (または実装を戻す)",
                "d-catalog-t-books:title | --match-impl | "
                "テーブル d-catalog-t-books のインデックス (title) が実装にあるが YAML に無い。YAML に足す (または実装を戻す)",
            ],
        )

    def test_index_to_delete_comes_before_columns_and_primary_key_change(self):
        # 実装でカラム member_id を消すと、YAML のインデックス (member_id) を先に消し、カラムはその後
        self.replace(LOANS_MIGRATION, "  member_id text NOT NULL REFERENCES members (id),\n", "")
        self.replace(LOANS_MIGRATION, "CREATE INDEX loans_member_idx ON loans (member_id);\n", "")
        result = self.resolve("--list")
        ids = [line.split(" | ")[0] for line in result.stdout.splitlines()]
        self.assertEqual(ids, ["d-loans-t-loans:member_id", "d-loans-t-loans-c-member_id"])

    def test_primary_key_with_new_column_comes_after_columns(self):
        self.replace(
            CATALOG_MIGRATION,
            "  category_id text NOT NULL REFERENCES categories (id),\n  PRIMARY KEY (book_id, category_id)",
            "  category_id text NOT NULL REFERENCES categories (id),\n  shelf text NOT NULL,\n"
            "  PRIMARY KEY (book_id, category_id, shelf)",
        )
        result = self.resolve("--list")
        ids = [line.split(" | ")[0] for line in result.stdout.splitlines()]
        self.assertEqual(ids, ["d-catalog-t-book_categories-c-shelf", "d-catalog-t-book_categories"])


class ArgumentsTest(ResolveTestCase):
    def test_id_and_flag_are_required(self):
        for args in ((), ("d-loans-t-loans",), ("--match-impl",), ("--list", "d-loans-t-loans"), ("--list", "--file", "x")):
            with self.subTest(args=args):
                result = self.resolve(*args)
                self.assertEqual(result.returncode, 2, result.stderr)

    def test_two_flags(self):
        result = self.resolve("d-loans-t-loans", "--planned", "--match-impl")
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_unknown_id(self):
        self.add_differences()
        for given in ("d-loans-t-loans", "d-loans-t-nothing", "not an id"):
            with self.subTest(given=given):
                result = self.resolve(given, "--match-impl")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(f"ID {given} の差分の件は無い。差分の件は bin/doc-structured impl-diff-resolve --list で見る", result.stderr)
                self.assertIn("何も書き換えなかった", result.stderr)

    def test_unknown_domain_of_new_table(self):
        self.add_differences()
        result = self.resolve("d-nothing-t-fines", "--match-impl")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("ID d-nothing-t-fines のドメイン nothing は無い (テーブルを足すドメインを ID に書く)", result.stderr)

    def test_flag_not_usable_for_the_case(self):
        self.add_differences()
        before = self.read(MEMBERS_SCHEMA)
        for given, flag, usable in (
            ("d-members-t-member_cards", "--planned", "--unplanned・--match-impl"),
            ("d-members-t-members-c-phone", "--unplanned", "--planned・--match-impl"),
            ("d-members-t-members-c-email", "--planned", "--match-impl"),
            ("d-catalog-t-books-c-call_number", "--unplanned", "--match-impl"),
        ):
            with self.subTest(given=given, flag=flag):
                result = self.resolve(given, flag)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(f"{given} に {flag} は使えない。この項目に使えるフラグは {usable} (", result.stderr)
        self.assertEqual(self.read(MEMBERS_SCHEMA), before)

    def test_yaml_errors(self):
        self.replace(MEMBERS_SCHEMA, "type: text", "type: ''")
        for args in (("--list",), ("d-members-t-members", "--match-impl")):
            with self.subTest(args=args):
                result = self.resolve(*args)
                self.assertEqual(result.returncode, 1)
                self.assertIn("YAML に 1 件の誤りがあるので、設計と実装を比べなかった", result.stderr)

    def test_without_database_config(self):
        self.write_config()
        result = self.resolve("--list")
        self.assertEqual(result.returncode, 1)
        self.assertIn("設定に paths.migrations と database を書く", result.stderr)

    def test_migration_error(self):
        self.write("migrations/0003_broken.sql", "CREATE TABLE broken (\n")
        result = self.resolve("--list")
        self.assertEqual(result.returncode, 1)
        self.assertIn("migrations/0003_broken.sql", result.stderr)
        self.assertIn("マイグレーションを適用できないので、設計と実装を比べなかった", result.stderr)


if __name__ == "__main__":
    unittest.main()
