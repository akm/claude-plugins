"""生成 (モジュール generate とサブコマンド generate) のテスト。

サンプルのプロジェクトの生成物はコミットしてあり、生成し直した内容がそれと同じであることを確かめる。
CI (Linux) でもこのテストが成功することで、手元 (macOS) で生成してコミットしたファイルと、環境による差が無いことを確かめる。
"""

import subprocess
import unittest

from doc_structured.domains import load_project
from doc_structured.generate import generated_files, render_project
from tooltest import PYTHON, SAMPLE_PROJECT, ProjectTestCase, clean_env

MINIMAL = """\
domain:
  description: 図書の貸出と返却を扱う。
models:
  loan:
    name_ja: 貸出
    definition: 利用者が図書を借りてから返すまでの 1 回の記録。
"""


class GenerateTest(ProjectTestCase):
    def run_tool(self, *args: str):
        return subprocess.run(
            [PYTHON, "-m", "doc_structured", *args], cwd=self.project, env=clean_env(), capture_output=True, text=True
        )

    def snapshot(self) -> dict[str, str]:
        return {
            p.relative_to(self.project).as_posix(): p.read_text(encoding="utf-8")
            for p in sorted(self.project.rglob("*"))
            if p.is_file()
        }

    def test_committed_sample_outputs_are_up_to_date(self):
        project, problems = load_project(SAMPLE_PROJECT)
        self.assertEqual(problems, [])
        outputs = render_project(project)
        self.assertEqual(sorted(outputs), sorted(generated_files(SAMPLE_PROJECT)))
        for relative, content in outputs.items():
            with self.subTest(file=relative):
                self.assertEqual((SAMPLE_PROJECT / relative).read_text(encoding="utf-8"), content)

    def test_generate_twice_makes_no_difference(self):
        self.copy_sample()
        for path in generated_files(self.project):
            (self.project / path).unlink()
        first = self.run_tool("generate")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("書いた: docs/glossary.md", first.stdout)
        after_first = self.snapshot()
        second = self.run_tool("generate")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(second.stdout, "生成したファイルは、すべて最新だった\n")
        self.assertEqual(self.snapshot(), after_first)

    def test_files_without_definitions_are_not_generated_and_old_ones_are_removed(self):
        self.write(".claude/akm-claude-plugins/doc-structured/config.yaml", "version: 0.2.0\n")
        self.write("docs/domains/01-loans/domain.yaml", MINIMAL + "unclassified_app_terms:\n  business_day:\n    name_ja: 開館日\n    definition: 開いている日。\n")
        self.write("docs/domains/01-loans/concept.md", "# 手書きの文書\n")
        self.assertEqual(self.run_tool("generate").returncode, 0)
        self.assertTrue((self.project / "docs/domains/01-loans/unclassified_app_terms.md").is_file())

        self.write("docs/domains/01-loans/domain.yaml", MINIMAL)
        result = self.run_tool("generate")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("消した: docs/domains/01-loans/unclassified_app_terms.md", result.stdout)
        self.assertFalse((self.project / "docs/domains/01-loans/unclassified_app_terms.md").exists())
        # 手書きのファイル (先頭の記述が無い) は消さない
        self.assertTrue((self.project / "docs/domains/01-loans/concept.md").is_file())
        readme = (self.project / "docs/domains/01-loans/README.md").read_text(encoding="utf-8")
        self.assertNotIn("unclassified_app_terms.md", readme)

        # 定義が 1 つも無いドメインは、README.md だけ
        self.write("docs/domains/01-loans/domain.yaml", "domain:\n  description: 空のドメイン。\n")
        self.assertEqual(self.run_tool("generate").returncode, 0)
        names = sorted(generated_files(self.project))
        self.assertEqual(names, ["docs/domains/01-loans/README.md"])

    def test_yaml_errors_stop_generation(self):
        self.write(".claude/akm-claude-plugins/doc-structured/config.yaml", "version: 0.2.0\n")
        self.write("docs/domains/01-loans/domain.yaml", "domain:\n  description: [x\n")
        result = self.run_tool("generate")
        self.assertEqual(result.returncode, 1)
        self.assertIn("docs/domains/01-loans/domain.yaml:3:1: 検査 h: YAML として読めない", result.stderr)
        self.assertIn("何も生成しなかった", result.stderr)
        self.assertEqual(generated_files(self.project), {})

    def test_terms_are_sorted_by_code_point_of_name_ja(self):
        project, _ = load_project(SAMPLE_PROJECT)
        terms = render_project(project)["docs/domains/02-loans/terms.md"]
        rows = [line.split("]")[0].lstrip("| [") for line in terms.splitlines() if line.startswith("| [")]
        self.assertEqual(rows, sorted(rows))
        self.assertLess(rows.index("貸出中"), rows.index("貸出図書"))

    def test_link_text_and_table_cells_are_escaped(self):
        self.write(
            "docs/domains/01-loans/domain.yaml",
            MINIMAL.replace("name_ja: 貸出", "name_ja: 貸出|[一時]"),
        )
        project, problems = load_project(self.project)
        self.assertEqual(problems, [])
        terms = render_project(project)["docs/domains/01-loans/terms.md"]
        self.assertIn(r"| [貸出\|\[一時\]][d-loans-m-loan] |", terms)


if __name__ == "__main__":
    unittest.main()
