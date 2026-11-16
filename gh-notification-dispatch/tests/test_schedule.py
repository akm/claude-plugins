#!/usr/bin/env python3
"""定期の予定の記録 (サブコマンド schedule record・schedule clear。ファイル
`gh-notification-dispatch/scripts/gh_notification_dispatch/schedule.py`) のテスト (計画の U5 のテストの項目)。

CLI の入口をサブプロセスで実行する。

  python3 -m unittest discover -s gh-notification-dispatch/tests
"""

import unittest

from fakegh_case import FakeGhCase

DISPATCHER = "local_00000000-0000-4000-8000-000000000000"
OTHER = "local_00000000-0000-4000-8000-0000000000ff"
T0 = "2026-11-16T06:00:00Z"
CRON = "7-59/10 * * * *"


class ScheduleCase(FakeGhCase):

    def setUp(self):
        super().setUp()
        self.at(T0)
        self.as_session(DISPATCHER)
        self.write_home("state.json", {"version": 1, "dispatcher": {"session_id": DISPATCHER, "name": "配信",
                                                                   "permission_mode": "auto", "recorded_at": T0}})

    def record(self, job_id="a1b2c3d4", cron=CRON, at=None):
        if at:
            self.at(at)
        code, out, err = self.cli("schedule", "record", "--job-id", job_id, "--cron", cron)
        self.assertIsNotNone(out, err)
        return code, out

    def clear(self, at=None):
        if at:
            self.at(at)
        code, out, err = self.cli("schedule", "clear")
        self.assertIsNotNone(out, err)
        return code, out

    def schedule(self):
        return self.read_home("state.json").get("schedule")


class RecordTest(ScheduleCase):

    def test_record_sets_expiry_seven_days_later(self):
        code, out = self.record()
        self.assertEqual(code, 0, out)
        expected = {"state": "running", "job_id": "a1b2c3d4", "cron": CRON, "created_at": T0,
                    "expires_at": "2026-11-23T06:00:00Z", "reminders": [], "stopped_at": None}
        self.assertEqual(out["schedule"], expected)
        self.assertIsNone(out["previous"])
        self.assertEqual(self.schedule(), expected)

    def test_renew_clears_reminders_and_moves_expiry(self):
        """renew (作り直して記録し直す) の後は、出した確認の記録を消し、期限を 7 日後にする。"""
        self.record()
        state = self.read_home("state.json")
        state["schedule"]["reminders"] = [24, 6]
        self.write_home("state.json", state)
        code, out = self.record(job_id="e5f6a7b8", at="2026-11-22T20:00:00Z")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["previous"]["reminders"], [24, 6])
        self.assertEqual((self.schedule()["job_id"], self.schedule()["reminders"], self.schedule()["expires_at"]),
                         ("e5f6a7b8", [], "2026-11-29T20:00:00Z"))

    def test_clear_records_stop(self):
        self.record()
        code, out = self.clear(at="2026-11-17T06:00:00Z")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.schedule(), {"state": "stopped", "job_id": None, "cron": None, "created_at": None,
                                           "expires_at": None, "reminders": [], "stopped_at": "2026-11-17T06:00:00Z"})
        self.assertEqual(out["previous"]["job_id"], "a1b2c3d4")

    def test_other_session_changes_nothing(self):
        """前の配信のセッションでの stop・renew・resume が、切り替えた後の記録を書き換えない (KTD3)。"""
        self.record()
        self.as_session(OTHER)
        before = self.home_files()
        for args in (("record", "--job-id", "ffff0000", "--cron", CRON), ("clear",)):
            with self.subTest(command=args[0]):
                code, out, _ = self.cli("schedule", *args)
                self.assertEqual(code, 3, out)
                self.assertIsNone(out["schedule"])
                self.assertTrue(out["errors"])
        self.assertEqual(self.home_files(), before)

    def test_without_session_id_changes_nothing(self):
        self.as_session(None)
        before = self.home_files()
        self.assertEqual(self.record()[0], 3)
        self.assertEqual(self.home_files(), before)

    def test_invalid_values_are_refused(self):
        before = self.home_files()
        for job_id, cron in (("", CRON), ("a b", CRON), ("a1b2c3d4", "*/10 * * *"), ("a1b2c3d4", "*/10 * * * * *"),
                             ("a1b2c3d4", "*/10 * * * ;")):
            with self.subTest(job_id=job_id, cron=cron):
                code, out = self.record(job_id=job_id, cron=cron)
                self.assertEqual(code, 3, out)
                self.assertTrue(out["errors"])
        self.assertEqual(self.home_files(), before)


if __name__ == "__main__":
    unittest.main()
