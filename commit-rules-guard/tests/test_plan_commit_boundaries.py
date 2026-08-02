#!/usr/bin/env python3
"""計画時フック（plan-commit-boundaries.py）のテスト。

標準ライブラリの unittest だけで動く（利用者の環境に pytest 等を要求しない）。

  python3 -m unittest discover -s commit-rules-guard/tests

ここでテストするのは、モデルの裁量ではなく決定的に決まるべき部分:
  - 発火頻度の間引き（同じ計画で二度出さない / 作り直されたら出す）
  - 対象ツールの判定
  - リポジトリ外では黙る
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

_HOOK = os.path.join(
    os.path.dirname(__file__), "..", "hook-scripts", "plan-commit-boundaries.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("plan_commit_boundaries", _HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


plan = _load()

NOTIFIED = 2
SILENT = 0


class TestPlanDigest(unittest.TestCase):
    """計画の「実質的な内容」の取り出し。"""

    def test_same_content_same_digest(self):
        a = {"todos": [{"content": "A を直す", "status": "pending"}]}
        b = {"todos": [{"content": "A を直す", "status": "pending"}]}
        self.assertEqual(plan.plan_digest(a), plan.plan_digest(b))

    def test_status_change_does_not_change_digest(self):
        # TodoWrite は状態更新のたびに呼ばれる。ここで digest が変わると、
        # 同じ文言が数分おきに出てノイズになり「慣れ」を招く。
        before = {"todos": [{"content": "A を直す", "status": "pending"}]}
        after = {"todos": [{"content": "A を直す", "status": "completed"}]}
        self.assertEqual(plan.plan_digest(before), plan.plan_digest(after))

    def test_different_content_differs(self):
        a = {"todos": [{"content": "A を直す"}]}
        b = {"todos": [{"content": "B を直す"}]}
        self.assertNotEqual(plan.plan_digest(a), plan.plan_digest(b))

    def test_added_task_changes_digest(self):
        # 計画が作り直されたら境界の再検討が要るので、再度促してよい。
        a = {"todos": [{"content": "A を直す"}]}
        b = {"todos": [{"content": "A を直す"}, {"content": "B も直す"}]}
        self.assertNotEqual(plan.plan_digest(a), plan.plan_digest(b))

    def test_empty_input_has_no_digest(self):
        self.assertIsNone(plan.plan_digest({}))
        self.assertIsNone(plan.plan_digest({"todos": []}))
        self.assertIsNone(plan.plan_digest(None))

    def test_plain_text_plan(self):
        # ExitPlanMode は文字列で計画を渡す。
        self.assertIsNotNone(plan.plan_digest({"plan": "まず X をして、次に Y"}))


class TestHookBehavior(unittest.TestCase):
    """フック本体の入出力（実際にプロセスとして起動する）。"""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self._dir.name, "repo")
        os.makedirs(self.repo)
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        self.state = os.path.join(self._dir.name, "state")

    def tearDown(self):
        self._dir.cleanup()

    def _run(self, payload, cwd=None):
        env = dict(os.environ, COMMIT_GUARD_STATE_DIR=self.state)
        p = subprocess.run(
            [sys.executable, _HOOK],
            input=json.dumps(payload),
            capture_output=True, text=True,
            cwd=cwd if cwd is not None else self.repo,
            env=env,
        )
        return p.returncode, p.stderr

    def _payload(self, tool_name="TodoWrite", todos=None, session="s1"):
        # todos=[] を「既定値」に差し替えないよう None とは区別する。
        if todos is None:
            todos = [{"content": "A を直す", "status": "pending"}]
        return {
            "session_id": session,
            "cwd": self.repo,
            "hook_event_name": "PostToolUse",
            "tool_name": tool_name,
            "tool_input": {"todos": todos},
        }

    def test_notifies_once_for_a_new_plan(self):
        code, err = self._run(self._payload())
        self.assertEqual(code, NOTIFIED)
        self.assertIn("コミット境界", err)

    def test_does_not_repeat_for_the_same_plan(self):
        # ここが本フックの成否を分ける。繰り返すと無視されるようになる。
        self.assertEqual(self._run(self._payload())[0], NOTIFIED)
        self.assertEqual(self._run(self._payload())[0], SILENT)
        self.assertEqual(self._run(self._payload())[0], SILENT)

    def test_does_not_repeat_on_status_updates(self):
        self.assertEqual(self._run(self._payload())[0], NOTIFIED)
        updated = self._payload(
            todos=[{"content": "A を直す", "status": "in_progress"}])
        self.assertEqual(self._run(updated)[0], SILENT)
        done = self._payload(todos=[{"content": "A を直す", "status": "completed"}])
        self.assertEqual(self._run(done)[0], SILENT)

    def test_notifies_again_when_the_plan_is_rewritten(self):
        self.assertEqual(self._run(self._payload())[0], NOTIFIED)
        rewritten = self._payload(todos=[{"content": "まったく別の作業"}])
        self.assertEqual(self._run(rewritten)[0], NOTIFIED)

    def test_separate_sessions_each_get_one(self):
        self.assertEqual(self._run(self._payload(session="s1"))[0], NOTIFIED)
        self.assertEqual(self._run(self._payload(session="s2"))[0], NOTIFIED)

    def test_ignores_unrelated_tools(self):
        self.assertEqual(self._run(self._payload(tool_name="Bash"))[0], SILENT)
        self.assertEqual(self._run(self._payload(tool_name="Read"))[0], SILENT)

    def test_handles_the_other_planning_tools(self):
        for name in ("ExitPlanMode", "TaskCreate", "TaskUpdate"):
            code, _ = self._run(self._payload(tool_name=name, session="s-" + name))
            self.assertEqual(code, NOTIFIED, name + " で発火しなかった")

    def test_silent_outside_a_repository(self):
        # コミットの話が無関係な場所では黙る。
        outside = os.path.join(self._dir.name, "plain")
        os.makedirs(outside)
        payload = self._payload()
        payload["cwd"] = outside
        self.assertEqual(self._run(payload, cwd=outside)[0], SILENT)

    def test_silent_for_empty_plans(self):
        payload = self._payload(todos=[])
        self.assertEqual(self._run(payload)[0], SILENT)

    def test_malformed_input_does_not_break_the_session(self):
        env = dict(os.environ, COMMIT_GUARD_STATE_DIR=self.state)
        p = subprocess.run([sys.executable, _HOOK], input="{ not json",
                           capture_output=True, text=True, cwd=self.repo, env=env)
        self.assertEqual(p.returncode, SILENT)

    def test_missing_session_id_still_throttles(self):
        # session_id が取れない環境でも、毎回出すよりは 1 回に留める。
        payload = self._payload()
        del payload["session_id"]
        self.assertEqual(self._run(payload)[0], NOTIFIED)
        self.assertEqual(self._run(payload)[0], SILENT)


if __name__ == "__main__":
    unittest.main()
