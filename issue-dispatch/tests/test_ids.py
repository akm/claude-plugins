#!/usr/bin/env python3
"""Issue の参照の正規化 (issue-dispatch/scripts/issue_dispatch/ids.py) のテスト。

  python3 -m unittest discover -s issue-dispatch/tests
"""

import os
import sys
import unittest

_SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, _SCRIPTS)

from issue_dispatch import config, ids  # noqa: E402


class IdsTest(unittest.TestCase):

    def test_key_and_url_normalize_to_the_same_form(self):
        for text in ("akm/sample#12", " akm/sample#12 ", "https://github.com/akm/sample/issues/12", "https://github.com/akm/sample/issues/12/"):
            with self.subTest(text=text):
                self.assertEqual(ids.issue_key(text), "akm/sample#12")
                self.assertEqual(ids.issue_url(text), "https://github.com/akm/sample/issues/12")
                self.assertEqual(ids.parse_issue_ref(text)["number"], 12)

    def test_unreadable_references(self):
        for text in ("", "sample#12", "akm/sample#0", "akm/sample#x", "https://github.com/akm/sample/pull/12",
                     "https://gitlab.com/akm/sample/issues/12", "akm/sample", "akm/sam ple#1", None, 12):
            with self.subTest(text=text):
                self.assertIsNone(ids.parse_issue_ref(text), "PR の URL・ほかの host・形の崩れは読めないこと")

    def test_same_issue_ignores_repository_case(self):
        self.assertTrue(ids.same_issue("AKM/Sample#12", "https://github.com/akm/sample/issues/12"))
        self.assertFalse(ids.same_issue("akm/sample#12", "akm/sample#13"))
        self.assertFalse(ids.same_issue("akm/sample#12", "nope"))

    def test_repository_name_pattern_matches_config(self):
        self.assertEqual(ids.REPO_NAME_PATTERN, config.REPO_NAME_PATTERN, "名前の形は config と同じ文字列であること")
        self.assertEqual(ids.issue_key("akm/.github#1"), "akm/.github#1")


if __name__ == "__main__":
    unittest.main()
