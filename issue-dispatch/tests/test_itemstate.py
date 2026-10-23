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
              body_edits=(), position=1):
    return {"item_id": "I9", "position": position, "key": key, "repo": key.split("#")[0], "number": int(key.split("#")[1]),
            "url": f"https://github.com/{key.replace('#', '/issues/')}", "state": state, "created_at": t(0), "author": "akm",
            "status": {"name": status, "option_id": "o", "updated_at": t(1)} if status else None,
            "fields": {"Agent session ID": {"text": session_field, "updated_at": t(1)}} if session_field is not None else {},
            "assignees": list(assignees), "labels": list(labels), "blocked_by": [], "body_edits": list(body_edits),
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
        self.assertEqual((d["stage"], d["manager_blocked"], d["return_status"], d["own_blockers"]), ("waiting", True, "In Progress", [A2]))

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
        self.assertEqual((d["stage"], d["manager_blocked"], d["own_blockers"]), ("go", False, []))

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
        # 固定データの項目 3 のフィールド Agent session ID は W-7 ではないので、W-7 に書き換える
        for fv in node_of(nodes, 3)["fieldValues"]["nodes"]:
            if fv and (fv.get("field") or {}).get("name") == "Agent session ID":
                fv["text"] = W7
        c["comments"]["nodes"] += [gql_comment(x) for x in (ASSIGN1, *extra)]

    def test_item_state_cli(self):
        """item state は、割り当てのある項目の状態と資源の使用を返す (gh は読むだけ)。"""
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": items_data(lambda nodes: self._assigned_item3(nodes, [DECL1, _go(400, t(13), 500)]))}])
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
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": items_data(lambda nodes: self._assigned_item3(nodes, [report]))},
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
                    "`own_blockers`", "`held`", "`reserved`", "`item state`", "`work check`", "`work held`"):
            self.assertIn(key, doc, f"{key} が文書に無い")
        for stage in itemstate.STAGES:
            self.assertIn(f"`{stage}`", doc)


if __name__ == "__main__":
    unittest.main()
