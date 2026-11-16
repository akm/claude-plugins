#!/usr/bin/env python3
"""hook SessionStart (サブコマンド hook session-start。ファイル
`gh-notification-dispatch/scripts/gh_notification_dispatch/hook.py`) のテスト (計画の U5 のテストの項目・KTD10)。

CLI の入口をサブプロセスで実行し、標準入力に hook の入力の JSON を渡す。

  python3 -m unittest discover -s gh-notification-dispatch/tests
"""

import json
import os
import shutil
import unittest

from fakegh_case import FakeGhCase

DISPATCHER = "local_00000000-0000-4000-8000-000000000000"
OTHER = "local_00000000-0000-4000-8000-0000000000ff"
T0 = "2026-11-16T06:00:00Z"
RUNNING = {"state": "running", "job_id": "a1b2c3d4", "cron": "7-59/10 * * * *", "created_at": T0,
           "expires_at": "2026-11-23T06:00:00Z", "reminders": [], "stopped_at": None}
STOPPED = {"state": "stopped", "job_id": None, "cron": None, "created_at": None, "expires_at": None, "reminders": [],
           "stopped_at": "2026-11-17T06:00:00Z"}


class HookTest(FakeGhCase):

    def setUp(self):
        super().setUp()
        self.at("2026-11-17T06:00:00Z")
        self.as_session(DISPATCHER)
        self.write_state(RUNNING)

    def write_state(self, schedule):
        state = {"version": 1, "dispatcher": {"session_id": DISPATCHER, "name": "配信", "permission_mode": "auto",
                                              "recorded_at": T0}}
        if schedule is not None:
            state["schedule"] = schedule
        self.write_home("state.json", state)

    def hook(self, source="resume"):
        """hook を実行し、出力の additionalContext を返す。何も出力しなければ None。記録のディレクトリに書かないこと。"""
        before = self.home_files() if os.path.isdir(self.home) else None
        code, out, err = self.cli("hook", "session-start",
                                  stdin=json.dumps({"session_id": "x", "hook_event_name": "SessionStart", "source": source}))
        self.assertEqual(code, 0, err)
        self.assertEqual(self.home_files() if os.path.isdir(self.home) else None, before, "記録のディレクトリに書かない")
        if out is None:
            return None
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")
        return out["hookSpecificOutput"]["additionalContext"]

    def test_running_dispatcher_on_startup_and_resume(self):
        for source in ("startup", "resume"):
            with self.subTest(source=source):
                context = self.hook(source)
                self.assertIn("/gh-notification-dispatch:dispatch resume", context)
                self.assertNotIn("期限 (", context, "期限の前は期限切れを出さない")

    def test_expired(self):
        self.at("2026-11-23T06:00:00Z")
        context = self.hook()
        self.assertIn("/gh-notification-dispatch:dispatch resume", context)
        self.assertIn("期限 (", context)

    def test_compact_and_clear_output_nothing(self):
        """会話の要約と /clear では、同じプロセスに定期の予定が残っているので働かせない。"""
        for source in ("compact", "clear"):
            with self.subTest(source=source):
                self.assertIsNone(self.hook(source))

    def test_other_sessions_output_nothing(self):
        for session in (OTHER, None):
            with self.subTest(session=session):
                self.as_session(session)
                self.assertIsNone(self.hook())

    def test_not_running_outputs_nothing(self):
        for schedule in (STOPPED, None):
            with self.subTest(schedule=schedule and schedule["state"]):
                self.write_state(schedule)
                self.assertIsNone(self.hook())

    def test_without_record_directory_outputs_nothing(self):
        shutil.rmtree(self.home)
        self.assertIsNone(self.hook())
        self.assertFalse(os.path.exists(self.home), "記録のディレクトリを作らない")


if __name__ == "__main__":
    unittest.main()
