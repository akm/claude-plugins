#!/usr/bin/env python3
"""動いている作業セッションを、記録のコメントから集めること (sessions active) のテスト (計画の U3・R29・KTD17)。

偽の gh (ファイル `issue-practice/tests/fake-gh`) で、管理 Issue の PR マージ計画と、作業 Issue の状態とコメントを返す。
"""

import os
import unittest

from fakegh_case import FakeGhCase

from issue_practice import bodies, mergeplan, records  # noqa: E402

REPO = "o/r"
LOGIN = "akm"


def issue_url(n):
    return f"https://github.com/{REPO}/issues/{n}"


def comment(n, cid, first_line, body, login=LOGIN):
    return {"id": cid, "html_url": f"{issue_url(n)}#issuecomment-{cid}", "created_at": f"2026-11-14T00:00:{cid:02d}Z",
            "updated_at": f"2026-11-14T00:00:{cid:02d}Z", "body": f"{first_line}\n\n{body}", "user": {"login": login}}


def working_record(n, cid, session, name, previous=None):
    line = f"issue-practice: session role=working session={session} branch=feat/{n}-x"
    if previous:
        line += f" previous={previous}"
    return comment(n, cid, line, f"起動した。\n\n- 作業セッションの名前: {name}\n- 報告先の管理セッション: r#10 管理: x (local_m)")


def managing_body():
    rows = [(str(i + 1), f"#{n}", f"`feat/{n}-x`", "main", "なし", "") for i, n in enumerate((12, 13, 14, 15, 16))]
    text = "- ブランチの構成: 1\n- PR をマージする人: 利用者\n\n| " + " | ".join(mergeplan.HEADER) + " |\n" \
        + "| --- | --- | --- | --- | --- | --- |\n" + "\n".join(f"| {' | '.join(r)} |" for r in rows) + "\n"
    content = mergeplan.render(mergeplan.parse(text))
    return f"## PR マージ計画\n\n<!-- issue-practice:merge-plan -->\n\n{content}\n\n<!-- /issue-practice:merge-plan -->\n"


class SessionNameTest(unittest.TestCase):

    def test_reads_name_line(self):
        self.assertEqual(records.session_name("起動した。\n\n- 作業セッションの名前: r#12 作業: 一覧\n- 報告先: x"), "r#12 作業: 一覧")
        self.assertEqual(records.session_name("- 管理セッションの名前: r#10 管理: 全体"), "r#10 管理: 全体")
        self.assertIsNone(records.session_name("名前の行が無い"))


class ActiveSessionsTest(FakeGhCase):

    def setUp(self):
        super().setUp()
        states = {12: "OPEN", 13: "OPEN", 14: "CLOSED", 15: "OPEN", 16: "OPEN"}
        comments = {
            10: [comment(10, 1, "issue-practice: session role=managing session=local_m1", "- 管理セッションの名前: r#10 管理: x"),
                 comment(10, 2, "issue-practice: session role=managing session=local_m2 previous=local_m1",
                         "- 管理セッションの名前: r#10 管理: x\n- 前の管理セッション: r#10 管理: x (local_m1)")],
            12: [working_record(12, 3, "local_w12", "r#12 作業: 一つ目"),
                 comment(12, 4, "issue-practice: report type=pr pr=https://github.com/o/r/pull/20", "PR を作った")],
            13: [working_record(13, 5, "local_w13", "r#13 作業: 二つ目"),
                 comment(13, 6, "issue-practice: abandon session=local_w13", "中断した")],
            15: [working_record(15, 7, "local_w15a", "r#15 作業: 四つ目"),
                 working_record(15, 8, "local_w15b", "r#15 作業: 四つ目", previous="local_w15a"),
                 working_record(15, 9, "local_other", "偽物", ) | {"user": {"login": "someone"}}],
            16: [],
        }
        entries = [{"prefix": ["issue", "view", "10", "-R", REPO, "--json", bodies.ISSUE_FIELDS],
                    "stdout": {"number": 10, "url": issue_url(10), "state": "OPEN", "title": "管理", "body": managing_body(),
                               "updatedAt": "x"}},
                   {"prefix": ["api", "user"], "stdout": {"login": LOGIN}}]
        for n, state in states.items():
            entries.append({"prefix": ["issue", "view", str(n), "-R", REPO, "--json", records.STATE_FIELDS],
                            "stdout": {"number": n, "url": issue_url(n), "state": state}})
        for n, items in comments.items():
            entries.append({"prefix": ["api", f"repos/{REPO}/issues/{n}/comments"], "stdout": [items]})
        self.responses(entries)

    def test_collects_active_working_sessions(self):
        code, out, err = self.cli("sessions", "active", "--issue", f"{REPO}#10")
        self.assertEqual(code, 0, err)
        self.assertEqual([(s["number"], s["session"], s["name"]) for s in out["sessions"]],
                         [(12, "local_w12", "r#12 作業: 一つ目"), (15, "local_w15b", "r#15 作業: 四つ目")],
                         "交代した作業 Issue は最後の session の記録を使い、投稿者が違うコメントは読まない")
        self.assertEqual(out["sessions"][0]["branch"], "feat/12-x")
        self.assertEqual(out["sessions"][1]["previous"], "local_w15a")
        self.assertEqual({e["number"]: e["reason"] for e in out["excluded"]},
                         {13: "abandoned", 14: "closed", 16: "no-session"})
        self.assertEqual((out["managing"]["session"], out["managing"]["previous"], out["managing"]["name"]),
                         ("local_m2", "local_m1", "r#10 管理: x"))
        self.assertFalse([a for a in self.recorded() if a[:2] == ["api", f"repos/{REPO}/issues/14/comments"]],
                         "閉じた作業 Issue のコメントは読まない")

    def test_gh_failure(self):
        os.environ["FAKE_GH_MODE"] = "auth_expired"
        code, out, _ = self.cli("sessions", "active", "--issue", f"{REPO}#10")
        self.assertEqual(code, 4)
        self.assertEqual(out["gh_error"]["failure"], "auth")

    def test_no_merge_plan(self):
        self.responses([{"prefix": ["issue", "view", "10"], "stdout": {"number": 10, "url": issue_url(10), "state": "OPEN",
                                                                      "title": "管理", "body": "本文だけ", "updatedAt": "x"}}])
        code, out, _ = self.cli("sessions", "active", "--issue", f"{REPO}#10")
        self.assertEqual(code, 3)
        self.assertTrue(out["errors"])


if __name__ == "__main__":
    unittest.main()
