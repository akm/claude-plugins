#!/usr/bin/env python3
"""スナップショットと差分 (issue-dispatch/scripts/issue_dispatch/observe.py) と、CLI の `project items --write-snapshot` /
`observe diff` / 書き込みのサブコマンドの反映のテスト。偽の gh (fake-gh) と固定データ (fixtures/gh/project-items-ok・
pr-observe-*) で動く。偽の gh の用意は test_project.FakeGhCase と同じ。

  python3 -m unittest discover -s issue-dispatch/tests

様式の正本は issue-dispatch/skills/issue-dispatch/references/observation.md。
"""

import copy
import json
import os
import subprocess
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.join(_HERE, "..", "scripts")
sys.path.insert(0, _SCRIPTS)
sys.path.insert(0, _HERE)

from issue_dispatch import comments, config, issues, observe, project  # noqa: E402
from test_project import FakeGhCase, fixture_json  # noqa: E402

_CLI = os.path.join(_SCRIPTS, "issue_dispatch.py")
_DOC = os.path.join(_HERE, "..", "skills", "issue-dispatch", "references", "observation.md")
PROJECT = {"owner": "akm", "number": 3}
A = "akm/issue-dispatch-verify-a"
A1, A2, A3 = f"{A}#1", f"{A}#2", f"{A}#3"
PR9 = f"https://github.com/{A}/pull/9"
USER_ENTRY = {"prefix": ["api", "user"], "stdout": {"fixture": "api-user"}}


def items_data(mutate=None):
    """固定データ project-items-ok の複製。mutate(nodes) で書き換える。"""
    data = fixture_json("project-items-ok")
    if mutate:
        mutate(data["data"]["repositoryOwner"]["projectV2"]["items"]["nodes"])
    return data


def node_of(nodes, number, repo=A):
    return next(n for n in nodes if (n.get("content") or {}).get("number") == number and n["content"]["repository"]["nameWithOwner"] == repo)


def pr_report_comment(url, database_id=90001):
    line = comments.format_header("worker", "w", "W-7", "PR の報告", {})
    return {"id": f"IC_{database_id}", "databaseId": database_id, "url": f"https://github.com/{A}/issues/3#issuecomment-{database_id}",
            "createdAt": "2026-10-23T00:00:00Z", "author": {"login": "akm"}, "body": f"{line}\n\n{url}"}


def pr_fixture(state, draft=False, merged=False):
    data = fixture_json("pr-observe-open-other-base")
    pr = data["data"]["repository"]["pullRequest"]
    pr["state"], pr["isDraft"], pr["mergedAt"] = state, draft, ("2026-10-23T00:00:00Z" if merged else None)
    return data


class SnapshotFileTest(unittest.TestCase):

    def test_round_trip_and_missing_and_corrupt(self):
        """書いた内容を往復で同じに返し、ファイルが無いときと壊れているとき (JSON でない・キーが無い) を区別する。"""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(observe.load_snapshot(d)["status"], "missing")
            snap = {"version": observe.SNAPSHOT_VERSION, "taken_at": "2026-10-23T00:00:00Z", "project_id": "P", "items": {A1: {"position": 1}}, "comment_prs": {}}
            observe.save_snapshot(d, snap)
            loaded = observe.load_snapshot(d)
            self.assertEqual((loaded["status"], loaded["snapshot"]), ("ok", snap))
            self.assertEqual(sorted(os.listdir(d)), [observe.SNAPSHOT_FILE], "一時ファイルを残さない")
            # 一時名は records.md の決まり (`.` で始まり `.tmp` で終わる) で、書き手ごとに別の名前
            import tempfile as _tempfile
            fd, tmp = _tempfile.mkstemp(dir=d, prefix=".snapshot-", suffix=".json.tmp")
            os.close(fd)
            self.assertTrue(os.path.basename(tmp).startswith(".") and tmp.endswith(".tmp"))
            os.unlink(tmp)
            with open(os.path.join(d, observe.SNAPSHOT_FILE), "w", encoding="utf-8") as f:
                f.write("{not json")
            self.assertEqual(observe.load_snapshot(d)["status"], "corrupt")
            with open(os.path.join(d, observe.SNAPSHOT_FILE), "w", encoding="utf-8") as f:
                json.dump({"version": observe.SNAPSHOT_VERSION, "items": {}}, f)
            self.assertEqual(observe.load_snapshot(d)["status"], "corrupt", "キーが無ければ壊れている")


class BuildTest(FakeGhCase):

    def test_build_from_items(self):
        """項目の読み取りから、R21 の見つける変化の一覧にある値だけを持つスナップショットを作る。"""
        self.responses([{"substring": "query ProjectItems", "stdout": {"fixture": "project-items-ok"}}])
        result = project.items(PROJECT)
        snap = observe.build_snapshot(result, {}, taken_at="2026-10-23T00:00:00Z")
        self.assertEqual(snap["version"], observe.SNAPSHOT_VERSION)
        self.assertEqual(snap["project_id"], result["project_id"])
        self.assertEqual(sorted(snap["items"]), sorted([A1, A2, A3, "akm/issue-dispatch-verify-b#1", "akm/issue-dispatch-verify-b#2"]))
        item = snap["items"][A1]
        self.assertEqual(set(item), {"item_id", "position", "state", "status", "fields", "assignees", "labels", "blocked_by", "body_edited_at", "comment_ids", "prs", "partial", "carried"},
                         "一覧に無い値 (title・url・events など) は持たない")
        self.assertEqual(item["partial"], [])
        self.assertEqual(item["state"], "OPEN")
        self.assertEqual(item["prs"][f"https://github.com/{A}/pull/4"], {"state": "MERGED", "draft": False, "merged": True})
        self.assertEqual(snap["items"][A2]["state"], "CLOSED")
        self.assertEqual(len(snap["items"][A3]["comment_ids"]), 10)
        self.assertEqual(snap["items"][A3]["fields"]["Agent session ID"]["value"], result["items"][0]["fields"]["Agent session ID"]["text"])
        self.assertEqual(snap["comment_prs"], {})

    def test_pr_urls_in_comments_of_open_items(self):
        """開いている項目のコメント (`PR の報告`・`待機` の理由の小さな PR) に URL で書かれた PR を集める。閉じた項目は読まない。"""
        def mutate(nodes):
            node_of(nodes, 3)["content"]["comments"]["nodes"].append(pr_report_comment(PR9))
            wait = comments.format_header("manager", "m", "M-1", "待機", {"to": "W-7", "assignment": 1, "declaration": 5,
                                                                      "waits": [{"kind": "小さな PR", "issue": A1, "pr": f"https://github.com/{A}/pull/10"}]})
            node_of(nodes, 1)["content"]["comments"]["nodes"].append({"id": "IC_x", "databaseId": 90002, "url": "u", "createdAt": "2026-10-23T00:00:01Z",
                                                                       "author": {"login": "akm"}, "body": wait + "\n\n理由"})
            node_of(nodes, 2)["content"]["comments"]["nodes"].append(pr_report_comment(f"https://github.com/{A}/pull/11", 90003))  # 閉じた項目
        self.responses([{"substring": "query ProjectItems", "stdout": items_data(mutate)}])
        result = project.items(PROJECT)
        self.assertEqual(observe.pr_urls_in_comments(result["items"], login="akm"), [PR9, f"https://github.com/{A}/pull/10"])

    def test_pr_urls_ignore_other_authors(self):
        def mutate(nodes):
            c = pr_report_comment(PR9)
            c["author"] = {"login": "someone-else"}
            node_of(nodes, 3)["content"]["comments"]["nodes"].append(c)
        self.responses([{"substring": "query ProjectItems", "stdout": items_data(mutate)}])
        self.assertEqual(observe.pr_urls_in_comments(project.items(PROJECT)["items"], login="akm"), [])

    def test_pr_state(self):
        """PR の状態だけを読む (作者で除かない)。"""
        data = pr_fixture("OPEN")
        data["data"]["repository"]["pullRequest"]["author"] = {"login": "someone-else"}
        self.responses([{"substring": "query PrObserve", "stdout": data}])
        self.assertEqual(issues.pr_state(PR9), {"status": "ok", "url": PR9, "state": "OPEN", "draft": False, "merged": False})
        self.assertEqual(issues.pr_state("not a url")["status"], "error")


class DiffTest(FakeGhCase):

    def snapshot(self, mutate=None, comment_prs=None):
        self.responses([{"substring": "query ProjectItems", "stdout": items_data(mutate)}])
        return observe.build_snapshot(project.items(PROJECT), comment_prs or {}, taken_at="t")

    def diff(self, mutate=None, before=None, comment_prs=None):
        before = before or self.snapshot()
        return observe.diff(before, self.snapshot(mutate, comment_prs))

    def test_no_change(self):
        self.assertEqual(self.diff(), [])

    def test_close_and_reopen(self):
        """Covers AE5, AE57. Issue の close と reopen を差分として返す (Done を書く呼び出しは無い)。"""
        d = self.diff(lambda nodes: node_of(nodes, 1)["content"].__setitem__("state", "CLOSED"))
        self.assertEqual(d, [{"kind": "closed", "item": A1, "before": "OPEN", "after": "CLOSED"}])
        self.assertEqual([c["args"][:2] for c in self.recorded_full()], [["api", "graphql"], ["api", "graphql"]], "読むだけ")
        d = self.diff(lambda nodes: node_of(nodes, 2)["content"].__setitem__("state", "OPEN"))
        self.assertEqual(d, [{"kind": "reopened", "item": A2, "before": "CLOSED", "after": "OPEN"}])

    def test_human_changes(self):
        """Covers AE39, AE40. Status・フィールド (Agent stuck state を空にした・Agent session ID を別の値にした)・担当者・ラベルの変化。"""
        def mutate(nodes):
            n = node_of(nodes, 3)
            for fv in n["fieldValues"]["nodes"]:
                if fv and fv.get("field", {}).get("name") == "Status":
                    fv["name"] = "Ready"
                if fv and fv.get("field", {}).get("name") == "Agent session ID":
                    fv["text"] = "local_other"
            n["content"]["assignees"]["nodes"].append({"login": "akm"})
            n["content"]["labels"]["nodes"].append({"name": "resource:db"})
        d = self.diff(mutate)
        kinds = [(x["kind"], x.get("field")) for x in d]
        self.assertEqual(kinds, [("status", None), ("field", "Agent session ID"), ("assignees", None), ("labels", None)], "人の変更の種類の順")
        self.assertEqual(d[0]["before"], "In Progress")
        self.assertEqual(d[0]["after"], "Ready")
        self.assertEqual((d[1]["before"], d[1]["after"]), (self.snapshot()["items"][A3]["fields"]["Agent session ID"]["value"], "local_other"))
        self.assertEqual((d[2]["added"], d[2]["removed"]), (["akm"], []))
        self.assertEqual((d[3]["added"], d[3]["removed"]), (["resource:db"], []))
        # Agent stuck state を人が空にした: 前にあって今は無い
        before = self.snapshot()
        before["items"][A3]["fields"]["Agent stuck state"] = {"value": "idle-no-progress", "updated_at": "t"}
        d = observe.diff(before, self.snapshot())
        self.assertEqual(d, [{"kind": "field", "item": A3, "field": "Agent stuck state", "before": "idle-no-progress", "after": None}])

    def test_blocked_by_comment_pr_and_order(self):
        """blocker の close・コメントの追加・待機している小さな PR の状態の変化を返し、処理の順 (人の変更 → close → blockedBy → コメント → PR → 項目の追加) に並ぶ。"""
        before = self.snapshot(comment_prs={PR9: {"state": "OPEN", "draft": False, "merged": False}})
        before["items"][A3]["blocked_by"] = {A1: "OPEN"}
        def mutate(nodes):
            n3 = node_of(nodes, 3)
            n3["content"]["blockedBy"]["nodes"].append({"number": 1, "url": f"https://github.com/{A}/issues/1", "state": "CLOSED", "repository": {"nameWithOwner": A}})
            n3["content"]["comments"]["nodes"].append(pr_report_comment(PR9))
            node_of(nodes, 1)["content"]["labels"]["nodes"].append({"name": "x"})
            node_of(nodes, 2)["content"]["state"] = "OPEN"
            nodes.append(copy.deepcopy(node_of(nodes, 1)))
            nodes[-1]["id"] = "PVTI_new"
            nodes[-1]["content"]["number"] = 7
            nodes[-1]["content"]["labels"]["nodes"] = []
        d = self.diff(mutate, before=before, comment_prs={PR9: {"state": "MERGED", "draft": False, "merged": True}})
        self.assertEqual([x["kind"] for x in d], ["labels", "reopened", "blocked_by", "comment", "pr", "added"])
        self.assertEqual(d[2], {"kind": "blocked_by", "item": A3, "added": [], "removed": [], "state_changed": [{"key": A1, "before": "OPEN", "after": "CLOSED"}]})
        self.assertEqual(d[3]["ids"], [90001])
        self.assertEqual(d[4], {"kind": "pr", "item": None, "url": PR9, "source": "comment", "before": {"state": "OPEN", "draft": False, "merged": False}, "after": {"state": "MERGED", "draft": False, "merged": True}})
        self.assertEqual(d[5]["item"], f"{A}#7")

    def test_removed_position_body_edit_and_reference_pr(self):
        def mutate(nodes):
            nodes.remove(node_of(nodes, 2, "akm/issue-dispatch-verify-b"))
            n1 = node_of(nodes, 1)
            n1["content"]["userContentEdits"]["nodes"].append({"editor": {"login": "someone"}, "editedAt": "2026-10-24T00:00:00Z", "deletedAt": None})
            n1["content"]["closedByPullRequestsReferences"]["nodes"][0]["state"] = "OPEN"
        d = self.diff(mutate)
        kinds = [x["kind"] for x in d]
        self.assertEqual(kinds, ["removed", "pr", "body_edit"], "除去で後ろの項目の位置がずれても、相対の順が同じなら position は返さない")
        self.assertEqual(d[0]["item"], "akm/issue-dispatch-verify-b#2")
        self.assertEqual((d[1]["item"], d[1]["source"], d[1]["after"]["state"]), (A1, "reference", "OPEN"))
        self.assertEqual((d[2]["item"], d[2]["after"]), (A1, "2026-10-24T00:00:00Z"))

    def test_position_only_when_relative_order_changes(self):
        """並び順の変化は、両方にある項目の相対の順が変わったときだけ 1 件。"""
        def swap(nodes):
            nodes[0], nodes[1] = nodes[1], nodes[0]
        d = self.diff(swap)
        self.assertEqual(len(d), 1)
        self.assertEqual((d[0]["kind"], d[0]["item"]), ("position", None))
        self.assertEqual(d[0]["before"][:2], [A3, A2])
        self.assertEqual(d[0]["after"][:2], [A2, A3])
        def insert_first(nodes):
            nodes.insert(0, copy.deepcopy(node_of(nodes, 1)))
            nodes[0]["id"] = "PVTI_new"
            nodes[0]["content"]["number"] = 7
        self.assertEqual([x["kind"] for x in self.diff(insert_first)], ["added"], "先頭に足しても後ろの項目に position は出ない")

    def test_reflect_hides_own_writes(self):
        """Covers AE55. 書いた値だけを反映し、反映した後の差分に自分の書き込みが現れない。読み取りの後にほかの人が変えた値は反映しない。"""
        snap = self.snapshot()
        ops = [{"kind": "status", "item": A3, "value": "In Progress"},
               {"kind": "field", "item": A3, "field": "Agent session ID", "value": "local_new"},
               {"kind": "comment", "item": A3, "id": 90001},
               {"kind": "blocked_by", "item": A3, "action": "add", "blocker": A1, "state": "OPEN"},
               {"kind": "labels", "item": A3, "add": ["resource:db"], "remove": []},
               {"kind": "assignees", "item": A3, "add": ["akm"], "remove": []}]
        for op in ops:
            snap, problem = observe.reflect(snap, op)
            self.assertIsNone(problem, op)
        def mutate(nodes):
            n = node_of(nodes, 3)
            for fv in n["fieldValues"]["nodes"]:
                if fv and fv.get("field", {}).get("name") == "Status":
                    fv["name"] = "In Progress"
                if fv and fv.get("field", {}).get("name") == "Agent session ID":
                    fv["text"] = "local_new"
            n["content"]["comments"]["nodes"].append(pr_report_comment(PR9))
            n["content"]["blockedBy"]["nodes"].append({"number": 1, "url": f"https://github.com/{A}/issues/1", "state": "OPEN", "repository": {"nameWithOwner": A}})
            n["content"]["labels"]["nodes"].append({"name": "resource:db"})
            n["content"]["assignees"]["nodes"].append({"login": "akm"})
            node_of(nodes, 1)["content"]["labels"]["nodes"].append({"name": "other"})  # ほかの人の変更
        d = self.diff(mutate, before=snap)
        self.assertEqual(d, [{"kind": "labels", "item": A1, "added": ["other"], "removed": []}], "自分の書き込みは現れず、ほかの人の変更だけ")
        _, problem = observe.reflect(snap, {"kind": "status", "item": "akm/x#999", "value": "Ready"})
        self.assertIsNotNone(problem, "無い項目への反映は問題を返す")
        _, problem = observe.reflect(snap, {"kind": "nope", "item": A3})
        self.assertIsNotNone(problem)


class CliTest(FakeGhCase):

    def setUp(self):
        super().setUp()
        self.manager = os.path.join(self.root, "manager")
        os.makedirs(os.path.dirname(os.path.join(self.manager, config.CONFIG_PATH)))
        with open(os.path.join(self.manager, config.CONFIG_PATH), "w", encoding="utf-8") as f:
            json.dump({"project": PROJECT, "record_dir": "rec"}, f)
        self.snapshot_dir = os.path.join(self.manager, "rec", "akm-3")

    def cli(self, *args, stdin=None):
        r = subprocess.run([sys.executable, _CLI, *args], capture_output=True, text=True, input=stdin)
        return r.returncode, json.loads(r.stdout) if r.stdout.strip() else None, r.stderr

    def test_write_snapshot_reads_comment_prs(self):
        """project items --write-snapshot は読んだ内容と、コメントの URL の PR の状態をスナップショットに書く。記録は読まない。"""
        self.responses([{"substring": "query ProjectItems", "stdout": items_data(lambda nodes: node_of(nodes, 3)["content"]["comments"]["nodes"].append(pr_report_comment(PR9)))},
                        USER_ENTRY, {"substring": "query PrObserve", "stdout": pr_fixture("MERGED", merged=True)}])
        code, out, err = self.cli("project", "items", "--project", "akm/3", "--write-snapshot", "--dir", self.manager)
        self.assertEqual((code, out["status"]), (0, "ok"), err)
        self.assertEqual(out["snapshot"]["path"], os.path.join(self.snapshot_dir, observe.SNAPSHOT_FILE))
        self.assertEqual(out["snapshot"]["comment_prs"], {PR9: {"state": "MERGED", "draft": False, "merged": True}})
        loaded = observe.load_snapshot(self.snapshot_dir)
        self.assertEqual(loaded["status"], "ok")
        self.assertEqual(loaded["snapshot"]["comment_prs"][PR9]["merged"], True)
        self.assertNotIn("record.json", os.listdir(self.snapshot_dir))

    def test_write_snapshot_requires_dir(self):
        code, out, _ = self.cli("project", "items", "--project", "akm/3", "--write-snapshot")
        self.assertEqual(code, 2, "--dir が無ければ引数の誤り")

    def test_diff_cli(self):
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": {"fixture": "project-items-ok"}}])
        self.cli("project", "items", "--project", "akm/3", "--write-snapshot", "--dir", self.manager)
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": items_data(lambda nodes: node_of(nodes, 1)["content"].__setitem__("state", "CLOSED"))}])
        code, out, err = self.cli("observe", "diff", "--dir", self.manager, "--project", "akm/3")
        self.assertEqual((code, out["status"], out["errors"]), (0, "ok", []), err)
        self.assertEqual(out["diffs"], [{"kind": "closed", "item": A1, "before": "OPEN", "after": "CLOSED"}])
        self.assertEqual(out["snapshot_taken_at"], observe.load_snapshot(self.snapshot_dir)["snapshot"]["taken_at"])
        self.assertEqual(observe.load_snapshot(self.snapshot_dir)["snapshot"]["items"][A1]["state"], "OPEN", "diff は書かない")

    def test_partial_read_yields_no_diff_and_no_save(self):
        """項目の一覧そのものが無ければ、diff は差分を返さず、--write-snapshot はスナップショットを書き換えない (読めなかった項目を removed にしない)。"""
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": {"fixture": "project-items-ok"}}])
        self.cli("project", "items", "--project", "akm/3", "--write-snapshot", "--dir", self.manager)
        taken = observe.load_snapshot(self.snapshot_dir)["snapshot"]["taken_at"]
        partial = [USER_ENTRY, {"substring": ["query ProjectItems", '"after": "CURSOR-PAGE-1"'], "stdout": "", "stderr": "gh: HTTP 502\n", "exit": 1},
                   {"substring": "query ProjectItems", "stdout": {"fixture": "project-items-page1"}}]
        self.responses(partial)
        code, out, err = self.cli("observe", "diff", "--dir", self.manager, "--project", "akm/3")
        self.assertEqual((code, out["status"], out["diffs"], out["errors"][0]["key"]), (0, "error", [], "partial"), err)
        self.assertEqual(out["problems"][0]["what"], "items-page")
        self.responses(partial)
        code, out, _ = self.cli("project", "items", "--project", "akm/3", "--write-snapshot", "--dir", self.manager)
        self.assertEqual((out["status"], out["snapshot"], out["errors"][0]["key"]), ("error", None, "partial"))
        self.assertEqual(observe.load_snapshot(self.snapshot_dir)["snapshot"]["taken_at"], taken, "書き換えない")
        # コメントの URL の PR が読めないときは、その PR だけを比べずに続ける (読むたびに同じく出る欠損で観測を止めない)
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": items_data(lambda nodes: node_of(nodes, 3)["content"]["comments"]["nodes"].append(pr_report_comment(PR9)))},
                        {"substring": "query PrObserve", "stdout": "", "stderr": "gh: HTTP 502\n", "exit": 1}])
        code, out, _ = self.cli("observe", "diff", "--dir", self.manager, "--project", "akm/3")
        self.assertEqual((out["status"], out["problems"][0]["what"]), ("partial", "comment-pr"))
        self.assertEqual([d["kind"] for d in out["diffs"]], ["comment"], "読めない PR の差分は出ず、ほかの差分 (コメントの追加) は返る")
        self.assertEqual(list(out["skipped"]["prs"]), [PR9])

    def test_item_level_gaps_skip_only_affected_values(self):
        """1 項目の中の欠損 (入れ子の connection の上限) は、その種類が狂わせる値だけを前のスナップショットから引き継いで比べず、ほかの値の変化と差分の保存は続ける。"""
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": {"fixture": "project-items-ok"}}])
        self.cli("project", "items", "--project", "akm/3", "--write-snapshot", "--dir", self.manager)
        def mutate(nodes):
            c = node_of(nodes, 1)["content"]
            c["blockedBy"]["pageInfo"] = {"hasNextPage": True, "endCursor": "C"}
            c["blockedBy"]["nodes"].append({"number": 7, "url": f"https://github.com/{A}/issues/7", "state": "OPEN", "repository": {"nameWithOwner": A}})  # 欠損した値は比べない
            c["labels"]["nodes"].append({"name": "x"})  # 欠損と関係のない値の変化は返る
            node_of(nodes, 3)["content"]["labels"]["nodes"].append({"name": "y"})  # ほかの項目の変化は返る
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": items_data(mutate)}])
        code, out, err = self.cli("observe", "diff", "--dir", self.manager, "--project", "akm/3")
        self.assertEqual((code, out["status"], out["errors"]), (0, "partial", []), err)
        self.assertEqual(out["diffs"], [{"kind": "labels", "item": A3, "added": ["y"], "removed": []},
                                        {"kind": "labels", "item": A1, "added": ["x"], "removed": []}])
        taken1 = observe.load_snapshot(self.snapshot_dir)["snapshot"]["taken_at"]
        self.assertEqual((out["skipped"]["items"], out["carried"]["items"]), ({}, {A1: {"blocked_by-truncated": taken1}}), "前の値を引き継ぐので比べない値は無い")
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": items_data(mutate)}])
        code, out, _ = self.cli("project", "items", "--project", "akm/3", "--write-snapshot", "--dir", self.manager)
        self.assertEqual((out["status"], out["snapshot"]["carried"]["items"]), ("partial", {A1: {"blocked_by-truncated": taken1}}), "保存し、引き継いだ種類を残す")
        saved = observe.load_snapshot(self.snapshot_dir)["snapshot"]["items"][A1]
        self.assertEqual((saved["partial"], saved["carried"], saved["blocked_by"]), ([], {"blocked_by-truncated": taken1}, {}), "blocked_by は前の値 (空) を引き継ぐ")
        # 全部読めるようになった次の差分では、引き継いだ値 (blocked_by) と今の値を比べる (この固定データでは同じ)
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": {"fixture": "project-items-ok"}}])
        code, out, _ = self.cli("observe", "diff", "--dir", self.manager, "--project", "akm/3")
        self.assertEqual([(d["kind"], d["item"]) for d in out["diffs"]], [("labels", A3), ("labels", A1)])
        self.assertEqual(out["carried"], {"items": {}, "prs": {}})

    def test_item_level_gap_does_not_hide_close_comment_and_removal(self):
        """欠損が続く項目でも、close・新しいコメント・Project からの除去は差分に出る。"""
        def truncated(nodes):
            node_of(nodes, 1)["content"]["blockedBy"]["pageInfo"] = {"hasNextPage": True, "endCursor": "C"}
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": items_data(truncated)}])
        self.cli("project", "items", "--project", "akm/3", "--write-snapshot", "--dir", self.manager)
        def closed_and_commented(nodes):
            truncated(nodes)
            c = node_of(nodes, 1)["content"]
            c["state"] = "CLOSED"
            c["comments"]["nodes"].append(pr_report_comment(PR9, database_id=90009))
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": items_data(closed_and_commented)}])
        code, out, err = self.cli("observe", "diff", "--dir", self.manager, "--project", "akm/3")
        self.assertEqual((code, out["status"]), (0, "partial"), err)
        self.assertEqual([(d["kind"], d["item"]) for d in out["diffs"]], [("closed", A1), ("comment", A1)])
        self.assertEqual(out["skipped"]["items"], {A1: ["blocked_by-truncated"]})
        def removed(nodes):
            nodes.remove(node_of(nodes, 1))
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": items_data(removed)}])
        code, out, err = self.cli("observe", "diff", "--dir", self.manager, "--project", "akm/3")
        self.assertEqual((code, out["status"]), (0, "ok"), err)  # 今の読み取りに欠損は無い
        self.assertEqual([(d["kind"], d["item"]) for d in out["diffs"]], [("removed", A1)])

    def test_fields_gap_skips_status_too(self):
        """フィールドの値の欠損 (fields-truncated) では、同じ connection から読む Status も引き継いで比べない (Status が読めなかっただけで null になるため)。"""
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": {"fixture": "project-items-ok"}}])
        self.cli("project", "items", "--project", "akm/3", "--write-snapshot", "--dir", self.manager)
        def mutate(nodes):
            n = node_of(nodes, 1)
            n["fieldValues"]["pageInfo"] = {"hasNextPage": True, "endCursor": "F"}
            n["fieldValues"]["nodes"] = [fv for fv in n["fieldValues"]["nodes"] if not (fv and fv.get("field") and fv["field"]["name"] == "Status")]
            n["content"]["labels"]["nodes"].append({"name": "x"})  # 欠損と関係のない値の変化は返る
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": items_data(mutate)}])
        code, out, err = self.cli("observe", "diff", "--dir", self.manager, "--project", "akm/3")
        self.assertEqual((code, out["status"], out["errors"]), (0, "partial", []), err)
        self.assertEqual(out["diffs"], [{"kind": "labels", "item": A1, "added": ["x"], "removed": []}])
        self.assertEqual(list(out["carried"]["items"][A1]), ["fields-truncated"])
        self.assertEqual(out["skipped"]["items"], {})
        # 引き継ぐ元が無ければ、status と field を比べない
        before = {"version": 1, "taken_at": "t0", "project_id": "P", "comment_prs": {},
                  "items": {A1: observe.snapshot_item({"item_id": "I1", "position": 1, "state": "OPEN", "status": {"name": "Todo"}}, partial=["fields-truncated"])}}
        after = {"version": 1, "taken_at": "t1", "project_id": "P", "comment_prs": {},
                 "items": {A1: observe.snapshot_item({"item_id": "I1", "position": 1, "state": "CLOSED", "status": {"name": "Done"}})}}
        self.assertEqual([d["kind"] for d in observe.diff(before, after)], ["closed"])

    def test_carry_forward_keeps_last_complete_value(self):
        """コメントの続きのページが読めなかったターンは、前のスナップショットのコメント ID を引き継いで保存し (carried)、読めるようになったターンに
        最後に全部読めたときからの変化だけを差分に出す。"""
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": {"fixture": "project-items-ok"}}])
        self.cli("project", "items", "--project", "akm/3", "--write-snapshot", "--dir", self.manager)
        first = observe.load_snapshot(self.snapshot_dir)["snapshot"]
        ids_t1 = first["items"][A3]["comment_ids"]
        def comments_fail(nodes):
            node_of(nodes, 3)["content"]["comments"]["pageInfo"] = {"hasNextPage": True, "endCursor": "C1"}
        failing = [USER_ENTRY, {"substring": "query ProjectItems", "stdout": items_data(comments_fail)},
                   {"substring": "query IssueComments", "stdout": "", "stderr": "gh: HTTP 502\n", "exit": 1}]
        self.responses(failing)
        code, out, err = self.cli("observe", "diff", "--dir", self.manager, "--project", "akm/3")
        self.assertEqual((code, out["status"], out["diffs"], out["skipped"]["items"]), (0, "partial", [], {}), err)
        self.assertEqual(out["carried"]["items"], {A3: {"comments": first["taken_at"]}})
        self.responses(failing)
        code, out, err = self.cli("project", "items", "--project", "akm/3", "--write-snapshot", "--dir", self.manager)
        self.assertEqual((code, out["status"], out["snapshot"]["carried"]["items"]), (0, "partial", {A3: {"comments": first["taken_at"]}}), err)
        second = observe.load_snapshot(self.snapshot_dir)["snapshot"]
        self.assertEqual((second["items"][A3]["comment_ids"], second["items"][A3]["partial"], second["items"][A3]["carried"]),
                         (ids_t1, [], {"comments": first["taken_at"]}), "前の値を引き継ぎ、partial には入れない")
        # 続けて読めなければ、引き継いだ元 (最初に全部読めたとき) の taken_at を保つ
        self.responses(failing)
        self.cli("project", "items", "--project", "akm/3", "--write-snapshot", "--dir", self.manager)
        third = observe.load_snapshot(self.snapshot_dir)["snapshot"]
        self.assertEqual(third["items"][A3]["carried"], {"comments": first["taken_at"]})
        # 読めるようになったターン: 最後に全部読めたときからの変化 (足されたコメント) だけが出る
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": items_data(lambda nodes: node_of(nodes, 3)["content"]["comments"]["nodes"].append(pr_report_comment(PR9, 90009)))},
                        {"substring": "query PrObserve", "stdout": pr_fixture("OPEN")}])
        code, out, err = self.cli("observe", "diff", "--dir", self.manager, "--project", "akm/3")
        self.assertEqual([(d["kind"], d["item"], d.get("ids")) for d in out["diffs"] if d["kind"] == "comment"], [("comment", A3, [90009])], err)
        self.assertEqual(out["carried"], {"items": {}, "prs": {}})

    def test_carry_forward_comment_pr_state(self):
        """コメントの URL の PR が読めなかったターンは前の状態を引き継ぎ、読めるようになったターンにその変化 (マージ) を差分に出す。"""
        with_pr = items_data(lambda nodes: node_of(nodes, 3)["content"]["comments"]["nodes"].append(pr_report_comment(PR9)))
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": with_pr}, {"substring": "query PrObserve", "stdout": pr_fixture("OPEN")}])
        self.cli("project", "items", "--project", "akm/3", "--write-snapshot", "--dir", self.manager)
        taken1 = observe.load_snapshot(self.snapshot_dir)["snapshot"]["taken_at"]
        failing = [USER_ENTRY, {"substring": "query ProjectItems", "stdout": with_pr}, {"substring": "query PrObserve", "stdout": "", "stderr": "gh: HTTP 502\n", "exit": 1}]
        self.responses(failing)
        code, out, err = self.cli("observe", "diff", "--dir", self.manager, "--project", "akm/3")
        self.assertEqual((code, out["status"], out["diffs"], out["skipped"]["prs"], out["carried"]["prs"]), (0, "partial", [], {}, {PR9: taken1}), err)
        self.responses(failing)
        self.cli("project", "items", "--project", "akm/3", "--write-snapshot", "--dir", self.manager)
        saved = observe.load_snapshot(self.snapshot_dir)["snapshot"]["comment_prs"][PR9]
        self.assertEqual(saved, {"state": "OPEN", "draft": False, "merged": False, "carried": taken1})
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": with_pr}, {"substring": "query PrObserve", "stdout": pr_fixture("MERGED", merged=True)}])
        code, out, err = self.cli("observe", "diff", "--dir", self.manager, "--project", "akm/3")
        self.assertEqual(out["diffs"], [{"kind": "pr", "item": None, "url": PR9, "source": "comment",
                                        "before": {"state": "OPEN", "draft": False, "merged": False}, "after": {"state": "MERGED", "draft": False, "merged": True}}], err)

    def test_write_snapshot_drops_prs_no_longer_in_comments(self):
        """--write-snapshot は今のコメントに書かれた PR だけを読む。前のスナップショットにだけある URL は読み直さず、保存にも残らない
        (項目が閉じた後の PR の URL が増え続けないため)。observe diff は差分のために読み直す (別のテスト)。"""
        with_pr = items_data(lambda nodes: node_of(nodes, 3)["content"]["comments"]["nodes"].append(pr_report_comment(PR9)))
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": with_pr}, {"substring": "query PrObserve", "stdout": pr_fixture("OPEN")}])
        self.cli("project", "items", "--project", "akm/3", "--write-snapshot", "--dir", self.manager)
        self.assertEqual(list(observe.load_snapshot(self.snapshot_dir)["snapshot"]["comment_prs"]), [PR9])
        calls_before = len(self.recorded_full())
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": {"fixture": "project-items-ok"}}])  # コメントが無い (PrObserve の応答は用意しない)
        code, out, err = self.cli("project", "items", "--project", "akm/3", "--write-snapshot", "--dir", self.manager)
        self.assertEqual((code, out["status"], out["snapshot"]["comment_prs"]), (0, "ok", {}), err)
        self.assertEqual(observe.load_snapshot(self.snapshot_dir)["snapshot"]["comment_prs"], {})
        self.assertFalse(any("PrObserve" in (r.get("stdin") or "") for r in self.recorded_full()[calls_before:]), "前のスナップショットの URL を読み直さない")

    def test_no_carry_without_previous_complete_value(self):
        """最初のスナップショットから一部しか読めていない値は引き継ぐ元が無いので、partial のまま比べない。"""
        def comments_fail(nodes):
            node_of(nodes, 3)["content"]["comments"]["pageInfo"] = {"hasNextPage": True, "endCursor": "C1"}
        failing = [USER_ENTRY, {"substring": "query ProjectItems", "stdout": items_data(comments_fail)},
                   {"substring": "query IssueComments", "stdout": "", "stderr": "gh: HTTP 502\n", "exit": 1}]
        self.responses(failing)
        code, out, err = self.cli("project", "items", "--project", "akm/3", "--write-snapshot", "--dir", self.manager)
        self.assertEqual((code, out["snapshot"]["skipped"]["items"], out["snapshot"]["carried"]["items"]), (0, {A3: ["comments"]}, {}), err)
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": items_data(lambda nodes: node_of(nodes, 3)["content"]["comments"]["nodes"].append(pr_report_comment(PR9, 90009)))},
                        {"substring": "query PrObserve", "stdout": pr_fixture("OPEN")}])
        code, out, err = self.cli("observe", "diff", "--dir", self.manager, "--project", "akm/3")
        self.assertEqual(([d["kind"] for d in out["diffs"]], out["skipped"]["items"]), (["pr"], {A3: ["comments"]}), "前の側が partial なら比べない")

    def test_build_snapshot_does_not_carry_from_partial_previous(self):
        """前のスナップショットでも同じ種類が partial なら引き継がない (引き継ぐ元が無い)。"""
        base = {"item_id": "I3", "position": 1, "state": "OPEN", "status": {"name": "Todo"}, "comments": [{"database_id": 1}]}
        prev_item = observe.snapshot_item(base, partial=["comments"])
        previous = {"version": 1, "taken_at": "t0", "project_id": "P", "items": {A3: prev_item}, "comment_prs": {}}
        result = {"project_id": "P", "items": [{**base, "key": A3, "comments": [{"database_id": 1}, {"database_id": 2}]}],
                  "problems": [{"item": A3, "what": "comments", "failure": "other", "message": "x", "exit_code": 1}]}
        snap = observe.build_snapshot(result, {}, "t1", previous=previous)
        self.assertEqual((snap["items"][A3]["partial"], snap["items"][A3]["carried"], snap["items"][A3]["comment_ids"]), (["comments"], {}, [1, 2]))

    def test_unknown_partial_kind_skips_whole_item(self):
        """対応に無い欠損の種類は、どの値が狂うか分からないので項目全体を比べない。"""
        before = {"version": 1, "taken_at": "t0", "project_id": "P", "comment_prs": {},
                  "items": {A1: dict(observe.snapshot_item({"item_id": "I1", "position": 1, "state": "OPEN", "status": {"name": "Todo"}}), partial=["new-kind"])}}
        after = {"version": 1, "taken_at": "t1", "project_id": "P", "comment_prs": {},
                 "items": {A1: observe.snapshot_item({"item_id": "I1", "position": 1, "state": "CLOSED", "status": {"name": "Done"}})}}
        self.assertEqual(observe.diff(before, after), [])
        self.assertEqual(observe.skipped(before, after), {"items": {A1: ["new-kind"]}, "prs": {}})

    def test_diff_without_snapshot(self):
        code, out, _ = self.cli("observe", "diff", "--dir", self.manager, "--project", "akm/3")
        self.assertEqual((code, out["status"], out["errors"][0]["key"]), (0, "error", "snapshot"))
        self.assertEqual(self.recorded(), [], "スナップショットが無ければ gh を実行しない")

    def test_write_subcommands_reflect(self):
        """書き込みのサブコマンドは、--snapshot-dir があれば書いた値だけをスナップショットに反映する。"""
        self.responses([USER_ENTRY, {"substring": "query ProjectItems", "stdout": {"fixture": "project-items-ok"}}])
        self.cli("project", "items", "--project", "akm/3", "--write-snapshot", "--dir", self.manager)
        item_id = observe.load_snapshot(self.snapshot_dir)["snapshot"]["items"][A3]["item_id"]
        self.responses([{"substring": "query ProjectMeta", "stdout": {"fixture": "project-meta-ok"}},
                        {"prefix": ["project", "item-edit"], "stdout": ""}])
        code, out, err = self.cli("project", "set-status", "--project", "akm/3", "--item", item_id, "--status", "Ready", "--snapshot-dir", self.manager)
        self.assertEqual((code, out["status"]), (0, "ok"), err)
        self.assertEqual(out["snapshot"], {"reflected": True, "warnings": []})
        self.assertEqual(observe.load_snapshot(self.snapshot_dir)["snapshot"]["items"][A3]["status"], "Ready")
        # blocked-by add
        self.responses([{"prefix": ["issue", "edit"], "stdout": f"https://github.com/{A}/issues/3\n"}])
        code, out, _ = self.cli("blocked-by", "add", "--issue", A3, "--blocker", A1, "--snapshot-dir", self.manager)
        self.assertEqual(out["snapshot"]["reflected"], True)
        self.assertEqual(observe.load_snapshot(self.snapshot_dir)["snapshot"]["items"][A3]["blocked_by"], {A1: "OPEN"})
        # issue add-label
        self.responses([{"prefix": ["issue", "view"], "stdout": {"labels": []}}, {"prefix": ["label", "list"], "stdout": {"fixture": "label-list"}},
                        {"prefix": ["issue", "edit"], "stdout": f"https://github.com/{A}/issues/3\n"}])
        code, out, _ = self.cli("issue", "add-label", "--issue", A3, "--label", "resource:verify", "--snapshot-dir", self.manager)
        self.assertEqual(observe.load_snapshot(self.snapshot_dir)["snapshot"]["items"][A3]["labels"], ["resource:verify"])
        # comment post
        data = fixture_json("issue-comments-ok")
        data["data"]["repository"]["issue"]["comments"]["nodes"] = []
        self.responses([USER_ENTRY, {"substring": "query IssueComments", "stdout": data}, {"prefix": ["issue", "comment"], "stdout": f"https://github.com/{A}/issues/3#issuecomment-777\n"}])
        code, out, _ = self.cli("comment", "post", "--issue", A3, "--role", "manager", "--name", "m", "--session-id", "M-1", "--kind", "割り当て",
                                "--to", "W-7", "--assignment", "1", "--body", "x", "--snapshot-dir", self.manager)
        self.assertEqual(out["snapshot"]["reflected"], True)
        self.assertIn(777, observe.load_snapshot(self.snapshot_dir)["snapshot"]["items"][A3]["comment_ids"])

    def test_reflect_warns_without_snapshot(self):
        """スナップショットが無い・壊れていれば反映せず warnings で知らせ、書き込みの結果は変えない。"""
        self.responses([{"substring": "query ProjectMeta", "stdout": {"fixture": "project-meta-ok"}}, {"prefix": ["project", "item-edit"], "stdout": ""}])
        code, out, _ = self.cli("project", "set-status", "--project", "akm/3", "--item", "PVTI_x", "--status", "Ready", "--snapshot-dir", self.manager)
        self.assertEqual((code, out["status"], out["snapshot"]["reflected"]), (0, "ok", False))
        self.assertEqual(out["snapshot"]["warnings"][0]["key"], "snapshot")


class DocTest(unittest.TestCase):

    def test_doc_lists_kinds(self):
        with open(_DOC, encoding="utf-8") as f:
            doc = f.read()
        for kind in observe.DIFF_KINDS:
            self.assertIn(f"`{kind}`", doc, f"差分の種類 {kind} が文書に無い")
        for key in ("`comment_prs`", "`comment_ids`", "`body_edited_at`", "`blocked_by`", "`--write-snapshot`", "`--snapshot-dir`", "`observe diff`"):
            self.assertIn(key, doc)


if __name__ == "__main__":
    unittest.main()
