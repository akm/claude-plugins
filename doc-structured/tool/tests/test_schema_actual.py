"""実際のスキーマを読む (モジュール schema_actual) のテスト。SQLite のマイグレーションを適用して読む。

PostgreSQL のテストは tests/test_schema_actual_postgresql.py。決めた経緯は Issue #207 のコメントの 1〜4・6・11。
"""

import unittest

from doc_structured.config import DatabaseConfig
from doc_structured.schema_actual import (
    MigrationError,
    check_constraints,
    index_terms,
    index_where,
    migration_files,
    read_schema,
)
from tooltest import ProjectTestCase


def sqlite_config(pattern: str = "migrations/*.sql") -> DatabaseConfig:
    return DatabaseConfig(kind="sqlite", image=None, schema_actual=False, migrations=pattern, migrations_at=(3, 15))


class MigrationFilesTest(ProjectTestCase):
    def test_sorted_by_relative_path(self):
        self.write("migrations/20260102_b/migration.sql", "")
        self.write("migrations/20260101_a/migration.sql", "")
        self.write("migrations/20260101_a/snapshot.json", "")
        self.assertEqual(
            migration_files(self.project, "migrations/**/*.sql"),
            ["migrations/20260101_a/migration.sql", "migrations/20260102_b/migration.sql"],
        )

    def test_only_matching_files(self):
        self.write("migrations/0001_init.up.sql", "")
        self.write("migrations/0001_init.down.sql", "")
        self.assertEqual(migration_files(self.project, "migrations/*.up.sql"), ["migrations/0001_init.up.sql"])

    def test_no_files(self):
        with self.assertRaises(MigrationError) as cm:
            migration_files(self.project, "migrations/*.sql")
        self.assertIn("合うファイルが無い", str(cm.exception))


class ReadSqliteTest(ProjectTestCase):
    def read(self, *migrations: str):
        for number, sql in enumerate(migrations, start=1):
            self.write(f"migrations/{number:04d}.sql", sql)
        return read_schema(self.project, sqlite_config())

    def test_tables_columns_and_keys(self):
        schema = self.read(
            """
            CREATE TABLE `books` (
              `id` text PRIMARY KEY NOT NULL,
              `title` VARCHAR(200) NOT NULL,
              `shelf_status` text DEFAULT 'shelved' NOT NULL,
              `created_at` integer
            );
            --> statement-breakpoint
            CREATE TABLE loans (
              id integer PRIMARY KEY,
              book_id text NOT NULL REFERENCES books(id),
              status text DEFAULT ('on_loan') NOT NULL,
              CONSTRAINT loans_status_check CHECK (status IN ('on_loan', 'returned'))
            );
            """,
            "ALTER TABLE loans ADD member_id text REFERENCES members;\n"
            "CREATE TABLE members (id text NOT NULL, name text NOT NULL CHECK(length(name) > 0), PRIMARY KEY (id));",
        )
        self.assertEqual(schema.kind, "sqlite")
        self.assertEqual(list(schema.tables), ["books", "loans", "members"])
        books = schema.tables["books"]
        self.assertEqual([c.name for c in books.columns], ["id", "title", "shelf_status", "created_at"])
        self.assertEqual(books.primary_key, ["id"])
        title = books.column("title")
        self.assertEqual((title.type, title.not_null, title.default), ("VARCHAR(200)", True, None))
        self.assertEqual(books.column("shelf_status").default, "'shelved'")
        self.assertFalse(books.column("created_at").not_null)
        loans = schema.tables["loans"]
        # INTEGER PRIMARY KEY は NOT NULL を書かなくても NULL を入れられない
        self.assertTrue(loans.column("id").not_null)
        self.assertEqual(loans.column("status").default, "'on_loan'")
        self.assertEqual(
            [(k.columns, k.ref_table, k.ref_columns) for k in loans.foreign_keys],
            [(["book_id"], "books", ["id"]), (["member_id"], "members", ["id"])],
        )
        self.assertEqual(loans.checks, ["status IN ('on_loan', 'returned')"])
        members = schema.tables["members"]
        self.assertEqual(members.primary_key, ["id"])
        self.assertEqual(members.checks, ["length(name) > 0"])

    def test_primary_key_without_not_null_allows_null(self):
        # SQLite では、INTEGER PRIMARY KEY 以外の主キーに NOT NULL を書かないと NULL が入る
        schema = self.read("CREATE TABLE books (id text PRIMARY KEY);")
        self.assertFalse(schema.tables["books"].column("id").not_null)

    def test_without_rowid_integer_primary_key(self):
        schema = self.read("CREATE TABLE codes (id INTEGER PRIMARY KEY) WITHOUT ROWID;")
        # WITHOUT ROWID のテーブルの主キーは、行の識別子の別名ではない。ただし WITHOUT ROWID の主キーは NOT NULL になる
        self.assertTrue(schema.tables["codes"].column("id").not_null)

    def test_composite_primary_key_and_foreign_key(self):
        schema = self.read(
            "CREATE TABLE a (x text NOT NULL, y text NOT NULL, PRIMARY KEY (y, x));\n"
            "CREATE TABLE b (id text PRIMARY KEY NOT NULL, ax text, ay text, FOREIGN KEY (ay, ax) REFERENCES a (y, x));"
        )
        self.assertEqual(schema.tables["a"].primary_key, ["y", "x"])
        key = schema.tables["b"].foreign_keys[0]
        self.assertEqual((key.columns, key.ref_table, key.ref_columns), (["ay", "ax"], "a", ["y", "x"]))

    def test_indexes(self):
        schema = self.read(
            """
            CREATE TABLE visits (id text PRIMARY KEY NOT NULL, table_id text NOT NULL, status text NOT NULL,
              token text NOT NULL UNIQUE, email text NOT NULL);
            CREATE UNIQUE INDEX visits_open ON visits (table_id) WHERE "visits"."status" IN ('open', 'waiting');
            CREATE INDEX visits_status_table ON visits (status, table_id);
            CREATE INDEX visits_email_lower ON visits (lower(email), status);
            """
        )
        indexes = {index.name: index for index in schema.tables["visits"].indexes}
        unique = indexes["visits_open"]
        self.assertEqual((unique.columns, unique.unique, unique.where), (["table_id"], True, "\"visits\".\"status\" IN ('open', 'waiting')"))
        plain = indexes["visits_status_table"]
        self.assertEqual((plain.columns, plain.unique, plain.where, plain.has_expression), (["status", "table_id"], False, None, False))
        expression = indexes["visits_email_lower"]
        self.assertTrue(expression.has_expression)
        self.assertEqual(expression.columns, ["lower(email)", "status"])
        # UNIQUE の制約は、データベースが作るインデックスとして読む。主キーのインデックスは含まない
        constraint = [index for name, index in indexes.items() if name.startswith("sqlite_autoindex")]
        self.assertEqual([(i.columns, i.unique) for i in constraint], [(["token"], True)])
        self.assertEqual(len(indexes), 4)

    def test_data_migrations_are_applied(self):
        schema = self.read(
            "CREATE TABLE stores (id text PRIMARY KEY NOT NULL, term text);",
            "-- 既にある行を直す\nUPDATE stores SET term = 'yearly' WHERE term IS NULL;\nDELETE FROM stores WHERE id = 'x';",
        )
        self.assertEqual(list(schema.tables), ["stores"])

    def test_migration_error_names_file(self):
        with self.assertRaises(MigrationError) as cm:
            self.read("CREATE TABLE books (id text);", "ALTER TABLE missing ADD x text;")
        self.assertEqual(cm.exception.path, "migrations/0002.sql")
        self.assertIn("missing", str(cm.exception))


class SqlTextTest(unittest.TestCase):
    def test_check_constraints_ignore_quotes_and_comments(self):
        sql = (
            "CREATE TABLE t (\n"
            "  note text DEFAULT 'CHECK (x)', -- CHECK (comment)\n"
            "  \"check\" integer CHECK (\"check\" > 0),\n"
            "  CONSTRAINT c CHECK(a < (b + 1))\n"
            ")"
        )
        self.assertEqual(check_constraints(sql), ['"check" > 0', "a < (b + 1)"])

    def test_index_terms_and_where(self):
        sql = "CREATE UNIQUE INDEX i ON t (a, coalesce(b, 'x, y')) WHERE a IS NOT NULL;"
        self.assertEqual(index_terms(sql), ["a", "coalesce(b, 'x, y')"])
        self.assertEqual(index_where(sql), "a IS NOT NULL")
        self.assertIsNone(index_where("CREATE INDEX i ON t (a)"))


if __name__ == "__main__":
    unittest.main()
