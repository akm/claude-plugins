#!/usr/bin/env python3
"""記録 (issue-dispatch/scripts/issue_dispatch/record.py) と、CLI の `record read` / `record apply` / `record log` のテスト。

標準ライブラリの unittest だけで動く。`gh` は使わない。

  python3 -m unittest discover -s issue-dispatch/tests

記録の置き場・キー・扱いの正本は issue-dispatch/skills/issue-dispatch/references/records.md。
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.join(_HERE, "..", "scripts")
sys.path.insert(0, _SCRIPTS)

from issue_dispatch import record  # noqa: E402

_CLI = os.path.join(_SCRIPTS, "issue_dispatch.py")
_DOC = os.path.join(_HERE, "..", "skills", "issue-dispatch", "references", "records.md")
PROJECT = "akm/3"
T1, T2, T3 = "2026-10-21T10:00:00Z", "2026-10-21T10:05:00Z", "2026-10-21T10:10:00Z"


class RecordDirTest(unittest.TestCase):

    def test_record_dir_is_under_manager_root_per_project(self):
        self.assertEqual(record.record_dir("/m", "tmp/issue-dispatch", "akm/3"), "/m/tmp/issue-dispatch/akm-3")
        self.assertEqual(record.record_dir("/m", "tmp/issue-dispatch", {"owner": "akm", "number": 3}), "/m/tmp/issue-dispatch/akm-3")


class LoadSaveTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.join(self._tmp.name, "akm-3")

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, text):
        os.makedirs(self.dir, exist_ok=True)
        with open(os.path.join(self.dir, record.RECORD_FILE), "w", encoding="utf-8") as f:
            f.write(text)

    def test_missing_record_is_new(self):
        rec = record.load(self.dir, PROJECT)
        self.assertEqual(rec["project"], PROJECT)
        self.assertEqual((rec["sessions"], rec["items"], rec["questions"]), ({}, {}, {}))
        self.assertFalse(os.path.exists(os.path.join(self.dir, record.RECORD_FILE)), "読むだけでは作らないこと")

    def test_corrupt_records_stop(self):
        """Covers AE10. 壊れた記録は Corrupt で止め、新規として扱わない。"""
        cases = {
            "not json": "{",
            "top level not object": "[]",
            "missing key": json.dumps({"project": PROJECT, "manager": None, "sessions": {}, "items": {}}),
            "items is a list": json.dumps({"project": PROJECT, "manager": None, "sessions": {}, "items": [], "questions": {}}),
            "wrong project": json.dumps({"project": "akm/4", "manager": None, "sessions": {}, "items": {}, "questions": {}}),
        }
        for name, text in cases.items():
            with self.subTest(case=name):
                self._write(text)
                with self.assertRaises(record.Corrupt) as cm:
                    record.load(self.dir, PROJECT)
                self.assertIn(record.RECORD_FILE, str(cm.exception))

    def test_unreadable_bytes_and_broken_elements_are_corrupt(self):
        """読めないバイト列と、要素の形の崩れも Corrupt で止める (ok として読んで後の操作で落ちない)。"""
        base = {"project": PROJECT, "manager": None, "sessions": {}, "items": {}, "questions": {}}
        cases = {
            "manager is a string": dict(base, manager="x"),
            "manager state unknown": dict(base, manager={"id": "m", "name": "n", "started_at": T1, "state": "paused",
                                                         "stop_reason": None, "exchanges_since_input": 0}),
            "session is a string": dict(base, sessions={"s1": "y"}),
            "item lacks keys": dict(base, items={"akm/r#1": {"intent": None}}),
            "item resend_count is bool": dict(base, items={"akm/r#1": {"intent": None, "notified_at": None, "resend_count": True,
                                                                        "conflict_choice": None, "reported": {}, "body_edit_confirmed_at": None}}),
            "question options not a list": dict(base, questions={"q1": {"item": "akm/r#1", "kind": "k", "options": "a",
                                                                        "asked_at": T1, "answer": None, "answered_at": None}}),
            "opt_in not an object": dict(base, opt_in_proposals={"akm/r": "yes"}),
        }
        for name, data in cases.items():
            with self.subTest(case=name):
                self._write(json.dumps(data))
                with self.assertRaises(record.Corrupt):
                    record.load(self.dir, PROJECT)
        os.makedirs(self.dir, exist_ok=True)
        with open(os.path.join(self.dir, record.RECORD_FILE), "wb") as f:
            f.write(b"\xff\xfe{}")
        with self.assertRaises(record.Corrupt):
            record.load(self.dir, PROJECT)
        os.unlink(os.path.join(self.dir, record.RECORD_FILE))
        os.makedirs(os.path.join(self.dir, record.RECORD_FILE))
        with self.assertRaises(record.Corrupt):
            record.load(self.dir, PROJECT)

    def test_saved_records_reload(self):
        """apply で作った記録は、保存して読み直せる (要素の形の検査が自分の書いたものを壊れていると見ないこと)。"""
        rec, errors = record.apply(record.new_record(PROJECT), [
            {"op": "set_manager", "id": "m1", "name": "n", "started_at": T1},
            {"op": "set_session", "id": "s1", "name": "w", "repo": "akm/r", "worktree": "/w"},
            {"op": "set_waiting", "id": "s1", "since": T1},
            {"op": "set_refused", "id": "s1", "at": T1, "signal": "go"},
            {"op": "set_intent", "item": "akm/r#1", "session_id": "s1", "session_title": "w", "status": "In Progress", "assignment": 1, "at": T1},
            {"op": "mark_reported", "item": "akm/r#1", "kind": "human_change", "at": T1},
            {"op": "set_opt_in", "repo": "akm/r", "proposed_at": T1, "answer": True},
            {"op": "ask", "question_id": "q1", "item": "akm/r#1", "kind": "conflict", "options": ["a"], "at": T1},
            {"op": "answer", "question_id": "q1", "answer": "a", "at": T2},
            {"op": "set_notice", "key": "n", "at": T1},
        ])
        self.assertEqual(errors, [])
        record.save(self.dir, rec)
        self.assertEqual(record.load(self.dir, PROJECT), rec)

    def test_save_is_atomic(self):
        rec = record.new_record(PROJECT)
        record.save(self.dir, rec)
        self.assertEqual(record.load(self.dir, PROJECT), rec)
        self.assertEqual([n for n in os.listdir(self.dir) if n.startswith(".")], [], "一時ファイルを残さないこと")
        # 保存の途中で失敗しても元の記録が残る
        bad = dict(rec, items={"x": object()})  # JSON にできない
        with self.assertRaises(TypeError):
            record.save(self.dir, bad)
        self.assertEqual(record.load(self.dir, PROJECT), rec, "失敗した保存で元の記録が壊れないこと")
        self.assertEqual([n for n in os.listdir(self.dir) if n.startswith(".")], [])


class ApplyTest(unittest.TestCase):

    def setUp(self):
        self.rec = record.new_record(PROJECT)

    def apply(self, *ops):
        rec, errors = record.apply(self.rec, list(ops))
        self.assertEqual(errors, [], "操作が通ること")
        self.rec = rec
        return rec

    def test_unknown_or_malformed_operations_are_rejected_as_a_whole(self):
        before = json.dumps(self.rec)
        rec, errors = record.apply(self.rec, [{"op": "set_manager", "id": "m1", "name": "n", "started_at": T1},
                                              {"op": "no_such_op"}, {"op": "mark_notified"}])
        self.assertEqual(len(errors), 2, "操作ごとに理由を返すこと")
        self.assertEqual(json.dumps(rec), before, "1 つでも誤りがあれば何も適用しないこと")

    def test_intent_and_notified(self):
        """Covers AE9. 意図があって notified が無い項目は列挙され、同じ印を 2 度付けても時刻は最初のまま。"""
        self.apply({"op": "set_intent", "item": "akm/r#12", "session_id": "s1", "session_title": "worker", "status": "In Progress",
                    "assignment": 1, "at": T1})
        self.assertEqual(record.items_without_notified(self.rec), ["akm/r#12"])
        self.assertTrue(record.intent_matches(self.rec, "akm/r#12", {"session_id": "s1", "session_title": "worker", "status": "In Progress"}),
                        "Project の値が意図と一致すれば自分の書き込み")
        self.assertFalse(record.intent_matches(self.rec, "akm/r#12", {"session_id": "s2", "session_title": "worker", "status": "In Progress"}))
        self.assertFalse(record.intent_matches(self.rec, "akm/r#99", {"session_id": "s1"}), "意図の無い項目は一致しない")
        self.apply({"op": "mark_notified", "item": "akm/r#12", "at": T2})
        self.apply({"op": "mark_notified", "item": "akm/r#12", "at": T3})
        self.assertEqual(self.rec["items"]["akm/r#12"]["notified_at"], T2, "2 度付けても最初の時刻のまま")
        self.assertEqual(record.items_without_notified(self.rec), [])
        self.apply({"op": "clear_intent", "item": "akm/r#12"})
        self.assertIsNone(self.rec["items"]["akm/r#12"]["intent"])
        self.assertIsNone(self.rec["items"]["akm/r#12"]["notified_at"], "意図を消せば印も消える")

    def test_resend_count(self):
        self.apply({"op": "set_intent", "item": "akm/r#12", "session_id": "s1", "session_title": "w", "status": "In Progress",
                    "assignment": 1, "at": T1})
        self.assertTrue(record.can_resend(self.rec, "akm/r#12"), "まだ再送していなければ再送できる")
        self.apply({"op": "count_resend", "item": "akm/r#12"})
        self.assertFalse(record.can_resend(self.rec, "akm/r#12"), "再送は通算 1 回。1 回再送した後は再送しない")
        self.assertEqual(self.rec["items"]["akm/r#12"]["resend_count"], 1)
        resends = 0
        rec = self.rec
        while record.can_resend(rec, "akm/r#12"):
            resends += 1
            rec, _ = record.apply(rec, [{"op": "count_resend", "item": "akm/r#12"}])
        self.assertEqual(resends, 0, "確認する → 再送 → 数える の順で使っても通算 1 回を超えないこと")

    def test_manager_and_exchanges(self):
        self.apply({"op": "set_manager", "id": "m1", "name": "issue-dispatch akm/3/akm", "started_at": T1})
        m = self.rec["manager"]
        self.assertEqual((m["id"], m["state"], m["stop_reason"], m["exchanges_since_input"]), ("m1", "active", None, 0))
        self.apply({"op": "count_exchange"}, {"op": "count_exchange"})
        self.assertEqual(self.rec["manager"]["exchanges_since_input"], 2)
        self.apply({"op": "reset_exchanges"})
        self.assertEqual(self.rec["manager"]["exchanges_since_input"], 0)
        self.apply({"op": "set_manager_state", "state": "stopped", "stop_reason": "gh auth expired"})
        self.assertEqual((self.rec["manager"]["state"], self.rec["manager"]["stop_reason"]), ("stopped", "gh auth expired"))
        _, errors = record.apply(self.rec, [{"op": "set_manager_state", "state": "paused"}])
        self.assertEqual(len(errors), 1, "状態は active / stopped / ended だけ")

    def test_sessions_waiting_and_refused(self):
        self.apply({"op": "set_session", "id": "s1", "name": "w1", "repo": "akm/r", "worktree": "/w1"},
                   {"op": "set_session", "id": "s2", "name": "w2", "repo": "akm/r", "worktree": "/w2"},
                   {"op": "set_waiting", "id": "s2", "since": T1},
                   {"op": "set_waiting", "id": "s1", "since": T2})
        self.assertEqual([s["id"] for s in record.waiting_sessions(self.rec)], ["s2", "s1"], "待機中のセッションを時刻の順に返すこと")
        self.apply({"op": "clear_waiting", "id": "s2"})
        self.assertEqual([s["id"] for s in record.waiting_sessions(self.rec)], ["s1"])
        self.apply({"op": "set_session_state", "id": "s1", "state": "waiting"})
        self.assertEqual(self.rec["sessions"]["s1"]["seen_state"], "waiting")
        self.apply({"op": "set_refused", "id": "s1", "at": T3, "signal": "assigned"})
        self.assertEqual(self.rec["sessions"]["s1"]["refused"], {"at": T3, "signal": "assigned"})
        self.apply({"op": "set_refused", "id": "s1", "at": "2026-10-22T00:00:00Z", "signal": "go"})
        self.assertEqual(self.rec["sessions"]["s1"]["refused"]["at"], T3, "最初に拒まれた時刻を保つこと")
        _, errors = record.apply(self.rec, [{"op": "set_waiting", "id": "s9", "since": T1}])
        self.assertEqual(len(errors), 1, "無いセッションには付けない")

    def test_reported_marks_choice_and_body_edit(self):
        self.apply({"op": "mark_reported", "item": "akm/r#5", "kind": "human_change", "at": T1},
                   {"op": "mark_reported", "item": "akm/r#5", "kind": "human_change", "at": T2})
        self.assertEqual(self.rec["items"]["akm/r#5"]["reported"], {"human_change": T1}, "報告済みの印は最初の時刻のまま")
        self.assertTrue(record.is_reported(self.rec, "akm/r#5", "human_change"))
        self.assertFalse(record.is_reported(self.rec, "akm/r#5", "not_assigned"))
        self.apply({"op": "set_conflict_choice", "item": "akm/r#5", "choice": "proceed"},
                   {"op": "set_body_edit_confirmed", "item": "akm/r#5", "at": T2})
        self.assertEqual(self.rec["items"]["akm/r#5"]["conflict_choice"], "proceed")
        self.assertEqual(self.rec["items"]["akm/r#5"]["body_edit_confirmed_at"], T2)
        self.apply({"op": "set_notice", "key": "plugin-version-mismatch", "at": T1})
        self.assertEqual(self.rec["notices"], {"plugin-version-mismatch": T1})

    def test_opt_in_proposals(self):
        self.apply({"op": "set_opt_in", "repo": "akm/pub", "proposed_at": T1, "answer": None})
        self.assertEqual(self.rec["opt_in_proposals"]["akm/pub"], {"proposed_at": T1, "answer": None})
        self.apply({"op": "set_opt_in", "repo": "akm/pub", "proposed_at": T1, "answer": True})
        self.assertTrue(self.rec["opt_in_proposals"]["akm/pub"]["answer"])

    def test_questions_and_answers(self):
        self.apply({"op": "ask", "question_id": "q1", "item": "akm/r#5", "kind": "conflict", "options": ["wait", "small-pr", "proceed"], "at": T1})
        self.assertEqual([q["question_id"] for q in record.unanswered_questions(self.rec)], ["q1"])
        _, errors = record.apply(self.rec, [{"op": "answer", "question_id": "q1", "answer": "later", "at": T2}])
        self.assertEqual(len(errors), 1, "選択肢に無い回答は受け付けない")
        self.apply({"op": "answer", "question_id": "q1", "answer": "proceed", "at": T2})
        self.assertEqual(record.unanswered_questions(self.rec), [])
        self.assertEqual(self.rec["questions"]["q1"]["answered_at"], T2)
        _, errors = record.apply(self.rec, [{"op": "answer", "question_id": "q9", "answer": "x", "at": T2}])
        self.assertEqual(len(errors), 1, "無い質問には回答できない")
        _, errors = record.apply(self.rec, [{"op": "ask", "question_id": "q1", "item": "akm/r#5", "kind": "conflict", "options": ["wait"], "at": T3}])
        self.assertEqual(len(errors), 1, "同じ ID の質問を立て直せない (回答が消えるため)")
        self.assertEqual(self.rec["questions"]["q1"]["answer"], "proceed")

    def test_withdraw_question(self):
        """取り下げた質問は未回答に数えず、回答は null のまま。回答のある質問は取り下げられない。"""
        self.apply({"op": "ask", "question_id": "q2", "item": "akm/r#6", "kind": "close-in-progress", "options": ["stop", "reopen"], "at": T1})
        self.apply({"op": "withdraw", "question_id": "q2", "at": T2})
        self.assertEqual((record.unanswered_questions(self.rec), self.rec["questions"]["q2"]["answer"], self.rec["questions"]["q2"]["answered_at"]), ([], None, T2))
        _, errors = record.apply(self.rec, [{"op": "withdraw", "question_id": "q1", "at": T3}])
        self.assertEqual(len(errors), 1, "回答のある質問は取り下げられない")

    def test_null_and_out_of_range_values_are_rejected(self):
        """必須のキーの null・bool や 0 の assignment・null や空の answer は、例外ではなく誤りとして差し戻す。"""
        before = json.dumps(self.rec)
        intent = {"op": "set_intent", "item": "akm/r#1", "session_id": "s", "session_title": "t", "status": "In Progress", "at": T1}
        cases = [{"op": "clear_intent", "item": None},
                 {"op": "set_manager", "id": None, "name": "n", "started_at": T1},
                 {"op": "set_opt_in", "repo": None, "proposed_at": T1},
                 dict(intent, assignment=True), dict(intent, assignment=0), dict(intent, assignment=-1), dict(intent, assignment="1")]
        for op in cases:
            with self.subTest(op=op):
                rec, errors = record.apply(self.rec, [op])
                self.assertEqual(len(errors), 1)
                self.assertEqual(json.dumps(rec), before)
        self.apply({"op": "set_manager", "id": "m", "name": "n", "started_at": T1},
                   {"op": "set_manager_state", "state": "stopped", "stop_reason": None},
                   {"op": "set_opt_in", "repo": "akm/r", "proposed_at": T1, "answer": None},
                   {"op": "ask", "question_id": "q1", "item": "akm/r#1", "kind": "free", "options": [], "at": T1})
        for answer in (None, "", 1):
            with self.subTest(answer=answer):
                _, errors = record.apply(self.rec, [{"op": "answer", "question_id": "q1", "answer": answer, "at": T2}])
                self.assertEqual(len(errors), 1, "回答は空でない文字列に限ること")
        self.apply({"op": "answer", "question_id": "q1", "answer": "free text", "at": T2})
        self.assertEqual(record.unanswered_questions(self.rec), [])

    def test_options_must_be_distinct_non_empty_strings(self):
        """選択肢の要素は空でない文字列で重複しない (回答が文字列だけなので、文字列でない選択肢には回答できない)。"""
        for options in ([1, 2], [None], [{"a": 1}], ["a", ""], ["a", "a"]):
            with self.subTest(options=options):
                _, errors = record.apply(self.rec, [{"op": "ask", "question_id": "q1", "item": "akm/r#1", "kind": "k", "options": options, "at": T1}])
                self.assertEqual(len(errors), 1)
        self.apply({"op": "ask", "question_id": "q1", "item": "akm/r#1", "kind": "k", "options": ["a", "b"], "at": T1},
                   {"op": "answer", "question_id": "q1", "answer": "b", "at": T2})
        self.assertEqual(self.rec["questions"]["q1"]["answer"], "b")

    def test_item_keys_must_be_issue_references(self):
        _, errors = record.apply(self.rec, [{"op": "mark_reported", "item": "https://github.com/akm/r/issues/5", "kind": "x", "at": T1}])
        self.assertEqual(len(errors), 1, "項目のキーは owner/repo#番号 の形")


class NamePatternTest(unittest.TestCase):

    def test_pattern_matches_config(self):
        """record は config を import しないので、リポジトリの名前の形を写している。同じ文字列であることを確認する。"""
        from issue_dispatch import config
        self.assertEqual(record.REPO_NAME_PATTERN, config.REPO_NAME_PATTERN)
        rec = record.new_record(PROJECT)
        _, errors = record.apply(rec, [{"op": "mark_reported", "item": "akm/.github#1", "kind": "x", "at": T1}])
        self.assertEqual(errors, [], "`.github` のような名前の項目も受け付けること")


class ActionsLogTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.join(self._tmp.name, "akm-3")

    def tearDown(self):
        self._tmp.cleanup()

    def test_append_requires_keys_and_appends_one_line(self):
        entry = {"at": T1, "kind": "set-status", "target": "akm/r#12", "before": "Ready", "after": "In Progress", "reason": "割り当て 1"}
        record.append_action(self.dir, entry)
        record.append_action(self.dir, dict(entry, at=T2, reason="再送"))
        with open(os.path.join(self.dir, record.ACTIONS_LOG), encoding="utf-8") as f:
            lines = f.read().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0]), entry)
        with self.assertRaises(ValueError):
            record.append_action(self.dir, {"at": T1, "kind": "x"})


class CliTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        cfg = os.path.join(self.root, ".claude", "akm-claude-plugins", "issue-dispatch", "config.json")
        os.makedirs(os.path.dirname(cfg))
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump({"project": {"owner": "akm", "number": 3}, "record_dir": "rec"}, f)
        self.dir = os.path.join(self.root, "rec", "akm-3")

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *args, stdin=None):
        return subprocess.run([sys.executable, _CLI, *args], capture_output=True, text=True, input=stdin)

    def test_read_new_apply_and_read(self):
        p = self._run("record", "read", "--dir", self.root)
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual((out["status"], out["record"]["project"], out["errors"]), ("new", "akm/3", []))
        self.assertEqual(out["path"], os.path.join(self.dir, "record.json"))
        ops = [{"op": "set_manager", "id": "m1", "name": "n", "started_at": T1},
               {"op": "set_intent", "item": "akm/r#12", "session_id": "s1", "session_title": "w", "status": "In Progress", "assignment": 1, "at": T1}]
        p = self._run("record", "apply", "--dir", self.root, stdin=json.dumps(ops))
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual((out["status"], out["applied"], out["errors"]), ("ok", 2, []))
        out = json.loads(self._run("record", "read", "--dir", self.root).stdout)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["record"]["manager"]["id"], "m1")
        self.assertEqual(out["record"]["items"]["akm/r#12"]["intent"]["session_id"], "s1")

    def test_apply_rejects_bad_operations_without_saving(self):
        p = self._run("record", "apply", "--dir", self.root, stdin=json.dumps([{"op": "nope"}]))
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual((out["status"], out["applied"]), ("rejected", 0))
        self.assertTrue(out["errors"])
        self.assertFalse(os.path.exists(os.path.join(self.dir, "record.json")), "誤った操作では保存しないこと")
        p = self._run("record", "apply", "--dir", self.root, stdin="not json")
        self.assertEqual(json.loads(p.stdout)["status"], "rejected")

    def test_corrupt_record_is_reported_and_not_overwritten(self):
        os.makedirs(self.dir)
        with open(os.path.join(self.dir, "record.json"), "w", encoding="utf-8") as f:
            f.write("{")
        out = json.loads(self._run("record", "read", "--dir", self.root).stdout)
        self.assertEqual(out["status"], "corrupt")
        self.assertIsNone(out["record"])
        self.assertTrue(out["errors"])
        p = self._run("record", "apply", "--dir", self.root, stdin=json.dumps([{"op": "count_exchange"}]))
        self.assertEqual(json.loads(p.stdout)["status"], "corrupt")
        with open(os.path.join(self.dir, "record.json"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "{", "壊れた記録を上書きしないこと")

    def test_log_appends(self):
        entry = {"at": T1, "kind": "comment", "target": "akm/r#12", "before": None, "after": "割り当て", "reason": "割り当て 1"}
        p = self._run("record", "log", "--dir", self.root, stdin=json.dumps(entry))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["status"], "ok")
        with open(os.path.join(self.dir, "actions.log"), encoding="utf-8") as f:
            self.assertEqual(json.loads(f.read().splitlines()[0]), entry)
        p = self._run("record", "log", "--dir", self.root, stdin=json.dumps({"at": T1}))
        self.assertEqual(json.loads(p.stdout)["status"], "rejected")

    def test_missing_project_in_config_is_an_error(self):
        cfg = os.path.join(self.root, ".claude", "akm-claude-plugins", "issue-dispatch", "config.json")
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump({"record_dir": "rec"}, f)
        out = json.loads(self._run("record", "read", "--dir", self.root).stdout)
        self.assertEqual(out["status"], "config-error")
        self.assertTrue(out["errors"])


class DocTest(unittest.TestCase):

    def test_record_keys_are_documented(self):
        """record.json のキーが records.md の表と一致する。"""
        with open(_DOC, encoding="utf-8") as f:
            doc = f.read()
        rec = record.new_record(PROJECT)
        rec, _ = record.apply(rec, [
            {"op": "set_manager", "id": "m1", "name": "n", "started_at": T1},
            {"op": "set_session", "id": "s1", "name": "w", "repo": "akm/r", "worktree": "/w"},
            {"op": "set_intent", "item": "akm/r#1", "session_id": "s1", "session_title": "w", "status": "In Progress", "assignment": 1, "at": T1},
            {"op": "set_opt_in", "repo": "akm/r", "proposed_at": T1, "answer": None},
            {"op": "ask", "question_id": "q1", "item": "akm/r#1", "kind": "conflict", "options": ["a"], "at": T1},
        ])
        names = set(rec) | set(rec["manager"]) | set(rec["sessions"]["s1"]) | set(rec["items"]["akm/r#1"]) \
            | set(rec["items"]["akm/r#1"]["intent"]) | set(rec["opt_in_proposals"]["akm/r"]) | set(rec["questions"]["q1"])
        for name in sorted(names):
            with self.subTest(key=name):
                self.assertIn(f"`{name}`", doc)
        for op in sorted(record.OPERATIONS):
            with self.subTest(op=op):
                self.assertIn(f"`{op}`", doc, "操作の種類が文書の表にあること")
        for key in record.ACTION_KEYS:
            self.assertIn(f"`{key}`", doc)


if __name__ == "__main__":
    unittest.main()
