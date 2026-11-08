"""生成するファイル docs/.gitattributes (生成したファイルの merge の設定) のテスト。

docs/.gitattributes は、ディレクトリ docs/ の下の生成したファイルに、git の組み込みの merge driver binary を設定する。
生成したファイルが競合したマージとリベースの後に、git が ours とする側 (このテストの git merge では現在のブランチ、
git rebase main ではリベース先のブランチ main) の内容が競合のマーク無しで残り、generate で生成し直すと正しい内容になることを、一時的な git のリポジトリで確認する。
"""

import subprocess
import unittest

from doc_structured import generated_header as gh
from doc_structured.domains import load_project
from doc_structured.generate import GITATTRIBUTES_PATH, generated_files, render_project
from tooltest import PYTHON, SAMPLE_PROJECT, ProjectTestCase, clean_env

TERMS_FILE = "docs/domains/01-catalog/unclassified_app_terms.md"


def term_yaml(name: str, name_ja: str, definition: str) -> str:
    return f"unclassified_app_terms:\n  {name}:\n    name_ja: {name_ja}\n    definition: {definition}\n"


class GitattributesTest(ProjectTestCase):
    def run_tool(self, *args: str):
        return subprocess.run(
            [PYTHON, "-m", "doc_structured", *args], cwd=self.project, env=clean_env(), capture_output=True, text=True
        )

    def git(self, *args: str, check: bool = True):
        # 利用者の git の設定 (merge.*.driver など) が結果を変えないよう、全体とシステムの設定を読ませない
        env = clean_env(
            GIT_CONFIG_GLOBAL="/dev/null",
            GIT_CONFIG_NOSYSTEM="1",
            GIT_AUTHOR_NAME="test",
            GIT_AUTHOR_EMAIL="test@example.com",
            GIT_COMMITTER_NAME="test",
            GIT_COMMITTER_EMAIL="test@example.com",
        )
        result = subprocess.run(["git", *args], cwd=self.project, env=env, capture_output=True, text=True)
        if check:
            self.assertEqual(result.returncode, 0, f"git {' '.join(args)}\n{result.stdout}{result.stderr}")
        return result

    def test_lists_every_generated_file_with_binary_merge_driver(self):
        project, problems = load_project(SAMPLE_PROJECT)
        self.assertEqual(problems, [])
        outputs = render_project(project)
        content = outputs[GITATTRIBUTES_PATH]
        lines = content.splitlines()
        self.assertEqual(lines[0], gh.hash_line("docs/domains/"))
        self.assertEqual(gh.read_header(content), gh.Header(source="docs/domains/", command=gh.GENERATE_COMMAND))
        patterns = [line for line in lines if not line.startswith("#")]
        # docs/.gitattributes 自身を含む、すべての生成したファイル。パスは docs/ からの相対で、先頭に「/」を付ける
        expected = [f"/{path.removeprefix('docs/')} merge=binary" for path in sorted(outputs)]
        self.assertEqual(patterns, expected)
        self.assertIn("/.gitattributes merge=binary", patterns)
        self.assertIn("/glossary.md merge=binary", patterns)

    def test_is_treated_as_generated_file(self):
        self.assertIn(GITATTRIBUTES_PATH, generated_files(SAMPLE_PROJECT))

    def test_not_generated_without_any_domain(self):
        self.write(".claude/akm-claude-plugins/doc-structured/config.yaml", "version: 0.3.0\n")
        project, problems = load_project(self.project)
        self.assertEqual(problems, [])
        self.assertEqual(render_project(project), {})

    def test_check_a_reports_hand_edited_gitattributes(self):
        self.copy_sample()
        path = self.project / GITATTRIBUTES_PATH
        path.write_text(path.read_text(encoding="utf-8") + "/domains/01-catalog/concept.md merge=binary\n", encoding="utf-8")
        result = self.run_tool("check", "--only", "a")
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"{GITATTRIBUTES_PATH}: 検査 a: 生成し直した内容と違う。", result.stdout)

    def test_check_a_passes_after_generate(self):
        self.copy_sample()
        (self.project / GITATTRIBUTES_PATH).unlink()
        self.assertEqual(self.run_tool("check", "--only", "a").returncode, 1)
        result = self.run_tool("generate")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"書いた: {GITATTRIBUTES_PATH}", result.stdout)
        self.assertEqual(self.run_tool("check", "--only", "a").returncode, 0)

    def make_conflicting_branches(self) -> None:
        """2 つのブランチ main と other が、同じドメインの別の YAML のファイルに未分類の用語を足す。
        YAML は競合しないが、生成したファイル unclassified_app_terms.md は同じ位置に足されて競合する。最後は main にいる。"""
        self.copy_sample()
        self.git("init", "--quiet", "--initial-branch=main")
        self.git("add", "--all")
        self.git("commit", "--quiet", "-m", "サンプルのプロジェクト")
        self.assertEqual(
            self.git("check-attr", "merge", TERMS_FILE).stdout.strip(), f"{TERMS_FILE}: merge: binary"
        )
        self.git("switch", "--quiet", "--create", "other")
        self.write("docs/domains/01-catalog/other/terms.yaml", term_yaml("isbn", "国際標準図書番号", "図書を識別する番号。"))
        self.assertEqual(self.run_tool("generate").returncode, 0)
        self.git("add", "--all")
        self.git("commit", "--quiet", "-m", "other")
        self.git("switch", "--quiet", "main")
        self.write("docs/domains/01-catalog/main/terms.yaml", term_yaml("spine_label", "背ラベル", "図書の背に貼るラベル。"))
        self.assertEqual(self.run_tool("generate").returncode, 0)
        self.git("add", "--all")
        self.git("commit", "--quiet", "-m", "main")

    def assert_conflicts_keep(self, kept_rev: str) -> None:
        """競合したのは生成したファイルだけで、kept_rev の内容が競合のマーク無しで残っている。"""
        conflicted = self.git("diff", "--name-only", "--diff-filter=U").stdout.split()
        self.assertIn(TERMS_FILE, conflicted)
        for path in conflicted:
            with self.subTest(file=path):
                self.assertIn(path, generated_files(self.project))
                actual = (self.project / path).read_text(encoding="utf-8")
                self.assertNotIn("<<<<<<<", actual)
                self.assertEqual(actual, self.git("show", f"{kept_rev}:{path}").stdout)

    def assert_generate_resolves(self) -> None:
        result = self.run_tool("generate")
        self.assertEqual(result.returncode, 0, result.stderr)
        terms = (self.project / TERMS_FILE).read_text(encoding="utf-8")
        self.assertIn("国際標準図書番号", terms)
        self.assertIn("背ラベル", terms)
        self.assertEqual(self.run_tool("check").returncode, 0)
        self.git("add", "--all")
        self.assertEqual(self.git("diff", "--name-only", "--diff-filter=U").stdout, "")

    def test_merge_conflict_keeps_current_branch_and_generate_fixes_it(self):
        self.make_conflicting_branches()
        merge = self.git("merge", "--no-edit", "other", check=False)
        self.assertNotEqual(merge.returncode, 0, merge.stdout)
        # git merge では、現在のブランチ (main) の内容が残る
        self.assert_conflicts_keep("main")
        self.assert_generate_resolves()
        self.git("commit", "--quiet", "--no-edit")

    def test_rebase_conflict_keeps_upstream_and_generate_fixes_it(self):
        self.make_conflicting_branches()
        self.git("switch", "--quiet", "other")
        rebase = self.git("rebase", "main", check=False)
        self.assertNotEqual(rebase.returncode, 0, rebase.stdout)
        # git rebase main では、リベース先のブランチ (main) の内容が残る。リベースしているブランチ (other) の内容ではない
        self.assert_conflicts_keep("main")
        self.assert_generate_resolves()
        self.git("-c", "core.editor=true", "rebase", "--continue")


if __name__ == "__main__":
    unittest.main()
