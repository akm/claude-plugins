"""宣言の判定 (judge) のテスト。判定は gh を実行しないので、項目と状態は合成して渡し、リポジトリの設定の読み取りは関数で差し替える。
CLI のテストは偽の gh (tests/fake-gh) と固定データと、clone に見えるリポジトリ (test_repo.make_clone) で動く。場面はテストの名前に書く (計画の U15)。"""

import json
import os
import subprocess
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.join(_HERE, "..", "scripts")
sys.path.insert(0, _SCRIPTS)
sys.path.insert(0, _HERE)

from issue_dispatch import comments, config, filekinds, itemstate, judge, record, resources  # noqa: E402
from test_itemstate import (A, ASSIGN1, LOGIN, M1, PR9, PROJECT_NUMBER, W7, USER_ENTRY, decl_body, gql_comment, items_data, make_item,  # noqa: E402
                            mcomment, node_of, observed, options_text, question_kinds, question_options_cell, question_row, question_table, rec_with, t, wcomment)
from test_project import FakeGhCase  # noqa: E402
from test_repo import make_clone  # noqa: E402

_CLI = os.path.join(_SCRIPTS, "issue_dispatch.py")
_FLOW = os.path.join(_HERE, "..", "skills", "issue-dispatch", "references", "flow.md")
_RECORDS = os.path.join(_HERE, "..", "skills", "issue-dispatch", "references", "records.md")
A9, A5, A6 = f"{A}#9", f"{A}#5", f"{A}#6"
OTHER_REPO_ITEM = "akm/other-repo#2"
W8, W9 = "W-8", "W-9"
TABLE = filekinds.load_default_table()


def ok_config(rules=()):
    """read_repo_config の結果 (読める)。rules は設定の files の規則 (config.load_text でそろえる)。"""
    loaded = config.load_text(json.dumps({"files": list(rules)}), "repo", "/clone/.claude/akm-claude-plugins/issue-dispatch/config.json")
    return {"status": "ok", "reason": None, "message": None, "fix": None, "root_hint": "/clone", "path": "/clone", "config": loaded["config"],
            "warnings": loaded["warnings"], "errors": []}


MISSING_CONFIG = {"status": "missing", "reason": None, "message": "既定のブランチに設定ファイルが無い", "fix": None, "root_hint": "/clone", "path": "/clone",
                  "config": config.load_text("{}", "repo", "x")["config"], "warnings": [], "errors": []}
UNREADABLE_CONFIG = {"status": "unreadable", "reason": "not-in-repositories", "message": "管理ディレクトリの設定の repositories に akm/issue-dispatch-verify-a が無い",
                     "fix": "設定の repositories に owner/repo → clone の絶対パスを足す", "root_hint": None, "path": None, "config": None, "warnings": [], "errors": []}


def reader(result=None, by_repo=None):
    """リポジトリの設定の読み取りの差し替え。by_repo は owner/repo (小文字) → 結果。"""
    def read(repo):
        if by_repo:
            return by_repo[repo.lower()]
        return result if result is not None else ok_config()
    return read


def assign(to, number=1, at=None, cid=None):
    return mcomment("割り当て", {"to": to, "assignment": number}, at or t(10), cid or 100)


def decl(cid, at, files=(("src/a.py", None),), resources=(), to=W7, split=False, body=None, kind="着手の宣言"):
    return wcomment(kind, None, at, cid, body=body if body is not None else decl_body(files, resources, split), sid=to)


def go(decl_id, at, cid, to=W7, number=1):
    return mcomment("開始可", {"to": to, "assignment": number, "declaration": decl_id}, at, cid)


def wait(decl_id, at, cid, waits, to=W7, number=1):
    return mcomment("待機", {"to": to, "assignment": number, "declaration": decl_id, "waits": waits}, at, cid)


def item(key, comments_, position=1, status="In Progress", session=W7, labels=(), blocked_by=(), events=(), state="OPEN", prs=()):
    return make_item(key=key, comments_=list(comments_), position=position, status=status, session_field=session, labels=labels,
                     blocked_by=list(blocked_by), events=list(events), state=state, prs=list(prs))


def states_of(items, pr_states=None, attrs=None):
    return [itemstate.derive(it, LOGIN, pr_states or {}, PROJECT_NUMBER, attrs) for it in items]


def question(kind, item_key, subject, answer=None, qid="q1", asked=None):
    # 質問した時刻は、固定の割り当て (ASSIGN1。t(10)) の後にする (判定は今の割り当ての質問だけを読む)
    return {qid: {"item": item_key, "kind": kind, "options": list(judge.QUESTION_OPTIONS[kind]), "asked_at": asked or t(11), "answer": answer,
                  "answered_at": t(12) if answer is not None else None, "subject": subject}}


def run_judge(items, rec=None, read=None, attrs=None, pr_states=None, only=None):
    return judge.judge(items, states_of(items, pr_states, attrs), rec, attrs or {}, pr_states or {}, read or reader(), TABLE, login=LOGIN, only=only)


def kinds(actions):
    return [(a["kind"], a.get("comment_kind")) if a["kind"] == "comment" else (a["kind"],) for a in actions]


# 相手 B (項目 A5、セッション W-8) が src/a.py 全体を `開始可` で持つ
B_GO = [assign(W8, 1, t(10), 110), decl(410, t(11), to=W8), go(410, t(12), 510, to=W8)]


class PendingTest(unittest.TestCase):

    def test_pending_declarations_sorted_by_posted_then_position(self):
        """未判定の宣言は投稿の順、同じなら Project の中の順 (AE32)。"""
        a = item(A9, [ASSIGN1, decl(400, t(20))], position=2)
        b = item(A5, [assign(W8, 1, t(10), 110), decl(410, t(20), to=W8)], position=1)
        c = item(A6, [assign(W9, 1, t(10), 120), decl(420, t(15), to=W9)], position=3)
        items = [a, b, c]
        got = judge.pending(items, states_of(items))
        self.assertEqual([(e["item"]["key"], e["judged"]["comment_id"]) for e in got], [(A6, 420), (A5, 410), (A9, 400)])

    def test_only_undecided_declarations_are_pending(self):
        """判定済み (`開始可`・`待機`・`依頼` が最新) の宣言と、割り当ての無い項目は前半の判定の対象にしない。"""
        waiting = item(A5, [assign(W8, 1, t(10), 110), decl(410, t(11), to=W8), wait(410, t(12), 510, [{"kind": "利用者の回答"}], to=W8)])
        gone = item(A6, [assign(W9, 1, t(10), 120), decl(420, t(11), to=W9), go(420, t(12), 520, to=W9)])
        returned = item(f"{A}#7", [assign(W9, 1, t(10), 130), decl(430, t(11), to=W9),
                                   mcomment("依頼", {"to": W9, "assignment": 1, "request_kind": "宣言の修正", "declaration": 430}, t(12), 530)])
        unassigned = item(f"{A}#8", [decl(440, t(11))], session=None)
        items = [waiting, gone, returned, unassigned, item(A9, [ASSIGN1, decl(400, t(20))])]
        self.assertEqual([e["judged"]["comment_id"] for e in judge.pending(items, states_of(items))], [400])

    def test_update_after_go_is_pending_again(self):
        """`開始可` の後の判定の要る更新 (資源を足す・ファイルを変える) は未判定の宣言。"""
        it = item(A9, [ASSIGN1, decl(400, t(11)), go(400, t(12), 500), decl(401, t(13), resources=("db",), kind="宣言の更新")])
        got = judge.pending([it], states_of([it]))
        self.assertEqual([(e["judged"]["comment_id"], e["judged"]["update_kind"]) for e in got], [(401, "resources-only")])


class OthersTest(unittest.TestCase):

    def test_compared_only_with_go_declarations(self):
        """比べる相手は既に `開始可` になった宣言だけ。未判定の宣言どうしは比べない (AE32)。"""
        mine = item(A9, [ASSIGN1, decl(400, t(20))])
        undecided = item(A5, [assign(W8, 1, t(10), 110), decl(410, t(21), to=W8)])
        items = [mine, undecided]
        others = judge.go_declarations(items, states_of(items), {}, LOGIN)
        self.assertEqual(others, [])
        out = run_judge(items)
        self.assertEqual([j["result"] for j in out["judgments"]], ["go", "ask"])
        self.assertEqual(out["judgments"][1]["compared"], [400], "先に `開始可` になった宣言を、後の宣言の相手にする")

    def test_only_judges_up_to_that_item_in_posting_order(self):
        """only (CLI の --issue) は、投稿の順に並べた未判定の宣言のうち、その項目の宣言まで判定する。前の宣言は飛ばさず、後の宣言は判定しない。
        その項目に未判定の宣言が無ければ何も判定しない。"""
        first = item(A9, [ASSIGN1, decl(400, t(20))], position=1)  # 先に投稿。src/a.py
        target = item(A5, [assign(W8, 1, t(10), 110), decl(410, t(30), to=W8)], position=2)  # 後に投稿。同じ src/a.py
        later = item(A6, [assign(W9, 1, t(10), 120), decl(420, t(40), files=(("src/c.py", None),), to=W9)], position=3)
        out = run_judge([first, target, later], only=A5)
        self.assertEqual([(j["item"], j["result"]) for j in out["judgments"]], [(A9, "go"), (A5, "ask")], "前の宣言を先に判定し、後の宣言は判定しない")
        self.assertEqual(out["judgments"][1]["compared"], [400], "先に `開始可` にした前の宣言が相手になる")
        out = run_judge([first, target, later], only=A9)
        self.assertEqual([(j["item"], j["result"]) for j in out["judgments"]], [(A9, "go")])
        no_pending = item(f"{A}#7", [assign(W9, 1, t(10), 130), decl(430, t(11), to=W9), go(430, t(12), 530, to=W9)])
        out = run_judge([first, target, no_pending], only=f"{A}#7")
        self.assertEqual(out["judgments"], [], "その項目に未判定の宣言が無ければ何も判定しない")

    def test_other_repository_is_not_compared(self):
        """別のリポジトリの `開始可` の宣言とは比べない。"""
        other = item(OTHER_REPO_ITEM, [assign(W8, 1, t(10), 110), decl(410, t(11), to=W8), go(410, t(12), 510, to=W8)])
        out = run_judge([item(A9, [ASSIGN1, decl(400, t(20))]), other])
        self.assertEqual((out["judgments"][0]["result"], out["judgments"][0]["compared"]), ("go", []))

    def test_in_review_pr_files_not_in_declaration_join_the_other(self):
        """In review の PR が変えた、宣言に無いファイルも相手に加える (生成物は除く)。"""
        other_item = item(A5, [assign(W8, 1, t(10), 110), decl(410, t(11), files=(("src/b.py", None),), to=W8), go(410, t(12), 510, to=W8),
                              wcomment("PR の報告", None, t(13), 511, body=PR9, sid=W8)])
        pr = observed(PR9, issues=(A5,))
        pr["pr"]["files"] = [{"path": "src/b.py", "additions": 1, "deletions": 0, "change_type": "MODIFIED"},
                             {"path": "src/a.py", "additions": 1, "deletions": 0, "change_type": "MODIFIED"},
                             {"path": "go.sum", "additions": 1, "deletions": 0, "change_type": "MODIFIED"}]
        items = [item(A9, [ASSIGN1, decl(400, t(20))]), other_item]
        others = judge.go_declarations(items, states_of(items, {PR9: pr}), {PR9: pr}, LOGIN)
        self.assertEqual(others[0]["pr_paths"], ["go.sum", "src/a.py"])
        out = run_judge(items, pr_states={PR9: pr})
        self.assertEqual(out["judgments"][0]["result"], "ask")
        self.assertEqual(out["questions"][0]["subject"], f"{A5}:410")


class ConfigAndParseTest(unittest.TestCase):

    def test_unreadable_config_waits_for_config_without_judging(self):
        """リポジトリの設定が読めなければ、そのリポジトリの宣言は判定せず `待機` (理由 `設定`) を書き、直し方を本文に書く (KTD9)。"""
        out = run_judge([item(A9, [ASSIGN1, decl(400, t(20))])] + [item(A5, B_GO)], read=reader(UNREADABLE_CONFIG))
        j = out["judgments"][0]
        self.assertEqual((j["result"], j["waits"], j["repo_config"]), ("wait", [{"kind": "設定"}], "unreadable"))
        self.assertEqual(kinds(out["actions"]), [("comment", "待機")])
        self.assertEqual(out["actions"][0]["values"]["waits"], [{"kind": "設定"}])
        self.assertIn("repositories に owner/repo", out["actions"][0]["body"])
        self.assertIn("知らせ", out["actions"][0]["body"])
        self.assertEqual(out["signals"], [{"kind": "wait", "to": W7, "item": A9, "declaration": 400}])
        self.assertEqual(out["questions"], [])

    def test_missing_config_uses_default_table_only(self):
        """既定のブランチに設定ファイルが無いことは読めないことではなく、デフォルトの表だけで照合して進む。"""
        out = run_judge([item(A9, [ASSIGN1, decl(400, t(20))])], read=reader(MISSING_CONFIG))
        self.assertEqual((out["judgments"][0]["result"], out["judgments"][0]["repo_config"]), ("go", "missing"))

    def test_parse_error_with_repo_rules_requests_rewrite(self):
        """宣言の形の誤り (リポジトリの設定の規則で種類を付けて検査する) は `依頼` (宣言の修正)。本文に誤りと使った規則を書く。"""
        rules = [{"pattern": "src/**", "kind": "unknown-structure"}]
        out = run_judge([item(A9, [ASSIGN1, decl(400, t(20), files=(("src/a.py", [["f"]]),))])], read=reader(ok_config(rules)))
        j = out["judgments"][0]
        self.assertEqual(j["result"], "request")
        self.assertEqual(kinds(out["actions"]), [("comment", "依頼")])
        a = out["actions"][0]
        self.assertEqual(a["values"], {"to": W7, "assignment": 1, "request_kind": "宣言の修正", "declaration": 400})
        self.assertIn("files[0].units", a["body"])
        self.assertIn("リポジトリの設定", a["body"])
        self.assertIn("src/**", a["body"])
        self.assertEqual(out["signals"], [{"kind": "request", "to": W7, "item": A9, "declaration": 400, "request_kind": "宣言の修正"}])

    def test_unreadable_json_requests_rewrite(self):
        """JSON のコードブロックが無い・読めない宣言も `依頼` (宣言の修正)。本文に理由を書く。"""
        out = run_judge([item(A9, [ASSIGN1, decl(400, t(20), body="宣言です")])])
        self.assertEqual(out["judgments"][0]["result"], "request")
        self.assertIn("JSON のコードブロック", out["actions"][0]["body"])
        self.assertIn("デフォルトの表", out["actions"][0]["body"])


class ConflictTest(unittest.TestCase):

    def test_conflict_without_answer_asks_and_waits_for_answer(self):
        """競合しうる相手への回答が記録に無ければ、3 つの扱いを質問し、回答まで `待機` (理由 `利用者の回答`)。Status と blockedBy は変えない。"""
        out = run_judge([item(A9, [ASSIGN1, decl(400, t(20))]), item(A5, B_GO)])
        j = out["judgments"][0]
        self.assertEqual((j["result"], j["waits"], j["compared"]), ("ask", [{"kind": "利用者の回答"}], [410]))
        self.assertEqual(kinds(out["actions"]), [("comment", "待機")])
        self.assertEqual(out["actions"][0]["values"], {"to": W7, "assignment": 1, "declaration": 400, "waits": [{"kind": "利用者の回答"}]})
        self.assertEqual(out["questions"], [{"kind": "conflict", "item": A9, "options": ["wait", "small-pr", "proceed"], "subject": f"{A5}:410",
                                             "declaration": 400, "other": {"item": A5, "declaration": 410, "to": W8},
                                             "paths": [{"path": "src/a.py", "result": "conflict", "reason": "どちらかが units を省いている (ファイル全体を変える予定) ので、同じパスで競合しうる"}]}])
        self.assertEqual(out["signals"], [{"kind": "wait", "to": W7, "item": A9, "declaration": 400}])

    def test_unanswered_question_in_record_is_not_asked_again(self):
        """記録に同じ項目・種類・対象の未回答の質問があれば質問し直さない (`待機` は書く)。"""
        rec = rec_with(questions=question("conflict", A9, f"{A5}:410"))
        out = run_judge([item(A9, [ASSIGN1, decl(400, t(20))]), item(A5, B_GO)], rec=rec)
        self.assertEqual((out["judgments"][0]["result"], out["questions"], kinds(out["actions"])), ("ask", [], [("comment", "待機")]))

    def test_withdrawn_question_counts_as_unanswered(self):
        """取り下げた質問 (answer が null で answered_at がある) は回答に数えず、質問し直す。"""
        q = question("conflict", A9, f"{A5}:410")
        q["q1"]["answered_at"] = t(7)
        out = run_judge([item(A9, [ASSIGN1, decl(400, t(20))]), item(A5, B_GO)], rec=rec_with(questions=q))
        self.assertEqual((out["judgments"][0]["result"], len(out["questions"])), ("ask", 1))

    def test_answer_wait_waits_for_issue_with_blocked_by_and_blocked(self):
        """回答が wait なら `待機` (理由 `Issue` 相手) を書き、相手を blockedBy に足し、Status を Blocked にする (コメントが先)。"""
        rec = rec_with(questions=question("conflict", A9, f"{A5}:410", "wait"))
        out = run_judge([item(A9, [ASSIGN1, decl(400, t(20))]), item(A5, B_GO)], rec=rec)
        j = out["judgments"][0]
        self.assertEqual((j["result"], j["waits"]), ("wait", [{"kind": "Issue", "issue": A5}]))
        self.assertEqual(kinds(out["actions"]), [("comment", "待機"), ("blocked-by-add",), ("set-status",)])
        self.assertEqual((out["actions"][1]["blocker"], out["actions"][2]["status"]), (A5, "Blocked"))
        self.assertEqual(out["signals"], [{"kind": "wait", "to": W7, "item": A9, "declaration": 400}])

    def test_answer_wait_does_not_repeat_existing_blocked_by_or_status(self):
        """既に blockedBy にあり Status が Blocked なら、足し直さず変えない。"""
        rec = rec_with(questions=question("conflict", A9, f"{A5}:410", "wait"))
        mine = item(A9, [ASSIGN1, decl(400, t(20))], status="Blocked", blocked_by=[{"key": A5, "url": "", "state": "OPEN"}])
        out = run_judge([mine, item(A5, B_GO)], rec=rec)
        self.assertEqual(kinds(out["actions"]), [("comment", "待機")])

    def test_answer_small_pr_requests_other_session_and_waits(self):
        """回答が small-pr なら、相手のセッションに `依頼` (小さな PR) を書き、`待機` (理由 `小さな PR` 相手) と blockedBy と Blocked。合図は wait と request。"""
        rec = rec_with(questions=question("conflict", A9, f"{A5}:410", "small-pr"))
        out = run_judge([item(A9, [ASSIGN1, decl(400, t(20))]), item(A5, B_GO)], rec=rec)
        j = out["judgments"][0]
        self.assertEqual((j["result"], j["waits"]), ("wait", [{"kind": "小さな PR", "issue": A5}]))
        self.assertEqual(kinds(out["actions"]), [("comment", "待機"), ("comment", "依頼"), ("blocked-by-add",), ("set-status",)])
        req = out["actions"][1]
        self.assertEqual((req["item"], req["values"]), (A5, {"to": W8, "assignment": 1, "request_kind": "小さな PR", "waiting_issue": A9, "waiting_declaration": 400}))
        self.assertIn("src/a.py", req["body"])
        self.assertEqual(out["signals"], [{"kind": "wait", "to": W7, "item": A9, "declaration": 400},
                                          {"kind": "request", "to": W8, "item": A5, "declaration": 400, "request_kind": "小さな PR"}])

    def test_small_pr_request_is_not_repeated_and_reported_pr_is_transcribed(self):
        """相手の項目に同じ待機する Issue への `依頼` (小さな PR) が既にあれば新しい依頼を出さず、`小さな PR の報告` があれば PR を `待機` の理由に写す
        (修正で宣言の ID が変わっても、前の依頼と報告を使う)。"""
        rec = rec_with(questions=question("conflict", A9, f"{A5}:410", "small-pr"))
        other = item(A5, B_GO + [mcomment("依頼", {"to": W8, "assignment": 1, "request_kind": "小さな PR", "waiting_issue": A9, "waiting_declaration": 399}, t(15), 512),
                                 wcomment("小さな PR の報告", {"waiting_issue": A9, "waiting_declaration": 399}, t(16), 513, body=PR9, sid=W8)])
        out = run_judge([item(A9, [ASSIGN1, decl(400, t(20))]), other], rec=rec)
        self.assertEqual(out["judgments"][0]["waits"], [{"kind": "小さな PR", "issue": A5, "pr": PR9}])
        self.assertEqual(kinds(out["actions"]), [("comment", "待機"), ("blocked-by-add",), ("set-status",)])
        self.assertEqual([s["kind"] for s in out["signals"]], ["wait"])

    def test_answer_proceed_goes(self):
        """回答が proceed なら競合しうるまま `開始可`。"""
        rec = rec_with(questions=question("conflict", A9, f"{A5}:410", "proceed"))
        out = run_judge([item(A9, [ASSIGN1, decl(400, t(20))]), item(A5, B_GO)], rec=rec)
        self.assertEqual(out["judgments"][0]["result"], "go")
        self.assertEqual(kinds(out["actions"]), [("comment", "開始可")])
        self.assertEqual(out["actions"][0]["values"], {"to": W7, "assignment": 1, "declaration": 400})
        self.assertEqual(out["signals"], [{"kind": "go", "to": W7, "item": A9, "declaration": 400}])

    def test_mixed_others_list_all_waits_and_ask_for_the_unanswered(self):
        """相手が 2 つで、1 つは wait と回答済み、1 つは未回答なら、`待機` の理由に `利用者の回答` と `Issue` を並べ、未回答の相手だけ質問する。"""
        c_go = [assign(W9, 1, t(10), 120), decl(420, t(11), to=W9), go(420, t(12), 520, to=W9)]
        rec = rec_with(questions=question("conflict", A9, f"{A5}:410", "wait"))
        out = run_judge([item(A9, [ASSIGN1, decl(400, t(20))]), item(A5, B_GO), item(A6, c_go)], rec=rec)
        j = out["judgments"][0]
        self.assertEqual((j["result"], j["waits"]), ("ask", [{"kind": "利用者の回答"}, {"kind": "Issue", "issue": A5}]))
        self.assertEqual([q["subject"] for q in out["questions"]], [f"{A6}:420"])
        self.assertEqual(kinds(out["actions"]), [("comment", "待機"), ("blocked-by-add",), ("set-status",)])

    def test_needs_user_asks_whether_unknown_content_path_conflicts(self):
        """種類 unknown-content の同じパスは、競合しうるかを利用者に質問する (相手の宣言とパスが対象)。"""
        other = [assign(W8, 1, t(10), 110), decl(410, t(11), files=(("data/x.bin", None),), to=W8), go(410, t(12), 510, to=W8)]
        out = run_judge([item(A9, [ASSIGN1, decl(400, t(20), files=(("data/x.bin", None),))]), item(A5, other)])
        self.assertEqual(out["judgments"][0]["result"], "ask")
        self.assertEqual([(q["kind"], q["subject"], q["options"]) for q in out["questions"]],
                         [("unknown-content", f"{A5}:410:data/x.bin", ["conflict", "none"])])

    def test_unknown_content_answers(self):
        """unknown-content の回答が conflict なら、その相手について 3 つの扱いを質問する。none なら競合しないとして `開始可`。"""
        other = [assign(W8, 1, t(10), 110), decl(410, t(11), files=(("data/x.bin", None),), to=W8), go(410, t(12), 510, to=W8)]
        items = [item(A9, [ASSIGN1, decl(400, t(20), files=(("data/x.bin", None),))]), item(A5, other)]
        out = run_judge(items, rec=rec_with(questions=question("unknown-content", A9, f"{A5}:410:data/x.bin", "conflict")))
        self.assertEqual((out["judgments"][0]["result"], [q["kind"] for q in out["questions"]]), ("ask", ["conflict"]))
        out = run_judge(items, rec=rec_with(questions=question("unknown-content", A9, f"{A5}:410:data/x.bin", "none")))
        self.assertEqual((out["judgments"][0]["result"], out["questions"]), ("go", []))

    def test_other_with_conflict_path_is_not_asked_unknown_content(self):
        """同じ相手に競合しうるパスと unknown-content のパスの両方があれば、3 つの扱いだけを質問する。"""
        other = [assign(W8, 1, t(10), 110), decl(410, t(11), files=(("data/x.bin", None), ("src/a.py", None)), to=W8), go(410, t(12), 510, to=W8)]
        out = run_judge([item(A9, [ASSIGN1, decl(400, t(20), files=(("data/x.bin", None), ("src/a.py", None)))]), item(A5, other)])
        self.assertEqual([q["kind"] for q in out["questions"]], ["conflict"])


class ResourceTest(unittest.TestCase):

    def setUp(self):
        self.attrs, _ = resources.attributes({"db": {"when_busy": "wait"}, "gpu": {"when_busy": "ask"}, "cache": {"release_undeclared": "release"}})

    def _holder(self, name):
        """項目 A5 が資源 name を割り当てのラベルで予約している。"""
        return item(A5, [assign(W8, 1, t(10), 110)], labels=[f"resource:{name}"],
                    events=[{"type": "LabeledEvent", "at": t(9), "label": f"resource:{name}"}])

    def test_busy_resource_with_when_busy_wait_waits(self):
        """空いていない資源の when_busy が wait なら `待機` (理由 `資源`)。Status は変えず、空いている資源も予約しない。"""
        out = run_judge([item(A9, [ASSIGN1, decl(400, t(20), resources=("db", "gpu"))]), self._holder("db")], attrs=self.attrs)
        j = out["judgments"][0]
        self.assertEqual((j["result"], j["waits"], j["reserve"]), ("wait", [{"kind": "資源", "resource": "db"}], []))
        self.assertEqual(kinds(out["actions"]), [("comment", "待機")])

    def test_busy_resource_with_when_busy_ask_asks_then_follows_answer(self):
        """when_busy が ask なら質問して `待機` (理由 `利用者の回答`)。回答が wait なら `待機` (理由 `資源`)、proceed なら `開始可` で予約する。"""
        items = [item(A9, [ASSIGN1, decl(400, t(20), resources=("gpu",))]), self._holder("gpu")]
        out = run_judge(items, attrs=self.attrs)
        self.assertEqual((out["judgments"][0]["result"], out["judgments"][0]["waits"]), ("ask", [{"kind": "利用者の回答"}]))
        self.assertEqual([(q["kind"], q["subject"], q["options"]) for q in out["questions"]], [("resource-busy", "gpu", ["wait", "proceed"])])
        out = run_judge(items, rec=rec_with(questions=question("resource-busy", A9, "gpu", "wait")), attrs=self.attrs)
        self.assertEqual((out["judgments"][0]["result"], out["judgments"][0]["waits"]), ("wait", [{"kind": "資源", "resource": "gpu"}]))
        out = run_judge(items, rec=rec_with(questions=question("resource-busy", A9, "gpu", "proceed")), attrs=self.attrs)
        self.assertEqual((out["judgments"][0]["result"], out["judgments"][0]["reserve"]), ("go", ["gpu"]))

    def test_busy_answer_is_read_only_until_the_item_releases_the_resource(self):
        """resource-busy の回答は、その項目がその資源を解放するまで読む。解放した後に足し直した更新では (持ち主が同じでも) 読まずに質問を出す。
        `開始可` の前の修正や、`開始可` の後の更新の出し直し (解放していない) では読む。"""
        holder = self._holder("gpu")
        rec = rec_with(questions=question("resource-busy", A9, "gpu", "proceed", asked=t(21)))
        rec["questions"]["q1"]["answered_at"] = t(22)
        # 修正 (`開始可` の前): 400 が差し戻され 401 で gpu をもう一度宣言。解放していないので回答を読む
        rewrite = item(A9, [ASSIGN1, decl(400, t(20), resources=("gpu",)), wait(400, t(21), 500, [{"kind": "利用者の回答"}]),
                            mcomment("依頼", {"to": W7, "assignment": 1, "request_kind": "宣言の修正", "declaration": 400}, t(23), 501),
                            decl(401, t(24), resources=("gpu",), kind="宣言の更新")])
        out = run_judge([rewrite, holder], rec=rec, attrs=self.attrs)
        self.assertEqual((out["judgments"][0]["result"], out["judgments"][0]["reserve"], out["questions"]), ("go", ["gpu"], []))
        # 解放の後の足し直し: 400 [gpu] に `開始可`、401 で外し、402 で足し直す。持ち主は同じでも質問を出す
        readd = item(A9, [ASSIGN1, decl(400, t(20), resources=("gpu",)), go(400, t(23), 500), decl(401, t(24), resources=(), kind="宣言の更新"),
                          decl(402, t(25), resources=("gpu",), kind="宣言の更新")])
        states = states_of([readd, holder], attrs=self.attrs)
        self.assertTrue(judge.released_since(states[0], "gpu", t(22)))
        self.assertEqual(judge.busy_answers(states[0], rec, ["gpu"]), {})
        out = run_judge([readd, holder], rec=rec, attrs=self.attrs)
        self.assertEqual((out["judgments"][0]["result"], [q["kind"] for q in out["questions"]]), ("ask", ["resource-busy"]))
        # `開始可` の後の更新の出し直し: 400 [] に `開始可`、401 [gpu] が差し戻され、402 [gpu] を出し直す。解放していないので回答を読む
        redo = item(A9, [ASSIGN1, decl(400, t(20)), go(400, t(21), 500), decl(401, t(23), resources=("gpu",), kind="宣言の更新"),
                         mcomment("依頼", {"to": W7, "assignment": 1, "request_kind": "宣言の修正", "declaration": 401}, t(24), 501),
                         decl(402, t(25), resources=("gpu",), kind="宣言の更新")])
        out = run_judge([redo, holder], rec=rec, attrs=self.attrs)
        self.assertEqual((out["judgments"][0]["result"], out["judgments"][0]["reserve"], out["questions"]), ("go", ["gpu"], []))

    def test_questions_of_a_previous_assignment_are_not_read(self):
        """前の割り当ての回答 (resource-busy・conflict) と未回答の質問は、新しい割り当ての判定で読まない (割り当てが終了すれば資源・宣言・相手が新しくなる)。"""
        release = mcomment("解放", {"to": W7, "assignment": 1, "release_reason": "解除"}, t(100), 150)
        prev = [ASSIGN1, decl(400, t(20), resources=("gpu",)), go(400, t(23), 500), release]
        assign2 = mcomment("割り当て", {"to": W7, "assignment": 2}, t(200), 200)
        # 前の割り当てで proceed と回答した gpu: 新しい割り当ての宣言では質問する
        rec = rec_with(questions=question("resource-busy", A9, "gpu", "proceed", asked=t(21)))
        mine = item(A9, prev + [assign2, decl(700, t(210), resources=("gpu",))])
        out = run_judge([mine, self._holder("gpu")], rec=rec, attrs=self.attrs)
        self.assertEqual((out["judgments"][0]["assignment"], out["judgments"][0]["result"], [q["kind"] for q in out["questions"]]), (2, "ask", ["resource-busy"]))
        # 前の割り当ての未回答の質問が残っていても、新しい割り当てでは質問を出す
        rec = rec_with(questions=question("conflict", A9, f"{A5}:410", asked=t(21)))
        mine = item(A9, prev + [assign2, decl(700, t(210))])
        out = run_judge([mine, item(A5, B_GO)], rec=rec, attrs=self.attrs)
        self.assertEqual((out["judgments"][0]["result"], [q["kind"] for q in out["questions"]]), ("ask", ["conflict"]))
        # 前の割り当てで wait と回答した相手: 新しい割り当てでは読まずに質問する
        rec = rec_with(questions=question("conflict", A9, f"{A5}:410", "wait", asked=t(21)))
        out = run_judge([mine, item(A5, B_GO)], rec=rec, attrs=self.attrs)
        self.assertEqual((out["judgments"][0]["result"], [q["kind"] for q in out["questions"]]), ("ask", ["conflict"]))

    def test_resources_are_not_judged_while_conflict_waits(self):
        """競合の可能性で待機する・質問する宣言は、資源の空きを確認しない (待機している宣言は新しい資源を持たない)。"""
        out = run_judge([item(A9, [ASSIGN1, decl(400, t(20), resources=("gpu",))]), item(A5, B_GO), self._holder("gpu")], attrs=self.attrs)
        self.assertEqual([q["kind"] for q in out["questions"]], ["conflict"])
        self.assertEqual(out["judgments"][0]["reserve"], [])

    def test_undeclared_reservation_release_attribute_releases_on_go(self):
        """予約したのに宣言に無い資源の release_undeclared が release なら、`開始可` と一緒に解放する。"""
        mine = item(A9, [ASSIGN1, decl(400, t(20))], labels=["resource:cache"], events=[{"type": "LabeledEvent", "at": t(9), "label": "resource:cache"}])
        out = run_judge([mine], attrs=self.attrs)
        j = out["judgments"][0]
        self.assertEqual((j["result"], j["release"], j["keep"]), ("go", ["cache"], []))

    def test_undeclared_reservation_ask_goes_and_asks_after(self):
        """release_undeclared が ask なら、ほかの判定が済んでいれば `開始可` を書いてから質問し、回答まで予約を残す (KTD8)。"""
        mine = item(A9, [ASSIGN1, decl(400, t(20))], labels=["resource:db"], events=[{"type": "LabeledEvent", "at": t(9), "label": "resource:db"}])
        out = run_judge([mine], attrs=self.attrs)
        j = out["judgments"][0]
        self.assertEqual((j["result"], j["release"], j["keep"]), ("go", [], ["db"]))
        self.assertEqual(kinds(out["actions"]), [("comment", "開始可")])
        self.assertEqual([(q["kind"], q["subject"], q["options"]) for q in out["questions"]], [("release-undeclared", "db", ["release", "keep"])])
        out = run_judge([mine], rec=rec_with(questions=question("release-undeclared", A9, "db", "release")), attrs=self.attrs)
        self.assertEqual((out["judgments"][0]["result"], out["judgments"][0]["release"], out["questions"]), ("go", ["db"], []))

    def test_undeclared_reservation_keep_answer_requests_rewrite(self):
        """解放してはいけないと回答した資源は、予約を残して `依頼` (宣言の修正: その資源を足す)。`開始可` は書かない。"""
        mine = item(A9, [ASSIGN1, decl(400, t(20))], labels=["resource:db"], events=[{"type": "LabeledEvent", "at": t(9), "label": "resource:db"}])
        out = run_judge([mine], rec=rec_with(questions=question("release-undeclared", A9, "db", "keep")), attrs=self.attrs)
        j = out["judgments"][0]
        self.assertEqual((j["result"], j["keep"], j["release"]), ("request", ["db"], []))
        self.assertEqual(kinds(out["actions"]), [("comment", "依頼")])
        self.assertIn("db", out["actions"][0]["body"])
        self.assertEqual(out["signals"][0]["kind"], "request")

    def test_undeclared_reservation_is_handled_while_waiting(self):
        """宣言に無い予約の扱いは判定の結果に依らない: 競合や資源で待機する宣言でも、release なら解放し、ask なら質問し、keep の回答なら `依頼` にする。"""
        events = [{"type": "LabeledEvent", "at": t(9), "label": f"resource:{n}"} for n in ("cache", "db")]
        mine = item(A9, [ASSIGN1, decl(400, t(20), resources=("gpu",))], labels=["resource:cache", "resource:db"], events=events)
        # 競合で質問する
        out = run_judge([mine, item(A5, B_GO)], attrs=self.attrs)
        j = out["judgments"][0]
        self.assertEqual((j["result"], j["release"], j["keep"]), ("ask", ["cache"], ["db"]))
        self.assertEqual(sorted(q["kind"] for q in out["questions"]), ["conflict", "release-undeclared"])
        self.assertEqual(kinds(out["actions"]), [("comment", "待機")])
        self.assertIn("解放した資源 (宣言に無い予約・更新で外した資源): cache", out["actions"][0]["body"])
        # 資源で待機する
        out = run_judge([mine, self._holder("gpu")], rec=rec_with(questions=question("resource-busy", A9, "gpu", "wait")), attrs=self.attrs)
        j = out["judgments"][0]
        self.assertEqual((j["result"], j["waits"], j["release"], j["keep"]), ("wait", [{"kind": "資源", "resource": "gpu"}], ["cache"], ["db"]))
        self.assertEqual([q["kind"] for q in out["questions"]], ["release-undeclared"])
        # keep の回答があれば、競合しうる相手がいても修正を頼んで終了する
        out = run_judge([mine, item(A5, B_GO)], rec=rec_with(questions=question("release-undeclared", A9, "db", "keep")), attrs=self.attrs)
        self.assertEqual((out["judgments"][0]["result"], kinds(out["actions"])), ("request", [("comment", "依頼")]))

    def test_undeclared_reservation_is_handled_before_config_and_form_checks(self):
        """宣言に無い予約の扱いは、リポジトリの設定が読めないときも、規則での形の誤りのときも行い、結果と本文に載せる (資源の使用と食い違わないため)。"""
        events = [{"type": "LabeledEvent", "at": t(9), "label": f"resource:{n}"} for n in ("cache", "db")]
        mine = item(A9, [ASSIGN1, decl(400, t(20), files=(("src/a.py", [["f"]]),), resources=("gpu",))], labels=["resource:cache", "resource:db"], events=events)
        out = run_judge([mine], read=reader(UNREADABLE_CONFIG), attrs=self.attrs)
        j = out["judgments"][0]
        self.assertEqual((j["result"], j["waits"], j["release"], j["keep"]), ("wait", [{"kind": "設定"}], ["cache"], ["db"]))
        self.assertEqual([q["kind"] for q in out["questions"]], ["release-undeclared"])
        self.assertIn("解放した資源 (宣言に無い予約・更新で外した資源): cache", out["actions"][0]["body"])
        self.assertIn("回答を待機する予約 (宣言に無い資源。解放してよいか利用者に質問している): db", out["actions"][0]["body"])
        out = run_judge([mine], read=reader(ok_config([{"pattern": "src/**", "kind": "unknown-structure"}])), attrs=self.attrs)
        j = out["judgments"][0]
        self.assertEqual((j["result"], j["release"], j["keep"], kinds(out["actions"])), ("request", ["cache"], ["db"], [("comment", "依頼")]))
        self.assertIn("files[0].units", out["actions"][0]["body"])
        self.assertIn("解放した資源 (宣言に無い予約・更新で外した資源): cache", out["actions"][0]["body"])
        out = run_judge([mine], rec=rec_with(questions=question("release-undeclared", A9, "db", "keep")), attrs=self.attrs)
        self.assertEqual((out["judgments"][0]["result"], out["judgments"][0]["release"]), ("request", ["cache"]))
        self.assertIn("資源 db は", out["actions"][0]["body"])
        self.assertIn("解放した資源 (宣言に無い予約・更新で外した資源): cache", out["actions"][0]["body"], "修正の依頼の本文にも解放した資源を書く")
        unreadable = item(A9, [ASSIGN1, decl(400, t(20), body="宣言です")], labels=["resource:cache"], events=events[:1])
        out = run_judge([unreadable], attrs=self.attrs)
        self.assertEqual((out["judgments"][0]["result"], out["judgments"][0]["release"]), ("request", []), "JSON が読めない宣言は資源も分からないので解放しない")
        self.assertEqual(judge.usage_for(states_of([unreadable], attrs=self.attrs), None, self.attrs), {"cache": [A9]})

    def test_release_while_waiting_frees_the_resource_for_later_declarations_and_usage(self):
        """待機する宣言が解放した予約は、同じ実行の後の宣言と usage_for の両方で使用中でなくなる。"""
        events = [{"type": "LabeledEvent", "at": t(9), "label": "resource:cache"}]
        a = item(A9, [ASSIGN1, decl(400, t(20))], labels=["resource:cache"], events=events, position=1)
        b = item(A5, B_GO, position=2)  # A9 と競合しうる相手
        c = item(A6, [assign(W9, 1, t(10), 120), decl(420, t(21), files=(("src/c.py", None),), resources=("cache",), to=W9)], position=3)
        states = states_of([a, b, c], attrs=self.attrs)
        self.assertEqual(judge.usage_for(states, None, self.attrs), {}, "着手の宣言に無い予約 (属性 release) は `開始可` の前でも数えない")
        out = run_judge([a, b, c], attrs=self.attrs)
        self.assertEqual([(j["item"], j["result"]) for j in out["judgments"]], [(A9, "ask"), (A6, "go")])
        self.assertEqual(out["judgments"][1]["reserve"], ["cache"])

    def test_released_reservation_added_back_by_rewrite_is_checked_for_availability(self):
        """待機する間に解放した予約 (属性 release) を修正で足し直すと、予約済みとは扱わず空きを確認する。別の項目が持っていれば `待機` (理由 `資源`)。"""
        events = [{"type": "LabeledEvent", "at": t(9), "label": "resource:cache"}]
        mine = item(A9, [ASSIGN1, decl(400, t(20)), wait(400, t(21), 500, [{"kind": "利用者の回答"}]),
                         mcomment("依頼", {"to": W7, "assignment": 1, "request_kind": "宣言の修正", "declaration": 400}, t(22), 501),
                         decl(401, t(23), files=(("src/z.py", None),), resources=("cache",), kind="宣言の更新")], labels=["resource:cache"], events=events)
        holder = item(A6, [assign(W9, 1, t(10), 120), decl(420, t(11), files=(("src/c.py", None),), resources=("cache",), to=W9), go(420, t(12), 520, to=W9)])
        states = states_of([mine, holder], attrs=self.attrs)
        self.assertEqual(judge.released_reservations(states[0], None, self.attrs), ["cache"], "宣言 400 に無かったので解放した")
        self.assertEqual(judge.released_reservations(states[0], None, self.attrs, before=400), [], "400 より前の宣言は無い")
        self.assertEqual(judge.usage_for(states, None, self.attrs), {"cache": [A6]})
        out = run_judge([mine, holder], attrs=self.attrs)
        j = out["judgments"][0]
        self.assertEqual((j["declaration"], j["result"], j["waits"], j["reserve"]), (401, "wait", [{"kind": "資源", "resource": "cache"}], []))
        # 足し直した宣言が `開始可` になれば持っている (前の宣言に無かったことは解放とみなさない)
        gone = item(A9, mine["comments"] + [go(401, t(24), 502)], labels=["resource:cache"], events=events)
        states = states_of([gone], attrs=self.attrs)
        self.assertEqual(states[0]["declaration"]["held"], ["cache"])
        self.assertEqual(judge.released_reservations(states[0], None, self.attrs), [])
        self.assertEqual(judge.usage_for(states, None, self.attrs), {"cache": [A9]})

    def test_resource_removed_by_update_after_go_is_released_regardless_of_attribute(self):
        """ラベルで予約した資源 (属性はデフォルト値 ask) を着手の宣言に書いて `開始可` になり、更新で外した後は、使用に数えない (契機 update は結果に依らず解放する)。
        宣言に書かれなかった予約 (ask) は回答まで数える。"""
        events = [{"type": "LabeledEvent", "at": t(9), "label": f"resource:{n}"} for n in ("db", "gpu")]
        base = [ASSIGN1, decl(400, t(11), resources=("db",)), go(400, t(12), 500)]
        for update in (decl(401, t(13), resources=(), kind="宣言の更新"),  # 資源を外すだけ (判定しない)
                       decl(401, t(13), files=(("src/b.py", None),), resources=(), kind="宣言の更新")):  # ファイルも変える (判定の要る更新)
            mine = item(A9, base + [update], labels=["resource:db", "resource:gpu"], events=events)
            states = states_of([mine], attrs=self.attrs)
            self.assertEqual((states[0]["declaration"]["held"], states[0]["reserved"]), ([], ["db", "gpu"]))
            self.assertEqual(judge.released_reservations(states[0], None, self.attrs), ["db"], "db は外した (無条件)。gpu は宣言に無い予約 (ask) で回答待ち")
            self.assertEqual(judge.usage_for(states, None, self.attrs), {"gpu": [A9]})
        other = item(A5, [assign(W8, 1, t(10), 110), decl(410, t(20), files=(("src/c.py", None),), resources=("db",), to=W8)])
        out = run_judge([mine, other], attrs=self.attrs)
        self.assertEqual([(j["item"], j["result"]) for j in out["judgments"]], [(A9, "go"), (A5, "go")])
        self.assertEqual(out["judgments"][1]["reserve"], ["db"])
        # 外した後に、その資源を含まない別の更新が `開始可` になっても (最新の `開始可` の宣言に db が無い)、外した db は解放したまま
        later = item(A9, base + [decl(401, t(13), resources=(), kind="宣言の更新"), decl(402, t(14), files=(("src/b.py", None),), resources=(), kind="宣言の更新"),
                              go(402, t(15), 502)], labels=["resource:db", "resource:gpu"], events=events)
        states = states_of([later], attrs=self.attrs)
        self.assertEqual((states[0]["declaration"]["go_declaration_id"], states[0]["declaration"]["held"]), (402, []))
        self.assertEqual(judge.released_reservations(states[0], None, self.attrs), ["db"])
        self.assertEqual(judge.usage_for(states, None, self.attrs), {"gpu": [A9]})

    def test_update_adds_resource_and_releases_removed(self):
        """`開始可` の後の更新は、足した資源の空きを確認し、外した資源を解放する。"""
        mine = item(A9, [ASSIGN1, decl(400, t(11), resources=("db",)), go(400, t(12), 500), decl(401, t(13), resources=("gpu",), kind="宣言の更新")])
        out = run_judge([mine], attrs=self.attrs)
        j = out["judgments"][0]
        self.assertEqual((j["result"], j["reserve"], j["release"]), ("go", ["gpu"], ["db"]))

    def test_usage_excludes_released_undeclared_reservations(self):
        """資源の使用は、`開始可` の後に宣言に無い予約を、解放する (属性 release か回答 release) ものを除いて数える。"""
        mine = item(A9, [ASSIGN1, decl(400, t(11)), go(400, t(12), 500)], labels=["resource:cache", "resource:db", "resource:gpu"],
                    events=[{"type": "LabeledEvent", "at": t(9), "label": f"resource:{n}"} for n in ("cache", "db", "gpu")])
        rec = rec_with(questions=question("release-undeclared", A9, "db", "release"))
        usage = judge.usage_for(states_of([mine], attrs=self.attrs), rec, self.attrs)
        self.assertEqual(usage, {"gpu": [A9]})

    def test_go_in_the_same_run_makes_the_resource_busy_for_later_declarations(self):
        """同じ実行で先に `開始可` にした宣言の資源は、後の宣言には空いていない。"""
        a = item(A9, [ASSIGN1, decl(400, t(20), resources=("db",))], position=1)
        b = item(A5, [assign(W8, 1, t(10), 110), decl(410, t(21), files=(("src/b.py", None),), resources=("db",), to=W8)], position=2)
        out = run_judge([a, b], attrs=self.attrs)
        self.assertEqual([(j["result"], j["waits"]) for j in out["judgments"]], [("go", []), ("wait", [{"kind": "資源", "resource": "db"}])])


class RecompareTest(unittest.TestCase):

    def test_resources_only_update_after_ready_for_review_is_not_recompared(self):
        """ready for review の後の資源だけを変える更新は比べ直さず、競合しうる `開始可` の宣言があっても `開始可` (AE54)。"""
        mine = item(A9, [ASSIGN1, decl(400, t(11)), go(400, t(12), 500), wcomment("PR の報告", None, t(13), 501, body=PR9),
                         decl(401, t(14), resources=("db",), kind="宣言の更新")], status="In review")
        pr = {PR9: observed(PR9)}
        out = run_judge([mine, item(A5, B_GO)], pr_states=pr)
        j = out["judgments"][0]
        self.assertEqual((j["result"], j["compared"], j["recompared"]), ("go", [], False))

    def test_full_update_after_ready_for_review_is_recompared(self):
        """ファイルを変える更新は、ready for review の後でも比べ直す。"""
        mine = item(A9, [ASSIGN1, decl(400, t(11), files=(("src/b.py", None),)), go(400, t(12), 500), wcomment("PR の報告", None, t(13), 501, body=PR9),
                         decl(401, t(14), kind="宣言の更新")], status="In review")
        out = run_judge([mine, item(A5, B_GO)], pr_states={PR9: observed(PR9)})
        self.assertEqual((out["judgments"][0]["result"], out["judgments"][0]["recompared"]), ("ask", True))


class RewriteTest(unittest.TestCase):
    """判定を待機する宣言の修正 (計画の U15 の Approach 2)。"""

    def _rewritten(self, new_files=(("src/a.py", None),), other_go=True):
        """宣言 400 が相手 A5 (410) との競合で wait と回答でき `待機` → blockedBy A5・Blocked。`依頼` の後に修正した宣言が 401。"""
        mine = item(A9, [ASSIGN1, decl(400, t(20)), wait(400, t(21), 500, [{"kind": "Issue", "issue": A5}]),
                         mcomment("依頼", {"to": W7, "assignment": 1, "request_kind": "宣言の修正", "declaration": 400}, t(22), 501),
                         decl(401, t(23), files=new_files, kind="宣言の更新")],
                    status="Blocked", blocked_by=[{"key": A5, "url": "", "state": "OPEN"}],
                    events=[{"type": "ProjectV2ItemStatusChangedEvent", "at": t(21), "status": "Blocked", "previous_status": "In Progress",
                             "was_automated": False, "project_number": PROJECT_NUMBER}])
        return [mine] + ([item(A5, B_GO)] if other_go else [])

    def test_rewrite_reuses_answer_for_the_same_other(self):
        """新しい宣言も同じ相手と競合しうるなら、前の宣言への回答 (相手で対応づける) を使い、質問し直さない。blockedBy は残す。"""
        rec = rec_with(questions=question("conflict", A9, f"{A5}:410", "wait"))
        out = run_judge(self._rewritten(), rec=rec)
        j = out["judgments"][0]
        self.assertEqual((j["declaration"], j["result"], j["waits"]), (401, "wait", [{"kind": "Issue", "issue": A5}]))
        self.assertEqual(out["questions"], [])
        self.assertEqual(kinds(out["actions"]), [("comment", "待機")], "blockedBy と Blocked は既にあるので書かない")

    def test_rewrite_asks_only_for_new_other(self):
        """新しい相手だけ質問する。"""
        c_go = [assign(W9, 1, t(10), 120), decl(420, t(11), to=W9), go(420, t(12), 520, to=W9)]
        rec = rec_with(questions=question("conflict", A9, f"{A5}:410", "wait"))
        out = run_judge(self._rewritten() + [item(A6, c_go)], rec=rec)
        self.assertEqual([q["subject"] for q in out["questions"]], [f"{A6}:420"])
        self.assertEqual(out["judgments"][0]["waits"], [{"kind": "利用者の回答"}, {"kind": "Issue", "issue": A5}])

    def test_rewrite_without_the_old_other_goes_and_restores(self):
        """新しい宣言がどの相手とも競合しなければ `開始可`。前の `待機` のために書いた Blocked を In Progress に戻し、足した blockedBy は外す候補にする。"""
        out = run_judge(self._rewritten(new_files=(("src/c.py", None),)))
        j = out["judgments"][0]
        self.assertEqual(j["result"], "go")
        self.assertEqual(kinds(out["actions"]), [("comment", "開始可"), ("set-status",), ("blocked-by-remove",)])
        self.assertEqual((out["actions"][1]["status"], out["actions"][2]["blocker"], out["actions"][2]["needs_approval"]), ("In Progress", A5, True))

    def test_rewrite_waiting_for_new_other_only_replaces_blocked_by(self):
        """前の相手を待機しなくなり、別の相手を待機するなら、新しい相手を足し、前の相手は外す候補。Status は Blocked のまま。"""
        c_go = [assign(W9, 1, t(10), 120), decl(420, t(11), files=(("src/c.py", None),), to=W9), go(420, t(12), 520, to=W9)]
        rec = rec_with(questions=question("conflict", A9, f"{A6}:420", "wait"))
        out = run_judge(self._rewritten(new_files=(("src/c.py", None),)) + [item(A6, c_go)], rec=rec)
        self.assertEqual(kinds(out["actions"]), [("comment", "待機"), ("blocked-by-add",), ("blocked-by-remove",)])
        self.assertEqual((out["actions"][1]["blocker"], out["actions"][2]["blocker"]), (A6, A5))


class CliTest(FakeGhCase):

    def setUp(self):
        super().setUp()
        self.manager = os.path.join(self.root, "manager")
        self.clone = os.path.join(self.root, "clone")
        make_clone(self.clone, origin_url="git@github.com:akm/issue-dispatch-verify-a.git",
                   config_on_default={"files": [{"pattern": "src/**", "kind": "unknown-structure"}]})
        os.makedirs(os.path.dirname(os.path.join(self.manager, config.CONFIG_PATH)))
        self.write_config({"project": {"owner": "akm", "number": 3}, "record_dir": "rec", "repositories": {A: self.clone}})

    def write_config(self, cfg):
        with open(os.path.join(self.manager, config.CONFIG_PATH), "w", encoding="utf-8") as f:
            json.dump(cfg, f)

    def cli(self, *args):
        r = subprocess.run([sys.executable, _CLI, *args], capture_output=True, text=True, env=dict(os.environ))
        return r.returncode, json.loads(r.stdout) if r.stdout.strip() else None, r.stderr

    def _item3(self, nodes, extra):
        c = node_of(nodes, 3)["content"]
        c["assignees"]["nodes"] = [{"login": LOGIN}]
        for fv in node_of(nodes, 3)["fieldValues"]["nodes"]:
            if fv and (fv.get("field") or {}).get("name") == "Agent session ID":
                fv["text"] = W7
        c["comments"]["nodes"] += [gql_comment(x) for x in extra]

    def test_declaration_judge_cli_returns_judgments_without_writing(self):
        """declaration judge は、Project の項目から判定し、judgments・actions・questions・signals を返して書かない。リポジトリの設定は clone から読む。"""
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": items_data(lambda nodes: self._item3(nodes, [ASSIGN1, decl(400, t(20), files=(("src/a.py", [["f"]]),))]))}])
        code, out, err = self.cli("declaration", "judge", "--dir", self.manager)
        self.assertEqual((code, out["status"], out["errors"]), (0, "ok", []), err)
        self.assertEqual([(j["item"], j["declaration"], j["result"], j["repo_config"]) for j in out["judgments"]], [(f"{A}#3", 400, "request", "ok")])
        self.assertEqual(kinds(out["actions"]), [("comment", "依頼")])
        self.assertIn("src/**", out["actions"][0]["body"], "clone の設定の規則で検査した")
        self.assertEqual(out["signals"][0]["kind"], "request")
        self.assertFalse(any("mutation" in (r.get("stdin") or "") for r in self.recorded_full()), "書き込みの gh を実行しない")

    def test_declaration_judge_cli_rejects_bad_or_missing_issue(self):
        """--issue が参照の形でなければ gh を読まずに errors、Project に無い項目なら rejected。どちらも全項目を判定しない。"""
        code, out, err = self.cli("declaration", "judge", "--dir", self.manager, "--issue", "#3")
        self.assertEqual((code, out["status"], out["errors"][0]["key"], out["judgments"]), (0, "error", "issue", []), err)
        self.assertEqual(self.recorded_full(), [], "gh を実行しない")
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": items_data(lambda nodes: self._item3(nodes, [ASSIGN1, decl(400, t(20))]))}])
        code, out, err = self.cli("declaration", "judge", "--dir", self.manager, "--issue", f"{A}#999")
        self.assertEqual((code, out["status"], out["errors"][0]["key"], out["judgments"]), (0, "rejected", "issue", []), err)

    def test_declaration_judge_cli_waits_when_repository_is_not_configured(self):
        """設定の repositories に無いリポジトリの宣言は `待機` (理由 `設定`)。"""
        self.write_config({"project": {"owner": "akm", "number": 3}, "record_dir": "rec"})
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": items_data(lambda nodes: self._item3(nodes, [ASSIGN1, decl(400, t(20))]))}])
        code, out, err = self.cli("declaration", "judge", "--dir", self.manager, "--issue", f"{A}#3")
        self.assertEqual((code, out["status"]), (0, "ok"), err)
        self.assertEqual((out["judgments"][0]["result"], out["judgments"][0]["repo_config"], out["judgments"][0]["waits"]), ("wait", "unreadable", [{"kind": "設定"}]))


class DocTest(unittest.TestCase):

    def test_flow_doc_has_judgment_section_and_cli(self):
        with open(_FLOW, encoding="utf-8") as f:
            doc = f.read()
        self.assertIn("## 判定", doc)
        self.assertIn("`declaration judge --dir", doc)
        for word in ("judgments", "signals", "`blocked-by-remove`", "比べ直"):
            self.assertIn(word, doc)

    def test_question_kinds_are_documented(self):
        """判定の質問の種類と選択肢は flow.md の「判定」の表にある。記録の質問の `subject` は records.md に書かれている。"""
        with open(_FLOW, encoding="utf-8") as f:
            table = question_table(f.read(), "判定の質問の種類 (`kind`) と選択肢 (`options`)")
        self.assertEqual(question_kinds(table), set(judge.QUESTION_OPTIONS), "flow.md の判定の質問の表の種類とコードの種類が一致しない")
        for kind, options in judge.QUESTION_OPTIONS.items():
            row = question_row(table, kind)
            self.assertIsNotNone(row, f"質問の種類 {kind} が flow.md の判定の質問の表に無い")
            self.assertEqual(question_options_cell(row), options_text(options), f"質問の種類 {kind} の選択肢が flow.md の判定の質問の表の行と一致しない")
        with open(_RECORDS, encoding="utf-8") as f:
            self.assertIn("`subject`", f.read())

    def test_record_ask_accepts_subject_and_answer_for_reads_it(self):
        """記録の `ask` は任意の `subject` を受け、judge.answer_for は項目・種類・対象で回答を引く (取り下げた質問は数えない)。"""
        rec, errors = record.apply(record.new_record("akm/3"), [{"op": "ask", "question_id": "q1", "item": A9, "kind": "conflict", "options": ["wait", "small-pr", "proceed"], "at": t(1), "subject": f"{A5}:410"},
                                    {"op": "answer", "question_id": "q1", "answer": "wait", "at": t(2)},
                                    {"op": "ask", "question_id": "q2", "item": A9, "kind": "conflict", "options": ["wait"], "at": t(3), "subject": f"{A6}:420"},
                                    {"op": "withdraw", "question_id": "q2", "at": t(4)}])
        self.assertEqual(errors, [])
        self.assertEqual(rec["questions"]["q1"]["subject"], f"{A5}:410")
        self.assertEqual(judge.answer_for(rec, A9, "conflict", f"{A5}:410", t(0)), "wait")
        self.assertIsNone(judge.answer_for(rec, A9, "conflict", f"{A6}:420", t(0)), "取り下げた質問は回答に数えない")
        self.assertIsNone(judge.answer_for(rec, A9, "conflict", None, t(0)))
        self.assertIsNone(judge.answer_for(rec, A9, "conflict", f"{A5}:410", t(2)), "質問した時刻が割り当ての時刻より前の質問は読まない")
        _, errors = record.apply(rec, [{"op": "ask", "question_id": "q3", "item": A9, "kind": "conflict", "options": ["wait"], "at": t(5), "subject": ""}])
        self.assertEqual([e["message"] for e in errors], ["subject は空でない文字列 (質問の対象: 資源の名前・相手の宣言など)"])


if __name__ == "__main__":
    unittest.main()
