#!/usr/bin/env python3
"""識別子の解析 (ファイル `issue-practice/scripts/issue_practice/refs.py`) のテスト。"""

import unittest

from fakegh_case import FakeGhCase  # noqa: F401  (sys.path にスクリプトのディレクトリを加える)

from issue_practice import refs  # noqa: E402


class ParseRefTest(unittest.TestCase):

    def test_accepted_forms(self):
        cases = {
            "owner/repo#12": ("owner", "repo", 12, None, "owner/repo#12"),
            "https://github.com/o/r/issues/12": ("o", "r", 12, "issue", "o/r#12"),
            "https://github.com/o/r/pull/12": ("o", "r", 12, "pull", "o/r#12"),
            "https://github.com/o/r.js/issues/3/": ("o", "r.js", 3, "issue", "o/r.js#3"),
            "  akm/claude-plugins#239 ": ("akm", "claude-plugins", 239, None, "akm/claude-plugins#239"),
        }
        for text, (owner, repo, number, kind, key) in cases.items():
            with self.subTest(text=text):
                r = refs.parse_ref(text)
                self.assertNotIn("error", r)
                self.assertEqual((r["owner"], r["repo"], r["number"], r["kind"], r["key"]), (owner, repo, number, kind, key))

    def test_url_is_normalized(self):
        self.assertEqual(refs.parse_ref("o/r#5")["url"], "https://github.com/o/r/issues/5")
        self.assertEqual(refs.parse_ref("https://github.com/o/r/pull/5/")["url"], "https://github.com/o/r/pull/5")

    def test_short_form_uses_default_repo(self):
        r = refs.parse_ref("#12", default_repo="akm/claude-plugins")
        self.assertEqual((r["key"], r["number"]), ("akm/claude-plugins#12", 12))
        self.assertEqual(refs.parse_ref("12", default_repo="o/r")["key"], "o/r#12")

    def test_short_form_without_repo_has_no_key(self):
        r = refs.parse_ref("#12")
        self.assertNotIn("error", r)
        self.assertEqual((r["number"], r["key"], r["owner"]), (12, None, None))

    def test_rejected_forms_have_reasons(self):
        for text in ("", "   ", None, "o/r#0", "#0", "0", "o/r#012", "https://github.com/o/r/issues/0",
                     "https://github.com/o/r/discussions/3", "https://example.com/o/r/issues/3", "o#3", "o/r/x#3",
                     "o/r#", "#", "abc", "o/..#3", "https://github.com/o/r/issues/3#issuecomment-1"):
            with self.subTest(text=text):
                r = refs.parse_ref(text)
                self.assertIn("error", r)
                self.assertTrue(r["error"])

    def test_bad_default_repo(self):
        self.assertIn("error", refs.parse_ref("#3", default_repo="not-a-repo"))

    def test_same_issue_ignores_owner_repo_case(self):
        self.assertTrue(refs.same_issue(refs.parse_ref("AKM/Claude-Plugins#3"), refs.parse_ref("https://github.com/akm/claude-plugins/issues/3")))
        self.assertFalse(refs.same_issue(refs.parse_ref("o/r#3"), refs.parse_ref("o/r#4")))
        self.assertFalse(refs.same_issue(refs.parse_ref("#3"), refs.parse_ref("#3")), "リポジトリが分からない参照は同じとしないこと")


class ParseCommentUrlTest(unittest.TestCase):

    def test_comment_url(self):
        r = refs.parse_comment_url("https://github.com/akm/claude-plugins/issues/266#issuecomment-6857140375")
        self.assertEqual((r["key"], r["comment_id"], r["kind"]), ("akm/claude-plugins#266", 6857140375, "issue"))

    def test_rejected(self):
        for text in ("https://github.com/o/r/issues/3", "https://github.com/o/r/issues/3#issuecomment-", "", None):
            with self.subTest(text=text):
                self.assertIn("error", refs.parse_comment_url(text))


class ParseMilestoneNameTest(unittest.TestCase):

    def test_without_target(self):
        self.assertEqual(refs.parse_milestone_name("R285 (バックアップ一式)"),
                         {"number": 285, "target": None, "subject": "バックアップ一式"})

    def test_with_target(self):
        self.assertEqual(refs.parse_milestone_name("R285 platform (…)"), {"number": 285, "target": "platform", "subject": "…"})

    def test_subject_may_contain_parentheses(self):
        self.assertEqual(refs.parse_milestone_name("R7 (認証 (OAuth) の移行)")["subject"], "認証 (OAuth) の移行")

    def test_rejected_forms_have_reasons(self):
        for name in ("285 (x)", "R285", "R285 ()", "R0 (x)", "R285(x)", "R285 two words (x)", "r285 (x)",
                     "20261008-2 (x)", "", None, "R285 ( )"):
            with self.subTest(name=name):
                r = refs.parse_milestone_name(name)
                self.assertIn("error", r)


class ParseRepoTest(unittest.TestCase):

    def test_repo(self):
        self.assertEqual(refs.parse_repo("akm/claude-plugins")["repo_key"], "akm/claude-plugins")
        for text in ("akm", "a/b/c", "", "-a/b", "a/.."):
            with self.subTest(text=text):
                self.assertIn("error", refs.parse_repo(text))


class RefsCliTest(FakeGhCase):

    def test_refs_parse(self):
        code, out, _ = self.cli("refs", "parse", "#12", "--repo", "o/r")
        self.assertEqual(code, 0)
        self.assertEqual(out["ref"]["key"], "o/r#12")

    def test_refs_parse_error_is_exit_3(self):
        code, out, _ = self.cli("refs", "parse", "o/r#0")
        self.assertEqual(code, 3)
        self.assertTrue(out["errors"])

    def test_milestone_parse(self):
        code, out, _ = self.cli("refs", "milestone", "R285 platform (x)")
        self.assertEqual((code, out["milestone"]["number"]), (0, 285))
        code, out, _ = self.cli("refs", "milestone", "20261008-2 (x)")
        self.assertEqual(code, 3)


if __name__ == "__main__":
    unittest.main()
