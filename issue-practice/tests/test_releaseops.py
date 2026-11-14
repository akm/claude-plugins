#!/usr/bin/env python3
"""リリース計画の計画案を GitHub に書く「示す」(release plan) と「実行する」(release apply) のテスト
(計画の U4・R38・R39・R40・KTD3・KTD5)。

状態を持つ偽の GitHub (ファイル `issue-practice/tests/fakegithub.py`) で、関数 `gh.run` を差し替える。途中で失敗させてから
同じ計画案でやり直し、済んでいない書き込みだけを行うことを確認する。
"""

import datetime
import os
import re
import tempfile
import unittest
from unittest import mock

from fakegh_case import HERE, FakeGhCase
from fakegithub import FakeGitHub

from issue_practice import bodies, gh, releaseops, releaseplan  # noqa: E402

REPO = "o/r"
NAME = "20261114-1200-release-plan-next.md"
NAME2 = "20261115-1200-release-plan-next.md"


def draft_text(rows, dests="なし", cancels="なし", kind="新しい計画", current=None, target="なし"):
    """rows は (#番号 かキー, 主題) の配列。current は (URL, 本文) か None。"""
    sources = f"- {current[0]} 本文の SHA-256: {bodies.body_sha256(current[1])}" if current else "- なし"
    table = "\n".join(f"| {i} | {ref} | {subject} |" for i, (ref, subject) in enumerate(rows, start=1))
    return (f"# 計画案: 次のリリース\n\n## 元にした Issue\n\n{sources}\n\n"
            f"## 対象\n\n- 種類: {kind}\n- リリース対象: {target}\n- 今の計画: {current[0] if current else 'なし'}\n\n"
            f"## リリースの順番\n\n| 順 | リリース Issue | 主題 |\n| --- | --- | --- |\n{table}\n\n"
            f"## Issue の入れ先\n\n{dests}\n\n## 取りやめるリリース\n\n{cancels}\n")


def dest_table(*pairs):
    return "| Issue | 入れるリリース |\n| --- | --- |\n" + "\n".join(f"| {a} | {b} |" for a, b in pairs)


def cancel_table(*rows):
    return "| リリース Issue | 理由 | メモの移し先 |\n| --- | --- | --- |\n" + "\n".join(f"| {a} | {b} | {c} |" for a, b, c in rows)


class ParseTest(unittest.TestCase):

    def parse(self, text, name=NAME):
        return releaseops.parse_plan(text, name, REPO)

    def test_reads_draft(self):
        parsed = self.parse(draft_text([("#3", "既存"), ("a", "新しい")], dests=dest_table(("#5", "a"), ("#6", "未定"))))
        self.assertEqual(parsed["errors"], [])
        self.assertEqual(parsed["kind"], "新しい計画")
        self.assertEqual([(r["number"], r["key"]) for r in parsed["rows"]], [(3, None), (None, "a")])
        self.assertEqual([(d["number"], d["value"]) for d in parsed["dests"]], [(5, "a"), (6, "未定")])

    def test_errors(self):
        url = "https://github.com/o/r/issues/30"
        cases = {
            "知らない種類": draft_text([("a", "x")], kind="大きな計画"),
            "入れ先が表に無い": draft_text([("a", "x")], dests=dest_table(("#5", "b"))),
            "入れ先がリリース Issue": draft_text([("#3", "x")], dests=dest_table(("#3", "#3"))),
            "キー plan": draft_text([("plan", "x")]),
            "急ぎで今の計画が無い": draft_text([("a", "x")], kind="急ぎのリリースの追加"),
            "急ぎで取りやめる": draft_text([("#3", "x"), ("a", "y")], kind="急ぎのリリースの追加", current=(url, "b"),
                                    cancels=cancel_table(("#4", "理由", "なし"))),
            "急ぎでキーが無い": draft_text([("#3", "x")], kind="急ぎのリリースの追加", current=(url, "b")),
            "取りやめるのが表にもある": draft_text([("#3", "x")], cancels=cancel_table(("#3", "理由", "なし"))),
            "今の計画が元にした Issue に無い": draft_text([("a", "x")]).replace("- 今の計画: なし", f"- 今の計画: {url}"),
            "節の順序": draft_text([("a", "x")]).replace("## Issue の入れ先", "## 入れ先"),
        }
        for name, text in cases.items():
            with self.subTest(name):
                self.assertTrue(self.parse(text)["errors"], name)


class ReleaseOpsCase(unittest.TestCase):

    def setUp(self):
        self.gh = FakeGitHub(REPO)
        patcher = mock.patch.object(gh, "run", self.gh.run)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(releaseops, "today", lambda: datetime.date(2026, 11, 14))
        patcher.start()
        self.addCleanup(patcher.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def write_draft(self, text, name=NAME):
        path = os.path.join(self._tmp.name, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def writes(self):
        reads = (["api", "user"], ["label", "list"], ["issue", "list"], ["issue", "view"], ["pr", "view"])
        return [c for c in self.gh.calls if c["args"][:2] not in reads
                and not (c["args"][0] == "api" and "-X" not in c["args"])]

    def find(self, pattern):
        return [n for n, i in self.gh.issues.items() if re.search(pattern, i["title"])]

    def released(self, subject, done=False):
        """主題 subject のリリース Issue とマイルストーンを、前もって作っておく。"""
        number = self.gh.add_issue("仮")
        self.gh.issues[number]["title"] = releaseplan.release_title(number, subject, draft=not done)
        milestone = self.gh.add_milestone(releaseplan.milestone_title(number, subject), f"リリース Issue: {self.gh.url(number)}")
        self.gh.issues[number]["body"] = f"## 参照\n\n- リリースマイルストーン: {self.gh.milestones[milestone]['html_url']}\n"
        return number, milestone

    def current_plan(self, rows, date="20261101"):
        body = "## リリースの順番\n\n" + releaseplan.render_table([{"number": n, "subject": s} for n, s in rows]) + "\n"
        self.gh.add_label("current")
        number = self.gh.add_issue(releaseplan.plan_title(date), body=body, labels=["current"])
        return number, body


class FirstPlanTest(ReleaseOpsCase):

    def setUp(self):
        super().setUp()
        self.gh.add_issue("要望 1")  # #1
        self.gh.add_issue("要望 2")  # #2
        self.path = self.write_draft(draft_text([("a", "バックアップ"), ("b", "絞り込み")],
                                                dests=dest_table(("#1", "a"), ("#2", "b"))))

    def test_plan_shows_steps_without_writing(self):
        result = releaseops.plan(self.path, REPO)
        self.assertEqual(result["status"], "ok", result["errors"])
        self.assertEqual(self.writes(), [], "示すときは書き込まない")
        self.assertEqual([l["name"] for l in result["labels_to_create"]], ["current"])
        self.assertEqual([(a["step"], a["action"]) for a in result["actions"]], [
            (0, "create-label"), (1, "create-plan"), (1, "record-approval"),
            (2, "create-release"), (2, "set-release-number"), (2, "create-milestone"), (2, "write-release-body"),
            (2, "create-release"), (2, "set-release-number"), (2, "create-milestone"), (2, "write-release-body"),
            (2, "set-milestone"), (2, "set-milestone"), (2, "write-plan-table"), (3, "add-current"),
            (5, "record-current-swap")], "古い計画が無いので、手順 4 と 6 は行わない")

    def test_apply_writes_first_plan(self):
        result = releaseops.apply(self.path, REPO)
        self.assertEqual(result["status"], "ok", result["errors"])
        plan = self.find("^📅 リリース計画 20261114$")
        self.assertEqual(len(plan), 1)
        plan = self.gh.issues[plan[0]]
        self.assertEqual(plan["labels"], ["current"])
        releases = self.find("🔖 リリース")
        self.assertEqual([self.gh.issues[n]["title"] for n in releases],
                         [f"[DRAFT] 🔖 リリース R{releases[0]} (バックアップ)", f"[DRAFT] 🔖 リリース R{releases[1]} (絞り込み)"],
                         "題名に番号を書き足す")
        for number in releases:
            milestone = next(m for m in self.gh.milestones.values() if m["title"].startswith(f"R{number} "))
            self.assertIn(self.gh.url(number), milestone["description"], "マイルストーンの説明にリリース Issue の URL")
            self.assertIn(milestone["html_url"], self.gh.issues[number]["body"], "リリース Issue の本文にマイルストーンの URL")
        self.assertEqual(self.gh.milestones[self.gh.issues[1]["milestone"]]["title"], f"R{releases[0]} (バックアップ)")
        self.assertEqual(self.gh.milestones[self.gh.issues[2]["milestone"]]["title"], f"R{releases[1]} (絞り込み)")
        rows = releaseplan.parse_table(plan["body"])["rows"]
        self.assertEqual([r["number"] for r in rows], releases)
        kinds = [c["body"].split("\n")[0] for c in self.gh.comments[plan["number"]]]
        self.assertEqual(kinds, [f"issue-practice: approval draft={NAME}", "issue-practice: current-swap date=2026-11-14"])
        # やり直しても、何も書かない
        before = len(self.writes())
        again = releaseops.apply(self.path, REPO)
        self.assertEqual(again["status"], "ok", again["errors"])
        self.assertEqual(again["done"], [])
        self.assertEqual(len(self.writes()), before)
        decided = releaseplan.current_and_next(REPO)
        self.assertEqual(decided["errors"], [], "作った計画から、今のリリースと次のリリースを決められる")
        self.assertEqual((decided["current"], decided["next"]["number"]), (None, releases[0]))

    def test_retry_after_failure_in_step_2(self):
        """手順 1・2 の途中 (2 つ目のマイルストーンを作るところ) で失敗させ、やり直すと、作り済みのものは作らない。"""
        created = []

        def fail(args):
            if args[:2] == ["api", f"repos/{REPO}/milestones"] and "POST" in args:
                created.append(args)
                return len(created) == 2
            return False
        self.gh.fail_when = fail
        result = releaseops.apply(self.path, REPO)
        self.assertEqual(result["status"], "gh_failed")
        self.assertEqual(result["done"][-1]["action"], "set-release-number")
        self.assertNotIn("current", sum((i["labels"] for i in self.gh.issues.values() if "リリース計画" in i["title"]), []),
                         "途中では、新しい計画に current が無い")
        shown = releaseops.plan(self.path, REPO)
        self.assertEqual(shown["status"], "ok", shown["errors"])
        self.assertEqual([a["action"] for a in shown["actions"]][:2], ["create-milestone", "write-release-body"],
                         "作り済みのリリース Issue は作らず、残りから行う")
        result = releaseops.apply(self.path, REPO)
        self.assertEqual(result["status"], "ok", result["errors"])
        self.assertEqual(len(self.find("リリース計画")), 1)
        self.assertEqual(len(self.find("🔖 リリース")), 2)
        self.assertEqual(len(self.gh.milestones), 2)


class SecondPlanTest(ReleaseOpsCase):

    def setUp(self):
        super().setUp()
        self.r1, self.m1 = self.released("バックアップ", done=True)
        self.gh.add_comment(self.r1, f"issue-practice: draft-removed date=2026-11-01\n\n承認した。")
        self.r2, self.m2 = self.released("取りやめる")
        self.gh.add_comment(self.r2, "入れたいこと: 一覧の CSV 出力")
        self.old, self.old_body = self.current_plan([(self.r1, "バックアップ"), (self.r2, "取りやめる")])
        self.gh.add_issue("要望", milestone=self.m2)  # 取りやめるリリースのマイルストーンにある Issue
        self.wish = max(self.gh.issues)
        self.path = self.write_draft(draft_text(
            [(f"#{self.r1}", "バックアップ"), ("c", "まとめ")], dests=dest_table((f"#{self.wish}", "c")),
            cancels=cancel_table((f"#{self.r2}", "c にまとめた", "c")),
            current=(self.gh.url(self.old), self.old_body)), name=NAME2)

    def test_retry_after_interruption_in_step_4(self):
        """手順 3 の後 (ラベル current が 2 つ) で中断し、やり直すと、手順 4・5・6 と取りやめだけを行う。"""
        self.gh.fail_when = lambda args: args[:2] == ["issue", "edit"] and "--remove-label" in args
        result = releaseops.apply(self.path, REPO)
        self.assertEqual(result["status"], "gh_failed")
        self.assertEqual(result["done"][-1]["action"], "add-current")
        current = releaseplan.current_and_next(REPO)
        self.assertTrue(current["swapping"], "current の付いた計画が 2 つあるのは付け替えの途中")
        shown = releaseops.plan(self.path, REPO)
        self.assertEqual(shown["status"], "ok", shown["errors"])
        self.assertEqual([(a["step"], a["action"]) for a in shown["actions"]], [
            (4, "remove-current"), (5, "record-current-swap"), (6, "close-old-plan"), (7, "copy-memo"),
            (7, "record-cancel"), (7, "close-cancelled-release"), (7, "close-cancelled-milestone")])
        result = releaseops.apply(self.path, REPO)
        self.assertEqual(result["status"], "ok", result["errors"])
        old = self.gh.issues[self.old]
        self.assertEqual((old["state"], old["labels"]), ("CLOSED", []))
        new = self.find("リリース計画 20261114")[0]
        swap = self.gh.comments[new][-1]["body"]
        self.assertTrue(swap.startswith(f"issue-practice: current-swap date=2026-11-14 old=#{self.old}\n"), swap)
        c = self.find(r"\(まとめ\)")[0]
        self.assertEqual(self.gh.milestones[self.gh.issues[self.wish]["milestone"]]["title"], f"R{c} (まとめ)",
                         "取りやめたリリースの Issue を、入れ先に移す")
        cancelled = self.gh.issues[self.r2]
        self.assertEqual((cancelled["state"], cancelled["state_reason"]), ("CLOSED", "not planned"))
        self.assertEqual(self.gh.milestones[self.m2]["state"], "closed")
        self.assertTrue(self.gh.comments[self.r2][-1]["body"].startswith(f"issue-practice: plan-change draft={NAME2}\n"))
        copied = [x["body"] for x in self.gh.comments[c]]
        self.assertEqual(len(copied), 1)
        self.assertIn(self.gh.comments[self.r2][0]["html_url"], copied[0])
        self.assertIn("入れたいこと: 一覧の CSV 出力", copied[0])
        self.assertEqual(releaseops.plan(self.path, REPO)["actions"], [], "書き終えた後は、行う書き込みが無い")

    def test_old_plan_changed_is_unsatisfied(self):
        self.gh.issues[self.old]["body"] += "\n追記\n"
        result = releaseops.apply(self.path, REPO)
        self.assertEqual(result["status"], "unsatisfied")
        self.assertEqual(self.writes(), [])

    def test_missing_cancellation_is_unsatisfied(self):
        path = self.write_draft(draft_text([(f"#{self.r1}", "バックアップ")], current=(self.gh.url(self.old), self.old_body)),
                                name="20261115-1300-release-plan-next.md")
        result = releaseops.plan(path, REPO)
        self.assertEqual(result["status"], "unsatisfied")
        self.assertTrue(any(f"#{self.r2}" in e["message"] for e in result["errors"]), result["errors"])

    def test_issue_left_in_cancelled_milestone_is_unsatisfied(self):
        path = self.write_draft(draft_text([(f"#{self.r1}", "バックアップ")], cancels=cancel_table((f"#{self.r2}", "理由", "なし")),
                                           current=(self.gh.url(self.old), self.old_body)), name="20261115-1300-release-plan-next.md")
        result = releaseops.plan(path, REPO)
        self.assertEqual(result["status"], "unsatisfied")
        self.assertTrue(any(f"#{self.wish}" in e["message"] for e in result["errors"]), result["errors"])


class UrgentTest(ReleaseOpsCase):

    def test_adds_row_to_current_plan(self):
        r1, _ = self.released("バックアップ")
        old, body = self.current_plan([(r1, "バックアップ")])
        path = self.write_draft(draft_text([("hotfix", "急ぎの修正"), (f"#{r1}", "バックアップ")], kind="急ぎのリリースの追加",
                                           current=(self.gh.url(old), body)))
        result = releaseops.apply(path, REPO)
        self.assertEqual(result["status"], "ok", result["errors"])
        self.assertEqual(len(self.find("リリース計画")), 1, "新しい計画を作らない")
        hotfix = self.find("急ぎの修正")[0]
        rows = releaseplan.parse_table(self.gh.issues[old]["body"])["rows"]
        self.assertEqual([r["number"] for r in rows], [hotfix, r1])
        self.assertEqual(self.gh.issues[old]["labels"], ["current"])
        kinds = [c["body"].split("\n")[0] for c in self.gh.comments[old]]
        self.assertEqual(kinds, [f"issue-practice: approval draft={NAME}", f"issue-practice: plan-change draft={NAME}"])
        again = releaseops.apply(path, REPO)
        self.assertEqual((again["status"], again["done"]), ("ok", []), again["errors"])


class StateErrorTest(ReleaseOpsCase):

    def test_other_current_plan_is_unsatisfied(self):
        self.current_plan([])
        path = self.write_draft(draft_text([("a", "x")]))
        result = releaseops.plan(path, REPO)
        self.assertEqual(result["status"], "unsatisfied")
        self.assertTrue(any("ラベル current" in e["message"] for e in result["errors"]), result["errors"])


class ReviewTest(ReleaseOpsCase):

    def test_no_plan(self):
        result = releaseops.review(REPO)
        self.assertEqual((result["status"], result["plan"], result["releases"]), ("ok", None, []))

    def test_malformed_states(self):
        r1, m1 = self.released("一つ目")
        self.gh.issues[r1]["title"] = releaseplan.release_title(r1, "一つ目", draft=False)  # draft-removed の記録が無い
        r2, m2 = self.released("二つ目")
        self.gh.milestones[m2]["description"] = "説明"  # お互いの URL が無い
        self.current_plan([(r1, "一つ目"), (r2, "二つ目")])
        result = releaseops.review(REPO)
        self.assertEqual(result["status"], "unsatisfied")
        self.assertTrue(any("draft-removed が無い" in e for e in result["errors"]), result["errors"])
        self.assertTrue(any("リリース Issue の URL" in e for e in result["errors"]), result["errors"])
        self.assertEqual([bool(r["errors"]) for r in result["releases"]], [True, True])

    def test_three_current_plans(self):
        for date in ("20261101", "20261102", "20261103"):
            self.current_plan([], date=date)
        result = releaseops.review(REPO)
        self.assertEqual(result["status"], "unsatisfied")
        self.assertTrue(any("3 つある" in e for e in result["errors"]), result["errors"])

    def test_counts_current_per_target(self):
        """リリース対象が 2 つのとき、release-target:<名前> ごとに current を数える。"""
        self.gh.add_label("release-target:app")
        self.gh.add_label("release-target:api")
        self.gh.add_label("current")
        for target in ("app", "api"):
            self.gh.add_issue(releaseplan.plan_title("20261101", target), body="## リリースの順番\n\n"
                              + releaseplan.render_table([]) + "\n", labels=["current", f"release-target:{target}"])
        self.assertEqual(releaseops.review(REPO)["status"], "unsatisfied", "リリース対象を指定しなければ満たさない")
        result = releaseops.review(REPO, target="app")
        self.assertEqual([p["title"] for p in result["plans"]], ["📅 リリース計画 app 20261101"])
        self.assertFalse(result["swapping"])

    def test_unassigned_excludes_plans_releases_and_no_release(self):
        self.released("一つ目")
        self.current_plan([])
        self.gh.add_label("no-release")
        self.gh.add_issue("入れない", labels=["no-release"])
        wish = self.gh.add_issue("要望")
        result = releaseops.review(REPO)
        self.assertEqual([u["number"] for u in result["unassigned"]], [wish])

    def test_dependencies_left_after_blocker_closed(self):
        blocker = self.gh.add_issue("依存先", state="CLOSED")
        other = self.gh.add_issue("別の依存先")
        waiting = self.gh.add_issue("待つ", body=f"## 問題\n\nx\n\n## 依存先\n\n- #{blocker} が閉じるのを待つ\n- #{other}\n")
        self.gh.issues[waiting]["blocked_by"] = [blocker, other]
        result = releaseops.review(REPO)
        self.assertEqual([(d["number"], [r["number"] for r in d["resolved"]]) for d in result["dependencies"]],
                         [(waiting, [blocker])])


class ShowTest(ReleaseOpsCase):

    def test_shows_memos_and_records(self):
        r1, _ = self.released("一つ目")
        self.gh.add_comment(r1, "入れたいこと")
        self.gh.add_comment(r1, "issue-practice: release-start\n\n始めた。")
        self.gh.issues[r1]["body"] += "- PR: https://github.com/o/r/pull/9\n"
        result = releaseops.show(releaseplan.refs.parse_ref(self.gh.url(r1)))
        self.assertEqual(result["status"], "ok", result["errors"])
        self.assertEqual(result["subject"], "一つ目")
        self.assertTrue(result["draft"])
        self.assertTrue(result["running"])
        self.assertEqual([m["first_line"] for m in result["memos"]], ["入れたいこと"])
        self.assertEqual(result["prs"], ["https://github.com/o/r/pull/9"])


COMMIT = "0123456789abcdef0123456789abcdef01234567"
ISSUE_NAME = "20261114-1300-release-issue-plan-1.md"


def issue_draft(url, body, milestone_url, change=None, steps=None, done="- [ ] 本番で一覧が表示される"):
    steps = steps or (f"- 手順の文書: https://github.com/o/r/blob/{COMMIT}/docs/release.md\n\n"
                      "| 手順 | 行う / 省く | 理由 |\n| --- | --- | --- |\n| タグを打つ | 行う | 版を上げる |\n"
                      "| 告知する | 省く | 内部向けの変更だけ |")
    change_section = f"## 変えたこと\n\n{change}\n\n" if change else ""
    return (f"# 計画案: リリース Issue の計画\n\n## 元にした Issue\n\n- {url} 本文の SHA-256: {bodies.body_sha256(body)}\n\n"
            f"## 対象\n\n- リリース Issue: {url}\n\n{change_section}"
            f"## 参照\n\n- リリースマイルストーン: {milestone_url}\n\n## 目的\n\n一覧を絞り込める。\n\n"
            "## 範囲の判断\n\n絞り込みだけを含める。\n\n## 順序\n\n| 順 | Issue | 理由 |\n| --- | --- | --- |\n| 1 | #5 | 先に要る |\n\n"
            "## メモの扱い\n\nメモは無い。\n\n"
            f"## リリースの手順\n\n{steps}\n\n## 完了の条件\n\n{done}\n")


class IssuePlanTest(ReleaseOpsCase):

    def setUp(self):
        super().setUp()
        self.r, self.m = self.released("絞り込み")
        self.gh.issues[self.r]["body"] += "\nissue-practice: created-from draft=20261101-1200-release-plan-next.md key=a\n"
        self.url = self.gh.url(self.r)
        self.ms_url = self.gh.milestones[self.m]["html_url"]

    def write_issue_draft(self, **kwargs):
        return self.write_draft(issue_draft(self.url, self.gh.issues[self.r]["body"], self.ms_url, **kwargs), name=ISSUE_NAME)

    def test_approve_writes_body_record_and_title(self):
        path = self.write_issue_draft()
        shown = releaseops.issue_plan(path)
        self.assertEqual(shown["status"], "ok", shown["errors"])
        self.assertEqual((shown["mode"], shown["body_state"]), ("approve", "pending"))
        self.assertEqual([a["action"] for a in shown["actions"]], ["write-body", "record-draft-removed", "remove-draft-title"])
        self.assertEqual(self.writes(), [])
        result = releaseops.issue_apply(path)
        self.assertEqual(result["status"], "ok", result["errors"])
        issue = self.gh.issues[self.r]
        self.assertEqual(issue["title"], f"🔖 リリース R{self.r} (絞り込み)")
        self.assertTrue(issue["body"].startswith("## 参照\n\n- リリースマイルストーン: "))
        self.assertTrue(issue["body"].rstrip().endswith("key=a"), "created-from の行を残す")
        self.assertEqual(self.gh.comments[self.r][-1]["body"].split("\n")[0],
                         f"issue-practice: draft-removed date=2026-11-14 draft={ISSUE_NAME}")
        self.assertEqual(releaseops.show(releaseplan.refs.parse_ref(self.url))["errors"], [])
        again = releaseops.issue_apply(path)
        self.assertEqual((again["status"], again["body_state"], again["done"]), ("ok", "applied", []))

    def test_retry_after_title_failed(self):
        path = self.write_issue_draft()
        self.gh.fail_when = lambda args: args[:2] == ["issue", "edit"] and "--title" in args
        self.assertEqual(releaseops.issue_apply(path)["status"], "gh_failed")
        shown = releaseops.issue_plan(path)
        self.assertEqual(shown["status"], "ok", shown["errors"])
        self.assertEqual([a["action"] for a in shown["actions"]], ["remove-draft-title"],
                         "本文と draft-removed の記録は書き済みなので、題名だけを書き換える")

    def test_change_after_approval(self):
        releaseops.issue_apply(self.write_issue_draft())
        edited = self.write_issue_draft(done="- [ ] 本番で一覧が表示される\n- [ ] 告知した")
        self.assertEqual(releaseops.issue_plan(edited)["status"], "unsatisfied",
                         "承認に使った計画案を直して、もう一度書くことはできない (変更の記録が残らないため)")
        name = "20261115-1300-release-issue-plan-1.md"
        text = issue_draft(self.url, self.gh.issues[self.r]["body"], self.ms_url, done="- [ ] 本番で一覧が表示される\n- [ ] 告知した")
        self.assertEqual(releaseops.issue_plan(self.write_draft(text, name=name))["status"], "unsatisfied",
                         "承認の後は節「変えたこと」が要る")
        path = self.write_draft(issue_draft(self.url, self.gh.issues[self.r]["body"], self.ms_url,
                                            done="- [ ] 本番で一覧が表示される\n- [ ] 告知した",
                                            change="完了の条件に告知を足した。理由: 利用者が告知すると決めた。決めた人: 利用者"),
                                name=name)
        result = releaseops.issue_apply(path)
        self.assertEqual(result["status"], "ok", result["errors"])
        self.assertEqual([d["action"] for d in result["done"]], ["write-body", "record-plan-change"])
        self.assertNotIn("[DRAFT]", self.gh.issues[self.r]["title"], "承認の後の変更でも [DRAFT] を付け直さない")

    def test_errors(self):
        cases = {
            "手順の文書がコミットの URL ではない": dict(steps="- 手順の文書: https://github.com/o/r/blob/main/docs/release.md\n\n"
                                                    "| 手順 | 行う / 省く | 理由 |\n| --- | --- | --- |\n| a | 行う | b |"),
            "行う / 省く 以外": dict(steps=f"- 手順の文書: https://github.com/o/r/blob/{COMMIT}/d.md\n\n"
                                        "| 手順 | 行う / 省く | 理由 |\n| --- | --- | --- |\n| a | たぶん | b |"),
            "手順の文書が無いのに手順が無い": dict(steps="- 手順の文書: なし"),
            "完了の条件がチェックボックスではない": dict(done="本番で確認する"),
        }
        for name, kwargs in cases.items():
            with self.subTest(name):
                text = issue_draft(self.url, self.gh.issues[self.r]["body"], self.ms_url, **kwargs)
                self.assertTrue(releaseops.parse_issue_plan(text, ISSUE_NAME)["errors"], name)
        self.assertEqual(releaseops.parse_issue_plan(issue_draft(self.url, "b", self.ms_url, steps="- 手順の文書: なし\n\n1. タグを打つ",
                                                                 done="- なし"), ISSUE_NAME)["errors"], [])

    def test_state_errors(self):
        path = self.write_draft(issue_draft(self.url, self.gh.issues[self.r]["body"], "https://github.com/o/r/milestone/99"),
                                name=ISSUE_NAME)
        self.assertEqual(releaseops.issue_plan(path)["status"], "unsatisfied", "マイルストーンの URL が違う")
        path = self.write_issue_draft()
        self.gh.issues[self.r]["body"] += "追記\n"
        result = releaseops.issue_apply(path)
        self.assertEqual((result["status"], result["body_state"]), ("unsatisfied", "changed"))
        self.assertEqual(self.writes(), [])


class CliTest(FakeGhCase):
    """入口 (issue_practice.py) の終了コード。書き込みの中身は、上のテストで関数を直接呼んで確認する。"""

    def test_malformed_draft_exits_3_without_gh(self):
        path = os.path.join(self.root, NAME)
        with open(path, "w", encoding="utf-8") as f:
            f.write(draft_text([("a", "x")], kind="大きな計画"))
        for command in ("plan", "apply"):
            code, out, _ = self.cli("release", command, path, "--repo", REPO)
            self.assertEqual(code, 3)
            self.assertTrue(out["errors"])
        self.assertEqual(self.recorded(), [], "計画案の形が違えば gh を実行しない")

    def test_gh_failure_exits_4(self):
        self.responses([{"prefix": ["api", "user"], "exit": 1, "stderr": "HTTP 502: Bad Gateway"}])
        code, out, _ = self.cli("release", "review", "--repo", REPO)
        self.assertEqual(code, 4)
        self.assertEqual(out["gh_error"]["args"][:2], ["api", "user"])


class DocTest(unittest.TestCase):
    """文書 `issue-practice/skills/release-plan/references/release-plan-issue.md` の計画案の書式が、定数と一致すること。"""

    def test_sections_and_fields(self):
        path = os.path.join(HERE, "..", "skills", "release-plan", "references", "release-plan-issue.md")
        with open(path, encoding="utf-8") as f:
            doc = f.read()
        table_text = doc.split("| 節 | 書くこと |\n| --- | --- |\n")[1].split("\n\n")[0]
        self.assertEqual(tuple(line.split("|")[1].strip() for line in table_text.splitlines()), releaseops.PLAN_SECTIONS)
        first = table_text.splitlines()[0]
        self.assertEqual(tuple(re.findall(r"項目「([^」]+)」", first)), releaseops.TARGET_FIELDS)
        self.assertEqual(tuple(re.findall(r"`([^`]+)`", first)), releaseops.KINDS)
        self.assertIn(f"`| {' | '.join(releaseops.DEST_HEADER)} |`", doc)
        self.assertIn(f"`| {' | '.join(releaseops.CANCEL_HEADER)} |`", doc)
        self.assertIn(f"`{releaseplan.plan_title('YYYYMMDD')}`", doc)
        self.assertIn(f"`{releaseplan.release_title('<番号>', '主題')}`", doc)

    def test_release_issue_sections(self):
        path = os.path.join(HERE, "..", "skills", "release-issue-plan", "references", "release-issue.md")
        with open(path, encoding="utf-8") as f:
            doc = f.read()
        table_text = doc.split("| 節 | 書くこと |\n| --- | --- |\n")[1].split("\n\n")[0]
        self.assertEqual(tuple(line.split("|")[1].strip() for line in table_text.splitlines()),
                         releaseops.ISSUE_SECTIONS[:1] + (releaseops.CHANGE_SECTION,) + releaseops.ISSUE_SECTIONS[1:])
        self.assertIn(f"項目「{releaseops.ISSUE_TARGET_FIELD}」", table_text)
        items = doc.split("| 項目 | 書くこと |\n| --- | --- |\n")[1].split("\n\n")[0]
        self.assertEqual(tuple(line.split("|")[1].strip() for line in items.splitlines()), releaseops.ISSUE_SECTIONS[1:])
        self.assertIn(f"`| {' | '.join(releaseops.STEPS_HEADER)} |`", doc)


if __name__ == "__main__":
    unittest.main()
