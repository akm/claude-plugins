#!/usr/bin/env python3
"""定期の予定の記録 (サブコマンド schedule record・schedule clear。ファイル
`gh-notification-dispatch/scripts/gh_notification_dispatch/schedule.py`) と状態の表示 (サブコマンド status)、
サブコマンド tick の期限の確認・配信のセッションの確認・再開の後の取得のテスト (計画の U5 のテストの項目)。

CLI の入口をサブプロセスで実行し、偽の `gh` が通知・timeline・所属するチームを返す。

  python3 -m unittest discover -s gh-notification-dispatch/tests
"""

import os
import unittest

from fakegh_case import FakeGhCase, http, notification, timeline_event

DISPATCHER = "local_00000000-0000-4000-8000-000000000000"
OTHER = "local_00000000-0000-4000-8000-0000000000ff"
T0 = "2026-11-16T06:00:00Z"
CRON = "7-59/10 * * * *"
RECEIVER = "local_00000000-0000-4000-8000-00000000000a"
REPO = "akm/claude-plugins"
TEAMS = [{"id": 101, "slug": "reviewers", "name": "reviewers", "organization": {"login": "akm-org", "id": 9}}]


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
        self.assertFalse(out["not_dispatcher"])
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
                self.assertTrue(out["not_dispatcher"], "記録と違うセッションなので、スキルは作った予定を消す")
                self.assertTrue(out["errors"])
        self.assertEqual(self.home_files(), before)

    def test_unconfirmed_session_changes_nothing_and_is_not_flagged(self):
        """環境変数が無い・配信のセッションが記録されていないときは、記録と違うセッションとは示さない (スキルは、記録と違うセッションとは伝えずに質問する)。"""
        for label, session, state in (("環境変数が無い", None, None),
                                      ("配信のセッションが記録されていない", DISPATCHER, {"version": 1})):
            with self.subTest(label):
                self.as_session(session)
                if state is not None:
                    self.write_home("state.json", state)
                before = self.home_files()
                for args in (("record", "--job-id", "ffff0000", "--cron", CRON), ("clear",)):
                    code, out, _ = self.cli("schedule", *args)
                    self.assertEqual(code, 3, out)
                    self.assertFalse(out["not_dispatcher"])
                    self.assertTrue(out["errors"])
                self.assertEqual(self.home_files(), before)

    def test_invalid_values_are_refused(self):
        before = self.home_files()
        for job_id, cron in (("", CRON), ("a b", CRON), ("a1b2c3d4", "*/10 * * *"), ("a1b2c3d4", "*/10 * * * * *"),
                             ("a1b2c3d4", "*/10 * * * ;")):
            with self.subTest(job_id=job_id, cron=cron):
                code, out = self.record(job_id=job_id, cron=cron)
                self.assertEqual(code, 3, out)
                self.assertFalse(out["not_dispatcher"], "形の誤りは、記録と違うセッションではない")
                self.assertTrue(out["errors"])
        self.assertEqual(self.home_files(), before)



class StatusTest(ScheduleCase):
    """状態の表示は読むだけで、どのセッションでも実行でき、記録のディレクトリに書かない。"""

    def status(self, at=None):
        if at:
            self.at(at)
        before = self.home_files() if os.path.isdir(self.home) else None
        code, out, err = self.cli("status")
        self.assertEqual(code, 0, (out, err))
        self.assertEqual(self.home_files() if os.path.isdir(self.home) else None, before, "記録のディレクトリに書かない")
        return out

    def test_running(self):
        self.record()
        out = self.status("2026-11-17T08:30:00Z")
        self.assertTrue(out["is_dispatcher"])
        self.assertEqual((out["schedule"]["state"], out["expired"], out["remaining"]), ("running", False, "5 日 21 時間"))
        self.assertIn("/gh-notification-dispatch:dispatch renew", out["notice"])

    def test_expired_without_tick(self):
        """期限より前に最後の tick が実行され、その後に tick が無いまま期限を過ぎたときも、期限切れと再開の手順を示す (R17)。"""
        self.record()
        out = self.status("2026-11-23T06:00:00Z")
        self.assertEqual((out["expired"], out["remaining"]), (True, None))
        self.assertIn("/gh-notification-dispatch:dispatch resume", out["notice"])
        self.assertEqual(self.schedule()["state"], "running", "期限切れは記録に書かない (KTD9)")

    def test_stopped(self):
        self.record()
        self.clear(at="2026-11-17T06:00:00Z")
        out = self.status("2026-11-30T06:00:00Z")
        self.assertEqual((out["schedule"]["state"], out["expired"], out["remaining"]), ("stopped", False, None))
        self.assertIn("/gh-notification-dispatch:dispatch resume", out["notice"])

    def test_before_schedule_and_other_session(self):
        self.as_session(OTHER)
        out = self.status()
        self.assertFalse(out["is_dispatcher"])
        self.assertEqual(out["dispatcher"]["session_id"], DISPATCHER)
        self.assertIsNone(out["schedule"])
        self.assertIn("/gh-notification-dispatch:dispatch start", out["notice"])

    def test_without_record_directory(self):
        os.remove(os.path.join(self.home, "state.json"))
        os.rmdir(self.home)
        out = self.status()
        self.assertEqual((out["dispatcher"], out["is_dispatcher"], out["schedule"]), (None, False, None))
        self.assertIn("/gh-notification-dispatch:dispatch start", out["notice"])
        self.assertFalse(os.path.exists(self.home), "記録のディレクトリを作らない")

    def test_unreachable_and_expired_events(self):
        """届かない登録と、30 日を過ぎて消した出来事の、登録ごとの累計と最後に消した時刻を示す (R15)。"""
        base = {"repo": REPO, "kind": "review_requested", "session_id": RECEIVER, "session_name": "受信",
                "permission_mode": "auto", "created_at": T0}
        self.write_home("subscriptions.json", {"version": 1, "subscriptions": [
            {**base, "id": "aaaaaaaaaaaa", "consecutive_failures": 3, "expired_events": 0, "last_expired_at": None},
            {**base, "id": "bbbbbbbbbbbb", "kind": "merged", "consecutive_failures": 2, "expired_events": 4,
             "last_expired_at": "2026-11-16T05:00:00Z"},
            {**base, "id": "cccccccccccc", "repo": "akm/other"}]})
        self.write_home("outbox.json", {"version": 1, "pending": [
            {"subscription_id": "aaaaaaaaaaaa", "event": {"key": "review_requested:1"}, "enqueued_at": T0, "outputs": 1}],
            "round": None})
        out = self.status()
        self.assertEqual((out["subscriptions"], out["waiting"]), (3, 1))
        self.assertEqual([(u["subscription_id"], u["consecutive_failures"]) for u in out["unreachable"]],
                         [("aaaaaaaaaaaa", 3)])
        self.assertEqual([(e["subscription_id"], e["expired_events"], e["last_expired_at"]) for e in out["expired_events"]],
                         [("bbbbbbbbbbbb", 4, "2026-11-16T05:00:00Z")])


class TickScheduleCase(ScheduleCase):
    """サブコマンド tick を実行するテスト。T0 に最初の tick を行い、定期の予定を記録する。"""

    def setUp(self):
        super().setUp()
        self.write_home("subscriptions.json", {"version": 1, "subscriptions": [
            {"id": "aaaaaaaaaaaa", "repo": REPO, "kind": "review_requested", "session_id": RECEIVER,
             "session_name": "受信", "permission_mode": "auto", "created_at": "2026-11-16T05:00:00Z"}]})
        self.serve()
        self.assertEqual(self.tick()[0], 0)  # 最初の tick (開始)
        self.assertEqual(self.record()[0], 0)

    def serve(self, notifications=(), timelines=None):
        entries = [{"prefix": ["api", "user"], "stdout": {"login": "akm", "id": 1}},
                   {"prefix": ["api", "-i", "user/teams?per_page=100"], "stdout": http(200, TEAMS)},
                   {"prefix": ["api", "-i"], "substring": "notifications?all=true",
                    "stdout": http(200, list(notifications), {"Etag": 'W/"e1"'})}]
        for (repo, number), items in (timelines or {}).items():
            entries.append({"prefix": ["api", "-i", f"repos/{repo}/issues/{number}/timeline?per_page=100"],
                            "stdout": http(200, items)})
        self.responses(entries)

    def tick(self, at=None):
        if at:
            self.at(at)
        code, out, err = self.cli("tick")
        self.assertIsNotNone(out, err)
        return code, out

    def notice(self, at):
        code, out = self.tick(at)
        self.assertEqual(code, 0, out)
        return out["schedule_notice"]


class ReminderTest(TickScheduleCase):
    """期限 (T0 の 7 日後の 2026-11-23T06:00:00Z) までの残りが 24・6・1 時間を切った回に、確認を 1 回だけ出す (R17)。"""

    def test_each_threshold_once(self):
        self.assertIsNone(self.notice("2026-11-22T05:50:00Z"), "残り 24 時間 10 分では出さない")
        for first, second, hours in (("2026-11-22T07:00:00Z", "2026-11-22T07:10:00Z", 24),
                                     ("2026-11-23T00:10:00Z", "2026-11-23T00:20:00Z", 6),
                                     ("2026-11-23T05:10:00Z", "2026-11-23T05:20:00Z", 1)):
            with self.subTest(hours=hours):
                notice = self.notice(first)
                self.assertEqual((notice["kind"], notice["hours"]), ("reminder", hours))
                self.assertIn("/gh-notification-dispatch:dispatch renew", notice["text"])
                self.assertIsNone(self.notice(second), "次の回では出さない")
        self.assertEqual(self.schedule()["reminders"], [24, 6, 1])

    def test_several_thresholds_in_one_tick_give_one_reminder(self):
        """スリープの後などで、1 つの回で 3 つの閾値を切ったときも、確認は 1 回だけにする。"""
        notice = self.notice("2026-11-23T05:10:00Z")
        self.assertEqual((notice["kind"], notice["hours"]), ("reminder", 1))
        self.assertIn("残り 50 分", notice["text"])
        self.assertEqual(self.schedule()["reminders"], [24, 6, 1])
        self.assertIsNone(self.notice("2026-11-23T05:20:00Z"))

    def test_reminder_is_output_once_even_when_gh_fails(self):
        """確認は gh の失敗とは別に出す。失敗した回に出した確認は、次の回で出し直さない。"""
        os.environ["FAKE_GH_MODE"] = "auth_expired"
        code, out = self.tick("2026-11-22T07:00:00Z")
        self.assertEqual(code, 4, out)
        self.assertEqual(out["schedule_notice"]["hours"], 24)
        os.environ.pop("FAKE_GH_MODE")
        self.serve()
        self.assertIsNone(self.notice("2026-11-22T07:10:00Z"))

    def test_after_renew_reminders_start_over(self):
        self.assertEqual(self.notice("2026-11-22T07:00:00Z")["hours"], 24)
        self.assertEqual(self.record(job_id="e5f6a7b8", at="2026-11-22T07:05:00Z")[0], 0)
        self.assertIsNone(self.notice("2026-11-22T07:10:00Z"), "期限が 2026-11-29T07:05:00Z に変わった")
        self.assertEqual(self.notice("2026-11-28T07:10:00Z")["hours"], 24)

    def test_no_notice_without_running_schedule(self):
        self.assertEqual(self.clear()[0], 0)
        self.assertIsNone(self.notice("2026-11-23T05:10:00Z"), "停止した記録には確認を出さない")
        self.assertIsNone(self.notice("2026-11-24T06:00:00Z"), "停止した記録は期限切れにしない")
        state = self.read_home("state.json")
        del state["schedule"]
        self.write_home("state.json", state)
        self.assertIsNone(self.notice("2026-11-24T06:10:00Z"), "定期の予定を作る前の記録 (手で実行した tick)")


class ExpiredTickTest(TickScheduleCase):

    def test_expired_tick_delivers_and_reports_expiry(self):
        """期限を過ぎた tick (予定の最後の実行) も、取得と配信を通常どおり行い、期限切れと再開の手順を出力する (KTD9)。"""
        self.serve([notification(REPO, 1, "2026-11-23T06:05:00Z")],
                   {(REPO, 1): [timeline_event(10, "2026-11-23T06:04:00Z", login="akm")]})
        code, out = self.tick("2026-11-23T06:10:00Z")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(out["messages"]), 1)
        self.assertEqual(out["schedule_notice"]["kind"], "expired")
        self.assertIn("/gh-notification-dispatch:dispatch resume", out["schedule_notice"]["text"])
        self.assertEqual(self.read_home("state.json")["position"], "2026-11-23T06:10:00Z")


class NotDispatcherTickTest(TickScheduleCase):

    def test_other_session_neither_fetches_nor_outputs(self):
        """記録の配信のセッションと違うセッションの tick は、取得も出力もせずに終了コード 3 で、定期の予定を消すよう示す。"""
        self.as_session(OTHER)
        self.serve([notification(REPO, 1, "2026-11-16T06:05:00Z")],
                   {(REPO, 1): [timeline_event(10, "2026-11-16T06:04:00Z", login="akm")]})
        calls = len(self.recorded())
        before = self.home_files()
        code, out = self.tick("2026-11-16T06:10:00Z")
        self.assertEqual(code, 3, out)
        self.assertTrue(out["not_dispatcher"])
        self.assertEqual((out["messages"], out["schedule_notice"]), ([], None))
        self.assertTrue(out["errors"])
        self.assertEqual(len(self.recorded()), calls, "gh を実行しない")
        self.assertEqual(self.home_files(), before)

    def test_unconfirmed_session_is_not_flagged(self):
        """環境変数が無い・配信のセッションが記録されていないときは、取得も出力もしないが、予定を消すよう示さない (KTD11 の質問)。"""
        state = self.read_home("state.json")
        for label, session, written in (("環境変数が無い", None, state),
                                        ("配信のセッションが記録されていない", DISPATCHER,
                                         {k: v for k, v in state.items() if k != "dispatcher"})):
            with self.subTest(label):
                self.as_session(session)
                self.write_home("state.json", written)
                calls = len(self.recorded())
                before = self.home_files()
                code, out = self.tick("2026-11-16T06:10:00Z")
                self.assertEqual(code, 3, out)
                self.assertFalse(out["not_dispatcher"])
                self.assertTrue(out["errors"])
                self.assertEqual(len(self.recorded()), calls, "gh を実行しない")
                self.assertEqual(self.home_files(), before)

    def test_dispatcher_tick_is_not_flagged(self):
        code, out = self.tick("2026-11-16T06:10:00Z")
        self.assertEqual(code, 0, out)
        self.assertFalse(out["not_dispatcher"])


class ResumeTest(TickScheduleCase):
    """スキル dispatch の resume (dispatcher set で配信のセッションを記録し直し、定期の予定を作り直して記録する) の後の tick。"""

    def resume(self, at):
        self.at(at)
        code, out, err = self.cli("dispatcher", "set", "--name", "配信", "--permission-mode", "auto")
        self.assertEqual(code, 0, (out, err))
        self.assertEqual(self.record(job_id="c0ffee00")[0], 0)

    def test_first_tick_after_resume_fetches_from_position_before_stop(self):
        """停止していた間の通知は、resume の後の最初の tick で、停止する前の取得の位置から取得する (R18)。"""
        self.serve()
        self.assertEqual(self.tick("2026-11-16T06:10:00Z")[0], 0)
        self.assertEqual(self.clear(at="2026-11-16T06:15:00Z")[0], 0)
        self.resume("2026-11-19T09:00:00Z")
        self.serve([notification(REPO, 1, "2026-11-17T12:00:00Z")],
                   {(REPO, 1): [timeline_event(10, "2026-11-17T11:59:00Z", login="akm")]})
        code, out = self.tick("2026-11-19T09:10:00Z")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["window_start"], "2026-11-16T06:05:00Z")
        self.assertIn("since=2026-11-16T06:05:00Z", [a for a in self.recorded() if "notifications?" in " ".join(a)][-1][2])
        self.assertEqual([m["subscription_id"] for m in out["messages"]], ["aaaaaaaaaaaa"])

    def test_first_tick_after_resume_refetches_viewer(self):
        """resume の後の最初の tick は、取得から 1 日を過ぎていなくても、自分のログイン名と所属するチームを取得し直す (KTD4)。"""
        self.resume("2026-11-16T08:00:00Z")
        self.serve()
        before = len([a for a in self.recorded() if a[:2] == ["api", "user"]])
        self.assertEqual(self.tick("2026-11-16T08:10:00Z")[0], 0)
        self.assertEqual(len([a for a in self.recorded() if a[:2] == ["api", "user"]]), before + 1)
        self.assertEqual(self.read_home("state.json")["viewer"]["fetched_at"], "2026-11-16T08:10:00Z")


if __name__ == "__main__":
    unittest.main()
