"""サブコマンド impl-diff のテスト。サンプルのプロジェクトのコピーで、差分の表示と終了コードを確認する。

決めた経緯は Issue #207 のコメントの 7・8・11。
"""

import subprocess
import unittest

from tooltest import PYTHON, ProjectTestCase, clean_env

LOANS_MIGRATION = "migrations/0002_create_loans.sql"


class ImplDiffCommandTest(ProjectTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.copy_sample()

    def run_impl_diff(self):
        return subprocess.run(
            [PYTHON, "-m", "doc_structured", "impl-diff"], cwd=self.project, env=clean_env(), capture_output=True, text=True
        )

    def replace(self, relative: str, old: str, new: str) -> None:
        path = self.project / relative
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1), encoding="utf-8")

    def test_no_difference(self):
        result = self.run_impl_diff()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "設計と実装に差分は無かった\n")

    def test_shows_unified_diff_and_instructions(self):
        self.replace(LOANS_MIGRATION, "reservation_id text REFERENCES", "reservation_id integer REFERENCES")
        result = self.run_impl_diff()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(
            result.stdout,
            "--- 設計 (docs/domains/ の schema*.yaml)\n"
            "+++ 実装 (migrations/*.sql を sqlite に適用したもの)\n"
            "@@ -21,7 +21,7 @@\n"
            " table loans column book_id: text not null\n"
            " table loans column id: text not null\n"
            " table loans column member_id: text not null\n"
            "-table loans column reservation_id: text null\n"
            "+table loans column reservation_id: integer null\n"
            " table loans column status: text not null default 'on_loan'\n"
            " table loans primary key id\n"
            " table loans foreign key book_id: books.id\n"
            "docs/domains/02-loans/schema.yaml:18:7: 検査 j: カラム d-loans-t-loans-c-reservation_id の型が違う "
            "(設計 text、実装 integer)。YAML か実装を直す\n"
            "検査 j: 問題が 1 件あった\n",
        )

    def test_yaml_errors(self):
        self.replace("docs/domains/02-loans/schema.yaml", "type: integer", "type: ''")
        result = self.run_impl_diff()
        self.assertEqual(result.returncode, 1)
        self.assertIn("YAML に 1 件の誤りがあるので、設計と実装を比べなかった", result.stderr)

    def test_without_database_config(self):
        self.write_config()
        result = self.run_impl_diff()
        self.assertEqual(result.returncode, 1)
        self.assertIn("設定に paths.migrations と database を書く", result.stdout)


if __name__ == "__main__":
    unittest.main()
