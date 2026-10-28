#!/usr/bin/env python3
"""セッション (issue-dispatch/scripts/issue_dispatch/sessions.py) のテスト。gh も ListAgents も使わず、環境変数は辞書で渡す。

  python3 -m unittest discover -s issue-dispatch/tests

様式の SSOT は issue-dispatch/skills/issue-dispatch/references/messaging.md。
"""

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.join(_HERE, "..", "scripts")
sys.path.insert(0, _SCRIPTS)

from issue_dispatch import sessions  # noqa: E402

_DOC = os.path.join(_HERE, "..", "skills", "issue-dispatch", "references", "messaging.md")
UUID = "c3c8c6fe-1234-4abc-8def-0123456789ab"
HOST = "local_ed5effac-5678-4abc-8def-0123456789ab"


class SessionIdTest(unittest.TestCase):

    def test_normalize_keeps_local_prefix(self):
        """`local_<UUID>` と `<UUID>` を区別して保持し、別物として比べる。"""
        self.assertEqual(sessions.normalize_session_id(f"  {HOST}\n"), HOST)
        self.assertEqual(sessions.normalize_session_id(UUID), UUID)
        self.assertNotEqual(sessions.normalize_session_id(HOST), sessions.normalize_session_id(HOST[len("local_"):]))
        self.assertTrue(sessions.same_session_id(HOST, f" {HOST} "))
        self.assertFalse(sessions.same_session_id(HOST, HOST[len("local_"):]), "local_ の有無が違えば別のセッション")
        self.assertFalse(sessions.same_session_id(HOST, None))

    def test_normalize_rejects_bad_ids(self):
        for bad in ("", "   ", None, 12, "a b", "a/b", "local_", "a\nb", ".", "..", ".hidden"):  # `local_.` は `.` で始まらず、パスの 1 区切りにできるので通す
            with self.subTest(bad=bad):
                self.assertIsNone(sessions.normalize_session_id(bad))

    def test_own_session_id_prefers_host(self):
        """CLAUDE_CODE_HOST_SESSION_ID があればそれ、無ければ CLAUDE_CODE_SESSION_ID (KTD10)。"""
        self.assertEqual(sessions.own_session_id({"CLAUDE_CODE_HOST_SESSION_ID": HOST, "CLAUDE_CODE_SESSION_ID": UUID}), (HOST, "CLAUDE_CODE_HOST_SESSION_ID"))
        self.assertEqual(sessions.own_session_id({"CLAUDE_CODE_SESSION_ID": UUID}), (UUID, "CLAUDE_CODE_SESSION_ID"))
        self.assertEqual(sessions.own_session_id({"CLAUDE_CODE_HOST_SESSION_ID": "  ", "CLAUDE_CODE_SESSION_ID": UUID}), (UUID, "CLAUDE_CODE_SESSION_ID"), "空の値は無いものとして扱う")
        self.assertEqual(sessions.own_session_id({}), (None, None))
        self.assertEqual(sessions.own_session_id({"CLAUDE_CODE_SESSION_ID": "a b"}), (None, None), "形が読めなければ無い")


class ManagerNameTest(unittest.TestCase):

    def test_name_from_project_and_login(self):
        """規約の名前は owner・番号・login から作り、同じ入力なら同じ名前 (KD23)。"""
        self.assertEqual(sessions.manager_name("akm", 3, "akm"), "issue-dispatch akm/3/akm")
        self.assertEqual(sessions.manager_name("akm", 3, "akm"), sessions.manager_name("akm", "3", "akm"))
        self.assertEqual(sessions.manager_name({"owner": "akm", "number": 3}, login="someone"), "issue-dispatch akm/3/someone", "設定の project (dict) も受ける")
        self.assertEqual(sessions.manager_name("AKM", 3, "Akm"), "issue-dispatch akm/3/akm", "owner と login の表記が違っても同じ名前 (GitHub は区別しない)")

    def test_name_rejects_bad_inputs(self):
        for owner, number, login in (("", 3, "akm"), ("akm", 0, "akm"), ("akm", "x", "akm"), ("akm", 3, ""), ("a/b", 3, "akm"), ("akm", 3, "a b"), (None, 3, "akm")):
            with self.subTest(owner=owner, number=number, login=login), self.assertRaises(ValueError):
                sessions.manager_name(owner, number, login)

    def test_parse_round_trip(self):
        parsed = sessions.parse_manager_name("issue-dispatch akm/3/akm")
        self.assertEqual(parsed, {"owner": "akm", "number": 3, "login": "akm"})
        self.assertEqual(sessions.manager_name(**parsed), "issue-dispatch akm/3/akm")
        self.assertEqual(sessions.parse_manager_name("  issue-dispatch my-org/12/some-one  "), {"owner": "my-org", "number": 12, "login": "some-one"})
        self.assertEqual(sessions.parse_manager_name("issue-dispatch AKM/3/Akm"), {"owner": "akm", "number": 3, "login": "akm"}, "読むときも小文字にそろえる")
        for bad in ("issue-dispatch akm/3", "issue-dispatch akm/3/akm/x", "issue-dispatch akm/0/akm", "issue-dispatch  akm/3/akm", "worker-a", "", None,
                    "issue-dispatch akm/3/akm [2c2f42]"):
            with self.subTest(bad=bad):
                self.assertIsNone(sessions.parse_manager_name(bad), "ListAgents の行に付く短い識別子は呼び出し元が外してから渡す")


class TempDirTest(unittest.TestCase):

    def test_under_tmpdir_or_tmp(self):
        """`${TMPDIR:-/tmp}/issue-dispatch/<セッション ID>/` で、作業ツリーの中を指さない。"""
        self.assertEqual(sessions.session_temp_dir(HOST, {"TMPDIR": "/var/folders/x/T/"}), f"/var/folders/x/T/issue-dispatch/{HOST}")
        self.assertEqual(sessions.session_temp_dir(HOST, {"TMPDIR": "/var/folders/x/T"}), f"/var/folders/x/T/issue-dispatch/{HOST}")
        self.assertEqual(sessions.session_temp_dir(UUID, {}), f"/tmp/issue-dispatch/{UUID}")
        self.assertEqual(sessions.session_temp_dir(UUID, {"TMPDIR": ""}), f"/tmp/issue-dispatch/{UUID}", "空の TMPDIR は無いものとして扱う")
        self.assertEqual(sessions.session_temp_dir(UUID, {"TMPDIR": "relative/dir"}), f"/tmp/issue-dispatch/{UUID}", "相対パスの TMPDIR は使わない (作業ツリーの中を指しうる)")
        self.assertFalse(sessions.session_temp_dir(UUID, {"TMPDIR": "/var/folders/x/T"}).startswith(os.getcwd()))
        self.assertEqual(sessions.session_temp_dir(UUID, {"TMPDIR": "/a///b/"}), f"/a/b/issue-dispatch/{UUID}", "続く / は 1 つにそろえる")

    def test_rejects_dot_ids(self):
        """`.`・`..` はパスの 1 区切りにできないので、一時ディレクトリが issue-dispatch/ そのものや TMPDIR を指さない。"""
        for bad in (".", ".."):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                sessions.session_temp_dir(bad, {"TMPDIR": "/var/tmp"})

    def test_rejects_bad_session_id(self):
        with self.assertRaises(ValueError):
            sessions.session_temp_dir("a/b", {})
        with self.assertRaises(ValueError):
            sessions.session_temp_dir("", {})


class DocTest(unittest.TestCase):

    def test_doc_mentions_rules(self):
        with open(_DOC, encoding="utf-8") as f:
            doc = f.read()
        for text in ("`CLAUDE_CODE_HOST_SESSION_ID`", "`CLAUDE_CODE_SESSION_ID`", "`issue-dispatch <owner>/<number>/<login>`", "`${TMPDIR:-/tmp}/issue-dispatch/<セッション ID>/`",
                     "`own_session_id`", "`manager_name`", "`session_temp_dir`"):
            self.assertIn(text, doc, f"{text} が文書に無い")


if __name__ == "__main__":
    unittest.main()
