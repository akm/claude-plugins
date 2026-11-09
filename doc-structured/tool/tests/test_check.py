"""サブコマンド check と検査 a (モジュール check) のテスト。

検査ごとに、失敗する例と成功する例を確かめる。題材はサンプルのプロジェクトのコピー。
"""

import subprocess
import unittest

from doc_structured import generated_header as gh
from tooltest import PYTHON, ProjectTestCase, clean_env

MODELS = "docs/domains/02-loans/models.md"


class CheckTest(ProjectTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.copy_sample()

    def run_check(self, *args: str):
        return subprocess.run(
            [PYTHON, "-m", "doc_structured", "check", *args],
            cwd=self.project,
            env=clean_env(),
            capture_output=True,
            text=True,
        )

    def test_sample_project_passes_all_light_checks(self):
        for args in ((), ("--light",), ("--all",), ("--only", "a"), ("--only", "b"), ("--only", "h"), ("--only", "i")):
            with self.subTest(args=args):
                result = self.run_check(*args)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue(result.stdout.endswith(": 問題は無かった\n"), result.stdout)
        self.assertEqual(self.run_check().stdout, "検査 a・b・h・i: 問題は無かった\n")

    def test_check_a_reports_hand_edited_file_with_source_and_command(self):
        path = self.project / MODELS
        path.write_text(path.read_text(encoding="utf-8").replace("貸し出した図書。", "貸し出した本。"), encoding="utf-8")
        result = self.run_check()
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            f"{MODELS}: 検査 a: 生成し直した内容と違う。このファイルを直接編集せず、"
            "生成元 docs/domains/02-loans/ の YAML を直して bin/doc-structured generate を実行する",
            result.stdout,
        )
        self.assertIn("-貸し出した本。", result.stdout)
        self.assertIn("+貸し出した図書。", result.stdout)
        self.assertIn("検査 a・b・h・i: 問題が 1 件あった", result.stdout)

    def test_check_a_reports_missing_generated_file(self):
        (self.project / "docs/glossary.md").unlink()
        result = self.run_check("--only", "a")
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "docs/glossary.md: 検査 a: 生成するはずのファイルが無い。bin/doc-structured generate を実行する", result.stdout
        )

    def test_check_a_reports_generated_file_whose_source_is_gone(self):
        # 消したドメインの生成物が、別の場所に残った
        self.write(
            "docs/old/models.md",
            gh.markdown_line("docs/domains/09-gone/") + "\n# 消したドメインのモデル\n",
        )
        result = self.run_check("--only", "a")
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "docs/old/models.md: 検査 a: 生成元 docs/domains/09-gone/ が無い。このファイルを消すか、生成元を戻す",
            result.stdout,
        )

    def test_check_a_reports_file_that_generation_would_remove(self):
        yaml = self.project / "docs/domains/01-catalog/domain.yaml"
        text = yaml.read_text(encoding="utf-8")
        yaml.write_text(text.split("unclassified_app_terms:")[0], encoding="utf-8")
        result = self.run_check("--only", "a")
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "docs/domains/01-catalog/unclassified_app_terms.md: 検査 a: 生成し直すと消えるファイルが残っている。"
            "bin/doc-structured generate を実行して消す",
            result.stdout,
        )

    def test_check_a_reports_handwritten_file_at_output(self):
        self.write(MODELS, "# 貸出のモデル (手で書いた)\n")
        result = self.run_check("--only", "a")
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            f"{MODELS}: 検査 a: 手で書いたファイルが、生成するファイルの場所にある。"
            "ファイルの名前を変える。または、内容を手書きの文書に移してから、このファイルを消す",
            result.stdout,
        )
        # 生成し直した内容との差分は出さない (generate を促さない)
        self.assertNotIn("生成し直した内容と違う", result.stdout)

    def test_check_a_asks_to_regenerate_empty_file_at_output(self):
        self.write(MODELS, "")
        result = self.run_check("--only", "a")
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"{MODELS}: 検査 a: 生成したファイルの中身が無い。bin/doc-structured generate を実行する", result.stdout)
        self.assertNotIn("手で書いたファイル", result.stdout)
        self.assertNotIn("YAML を直して", result.stdout)

    def test_check_a_reports_bom_and_invalid_bytes_in_generated_file(self):
        path = self.project / MODELS
        original = path.read_bytes()
        path.write_bytes(b"\xef\xbb\xbf" + original)
        result = self.run_check("--only", "a")
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            f"{MODELS}: 検査 a: 生成し直した内容と違う (BOM か、UTF-8 として読めないバイトがある)。bin/doc-structured generate を実行する",
            result.stdout,
        )
        path.write_bytes(original + b"\xff\n")
        result = self.run_check("--only", "a")
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"{MODELS}: 検査 a: 生成し直した内容と違う。", result.stdout)
        # 案内どおりに generate を実行すると直る
        generate = subprocess.run(
            [PYTHON, "-m", "doc_structured", "generate"], cwd=self.project, env=clean_env(), capture_output=True, text=True
        )
        self.assertEqual(generate.returncode, 0, generate.stderr)
        self.assertEqual(self.run_check("--only", "a").returncode, 0)

    def test_check_h_failure_skips_a_b_and_i(self):
        self.write("docs/domains/03-members/domain.yaml", "domain:\n  description: [x\n")
        result = self.run_check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("docs/domains/03-members/domain.yaml:3:1: 検査 h: YAML として読めない", result.stdout)
        self.assertIn("YAML に誤りがあるので、検査 a・b・i を実行しなかった (誤りは検査 h で確認する)", result.stdout)

    def test_check_b_reports_with_path_line_and_column(self):
        path = self.project / "docs/domains/02-loans/concept.md"
        path.write_text(path.read_text(encoding="utf-8").replace("[開館日]とする", "[休館日]とする"), encoding="utf-8")
        result = self.run_check("--only", "b")
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "docs/domains/02-loans/concept.md:11:20: 検査 b: ラベル 休館日 の定義の行が無い。参照先の候補は無い", result.stdout
        )
        self.assertIn("docs/domains/02-loans/concept.md:22:1: 検査 b: ラベル 開館日 の定義の行が、本文で使われていない", result.stdout)

    def test_only_a_with_yaml_error_fails(self):
        self.write("docs/domains/03-members/domain.yaml", "domain:\n  description: [x\n")
        result = self.run_check("--only", "a")
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("検査 h:", result.stdout)
        self.assertIn("検査 a を実行しなかった", result.stdout)
        self.assertIn("検査 a: 実行できなかった検査がある", result.stdout)

    def test_check_i_failure(self):
        self.write(
            "docs/domains/02-loans/reservations/hold.yaml",
            "models:\n  hold:\n    name_ja: 取置\n    definition: 取り置き。\n    attributes:\n"
            "      loan:\n        name_ja: 元の貸出\n        definition: 元の貸出。\n        refers_to: d-loans-m-loan\n",
        )
        result = self.run_check("--only", "i")
        self.assertEqual(result.returncode, 1)
        self.assertIn("docs/domains/02-loans/reservations/hold.yaml:9:20: 検査 i:", result.stdout)

    def test_heavy_has_no_checks_in_this_version(self):
        result = self.run_check("--heavy")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "重い群の検査は、このバージョンのツールには無い\n")

    def test_unknown_check_is_usage_error(self):
        result = self.run_check("--only", "j")
        self.assertEqual(result.returncode, 2)
        self.assertIn("このバージョンのツールに検査 j は無い (ある検査: a・b・h・i)", result.stderr)

    def test_options_are_mutually_exclusive(self):
        result = self.run_check("--light", "--all")
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
