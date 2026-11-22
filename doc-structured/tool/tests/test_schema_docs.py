"""スキーマの文書 (ドメインごとの schema.md と docs/system/schema.md) の生成と、テーブルとカラムを指すリンク
(検査 b・links-fix・refs) と、生成したファイルの保護 (hook・docs/.gitattributes) のテスト。
題材は、サンプルのプロジェクト (ディレクトリ fixtures/library-loans) のコピー。"""

import json
import re
import subprocess
import unittest

from doc_structured.domains import load_project
from doc_structured.generate import render_project
from tooltest import PLUGIN_DIR, PYTHON, ProjectTestCase, clean_env

LOANS_SCHEMA_MD = "docs/domains/02-loans/schema.md"
CATALOG_SCHEMA_MD = "docs/domains/01-catalog/schema.md"
MEMBERS_SCHEMA_MD = "docs/domains/03-members/schema.md"
SYSTEM_SCHEMA_MD = "docs/system/schema.md"
DESIGN = "docs/domains/02-loans/design.md"
HOOK_SCRIPT = PLUGIN_DIR / "hook-scripts" / "guard-generated.py"


def mermaid_block(text: str) -> list[str]:
    """最初の mermaid の図の行 (```mermaid と ``` を除く)。"""
    return text.split("```mermaid\n", 1)[1].split("\n```", 1)[0].splitlines()


class SchemaDocsTestCase(ProjectTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.copy_sample()

    def outputs(self) -> dict[str, str]:
        project, problems = load_project(self.project)
        self.assertEqual([p.format() for p in problems], [])
        return render_project(project)

    def run_tool(self, *args: str):
        return subprocess.run(
            [PYTHON, "-m", "doc_structured", *args], cwd=self.project, env=clean_env(), capture_output=True, text=True
        )


class DomainSchemaTest(SchemaDocsTestCase):
    def test_er_diagram_draws_own_tables_and_referenced_columns_of_other_domains(self):
        diagram = mermaid_block(self.outputs()[LOANS_SCHEMA_MD])
        self.assertEqual(diagram[0], "erDiagram")
        # このドメインのテーブルはすべてのカラムを、ほかのドメインのテーブルは参照されるカラムだけを描く
        self.assertEqual(
            [line.strip() for line in diagram if line.endswith("{")],
            ['"reservations" {', '"loans" {', '"books" {', '"members" {'],
        )
        text = "\n".join(diagram)
        self.assertIn('  "books" {\n    text id PK\n  }', text)
        self.assertNotIn("title", text)
        self.assertIn('    integer returned_at "未実装"', text)
        self.assertIn("    text reservation_id FK, UK", text)

    def test_er_relationships_cardinality(self):
        diagram = mermaid_block(self.outputs()[LOANS_SCHEMA_MD])
        relationships = [line.strip() for line in diagram if "--" in line]
        self.assertEqual(relationships, [
            '"books" ||--o{ "reservations" : "book_id"',
            # NULL を許可する外部キーは、参照される側が 0 か 1 つ。自己参照も描く
            '"reservations" |o--o{ "reservations" : "previous_id"',
            '"books" ||--o{ "loans" : "book_id"',
            '"members" ||--o{ "loans" : "member_id"',
            # そのカラムだけの一意のインデックスを持つ外部キーは、参照する側も 0 か 1 つ
            '"reservations" |o--o| "loans" : "reservation_id"',
        ])

    def test_table_sections_and_columns(self):
        text = self.outputs()[LOANS_SCHEMA_MD]
        self.assertTrue(text.split("\n")[1] == '<a name="d-loans-schema"></a>')
        self.assertIn("# ドメイン `loans` のスキーマ\n", text)
        self.assertIn(
            '<a name="d-loans-t-loans"></a>\n\n## テーブル `loans`\n\n対応するモデル: [モデル「貸出」][d-loans-m-loan]\n\n主キー: `id`\n',
            text,
        )
        self.assertIn("| カラム | 型 | NULL | デフォルト値 | 参照先 | 属性・定義 |\n|---|---|---|---|---|---|\n", text)
        self.assertIn(
            '| <a name="d-loans-t-loans-c-book_id"></a>`book_id` | `text` | | | '
            "[ドメイン `catalog` のテーブル `books` のカラム `id`][d-catalog-t-books-c-id] | "
            "[モデル「貸出」の属性「貸出図書」][d-loans-m-loan-a-book] |",
            text,
        )
        self.assertIn(
            '| <a name="d-loans-t-loans-c-returned_at"></a>`returned_at` (未実装) | `integer` | 許可 | | | '
            "図書が返った時刻 (UNIX 時刻のミリ秒)。 |",
            text,
        )
        self.assertIn("| `'on_loan'` |", text)
        self.assertIn("インデックス:\n\n- `member_id`\n- `reservation_id` (一意)\n", text)
        # ほかのドメインのテーブルへのリンクは、列「参照先」だけで、別の節は無い
        self.assertNotIn("## テーブル `books`", text)

    def test_intermediate_table_and_planned_table(self):
        outputs = self.outputs()
        catalog = outputs[CATALOG_SCHEMA_MD]
        self.assertIn(
            "## テーブル `book_categories`\n\n対応する属性: [モデル「図書」の属性「分類」][d-catalog-m-book-a-categories]\n\n"
            "主キー: `book_id`・`category_id`\n",
            catalog,
        )
        self.assertIn("    text book_id PK, FK\n", catalog)
        members = outputs[MEMBERS_SCHEMA_MD]
        self.assertIn("## テーブル `member_cards`\n\n利用者に発行する利用者カード 1 枚の行。\n\n未実装\n\n主キー: `id`\n", members)
        # 未実装のテーブルのカラムは、図ではすべて未実装の注記を付ける
        self.assertIn('    text member_id FK "未実装"\n', members)

    def test_table_and_column_names_are_quoted_in_er_diagram(self):
        # mermaid は、引用符で囲まないエンティティ名と線の文字の end・style・class を読めない
        path = self.project / "docs/domains/03-members/schema.yaml"
        path.write_text(
            path.read_text(encoding="utf-8").replace("  member_cards:\n", "  end:\n").replace(
                "      member_id:\n        type: text\n        definition: カードを持つ利用者。\n",
                "      style:\n        type: text\n        definition: カードを持つ利用者。\n",
            ).replace("      - columns: [member_id]\n", "      - columns: [style]\n"),
            encoding="utf-8",
        )
        diagram = mermaid_block(self.outputs()[MEMBERS_SCHEMA_MD])
        self.assertIn('  "end" {', diagram)
        self.assertIn('    text style FK "未実装"', diagram)
        self.assertIn('  "members" ||--o{ "end" : "style"', diagram)

    def test_type_with_characters_mermaid_cannot_read(self):
        path = self.project / "docs/domains/03-members/schema.yaml"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "      name:\n        type: text\n", "      name:\n        type: numeric(10, 2)\n"
            ),
            encoding="utf-8",
        )
        text = self.outputs()[MEMBERS_SCHEMA_MD]
        self.assertIn("    numeric(10__2) name\n", text)
        # 表には、書いた型のまま出す
        self.assertIn("| `numeric(10, 2)` |", text)

    def test_readme_lists_schema_after_functions(self):
        readme = self.outputs()["docs/domains/02-loans/README.md"]
        rows = [line.split("]")[0].lstrip("| [") for line in readme.splitlines() if line.startswith("| [`")]
        self.assertEqual(rows, [
            "`concept.md`", "`design.md`", "`models.md`", "`unclassified_app_terms.md`", "`functions.md`", "`schema.md`",
            "`dependencies.md`", "`terms.md`",
        ])
        self.assertIn("| テーブルとカラムの設計と ER 図 |", readme)

    def test_no_schema_md_without_tables(self):
        for relative in ("docs/domains/01-catalog/schema.yaml", "docs/domains/02-loans/schema.yaml",
                         "docs/domains/02-loans/reservations/schema.yaml", "docs/domains/03-members/schema.yaml"):
            (self.project / relative).unlink()
        outputs = self.outputs()
        self.assertNotIn(LOANS_SCHEMA_MD, outputs)
        self.assertNotIn(SYSTEM_SCHEMA_MD, outputs)
        self.assertNotIn("schema.md", outputs["docs/domains/02-loans/README.md"])

    def test_tables_are_not_in_term_indexes(self):
        outputs = self.outputs()
        self.assertNotIn("t-loans", outputs["docs/domains/02-loans/terms.md"])
        self.assertNotIn("-t-", outputs["docs/glossary.md"])


class MultilineTextInCellTest(SchemaDocsTestCase):
    """改行を書ける文 (テーブルとカラムの definition・ドメインの description) を、表のセルでは 1 行にする。"""

    def test_multiline_definitions_stay_in_one_table_row(self):
        path = self.project / "docs/domains/03-members/schema.yaml"
        text = path.read_text(encoding="utf-8")
        text = text.replace(
            "    definition: 利用者に発行する利用者カード 1 枚の行。\n",
            "    definition: |\n      利用者に発行する\n      利用者カード 1 枚の行。\n",
        ).replace(
            "        definition: カードを持つ利用者。\n", "        definition: |\n          カードを持つ\n\n          利用者。\n"
        )
        path.write_text(text, encoding="utf-8")
        outputs = self.outputs()
        self.assertIn("`member_id` | `text` | | | [テーブル `members` のカラム `id`][d-members-t-members-c-id] | カードを持つ 利用者。 |",
                      outputs[MEMBERS_SCHEMA_MD])
        self.assertIn("| [`member_cards`][d-members-t-member_cards] (未実装) | [`members`][d-members] | 利用者に発行する 利用者カード 1 枚の行。 |",
                      outputs[SYSTEM_SCHEMA_MD])

    def test_multiline_domain_description_stays_in_one_table_row(self):
        path = self.project / "docs/domains/03-members/domain.yaml"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "  description: 図書館に登録した利用者を扱う。\n", "  description: |\n    図書館に登録した\n    利用者を扱う。\n"
            ),
            encoding="utf-8",
        )
        readme = self.outputs()["docs/domains/README.md"]
        self.assertIn("| [`03-members`][d-members] | 図書館に登録した 利用者を扱う。 |", readme)


class SystemSchemaTest(SchemaDocsTestCase):
    def test_table_of_all_tables(self):
        text = self.outputs()[SYSTEM_SCHEMA_MD]
        self.assertTrue(text.startswith("<!-- doc-structured:generated 生成元: docs/domains/ "))
        self.assertNotIn("<a name=", text)
        self.assertIn("# スキーマ\n\n| テーブル | ドメイン | 対応するモデル・属性・定義 |\n", text)
        rows = [line for line in text.splitlines() if line.startswith("| [")]
        self.assertEqual([re.match(r"\| \[`(\w+)`\]", row).group(1) for row in rows], [
            "books", "categories", "book_categories", "reservations", "loans", "members", "member_cards",
        ])
        self.assertIn(
            "| [`loans`][d-loans-t-loans] | [`loans`][d-loans] | 対応するモデル: [モデル「貸出」][d-loans-m-loan] |", rows
        )
        self.assertIn(
            "| [`member_cards`][d-members-t-member_cards] (未実装) | [`members`][d-members] | 利用者に発行する利用者カード 1 枚の行。 |",
            rows,
        )

    def test_overview_diagram_draws_keys_states_and_in_overview(self):
        text = "\n".join(mermaid_block(self.outputs()[SYSTEM_SCHEMA_MD]))
        # キーのカラム・状態の遷移を持つ属性に対応するカラム (loans.status)・in_overview を書いたカラム (books.call_number)
        self.assertIn('  "books" {\n    text id PK\n    text call_number\n  }', text)
        self.assertIn(
            '  "loans" {\n    text id PK\n    text book_id FK\n    text member_id FK\n    text reservation_id FK, UK\n'
            "    text status\n  }",
            text,
        )
        # 状態の遷移を持たない属性に対応するカラム (books.title)・対応する属性が無いカラム (loans.returned_at) は描かない
        self.assertNotIn("title", text)
        self.assertNotIn("returned_at", text)
        self.assertIn('  "members" ||--o{ "member_cards" : "member_id"', text)


class ModelsReferencingTablesTest(SchemaDocsTestCase):
    """models.md の、モデルの定義の後の「このモデルを参照するテーブル」。"""

    def test_tables_with_model_and_intermediate_tables(self):
        catalog = self.outputs()["docs/domains/01-catalog/models.md"]
        self.assertIn(
            "このモデルを参照するモデル: [ドメイン `loans` のモデル「貸出」][d-loans-m-loan]・"
            "[ドメイン `loans` のモデル「予約」][d-loans-m-reservation]\n\n"
            "このモデルを参照するテーブル: [テーブル `books`][d-catalog-t-books]・"
            "[テーブル `book_categories`][d-catalog-t-book_categories] (属性「分類」を参照)\n",
            catalog,
        )
        self.assertIn('[d-catalog-t-books]: schema.md#d-catalog-t-books "ドメイン `catalog` のテーブル `books`"', catalog)

    def test_line_is_written_without_referencing_models(self):
        loans = self.outputs()["docs/domains/02-loans/models.md"]
        self.assertIn("## モデル「貸出」 `loan`\n\n利用者が図書を借りてから返すまでの 1 回の記録。\n\n"
                      "このモデルを参照するテーブル: [テーブル `loans`][d-loans-t-loans]\n", loans)

    def test_no_line_without_tables(self):
        for path in self.project.glob("docs/domains/**/schema.yaml"):
            path.unlink()
        self.assertNotIn("このモデルを参照するテーブル", self.outputs()["docs/domains/03-members/models.md"])


class LinksToTablesTest(SchemaDocsTestCase):
    """手書きの Markdown からテーブルとカラムへのリンク。サンプルの design.md は、カラム returned_at を指している。"""

    def test_check_b_accepts_link_to_column_anchor_in_table_cell(self):
        result = self.run_tool("check", "--only", "b")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_check_b_reports_stale_title_and_links_fix_rewrites_it(self):
        path = self.project / DESIGN
        text = path.read_text(encoding="utf-8")
        stale = text.replace(
            '"ドメイン `loans` のテーブル `loans` のカラム `returned_at`"', '"ドメイン `loans` のテーブル `loans` の返却時刻"'
        )
        path.write_text(stale, encoding="utf-8")
        result = self.run_tool("check", "--only", "b")
        self.assertEqual(result.returncode, 1)
        self.assertIn("ドメイン `loans` のテーブル `loans` のカラム `returned_at`", result.stdout)
        self.assertEqual(self.run_tool("links-fix").returncode, 0)
        self.assertEqual(path.read_text(encoding="utf-8"), text)

    def test_links_fix_adds_definition_for_table(self):
        path = self.project / DESIGN
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace("、未実装のままにする。", "、未実装のままにする。[テーブル `reservations`][d-loans-t-reservations]も参照する。"),
            encoding="utf-8",
        )
        result = self.run_tool("links-fix")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            '[d-loans-t-reservations]: schema.md#d-loans-t-reservations "ドメイン `loans` のテーブル `reservations`"',
            path.read_text(encoding="utf-8"),
        )
        self.assertEqual(self.run_tool("check", "--only", "b").returncode, 0)

    def test_link_to_missing_column_fails(self):
        path = self.project / DESIGN
        path.write_text(
            path.read_text(encoding="utf-8").replace("schema.md#d-loans-t-loans-c-returned_at", "schema.md#d-loans-t-loans-c-closed_at"),
            encoding="utf-8",
        )
        result = self.run_tool("check", "--only", "b")
        self.assertEqual(result.returncode, 1)
        self.assertIn("d-loans-t-loans-c-closed_at", result.stdout)

    def test_refs_finds_links_to_table_and_columns(self):
        result = self.run_tool("refs", "d-loans-t-loans")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [
            f"{DESIGN}:17:11: d-loans-t-loans-c-returned_at [テーブル `loans` のカラム `returned_at`] (d-loans-design-h-returned_at)",
            "d-loans-t-loans とその子孫を参照している箇所: 1 件 (1 ファイル)",
        ])


class ProtectionTest(SchemaDocsTestCase):
    def test_gitattributes_lists_schema_files(self):
        gitattributes = self.outputs()["docs/.gitattributes"]
        self.assertIn("/domains/02-loans/schema.md merge=binary\n", gitattributes)
        self.assertIn("/system/schema.md merge=binary\n", gitattributes)

    def test_hook_denies_editing_schema_files(self):
        for relative in (LOANS_SCHEMA_MD, SYSTEM_SCHEMA_MD):
            with self.subTest(path=relative):
                payload = {
                    "hook_event_name": "PreToolUse", "tool_name": "Edit",
                    "tool_input": {"file_path": str(self.project / relative)}, "cwd": str(self.project),
                }
                result = subprocess.run(
                    [PYTHON, str(HOOK_SCRIPT)], input=json.dumps(payload), cwd=self.tmp, env=clean_env(),
                    capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                output = json.loads(result.stdout)["hookSpecificOutput"]
                self.assertEqual(output["permissionDecision"], "deny")


if __name__ == "__main__":
    unittest.main()
