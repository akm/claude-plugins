#!/usr/bin/env python3
"""1 回の取得 (サブコマンド tick。ファイル `gh-notification-dispatch/scripts/gh_notification_dispatch/poll.py`) のテスト。

CLI の入口をサブプロセスで実行し、偽の `gh` が通知・timeline・所属するチームを返す (計画の U3 のテストの項目)。

  python3 -m unittest discover -s gh-notification-dispatch/tests
"""

import os
import unittest

from fakegh_case import FakeGhCase, fixture, http, link_next, notification, pull, review, timeline_event

from gh_notification_dispatch import messages  # noqa: E402

DISPATCHER = "local_00000000-0000-4000-8000-000000000000"
RECEIVER_A = "local_00000000-0000-4000-8000-00000000000a"
RECEIVER_B = "local_00000000-0000-4000-8000-00000000000b"
REPO = "akm/claude-plugins"
T0 = "2026-11-16T06:00:00Z"  # 最初の tick (開始した時刻)
TEAMS = [{"id": 101, "slug": "reviewers", "name": "reviewers", "organization": {"login": "akm-org", "id": 9}}]


def timeline_path(repo, number):
    return f"repos/{repo}/issues/{number}/timeline?per_page=100"


class TickCase(FakeGhCase):

    def setUp(self):
        super().setUp()
        self.at(T0)
        self.as_session(DISPATCHER)
        self.write_home("state.json", {"version": 1, "dispatcher": {"session_id": DISPATCHER, "name": "配信",
                                                                   "permission_mode": "auto", "recorded_at": T0}})
        self.subs = []

    def add_sub(self, sid, repo=REPO, kind="review_requested", session=RECEIVER_A, created_at="2026-11-16T05:00:00Z"):
        self.subs.append({"id": sid, "repo": repo, "kind": kind, "session_id": session, "session_name": f"受信 {sid}",
                          "permission_mode": "auto", "created_at": created_at})
        self.write_home("subscriptions.json", {"version": 1, "subscriptions": self.subs})

    def serve(self, notifications=(), timelines=None, etag='W/"e1"', not_modified_for=None, extra=(), page2=None,
              teams=TEAMS, pulls=(), reviews=None):
        """偽の gh の応答を決める。pulls は PR の応答 (関数 pull の値)、reviews は {(リポジトリ, 番号): レビューの配列}。"""
        entries = list(extra)
        for p in pulls:
            entries.append({"prefix": ["api", "-i", f"repos/{p['base']['repo']['full_name']}/pulls/{p['number']}"],
                            "stdout": http(200, p)})
        for (repo, number), items in (reviews or {}).items():
            entries.append({"prefix": ["api", "-i", f"repos/{repo}/pulls/{number}/reviews?per_page=100"],
                            "stdout": http(200, items)})
        entries.append({"prefix": ["api", "user"], "stdout": {"login": "akm", "id": 1}})
        entries.append({"prefix": ["api", "-i", "user/teams?per_page=100"], "stdout": http(200, teams)})
        if not_modified_for:
            entries.append({"prefix": ["api", "-i"], "substring": ["notifications?", f"If-None-Match: {not_modified_for}"],
                            "stdout": {"fixture": "notifications-not-modified"}, "stderr": "gh: HTTP 304\n", "exit": 1})
        if page2 is not None:
            entries.append({"prefix": ["api", "-i", "notifications?page=2"], "stdout": http(200, page2)})
        headers = {"Etag": etag}
        if page2 is not None:
            headers["Link"] = link_next("notifications?page=2")
        entries.append({"prefix": ["api", "-i"], "substring": "notifications?all=true",
                        "stdout": http(200, list(notifications), headers)})
        for (repo, number), items in (timelines or {}).items():
            entries.append({"prefix": ["api", "-i", timeline_path(repo, number)], "stdout": http(200, items)})
        self.responses(entries)

    def tick(self, at=None):
        if at:
            self.at(at)
        code, out, err = self.cli("tick")
        self.assertIsNotNone(out, err)
        return code, out

    def calls(self, needle):
        return [a for a in self.recorded() if any(needle in x for x in a)]

    def ack_all(self, out):
        for m in out["messages"]:
            self.assertEqual(self.cli("ack", m["message_id"])[0], 0)
        self.assertEqual(self.cli("settle")[0], 0)

    def state(self):
        return self.read_home("state.json")

    def failures(self, sid):
        return next(s for s in self.read_home("subscriptions.json")["subscriptions"] if s["id"] == sid).get(
            "consecutive_failures", 0)


class FirstTickTest(TickCase):

    def test_nothing_before_start(self):
        """最初の tick では、開始した時刻より前の通知とレビューの依頼を届けない (R8)。"""
        self.add_sub("aaaaaaaaaaaa")
        self.serve([notification(REPO, 1, "2026-11-16T05:59:00Z")],
                   {(REPO, 1): [timeline_event(10, "2026-11-16T05:58:00Z", login="akm")]})
        code, out = self.tick()
        self.assertEqual(code, 0, out)
        self.assertEqual((out["found"], out["messages"]), (0, []))
        state = self.state()
        self.assertEqual((state["started_at"], state["position"], state["etag"]), (T0, T0, 'W/"e1"'))
        self.assertEqual(out["window_start"], T0)
        self.assertIn(f"since={T0}", self.calls("notifications?")[0][2])
        self.assertIn("all=true", self.calls("notifications?")[0][2], "既読の通知も読むこと (KTD5)")
        self.assertEqual(state["viewer"]["teams"], [{"id": 101, "slug": "reviewers", "organization": "akm-org"}])


class StartedTickCase(TickCase):

    def setUp(self):
        super().setUp()
        self.add_sub("aaaaaaaaaaaa")
        self.serve()
        self.assertEqual(self.tick()[0], 0)  # 最初の tick (開始)
        self.responses([])


class DeliveryTest(StartedTickCase):

    def test_delivers_review_request(self):
        self.serve([notification(REPO, 1, "2026-11-16T06:05:00Z", title="✨ feat: 通知")],
                   {(REPO, 1): [timeline_event(10, "2026-11-16T06:04:00Z", login="akm")]}, etag='W/"e2"')
        code, out = self.tick("2026-11-16T06:10:00Z")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["found"], 1)
        self.assertEqual(len(out["messages"]), 1)
        message = out["messages"][0]
        self.assertEqual((message["to"], message["to_session_id"], message["count"], message["resend"]),
                         ("受信 aaaaaaaaaaaa", RECEIVER_A, 1, 0))
        parsed = messages.parse(message["body"])
        self.assertEqual((parsed["errors"], parsed["type"]), ([], "notify"))
        self.assertIn("✨ feat: 通知", parsed["fields"]["event"][0])
        state = self.state()
        self.assertEqual((state["position"], state["etag"]), ("2026-11-16T06:10:00Z", 'W/"e2"'))
        self.assertIn("メッセージ 1 通", out["summary"])

    def test_not_modified_skips_timeline(self):
        """304 のときは timeline を読まず、取得の位置を進め、前回の ETag は変えない (KTD5)。"""
        self.serve([notification(REPO, 1, "2026-11-16T06:05:00Z")],
                   {(REPO, 1): [timeline_event(10, "2026-11-16T06:04:00Z", login="akm")]}, not_modified_for='W/"e1"')
        code, out = self.tick("2026-11-16T06:10:00Z")
        self.assertEqual(code, 0, out)
        self.assertTrue(out["not_modified"])
        self.assertEqual(self.calls("timeline"), [])
        self.assertEqual((self.state()["position"], self.state()["etag"]), ("2026-11-16T06:10:00Z", 'W/"e1"'))
        self.assertIn("304", out["summary"])

    def test_second_page_of_notifications(self):
        self.serve([notification("akm/other", 2, "2026-11-16T06:05:00Z")],
                   {(REPO, 1): [timeline_event(10, "2026-11-16T06:04:00Z", login="akm")]},
                   page2=[notification(REPO, 1, "2026-11-16T06:05:00Z")])
        code, out = self.tick("2026-11-16T06:10:00Z")
        self.assertEqual((code, out["found"]), (0, 1))

    def test_read_notification_is_delivered(self):
        """利用者が次の tick より前に既読にした通知の依頼も届ける。偽の gh は、all=true の無い取得には既読の通知を返さない。"""
        read = notification(REPO, 1, "2026-11-16T06:05:00Z", unread=False)
        self.serve([read], {(REPO, 1): [timeline_event(10, "2026-11-16T06:04:00Z", login="akm")]},
                   extra=[{"prefix": ["api", "-i"], "substring": "notifications?per_page", "stdout": http(200, [])}])
        code, out = self.tick("2026-11-16T06:10:00Z")
        self.assertEqual((code, out["found"]), (0, 1))

    def test_unregistered_repo_and_kind_are_not_read(self):
        self.write_home("subscriptions.json", {"version": 1, "subscriptions": [
            {**self.subs[0], "repo": "akm/merged-only", "kind": "merged"}]})
        self.serve([notification(REPO, 1, "2026-11-16T06:05:00Z"), notification("akm/merged-only", 2, "2026-11-16T06:05:00Z")],
                   pulls=[pull("akm/merged-only", 2)])
        code, out = self.tick("2026-11-16T06:10:00Z")
        self.assertEqual((code, out["found"]), (0, 0))
        self.assertEqual(self.calls("timeline"), [], "review_requested の登録が無いリポジトリでは timeline を読まないこと")
        self.assertEqual(self.calls(f"repos/{REPO}/pulls/1"), [], "merged の登録が無いリポジトリでは PR を読まないこと")

    def test_two_sessions_two_repos_and_split(self):
        """同じ (リポジトリ, 種類) の 2 つのセッションには 2 通。21 件は 20 件と 1 件。2 つのリポジトリはリポジトリごとに 1 通。"""
        self.add_sub("bbbbbbbbbbbb", session=RECEIVER_B, created_at="2026-11-16T05:01:00Z")
        self.add_sub("cccccccccccc", repo="akm/other", created_at="2026-11-16T05:02:00Z")
        many = [timeline_event(100 + i, f"2026-11-16T06:01:{i:02d}Z", login="akm") for i in range(21)]
        self.serve([notification(REPO, 1, "2026-11-16T06:09:59Z"), notification("akm/other", 2, "2026-11-16T06:09:59Z")],
                   {(REPO, 1): many, ("akm/other", 2): [timeline_event(200, "2026-11-16T06:05:00Z", login="akm")]})
        code, out = self.tick("2026-11-16T06:10:00Z")
        self.assertEqual(code, 0, out)
        counts = sorted((m["subscription_id"], m["count"]) for m in out["messages"])
        self.assertEqual(counts, [("aaaaaaaaaaaa", 1), ("aaaaaaaaaaaa", 20), ("bbbbbbbbbbbb", 1), ("bbbbbbbbbbbb", 20),
                                  ("cccccccccccc", 1)])


class OverlapAndTimingTest(StartedTickCase):

    def test_overlap_is_deduplicated(self):
        """取得の位置の 5 分前から取るので重なった通知も、届けた出来事の記録で除く (R11)。"""
        served = ([notification(REPO, 1, "2026-11-16T06:09:00Z")],
                  {(REPO, 1): [timeline_event(10, "2026-11-16T06:08:00Z", login="akm")]})
        self.serve(*served)
        _, out = self.tick("2026-11-16T06:10:00Z")
        self.ack_all(out)
        self.serve(*served, etag='W/"e3"')
        code, out = self.tick("2026-11-16T06:11:00Z")
        self.assertEqual(out["window_start"], "2026-11-16T06:05:00Z")
        self.assertEqual((code, out["found"], out["messages"]), (0, 0, []))

    def test_late_appearing_request_is_delivered(self):
        """取得の位置の直前に付いた依頼が、その回には現れず次の回に初めて現れても届ける。"""
        self.serve([])
        self.tick("2026-11-16T06:10:00Z")
        self.serve([notification(REPO, 1, "2026-11-16T06:09:30Z")],
                   {(REPO, 1): [timeline_event(10, "2026-11-16T06:09:00Z", login="akm")]}, etag='W/"e4"')
        code, out = self.tick("2026-11-16T06:20:00Z")
        self.assertEqual(out["window_start"], "2026-11-16T06:05:00Z")
        self.assertEqual((code, out["found"]), (0, 1))

    def test_request_before_start_within_margin_is_not_delivered(self):
        """最初の開始の時刻より前に付いた依頼は、起点の 5 分の余裕の中にあっても届けない (R8)。"""
        self.serve([notification(REPO, 1, "2026-11-16T06:01:00Z")],
                   {(REPO, 1): [timeline_event(10, "2026-11-16T05:58:00Z", login="akm")]})
        code, out = self.tick("2026-11-16T06:02:00Z")
        self.assertEqual(out["window_start"], T0, "起点は開始した時刻より前にしない")
        self.assertEqual((code, out["found"]), (0, 0))

    def test_teams_are_refreshed_after_one_day(self):
        """所属するチームを読んでから 1 日を過ぎた tick は取得し直し、新しく加わったチームへの依頼も届ける (KTD4)。"""
        team_request = {(REPO, 1): [timeline_event(10, "2026-11-17T06:04:00Z", team_id=202)]}
        new_teams = TEAMS + [{"id": 202, "slug": "new", "organization": {"login": "akm-org"}}]
        self.serve([notification(REPO, 1, "2026-11-17T06:05:00Z")], team_request, teams=new_teams)
        at_start = len(self.calls("user/teams"))
        code, out = self.tick("2026-11-17T05:59:59Z")
        self.assertEqual(len(self.calls("user/teams")), at_start, "1 日を過ぎていなければ取得し直さないこと")
        self.assertEqual(out["found"], 0)
        code, out = self.tick("2026-11-17T06:10:00Z")
        self.assertEqual(len(self.calls("user/teams")), at_start + 1)
        self.assertEqual((code, out["found"]), (0, 1))
        self.assertIn("akm-org/new", messages.parse(out["messages"][0]["body"])["fields"]["event"][0])

    def test_resume_after_long_stop_does_not_duplicate(self):
        """30 日より長く配信を停止した後の再開でも、重なった範囲の出来事を 2 回届けない (計画のレビューの 12 回目 #2)。"""
        served = ([notification(REPO, 1, "2026-11-16T06:09:00Z")],
                  {(REPO, 1): [timeline_event(10, "2026-11-16T06:08:00Z", login="akm")]})
        self.serve(*served)
        _, out = self.tick("2026-11-16T06:10:00Z")
        self.ack_all(out)
        state = self.state()
        self.serve(*served, etag='W/"e9"')
        self.at("2026-12-31T00:00:00Z")
        # 停止していた間は tick が実行されないので、取得の位置は 2026-11-16T06:10:00Z のまま
        self.assertEqual(state["position"], "2026-11-16T06:10:00Z")
        code, out = self.tick()
        self.assertEqual((code, out["found"]), (0, 0))

    def test_dispatcher_set_makes_next_tick_refresh_viewer(self):
        """dispatcher set (スキル dispatch の start) の後の最初の tick は、1 日を過ぎていなくても、ログイン名と所属するチームを取得し直す (KTD4)。"""
        self.serve()
        at_start = len(self.calls("user/teams"))
        self.assertEqual(self.cli("dispatcher", "set", "--name", "配信", "--permission-mode", "auto")[0], 0)
        self.assertNotIn("viewer", self.state())
        code, out = self.tick("2026-11-16T06:10:00Z")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.calls("user/teams")), at_start + 1)
        self.assertEqual(self.state()["viewer"]["fetched_at"], "2026-11-16T06:10:00Z")


class MergedTest(StartedTickCase):
    """種類 merged (計画の R10・R11・KTD4)。登録 a は review_requested、登録 m は同じリポジトリの merged。"""

    T1 = "2026-11-16T06:10:00Z"
    MERGED_AT = "2026-11-16T06:15:00Z"

    def setUp(self):
        super().setUp()
        self.add_sub("mmmmmmmmmmmm", kind="merged", created_at="2026-11-16T05:01:00Z")

    def request(self, at=None, event_id=10, number=1, pulls=None):
        """PR への自分へのレビューの依頼を届ける (追跡に足す) 回。"""
        at = at or self.T1
        self.serve([notification(REPO, number, at)], {(REPO, number): [timeline_event(event_id, at, login="akm")]},
                   etag=f'W/"e{event_id}"', pulls=[pull(REPO, number)] if pulls is None else pulls)
        code, out = self.tick(at)
        self.assertEqual(code, 0, out)
        self.ack_all(out)
        return out

    def tracked(self):
        return [(p["repo"], p["number"], p["enqueued_at"]) for p in (self.read_home_or_none("tracked.json") or {"prs": []})["prs"]]

    def read_home_or_none(self, name):
        return self.read_home(name) if os.path.exists(os.path.join(self.home, name)) else None

    def merged_messages(self, out):
        return [m for m in out["messages"] if m["kind"] == "merged"]

    def test_tracked_pr_merged_without_notification(self):
        """依頼を届けた PR が、通知の無いまま (自分でマージした場合など) マージされても届け、追跡をやめる。304 の回も読む。"""
        self.request()
        self.assertEqual(self.tracked(), [(REPO, 1, self.T1)])
        self.serve(not_modified_for='W/"e10"', etag='W/"e10"', pulls=[pull(REPO, 1, merged_at=self.MERGED_AT, title="✨ feat")])
        code, out = self.tick("2026-11-16T06:20:00Z")
        self.assertTrue(out["not_modified"])
        [message] = self.merged_messages(out)
        self.assertEqual(message["subscription_id"], "mmmmmmmmmmmm")
        self.assertEqual(messages.parse(message["body"])["fields"]["event"],
                         [f"#1 {self.MERGED_AT} https://github.com/{REPO}/pull/1 ✨ feat"])
        self.assertEqual(self.tracked(), [])

    def test_closed_pr_stops_tracking(self):
        """依頼を届けた PR が、マージされずに閉じたら、届けずに追跡をやめる。その後は状態を読まない。"""
        self.request()
        self.serve(pulls=[pull(REPO, 1, state="closed")])
        code, out = self.tick("2026-11-16T06:20:00Z")
        self.assertEqual((code, self.merged_messages(out), self.tracked()), (0, [], []))
        before = len(self.calls(f"repos/{REPO}/pulls/1"))
        self.serve()
        self.tick("2026-11-16T06:30:00Z")
        self.assertEqual(len(self.calls(f"repos/{REPO}/pulls/1")), before)

    def test_same_merge_from_tracking_and_notification_once(self):
        """同じ PR のマージを、追跡と通知の両方で見つけても、1 回だけ届ける。次の回に通知が残っていても届けない (R11)。"""
        self.request()
        merged = pull(REPO, 1, merged_at=self.MERGED_AT, requested=["akm"])
        self.serve([notification(REPO, 1, "2026-11-16T06:16:00Z")], {(REPO, 1): []}, etag='W/"e11"', pulls=[merged])
        code, out = self.tick("2026-11-16T06:20:00Z")
        self.assertEqual((code, out["found"], len(self.merged_messages(out))), (0, 1, 1))
        self.ack_all(out)
        self.serve([notification(REPO, 1, "2026-11-16T06:16:00Z")], {(REPO, 1): []}, etag='W/"e12"', pulls=[merged])
        code, out = self.tick("2026-11-16T06:21:00Z")
        self.assertEqual((code, out["found"], out["messages"]), (0, 0, []))

    def test_notification_pr_with_my_review_is_delivered(self):
        """依頼を届けていない PR の通知では、自分のレビューがあるときだけ届ける (R10 の (b))。"""
        self.serve([notification(REPO, 5, "2026-11-16T06:16:00Z", reason="subscribed"),
                    notification(REPO, 6, "2026-11-16T06:16:00Z", reason="subscribed")],
                   {(REPO, 5): [], (REPO, 6): []},
                   pulls=[pull(REPO, 5, merged_at=self.MERGED_AT), pull(REPO, 6, merged_at=self.MERGED_AT)],
                   reviews={(REPO, 5): [review("akm")], (REPO, 6): [review("someone")]})
        code, out = self.tick("2026-11-16T06:20:00Z")
        self.assertEqual([m["count"] for m in self.merged_messages(out)], [1])
        self.assertIn("#5 ", messages.parse(self.merged_messages(out)[0]["body"])["fields"]["event"][0])
        self.assertEqual(self.tracked(), [], "依頼を届けていない PR は追跡しない")

    def test_repo_without_merged_subscription_drops_tracking(self):
        """merged の登録が無くなったリポジトリでは PR の状態を読まず、追跡を消す。後で merged を登録し直しても、その間の
        マージを届けない。"""
        self.request()
        merged_sub = self.subs.pop()
        self.write_home("subscriptions.json", {"version": 1, "subscriptions": self.subs})
        before = len(self.calls(f"repos/{REPO}/pulls/1"))
        self.serve()
        self.tick("2026-11-16T06:20:00Z")
        self.assertEqual((self.tracked(), len(self.calls(f"repos/{REPO}/pulls/1"))), ([], before))
        self.subs.append(merged_sub)
        self.write_home("subscriptions.json", {"version": 1, "subscriptions": self.subs})
        self.serve(pulls=[pull(REPO, 1, merged_at="2026-11-16T06:25:00Z")])
        code, out = self.tick("2026-11-16T06:30:00Z")
        self.assertEqual((code, self.merged_messages(out)), (0, []))

    def test_tracking_ends_thirty_days_after_last_request(self):
        """最後に依頼を送信待ちに入れてから 30 日を過ぎた PR は、状態を読まずに追跡をやめる。依頼のやり直しを送信待ちに
        入れると、30 日の起点がその時刻になる (R10)。"""
        self.request()
        later = "2026-12-06T06:10:00Z"  # 20 日後に依頼のやり直し
        self.request(at=later, event_id=11)
        self.assertEqual(self.tracked(), [(REPO, 1, later)])
        self.serve(pulls=[pull(REPO, 1)])
        self.tick("2026-12-17T06:10:00Z")  # 最初の依頼から 31 日後、やり直しから 11 日後
        self.assertEqual(self.tracked(), [(REPO, 1, later)])
        before = len(self.calls(f"repos/{REPO}/pulls/1"))
        self.serve(pulls=[pull(REPO, 1, merged_at="2027-01-06T06:00:00Z")])
        code, out = self.tick("2027-01-06T06:11:00Z")  # やり直しから 30 日と 1 分後
        self.assertEqual((code, self.merged_messages(out), self.tracked()), (0, [], []))
        self.assertEqual(len(self.calls(f"repos/{REPO}/pulls/1")), before, "状態を読まないこと")

    def test_start_stays_at_enqueue_time_while_unacked(self):
        """届かない登録で ack が遅れても、追跡する期間の起点は送信待ちに入れた時刻のままである (R10)。"""
        self.serve([notification(REPO, 1, self.T1)], {(REPO, 1): [timeline_event(10, self.T1, login="akm")]}, pulls=[pull(REPO, 1)])
        code, out = self.tick(self.T1)
        for i, at in enumerate(["2026-11-16T06:20:00Z", "2026-11-16T06:30:00Z", "2026-11-17T06:30:00Z"]):
            for m in out["messages"]:
                self.assertEqual(self.cli("fail", m["message_id"], "--reason", "届かない")[0], 0)
            self.assertEqual(self.cli("settle")[0], 0)
            self.serve(pulls=[pull(REPO, 1)])
            code, out = self.tick(at)
            self.assertEqual(code, 0, out)
        self.assertEqual(self.tracked(), [(REPO, 1, self.T1)])


class ResultsTest(StartedTickCase):

    def deliver_one(self, at="2026-11-16T06:10:00Z", event_id=10, number=1):
        self.serve([notification(REPO, number, at)], {(REPO, number): [timeline_event(event_id, at, login="akm")]},
                   etag=f'W/"e{event_id}"')
        code, out = self.tick(at)
        self.assertEqual(code, 0, out)
        return out

    def test_unacked_message_is_resent_with_count(self):
        out = self.deliver_one()
        self.serve(etag='W/"x"')
        code, again = self.tick("2026-11-16T06:20:00Z")
        self.assertEqual(again["previous_round"]["results"][0]["result"], "unrecorded",
                         "settle が呼ばれないまま次の tick が始まったら、始めに集計すること")
        self.assertEqual(len(again["messages"]), 1)
        self.assertEqual(again["messages"][0]["resend"], 1)
        self.assertIn("resend: 1", again["messages"][0]["body"])
        self.assertNotEqual(out["messages"][0]["body"], again["messages"][0]["body"])
        self.assertEqual(self.failures("aaaaaaaaaaaa"), 0, "記録の無いメッセージだけの回は数えないこと")

    def test_fail_then_same_event_in_window_makes_one_resend(self):
        out = self.deliver_one()
        self.cli("fail", out["messages"][0]["message_id"], "--reason", "届かない")
        self.cli("settle")
        self.serve([notification(REPO, 1, "2026-11-16T06:10:00Z")], {(REPO, 1): [timeline_event(10, "2026-11-16T06:10:00Z", login="akm")]},
                   etag='W/"y"')
        code, again = self.tick("2026-11-16T06:12:00Z")
        self.assertEqual((code, again["found"], len(again["messages"])), (0, 0, 1), "新しい送信待ちを作らず、送り直しの 1 通だけ")
        self.assertEqual(self.failures("aaaaaaaaaaaa"), 1)

    def test_old_round_id_after_auto_settle_is_refused(self):
        out = self.deliver_one()
        self.serve(etag='W/"z"')
        self.tick("2026-11-16T06:20:00Z")
        code, result = self.cli("ack", out["messages"][0]["message_id"])[:2]
        self.assertEqual(code, 3, "前の回のメッセージの ID は受け付けないこと")

    def test_resubscribe_before_next_tick_keeps_zero(self):
        """fail のあった回の後、次の tick より前に申し込み直した登録は、次の tick の後も回数が 0 のまま。"""
        out = self.deliver_one()
        self.cli("fail", out["messages"][0]["message_id"], "--reason", "届かない")
        self.responses([{"prefix": ["api", "repos/akm/claude-plugins"], "stdout": {"fixture": "repo-claude-plugins"}}])
        text = messages.subscribe(REPO, ["review_requested"], RECEIVER_A, "受信 a", "auto")
        path = os.path.join(self.root, "m.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        code, result, err = self.cli("subscriptions", "add", "--message-file", path, "--sender", RECEIVER_A)
        self.assertEqual(code, 0, (result, err))
        self.serve(etag='W/"w"')
        code, again = self.tick("2026-11-16T06:20:00Z")
        self.assertEqual(again["previous_round"]["results"], [], "申し込み直した登録の対応は消してあること")
        self.assertEqual(self.failures("aaaaaaaaaaaa"), 0)

    def test_three_failures_make_unreachable_and_resubscribe_recovers(self):
        """fail のあった tick が 3 回続いた登録は届かない登録になり、送信待ちを出力しないが、新しい出来事は入れ続ける。
        申し込み直すと回数を 0 に戻し、溜まった出来事も出力する。登録を削除すると送信待ちも消える (R15)。"""
        out = self.deliver_one()
        for i in range(3):
            self.cli("fail", out["messages"][0]["message_id"], "--reason", "届かない")
            code, settled, _ = self.cli("settle")
            self.serve(etag=f'W/"f{i}"')
            if i < 2:
                code, out = self.tick(f"2026-11-16T06:2{i}:00Z")
        self.assertEqual([s["subscription_id"] for s in settled["settled"]["became_unreachable"]], ["aaaaaaaaaaaa"])
        _, listed, _ = self.cli("subscriptions", "list", "--viewer", DISPATCHER)
        self.assertIn("(届かない登録)", listed["table"])
        self.assertTrue(listed["subscriptions"][0]["unreachable"])
        out = self.deliver_one(at="2026-11-16T06:30:00Z", event_id=11, number=2)
        self.assertEqual((out["found"], out["messages"]), (1, []), "届かない登録にも送信待ちを入れ、出力はしないこと")
        self.assertEqual(len(self.read_home("outbox.json")["pending"]), 2)
        self.responses([{"prefix": ["api", "repos/akm/claude-plugins"], "stdout": {"fixture": "repo-claude-plugins"}}])
        path = os.path.join(self.root, "m.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(messages.subscribe(REPO, ["review_requested"], RECEIVER_A, "受信 a", "auto"))
        self.assertEqual(self.cli("subscriptions", "add", "--message-file", path, "--sender", RECEIVER_A)[0], 0)
        self.serve(etag='W/"g"')
        code, out = self.tick("2026-11-16T06:40:00Z")
        self.assertEqual([(m["count"], m["resend"] > 0) for m in out["messages"]], [(1, True), (1, False)],
                         "溜まった出来事を、送り直しの出来事と初めての出来事に分けて出力すること")
        self.cli("subscriptions", "list", "--viewer", DISPATCHER)
        self.cli("subscriptions", "remove", "--viewer", DISPATCHER, "1")
        box = self.read_home("outbox.json")
        self.assertEqual((box["pending"], box["round"]["messages"]), ([], []), "登録を削除すると、送信待ちと対応も消えること")

    def test_expired_events_are_reported_once(self):
        out = self.deliver_one()
        self.serve(etag='W/"h"')
        code, out = self.tick("2026-12-16T06:10:01Z")
        self.assertEqual([(e["subscription_id"], e["count"]) for e in out["expired"]], [("aaaaaaaaaaaa", 1)])
        self.assertEqual(out["messages"], [])
        sub = self.read_home("subscriptions.json")["subscriptions"][0]
        self.assertEqual((sub["expired_events"], sub["last_expired_at"]), (1, "2026-12-16T06:10:01Z"))
        code, out = self.tick("2026-12-16T06:20:00Z")
        self.assertEqual(out["expired"], [], "消した回にだけ示すこと")


class FailureTest(StartedTickCase):

    def test_timeline_failure_keeps_position_and_etag(self):
        """gh の失敗では取得の位置も前回の ETag も変えない。通知の一覧の取得に成功し、その後の timeline の取得に
        失敗した回の次の回は、304 にならずに同じ範囲を判定し直す (KTD5)。読めない PR を判定から除く規則は置かない (KTD11)。"""
        before = self.state()
        self.serve([notification(REPO, 1, "2026-11-16T06:05:00Z")], etag='W/"e2"', not_modified_for='W/"e2"', extra=[
            {"prefix": ["api", "-i", timeline_path(REPO, 1)], "stdout": http(404, {"message": "Not Found"}),
             "stderr": fixture("repo-not-found", "stderr"), "exit": 1}])
        code, out = self.tick("2026-11-16T06:10:00Z")
        self.assertEqual(code, 4)
        self.assertEqual(out["failed_call"], {"api": "timeline", "repo": REPO, "number": 1})
        self.assertEqual(out["gh_error"]["failure"], "not_found")
        self.assertIsNone(out["position"])
        after = self.state()
        self.assertEqual((after["position"], after["etag"]), (before["position"], before["etag"]))
        self.serve([notification(REPO, 1, "2026-11-16T06:05:00Z")],
                   {(REPO, 1): [timeline_event(10, "2026-11-16T06:04:00Z", login="akm")]},
                   etag='W/"e2"', not_modified_for='W/"e2"')
        code, out = self.tick("2026-11-16T06:20:00Z")
        self.assertEqual(out["window_start"], T0, "取得の位置を変えていないので、同じ範囲を判定し直すこと")
        self.assertFalse(out["not_modified"], "前回の ETag を更新していないので、304 にならないこと")
        self.assertEqual((code, out["found"]), (0, 1))

    def test_notifications_failure(self):
        os.environ["FAKE_GH_MODE"] = "auth_expired"
        self.write_home("state.json", {**self.state(), "viewer": {**self.state()["viewer"], "fetched_at": "2026-11-16T06:00:00Z"}})
        code, out = self.tick("2026-11-16T06:10:00Z")
        self.assertEqual(code, 4)
        self.assertEqual(out["failed_call"]["api"], "notifications")
        self.assertEqual(out["gh_error"]["failure"], "auth")

    def test_not_dispatcher(self):
        self.as_session(RECEIVER_A)
        before = self.home_files()
        code, out = self.tick("2026-11-16T06:10:00Z")
        self.assertEqual(code, 3)
        self.assertEqual(self.home_files(), before)


class LogTest(StartedTickCase):

    def test_log_line_per_tick(self):
        self.serve(etag='W/"l"')
        self.tick("2026-11-16T06:10:00Z")
        with open(os.path.join(self.home, "log.jsonl"), encoding="utf-8") as f:
            lines = [line for line in f if line.strip()]
        self.assertEqual(len(lines), 2, "最初の tick と、この tick の 2 行")


if __name__ == "__main__":
    unittest.main()
