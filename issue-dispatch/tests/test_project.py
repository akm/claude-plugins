#!/usr/bin/env python3
"""Project の読み書き (issue-dispatch/scripts/issue_dispatch/project.py) と、CLI の `project check` / `project items` /
`project set-status` / `project add-fields` のテスト。偽の gh (fake-gh) と固定データ (fixtures/gh/project-*) で動く。

  python3 -m unittest discover -s issue-dispatch/tests

様式の正本は issue-dispatch/skills/issue-dispatch/references/project-schema.md。
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.join(_HERE, "..", "scripts")
sys.path.insert(0, _SCRIPTS)

from issue_dispatch import project  # noqa: E402

_CLI = os.path.join(_SCRIPTS, "issue_dispatch.py")
_FAKE = os.path.join(_HERE, "fake-gh")
_FIXTURES = os.path.join(_HERE, "fixtures", "gh")
_DOC = os.path.join(_HERE, "..", "skills", "issue-dispatch", "references", "project-schema.md")
PROJECT = {"owner": "akm", "number": 3}


def fixture_json(name):
    with open(os.path.join(_FIXTURES, f"{name}.stdout"), encoding="utf-8") as f:
        return json.load(f)


class FakeGhCase(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.bin = os.path.join(self.root, "bin")
        os.makedirs(self.bin)
        os.symlink(_FAKE, os.path.join(self.bin, "gh"))
        self.args_file = os.path.join(self.root, "args.jsonl")
        self.responses_file = os.path.join(self.root, "responses.json")
        self._saved = {k: os.environ.get(k) for k in ("PATH", "FAKE_GH_ARGS", "FAKE_GH_RESPONSES", "FAKE_GH_MODE")}
        os.environ["PATH"] = self.bin + os.pathsep + os.environ.get("PATH", "")
        os.environ["FAKE_GH_ARGS"] = self.args_file
        os.environ["FAKE_GH_RESPONSES"] = self.responses_file
        os.environ.pop("FAKE_GH_MODE", None)
        self.responses([])

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    def responses(self, entries):
        with open(self.responses_file, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False)

    def recorded(self):
        return [r["args"] for r in self.recorded_full()]

    def recorded_full(self):
        if not os.path.exists(self.args_file):
            return []
        with open(self.args_file, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    @staticmethod
    def body(record):
        """`gh api graphql --input -` の標準入力の本文 (query と variables)。"""
        return json.loads(record["stdin"])

    @staticmethod
    def meta_entry(stdout=None):
        return {"substring": "query ProjectMeta", "stdout": stdout if stdout is not None else {"fixture": "project-meta-ok"}}


class MetaAndCheckTest(FakeGhCase):

    def test_read_meta(self):
        self.responses([self.meta_entry()])
        meta = project.read_meta(PROJECT)
        self.assertEqual(meta["status"], "ok")
        p = meta["project"]
        self.assertEqual((p["owner"], p["number"], p["title"]), ("akm", 3, "issue-dispatch verify"))
        self.assertEqual(p["fields"]["Status"]["data_type"], "SINGLE_SELECT")
        self.assertEqual({o["name"] for o in p["fields"]["Status"]["options"]}, set(project.STATUS_OPTIONS), "選択肢の並びは問わない")
        self.assertEqual(p["fields"]["Agent stuck state"]["data_type"], "SINGLE_SELECT")
        self.assertTrue(p["workflows"]["Item closed"]["enabled"])
        call = self.recorded_full()[0]
        self.assertEqual(call["args"], ["api", "graphql", "--input", "-"], "本文は --input - で標準入力に渡すこと")
        self.assertEqual(self.body(call)["variables"], {"owner": "akm", "number": 3})
        self.assertIn("query ProjectMeta", self.body(call)["query"])

    def test_check_passes_on_prepared_project(self):
        """Covers AE30. 検証用 Project (フィールドと選択肢がそろっている) では不足が無く、推奨のワークフローの無効と案内だけを返す。"""
        self.responses([self.meta_entry()])
        checked = project.check(project.read_meta(PROJECT)["project"])
        self.assertTrue(checked["ok"])
        self.assertEqual(checked["missing_fields"], [])
        self.assertEqual(checked["missing_status_options"], [])
        wf = checked["workflows"]
        self.assertEqual(wf["required_disabled"], [])
        self.assertEqual(wf["recommended_disabled"], ["Item reopened"], "一覧に無い推奨のワークフローは無効として数えること")
        self.assertEqual(wf["discouraged_enabled"], ["Pull request linked to issue"], "無効を推奨するワークフローが有効なら案内すること")
        self.assertEqual(wf["notice_enabled"], [], "Auto-add to project は検証用 Project では有効ではない")
        self.assertEqual(checked["proposals"], {"field_create": [], "update_options": []})

    def test_check_lists_missing_fields_and_options(self):
        """Covers AE21, AE30. フィールドと Status の選択肢が無い Project では、不足と、既存の id を保った案を返す。"""
        data = fixture_json("project-meta-ok")
        node = data["data"]["repositoryOwner"]["projectV2"]
        node["fields"]["nodes"] = [f for f in node["fields"]["nodes"] if f and f["name"] not in ("Agent session ID", "Agent stuck state")]
        status = next(f for f in node["fields"]["nodes"] if f["name"] == "Status")
        status["options"] = [o for o in status["options"] if o["name"] in ("Todo", "In Progress", "Done")]
        node["workflows"]["nodes"] = [w for w in node["workflows"]["nodes"] if w["name"] != "Item closed"] + \
            [{"id": "W_auto", "name": "Auto-add to project", "number": 99, "enabled": True}]
        self.responses([self.meta_entry(data)])
        checked = project.check(project.read_meta(PROJECT)["project"])
        self.assertFalse(checked["ok"])
        self.assertEqual([f["name"] for f in checked["missing_fields"]], ["Agent session ID", "Agent stuck state"])
        self.assertEqual(checked["missing_status_options"], ["Ready", "In review", "Blocked"])
        self.assertEqual(checked["workflows"]["required_disabled"], ["Item closed"])
        self.assertEqual(checked["workflows"]["notice_enabled"], ["Auto-add to project"])
        proposal = checked["proposals"]["update_options"][0]
        self.assertEqual((proposal["field"], proposal["fieldId"]), ("Status", status["id"]))
        names = [o["name"] for o in proposal["options"]]
        self.assertEqual(names, ["Todo", "In Progress", "Done", "Ready", "In review", "Blocked"])
        self.assertEqual([o.get("id") for o in proposal["options"][:3]], [o["id"] for o in status["options"]], "既存の選択肢の id を保つこと")
        self.assertTrue(all("color" in o and "description" in o for o in proposal["options"]))
        cmds = checked["proposals"]["field_create"]
        self.assertEqual(cmds[0][:2], ["project", "field-create"])
        self.assertIn("--single-select-options", cmds[1])
        self.assertIn(",".join(project.STUCK_STATES), cmds[1])

    def test_missing_stuck_state_values_get_a_proposal(self):
        """Agent stuck state の値の不足も、既存の id を保った案になり、add-fields が実行する。"""
        data = fixture_json("project-meta-ok")
        node = data["data"]["repositoryOwner"]["projectV2"]
        stuck = next(f for f in node["fields"]["nodes"] if f and f["name"] == "Agent stuck state")
        stuck["options"] = [o for o in stuck["options"] if o["name"] != "waiting-for-user"]
        self.responses([self.meta_entry(data),
                        {"substring": "mutation UpdateStatusOptions", "stdout": {"data": {"updateProjectV2Field": {"projectV2Field": {"id": stuck["id"]}}}}}])
        meta = project.read_meta(PROJECT)["project"]
        checked = project.check(meta)
        self.assertFalse(checked["ok"])
        self.assertEqual(checked["missing_fields"][0]["problem"], "値 waiting-for-user が無い")
        proposal = checked["proposals"]["update_options"][0]
        self.assertEqual((proposal["field"], proposal["fieldId"]), ("Agent stuck state", stuck["id"]))
        self.assertEqual([o.get("id") for o in proposal["options"][:4]], [o["id"] for o in stuck["options"]], "既存の値の id を保つこと")
        self.assertEqual(proposal["options"][-1]["name"], "waiting-for-user")
        results = project.add_fields(meta, checked)
        self.assertEqual([(r["action"], r["field"], r["ok"]) for r in results], [("update-options", "Agent stuck state", True)])

    def test_add_fields_runs_proposals(self):
        """Covers AE21. add-fields は不足のフィールドを作り、Status の選択肢を既存の id を含めて足す。不足が無ければ何も実行しない。"""
        data = fixture_json("project-meta-ok")
        node = data["data"]["repositoryOwner"]["projectV2"]
        node["fields"]["nodes"] = [f for f in node["fields"]["nodes"] if f and f["name"] != "Agent session title"]
        status = next(f for f in node["fields"]["nodes"] if f["name"] == "Status")
        status["options"] = [o for o in status["options"] if o["name"] != "Blocked"]
        self.responses([self.meta_entry(data),
                        {"prefix": ["project", "field-create"], "stdout": "{}"},
                        {"substring": "mutation UpdateStatusOptions", "stdout": {"data": {"updateProjectV2Field": {"projectV2Field": {"id": status["id"]}}}}}])
        meta = project.read_meta(PROJECT)["project"]
        results = project.add_fields(meta, project.check(meta))
        self.assertEqual([(r["action"], r.get("field")) for r in results], [("field-create", None), ("update-options", "Status")])
        self.assertTrue(all(r["ok"] for r in results))
        calls = self.recorded_full()
        self.assertEqual(calls[1]["args"][:8], ["project", "field-create", "3", "--owner", "akm", "--name", "Agent session title", "--data-type"])
        self.assertEqual(calls[2]["args"], ["api", "graphql", "--input", "-"])
        variables = self.body(calls[2])["variables"]
        self.assertIsInstance(variables["options"], list, "入力オブジェクトの配列は本文の variables に JSON として渡すこと (-F では文字列になる)")
        self.assertEqual([o.get("id") for o in variables["options"][:5]], [o["id"] for o in status["options"]])
        self.assertEqual(variables["options"][-1]["name"], "Blocked")
        self.assertEqual(variables["fieldId"], status["id"])
        self.responses([self.meta_entry()])
        meta = project.read_meta(PROJECT)["project"]
        self.assertEqual(project.add_fields(meta, project.check(meta)), [], "不足が無ければ gh を実行しないこと")


class ItemsTest(FakeGhCase):

    def test_items_keep_position_and_carry_everything(self):
        """Covers AE18, AE19, AE52. 一覧は固定データの順を保ち、各項目に Status・フィールド・blocker・親・リポジトリと公開範囲・PR が付く。"""
        self.responses([{"substring": "query ProjectItems", "stdout": {"fixture": "project-items-ok"}}])
        result = project.items(PROJECT)
        self.assertEqual(result["status"], "ok", result)
        items = result["items"]
        self.assertEqual([i["key"] for i in items][:3], ["akm/issue-dispatch-verify-a#3", "akm/issue-dispatch-verify-a#2", "akm/issue-dispatch-verify-a#1"])
        self.assertEqual([i["position"] for i in items], [1, 2, 3, 4, 5])
        first = items[0]
        self.assertEqual(first["status"]["name"], "In Progress")
        self.assertEqual(first["fields"]["Agent session ID"]["text"], "u1-9")
        self.assertTrue(first["fields"]["Agent session ID"]["updated_at"])
        self.assertEqual((first["repo"], first["visibility"], first["in_organization"]), ("akm/issue-dispatch-verify-a", "PRIVATE", False))
        self.assertEqual(first["is_parent"], False)
        self.assertEqual(first["blocked_by"], [])
        self.assertEqual(len(first["body_edits"]), 2)
        self.assertEqual(first["body_edits"][0]["editor"], "akm")
        self.assertEqual(len(first["comments"]), 10)
        self.assertEqual(first["comments"][0]["author"], "akm")
        third = items[2]
        self.assertEqual(third["status"]["name"], "Done")
        self.assertEqual(third["prs"][0]["number"], 4)
        self.assertEqual((third["prs"][0]["state"], third["prs"][0]["merged"], third["prs"][0]["draft"]), ("MERGED", True, False))
        self.assertEqual(items[3]["repo"], "akm/issue-dispatch-verify-b")
        self.assertEqual(items[3]["status"]["name"], "Todo")
        self.assertEqual(result["rate_limit"]["cost"], 8)

    def test_events_are_sorted_by_time(self):
        self.responses([{"substring": "query ProjectItems", "stdout": {"fixture": "project-items-ok"}}])
        third = project.items(PROJECT)["items"][2]
        types = [e["type"] for e in third["events"]]
        self.assertEqual(types, ["AddedToProjectV2Event", "ProjectV2ItemStatusChangedEvent", "ProjectV2ItemStatusChangedEvent",
                                 "ClosedEvent", "ProjectV2ItemStatusChangedEvent", "ReopenedEvent"])
        self.assertEqual([e["at"] for e in third["events"]], sorted(e["at"] for e in third["events"]), "時刻の順であること")
        closed = next(e for e in third["events"] if e["type"] == "ClosedEvent")
        self.assertEqual(closed["closer_pr"], 4, "ClosedEvent の closer は PR の番号")
        done = third["events"][4]
        self.assertEqual((done["status"], done["previous_status"], done["was_automated"]), ("Done", "In Progress", False))

    def test_items_follow_pages(self):
        """ページは pageInfo で辿り、2 ページ目は endCursor を after に渡す。位置は通しで数える。"""
        self.responses([{"substring": ["query ProjectItems", '"after": "CURSOR-PAGE-1"'], "stdout": {"fixture": "project-items-page2"}},
                        {"substring": "query ProjectItems", "stdout": {"fixture": "project-items-page1"}}])
        result = project.items(PROJECT)
        self.assertEqual(result["status"], "ok")
        self.assertEqual([i["position"] for i in result["items"]], [1, 2, 3, 4, 5])
        calls = self.recorded_full()
        self.assertEqual(len(calls), 2)
        self.assertNotIn("after", self.body(calls[0])["variables"], "1 ページ目は after を渡さないこと")
        self.assertEqual(self.body(calls[1])["variables"]["after"], "CURSOR-PAGE-1")

    def test_comment_pages_are_followed_per_issue(self):
        """コメントが 1 ページに収まらない項目は、Issue ごとの続きのページを読んで全部返す。"""
        data = fixture_json("project-items-ok")
        node = data["data"]["repositoryOwner"]["projectV2"]["items"]["nodes"][0]
        node["content"]["comments"]["pageInfo"] = {"hasNextPage": True, "endCursor": "C1"}
        more = {"data": {"repository": {"issue": {"comments": {"pageInfo": {"hasNextPage": False, "endCursor": "C2"},
                                                            "nodes": [{"id": "IC_more", "databaseId": 1, "url": "u", "createdAt": "2026-10-20T00:00:00Z",
                                                                       "author": {"login": "akm"}, "body": "more"}]}}}, "rateLimit": {"cost": 1}}}
        self.responses([{"substring": "query ProjectItems", "stdout": data},
                        {"substring": ["query IssueComments", '"after": "C1"', '"name": "issue-dispatch-verify-a"', '"number": 3'], "stdout": more}])
        result = project.items(PROJECT)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["items"][0]["comments"]), 11)
        self.assertEqual(result["items"][0]["comments"][-1]["id"], "IC_more")

    def test_items_error_and_partial(self):
        os.environ["FAKE_GH_MODE"] = "auth_expired"
        result = project.items(PROJECT)
        self.assertEqual((result["status"], result["failure"]), ("error", "auth"))
        os.environ.pop("FAKE_GH_MODE")
        self.responses([{"substring": ["query ProjectItems", '"after": "CURSOR-PAGE-1"'], "stdout": "", "stderr": "gh: boom\n", "exit": 1},
                        {"substring": "query ProjectItems", "stdout": {"fixture": "project-items-page1"}}])
        result = project.items(PROJECT)
        self.assertEqual(result["status"], "partial", "2 ページ目が読めなければ 1 ページ目の結果と問題を返すこと")
        self.assertEqual(len(result["items"]), 3)
        self.assertEqual(result["problems"][0]["what"], "items-page")

    def test_data_with_errors_is_partial_not_error(self):
        """data と errors が一緒に返る応答 (一部の項目だけ読めない) では、読めた項目を返し、errors を知らせる。"""
        data = fixture_json("project-items-ok")
        data["errors"] = [{"type": "FORBIDDEN", "path": ["repositoryOwner", "projectV2", "items", "nodes", 3, "content"],
                           "message": "Resource protected by organization SAML enforcement."}]
        self.responses([{"substring": "query ProjectItems", "stdout": data}])
        result = project.items(PROJECT)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["items"]), 5, "読めた項目を捨てないこと")
        self.assertEqual(result["problems"][0]["what"], "graphql-errors")
        self.assertEqual(result["problems"][0]["errors"][0]["type"], "FORBIDDEN")
        meta = fixture_json("project-meta-ok")
        meta["errors"] = data["errors"]
        self.responses([self.meta_entry(meta)])
        r = project.read_meta(PROJECT)
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["warnings"][0]["type"], "FORBIDDEN", "読めれば errors は warnings に入れること")

    def test_later_page_without_project_is_partial(self):
        """2 ページ目以降で Project が読めなくても、それまでに読んだ項目を捨てない。"""
        self.responses([{"substring": ["query ProjectItems", '"after": "CURSOR-PAGE-1"'], "stdout": {"data": {"repositoryOwner": None}}},
                        {"substring": "query ProjectItems", "stdout": {"fixture": "project-items-page1"}}])
        result = project.items(PROJECT)
        self.assertEqual((result["status"], len(result["items"])), ("partial", 3))
        self.assertEqual(result["problems"][0]["what"], "items-page")

    def test_comment_page_without_issue_is_a_problem(self):
        data = fixture_json("project-items-ok")
        node = data["data"]["repositoryOwner"]["projectV2"]["items"]["nodes"][0]
        node["content"]["comments"]["pageInfo"] = {"hasNextPage": True, "endCursor": "C1"}
        self.responses([{"substring": "query ProjectItems", "stdout": data},
                        {"substring": "query IssueComments", "stdout": {"data": {"repository": {"issue": None}}, "errors": [{"type": "NOT_FOUND", "message": "gone"}]}}])
        result = project.items(PROJECT)
        self.assertEqual(result["status"], "partial", "続きのページの Issue が無くても例外にしないこと")
        self.assertEqual(result["problems"][0]["what"], "comments")
        self.assertEqual(len(result["items"][0]["comments"]), 10)

    def test_non_issue_items_are_kept_without_content(self):
        data = fixture_json("project-items-ok")
        nodes = data["data"]["repositoryOwner"]["projectV2"]["items"]["nodes"]
        nodes.insert(1, {"id": "PVTI_draft", "updatedAt": "2026-10-20T00:00:00Z", "fieldValues": {"nodes": []}, "content": {"__typename": "DraftIssue"}})
        self.responses([{"substring": "query ProjectItems", "stdout": data}])
        items = project.items(PROJECT)["items"]
        self.assertEqual((items[1]["content_type"], items[1]["key"], items[1]["position"]), ("DraftIssue", None, 2))
        self.assertEqual(items[2]["position"], 3)


class WriteTest(FakeGhCase):

    def setUp(self):
        super().setUp()
        self.responses([self.meta_entry(), {"prefix": ["project", "item-edit"], "stdout": "{}"}])
        self.meta = project.read_meta(PROJECT)["project"]

    def test_set_status_rejects_done_and_unknown_without_gh(self):
        """Covers AE5. Done と 5 つ以外の値は gh を実行せずに拒否する。"""
        before = len(self.recorded())
        for value in ("Done", "Closed", "", "ready"):
            with self.subTest(value=value):
                self.assertEqual(project.set_status(self.meta, "PVTI_x", value)["status"], "rejected")
        self.assertEqual(len(self.recorded()), before, "拒否では gh を実行しないこと")

    def test_set_status_writes_option_id(self):
        r = project.set_status(self.meta, "PVTI_x", "In review")
        self.assertEqual(r["status"], "ok")
        args = self.recorded()[-1]
        self.assertEqual(args[:2], ["project", "item-edit"])
        self.assertEqual(args[args.index("--project-id") + 1], self.meta["id"])
        self.assertEqual(args[args.index("--field-id") + 1], self.meta["fields"]["Status"]["id"])
        option = next(o for o in self.meta["fields"]["Status"]["options"] if o["name"] == "In review")
        self.assertEqual(args[args.index("--single-select-option-id") + 1], option["id"])

    def test_text_and_single_select_fields(self):
        r = project.set_text_field(self.meta, "PVTI_x", "Agent session ID", "sess-1")
        self.assertEqual(r["status"], "ok")
        self.assertIn("--text", self.recorded()[-1])
        r = project.set_text_field(self.meta, "PVTI_x", "Agent session ID", None)
        self.assertIn("--clear", self.recorded()[-1], "None なら空にすること")
        r = project.set_single_select_field(self.meta, "PVTI_x", "Agent stuck state", "idle-no-progress")
        self.assertEqual(r["status"], "ok")
        self.assertEqual(project.set_single_select_field(self.meta, "PVTI_x", "Agent stuck state", "stuck")["status"], "rejected")
        self.assertEqual(project.set_text_field(self.meta, "PVTI_x", "No such field", "x")["status"], "rejected")

    def test_write_failure_is_returned(self):
        self.responses([{"prefix": ["project", "item-edit"], "stdout": "", "stderr": "gh: boom\n", "exit": 1}])
        r = project.set_status(self.meta, "PVTI_x", "Ready")
        self.assertEqual((r["status"], r["failure"]), ("error", "other"))


class CliTest(FakeGhCase):

    def _run(self, *args):
        return subprocess.run([sys.executable, _CLI, *args], capture_output=True, text=True, env=dict(os.environ))

    def test_check_and_items(self):
        self.responses([self.meta_entry(), {"substring": "query ProjectItems", "stdout": {"fixture": "project-items-ok"}}])
        p = self._run("project", "check", "--project", "akm/3")
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual((out["status"], out["check"]["ok"], out["errors"]), ("ok", True, []))
        p = self._run("project", "items", "--project", "akm/3")
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(len(out["items"]), 5)
        self.assertEqual(out["items"][0]["key"], "akm/issue-dispatch-verify-a#3")
        out = json.loads(self._run("project", "items", "--project", "akm").stdout)
        self.assertEqual(out["status"], "error")

    def test_set_status_rejects_before_reading_project(self):
        """Covers AE5. Done は Project を読む前に拒否し、gh を 1 度も実行しない。"""
        p = self._run("project", "set-status", "--project", "akm/3", "--item", "PVTI_x", "--status", "Done")
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual(out["status"], "rejected")
        self.assertEqual(self.recorded(), [], "gh を実行しないこと")
        self.responses([self.meta_entry(), {"prefix": ["project", "item-edit"], "stdout": "{}"}])
        out = json.loads(self._run("project", "set-status", "--project", "akm/3", "--item", "PVTI_x", "--status", "Blocked").stdout)
        self.assertEqual((out["status"], out["value"]), ("ok", "Blocked"))


class DocTest(unittest.TestCase):

    def test_items_keys_and_constants_are_documented(self):
        with open(_DOC, encoding="utf-8") as f:
            doc = f.read()
        with open(os.path.join(_FIXTURES, "project-items-ok.stdout"), encoding="utf-8") as f:
            data = json.load(f)
        node = data["data"]["repositoryOwner"]["projectV2"]["items"]["nodes"][2]
        item, _ = project.simplify_item(node, 1)
        for key in sorted(item):
            with self.subTest(key=key):
                self.assertIn(f"`{key}`", doc, "project items の出力のキーが文書の表にあること")
        for name in list(project.CUSTOM_FIELDS) + list(project.STUCK_STATES) + list(project.STATUS_OPTIONS) + \
                list(project.REQUIRED_WORKFLOWS) + list(project.RECOMMENDED_WORKFLOWS) + list(project.DISCOURAGED_WORKFLOWS) + \
                list(project.NOTICE_IF_ENABLED_WORKFLOWS) + list(project.EVENT_TYPES):
            with self.subTest(name=name):
                self.assertIn(f"`{name}`", doc)


if __name__ == "__main__":
    unittest.main()
