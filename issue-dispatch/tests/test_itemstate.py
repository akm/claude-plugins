"""項目の状態 (itemstate) のテスト。導出は gh を実行しないので、項目は合成して渡す (コメントの先頭行は comments.format_header で作る)。
CLI のテストは偽の gh (tests/fake-gh) と固定データで動く。場面はテストの名前に書く (計画の U13)。"""

import json
import os
import subprocess
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.join(_HERE, "..", "scripts")
sys.path.insert(0, _SCRIPTS)
sys.path.insert(0, _HERE)

from issue_dispatch import comments, config, itemstate  # noqa: E402
from test_project import FakeGhCase, fixture_json  # noqa: E402

_CLI = os.path.join(_SCRIPTS, "issue_dispatch.py")
_DOC = os.path.join(_HERE, "..", "skills", "issue-dispatch", "references", "flow.md")
A = "akm/issue-dispatch-verify-a"
A1, A2, A9 = f"{A}#1", f"{A}#2", f"{A}#9"
LOGIN = "akm"
W7, M1 = "W-7", "M-1"
PR9 = f"https://github.com/{A}/pull/9"
PR10 = f"https://github.com/{A}/pull/10"
PROJECT_NUMBER = 3
_T = ["2026-10-20T00:00:00Z"]


def t(minutes):
    """基準から minutes 分後の時刻 (ISO 8601、UTC)。"""
    return f"2026-10-20T{minutes // 60:02d}:{minutes % 60:02d}:00Z"


def mcomment(kind, values=None, at=None, cid=None, body="", role="manager", name="mgr", sid=M1, author=LOGIN):
    """先頭行付きのコメント (project.items の comments の要素の形)。"""
    line = comments.format_header(role, name, sid, kind, values or {})
    return {"id": f"IC_{cid}", "database_id": cid, "url": f"https://github.com/{A}/issues/9#issuecomment-{cid}",
            "created_at": at, "author": author, "body": f"{line}\n\n{body}" if body else line}


def wcomment(kind, values=None, at=None, cid=None, body="", name="worker 1", sid=W7, author=LOGIN):
    return mcomment(kind, values, at, cid, body, role="worker", name=name, sid=sid, author=author)


def decl_body(files=(("src/a.py", None),), resources=(), split=False):
    obj = {"files": [{"path": p, "units": u} for p, u in files], "resources": list(resources),
           "split": {"needed": True, "reason": "大きい", "remaining": "残り", "blocked_by": []} if split else {"needed": False, "reason": ""}}
    return "```json\n" + json.dumps(obj, ensure_ascii=False) + "\n```"


def make_item(key=A9, state="OPEN", status="In Progress", session_field=W7, comments_=(), events=(), prs=(), labels=(), assignees=("akm",),
              body_edits=(), position=1, blocked_by=()):
    return {"item_id": "I9", "position": position, "key": key, "repo": key.split("#")[0], "number": int(key.split("#")[1]),
            "url": f"https://github.com/{key.replace('#', '/issues/')}", "state": state, "created_at": t(0), "author": "akm",
            "status": {"name": status, "option_id": "o", "updated_at": t(1)} if status else None,
            "fields": {"Agent session ID": {"text": session_field, "updated_at": t(1)}} if session_field is not None else {},
            "assignees": list(assignees), "labels": list(labels), "blocked_by": list(blocked_by), "body_edits": list(body_edits),
            "prs": list(prs), "comments": sorted(comments_, key=lambda c: c["created_at"]), "events": sorted(events, key=lambda e: e["at"])}


def ref_pr(url, created_at, state="OPEN", draft=False, merged=False, author=LOGIN, base_ref="main"):
    return {"number": int(url.rsplit("/", 1)[1]), "url": url, "state": state, "draft": draft, "merged": merged, "created_at": created_at,
            "merged_at": None, "closed_at": None, "author": author, "base_ref": base_ref}


def observed(url, state="OPEN", draft=False, merged=False, issues=(A9,), author=LOGIN, base_ref="main", created_at=None):
    """issues.observe_pr の結果 (pr_states の値) の形。"""
    return {"status": "ok", "author": author, "pr": {"url": url, "state": state, "draft": draft, "merged": merged, "base_ref": base_ref,
                                                      "created_at": created_at or t(20), "issues": [{"key": k, "state": "OPEN"} for k in issues]}}


ASSIGN1 = mcomment("割り当て", {"to": W7, "assignment": 1}, t(10), 100)
ASSIGN2 = mcomment("割り当て", {"to": W7, "assignment": 2}, t(200), 200)


class AssignmentTest(unittest.TestCase):

    def test_no_assignment_comment_means_not_assigned_even_with_field(self):
        """コメント `割り当て` が無ければ、フィールドに ID があっても割り当て中ではない (出どころはコメント。KTD19)。"""
        s = itemstate.derive(make_item(), LOGIN, {}, PROJECT_NUMBER)
        self.assertIsNone(s["assignment"])
        self.assertFalse(s["assigned"])

    def test_latest_assignment_comment_is_current(self):
        """今の割り当ては最新の `割り当て` (宛先と番号)。前の割り当ての `解放` は数えない。"""
        item = make_item(comments_=[ASSIGN1, mcomment("解放", {"to": W7, "assignment": 1, "release_reason": "解除"}, t(20), 101), ASSIGN2])
        s = itemstate.derive(item, LOGIN, {}, PROJECT_NUMBER)
        self.assertEqual((s["assignment"]["to"], s["assignment"]["number"], s["assignment"]["comment_id"]), (W7, 2, 200))
        self.assertIsNone(s["release"])
        self.assertTrue(s["assigned"])

    def test_release_with_current_number_ends_assignment(self):
        """今の番号の `解放` があれば割り当ては終わり (理由と時刻を返す)。"""
        item = make_item(comments_=[ASSIGN1, mcomment("解放", {"to": W7, "assignment": 1, "release_reason": "close"}, t(20), 101)], state="CLOSED")
        s = itemstate.derive(item, LOGIN, {}, PROJECT_NUMBER)
        self.assertEqual(s["release"]["reason"], "close")
        self.assertEqual(s["end"], {"kind": "released", "at": t(20), "reason": "close"})
        self.assertFalse(s["assigned"])

    def test_comments_by_other_authors_are_ignored(self):
        """書き手がトークンのログインと違う先頭行のコメントは、この仕組みのコメントとして扱わない (R6)。"""
        item = make_item(comments_=[mcomment("割り当て", {"to": W7, "assignment": 1}, t(10), 100, author="someone")])
        self.assertIsNone(itemstate.derive(item, LOGIN, {}, PROJECT_NUMBER)["assignment"])

    def test_status_todo_does_not_end_assignment(self):
        """Status だけの `Todo`・`Done` は終わりでも reopen でもない (KTD19)。"""
        item = make_item(status="Todo", comments_=[ASSIGN1])
        s = itemstate.derive(item, LOGIN, {}, PROJECT_NUMBER)
        self.assertTrue(s["assigned"])
        self.assertIsNone(s["end"])


class PrTest(unittest.TestCase):

    def test_pr_report_url_is_current_pr(self):
        """今の割り当ての PR は、今の割り当ての最新の `PR の報告` の URL の PR。"""
        item = make_item(comments_=[ASSIGN1, wcomment("PR の報告", None, t(30), 300, body=PR9), wcomment("PR の報告", None, t(40), 301, body=PR10)],
                         prs=[ref_pr(PR9, t(25))])
        s = itemstate.derive(item, LOGIN, {PR9: observed(PR9), PR10: observed(PR10)}, PROJECT_NUMBER)
        self.assertEqual((s["pr"]["url"], s["pr"]["source"], s["pr"]["closing"]), (PR10, "report", True))

    def test_pr_report_without_closing_reference(self):
        """報告の PR が Issue を閉じる参照を持たなければ closing は偽 (本文の追記を頼む材料。In review にしない)。"""
        item = make_item(comments_=[ASSIGN1, wcomment("PR の報告", None, t(30), 300, body=PR9)])
        s = itemstate.derive(item, LOGIN, {PR9: observed(PR9, issues=())}, PROJECT_NUMBER)
        self.assertEqual((s["pr"]["url"], s["pr"]["closing"]), (PR9, False))

    def test_pr_report_of_other_author_is_ignored_then_reference_is_used(self):
        """`PR の報告` の PR の作者がログインと違えば無いものとし、閉じる参照の PR (作者がログイン、作成が割り当ての後) を使う。"""
        item = make_item(comments_=[ASSIGN1, wcomment("PR の報告", None, t(30), 300, body=PR10)], prs=[ref_pr(PR9, t(25))])
        s = itemstate.derive(item, LOGIN, {PR10: observed(PR10, author="other")}, PROJECT_NUMBER)
        self.assertEqual((s["pr"]["url"], s["pr"]["source"], s["pr"]["closing"]), (PR9, "reference", True))

    def test_reference_pr_before_assignment_or_by_other_author_is_not_counted(self):
        """前の割り当ての PR (作成が今の `割り当て` より前) と、作者が違う PR は数えない。候補が複数なら作成が最新のもの。"""
        item = make_item(comments_=[ASSIGN2], prs=[ref_pr(PR9, t(25), merged=True, state="MERGED"), ref_pr(PR10, t(210), author="other"),
                                                   ref_pr(f"https://github.com/{A}/pull/11", t(220)), ref_pr(f"https://github.com/{A}/pull/12", t(230), draft=True)])
        s = itemstate.derive(item, LOGIN, {}, PROJECT_NUMBER)
        self.assertEqual(s["pr"]["url"], f"https://github.com/{A}/pull/12")

    def test_pr_unreadable_is_reported_as_problem(self):
        """`PR の報告` の PR が読めなければ、PR は無いものとせず、読めなかったことを problems で返し、閉じる参照の PR には戻らない。"""
        item = make_item(comments_=[ASSIGN1, wcomment("PR の報告", None, t(30), 300, body=PR9)], prs=[ref_pr(PR10, t(25))])
        s = itemstate.derive(item, LOGIN, {PR9: {"status": "error", "message": "HTTP 502"}}, PROJECT_NUMBER)
        self.assertEqual((s["pr"], [p["what"] for p in s["problems"]]), (None, ["pr-unreadable"]))


class EndTest(unittest.TestCase):

    def _closed(self, prs=(), pr_states=None, comments_=()):
        item = make_item(state="CLOSED", status="Done", comments_=[ASSIGN1, *comments_], prs=list(prs),
                         events=[{"type": "ClosedEvent", "at": t(50), "state_reason": "COMPLETED", "closer_pr": None}])
        return itemstate.derive(item, LOGIN, pr_states or {}, PROJECT_NUMBER)

    def test_close_with_merged_pr_is_normal_end(self):
        """進行中でない Issue (今の割り当ての PR がマージ済み) の close は正常な終わり。"""
        s = self._closed(prs=[ref_pr(PR9, t(25), state="MERGED", merged=True)])
        self.assertEqual((s["in_progress"], s["end"], s["assigned"]), (False, {"kind": "normal", "at": t(50)}, False))

    def test_close_with_ready_pr_not_merged_is_normal_end(self):
        """ready for review の後の close は、PR がマージされていなくても正常な終わり (KD9)。"""
        s = self._closed(prs=[ref_pr(PR9, t(25), state="OPEN", draft=False)])
        self.assertEqual(s["end"]["kind"], "normal")

    def test_close_with_closed_unmerged_non_draft_pr_is_normal_end(self):
        """マージされずに閉じた PR は、draft でなければ ready for review と読む (利用者が決めた)。"""
        s = self._closed(prs=[ref_pr(PR9, t(25), state="CLOSED", draft=False)])
        self.assertEqual(s["end"]["kind"], "normal")

    def test_close_in_progress_keeps_assignment(self):
        """進行中 (PR が無い・draft) の Issue の close は正常な終わりではなく、割り当て中のまま (利用者の答えを待つ。R21)。"""
        for prs in ([], [ref_pr(PR9, t(25), draft=True)]):
            s = self._closed(prs=prs)
            self.assertEqual((s["in_progress"], s["end"], s["assigned"]), (True, None, True), prs)

    def test_close_with_previous_assignment_merged_pr_is_in_progress(self):
        """reopen の後の割り当ての Issue を手で閉じても、前の割り当てのマージ済みの PR では正常な終わりにしない。"""
        item = make_item(state="CLOSED", comments_=[ASSIGN2], prs=[ref_pr(PR9, t(25), state="MERGED", merged=True)],
                         events=[{"type": "ClosedEvent", "at": t(250), "state_reason": "COMPLETED", "closer_pr": None}])
        s = itemstate.derive(item, LOGIN, {}, PROJECT_NUMBER)
        self.assertEqual((s["pr"], s["in_progress"], s["end"]), (None, True, None))

    def test_reopen_after_end_is_detected_and_reopen_while_pending_is_not(self):
        """終わった後の `ReopenedEvent` は reopen。終わる前 (進行中の close の後) の reopen は、終わった後の reopen ではない。"""
        ended = make_item(state="OPEN", status="Done", comments_=[ASSIGN1], prs=[ref_pr(PR9, t(25), state="MERGED", merged=True)],
                          events=[{"type": "ClosedEvent", "at": t(50), "state_reason": "COMPLETED", "closer_pr": 9}, {"type": "ReopenedEvent", "at": t(60)}])
        s = itemstate.derive(ended, LOGIN, {}, PROJECT_NUMBER)
        self.assertEqual((s["end"]["kind"], s["reopened"]), ("normal", {"at": t(60)}), "閉じた時点で正常な終わり。reopen は終わった後")
        pending = make_item(state="OPEN", status="Done", comments_=[ASSIGN1],
                            events=[{"type": "ClosedEvent", "at": t(50), "state_reason": "COMPLETED", "closer_pr": None}, {"type": "ReopenedEvent", "at": t(60)}])
        s = itemstate.derive(pending, LOGIN, {}, PROJECT_NUMBER)
        self.assertEqual((s["end"], s["reopened"], s["assigned"]), (None, None, True))

    def test_reopened_issue_with_pr_created_after_close_is_not_ended(self):
        """開いている Issue で、PR が close より後に作られたなら、その close は進行中の close (正常な終わりではない)。"""
        item = make_item(state="OPEN", comments_=[ASSIGN1], prs=[ref_pr(PR9, t(70), state="OPEN", draft=False)],
                         events=[{"type": "ClosedEvent", "at": t(50), "state_reason": "COMPLETED", "closer_pr": None}, {"type": "ReopenedEvent", "at": t(60)}])
        s = itemstate.derive(item, LOGIN, {}, PROJECT_NUMBER)
        self.assertEqual((s["end"], s["reopened"], s["assigned"]), (None, None, True))

    def test_released_then_reopened(self):
        """`解放` (理由 close) の後の `ReopenedEvent` も終わった後の reopen。"""
        item = make_item(state="OPEN", comments_=[ASSIGN1, mcomment("解放", {"to": W7, "assignment": 1, "release_reason": "close"}, t(55), 101)],
                         events=[{"type": "ClosedEvent", "at": t(50), "state_reason": "COMPLETED", "closer_pr": None}, {"type": "ReopenedEvent", "at": t(60)}])
        s = itemstate.derive(item, LOGIN, {}, PROJECT_NUMBER)
        self.assertEqual((s["end"]["kind"], s["reopened"]["at"]), ("released", t(60)))


DECL1 = wcomment("着手の宣言", None, t(12), 400, body=decl_body(resources=("db",)))


def _go(decl_id, at, cid):
    return mcomment("開始可", {"to": W7, "assignment": 1, "declaration": decl_id}, at, cid)


def _wait(decl_id, waits, at, cid):
    return mcomment("待機", {"to": W7, "assignment": 1, "declaration": decl_id, "waits": waits}, at, cid)


def _status_event(status, at, previous="In Progress", project=PROJECT_NUMBER):
    return {"type": "ProjectV2ItemStatusChangedEvent", "at": at, "status": status, "previous_status": previous, "was_automated": False, "project_number": project}


def stage_of(*cs, status="In Progress", events=()):
    item = make_item(status=status, comments_=[ASSIGN1, *cs], events=list(events))
    return itemstate.derive(item, LOGIN, {}, PROJECT_NUMBER)["declaration"]


class DeclarationStageTest(unittest.TestCase):

    def test_no_declaration(self):
        """宣言のコメントが無い項目は、判定の要る宣言が無く段階も無い (何も求めず作業のセッションの宣言を待つ)。"""
        d = stage_of()
        self.assertEqual((d["judged"], d["stage"], d["held"]), (None, None, []))

    def test_declaration_before_assignment_is_ignored(self):
        """今の `割り当て` より前の宣言は使わない (前の割り当てのときの宣言)。"""
        d = stage_of(wcomment("着手の宣言", None, t(5), 399, body=decl_body()))
        self.assertIsNone(d["judged"])

    def test_declaration_without_result_is_undecided(self):
        d = stage_of(DECL1)
        self.assertEqual((d["judged"]["comment_id"], d["judged"]["update_kind"], d["stage"], d["held"]), (400, "initial", "undecided", []))

    def test_declaration_with_go_is_in_work_and_holds_resources(self):
        d = stage_of(DECL1, _go(400, t(13), 500))
        self.assertEqual((d["stage"], d["go"]["comment_id"], d["held"], d["manager_blocked"]), ("go", 500, ["db"], False))

    def test_waiting_for_user_answer_does_not_make_blocked_managers(self):
        """理由が `利用者の答え` だけの `待機` では Status を変えないので、Status が `Blocked` でも管理のセッションのものではない。"""
        d = stage_of(DECL1, _wait(400, [{"kind": "利用者の答え"}], t(13), 500), status="Blocked", events=[_status_event("Blocked", t(14))])
        self.assertEqual((d["stage"], d["wait"]["reasons"], d["manager_blocked"], d["return_status"], d["own_blockers"]),
                         ("waiting", [{"kind": "利用者の答え"}], False, None, []))

    def test_waiting_for_issue_with_blocked_status_after_wait_is_managers(self):
        """理由に `Issue` を含む `待機` の後に `Blocked` になった Status は管理のセッションのもの。戻り先は `In Progress`、自分が足した blockedBy は待つ Issue。"""
        d = stage_of(DECL1, _wait(400, [{"kind": "Issue", "issue": A2}], t(13), 500), status="Blocked", events=[_status_event("Blocked", t(14))])
        self.assertEqual((d["stage"], d["manager_blocked"], d["return_status"], d["own_blockers"], d["waiting_blockers"]), ("waiting", True, "In Progress", [A2], [A2]))

    def test_blocked_status_before_wait_is_users(self):
        """`Blocked` への変化が `待機` より前なら、利用者が付けたもの (時刻で見分ける。KTD19 の基準)。"""
        d = stage_of(DECL1, _wait(400, [{"kind": "Issue", "issue": A2}], t(13), 500), status="Blocked", events=[_status_event("Blocked", t(12))])
        self.assertEqual((d["manager_blocked"], d["return_status"]), (False, None))

    def test_blocked_status_of_other_project_is_not_counted(self):
        """別の Project の Status の出来事は見ない。"""
        d = stage_of(DECL1, _wait(400, [{"kind": "Issue", "issue": A2}], t(13), 500), status="Blocked", events=[_status_event("Blocked", t(14), project=99)])
        self.assertFalse(d["manager_blocked"])

    def test_go_after_wait_ends_waiting(self):
        """`待機` の後に `開始可` があれば作業中 (最新の判定の結果で決める)。Status が `Blocked` のままでも管理のセッションのものではない (戻し済みのはず)。"""
        d = stage_of(DECL1, _wait(400, [{"kind": "Issue", "issue": A2}], t(13), 500), _go(400, t(15), 501), status="Blocked", events=[_status_event("Blocked", t(14))])
        self.assertEqual((d["stage"], d["manager_blocked"], d["waiting_blockers"], d["own_blockers"]), ("go", False, [], [A2]),
                         "待っている blocker は無いが、自分が足した blocker として残る (`開始可` の後に外すため)")

    def test_own_blockers_include_waits_of_previous_declarations(self):
        """自分が足した blocker は、今の割り当てのすべての `待機` から導く (ファイルを変えた更新で判定の要る宣言が変わっても残る)。"""
        update = wcomment("宣言の更新", None, t(20), 401, body=decl_body(files=(("src/b.py", None),), resources=("db",)))
        d = stage_of(DECL1, _wait(400, [{"kind": "Issue", "issue": A2}], t(13), 500), _go(400, t(15), 501), update)
        self.assertEqual((d["judged"]["comment_id"], d["own_blockers"], d["waiting_blockers"]), (401, [A2], []))

    def test_small_pr_wait_reasons(self):
        d = stage_of(DECL1, _wait(400, [{"kind": "小さな PR", "issue": A2, "pr": PR10}], t(13), 500))
        self.assertEqual((d["stage"], d["wait"]["reasons"][0]["pr"], d["own_blockers"]), ("waiting", PR10, [A2]))

    def test_returned_declaration_and_its_rewrite(self):
        """`依頼` (宣言の書き直し) で差し戻された宣言は段階 returned。書き直した更新は、資源を外しただけでも判定の要る宣言になる。"""
        req = mcomment("依頼", {"to": W7, "assignment": 1, "request_kind": "宣言の書き直し", "declaration": 400}, t(13), 500)
        d = stage_of(DECL1, req)
        self.assertEqual((d["stage"], d["returned"]["comment_id"]), ("returned", 500))
        rewrite = wcomment("宣言の更新", None, t(14), 401, body=decl_body(resources=()))
        d = stage_of(DECL1, req, rewrite)
        self.assertEqual((d["judged"]["comment_id"], d["stage"]), (401, "undecided"))

    def test_resources_removed_only_update_is_not_judged(self):
        """`開始可` の後の、資源を外すだけの更新は判定の要る宣言にならない (持っている資源は減る)。"""
        update = wcomment("宣言の更新", None, t(14), 401, body=decl_body(resources=()))
        d = stage_of(DECL1, _go(400, t(13), 500), update)
        self.assertEqual((d["judged"]["comment_id"], d["stage"], d["held"]), (400, "go", []))

    def test_full_update_after_go_is_judged_and_keeps_held(self):
        """ファイルを変えた更新は判定の要る宣言 (未判定)。持っている資源は `開始可` の宣言のもののまま。"""
        update = wcomment("宣言の更新", None, t(14), 401, body=decl_body(files=(("src/b.py", None),), resources=("db",)))
        d = stage_of(DECL1, _go(400, t(13), 500), update)
        self.assertEqual((d["judged"]["comment_id"], d["judged"]["update_kind"], d["stage"], d["held"]), (401, "full", "undecided", ["db"]))

    def test_unparsable_declaration_is_judged_with_error(self):
        """JSON のコードブロックが読めない宣言も判定の要る宣言 (管理のセッションが差し戻す)。宣言は None で理由を持つ。"""
        bad = wcomment("着手の宣言", None, t(12), 400, body="```json\n{not json\n```")
        d = stage_of(bad)
        self.assertEqual((d["judged"]["comment_id"], d["judged"]["declaration"], d["stage"]), (400, None, "undecided"))
        self.assertTrue(d["judged"]["error"])

    def test_declaration_without_units_is_read(self):
        """units を省いた (ファイル全体を変える) 宣言は様式どおりなので、読める宣言として扱う (units は None)。"""
        body = "```json\n" + json.dumps({"files": [{"path": "src/app.ts"}], "resources": ["db"], "split": {"needed": False, "reason": ""}}) + "\n```"
        d = stage_of(wcomment("着手の宣言", None, t(12), 400, body=body))
        self.assertEqual((d["judged"]["error"], d["judged"]["declaration"]["files"]), (None, [{"path": "src/app.ts", "units": None, "kind": None}]))

    def test_declaration_paths_are_normalized_for_update_kind(self):
        """パスの綴りだけが違う (./src/a.py) 更新は同じファイルと数え、資源を外すだけなら判定の要る宣言にならない (declaration.parse と同じ正規化)。"""
        update = wcomment("宣言の更新", None, t(14), 401, body=decl_body(files=(("./src/a.py", None),), resources=()))
        d = stage_of(DECL1, _go(400, t(13), 500), update)
        self.assertEqual((d["judged"]["comment_id"], d["stage"], d["held"]), (400, "go", []))

    def test_declaration_with_shape_error_reports_parse_errors(self):
        """形の誤り (必須のキーが無い・パスがルートの外) は declaration.parse の errors を理由にする。"""
        body = "```json\n" + json.dumps({"files": [{"path": "../x"}], "resources": []}) + "\n```"
        d = stage_of(wcomment("着手の宣言", None, t(12), 400, body=body))
        self.assertIsNone(d["judged"]["declaration"])
        self.assertIn("split", d["judged"]["error"])

    def test_results_for_other_declaration_are_not_counted(self):
        """ほかの宣言 (ID が違う) への `開始可` は、判定の要る宣言の結果にしない。"""
        d = stage_of(DECL1, _go(399, t(13), 500))
        self.assertEqual(d["stage"], "undecided")


def _label_event(kind, name, at):
    return {"type": kind, "at": at, "label": name}


class ResourceUsageTest(unittest.TestCase):

    def test_labels_at_assignment_time_from_events(self):
        """ある時点のラベルは、その時点までの出来事を時刻の順に全部読んで求める (外して付け直したラベルは、付け直しが `割り当て` より前なら持つ)。"""
        events = [_label_event("LabeledEvent", "resource:db", t(1)), _label_event("UnlabeledEvent", "resource:db", t(2)),
                  _label_event("LabeledEvent", "resource:db", t(3)), _label_event("LabeledEvent", "resource:gpu", t(20)), _label_event("LabeledEvent", "bug", t(4))]
        item = make_item(labels=["resource:db", "resource:gpu", "bug"], comments_=[ASSIGN1], events=events)
        self.assertEqual(itemstate.labels_at(item, t(10)), {"resource:db", "bug"})
        s = itemstate.derive(item, LOGIN, {}, PROJECT_NUMBER)
        self.assertEqual(s["reserved"], ["db"], "`割り当て` の後に足した gpu は予約していない")

    def test_label_removed_before_assignment_is_not_reserved(self):
        events = [_label_event("LabeledEvent", "resource:db", t(1)), _label_event("UnlabeledEvent", "resource:db", t(2)),
                  _label_event("LabeledEvent", "resource:db", t(30))]
        item = make_item(labels=["resource:db"], comments_=[ASSIGN1], events=events)
        self.assertEqual(itemstate.derive(item, LOGIN, {}, PROJECT_NUMBER)["reserved"], [])

    def test_label_prefix_is_case_insensitive(self):
        """ラベルの名前は GitHub が大文字小文字を区別しないので、`Resource:DB` も資源 DB として予約に数える (名前はラベルの綴りのまま)。"""
        item = make_item(labels=["Resource:DB"], comments_=[ASSIGN1], events=[_label_event("LabeledEvent", "Resource:DB", t(1))])
        self.assertEqual(itemstate.resource_labels(["Resource:DB", "bug", "resource:"]), ["DB"])
        self.assertEqual(itemstate.derive(item, LOGIN, {}, PROJECT_NUMBER)["reserved"], ["DB"])

    def test_reserve_on_declare_label_is_not_reserved_at_assignment(self):
        """属性 reserve が on_declare の資源は、割り当てのときに予約しない。"""
        item = make_item(labels=["resource:db"], comments_=[ASSIGN1], events=[_label_event("LabeledEvent", "resource:db", t(1))])
        table = {"db": {"capacity": 1, "reserve": "on_declare", "when_busy": "wait", "release_undeclared": "ask"}}
        self.assertEqual(itemstate.derive(item, LOGIN, {}, PROJECT_NUMBER, attrs_table=table)["reserved"], [])

    def test_usage_from_states(self):
        """資源の使用 (資源 → 持つ項目) は、割り当て中の項目の予約と持っている資源から導く。終わった項目は持たない。待っている宣言の新しい資源は持たない。"""
        held_item = make_item(key=A1, labels=["resource:db"], comments_=[ASSIGN1, DECL1, _go(400, t(13), 500)], events=[_label_event("LabeledEvent", "resource:db", t(1))])
        waiting_item = make_item(key=A2, comments_=[ASSIGN1, wcomment("着手の宣言", None, t(12), 410, body=decl_body(resources=("gpu",))),
                                                     _wait(410, [{"kind": "資源", "resource": "gpu"}], t(13), 510)])
        ended_item = make_item(key=A9, state="CLOSED", labels=["resource:gpu"], comments_=[ASSIGN1, mcomment("解放", {"to": W7, "assignment": 1, "release_reason": "close"}, t(50), 101)],
                               events=[_label_event("LabeledEvent", "resource:gpu", t(1))])
        states = [itemstate.derive(i, LOGIN, {}, PROJECT_NUMBER) for i in (held_item, waiting_item, ended_item)]
        self.assertEqual(itemstate.resource_usage(states), {"db": [A1]})


class WorkCheckTest(unittest.TestCase):

    def test_work_check_fields_and_assignment(self):
        """フィールドが自分の ID か・自分宛ての今の割り当ての `割り当て` があるか・今の番号の `解放` が無いか。"""
        item = make_item(comments_=[ASSIGN1])
        c = itemstate.work_check(item, W7, LOGIN, {})
        self.assertEqual((c["field_is_mine"], c["assigned_to_me"], c["assignment"]["number"], c["released"], c["pending_requests"]), (True, True, 1, None, []))
        other = make_item(session_field="W-8", comments_=[mcomment("割り当て", {"to": "W-8", "assignment": 1}, t(10), 100)])
        c = itemstate.work_check(other, W7, LOGIN, {})
        self.assertEqual((c["field_is_mine"], c["assigned_to_me"]), (False, False))

    def test_work_check_release_of_current_number_only(self):
        """前の割り当ての `解放` は数えず、今の番号の `解放` だけを返す。"""
        item = make_item(comments_=[ASSIGN1, mcomment("解放", {"to": W7, "assignment": 1, "release_reason": "解除"}, t(20), 101), ASSIGN2])
        self.assertIsNone(itemstate.work_check(item, W7, LOGIN, {})["released"])
        item2 = make_item(comments_=[ASSIGN1, mcomment("解放", {"to": W7, "assignment": 1, "release_reason": "解除"}, t(20), 101)])
        self.assertEqual(itemstate.work_check(item2, W7, LOGIN, {})["released"]["reason"], "解除")

    def test_pending_requests_by_kind(self):
        """まだ行っていない `依頼`: 宣言の書き直しは後の宣言の更新で、本文の追記は PR の閉じる参照で、小さな PR は対応する `小さな PR の報告` で行ったとする。"""
        rewrite = mcomment("依頼", {"to": W7, "assignment": 1, "request_kind": "宣言の書き直し", "declaration": 400}, t(13), 500)
        append = mcomment("依頼", {"to": W7, "assignment": 1, "request_kind": "本文の追記", "pr": PR9}, t(14), 501)
        small = mcomment("依頼", {"to": W7, "assignment": 1, "request_kind": "小さな PR", "waiting_issue": A2, "waiting_declaration": 777}, t(15), 502)
        item = make_item(comments_=[ASSIGN1, DECL1, rewrite, append, small])
        c = itemstate.work_check(item, W7, LOGIN, {PR9: observed(PR9, issues=())})
        self.assertEqual([r["comment_id"] for r in c["pending_requests"]], [500, 501, 502])
        done = [wcomment("宣言の更新", None, t(16), 401, body=decl_body()),
                wcomment("小さな PR の報告", {"waiting_issue": A2, "waiting_declaration": 777}, t(17), 402, body=PR10)]
        c = itemstate.work_check(make_item(comments_=[ASSIGN1, DECL1, rewrite, append, small, *done]), W7, LOGIN, {PR9: observed(PR9)})
        self.assertEqual(c["pending_requests"], [])

    def test_request_to_other_session_or_previous_assignment_is_not_mine(self):
        req_other = mcomment("依頼", {"to": "W-8", "assignment": 1, "request_kind": "宣言の書き直し", "declaration": 400}, t(13), 500)
        req_prev = mcomment("依頼", {"to": W7, "assignment": 1, "request_kind": "宣言の書き直し", "declaration": 400}, t(13), 501)
        item = make_item(comments_=[ASSIGN1, req_other, req_prev, ASSIGN2])
        self.assertEqual(itemstate.work_check(item, W7, LOGIN, {})["pending_requests"], [])

    def test_third_party_edits_after_assignment(self):
        """`割り当て` より後の、トークンのログイン以外による本文の編集を返す (確認の対象かは呼び出し元が決める)。"""
        edits = [{"editor": "akm", "edited_at": t(0), "deleted_at": None}, {"editor": "someone", "edited_at": t(5), "deleted_at": None},
                 {"editor": "someone", "edited_at": t(15), "deleted_at": None}, {"editor": "akm", "edited_at": t(16), "deleted_at": None}]
        item = make_item(comments_=[ASSIGN1], body_edits=edits)
        self.assertEqual(itemstate.work_check(item, W7, LOGIN, {})["third_party_edits"], [{"editor": "someone", "edited_at": t(15)}])


class WorkHeldTest(unittest.TestCase):

    def test_held_items_with_stage_and_blocked_owner(self):
        """割り当て中の Issue (閉じて答えを待つものを含む) を返し、終わった Issue は返さない。宣言の段階と `Blocked` の書き手を添える。"""
        no_decl = make_item(key=A1, comments_=[ASSIGN1])
        waiting = make_item(key=A2, status="Blocked", comments_=[ASSIGN1, DECL1, _wait(400, [{"kind": "Issue", "issue": A1}], t(13), 500)],
                            events=[_status_event("Blocked", t(14))])
        pending_close = make_item(key=A9, state="CLOSED", status="Done", comments_=[ASSIGN1, DECL1, _go(400, t(13), 500)],
                                  events=[{"type": "ClosedEvent", "at": t(50), "state_reason": "COMPLETED", "closer_pr": None}])
        ended = make_item(key=f"{A}#4", state="CLOSED", comments_=[ASSIGN1], prs=[ref_pr(PR9, t(25), state="MERGED", merged=True)],
                          events=[{"type": "ClosedEvent", "at": t(50), "state_reason": "COMPLETED", "closer_pr": 9}])
        other = make_item(key=f"{A}#5", session_field="W-8", comments_=[mcomment("割り当て", {"to": "W-8", "assignment": 1}, t(10), 100)])
        held = itemstate.work_held([no_decl, waiting, pending_close, ended, other], W7, LOGIN, {}, PROJECT_NUMBER)
        self.assertEqual([h["key"] for h in held], [A1, A2, A9])
        self.assertEqual((held[0]["status"], held[0]["judged"], held[0]["has_go"], held[0]["has_wait"]), ("In Progress", None, False, False))
        self.assertEqual((held[1]["status"], held[1]["judged"], held[1]["has_go"], held[1]["has_wait"], held[1]["manager_blocked"]), ("Blocked", 400, False, True, True))
        self.assertEqual((held[2]["state"], held[2]["status"], held[2]["has_go"]), ("CLOSED", "Done", True))

    def test_in_review_item_reports_judged_declaration(self):
        """Status が `In review` でも、判定の要る宣言と `開始可` の有無を返す (ready for review の後の資源を足す更新)。"""
        update = wcomment("宣言の更新", None, t(30), 401, body=decl_body(resources=("db", "gpu")))
        item = make_item(status="In review", comments_=[ASSIGN1, DECL1, _go(400, t(13), 500), update])
        held = itemstate.work_held([item], W7, LOGIN, {}, PROJECT_NUMBER)
        self.assertEqual((held[0]["judged"], held[0]["has_go"], held[0]["update_kind"]), (401, False, "resources-only"))


def _blocker(key, state="OPEN"):
    return {"key": key, "url": f"https://github.com/{key.replace('#', '/issues/')}", "state": state}


def dep_wait(blockers, at, cid):
    return mcomment("依存の待ち", {"blockers": list(blockers)}, at, cid)


def dep_clear(at, cid):
    return mcomment("依存の解消", None, at, cid)


def dependency(item):
    state = itemstate.derive(item, LOGIN, {}, PROJECT_NUMBER)
    return itemstate.dependency_actions(item, state, LOGIN, PROJECT_NUMBER)


class DependencyBlockedTest(unittest.TestCase):
    """割り当ての無い項目の Ready ⇄ Blocked の再導出 (KTD7)。範囲は担当者が自分 1 人の項目で、Status が Ready か Blocked のもの。"""

    def test_ready_with_open_blocker_waits(self):
        """開いている blocker があれば、`依存の待ち` を書いてから `Blocked` にする (コメントが先)。"""
        item = make_item(status="Ready", session_field=None, blocked_by=[_blocker(A1), _blocker(A2, "CLOSED")])
        actions, reports = dependency(item)
        self.assertEqual([(a["kind"], a.get("comment_kind") or a.get("status")) for a in actions], [("comment", "依存の待ち"), ("set-status", "Blocked")])
        self.assertEqual((actions[0]["values"], reports), ({"blockers": [A1]}, []))

    def test_blocked_by_manager_returns_to_ready_when_blockers_close(self):
        """管理のセッションが書いた `Blocked` (最新が `依存の待ち`) は、blocker がすべて閉じたら `依存の解消` を書いてから `Ready` に戻す。"""
        item = make_item(status="Blocked", session_field=None, blocked_by=[_blocker(A1, "CLOSED")], comments_=[dep_wait([A1], t(10), 100)],
                         events=[_status_event("Blocked", t(11), previous="Ready")])
        actions, _ = dependency(item)
        self.assertEqual([(a["kind"], a.get("comment_kind") or a.get("status")) for a in actions], [("comment", "依存の解消"), ("set-status", "Ready")])

    def test_blocked_by_user_is_not_rewritten(self):
        """`依存の待ち` の無い `Blocked` (利用者が手で付けた) は、blocker が閉じていても書き換えない。"""
        item = make_item(status="Blocked", session_field=None, blocked_by=[_blocker(A1, "CLOSED")])
        self.assertEqual(dependency(item), ([], []))
        item = make_item(status="Blocked", session_field=None, blocked_by=[])
        self.assertEqual(dependency(item), ([], []))

    def test_blocked_with_open_blocker_stays(self):
        item = make_item(status="Blocked", session_field=None, blocked_by=[_blocker(A1)], comments_=[dep_wait([A1], t(10), 100)], events=[_status_event("Blocked", t(11))])
        self.assertEqual(dependency(item), ([], []))

    def test_todo_and_empty_status_are_not_touched(self):
        """Status が空の項目と `Todo` の項目は書き換えない (R1)。"""
        for status in (None, "Todo"):
            item = make_item(status=status, session_field=None, blocked_by=[_blocker(A1)])
            self.assertEqual(dependency(item), ([], []), status)

    def test_items_not_assigned_to_me_alone_are_out_of_scope(self):
        """担当者が自分 1 人でない項目は範囲の外 (KD25)。"""
        for assignees in ((), ("akm", "other"), ("other",)):
            item = make_item(status="Ready", session_field=None, blocked_by=[_blocker(A1)], assignees=assignees)
            self.assertEqual(dependency(item), ([], []), assignees)

    def test_interrupted_after_wait_comment_continues_to_blocked(self):
        """`依存の待ち` を書いた後に止まった (Status が `Ready` のまま、その後の Status の変化が無い) 項目は、続きの `Blocked` を書く。"""
        item = make_item(status="Ready", session_field=None, blocked_by=[_blocker(A1)], comments_=[dep_wait([A1], t(10), 100)])
        actions, reports = dependency(item)
        self.assertEqual(([(a["kind"], a["status"], a.get("continuation")) for a in actions], reports), ([("set-status", "Blocked", True)], []))

    def test_user_returned_to_ready_after_wait_is_reported_not_rewritten(self):
        """`依存の待ち` → `Blocked` の後に利用者が `Ready` に戻した (Status の変化がコメントより後) 項目は、書き換えずに人の変更として報告する。"""
        item = make_item(status="Ready", session_field=None, blocked_by=[_blocker(A1)], comments_=[dep_wait([A1], t(10), 100)],
                         events=[_status_event("Blocked", t(11), previous="Ready"), _status_event("Ready", t(12), previous="Blocked")])
        actions, reports = dependency(item)
        self.assertEqual((actions, [r["kind"] for r in reports]), ([], ["status-changed"]))

    def test_interrupted_after_clear_comment_continues_to_ready(self):
        item = make_item(status="Blocked", session_field=None, blocked_by=[_blocker(A1, "CLOSED")], comments_=[dep_wait([A1], t(10), 100), dep_clear(t(20), 101)],
                         events=[_status_event("Blocked", t(11), previous="Ready")])
        actions, _ = dependency(item)
        self.assertEqual([(a["kind"], a["status"], a.get("continuation")) for a in actions], [("set-status", "Ready", True)])

    def test_ended_assignment_counts_as_unassigned(self):
        """割り当てが終わった (正常な終わりの後に reopen された) 項目も、割り当ての無い項目として扱う。"""
        item = make_item(status="Ready", state="OPEN", blocked_by=[_blocker(A1)], comments_=[ASSIGN1], prs=[ref_pr(PR9, t(25), state="MERGED", merged=True)],
                         events=[{"type": "ClosedEvent", "at": t(50), "state_reason": "COMPLETED", "closer_pr": 9}, {"type": "ReopenedEvent", "at": t(60)}])
        actions, _ = dependency(item)
        self.assertEqual([a["kind"] for a in actions], ["comment", "set-status"])

    def test_human_blocked_by_on_assigned_item_is_reported(self):
        """`In Progress`・`In review` の項目に人が足した `blockedBy` (自分が足したものでない) は導出せず報告する。"""
        item = make_item(status="In Progress", blocked_by=[_blocker(A1), _blocker(A2)], comments_=[ASSIGN1, DECL1, _wait(400, [{"kind": "Issue", "issue": A2}], t(13), 500)])
        state = itemstate.derive(item, LOGIN, {}, PROJECT_NUMBER)
        self.assertEqual(itemstate.human_blocked_by(item, state), [A1])


def rec_with(items=None, questions=None, manager_state="active"):
    """記録 (record.json の形)。manager_state が None なら記録が無い (None を返す)。"""
    if manager_state is None:
        return None
    return {"project": "akm/3", "manager": {"id": M1, "name": "issue-dispatch akm/3/akm", "started_at": t(0), "state": manager_state, "stop_reason": None, "exchanges_since_input": 0},
            "sessions": {}, "items": items or {}, "opt_in_proposals": {}, "notices": {}, "questions": questions or {}}


def rec_item(intent_status="In Progress", reported=None, confirmed=None):
    return {"intent": {"session_id": W7, "session_title": "worker 1", "status": intent_status, "assignment": 1, "at": t(9)}, "notified_at": t(10),
            "resend_count": 0, "conflict_choice": None, "reported": reported or {}, "body_edit_confirmed_at": confirmed}


def turn_of(item, rec="default", config=None, diffs=(), workflows=None, pr_states=None):
    if rec == "default":
        rec = rec_with(items={A9: rec_item()})
    return itemstate.derive_turn([item], rec, LOGIN, M1, PROJECT_NUMBER, {}, pr_states or {}, list(diffs), workflows or {"Item reopened": True},
                                 config or {"third_party_edit_check": []})


def kinds(entries):
    return [e["kind"] for e in entries]


class AssignedScenesTest(unittest.TestCase):
    """割り当て中の項目の場面ごとの扱い (問い・続きの書き込み・報告)。"""

    def test_nothing_to_do_for_item_in_expected_state(self):
        out = turn_of(make_item(comments_=[ASSIGN1, DECL1, _go(400, t(13), 500)]))
        self.assertEqual((out["actions"], out["questions"], out["reports"], out["record_lost"]), ([], [], [], False))

    def test_close_in_progress_asks(self):
        """進行中の Issue の close は、止めるか reopen して続けるかを尋ねる。答えが出るまで割り当て中のまま、ほかの書き込みはしない。"""
        item = make_item(state="CLOSED", status="Done", comments_=[ASSIGN1, DECL1, _go(400, t(13), 500)],
                         events=[{"type": "ClosedEvent", "at": t(50), "state_reason": "COMPLETED", "closer_pr": None}])
        out = turn_of(item)
        self.assertEqual([(q["kind"], q["item"], q["options"]) for q in out["questions"]], [("close-in-progress", A9, ["stop", "reopen"])])
        self.assertEqual(out["actions"], [])

    def test_pending_question_is_not_asked_again_and_item_is_left_alone(self):
        """同じ項目と種類の未回答の問いがあれば尋ね直さず、その項目には手を付けない (pending に返す)。"""
        item = make_item(state="CLOSED", status="Done", comments_=[ASSIGN1],
                         events=[{"type": "ClosedEvent", "at": t(50), "state_reason": "COMPLETED", "closer_pr": None}])
        rec = rec_with(items={A9: rec_item()}, questions={"q1": {"item": A9, "kind": "close-in-progress", "options": ["stop", "reopen"], "asked_at": t(51), "answer": None, "answered_at": None}})
        out = turn_of(item, rec=rec)
        self.assertEqual((out["questions"], [p["question_id"] for p in out["pending"]]), ([], ["q1"]))

    def test_reopen_while_close_question_pending_withdraws_and_restores_status(self):
        """進行中の close の答えを待つ間に reopen されたら、問いを取り下げ、フィールドは空にせず、Status を導いた状態に戻す。"""
        item = make_item(state="OPEN", status="Done", comments_=[ASSIGN1, DECL1, _go(400, t(13), 500)],
                         events=[{"type": "ClosedEvent", "at": t(50), "state_reason": "COMPLETED", "closer_pr": None}, {"type": "ReopenedEvent", "at": t(60)}])
        rec = rec_with(items={A9: rec_item()}, questions={"q1": {"item": A9, "kind": "close-in-progress", "options": ["stop", "reopen"], "asked_at": t(51), "answer": None, "answered_at": None}})
        out = turn_of(item, rec=rec)
        self.assertEqual([(a["kind"], a.get("question_id") or a.get("status")) for a in out["actions"]], [("withdraw-question", "q1"), ("set-status", "In Progress")])
        self.assertEqual(kinds(out["reports"]), ["reopened-while-pending"])

    def test_reopen_after_end_clears_fields_and_reports(self):
        """終わった後の reopen は、フィールドが自分の書いた値 (今の割り当ての宛先) なら空にして報告する。Status は変えない。"""
        item = make_item(state="OPEN", status="Done", comments_=[ASSIGN1], prs=[ref_pr(PR9, t(25), state="MERGED", merged=True)],
                         events=[{"type": "ClosedEvent", "at": t(50), "state_reason": "COMPLETED", "closer_pr": 9}, {"type": "ReopenedEvent", "at": t(60)}])
        out = turn_of(item)
        self.assertEqual([(a["kind"], a["fields"]) for a in out["actions"]], [("clear-field", ["Agent session ID", "Agent session title"])])
        self.assertEqual(kinds(out["reports"]), ["reopened"])
        other = make_item(state="OPEN", status="Done", session_field="someone", comments_=[ASSIGN1], prs=[ref_pr(PR9, t(25), state="MERGED", merged=True)],
                          events=[{"type": "ClosedEvent", "at": t(50), "state_reason": "COMPLETED", "closer_pr": 9}, {"type": "ReopenedEvent", "at": t(60)}])
        out = turn_of(other)
        self.assertEqual((out["actions"], kinds(out["reports"])), ([], ["reopened"]), "人が書いた値は消さない")

    def test_assignee_change_asks(self):
        item = make_item(assignees=("akm", "other"), comments_=[ASSIGN1, DECL1, _go(400, t(13), 500)])
        out = turn_of(item)
        self.assertEqual([(q["kind"], q["options"]) for q in out["questions"]], [("assignee-changed", ["release", "continue"])])

    def test_field_cleared_or_changed_by_user_asks(self):
        """フィールドの値が宛先と違い、更新が `割り当て` より後なら利用者の変更として尋ねる。"""
        item = make_item(session_field="", comments_=[ASSIGN1, DECL1, _go(400, t(13), 500)])
        item["fields"]["Agent session ID"]["updated_at"] = t(30)
        self.assertEqual(kinds(turn_of(item)["questions"]), ["field-cleared"])
        item = make_item(session_field="W-8", comments_=[ASSIGN1, DECL1, _go(400, t(13), 500)])
        item["fields"]["Agent session ID"]["updated_at"] = t(30)
        self.assertEqual(kinds(turn_of(item)["questions"]), ["field-changed"])

    def test_field_not_written_yet_is_continued(self):
        """`割り当て` の後にフィールドが書かれていない (更新がコメントより前) 項目は、途中で止まったとして続きを書く。"""
        item = make_item(session_field=None, status="Ready", comments_=[ASSIGN1])
        out = turn_of(item)
        self.assertEqual([(a["kind"], a.get("field"), a.get("value"), a.get("status")) for a in out["actions"]],
                         [("set-field", "Agent session ID", W7, None), ("set-field", "Agent session title", "worker 1", None), ("set-status", None, None, "In Progress")])
        self.assertTrue(all(a["continuation"] for a in out["actions"]))

    def test_status_changed_by_user_asks_release(self):
        """割り当て中の項目の Status を手で `Todo` にされたら、reopen とせず割り当てを保ち、解除するかを尋ねる (AE8)。"""
        item = make_item(status="Todo", comments_=[ASSIGN1, DECL1, _go(400, t(13), 500)], events=[_status_event("Todo", t(30))])
        out = turn_of(item)
        self.assertEqual([(q["kind"], q["options"]) for q in out["questions"]], [("status-changed", ["release", "restore"])])

    def test_in_review_is_an_expected_status(self):
        item = make_item(status="In review", comments_=[ASSIGN1, DECL1, _go(400, t(13), 500)])
        self.assertEqual(turn_of(item)["questions"], [])

    def test_wait_continuation_adds_blocker_and_blocked(self):
        """`待機` (Issue) を書いた後に止まった項目は、blockedBy と `Blocked` の続きを書く。"""
        item = make_item(status="In Progress", comments_=[ASSIGN1, DECL1, _wait(400, [{"kind": "Issue", "issue": A2}], t(13), 500)])
        out = turn_of(item)
        self.assertEqual([(a["kind"], a.get("blocker") or a.get("status")) for a in out["actions"]], [("blocked-by-add", A2), ("set-status", "Blocked")])

    def test_todo_with_wait_continues_to_blocked_once(self):
        """Status が `Todo` のまま (書かれずに止まった) で `待機` (Issue) もある項目は、続きの Status を `Blocked` 1 つだけにする (In Progress と Blocked の 2 つを返さない)。"""
        item = make_item(status="Todo", comments_=[ASSIGN1, DECL1, _wait(400, [{"kind": "Issue", "issue": A2}], t(13), 500)])
        out = turn_of(item)
        self.assertEqual([(a["kind"], a.get("blocker") or a.get("status")) for a in out["actions"]], [("set-status", "Blocked"), ("blocked-by-add", A2)])

    def test_wait_continuation_respects_user_removal(self):
        """`待機` の後に人が blockedBy を外した (BlockedByRemovedEvent がコメントより後) なら足し直さず報告する。Status も利用者が変えていれば報告する。"""
        item = make_item(status="In Progress", comments_=[ASSIGN1, DECL1, _wait(400, [{"kind": "Issue", "issue": A2}], t(13), 500)],
                         events=[{"type": "BlockedByAddedEvent", "at": t(14), "blocking": A2}, {"type": "BlockedByRemovedEvent", "at": t(15), "blocking": A2},
                                 _status_event("Blocked", t(14)), _status_event("In Progress", t(16), previous="Blocked")])
        out = turn_of(item)
        self.assertEqual((out["actions"], sorted(kinds(out["reports"]))), ([], ["blocked-by-removed", "status-changed"]))

    def test_third_party_edit_asks_only_for_configured_repos(self):
        edits = [{"editor": "someone", "edited_at": t(15), "deleted_at": None}]
        item = make_item(comments_=[ASSIGN1, DECL1, _go(400, t(13), 500)], body_edits=edits)
        self.assertEqual(kinds(turn_of(item)["questions"]), [])
        config = {"third_party_edit_check": [A]}
        self.assertEqual([(q["kind"], q["options"]) for q in turn_of(item, config=config)["questions"]], [("third-party-edit", ["stop", "continue"])])
        rec = rec_with(items={A9: rec_item(confirmed=t(15))})
        self.assertEqual(kinds(turn_of(item, rec=rec, config=config)["questions"]), [], "確かめた時刻までの編集は尋ねない")

    def test_pr_without_closing_reference_requests_append(self):
        """報告の PR が Issue を閉じる参照を持たなければ `依頼` (本文の追記) を書く (既に同じ依頼があれば書かない)。"""
        report = wcomment("PR の報告", None, t(30), 300, body=PR9)
        item = make_item(comments_=[ASSIGN1, DECL1, _go(400, t(13), 500), report])
        prs = {PR9: {**observed(PR9, issues=()), "pr": {**observed(PR9, issues=())["pr"], "default_branch": "main"}}}
        out = turn_of(item, pr_states=prs)
        self.assertEqual([(a["kind"], a["comment_kind"], a["values"]["request_kind"], a["values"]["pr"]) for a in out["actions"]], [("comment", "依頼", "本文の追記", PR9)])
        asked = mcomment("依頼", {"to": W7, "assignment": 1, "request_kind": "本文の追記", "pr": PR9}, t(31), 301)
        out = turn_of(make_item(comments_=[ASSIGN1, DECL1, _go(400, t(13), 500), report, asked]), pr_states=prs)
        self.assertEqual(out["actions"], [])

    def test_pr_to_non_default_branch_is_reported_not_requested(self):
        """既定のブランチ以外へ向けた PR の報告は、本文の追記を頼まず 1 回だけ報告する (利用者が決めた)。"""
        report = wcomment("PR の報告", None, t(30), 300, body=PR9)
        item = make_item(comments_=[ASSIGN1, DECL1, _go(400, t(13), 500), report])
        base = observed(PR9, issues=(), base_ref="develop")
        prs = {PR9: {**base, "pr": {**base["pr"], "default_branch": "main"}}}
        out = turn_of(item, pr_states=prs)
        self.assertEqual((out["actions"], kinds(out["reports"])), ([], ["pr-base-not-default"]))
        rec = rec_with(items={A9: rec_item(reported={"pr-base-not-default": t(31)})})
        self.assertEqual(kinds(turn_of(item, rec=rec, pr_states=prs)["reports"]), [], "報告済みの印があれば報告しない")

    def test_merged_pr_with_open_issue_and_closed_pr_ask(self):
        item = make_item(comments_=[ASSIGN1, DECL1, _go(400, t(13), 500)], prs=[ref_pr(PR9, t(25), state="MERGED", merged=True)])
        self.assertEqual([(q["kind"], q["options"]) for q in turn_of(item)["questions"]], [("merged-issue-open", ["close", "keep"])])
        item = make_item(comments_=[ASSIGN1, DECL1, _go(400, t(13), 500)], prs=[ref_pr(PR9, t(25), state="CLOSED")])
        self.assertEqual([(q["kind"], q["options"]) for q in turn_of(item)["questions"]], [("pr-closed-unmerged", ["release", "keep"])])

    def test_pr_left_open_after_normal_end_is_reported(self):
        """正常な終わり (ready for review の後の close) の後に開いたまま残る PR は 1 回報告し、判定の相手にしない。"""
        item = make_item(state="CLOSED", status="Done", comments_=[ASSIGN1], prs=[ref_pr(PR9, t(25), state="OPEN")],
                         events=[{"type": "ClosedEvent", "at": t(50), "state_reason": "COMPLETED", "closer_pr": None}])
        self.assertEqual(kinds(turn_of(item)["reports"]), ["pr-left-open"])

    def test_handover_comment_for_item_unknown_to_record(self):
        """初めて扱う項目 (記録にその項目の情報が無い) で、最後の管理のコメントの ID が自分と違えば `引き継ぎ` を書く。自分のならば書かない。"""
        prev = mcomment("割り当て", {"to": W7, "assignment": 1}, t(10), 100, name="old mgr", sid="M-0")
        item = make_item(comments_=[prev, wcomment("着手の宣言", None, t(12), 400, body=decl_body())])
        out = turn_of(item, rec=rec_with())
        self.assertEqual([(a["kind"], a["comment_kind"]) for a in out["actions"] if a["kind"] == "comment"], [("comment", "引き継ぎ")])
        self.assertIn("M-0", out["actions"][0]["body"])
        out = turn_of(item, rec=rec_with(items={A9: rec_item()}))
        self.assertEqual([a for a in out["actions"] if a.get("comment_kind") == "引き継ぎ"], [], "記録にある項目には書かない")
        done = mcomment("引き継ぎ", None, t(20), 101)
        out = turn_of(make_item(comments_=[prev, done]), rec=rec_with())
        self.assertEqual([a for a in out["actions"] if a.get("comment_kind") == "引き継ぎ"], [], "自分の `引き継ぎ` が既にあれば書かない")

    def test_record_lost_reasks_user_answer_waits(self):
        """記録を失ったとき (記録が無い・前の記録が ended) は、`利用者の答え` を待つ宣言を尋ね直す項目として返し、報告に記録を失ったためと書く。"""
        item = make_item(status="In Progress", comments_=[ASSIGN1, DECL1, _wait(400, [{"kind": "利用者の答え"}], t(13), 500)])
        for rec in (None, rec_with(manager_state="ended")):
            out = turn_of(item, rec=rec)
            self.assertEqual((out["record_lost"], [(q["kind"], q.get("record_lost")) for q in out["questions"]]), (True, [("user-answer-lost", True)]))

    def test_removed_item_with_intent_asks(self):
        """記録の意図にある項目が Project の一覧に無ければ、除去として解除を尋ねる。"""
        out = itemstate.derive_turn([], rec_with(items={A9: rec_item()}), LOGIN, M1, PROJECT_NUMBER, {}, {}, [], {}, {"third_party_edit_check": []})
        self.assertEqual([(q["kind"], q["item"], q["options"]) for q in out["questions"]], [("removed", A9, ["release", "keep"])])


class HumanChangeTest(unittest.TestCase):
    """スナップショットの差分のうち、自分の書き込みと組み込みワークフローの遷移で説明できないものを 1 回だけ報告する (R22)。"""

    def _unassigned(self, status, state="OPEN", events=()):
        return make_item(status=status, state=state, session_field=None, events=list(events))

    def test_workflow_and_user_start_transitions_are_not_reported(self):
        cases = [(self._unassigned("Done", state="CLOSED"), {"kind": "status", "item": A9, "before": "Ready", "after": "Done"}),
                 (self._unassigned("Todo", events=[{"type": "ReopenedEvent", "at": t(5)}]), {"kind": "status", "item": A9, "before": "Done", "after": "Todo"}),
                 (self._unassigned("Ready"), {"kind": "status", "item": A9, "before": "Todo", "after": "Ready"}),
                 (self._unassigned("Ready"), {"kind": "status", "item": A9, "before": None, "after": "Ready"}),
                 (self._unassigned("Ready", events=[{"type": "ReopenedEvent", "at": t(5)}]), {"kind": "status", "item": A9, "before": "Done", "after": "Ready"})]
        for item, diff in cases:
            self.assertEqual(turn_of(item, rec=rec_with(), diffs=[diff])["reports"], [], diff)

    def test_unexplained_status_change_is_reported_once(self):
        item = self._unassigned("Todo")
        diff = {"kind": "status", "item": A9, "before": "Ready", "after": "Todo"}
        out = turn_of(item, rec=rec_with(), diffs=[diff])
        self.assertEqual([(r["kind"], r["before"], r["after"]) for r in out["reports"]], [("status-changed", "Ready", "Todo")])
        rec = rec_with(items={A9: {**rec_item(), "intent": None, "reported": {"status-changed": t(1)}}})
        self.assertEqual(turn_of(item, rec=rec, diffs=[diff])["reports"], [])

    def test_reopen_to_todo_without_workflow_is_reported(self):
        """ワークフロー「Item reopened」が無い Project では、reopen で `Todo` にならないので、`Todo` への変化は人の変更。"""
        item = self._unassigned("Todo", events=[{"type": "ReopenedEvent", "at": t(5)}])
        out = turn_of(item, rec=rec_with(), diffs=[{"kind": "status", "item": A9, "before": "Done", "after": "Todo"}], workflows={"Item reopened": False})
        self.assertEqual(kinds(out["reports"]), ["status-changed"])

    def test_own_partial_write_matching_intent_is_not_reported(self):
        """記録の意図と一致する値 (自分の部分書き込み) は人の変更ではない。"""
        item = make_item(status="In Progress", comments_=[ASSIGN1])
        out = turn_of(item, diffs=[{"kind": "status", "item": A9, "before": "Ready", "after": "In Progress"},
                                   {"kind": "field", "item": A9, "field": "Agent session ID", "before": None, "after": W7}])
        self.assertEqual(out["reports"], [])

    def test_human_blocked_by_on_assigned_item_is_reported(self):
        item = make_item(status="In Progress", blocked_by=[_blocker(A1)], comments_=[ASSIGN1, DECL1, _go(400, t(13), 500)])
        out = turn_of(item, diffs=[{"kind": "blocked_by", "item": A9, "added": [A1], "removed": [], "state_changed": []}])
        self.assertEqual([(r["kind"], r["blockers"]) for r in out["reports"]], [("blocked-by-added", [A1])])


USER_ENTRY = {"prefix": ["api", "user"], "stdout": {"fixture": "api-user"}}


def items_data(mutate=None):
    data = fixture_json("project-items-ok")
    if mutate:
        mutate(data["data"]["repositoryOwner"]["projectV2"]["items"]["nodes"])
    return data


def node_of(nodes, number, repo=A):
    return next(n for n in nodes if (n.get("content") or {}).get("number") == number and n["content"]["repository"]["nameWithOwner"] == repo)


def gql_comment(c):
    """合成したコメント (project.items の形) を GraphQL の応答の形にする。"""
    return {"id": c["id"], "databaseId": c["database_id"], "url": c["url"], "createdAt": c["created_at"], "author": {"login": c["author"]}, "body": c["body"]}


def pr_fixture(state, draft=False, merged=False):
    data = fixture_json("pr-observe-open-other-base")
    pr = data["data"]["repository"]["pullRequest"]
    pr["state"], pr["isDraft"], pr["mergedAt"] = state, draft, ("2026-10-23T00:00:00Z" if merged else None)
    return data


class CliTest(FakeGhCase):

    def setUp(self):
        super().setUp()
        self.manager = os.path.join(self.root, "manager")
        os.makedirs(os.path.dirname(os.path.join(self.manager, config.CONFIG_PATH)))
        with open(os.path.join(self.manager, config.CONFIG_PATH), "w", encoding="utf-8") as f:
            json.dump({"project": {"owner": "akm", "number": 3}, "record_dir": "rec"}, f)

    def cli(self, *args, stdin=None, env=None):
        r = subprocess.run([sys.executable, _CLI, *args], capture_output=True, text=True, input=stdin, env={**os.environ, **(env or {})})
        return r.returncode, json.loads(r.stdout) if r.stdout.strip() else None, r.stderr

    def _assigned_item3(self, nodes, extra=()):
        c = node_of(nodes, 3)["content"]
        c["assignees"]["nodes"] = [{"login": LOGIN}]  # 範囲 (担当者が自分 1 人) に入れる
        # 固定データの項目 3 のフィールド Agent session ID は W-7 ではないので、W-7 に書き換える
        for fv in node_of(nodes, 3)["fieldValues"]["nodes"]:
            if fv and (fv.get("field") or {}).get("name") == "Agent session ID":
                fv["text"] = W7
        c["comments"]["nodes"] += [gql_comment(x) for x in (ASSIGN1, *extra)]

    def test_item_state_cli(self):
        """item state は、割り当てのある項目の状態と資源の使用を返す (gh は読むだけ)。"""
        self.responses([USER_ENTRY, {"substring": "query ProjectMeta", "stdout": {"fixture": "project-meta-ok"}}, {"substring": "query ProjectItems", "stdout": items_data(lambda nodes: self._assigned_item3(nodes, [DECL1, _go(400, t(13), 500)]))}])
        code, out, err = self.cli("item", "state", "--dir", self.manager)
        self.assertEqual((code, out["status"], out["errors"]), (0, "ok", []), err)
        self.assertEqual([i["key"] for i in out["items"]], [f"{A}#3"])
        st = out["items"][0]
        self.assertEqual((st["assigned"], st["declaration"]["stage"], st["declaration"]["held"]), (True, "go", ["db"]))
        self.assertEqual(out["usage"], {"db": [f"{A}#3"]})
        self.assertFalse(any("mutation" in (r.get("stdin") or "") for r in self.recorded_full()), "書き込みの gh を実行しない")

    def test_item_state_reads_report_pr(self):
        """`PR の報告` の PR は issues.observe_pr で読む。閉じる参照が無ければ closing は偽。"""
        report = wcomment("PR の報告", None, t(30), 300, body=PR9)
        self.responses([USER_ENTRY, {"substring": "query ProjectMeta", "stdout": {"fixture": "project-meta-ok"}}, {"substring": "query ProjectItems", "stdout": items_data(lambda nodes: self._assigned_item3(nodes, [report]))},
                        {"substring": "query PrObserve", "stdout": pr_fixture("OPEN")}])
        code, out, err = self.cli("item", "state", "--dir", self.manager, "--issue", f"{A}#3")
        self.assertEqual((code, out["status"]), (0, "ok"), err)
        self.assertEqual((out["items"][0]["pr"]["url"], out["items"][0]["pr"]["source"]), (PR9, "report"))

    def test_item_state_stops_on_list_problems(self):
        """項目の一覧そのものが欠ければ導かない。"""
        self.responses([USER_ENTRY, {"substring": ["query ProjectItems", '"after": "CURSOR-PAGE-1"'], "stdout": "", "stderr": "gh: HTTP 502\n", "exit": 1},
                        {"substring": "query ProjectItems", "stdout": {"fixture": "project-items-page1"}}])
        code, out, err = self.cli("item", "state", "--dir", self.manager)
        self.assertEqual((code, out["status"], out["errors"][0]["key"]), (0, "error", "partial"), err)

    def test_item_state_turn_outputs(self):
        """item state は、記録 (--dir) と差分 (--diffs) とワークフローを読み、actions・questions・reports・pending を返す (書かない)。"""
        rec_dir = os.path.join(self.manager, "rec", "akm-3")
        os.makedirs(rec_dir)
        rec = rec_with(items={f"{A}#3": rec_item()})
        with open(os.path.join(rec_dir, "record.json"), "w", encoding="utf-8") as f:
            json.dump(rec, f)
        diffs_path = os.path.join(self.root, "diffs.json")
        with open(diffs_path, "w", encoding="utf-8") as f:
            json.dump({"diffs": [{"kind": "status", "item": f"{A}#1", "before": "Ready", "after": "Todo"}]}, f)
        def mutate(nodes):
            self._assigned_item3(nodes, [DECL1, _wait(400, [{"kind": "Issue", "issue": A1}], t(13), 500)])
        self.responses([USER_ENTRY, {"substring": "query ProjectMeta", "stdout": {"fixture": "project-meta-ok"}}, {"substring": "query ProjectItems", "stdout": items_data(mutate)}])
        code, out, err = self.cli("item", "state", "--dir", self.manager, "--diffs", diffs_path)
        self.assertEqual((code, out["status"], out["record_lost"]), (0, "ok", False), err)
        self.assertEqual([(a["kind"], a.get("blocker") or a.get("status")) for a in out["actions"]], [("blocked-by-add", A1), ("set-status", "Blocked")])
        self.assertEqual([(r["kind"], r["item"]) for r in out["reports"]], [("status-changed", f"{A}#1")])
        self.assertEqual((out["questions"], out["pending"]), ([], []))
        self.assertFalse(any("mutation" in (r.get("stdin") or "") or r["args"][:2] == ["issue", "edit"] for r in self.recorded_full()), "書き込みの gh を実行しない")

    def test_item_state_without_record_is_lost(self):
        self.responses([USER_ENTRY, {"substring": "query ProjectMeta", "stdout": {"fixture": "project-meta-ok"}}, {"substring": "query ProjectItems", "stdout": items_data(lambda nodes: self._assigned_item3(nodes, [DECL1]))}])
        code, out, err = self.cli("item", "state", "--dir", self.manager)
        self.assertEqual((code, out["status"], out["record_lost"]), (0, "ok", True), err)

    def test_blocked_by_remove_only_own_blockers(self):
        """blocked-by remove は、自分が足した blockedBy (今の割り当ての `待機` の理由の Issue) だけを外し、それ以外は gh を実行せずに拒否する。"""
        def mutate(nodes):
            self._assigned_item3(nodes, [DECL1, _wait(400, [{"kind": "Issue", "issue": A1}], t(13), 500)])
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": items_data(mutate)}, {"prefix": ["issue", "edit"], "stdout": ""}])
        code, out, err = self.cli("blocked-by", "remove", "--dir", self.manager, "--issue", f"{A}#3", "--blocker", A2)
        self.assertEqual((code, out["status"], out["own_blockers"]), (0, "rejected", [A1]), err)
        self.assertFalse(any(r["args"][:2] == ["issue", "edit"] for r in self.recorded_full()), "拒否のときは gh を実行しない")
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": items_data(mutate)}, {"prefix": ["issue", "edit"], "stdout": ""}])
        code, out, err = self.cli("blocked-by", "remove", "--dir", self.manager, "--issue", f"{A}#3", "--blocker", A1)
        self.assertEqual((code, out["status"], out["blocker"]), (0, "ok", A1), err)
        edit = [r["args"] for r in self.recorded_full() if r["args"][:2] == ["issue", "edit"]]
        self.assertEqual(edit[-1][2:], [f"https://github.com/{A}/issues/3", "--remove-blocked-by", f"https://github.com/{A}/issues/1"])

    def test_work_check_and_held_cli(self):
        """work check と work held は、--session (無ければ環境変数) の作業のセッションについて返す。"""
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": items_data(lambda nodes: self._assigned_item3(nodes, [DECL1]))}])
        code, out, err = self.cli("work", "check", "--project", "akm/3", "--issue", f"{A}#3", "--session", W7)
        self.assertEqual((code, out["status"], out["field_is_mine"], out["assigned_to_me"], out["released"], out["pending_requests"]), (0, "ok", True, True, None, []), err)
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": items_data(lambda nodes: self._assigned_item3(nodes, [DECL1]))}])
        code, out, err = self.cli("work", "held", "--project", "akm/3", env={"CLAUDE_CODE_HOST_SESSION_ID": W7})
        self.assertEqual((code, out["status"], out["session"]), (0, "ok", W7), err)
        self.assertEqual([(h["key"], h["judged"], h["has_go"]) for h in out["items"]], [(f"{A}#3", 400, False)])

    def test_work_check_missing_issue_and_session(self):
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": {"fixture": "project-items-ok"}}])
        code, out, _ = self.cli("work", "check", "--project", "akm/3", "--issue", f"{A}#77", "--session", W7)
        self.assertEqual((code, out["status"], out["errors"][0]["key"]), (0, "error", "issue"))
        env = {k: "" for k in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_HOST_SESSION_ID")}
        code, out, _ = self.cli("work", "held", "--project", "akm/3", env=env)
        self.assertEqual((code, out["status"], out["errors"][0]["key"]), (0, "error", "session"))


class DocTest(unittest.TestCase):

    def test_doc_lists_states_and_cli(self):
        with open(_DOC, encoding="utf-8") as f:
            doc = f.read()
        for key in ("`assigned`", "`in_progress`", "`end`", "`reopened`", "`pr`", "`judged`", "`stage`", "`manager_blocked`", "`return_status`",
                    "`own_blockers`", "`waiting_blockers`", "`held`", "`reserved`", "`item state`", "`work check`", "`work held`", "`actions`", "`questions`", "`reports`",
                    "`pending`", "`record_lost`", "`blocked-by remove`", "`--diffs`"):
            self.assertIn(key, doc, f"{key} が文書に無い")
        for name in itemstate.STAGES + itemstate.ACTION_KINDS + itemstate.REPORT_KINDS:
            self.assertIn(f"`{name}`", doc, f"{name} が文書に無い")
        records = os.path.join(os.path.dirname(_DOC), "records.md")
        with open(records, encoding="utf-8") as f:
            rdoc = f.read()
        for kind in itemstate.QUESTION_KINDS:
            self.assertIn(f"`{kind}`", rdoc, f"問いの種類 {kind} が records.md に無い")


if __name__ == "__main__":
    unittest.main()
