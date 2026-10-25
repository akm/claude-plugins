#!/usr/bin/env python3
"""コメント (issue-dispatch/scripts/issue_dispatch/comments.py) と、CLI の `comment list` / `comment post` / `comment parse` の
テスト。偽の gh (fake-gh) と固定データ (fixtures/gh/issue-comments-ok・api-user) で動く。先頭行の形のコメントは固定データに
無いので、固定データの本文を書き換えて作る。偽の gh の用意は test_project.FakeGhCase と同じ。

  python3 -m unittest discover -s issue-dispatch/tests

様式の正本は issue-dispatch/skills/issue-dispatch/references/issue-format.md の「コメント」。
"""

import json
import os
import subprocess
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.join(_HERE, "..", "scripts")
sys.path.insert(0, _SCRIPTS)
sys.path.insert(0, _HERE)

from issue_dispatch import comments  # noqa: E402
from test_project import FakeGhCase, fixture_json  # noqa: E402

_CLI = os.path.join(_SCRIPTS, "issue_dispatch.py")
_DOC = os.path.join(_HERE, "..", "skills", "issue-dispatch", "references", "issue-format.md")
REPO = "akm/issue-dispatch-verify-a"
ISSUE3 = f"https://github.com/{REPO}/issues/3"
OTHER = f"{REPO}#5"
PR9 = f"https://github.com/{REPO}/pull/9"
PR10 = f"https://github.com/{REPO}/pull/10"
USER_ENTRY = {"prefix": ["api", "user"], "stdout": {"fixture": "api-user"}}
MANAGER = {"role": "manager", "name": "mgr", "session_id": "M-1"}
WORKER = {"role": "worker", "name": "worker 1", "session_id": "W-7"}


def header(kind, who=MANAGER, **values):
    return comments.format_header(who["role"], who["name"], who["session_id"], kind, values)


def cli(*args, stdin=None):
    r = subprocess.run([sys.executable, _CLI, *args], capture_output=True, text=True, input=stdin)
    return r.returncode, json.loads(r.stdout) if r.stdout.strip() else None, r.stderr


class HeaderFormatParseTest(unittest.TestCase):
    """先頭行の生成と解析が往復で一致する。"""

    CASES = [
        ("割り当て", MANAGER, {"to": "W-7", "assignment": 1}),
        ("開始可", MANAGER, {"to": "W-7", "assignment": 1, "declaration": 6262508430}),
        ("待機", MANAGER, {"to": "W-7", "assignment": 1, "declaration": 6262508430,
                          "waits": [{"kind": "利用者の回答"}, {"kind": "資源", "resource": "staging-db"}]}),
        ("待機", MANAGER, {"to": "W-7", "assignment": 2, "declaration": 6262508431,
                          "waits": [{"kind": "Issue", "issue": OTHER}, {"kind": "小さな PR", "issue": OTHER, "pr": PR9}, {"kind": "設定"}]}),
        ("待機", MANAGER, {"to": "W-7", "assignment": 2, "declaration": 6262508431, "waits": [{"kind": "小さな PR", "issue": OTHER}]}),
        ("解放", MANAGER, {"to": "W-7", "assignment": 1, "release_reason": "ID の変更"}),
        ("停滞", MANAGER, {"to": "W-7", "assignment": 1, "stuck_state": "idle-no-progress"}),
        ("依頼", MANAGER, {"to": "W-7", "assignment": 1, "request_kind": "宣言の修正", "declaration": 6262508430}),
        ("依頼", MANAGER, {"to": "W-7", "assignment": 1, "request_kind": "本文の追記", "pr": PR9}),
        ("依頼", MANAGER, {"to": "W-7", "assignment": 1, "request_kind": "小さな PR", "waiting_issue": OTHER, "waiting_declaration": 777}),
        ("依頼", MANAGER, {"to": "W-7", "assignment": 1, "request_kind": "小さな PR", "waiting_issue": OTHER, "waiting_declaration": 777, "previous_pr": PR9}),
        ("引き継ぎ", MANAGER, {}),
        ("依存の待機", MANAGER, {"blockers": [OTHER, f"{REPO}#6"]}),
        ("依存の解消", MANAGER, {}),
        ("着手の宣言", WORKER, {}),
        ("宣言の更新", WORKER, {}),
        ("小さな PR の報告", WORKER, {"waiting_issue": OTHER, "waiting_declaration": 777, "previous_pr": PR9}),
        ("PR の報告", WORKER, {}),
    ]

    def test_round_trip(self):
        for kind, who, values in self.CASES:
            with self.subTest(kind=kind, values=values):
                line = comments.format_header(who["role"], who["name"], who["session_id"], kind, values)
                self.assertNotIn("\n", line)
                parsed = comments.parse_header(line)
                self.assertIsNotNone(parsed, line)
                self.assertEqual((parsed["role"], parsed["name"], parsed["session_id"], parsed["kind"]),
                                 (who["role"], who["name"], who["session_id"], kind))
                self.assertEqual(parsed["values"], comments.normalize_values(kind, values))

    def test_examples(self):
        self.assertEqual(header("開始可", to="W-7", assignment=1, declaration=6262508430),
                         "issue-dispatch | 管理のセッション | mgr | M-1 | 開始可 | 対象 W-7 | 割り当て 1 | 宣言 6262508430")
        self.assertEqual(header("待機", to="W-7", assignment=1, declaration=1, waits=[{"kind": "小さな PR", "issue": OTHER, "pr": PR9}, {"kind": "資源", "resource": "db"}]),
                         f"issue-dispatch | 管理のセッション | mgr | M-1 | 待機 | 対象 W-7 | 割り当て 1 | 宣言 1 | 理由 小さな PR {OTHER} PR {PR9} | 理由 資源 db")
        self.assertEqual(header("小さな PR の報告", WORKER, waiting_issue=OTHER, waiting_declaration=777),
                         f"issue-dispatch | 作業のセッション | worker 1 | W-7 | 小さな PR の報告 | 待機する Issue {OTHER} | 待機する Issue の宣言 777")
        self.assertEqual(header("依存の待機", blockers=[OTHER]), f"issue-dispatch | 管理のセッション | mgr | M-1 | 依存の待機 | Issue {OTHER}")

    def test_name_with_delimiter(self):
        """区切り文字 ` | ` を含む名前でも、右から読むので正しく解析できる。"""
        who = {"role": "manager", "name": "a | 対象 b | 開始可", "session_id": "M-2"}
        line = comments.format_header(who["role"], who["name"], who["session_id"], "開始可", {"to": "W-7", "assignment": 3, "declaration": 5})
        parsed = comments.parse_header(line)
        self.assertEqual(parsed["name"], who["name"])
        self.assertEqual(parsed["values"], {"to": "W-7", "assignment": 3, "declaration": 5})

    def test_issue_references_are_normalized(self):
        parsed = comments.parse_header(header("依存の待機", blockers=[f"https://github.com/{REPO}/issues/5"]))
        self.assertEqual(parsed["values"]["blockers"], [OTHER], "Issue の参照は owner/repo#番号 の正規形にすること")

    def test_rejects(self):
        for line in ("u1 latency 0", "issue-dispatch | 管理のセッション | mgr | M-1", "issue-dispatch | 管理のセッション | mgr | M-1 | 謎の種類",
                     "issue-dispatch | 作業のセッション | w | W-1 | 割り当て | 対象 W-7 | 割り当て 1",  # 役割と種類が合わない
                     "issue-dispatch | 管理のセッション | mgr | M-1 | 開始可 | 対象 W-7 | 割り当て 1",  # 宣言が無い
                     "issue-dispatch | 管理のセッション | mgr | M-1 | 解放 | 対象 W-7 | 割り当て 1 | 理由 気分",
                     "issue-dispatch | 管理のセッション | mgr | M-1 | 割り当て | 対象 W-7 | 割り当て 1 | 宣言 3",  # 余分な値
                     "issue-dispatch | 管理のセッション | mgr | M-1 | 待機 | 対象 W-7 | 割り当て 1 | 宣言 3",  # 理由が無い
                     "issue-dispatch | 管理のセッション | mgr | M-1 | 依存の待機 | Issue not-a-ref",
                     ""):
            with self.subTest(line=line):
                self.assertIsNone(comments.parse_header(line))

    def test_format_rejects_bad_values(self):
        with self.assertRaises(ValueError):
            header("解放", to="W-7", assignment=1, release_reason="気分")
        with self.assertRaises(ValueError):
            header("依頼", to="W-7", assignment=1, request_kind="小さな PR", waiting_issue=OTHER)  # 待機する Issue の宣言が無い
        with self.assertRaises(ValueError):
            header("割り当て", to="W-7")  # 割り当ての番号が無い
        with self.assertRaises(ValueError):
            header("着手の宣言", WORKER, to="W-7")  # 作業のセッションの種類は宛先を持たない
        with self.assertRaises(ValueError):
            header("割り当て", {"role": "manager", "name": "m", "session_id": "M | 1"}, to="W-7", assignment=1)  # ID に区切り
        with self.assertRaises(ValueError):
            header("待機", to="W-7", assignment=1, declaration=1, waits=[{"kind": "Issue"}])  # 待機する Issue が無い

    def test_format_rejects_lines_that_do_not_round_trip(self):
        """作った先頭行を同じ内容に読み戻せない入力 (改行を含む値、`|` で終わる名前) は ValueError。"""
        with self.assertRaises(ValueError):
            header("停滞", to="W-7", assignment=1, stuck_state="idle\nx")
        with self.assertRaises(ValueError):
            header("待機", to="W-7", assignment=1, declaration=1, waits=[{"kind": "資源", "resource": "db\nx"}])
        with self.assertRaises(ValueError):
            header("割り当て", to="W-7\nx", assignment=1)
        for name in ("a |", "a | "):  # `| a` は読み戻せるので許す
            with self.subTest(name=name), self.assertRaises(ValueError):
                header("割り当て", {"role": "manager", "name": name, "session_id": "M-1"}, to="W-7", assignment=1)

    def test_match_report(self):
        request = comments.parse_header(header("依頼", to="W-7", assignment=1, request_kind="小さな PR", waiting_issue=OTHER, waiting_declaration=777))
        same = comments.parse_header(header("小さな PR の報告", {"role": "worker", "name": "renamed", "session_id": "W-8"}, waiting_issue=f"https://github.com/{REPO}/issues/5", waiting_declaration=777))
        other_decl = comments.parse_header(header("小さな PR の報告", WORKER, waiting_issue=OTHER, waiting_declaration=778))
        redo = comments.parse_header(header("小さな PR の報告", WORKER, waiting_issue=OTHER, waiting_declaration=777, previous_pr=PR9))
        self.assertTrue(comments.match_report(request, same), "名前と ID は比べない")
        self.assertFalse(comments.match_report(request, other_decl))
        self.assertFalse(comments.match_report(request, redo), "作り直しの依頼でなければ、前の PR を持つ報告は対応しない")
        redo_request = comments.parse_header(header("依頼", to="W-7", assignment=1, request_kind="小さな PR", waiting_issue=OTHER, waiting_declaration=777, previous_pr=PR9))
        self.assertTrue(comments.match_report(redo_request, redo))
        redo_upper = comments.parse_header(header("小さな PR の報告", WORKER, waiting_issue=OTHER.upper(), waiting_declaration=777, previous_pr=PR9.replace(REPO, REPO.upper())))
        self.assertTrue(comments.match_report(redo_request, redo_upper), "前の PR の owner/repo の大文字小文字は区別しない")
        self.assertFalse(comments.match_report(redo_request, same))
        self.assertFalse(comments.match_report(request, request))


def _comment(database_id, body, author="akm", at="2026-10-19T08:00:00Z"):
    return {"id": f"IC_{database_id}", "databaseId": database_id, "url": f"{ISSUE3}#issuecomment-{database_id}", "createdAt": at,
            "author": {"login": author}, "body": body}


class ListTest(FakeGhCase):

    def comments_entry(self, nodes, has_next=False, cursor=None, once=False):
        data = fixture_json("issue-comments-ok")
        c = data["data"]["repository"]["issue"]["comments"]
        c["nodes"] = nodes
        c["pageInfo"] = {"hasNextPage": has_next, "endCursor": cursor}
        entry = {"substring": "query IssueComments", "stdout": data}
        if once:
            entry["once"] = True
        return entry

    def test_lists_own_comments_with_headers(self):
        """Covers AE28. 先頭行が正しくても投稿者のログインが違うコメントは、無いものとして扱う。"""
        nodes = [_comment(1, "u1 latency 0"), _comment(2, header("割り当て", to="W-7", assignment=1) + "\n\n理由"),
                 _comment(3, header("開始可", to="W-7", assignment=1, declaration=2), author="someone-else"),
                 _comment(4, header("着手の宣言", WORKER) + "\n\n## 変えるファイル\n- a.go")]
        self.responses([USER_ENTRY, self.comments_entry(nodes)])
        result = comments.list_comments(ISSUE3)
        self.assertEqual(result["status"], "ok")
        self.assertEqual([c["database_id"] for c in result["comments"]], [1, 2, 4])
        self.assertEqual(result["excluded"], 1)
        self.assertIsNone(result["comments"][0]["header"], "先頭行の形でないコメントは header が None")
        self.assertEqual(result["comments"][1]["header"]["kind"], "割り当て")
        self.assertEqual(result["comments"][1]["body"], "理由", "body は先頭行と空行を除いた本文")
        self.assertEqual(result["comments"][2]["header"]["role"], "worker")
        self.assertEqual(result["comments"][2]["url"], f"{ISSUE3}#issuecomment-4")
        calls = self.recorded_full()
        self.assertEqual([c["args"][:2] for c in calls], [["api", "user"], ["api", "graphql"]])
        self.assertEqual(self.body(calls[1])["variables"], {"owner": "akm", "name": "issue-dispatch-verify-a", "number": 3})

    def test_follows_pages_and_sorts_by_time(self):
        self.responses([self.comments_entry([_comment(2, "b", at="2026-10-19T08:00:02Z")], has_next=True, cursor="C1", once=True),
                        self.comments_entry([_comment(1, "a", at="2026-10-19T08:00:01Z")])])
        result = comments.list_comments(ISSUE3, login="akm")
        self.assertEqual([c["database_id"] for c in result["comments"]], [1, 2])
        self.assertEqual(self.body(self.recorded_full()[1])["variables"]["after"], "C1")

    def test_errors(self):
        self.assertEqual(comments.list_comments("not a ref", login="akm")["status"], "error")
        self.assertEqual(self.recorded(), [])
        os.environ["FAKE_GH_MODE"] = "network"
        result = comments.list_comments(ISSUE3, login="akm")
        self.assertEqual((result["status"], result["failure"]), ("error", "network"))


class AlreadyPostedTest(unittest.TestCase):
    """既投稿の判別 (KTD2)。"""

    @staticmethod
    def own(*lines):
        out = []
        for n, line in enumerate(lines, 1):
            out.append({"database_id": n, "url": f"{ISSUE3}#issuecomment-{n}", "created_at": f"2026-10-19T08:00:{n:02d}Z",
                        "author": "akm", "header": comments.parse_header(line) if line else None, "body": ""})
        return out

    def assertPosted(self, line, existing, posted, msg=""):
        found = comments.already_posted(comments.parse_header(line), self.own(*existing))
        self.assertEqual(found is not None, posted, msg or line)
        return found

    def test_same_header_is_posted(self):
        a1 = header("割り当て", to="W-7", assignment=1)
        found = self.assertPosted(a1, [a1], True)
        self.assertEqual(found["database_id"], 1, "既投稿のコメントを返す")
        self.assertPosted(a1, ["u1 latency 0"], False)
        self.assertPosted(header("割り当て", to="W-7", assignment=2), [a1], False, "割り当ての番号が違えば投稿する")
        self.assertPosted(header("割り当て", to="W-8", assignment=1), [a1], False, "宛先が違えば投稿する")
        renamed = header("割り当て", {"role": "manager", "name": "renamed", "session_id": "M-1"}, to="W-7", assignment=1)
        self.assertPosted(renamed, [a1], True, "名前は比べない")
        other_manager = header("割り当て", {"role": "manager", "name": "mgr", "session_id": "M-2"}, to="W-7", assignment=1)
        self.assertPosted(other_manager, [a1], True, "管理のセッションの種類は投稿者の ID を比べない (引き継ぎの後も二重に書かない)")

    def test_handover_compares_session_id_and_worker_kinds_are_not_checked(self):
        """`引き継ぎ` は投稿者のセッション ID も比べる。作業のセッションの種類は既投稿を確認しない (渡されたら ValueError)。"""
        h1 = header("引き継ぎ", {"role": "manager", "name": "mgr", "session_id": "M-2"})
        h2 = header("引き継ぎ", {"role": "manager", "name": "mgr", "session_id": "M-3"})
        self.assertPosted(h1, [h1], True)
        self.assertPosted(h2, [h1], False, "別の管理のセッションの引き継ぎは投稿する")
        d1 = header("着手の宣言", WORKER)
        with self.assertRaises(ValueError):
            comments.already_posted(comments.parse_header(d1), self.own(d1))
        self.assertPosted(header("依存の解消", {"role": "manager", "name": "mgr", "session_id": "M-3"}),
                          [header("依存の待機", blockers=[OTHER]), header("依存の解消")], True, "依存の解消は投稿者の ID を比べない")
        s1 = header("停滞", to="W-7", assignment=1, stuck_state="idle-no-progress")
        self.assertPosted(header("停滞", {"role": "manager", "name": "mgr", "session_id": "M-3"}, to="W-7", assignment=1, stuck_state="idle-no-progress"),
                          [s1], True, "停滞も投稿者の ID を比べない")

    def test_declaration_id_distinguishes(self):
        go1 = header("開始可", to="W-7", assignment=1, declaration=1)
        self.assertPosted(header("開始可", to="W-7", assignment=1, declaration=2), [go1], False)
        self.assertPosted(go1, [go1], True)

    def test_wait_compares_with_latest_for_the_declaration(self):
        w_user = header("待機", to="W-7", assignment=1, declaration=1, waits=[{"kind": "利用者の回答"}])
        w_issue = header("待機", to="W-7", assignment=1, declaration=1, waits=[{"kind": "Issue", "issue": OTHER}])
        self.assertPosted(w_user, [w_user], True)
        self.assertPosted(w_issue, [w_user], False, "待機する理由が違えば投稿する")
        self.assertPosted(w_user, [w_user, w_issue], False, "前と同じ理由の待機に戻ったときも、最新と違えば投稿する")
        self.assertPosted(w_user, [w_issue, w_user], True, "最新と同じなら投稿しない")
        both = header("待機", to="W-7", assignment=1, declaration=1, waits=[{"kind": "利用者の回答"}, {"kind": "資源", "resource": "db"}])
        self.assertPosted(w_user, [both], False, "待機するものの一部が解けて残りを書いたときも投稿する")
        other_decl = header("待機", to="W-7", assignment=1, declaration=2, waits=[{"kind": "利用者の回答"}])
        self.assertPosted(w_user, [w_user, other_decl], True, "別の宣言への待機は比べる相手にしない")
        pr = header("待機", to="W-7", assignment=1, declaration=1, waits=[{"kind": "小さな PR", "issue": OTHER}])
        pr_made = header("待機", to="W-7", assignment=1, declaration=1, waits=[{"kind": "小さな PR", "issue": OTHER, "pr": PR9}])
        self.assertPosted(pr_made, [pr], False, "PR ができたら待機する相手が変わるので投稿する")

    def test_values_compare_by_meaning(self):
        """繰り返す値は順序を問わず、Issue の参照と PR の URL は owner/repo の大文字小文字を区別せずに比べる。"""
        ab = header("待機", to="W-7", assignment=1, declaration=1, waits=[{"kind": "利用者の回答"}, {"kind": "資源", "resource": "db"}])
        ba = header("待機", to="W-7", assignment=1, declaration=1, waits=[{"kind": "資源", "resource": "db"}, {"kind": "利用者の回答"}])
        self.assertPosted(ba, [ab], True, "待機するものの順序が違っても同じ")
        w56 = header("依存の待機", blockers=[OTHER, f"{REPO}#6"])
        w65 = header("依存の待機", blockers=[f"{REPO.upper()}#6", OTHER])
        self.assertPosted(w65, [w56], True, "待機する Issue の順序と owner/repo の大文字小文字が違っても同じ")
        req = header("依頼", to="W-7", assignment=1, request_kind="本文の追記", pr=PR9)
        upper = header("依頼", to="W-7", assignment=1, request_kind="本文の追記", pr=PR9.replace(REPO, REPO.upper()))
        self.assertPosted(upper, [req], True)
        self.assertPosted(header("依頼", to="W-7", assignment=1, request_kind="本文の追記", pr=PR10), [req], False)

    def test_dependency_wait_and_resolution(self):
        wait5 = header("依存の待機", blockers=[OTHER])
        wait56 = header("依存の待機", blockers=[OTHER, f"{REPO}#6"])
        done = header("依存の解消")
        self.assertPosted(wait5, [wait5], True)
        self.assertPosted(wait56, [wait5], False, "待機する Issue が違えば投稿する")
        self.assertPosted(wait5, [wait5, done], False, "間に依存の解消があれば投稿する")
        self.assertPosted(done, [wait5], False)
        self.assertPosted(done, [wait5, done], True)
        self.assertPosted(done, [wait5, done, wait5], False, "2 度目の Blocked の後の依存の解消は投稿する")
        self.assertPosted(done, [done], True, "依存の待機が無ければ、全部のコメントと比べる")

    def test_stuck_once_per_assignment_and_value(self):
        s1 = header("停滞", to="W-7", assignment=1, stuck_state="idle-no-progress")
        s2 = header("停滞", to="W-7", assignment=1, stuck_state="deadline-passed")
        self.assertPosted(s1, [s1, header("割り当て", to="W-7", assignment=1), s2], True, "間に別のコメントがあっても投稿しない")
        self.assertPosted(s2, [s1], False)
        self.assertPosted(header("停滞", to="W-7", assignment=2, stuck_state="idle-no-progress"), [s1], False)

    def test_release_request_and_report(self):
        rel = header("解放", to="W-7", assignment=1, release_reason="解除")
        self.assertPosted(rel, [rel], True)
        self.assertPosted(header("解放", to="W-7", assignment=1, release_reason="close"), [rel], False, "理由が違えば投稿する")
        req9 = header("依頼", to="W-7", assignment=1, request_kind="本文の追記", pr=PR9)
        self.assertPosted(header("依頼", to="W-7", assignment=1, request_kind="本文の追記", pr=PR10), [req9], False, "PR が違えば投稿する")
        self.assertPosted(req9, [req9], True)
        small = header("依頼", to="W-7", assignment=1, request_kind="小さな PR", waiting_issue=OTHER, waiting_declaration=777)
        small2 = header("依頼", to="W-7", assignment=1, request_kind="小さな PR", waiting_issue=f"{REPO}#8", waiting_declaration=778)
        self.assertPosted(small2, [small], False, "2 つの Issue からの依頼は別")
        self.assertPosted(header("依頼", to="W-7", assignment=1, request_kind="小さな PR", waiting_issue=OTHER, waiting_declaration=777, previous_pr=PR9),
                          [small], False, "作り直しの依頼は別")


class PostTest(FakeGhCase):

    def _setup(self, existing_bodies, posted_id=99):
        nodes = [_comment(n, body) for n, body in enumerate(existing_bodies, 1)]
        data = fixture_json("issue-comments-ok")
        c = data["data"]["repository"]["issue"]["comments"]
        c["nodes"], c["pageInfo"] = nodes, {"hasNextPage": False, "endCursor": None}
        self.responses([USER_ENTRY, {"substring": "query IssueComments", "stdout": data},
                        {"prefix": ["issue", "comment"], "stdout": f"{ISSUE3}#issuecomment-{posted_id}\n"}])

    def test_posts_with_header_and_body(self):
        self._setup(["u1 latency 0"])
        result = comments.post(ISSUE3, "manager", "mgr", "M-1", "割り当て", {"to": "W-7", "assignment": 1}, "理由を書く\n2 行目")
        self.assertEqual(result, {"status": "ok", "posted": True, "database_id": 99, "url": f"{ISSUE3}#issuecomment-99",
                                  "header": header("割り当て", to="W-7", assignment=1)})
        call = self.recorded_full()[2]
        self.assertEqual(call["args"], ["issue", "comment", ISSUE3, "--body-file", "-"], "本文は標準入力で渡す")
        self.assertEqual(call["stdin"], header("割り当て", to="W-7", assignment=1) + "\n\n理由を書く\n2 行目")

    def test_does_not_post_when_already_posted(self):
        """同じ出来事への同じコメントが既にあれば投稿しない (冪等)。"""
        self._setup([header("割り当て", to="W-7", assignment=1) + "\n\n前の本文"])
        result = comments.post(ISSUE3, "manager", "mgr", "M-1", "割り当て", {"to": "W-7", "assignment": 1}, "理由")
        self.assertEqual((result["status"], result["posted"], result["database_id"]), ("ok", False, 1))
        self.assertEqual([c["args"][:2] for c in self.recorded_full()], [["api", "user"], ["api", "graphql"]], "issue comment を実行しない")

    def test_other_author_does_not_count(self):
        """Covers AE28. 投稿者が違うコメントは既投稿の確認にも数えない。"""
        nodes = [_comment(1, header("割り当て", to="W-7", assignment=1), author="someone-else")]
        data = fixture_json("issue-comments-ok")
        data["data"]["repository"]["issue"]["comments"]["nodes"] = nodes
        self.responses([USER_ENTRY, {"substring": "query IssueComments", "stdout": data},
                        {"prefix": ["issue", "comment"], "stdout": f"{ISSUE3}#issuecomment-99\n"}])
        self.assertTrue(comments.post(ISSUE3, "manager", "mgr", "M-1", "割り当て", {"to": "W-7", "assignment": 1}, "理由")["posted"])

    def test_worker_kinds_post_without_checking(self):
        """作業のセッションの種類は、同じ先頭行のコメントが既にあっても投稿する (一覧も読まない)。"""
        self.responses([{"prefix": ["issue", "comment"], "stdout": f"{ISSUE3}#issuecomment-99\n"}])
        result = comments.post(ISSUE3, "worker", "worker 1", "W-7", "宣言の更新", {}, "資源を足した")
        self.assertEqual((result["status"], result["posted"], result["database_id"]), ("ok", True, 99))
        self.assertEqual([c["args"][:2] for c in self.recorded_full()], [["issue", "comment"]], "api user も一覧も読まない")

    def test_bad_values_do_not_run_gh(self):
        result = comments.post(ISSUE3, "manager", "mgr", "M-1", "解放", {"to": "W-7", "assignment": 1, "release_reason": "気分"}, "")
        self.assertEqual(result["status"], "error")
        self.assertEqual(self.recorded(), [])

    def test_list_failure_does_not_post(self):
        self.responses([USER_ENTRY, {"substring": "query IssueComments", "stdout": "", "stderr": "GraphQL: Could not resolve", "exit": 1}])
        result = comments.post(ISSUE3, "manager", "mgr", "M-1", "割り当て", {"to": "W-7", "assignment": 1}, "理由")
        self.assertEqual(result["status"], "error")
        self.assertEqual([c["args"][:2] for c in self.recorded_full()], [["api", "user"], ["api", "graphql"]], "既投稿を確認できなければ投稿しない")

    def test_post_failure(self):
        nodes = []
        data = fixture_json("issue-comments-ok")
        data["data"]["repository"]["issue"]["comments"]["nodes"] = nodes
        self.responses([USER_ENTRY, {"substring": "query IssueComments", "stdout": data},
                        {"prefix": ["issue", "comment"], "stdout": "", "stderr": "GraphQL: Resource not accessible", "exit": 1}])
        result = comments.post(ISSUE3, "manager", "mgr", "M-1", "割り当て", {"to": "W-7", "assignment": 1}, "理由")
        self.assertEqual(result["status"], "error")
        self.assertIn("not accessible", result["message"])


class CliTest(FakeGhCase):

    def test_parse(self):
        code, out, _ = cli("comment", "parse", "--line", header("開始可", to="W-7", assignment=1, declaration=5))
        self.assertEqual((code, out["status"], out["header"]["kind"], out["header"]["values"]["declaration"]), (0, "ok", "開始可", 5))
        self.assertEqual(self.recorded(), [])
        code, out, _ = cli("comment", "parse", "--line", "u1 latency 0")
        self.assertEqual((code, out["status"], out["header"]), (0, "ok", None))

    def test_list(self):
        data = fixture_json("issue-comments-ok")
        self.responses([USER_ENTRY, {"substring": "query IssueComments", "stdout": data}])
        code, out, _ = cli("comment", "list", "--issue", f"{REPO}#3")
        self.assertEqual((code, out["status"], len(out["comments"]), out["excluded"], out["errors"]), (0, "ok", 10, 0, []))

    def test_post_with_values(self):
        data = fixture_json("issue-comments-ok")
        data["data"]["repository"]["issue"]["comments"]["nodes"] = []
        self.responses([USER_ENTRY, {"substring": "query IssueComments", "stdout": data},
                        {"prefix": ["issue", "comment"], "stdout": f"{ISSUE3}#issuecomment-99\n"}])
        code, out, _ = cli("comment", "post", "--issue", ISSUE3, "--role", "manager", "--name", "mgr", "--session-id", "M-1", "--kind", "待機",
                           "--to", "W-7", "--assignment", "1", "--declaration", "5", "--reason", "利用者の回答", "--reason", f"小さな PR {OTHER} PR {PR9}",
                           "--body-file", "-", stdin="本文\n")
        self.assertEqual((code, out["status"], out["posted"], out["database_id"]), (0, "ok", True, 99))
        stdin = self.recorded_full()[2]["stdin"]
        self.assertEqual(stdin.split("\n")[0], header("待機", to="W-7", assignment=1, declaration=5,
                                                      waits=[{"kind": "利用者の回答"}, {"kind": "小さな PR", "issue": OTHER, "pr": PR9}]))
        self.assertTrue(stdin.endswith("\n\n本文\n"))

    def test_post_small_pr_request_and_dependency_wait(self):
        data = fixture_json("issue-comments-ok")
        data["data"]["repository"]["issue"]["comments"]["nodes"] = []
        self.responses([USER_ENTRY, {"substring": "query IssueComments", "stdout": data}, {"prefix": ["issue", "comment"], "stdout": f"{ISSUE3}#issuecomment-99\n"}])
        code, out, _ = cli("comment", "post", "--issue", ISSUE3, "--role", "manager", "--name", "mgr", "--session-id", "M-1", "--kind", "依頼",
                           "--to", "W-7", "--assignment", "1", "--request-kind", "小さな PR", "--waiting-issue", OTHER, "--waiting-declaration", "777",
                           "--previous-pr", PR9, "--body", "理由")
        self.assertEqual((code, out["status"], out["posted"]), (0, "ok", True))
        self.assertEqual(out["header"], header("依頼", to="W-7", assignment=1, request_kind="小さな PR", waiting_issue=OTHER, waiting_declaration=777, previous_pr=PR9))
        self.responses([USER_ENTRY, {"substring": "query IssueComments", "stdout": data}, {"prefix": ["issue", "comment"], "stdout": f"{ISSUE3}#issuecomment-100\n"}])
        code, out, _ = cli("comment", "post", "--issue", ISSUE3, "--role", "manager", "--name", "mgr", "--session-id", "M-1", "--kind", "依存の待機",
                           "--blocker", OTHER, "--blocker", f"{REPO}#6", "--body", "理由")
        self.assertEqual(out["header"], header("依存の待機", blockers=[OTHER, f"{REPO}#6"]))

    def test_post_rejects_bad_values_without_gh(self):
        code, out, _ = cli("comment", "post", "--issue", ISSUE3, "--role", "worker", "--name", "w", "--session-id", "W-1", "--kind", "割り当て",
                           "--to", "W-7", "--assignment", "1", "--body", "x")
        self.assertEqual((code, out["status"], out["errors"][0]["key"]), (0, "error", "header"))
        self.assertEqual(self.recorded(), [])
        code, out, _ = cli("comment", "post", "--issue", ISSUE3, "--role", "manager", "--name", "m", "--session-id", "M-1", "--kind", "待機",
                           "--to", "W-7", "--assignment", "1", "--declaration", "5", "--reason", "謎 x", "--body", "x")
        self.assertEqual((code, out["status"], out["errors"][0]["key"]), (0, "error", "header"))


class DocTest(unittest.TestCase):

    def test_doc_lists_every_kind_and_value(self):
        with open(_DOC, encoding="utf-8") as f:
            doc = f.read()
        for kind in comments.MANAGER_KINDS + comments.WORKER_KINDS:
            self.assertIn(f"`{kind}`", doc, f"種類 {kind} が文書に無い")
        for word in comments.VALUE_WORDS:
            self.assertIn(f"`{word} ", doc, f"値の見出し語 {word} が文書に無い")
        for reason in comments.RELEASE_REASONS:
            self.assertIn(f"`{reason}`", doc)
        for kind in comments.REQUEST_KINDS:
            self.assertIn(f"`{kind}`", doc)


if __name__ == "__main__":
    unittest.main()
