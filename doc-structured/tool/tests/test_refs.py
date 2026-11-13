"""サブコマンド refs (モジュール refs) のテスト。題材はサンプルのプロジェクトのコピー。"""

import subprocess
import unittest

from tooltest import PYTHON, ProjectTestCase, clean_env

CONCEPT = "docs/domains/02-loans/concept.md"
DESIGN = "docs/domains/02-loans/design.md"
CHILD = "docs/domains/02-loans/design/overdue_notice.md"


class RefsTest(ProjectTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.copy_sample()

    def run_refs(self, *args: str):
        return subprocess.run(
            [PYTHON, "-m", "doc_structured", "refs", *args],
            cwd=self.project,
            env=clean_env(),
            capture_output=True,
            text=True,
        )

    def append(self, relative: str, body: str, definition: str) -> None:
        """手書きのファイルの本文の末尾に 1 段落と、定義の行を足す。"""
        path = self.project / relative
        text = path.read_text(encoding="utf-8")
        head, _, definitions = text.rpartition("\n\n[")
        path.write_text(f"{head}\n\n{body}\n\n[{definitions}{definition}\n", encoding="utf-8")

    def test_id_and_descendants(self):
        result = self.run_refs("d-loans-m-loan")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                f"{CONCEPT}:5:1: d-loans-m-loan [モデル「貸出」] (d-loans-concept)",
                f"{DESIGN}:9:1: d-loans-m-loan-a-status [属性「貸出状態」] (d-loans-design-h-status_values)",
                f"{DESIGN}:9:14: d-loans-m-loan-a-status-v-on_loan [値「貸出中」][貸出中] (d-loans-design-h-status_values)",
                f"{DESIGN}:9:28: d-loans-m-loan-a-status-v-returned [値「返却済み」][返却済み] (d-loans-design-h-status_values)",
                f"{CHILD}:9:30: d-loans-m-loan-a-member [モデル「貸出」の属性「借りた利用者」][借りた利用者] (d-loans-design-f-overdue_notice-h-timing)",
                "d-loans-m-loan とその子孫を参照している箇所: 5 件 (3 ファイル)",
            ],
        )

    def test_similar_id_that_is_not_a_descendant_is_not_output(self):
        self.append(
            CONCEPT, "[貸出の明細]は別のモデル。",
            '[貸出の明細]: models.md#d-loans-m-loan_item "ドメイン `loans` のモデル「貸出の明細」"',
        )
        result = self.run_refs("d-loans-m-loan")
        self.assertNotIn("loan_item", result.stdout)
        self.assertIn("d-loans-m-loan とその子孫を参照している箇所: 5 件 (3 ファイル)", result.stdout)

    def test_generated_files_and_records_are_not_output(self):
        # 生成したファイル docs/domains/02-loans/models.md も d-catalog-m-book を参照している
        self.write(
            "docs/plans/2026-11-01-loan-period.md",
            "# 貸出の期間の計画\n\nこれは計画で、現在の仕様は docs/ の各文書を参照。[図書]の貸出の期間を変える。\n\n"
            '[図書]: ../domains/01-catalog/models.md#d-catalog-m-book "ドメイン `catalog` のモデル「図書」"\n',
        )
        result = self.run_refs("d-catalog-m-book")
        self.assertEqual(
            result.stdout.splitlines(),
            [
                f"{CONCEPT}:5:47: d-catalog-m-book [ドメイン `catalog` のモデル「図書」] (d-loans-concept)",
                "d-catalog-m-book とその子孫を参照している箇所: 1 件 (1 ファイル)",
            ],
        )

    def test_full_reference_and_section_owner(self):
        result = self.run_refs("d-loans-design-f-overdue_notice")
        self.assertEqual(
            result.stdout.splitlines()[0],
            f"{CONCEPT}:11:54: d-loans-design-f-overdue_notice [ファイル `design/overdue_notice.md`][d-loans-design-f-overdue_notice] "
            "(d-loans-concept-h-return_deadline)",
        )

    def test_id_without_anchor_is_searched(self):
        self.append(
            CONCEPT, "[古い貸出]は名前を変える前のリンク。",
            '[古い貸出]: models.md#d-loans-m-old_loan "ドメイン `loans` のモデル「古い貸出」"',
        )
        result = self.run_refs("d-loans-m-old_loan")
        self.assertEqual(result.returncode, 0)
        lines = result.stdout.splitlines()
        self.assertRegex(lines[0], rf"^{CONCEPT}:\d+:1: d-loans-m-old_loan \[古い貸出\] \(d-loans-concept-h-reservation_order\)$")
        self.assertEqual(lines[1], "ID d-loans-m-old_loan のアンカーは無い (定義の行の href の ID で探した)")

    def test_definition_only_label(self):
        self.append(CONCEPT, "本文。", '[返却済み]: models.md#d-loans-m-loan-a-status-v-returned "ドメイン `loans` のモデル「貸出」の属性「貸出状態」の値「返却済み」"')
        result = self.run_refs("d-loans-m-loan-a-status-v-returned")
        self.assertRegex(
            result.stdout.splitlines()[0],
            rf"^{CONCEPT}:\d+:1: d-loans-m-loan-a-status-v-returned \[返却済み\] \(定義の行だけで、本文で使われていない\)$",
        )

    def test_no_references_exits_zero(self):
        result = self.run_refs("d-catalog-models")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "d-catalog-models とその子孫を参照している箇所は無い\n")

    def test_malformed_id_exits_one(self):
        result = self.run_refs("d-loans-x")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("doc-structured: ID d-loans-x の形が違う:", result.stderr)

    def test_missing_argument_exits_two(self):
        self.assertEqual(self.run_refs().returncode, 2)

    def test_runs_with_yaml_errors(self):
        self.write("docs/domains/03-members/domain.yaml", "domain:\n  description: [x\n")
        result = self.run_refs("d-loans-m-loan")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("d-loans-m-loan とその子孫を参照している箇所: 5 件 (3 ファイル)", result.stdout)


if __name__ == "__main__":
    unittest.main()
