"""設計と実際のスキーマの比べ方 (モジュール schema_diff) のテスト。

サンプルのプロジェクト (架空の題材「図書館の貸出」) の YAML と SQLite のマイグレーションを一時ディレクトリにコピーし、片方を変えて、
結果の表の 6 つの行と、比べない項目だけが違うときに差分にならないことを確認する。決めた経緯は Issue #207 のコメントの 5〜8。
"""

import unittest

from doc_structured.config import find_config, load_config
from doc_structured.domains import load_project
from doc_structured.impl_diff import judge, unified
from doc_structured.schema_actual import read_schema
from doc_structured.schema_diff import LABELS, compare, normalize_default, normalize_type
from doc_structured.impl_diff import Location
from tooltest import ProjectTestCase

LOANS_SCHEMA = "docs/domains/02-loans/schema.yaml"
MEMBERS_SCHEMA = "docs/domains/03-members/schema.yaml"
CATALOG_SCHEMA = "docs/domains/01-catalog/schema.yaml"
LOANS_MIGRATION = "migrations/0002_create_loans.sql"
CATALOG_MIGRATION = "migrations/0001_create_catalog_and_members.sql"
CONFIG = ".claude/akm-claude-plugins/doc-structured/config.yaml"


class SampleDiffCase(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.copy_sample()

    def replace(self, relative: str, old: str, new: str) -> None:
        path = self.project / relative
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1), encoding="utf-8")

    def diff(self):
        config = load_config(find_config(self.project))
        project, problems = load_project(self.project)
        self.assertEqual(problems, [])
        result = compare(project, read_schema(self.project, config.database))
        fallback = Location(CONFIG, *config.database.migrations_at)
        return [p.format() for p in judge(result.items, LABELS, fallback)], result

    def messages(self) -> list[str]:
        return self.diff()[0]


class ResultTableTest(SampleDiffCase):
    """決定の一覧の検査 j の結果の表の、6 つの行。"""

    def test_sample_has_no_difference(self):
        # 1 行目: YAML にあり、実装にあり、planned が無い → 成功 (サンプルのすべてのテーブルとカラム)
        messages, result = self.diff()
        self.assertEqual(messages, [])
        self.assertEqual(unified(result.design_lines, result.actual_lines, "設計", "実装"), "")

    def test_planned_but_implemented(self):
        # 2 行目: YAML にあり、実装にあり、planned がある → エラー
        self.replace(LOANS_MIGRATION, "  status text DEFAULT 'on_loan' NOT NULL,", "  status text DEFAULT 'on_loan' NOT NULL,\n  returned_at integer,")
        self.assertEqual(
            self.messages(),
            [f"{LOANS_SCHEMA}:27:7: 検査 j: カラム d-loans-t-loans-c-returned_at は実装されたので、planned を外す"],
        )

    def test_planned_table_but_implemented_reports_table_only(self):
        self.replace(
            CATALOG_MIGRATION, "CREATE TABLE members (",
            "CREATE TABLE member_cards (id text PRIMARY KEY NOT NULL, member_id text NOT NULL, extra text);\nCREATE TABLE members (",
        )
        messages = self.messages()
        self.assertEqual(len(messages), 1)
        self.assertIn("テーブル d-members-t-member_cards は実装されたので、planned を外す", messages[0])

    def test_planned_and_not_implemented(self):
        # 3 行目: YAML にあり、実装に無く、planned がある → 成功 (サンプルの returned_at と member_cards)。設計の行にも出さない
        _, result = self.diff()
        self.assertFalse(any("returned_at" in line or "member_cards" in line for line in result.design_lines))

    def test_not_implemented_without_planned(self):
        # 4 行目: YAML にあり、実装に無く、planned が無い → エラー
        self.replace(LOANS_SCHEMA, "        planned: true\n", "")
        self.assertEqual(
            self.messages(),
            [
                f"{LOANS_SCHEMA}:27:7: 検査 j: カラム d-loans-t-loans-c-returned_at が実装に無い。"
                "planned: true を付けるか、YAML から消す"
            ],
        )

    def test_implemented_but_not_in_yaml(self):
        # 5 行目: YAML に無く、実装にある → エラー。位置は設定ファイルの paths.migrations
        self.replace(LOANS_MIGRATION, "CREATE INDEX loans_member_idx", "CREATE TABLE fines (id text PRIMARY KEY NOT NULL);\nCREATE INDEX loans_member_idx")
        self.replace(LOANS_MIGRATION, "  status text DEFAULT 'on_loan' NOT NULL,", "  status text DEFAULT 'on_loan' NOT NULL,\n  note text,")
        self.assertEqual(
            sorted(self.messages()),
            [
                f"{CONFIG}:4:15: 検査 j: テーブル d-loans-t-loans のカラム note が実装にあるが YAML に無い。YAML に足す (または実装を戻す)",
                f"{CONFIG}:4:15: 検査 j: テーブル fines が実装にあるが YAML に無い。YAML に足す (または実装を戻す)",
            ],
        )

    def test_compared_values_differ(self):
        # 6 行目: 比べる項目が違う → エラー
        self.replace(LOANS_MIGRATION, "  reservation_id text REFERENCES", "  reservation_id integer REFERENCES")
        self.replace(LOANS_MIGRATION, "  member_id text NOT NULL REFERENCES members (id),", "  member_id text NOT NULL,")
        self.replace(LOANS_MIGRATION, "status text DEFAULT 'on_loan' NOT NULL,\n  CONSTRAINT", "status text DEFAULT 'lent' NOT NULL,\n  CONSTRAINT")
        self.replace(CATALOG_MIGRATION, "  created_at integer NOT NULL,", "  created_at integer,")
        self.replace(CATALOG_MIGRATION, "  PRIMARY KEY (book_id, category_id)", "  PRIMARY KEY (category_id, book_id)")
        self.replace(LOANS_MIGRATION, "CREATE INDEX loans_member_idx ON loans (member_id);", "CREATE UNIQUE INDEX loans_member_idx ON loans (member_id);")
        messages = self.messages()
        expected = [
            "カラム d-loans-t-loans-c-reservation_id の型が違う (設計 text、実装 integer)。YAML か実装を直す",
            "カラム d-loans-t-loans-c-member_id の外部キーの参照先が違う (設計 members.id、実装 無し)。YAML か実装を直す",
            "カラム d-loans-t-loans-c-status のデフォルト値が違う (設計 'on_loan'、実装 'lent')。YAML か実装を直す",
            "カラム d-catalog-t-books-c-created_at の NULL を許可するかが違う (設計 許可しない、実装 許可する)。YAML か実装を直す",
            "テーブル d-catalog-t-book_categories の主キーが違う (設計 book_id, category_id、実装 category_id, book_id)。YAML か実装を直す",
            "テーブル d-loans-t-loans のインデックス (member_id) の一意かどうかが違う (設計 一意でない、実装 一意)。YAML か実装を直す",
        ]
        for message in expected:
            self.assertTrue(any(message in m for m in messages), (message, messages))
        self.assertEqual(len(messages), len(expected))

    def test_index_only_in_design_and_only_in_implementation(self):
        self.replace(LOANS_MIGRATION, "CREATE INDEX loans_member_idx ON loans (member_id);", "CREATE INDEX loans_member_idx ON loans (member_id, book_id);")
        self.assertEqual(
            sorted(self.messages()),
            [
                f"{CONFIG}:4:15: 検査 j: テーブル d-loans-t-loans のインデックス (member_id, book_id) が実装にあるが YAML に無い。"
                "YAML に足す (または実装を戻す)",
                f"{LOANS_SCHEMA}:33:9: 検査 j: テーブル d-loans-t-loans のインデックス (member_id) が実装に無い。"
                "planned: true を付けるか、YAML から消す",
            ],
        )

    def test_primary_key_without_not_null(self):
        self.replace(CATALOG_MIGRATION, "  id text PRIMARY KEY NOT NULL,\n  name text NOT NULL\n", "  id text PRIMARY KEY,\n  name text NOT NULL\n")
        self.assertEqual(
            self.messages(),
            [
                f"{MEMBERS_SCHEMA}:7:7: 検査 j: カラム d-members-t-members-c-id の NULL を許可するかが違う (設計 許可しない、実装 許可する)。"
                "マイグレーションで、主キーのカラムに NOT NULL を付ける (YAML の主キーのカラムには nullable を書けない)"
            ],
        )

    def test_unified_diff(self):
        self.replace(LOANS_MIGRATION, "  reservation_id text REFERENCES", "  reservation_id integer REFERENCES")
        _, result = self.diff()
        text = unified(result.design_lines, result.actual_lines, "設計", "実装")
        self.assertIn("-table loans column reservation_id: text null\n", text)
        self.assertIn("+table loans column reservation_id: integer null\n", text)


class NotComparedTest(SampleDiffCase):
    """比べない項目 (カラムの並び順・制約とインデックスの名前・コメント・CHECK 制約・部分インデックスの条件) だけが違うとき、差分にならない。"""

    def test_not_compared_items_only(self):
        # カラムの並び順
        self.replace(
            CATALOG_MIGRATION,
            "  title text NOT NULL,\n  shelf_status text DEFAULT 'shelved' NOT NULL,",
            "  shelf_status text DEFAULT 'shelved' NOT NULL,\n  title text NOT NULL,",
        )
        # 制約とインデックスの名前・コメント・CHECK 制約・部分インデックスの条件
        self.replace(LOANS_MIGRATION, "CONSTRAINT loans_status_check CHECK (status IN ('on_loan', 'returned'))", "CONSTRAINT other_name CHECK (length(status) > 0)")
        self.replace(LOANS_MIGRATION, "CREATE INDEX loans_member_idx", "-- 別の名前にした\nCREATE INDEX idx_loans_by_member")
        self.replace(LOANS_MIGRATION, "WHERE reservation_id IS NOT NULL", "WHERE status = 'on_loan'")
        self.replace(CATALOG_MIGRATION, "  CHECK (shelf_status IN ('shelved', 'on_loan'))\n", "  CHECK (1)\n")
        # 外部キーの制約の名前と ON DELETE
        self.replace(LOANS_MIGRATION, "  book_id text NOT NULL REFERENCES books (id),\n  previous_id", "  book_id text NOT NULL,\n  previous_id")
        self.replace(
            LOANS_MIGRATION, "  status text DEFAULT 'waiting' NOT NULL\n",
            "  status text DEFAULT 'waiting' NOT NULL,\n  CONSTRAINT fk_any FOREIGN KEY (book_id) REFERENCES books (id) ON DELETE CASCADE\n",
        )
        # 書き方の違い (大文字・小文字・空白・括弧)
        self.replace(LOANS_MIGRATION, "  status text DEFAULT 'on_loan' NOT NULL,", "  status TEXT   DEFAULT ('on_loan') NOT NULL,")
        messages, result = self.diff()
        self.assertEqual(messages, [])
        self.assertEqual(unified(result.design_lines, result.actual_lines, "設計", "実装"), "")

    def test_expression_index_and_multi_column_foreign_key_are_not_compared(self):
        self.replace(LOANS_MIGRATION, "CREATE INDEX loans_member_idx", "CREATE INDEX loans_lower_status ON loans (lower(status));\nCREATE INDEX loans_member_idx")
        self.replace(
            CATALOG_MIGRATION, "  PRIMARY KEY (book_id, category_id)\n",
            "  PRIMARY KEY (book_id, category_id),\n  FOREIGN KEY (book_id, category_id) REFERENCES book_categories (book_id, category_id)\n",
        )
        self.assertEqual(self.messages(), [])


class NormalizeTest(unittest.TestCase):
    def test_type_common(self):
        self.assertEqual(normalize_type("  VARCHAR ( 255 ) ", "sqlite"), ("varchar(255)", False))
        self.assertEqual(normalize_type("NUMERIC(10,2)", "sqlite"), ("numeric(10, 2)", False))
        # SQLite では別名を同じものとして扱わない
        self.assertEqual(normalize_type("int", "sqlite"), ("int", False))

    def test_type_postgresql_aliases(self):
        cases = {
            "int": "integer",
            "INT4": "integer",
            "int8": "bigint",
            "varchar(255)": "character varying(255)",
            "varchar": "character varying",
            "char": "character(1)",
            "char(3)": "character(3)",
            "timestamptz": "timestamp with time zone",
            "timestamp": "timestamp without time zone",
            "timestamp(3)": "timestamp(3) without time zone",
            "timestamp with time zone": "timestamp with time zone",
            "bool": "boolean",
            "float8": "double precision",
            "decimal(10,2)": "numeric(10, 2)",
            "text[]": "text[]",
            "int[]": "integer[]",
        }
        for written, expected in cases.items():
            self.assertEqual(normalize_type(written, "postgresql"), (expected, False), written)

    def test_type_postgresql_serial(self):
        self.assertEqual(normalize_type("serial", "postgresql"), ("integer", True))
        self.assertEqual(normalize_type("BIGSERIAL", "postgresql"), ("bigint", True))
        self.assertEqual(normalize_type("serial", "sqlite"), ("serial", False))

    def test_default(self):
        self.assertEqual(normalize_default(None, "sqlite", "text"), "")
        self.assertEqual(normalize_default(" FALSE ", "sqlite", "integer"), "false")
        self.assertEqual(normalize_default("('Closed')", "sqlite", "text"), "'Closed'")
        self.assertEqual(normalize_default("(unixepoch())", "sqlite", "integer"), "unixepoch()")
        self.assertEqual(normalize_default("(1) + (2)", "sqlite", "integer"), "(1) + (2)")
        self.assertEqual(normalize_default("CURRENT_TIMESTAMP", "sqlite", "text"), "current_timestamp")

    def test_default_postgresql_cast(self):
        self.assertEqual(normalize_default("'on_loan'::text", "postgresql", "text"), "'on_loan'")
        self.assertEqual(
            normalize_default("'a'::character varying", "postgresql", "character varying(20)"), "'a'"
        )
        # カラムの型と違う型への型変換は除かない
        self.assertEqual(normalize_default("'2026-01-01'::date", "postgresql", "text"), "'2026-01-01'::date")


if __name__ == "__main__":
    unittest.main()
