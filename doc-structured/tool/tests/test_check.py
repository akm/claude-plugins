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
        for args in ((), ("--light",), ("--all",), ("--only", "a"), ("--only", "h"), ("--only", "i")):
            with self.subTest(args=args):
                result = self.run_check(*args)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue(result.stdout.endswith(": 問題は無かった\n"), result.stdout)
        self.assertEqual(self.run_check().stdout, "検査 a・h・i: 問題は無かった\n")

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
        self.assertIn("検査 a・h・i: 問題が 1 件あった", result.stdout)

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

    def test_check_h_failure_skips_a_and_i(self):
        self.write("docs/domains/03-members/domain.yaml", "domain:\n  description: [x\n")
        result = self.run_check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("docs/domains/03-members/domain.yaml:3:1: 検査 h: YAML として読めない", result.stdout)
        self.assertIn("YAML に誤りがあるので、検査 a・i を実行しなかった (誤りは検査 h で確認する)", result.stdout)

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
        self.assertIn("このバージョンのツールに検査 j は無い (ある検査: a・h・i)", result.stderr)

    def test_options_are_mutually_exclusive(self):
        result = self.run_check("--light", "--all")
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
