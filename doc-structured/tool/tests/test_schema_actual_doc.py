"""実際のスキーマのファイル docs/system/schema-actual.md の生成と、generate --all・検査 a・検査 j での扱いと、
生成したファイルの保護 (hook・docs/.gitattributes) のテスト。題材はサンプルのプロジェクトのコピー。

決めた経緯は Issue #207 のコメントの 9・10。
"""

import json
import subprocess
import unittest

from doc_structured.config import DatabaseConfig
from doc_structured.schema_actual import ActualColumn, ActualForeignKey, ActualIndex, ActualSchema, ActualTable
from doc_structured.schema_diff import render_schema_actual
from tooltest import CONFIG_RELATIVE_PATH, PLUGIN_DIR, PYTHON, ProjectTestCase, clean_env

SCHEMA_ACTUAL = "docs/system/schema-actual.md"
LOANS_MIGRATION = "migrations/0002_create_loans.sql"
HOOK_SCRIPT = PLUGIN_DIR / "hook-scripts" / "guard-generated.py"


class RenderTest(unittest.TestCase):
    def test_contents(self):
        table = ActualTable(
            name="visits",
            columns=[
                ActualColumn("id", "INTEGER", True, None),
                ActualColumn("table_id", "text", True, None),
                ActualColumn("store_id", "text", False, None),
                ActualColumn("status", "text", True, "'open'"),
            ],
            primary_key=["id"],
            foreign_keys=[
                ActualForeignKey(["table_id"], "tables", ["id"]),
                ActualForeignKey(["store_id", "table_id"], "tables", ["store_id", "id"]),
            ],
            indexes=[
                ActualIndex("visits_open", ["table_id"], True, where='"status" IN (\'open\')'),
                ActualIndex("visits_lower", ["lower(`status`)"], False, has_expression=True),
            ],
            checks=["status IN ('open', 'closed')"],
        )
        database = DatabaseConfig("postgresql", "postgres:17", True, "db/*.up.sql", (3, 15))
        text = render_schema_actual(ActualSchema("postgresql", {"tables": ActualTable("tables"), "visits": table}), database)
        self.assertTrue(text.startswith(
            "<!-- doc-structured:generated 生成元: db/*.up.sql コマンド: bin/doc-structured generate --all "
        ))
        self.assertIn("# 実際のスキーマ\n\nマイグレーション `db/*.up.sql` を PostgreSQL (イメージ `postgres:17`) に適用したスキーマ。\n", text)
        self.assertIn(
            '  "tables"\n'
            '  "visits" {\n'
            "    INTEGER id PK\n"
            "    text table_id FK, UK\n"
            "    text store_id FK\n"
            "    text status\n"
            "  }\n"
            '  "tables" ||--o| "visits" : "table_id"\n'
            '  "tables" |o--o{ "visits" : "store_id, table_id"\n',
            text,
        )
        self.assertIn(
            "## テーブル `visits`\n\n主キー: `id`\n\n"
            "| カラム | 型 | NULL | デフォルト値 | 参照先 |\n|---|---|---|---|---|\n"
            "| `id` | `INTEGER` | | | |\n"
            "| `table_id` | `text` | | | `tables`.`id` |\n"
            "| `store_id` | `text` | 許可 | | |\n"
            "| `status` | `text` | | `'open'` | |\n\n"
            "複数のカラムからなる外部キー:\n\n- `store_id`・`table_id` → `tables`.`store_id`・`tables`.`id`\n\n"
            "インデックス:\n\n"
            "- `table_id` (一意。条件: `\"status\" IN ('open')`)\n"
            "- `` lower(`status`) ``\n\n"
            "CHECK 制約:\n\n- `status IN ('open', 'closed')`\n",
            text,
        )
        # 設計へのリンク・ID・アンカーを持たない
        self.assertNotIn("<a name=", text)
        self.assertNotIn("][", text)


class CommandTest(ProjectTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.copy_sample()

    def run_tool(self, *args: str):
        return subprocess.run(
            [PYTHON, "-m", "doc_structured", *args], cwd=self.project, env=clean_env(), capture_output=True, text=True
        )

    def change_migration(self) -> None:
        path = self.project / LOANS_MIGRATION
        path.write_text(path.read_text(encoding="utf-8").replace("  status text DEFAULT 'on_loan' NOT NULL,", "  status text DEFAULT 'on_loan' NOT NULL,\n  returned_at integer,"), encoding="utf-8")

    def test_sample_contents(self):
        text = (self.project / SCHEMA_ACTUAL).read_text(encoding="utf-8")
        self.assertIn("マイグレーション `migrations/*.sql` を SQLite に適用したスキーマ。", text)
        self.assertIn("- `reservation_id` (一意。条件: `reservation_id IS NOT NULL`)", text)
        self.assertIn("CHECK 制約:\n\n- `status IN ('on_loan', 'returned')`", text)

    def test_generate_does_not_touch_and_check_a_ignores_it(self):
        self.change_migration()
        result = self.run_tool("generate")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "生成したファイルは、すべて最新だった\n")
        self.assertNotIn("returned_at", (self.project / SCHEMA_ACTUAL).read_text(encoding="utf-8"))
        self.assertEqual(self.run_tool("check", "--only", "a").returncode, 0)

    def test_check_j_reports_stale_file_and_generate_all_updates_it(self):
        self.change_migration()
        result = self.run_tool("check", "--only", "j")
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            f"{SCHEMA_ACTUAL}: 検査 j: 生成し直した内容と違う。このファイルを直接編集せず、bin/doc-structured generate --all を実行する",
            result.stdout,
        )
        self.assertIn("+| `returned_at` | `INTEGER` | 許可 | | |", result.stdout)
        generated = self.run_tool("generate", "--all")
        self.assertEqual(generated.returncode, 0, generated.stderr)
        self.assertEqual(generated.stdout, f"書いた: {SCHEMA_ACTUAL}\n")
        after = self.run_tool("check", "--only", "j")
        self.assertNotIn(SCHEMA_ACTUAL, after.stdout)
        # 設計との差分 (planned のカラムが実装された) は残る
        self.assertIn("returned_at は実装されたので、planned を外す", after.stdout)

    def test_check_j_reports_missing_file(self):
        (self.project / SCHEMA_ACTUAL).unlink()
        result = self.run_tool("check", "--only", "j")
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"{SCHEMA_ACTUAL}: 検査 j: 生成するはずのファイルが無い。bin/doc-structured generate --all を実行する", result.stdout)

    def test_generate_all_reports_migration_error(self):
        (self.project / "migrations/0003_broken.sql").write_text("ALTER TABLE missing ADD x text;\n", encoding="utf-8")
        result = self.run_tool("generate", "--all")
        self.assertEqual(result.returncode, 1)
        self.assertIn("migrations/0003_broken.sql: マイグレーションを SQLite に適用できない: no such table: missing", result.stderr)

    def test_without_schema_actual(self):
        config = self.project / CONFIG_RELATIVE_PATH
        config.write_text(config.read_text(encoding="utf-8").replace("  schema_actual: true\n", ""), encoding="utf-8")
        # 残っていれば検査 a が報告し、generate (--all でも同じ) が消す
        result = self.run_tool("check", "--only", "a")
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            f"{SCHEMA_ACTUAL}: 検査 a: 設定に database.schema_actual: true が無いので、生成し直すと消えるファイルが残っている。"
            "bin/doc-structured generate を実行して消す (残すなら、設定に database.schema_actual: true を書く)",
            result.stdout,
        )
        generated = self.run_tool("generate", "--all")
        self.assertEqual(generated.returncode, 0, generated.stderr)
        self.assertIn(f"消した: {SCHEMA_ACTUAL}", generated.stdout)
        self.assertFalse((self.project / SCHEMA_ACTUAL).exists())
        self.assertNotIn("schema-actual.md", (self.project / "docs/.gitattributes").read_text(encoding="utf-8"))
        self.assertEqual(self.run_tool("check", "--all").returncode, 0)


class ProtectionTest(ProjectTestCase):
    def test_gitattributes_lists_schema_actual(self):
        self.copy_sample()
        self.assertIn(
            "/system/schema-actual.md merge=binary\n", (self.project / "docs/.gitattributes").read_text(encoding="utf-8")
        )

    def test_hook_denies_editing_schema_actual(self):
        self.copy_sample()
        payload = {
            "hook_event_name": "PreToolUse", "tool_name": "Edit",
            "tool_input": {"file_path": str(self.project / SCHEMA_ACTUAL)}, "cwd": str(self.project),
        }
        result = subprocess.run(
            [PYTHON, str(HOOK_SCRIPT)], input=json.dumps(payload), cwd=self.tmp, env=clean_env(), capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertIn("生成元 migrations/*.sql", output["permissionDecisionReason"])
        self.assertIn("bin/doc-structured generate --all", output["permissionDecisionReason"])


if __name__ == "__main__":
    unittest.main()
