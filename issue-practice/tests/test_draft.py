#!/usr/bin/env python3
"""計画案の共通の部分 (ファイル `issue-practice/scripts/issue_practice/draft.py`) のテスト。

git を実行するテストは、一時ディレクトリに作ったリポジトリで行い、環境変数 GIT_DIR などを消してから実行する
(テストを hook や別の作業ツリーから実行しても、このリポジトリの .git を読み書きしないため)。
"""

import json
import os
import subprocess
import unittest

from fakegh_case import FakeGhCase, fixture_json

from issue_practice import bodies, draft  # noqa: E402

BODY_239 = fixture_json("issue-view-239")["body"]
SHA_239 = bodies.body_sha256(BODY_239)
URL_239 = "https://github.com/akm/claude-plugins/issues/239"

VALID = f"""# 計画案: 管理 Issue #239 の計画

説明の文。

## 元にした Issue

- {URL_239} 本文の SHA-256: {SHA_239}

## 作業 Issue

- 1 つ目
"""

_GIT_KEYS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR", "GIT_PREFIX")


def git(root, *args):
    env = {k: v for k, v in os.environ.items() if k not in _GIT_KEYS}
    subprocess.run(["git", "-C", root, *args], check=True, capture_output=True, env=env)


class ParseTest(unittest.TestCase):

    NAME = "20261114-0010-managing-issue-plan-239.md"

    def test_valid(self):
        r = draft.parse(VALID, self.NAME)
        self.assertEqual(r["errors"], [])
        self.assertEqual((r["title"], r["skill"], r["target"], r["created"]),
                         ("管理 Issue #239 の計画", "managing-issue-plan", "239", "2026-11-14 00:10"))
        self.assertEqual(r["sources"], [{"issue": "akm/claude-plugins#239", "url": URL_239, "sha256": SHA_239, "line": 7}])
        self.assertEqual(r["sections"], [{"title": "作業 Issue", "line": 9}])

    def test_none_item(self):
        text = "# 計画案: x\n\n## 元にした Issue\n\n- なし\n"
        r = draft.parse(text, "20261114-0010-new-issue-next-release.md")
        self.assertEqual((r["errors"], r["sources"], r["target"]), ([], [], "next-release"))

    def test_errors_have_line_numbers(self):
        cases = [
            ("# 題\n\n## 元にした Issue\n\n- なし\n", 1),
            (f"# 計画案: x\n\n## 元にした Issue\n\n- {URL_239} sha: abc\n", 5),
            (f"# 計画案: x\n\n## 元にした Issue\n\n- https://example.com/x 本文の SHA-256: {SHA_239}\n", 5),
            (f"# 計画案: x\n\n## 元にした Issue\n\n- {URL_239} 本文の SHA-256: {SHA_239}\n- {URL_239} 本文の SHA-256: {SHA_239}\n", 6),
            (f"# 計画案: x\n\n## 元にした Issue\n\n- なし\n- {URL_239} 本文の SHA-256: {SHA_239}\n", 3),
            ("# 計画案: x\n\n## 元にした Issue\n\n## 次\n", 3),
            ("# 計画案: x\n\n## 前\n\n## 元にした Issue\n\n- なし\n", 5),
        ]
        for text, line in cases:
            with self.subTest(text=text):
                r = draft.parse(text, self.NAME)
                self.assertTrue(r["errors"])
                self.assertIn(line, [e["line"] for e in r["errors"]])

    def test_missing_sources_section(self):
        r = draft.parse("# 計画案: x\n\n本文だけ\n", self.NAME)
        self.assertEqual([e["line"] for e in r["errors"]], [None])

    def test_heading_in_code_block_is_ignored(self):
        text = "# 計画案: x\n\n```\n## 元にした Issue\n```\n\n## 元にした Issue\n\n- なし\n"
        self.assertEqual(draft.parse(text, self.NAME)["errors"], [])

    def test_file_name(self):
        self.assertEqual(draft.parse_file_name(self.NAME), {"date": "20261114", "time": "0010", "skill": "managing-issue-plan",
                                                            "target": "239"})
        self.assertEqual(draft.parse_file_name("20261114-0010-release-issue-plan-r285.md")["skill"], "release-issue-plan",
                         "長いスキルの名前を優先して解析すること")
        for name in ("plan.md", "20261114-0010-unknown-skill-239.md", "20261114-0010-new-issue-.md", "20261114-0010-new-issue-239.txt",
                     "2026111-0010-new-issue-239.md"):
            with self.subTest(name=name):
                self.assertIn("error", draft.parse_file_name(name))
        self.assertEqual(draft.file_name("new-issue", "239", "20261114-0010"), {"file_name": "20261114-0010-new-issue-239.md"})
        self.assertIn("error", draft.file_name("no-skill", "239", "20261114-0010"))
        self.assertIn("error", draft.file_name("new-issue", "Next Release", "20261114-0010"))
        self.assertIn("error", draft.file_name("new-issue", "239", "2026-11-14"))
        self.assertEqual([e["line"] for e in draft.parse("# 計画案: x\n\n## 元にした Issue\n\n- なし\n", "x.md")["errors"]], [None],
                         "ファイル名の誤りは行に結び付けないこと")


class DirTest(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._tmp.name)
        git(self.root, "init", "-q")

    def tearDown(self):
        self._tmp.cleanup()

    def ignore(self, pattern):
        with open(os.path.join(self.root, ".gitignore"), "w", encoding="utf-8") as f:
            f.write(pattern + "\n")

    def test_not_ignored(self):
        r = draft.check_dir(self.root)
        self.assertEqual(r["status"], "unsatisfied")
        self.assertIn(".gitignore", r["errors"][0])
        r = draft.new_path(self.root, "new-issue", "239", "20261114-0010")
        self.assertEqual(r["status"], "unsatisfied")
        self.assertFalse(os.path.exists(os.path.join(self.root, "tmp")), "無視されていなければディレクトリを作らないこと")

    def test_ignored(self):
        self.ignore("tmp/")
        self.assertEqual(draft.check_dir(self.root)["status"], "ok")
        r = draft.new_path(self.root, "new-issue", "239", "20261114-0010")
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["relative"], "tmp/issue-practice/20261114-0010-new-issue-239.md")
        self.assertTrue(os.path.isdir(os.path.join(self.root, "tmp", "issue-practice")))

    def test_existing_file_is_not_overwritten(self):
        self.ignore("tmp/")
        path = draft.new_path(self.root, "new-issue", "239", "20261114-0010")["path"]
        with open(path, "w", encoding="utf-8") as f:
            f.write("前の計画案\n")
        r = draft.new_path(self.root, "new-issue", "239", "20261114-0010")
        self.assertEqual(r["status"], "unsatisfied")
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "前の計画案\n")

    def test_root_must_be_absolute_toplevel(self):
        self.ignore("tmp/")
        sub = os.path.join(self.root, "sub")
        os.makedirs(sub)
        self.assertEqual(draft.check_dir(sub)["status"], "unsatisfied", "サブディレクトリはルートとして扱わないこと")
        self.assertEqual(draft.check_dir("relative/path")["status"], "unsatisfied")

    def test_not_a_repository(self):
        import tempfile
        with tempfile.TemporaryDirectory() as other:
            r = draft.check_dir(os.path.realpath(other))
        self.assertEqual(r["status"], "git_failed")

    def test_git_dir_in_environment_is_ignored(self):
        """環境変数 GIT_DIR が別のリポジトリを指していても、--root のリポジトリで判定する。"""
        self.ignore("tmp/")
        saved = os.environ.get("GIT_DIR")
        os.environ["GIT_DIR"] = os.path.join(self.root, "no-such-git-dir")
        try:
            self.assertEqual(draft.check_dir(self.root)["status"], "ok")
        finally:
            if saved is None:
                os.environ.pop("GIT_DIR")
            else:
                os.environ["GIT_DIR"] = saved


class CompareTest(FakeGhCase):

    def write_draft(self, text=VALID, name="20261114-0010-managing-issue-plan-239.md"):
        path = os.path.join(self.root, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def test_same_body_with_new_updated_at_is_not_changed(self):
        """コメントが付いて updatedAt だけが変わったときは、書き換えられたと判定しない。"""
        view = fixture_json("issue-view-239")
        view["updatedAt"] = "2099-01-01T00:00:00Z"
        self.responses([{"prefix": ["issue", "view", "239"], "stdout": view}])
        code, out, _ = self.cli("draft", "compare", self.write_draft())
        self.assertEqual(code, 0, out)
        self.assertEqual(out["results"][0]["changed"], False)
        self.assertEqual(out["results"][0]["updated_at"], "2099-01-01T00:00:00Z")

    def test_changed_body(self):
        view = fixture_json("issue-view-239")
        view["body"] += "\n追記\n"
        self.responses([{"prefix": ["issue", "view", "239"], "stdout": view}])
        code, out, _ = self.cli("draft", "compare", self.write_draft())
        self.assertEqual(code, 3)
        self.assertTrue(out["results"][0]["changed"])
        self.assertIn("akm/claude-plugins#239", out["errors"][0])

    def test_gh_failure(self):
        os.environ["FAKE_GH_MODE"] = "auth_expired"
        code, out, _ = self.cli("draft", "compare", self.write_draft())
        self.assertEqual(code, 4)
        self.assertEqual(out["gh_error"]["failure"], "auth")

    def test_malformed_draft_is_not_compared(self):
        code, out, _ = self.cli("draft", "compare", self.write_draft("# 題\n"))
        self.assertEqual(code, 3)
        self.assertEqual(self.recorded(), [], "形が違う計画案では gh を実行しないこと")

    def test_parse_cli(self):
        code, out, _ = self.cli("draft", "parse", self.write_draft())
        self.assertEqual((code, out["skill"]), (0, "managing-issue-plan"))
        code, out, _ = self.cli("draft", "parse", self.write_draft("# 題\n"))
        self.assertEqual(code, 3)
        self.assertEqual(out["errors"][0]["line"], 1)

    def test_missing_file_is_not_exit_3_or_4(self):
        """ファイルが無いのは呼び出し元の誤りなので、例外で終了する (3 や 4 にしない)。"""
        code, out, err = self.cli("draft", "parse", os.path.join(self.root, "none.md"))
        self.assertEqual(code, 1)
        self.assertIn("FileNotFoundError", err)


class DirCliTest(unittest.TestCase):

    def test_path_cli(self):
        import tempfile
        from fakegh_case import ENTRY
        import sys
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.realpath(tmp)
            git(root, "init", "-q")
            env = {k: v for k, v in os.environ.items() if k not in _GIT_KEYS}
            run = lambda *a: subprocess.run([sys.executable, ENTRY, *a], capture_output=True, text=True, env=env)  # noqa: E731
            completed = run("draft", "dir-check", "--root", root)
            self.assertEqual(completed.returncode, 3)
            with open(os.path.join(root, ".gitignore"), "w", encoding="utf-8") as f:
                f.write("tmp/\n")
            completed = run("draft", "path", "--root", root, "--skill", "new-issue", "--target", "next", "--stamp", "20261114-0930")
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(completed.stdout)["relative"], "tmp/issue-practice/20261114-0930-new-issue-next.md")
            completed = run("draft", "dir-check", "--root", os.path.join(root, "no-such"))
            self.assertEqual(completed.returncode, 4)


if __name__ == "__main__":
    unittest.main()
