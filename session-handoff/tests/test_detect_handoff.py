#!/usr/bin/env python3
"""プロンプト送信時フック（detect-handoff.py）のテスト。

標準ライブラリの unittest だけで動く（利用者の環境に pytest 等を要求しない）。

  python3 -m unittest discover -s session-handoff/tests

ここでテストするのは、モデルの裁量ではなく決定的に決まるべき部分:
  - 候補の抽出（コメントの URL の形、ファイル名の形）
  - 目印の有無による判定（形が合っても、目印が無ければ何も差し込まない）
  - gh が失敗・タイムアウト・不在のときに、何も出力せず終了コード 0 で終わること
  - スキルを直接呼んでいるプロンプトでは何もしないこと
  - 引き継ぎ文の本文を差し込まないこと
"""

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

_HOOK = os.path.join(
    os.path.dirname(__file__), "..", "hook-scripts", "detect-handoff.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("detect_handoff", _HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hook = _load()

URL = "https://github.com/akm/claude-plugins/pull/53#issuecomment-1234567890"
BODY = hook.MARKER + "\n# セッションの引き継ぎ: 例\n\n本文の秘密の文字列\n"


def _gh_result(stdout="", returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def _run_main(payload):
    """main() を標準入力つきで走らせ、(終了コード, 標準出力) を返す。"""
    stdin = io.StringIO(payload if isinstance(payload, str) else json.dumps(payload))
    stdout = io.StringIO()
    with mock.patch.object(sys, "stdin", stdin), mock.patch.object(sys, "stdout", stdout):
        code = hook.main()
    return code, stdout.getvalue()


class FindCandidatesTest(unittest.TestCase):
    def test_PRのコメントのURLを取り出す(self):
        cands = hook.find_candidates("これを再開して " + URL)
        self.assertEqual(cands, [("url", URL, "akm", "claude-plugins", "1234567890")])

    def test_IssueのコメントのURLを取り出す(self):
        url = "https://github.com/akm/claude-plugins/issues/35#issuecomment-42"
        self.assertEqual(hook.find_candidates(url)[0][4], "42")

    def test_コメントを指さないURLは候補にしない(self):
        self.assertEqual(hook.find_candidates("https://github.com/akm/claude-plugins/pull/53"), [])
        self.assertEqual(
            hook.find_candidates("https://github.com/akm/claude-plugins/pull/53#discussion_r1"), []
        )

    def test_引き継ぎ文のファイル名の形を取り出す(self):
        cands = hook.find_candidates("tmp/handoff-20260921-1530-feat-x.md を読んで")
        self.assertEqual(cands, [("path", "tmp/handoff-20260921-1530-feat-x.md")])

    def test_連番つきと絶対パスも取り出す(self):
        cands = hook.find_candidates("/repo/.git/session-handoff/handoff-20260921-1530-main-2.md")
        self.assertEqual(cands[0][1], "/repo/.git/session-handoff/handoff-20260921-1530-main-2.md")

    def test_日時の無いファイル名は候補にしない(self):
        self.assertEqual(hook.find_candidates("docs/handoff-notes.md を直して"), [])

    def test_同じ表記は1回だけ_出現順_上限まで(self):
        paths = ["handoff-20260921-153%d-a.md" % i for i in range(5)]
        cands = hook.find_candidates(" ".join([paths[0]] + paths))
        self.assertEqual([c[1] for c in cands], paths[: hook._MAX_CANDIDATES])


class FileIsHandoffTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cwd = os.path.realpath(self.tmp.name)

    def _write(self, name, content):
        path = os.path.join(self.cwd, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_目印で始まるファイルは絶対パスを返す(self):
        path = self._write("handoff-20260921-1530-x.md", BODY)
        self.assertEqual(hook.file_is_handoff("handoff-20260921-1530-x.md", self.cwd), path)

    def test_目印の無いファイルはNone(self):
        self._write("handoff-20260921-1530-x.md", "# ただのメモ\n")
        self.assertIsNone(hook.file_is_handoff("handoff-20260921-1530-x.md", self.cwd))

    def test_目印が1行目に無いファイルはNone(self):
        self._write("handoff-20260921-1530-x.md", "前置き\n" + BODY)
        self.assertIsNone(hook.file_is_handoff("handoff-20260921-1530-x.md", self.cwd))

    def test_存在しないファイルはNone(self):
        self.assertIsNone(hook.file_is_handoff("handoff-20260921-1530-none.md", self.cwd))


class CommentIsHandoffTest(unittest.TestCase):
    def test_本文が目印で始まればTrue(self):
        with mock.patch.object(hook.subprocess, "run", return_value=_gh_result(BODY)) as run:
            self.assertTrue(hook.comment_is_handoff("akm", "claude-plugins", "1", None))
        self.assertIn("repos/akm/claude-plugins/issues/comments/1", run.call_args[0][0])

    def test_目印が無ければFalse(self):
        with mock.patch.object(hook.subprocess, "run", return_value=_gh_result("LGTM\n")):
            self.assertFalse(hook.comment_is_handoff("akm", "claude-plugins", "1", None))

    def test_ghが失敗したらFalse(self):
        with mock.patch.object(hook.subprocess, "run", return_value=_gh_result(BODY, returncode=1)):
            self.assertFalse(hook.comment_is_handoff("akm", "claude-plugins", "1", None))

    def test_ghが無い_タイムアウトでもFalse(self):
        for exc in (FileNotFoundError(), subprocess.TimeoutExpired("gh", 3)):
            with mock.patch.object(hook.subprocess, "run", side_effect=exc):
                self.assertFalse(hook.comment_is_handoff("akm", "claude-plugins", "1", None))


class MainTest(unittest.TestCase):
    def test_引き継ぎ文のURLなら実行を促す文脈を出す(self):
        with mock.patch.object(hook.subprocess, "run", return_value=_gh_result(BODY)):
            code, out = _run_main({"prompt": URL, "cwd": "/"})
        self.assertEqual(code, 0)
        ctx = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(ctx["hookEventName"], "UserPromptSubmit")
        self.assertIn("handoff-resume", ctx["additionalContext"])
        self.assertIn(URL, ctx["additionalContext"])

    def test_引き継ぎ文の本文は差し込まない(self):
        with mock.patch.object(hook.subprocess, "run", return_value=_gh_result(BODY)):
            _, out = _run_main({"prompt": URL, "cwd": "/"})
        self.assertNotIn("本文の秘密の文字列", out)

    def test_目印の無いコメントのURLでは何も出さない(self):
        with mock.patch.object(hook.subprocess, "run", return_value=_gh_result("LGTM")):
            self.assertEqual(_run_main({"prompt": URL, "cwd": "/"}), (0, ""))

    def test_候補が無いプロンプトではghを呼ばない(self):
        with mock.patch.object(hook.subprocess, "run") as run:
            self.assertEqual(_run_main({"prompt": "テストを直して", "cwd": "/"}), (0, ""))
        run.assert_not_called()

    def test_スキルを直接呼んでいるプロンプトでは何もしない(self):
        for prefix in ("/handoff-resume ", "/session-handoff:handoff-resume "):
            with mock.patch.object(hook.subprocess, "run") as run:
                self.assertEqual(_run_main({"prompt": prefix + URL, "cwd": "/"}), (0, ""))
            run.assert_not_called()

    def test_ローカルファイルは絶対パスで出す(self):
        with tempfile.TemporaryDirectory() as d:
            cwd = os.path.realpath(d)
            name = "handoff-20260921-1530-x.md"
            with open(os.path.join(cwd, name), "w", encoding="utf-8") as f:
                f.write(BODY)
            _, out = _run_main({"prompt": name + " を再開して", "cwd": cwd})
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn(os.path.join(cwd, name), ctx)

    def test_壊れた入力でも終了コード0で何も出さない(self):
        self.assertEqual(_run_main("not json"), (0, ""))
        self.assertEqual(_run_main({"prompt": None}), (0, ""))
        self.assertEqual(_run_main([]), (0, ""))


if __name__ == "__main__":
    unittest.main()
