"""サブコマンド impl-diff-resolve の --match-impl のうち、planned を外して比べる項目を合わせる場合と、比べる項目を書き換える場合のテスト。

決めた経緯は Issue #208 のコメントの 2・5。
"""

import unittest

from doc_structured.config import load_config, find_config
from doc_structured.domains import load_project
from doc_structured.impl_resolve import MATCH_IMPL, Request, resolve
from doc_structured.schema_actual import read_schema
from test_impl_resolve_cli import CATALOG_MIGRATION, LOANS_MIGRATION, MEMBERS_SCHEMA, ResolveTestCase

CATALOG_SCHEMA = "docs/domains/01-catalog/schema.yaml"
LOANS_SCHEMA = "docs/domains/02-loans/schema.yaml"
CARDS_MIGRATION = """\
CREATE TABLE member_cards (
  id text NOT NULL,
  member_id text NOT NULL REFERENCES members (id),
  PRIMARY KEY (id, member_id)
);
CREATE UNIQUE INDEX member_cards_member_idx ON member_cards (member_id);
"""


class MatchColumnTest(ResolveTestCase):
    def test_type_and_null(self):
        self.replace(CATALOG_MIGRATION, "  call_number text NOT NULL,", "  call_number integer,")
        result = self.resolve("d-catalog-t-books-c-call_number", "--match-impl")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "      call_number:\n        type: integer\n        nullable: true\n        definition: 図書の請求記号。\n",
            self.read(CATALOG_SCHEMA),
        )
        self.assert_item_resolved("d-catalog-t-books-c-call_number")

    def test_default_changed_and_removed(self):
        self.replace(CATALOG_MIGRATION, "DEFAULT 'shelved'", "DEFAULT 'on_shelf'")
        self.replace(LOANS_MIGRATION, "  status text DEFAULT 'on_loan' NOT NULL,", "  status text NOT NULL,")
        self.assertEqual(self.resolve("d-catalog-t-books-c-shelf_status", "--match-impl").returncode, 0)
        self.assertEqual(self.resolve("d-loans-t-loans-c-status", "--match-impl").returncode, 0)
        self.assertIn("      shelf_status:\n        type: text\n        default: \"'on_shelf'\"\n", self.read(CATALOG_SCHEMA))
        self.assertIn("      status:\n        type: text\n        attribute: d-loans-m-loan-a-status\n", self.read(LOANS_SCHEMA))
        self.assertEqual(self.resolve("--list").stdout, "解消する差分は無かった\n")

    def test_default_expression_is_normalized(self):
        self.replace(CATALOG_MIGRATION, "  created_at integer NOT NULL,", "  created_at integer DEFAULT (CURRENT_TIMESTAMP) NOT NULL,")
        self.assertEqual(self.resolve("d-catalog-t-books-c-created_at", "--match-impl").returncode, 0)
        self.assertIn('      created_at:\n        type: integer\n        default: "current_timestamp"\n', self.read(CATALOG_SCHEMA))

    def test_references_removed(self):
        self.replace(LOANS_MIGRATION, "  reservation_id text REFERENCES reservations (id),", "  reservation_id text,")
        result = self.resolve("d-loans-t-loans-c-reservation_id", "--match-impl")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "      reservation_id:\n        type: text\n        nullable: true\n        attribute: d-loans-m-loan-a-reservation\n",
            self.read(LOANS_SCHEMA),
        )
        self.assert_item_resolved("d-loans-t-loans-c-reservation_id")

    def test_references_added(self):
        self.replace(CATALOG_MIGRATION, "  created_at integer NOT NULL,", "  created_at integer NOT NULL,\n  owner_id text REFERENCES members (id),")
        self.replace(
            CATALOG_SCHEMA,
            "        definition: 行を作った時刻 (UNIX 時刻のミリ秒)。\n",
            "        definition: 行を作った時刻 (UNIX 時刻のミリ秒)。\n      owner_id:\n        type: text\n        nullable: true\n"
            "        definition: 図書を寄贈した利用者。\n",
        )
        result = self.resolve("d-catalog-t-books-c-owner_id", "--match-impl")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "        nullable: true\n        references: d-members-t-members-c-id\n        definition: 図書を寄贈した利用者。\n",
            self.read(CATALOG_SCHEMA),
        )

    def test_references_to_table_not_in_yaml(self):
        self.write("migrations/0003_fines.sql", "CREATE TABLE fines (id text PRIMARY KEY NOT NULL);\n")
        self.replace(LOANS_MIGRATION, "  member_id text NOT NULL REFERENCES members (id),", "  member_id text NOT NULL REFERENCES fines (id),")
        before = self.read(LOANS_SCHEMA)
        result = self.resolve("d-loans-t-loans-c-member_id", "--match-impl")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(
            "テーブル loans のカラム member_id の外部キーの参照先のテーブル fines が YAML に無い。先に d-<ドメイン>-t-fines を解消する",
            result.stderr,
        )
        self.assertEqual(self.read(LOANS_SCHEMA), before)

    def test_nullable_primary_key_column(self):
        self.replace(CATALOG_MIGRATION, "  id text PRIMARY KEY NOT NULL,\n  title", "  id text PRIMARY KEY,\n  title")
        result = self.resolve("d-catalog-t-books-c-id", "--match-impl")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(
            "d-catalog-t-books-c-id は主キーのカラムなので、YAML に nullable: true を書けない。"
            "マイグレーションで、主キーのカラムに NOT NULL を付ける",
            result.stderr,
        )

    def test_planned_column_implemented_with_another_type(self):
        self.replace(LOANS_MIGRATION, "  status text DEFAULT 'on_loan' NOT NULL,", "  status text DEFAULT 'on_loan' NOT NULL,\n  returned_at text,")
        result = self.resolve("d-loans-t-loans-c-returned_at", "--match-impl")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("      returned_at:\n        type: text\n        nullable: true\n        definition: 図書が返った", self.read(LOANS_SCHEMA))
        self.assertEqual(self.resolve("--list").stdout, "解消する差分は無かった\n")


class MatchTableAndIndexTest(ResolveTestCase):
    def test_primary_key(self):
        self.replace(CATALOG_MIGRATION, "  PRIMARY KEY (book_id, category_id)", "  PRIMARY KEY (category_id, book_id)")
        result = self.resolve("d-catalog-t-book_categories", "--match-impl")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("    primary_key: [category_id, book_id]\n", self.read(CATALOG_SCHEMA))
        self.assert_item_resolved("d-catalog-t-book_categories")

    def test_primary_key_with_column_not_in_yaml(self):
        self.replace(
            CATALOG_MIGRATION,
            "  category_id text NOT NULL REFERENCES categories (id),\n  PRIMARY KEY (book_id, category_id)",
            "  category_id text NOT NULL REFERENCES categories (id),\n  shelf text NOT NULL,\n"
            "  PRIMARY KEY (book_id, category_id, shelf)",
        )
        result = self.resolve("d-catalog-t-book_categories", "--match-impl")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(
            "テーブル d-catalog-t-book_categories の実装の主キーのカラム shelf が YAML に無い。"
            "先に d-catalog-t-book_categories-c-shelf を解消する",
            result.stderr,
        )

    def test_planned_table_implemented(self):
        self.write("migrations/0003_cards.sql", CARDS_MIGRATION)
        result = self.resolve("d-members-t-member_cards", "--match-impl")
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.read(MEMBERS_SCHEMA)
        self.assertIn("  member_cards:\n    definition: 利用者に発行する利用者カード 1 枚の行。\n    primary_key: [id, member_id]\n", text)
        # 主キーのほかの違い (インデックスの一意) は、別の件として残る
        result = self.resolve("--list")
        self.assertEqual([line.split(" | ")[0] for line in result.stdout.splitlines()], ["d-members-t-member_cards:member_id"])
        result = self.resolve("d-members-t-member_cards:member_id", "--match-impl")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("      - columns: [member_id]\n        unique: true\n", self.read(MEMBERS_SCHEMA))
        self.assertEqual(self.resolve("--list").stdout, "解消する差分は無かった\n")

    def test_index_no_longer_unique(self):
        self.replace(CATALOG_MIGRATION, "  name text NOT NULL UNIQUE\n", "  name text NOT NULL\n")
        self.write("migrations/0003_index.sql", "CREATE INDEX categories_name_idx ON categories (name);\n")
        result = self.resolve("d-catalog-t-categories:name", "--match-impl")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("    indexes:\n      - columns: [name]\n  book_categories:", self.read(CATALOG_SCHEMA))
        self.assert_item_resolved("d-catalog-t-categories:name")

    def test_planned_index_implemented_as_unique(self):
        self.replace(LOANS_SCHEMA, "      - columns: [member_id]\n", "      - columns: [member_id]\n        planned: true\n")
        self.replace(LOANS_MIGRATION, "CREATE INDEX loans_member_idx", "CREATE UNIQUE INDEX loans_member_idx")
        result = self.resolve("d-loans-t-loans:member_id", "--match-impl")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("      - columns: [member_id]\n        unique: true\n      - columns: [reservation_id]\n", self.read(LOANS_SCHEMA))
        self.assert_item_resolved("d-loans-t-loans:member_id")


class PostgreSQLSerialTest(ResolveTestCase):
    """PostgreSQL の連番のカラムは、型 serial などで書き、デフォルト値を書かない。Docker を使わずに、読んだ実際のスキーマを
    PostgreSQL のものに変えて確認する。"""

    def test_serial_column(self):
        config = load_config(find_config(self.project))
        actual = read_schema(self.project, config.database)
        actual.kind = "postgresql"
        column = actual.tables["members"].column("name")
        column.type, column.default, column.owned_sequence = "bigint", "nextval('members_name_seq'::regclass)", True
        project, problems = load_project(self.project)
        self.assertEqual(problems, [])
        result = resolve(self.project, project, actual, Request("d-members-t-members-c-name", MATCH_IMPL))
        self.assertEqual(result.written, [MEMBERS_SCHEMA])
        self.assertIn("      name:\n        type: bigserial\n        attribute: d-members-m-member-a-name\n", self.read(MEMBERS_SCHEMA))


if __name__ == "__main__":
    unittest.main()
