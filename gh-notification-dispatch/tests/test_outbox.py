#!/usr/bin/env python3
"""送信待ち・割り当て・集計 (ファイル `gh-notification-dispatch/scripts/gh_notification_dispatch/outbox.py`) のテスト。

ファイルに書かない関数を直接呼ぶ。ack・fail・settle のサブコマンドは CLI で実行する (計画の R11・R13・R15・KTD6)。

  python3 -m unittest discover -s gh-notification-dispatch/tests
"""

import datetime
import unittest

from fakegh_case import FakeGhCase

from gh_notification_dispatch import messages, outbox, store  # noqa: E402

NOW = "2026-11-16T07:00:00Z"
DISPATCHER = "local_00000000-0000-4000-8000-000000000000"


def sub(sid, repo="akm/claude-plugins", kind="review_requested", created_at="2026-11-16T05:00:00Z", failures=0,
        session=None):
    return {"id": sid, "repo": repo, "kind": kind, "session_id": session or f"local_{sid}", "session_name": f"受信 {sid}",
            "permission_mode": "auto", "created_at": created_at, "consecutive_failures": failures,
            "expired_events": 0, "last_expired_at": None}


def event(n, time="2026-11-16T06:30:00Z", repo="akm/claude-plugins"):
    return {"kind": "review_requested", "key": f"review_requested:{n}", "repo": repo, "number": n, "title": f"PR {n}",
            "url": f"https://github.com/{repo}/pull/{n}", "time": time, "requested": "akm"}


def pending(sid, n, enqueued_at=NOW, outputs=0, time=None):
    return {"subscription_id": sid, "event": event(n, time=time or f"2026-11-16T06:{n % 60:02d}:00Z"),
            "enqueued_at": enqueued_at, "outputs": outputs}


class EnqueueTest(unittest.TestCase):

    def test_all_subscriptions_of_repo_and_kind(self):
        box, delivered = outbox.empty_outbox(), outbox.empty_delivered()
        subs = [sub("a"), sub("b"), sub("c", kind="merged"), sub("d", repo="akm/other"), sub("e", repo="AKM/Claude-Plugins")]
        self.assertEqual(outbox.enqueue(box, delivered, subs, [event(1)], NOW), 3)
        self.assertEqual(sorted(p["subscription_id"] for p in box["pending"]), ["a", "b", "e"])
        self.assertEqual(sorted(d["subscription_id"] for d in delivered["events"]), ["a", "b", "e"])

    def test_not_twice(self):
        """届けた出来事の記録か送信待ちにある (出来事, 登録) は、もう一度入れない (R11・KTD6)。"""
        box, delivered = outbox.empty_outbox(), outbox.empty_delivered()
        subs = [sub("a")]
        outbox.enqueue(box, delivered, subs, [event(1)], NOW)
        self.assertEqual(outbox.enqueue(box, delivered, subs, [event(1)], NOW), 0)
        delivered["events"].clear()
        self.assertEqual(outbox.enqueue(box, delivered, subs, [event(1)], NOW), 0, "送信待ちにあれば入れない")
        box["pending"].clear()
        delivered["events"].append({"key": "review_requested:2", "subscription_id": "a", "time": NOW, "recorded_at": NOW})
        self.assertEqual(outbox.enqueue(box, delivered, subs, [event(2)], NOW), 0, "届けた出来事の記録にあれば入れない")

    def test_unreachable_subscription_still_enqueued(self):
        box, delivered = outbox.empty_outbox(), outbox.empty_delivered()
        self.assertEqual(outbox.enqueue(box, delivered, [sub("a", failures=3)], [event(1)], NOW), 1)

    def test_prune_delivered_by_window_start(self):
        """取得の範囲の起点より前の出来事の記録だけを消す (計画のレビューの 12 回目 #2)。"""
        delivered = {"version": 1, "events": [
            {"key": "k1", "subscription_id": "a", "time": "2026-11-16T05:54:59Z", "recorded_at": "2026-09-01T00:00:00Z"},
            {"key": "k2", "subscription_id": "a", "time": "2026-11-16T05:55:00Z", "recorded_at": "2026-09-01T00:00:00Z"},
        ]}
        self.assertEqual(outbox.prune_delivered(delivered, "2026-11-16T05:55:00Z"), 1)
        self.assertEqual([d["key"] for d in delivered["events"]], ["k2"], "送信待ちに入れた時刻が古くても、起点より後なら残すこと")


class ExpireTest(unittest.TestCase):

    def test_expire_after_30_days(self):
        now = store.parse_time(NOW)
        old = store.format_time(now - datetime.timedelta(days=30, seconds=1))
        edge = store.format_time(now - datetime.timedelta(days=30))
        box = {"version": 1, "round": None, "pending": [pending("a", 1, enqueued_at=old), pending("a", 2, enqueued_at=old),
                                                       pending("a", 3, enqueued_at=edge), pending("b", 4, enqueued_at=old)]}
        subs = [sub("a"), sub("b")]
        subs[0]["expired_events"] = 5
        result = outbox.expire(box, subs, now)
        self.assertEqual(sorted((r["subscription_id"], r["count"]) for r in result), [("a", 2), ("b", 1)])
        self.assertEqual([p["event"]["number"] for p in box["pending"]], [3])
        self.assertEqual((subs[0]["expired_events"], subs[0]["last_expired_at"]), (7, NOW), "累計と最後に消した時刻")
        self.assertEqual(outbox.expire(box, subs, now), [], "消した回にだけ返すこと")


class AllocateTest(unittest.TestCase):

    def allocate(self, box, subs, last=None, limit=outbox.MAX_MESSAGES_PER_TICK):
        return outbox.allocate(box, subs, last, NOW, limit=limit)

    def test_one_message_per_subscription(self):
        box = {"version": 1, "round": None, "pending": [pending("a", 1), pending("a", 2), pending("a", 3), pending("b", 1)]}
        out, last = self.allocate(box, [sub("a"), sub("b", created_at="2026-11-16T05:01:00Z")])
        self.assertEqual([(m["subscription_id"], m["count"]) for m in out], [("a", 3), ("b", 1)])
        self.assertEqual(last, {"subscription_id": "b", "created_at": "2026-11-16T05:01:00Z"})
        self.assertEqual(len(box["round"]["messages"]), 2)
        self.assertEqual(messages.parse(out[0]["body"])["fields"]["count"], 3)
        self.assertEqual((out[0]["to"], out[0]["to_session_id"]), ("受信 a", "local_a"))

    def test_split_by_20(self):
        box = {"version": 1, "round": None, "pending": [pending("a", n) for n in range(1, 22)]}
        out, _ = self.allocate(box, [sub("a")])
        self.assertEqual([m["count"] for m in out], [20, 1], "21 件は、同じ回に 20 件と 1 件の 2 通")

    def test_oldest_first(self):
        box = {"version": 1, "round": None,
               "pending": [pending("a", 1, time="2026-11-16T06:50:00Z"), pending("a", 2, time="2026-11-16T06:10:00Z")]}
        out, _ = self.allocate(box, [sub("a")])
        numbers = [line.split()[0] for line in messages.parse(out[0]["body"])["fields"]["event"]]
        self.assertEqual(numbers, ["#2", "#1"])

    def test_backlog_does_not_starve_others(self):
        """1 つの登録に上限を超える送信待ちが溜まっていても、ほかの登録の新しい出来事を同じ回に出力する。"""
        box = {"version": 1, "round": None, "pending": [pending("a", n) for n in range(1, 301)] + [pending("b", 1)]}
        out, _ = self.allocate(box, [sub("a"), sub("b", created_at="2026-11-16T05:01:00Z")])
        self.assertEqual(len(out), 10)
        self.assertEqual([m["subscription_id"] for m in out[:2]], ["a", "b"])
        self.assertEqual([m["subscription_id"] for m in out[2:]], ["a"] * 8, "枠が残る限り、割り当てを始めた登録に戻ること")
        self.assertEqual(sum(1 for p in box["pending"] if p["outputs"] == 0), 300 - 9 * 20, "超えた分は送信待ちに残る")

    def test_rotation_when_more_subscriptions_than_limit(self):
        subs = [sub(f"s{i:02d}", created_at=f"2026-11-16T05:{i:02d}:00Z") for i in range(12)]
        box = {"version": 1, "round": None, "pending": [pending(s["id"], 1) for s in subs]}
        out, last = self.allocate(box, subs)
        self.assertEqual([m["subscription_id"] for m in out], [f"s{i:02d}" for i in range(10)])
        out, last = self.allocate(box, subs, last)
        self.assertEqual([m["subscription_id"] for m in out][:3], ["s10", "s11", "s00"],
                         "次の回は、前の回に最後に割り当てた登録の次から")

    def test_start_after_deleted_subscription(self):
        """last_allocated の登録が削除されていても、登録日時で次の登録から始める (計画のレビューの 6 回目 #3)。"""
        subs = [sub("a", created_at="2026-11-16T05:00:00Z"), sub("c", created_at="2026-11-16T05:02:00Z")]
        box = {"version": 1, "round": None, "pending": [pending("a", 1), pending("c", 1)]}
        out, _ = self.allocate(box, subs, {"subscription_id": "b", "created_at": "2026-11-16T05:01:00Z"})
        self.assertEqual([m["subscription_id"] for m in out], ["c", "a"])

    def test_unreachable_is_not_allocated(self):
        box = {"version": 1, "round": None, "pending": [pending("a", 1), pending("b", 1)]}
        out, _ = self.allocate(box, [sub("a", failures=3), sub("b")])
        self.assertEqual([m["subscription_id"] for m in out], ["b"])

    def test_nothing_to_send(self):
        box = outbox.empty_outbox()
        out, last = self.allocate(box, [sub("a")], {"subscription_id": "a", "created_at": "2026-11-16T05:00:00Z"})
        self.assertEqual((out, box["round"]), ([], None))
        self.assertEqual(last["subscription_id"], "a", "割り当てなかった回は、last_allocated を変えないこと")

    def test_resend_and_new_events_are_not_mixed(self):
        """送り直しの出来事と初めての出来事は、別のメッセージにする。resend のあるメッセージの出来事は、どれも前に送ったもの。"""
        box = {"version": 1, "round": None,
               "pending": [pending("a", 1, outputs=1, time="2026-11-16T06:10:00Z"),
                           pending("a", 2, outputs=2, time="2026-11-16T06:20:00Z"),
                           pending("a", 3, outputs=0, time="2026-11-16T06:05:00Z")]}
        out, _ = self.allocate(box, [sub("a")])
        self.assertEqual([(m["resend"], m["count"]) for m in out], [(2, 2), (0, 1)],
                         "送り直しの出来事を先に、回数は出来事ごとの回数の最大値にすること")
        numbers = [[line.split()[0] for line in messages.parse(m["body"])["fields"]["event"]] for m in out]
        self.assertEqual(numbers, [["#1", "#2"], ["#3"]], "初めての出来事を送り直しのメッセージに入れないこと")
        self.assertNotIn("送り直し", out[1]["body"].splitlines()[0])

    def test_resend_has_count_and_different_body(self):
        box = {"version": 1, "round": None, "pending": [pending("a", 1)]}
        first, _ = self.allocate(box, [sub("a")])
        again, _ = self.allocate(box, [sub("a")])
        self.assertEqual((first[0]["resend"], again[0]["resend"]), (0, 1))
        self.assertNotEqual(first[0]["body"], again[0]["body"], "送り直しは直前と同じ本文にしないこと")


class SettleRoundTest(unittest.TestCase):

    def round_with(self, results):
        return {"version": 1, "pending": [], "round": {"id": "r1", "tick_at": NOW, "messages": [
            {"message_id": f"m{i}", "subscription_id": sid, "event_keys": [], "result": result, "reason": None}
            for i, (sid, result) in enumerate(results)]}}

    def test_counting(self):
        """1 回の tick で同じ登録の 2 通が fail でも 1 回。ack と fail が混ざっても 1 回。記録の無いメッセージだけなら変えない。
        ack と記録の無いメッセージだけなら 0 に戻す (計画のレビューの 9 回目 #3)。メッセージの無かった登録は変えない。"""
        data = {"version": 1, "subscriptions": [sub("a", failures=1), sub("b", failures=1), sub("c", failures=2),
                                                 sub("d", failures=2), sub("e", failures=2)]}
        box = self.round_with([("a", "fail"), ("a", "fail"), ("b", "ack"), ("b", "fail"), ("c", None),
                               ("d", "ack"), ("d", None)])
        outcome = outbox.settle_round(box, data)
        counts = {s["id"]: s["consecutive_failures"] for s in data["subscriptions"]}
        self.assertEqual(counts, {"a": 2, "b": 2, "c": 2, "d": 0, "e": 2})
        self.assertEqual({r["subscription_id"]: r["result"] for r in outcome["results"]},
                         {"a": "failed", "b": "failed", "c": "unrecorded", "d": "delivered"})
        self.assertIsNone(box["round"])
        self.assertEqual(data["last_settled_round"], "r1")

    def test_third_failure_becomes_unreachable(self):
        data = {"version": 1, "subscriptions": [sub("a", failures=2)]}
        outcome = outbox.settle_round(self.round_with([("a", "fail")]), data)
        self.assertEqual([s["subscription_id"] for s in outcome["became_unreachable"]], ["a"])
        self.assertTrue(outbox.is_unreachable(data["subscriptions"][0]))

    def test_deleted_subscription_is_skipped(self):
        """出力した後に削除された登録は数えない (計画のレビューの 7 回目 #3)。"""
        data = {"version": 1, "subscriptions": [sub("a")]}
        outcome = outbox.settle_round(self.round_with([("gone", "fail"), ("a", "ack")]), data)
        self.assertEqual([r["subscription_id"] for r in outcome["results"]], ["a"])

    def test_already_counted_round_is_not_counted_again(self):
        """集計を書いた後、対応を消す前に中断しても、同じ回を 2 回数えない (計画のレビューの 6 回目 #4)。"""
        data = {"version": 1, "subscriptions": [sub("a", failures=1)], "last_settled_round": "r1"}
        box = self.round_with([("a", "fail")])
        outcome = outbox.settle_round(box, data)
        self.assertTrue(outcome["already_counted"])
        self.assertEqual(data["subscriptions"][0]["consecutive_failures"], 1)
        self.assertIsNone(box["round"])

    def test_no_round(self):
        self.assertIsNone(outbox.settle_round(outbox.empty_outbox(), {"version": 1, "subscriptions": []}))


class RecordCommandTest(FakeGhCase):
    """サブコマンド ack・fail・settle。"""

    def setUp(self):
        super().setUp()
        self.at(NOW)
        self.as_session(DISPATCHER)
        self.write_home("state.json", {"version": 1, "dispatcher": {"session_id": DISPATCHER, "name": "配信",
                                                                   "permission_mode": "auto", "recorded_at": NOW}})
        self.write_home("subscriptions.json", {"version": 1, "subscriptions": [sub("a", failures=2), sub("b")]})
        box = {"version": 1, "pending": [pending("a", 1), pending("a", 2), pending("b", 3)], "round": None}
        outbox.allocate(box, [sub("a"), sub("b")], None, NOW)
        self.write_home("outbox.json", box)
        self.ids = {m["subscription_id"]: m["message_id"] for m in box["round"]["messages"]}

    def test_ack_removes_events_and_fail_keeps(self):
        code, out, err = self.cli("ack", self.ids["a"])
        self.assertEqual(code, 0, (out, err))
        self.assertEqual((out["subscription_id"], out["removed_events"]), ("a", 2))
        code, out, _ = self.cli("fail", self.ids["b"], "--reason", "No agent named '受信 b' is reachable.")
        self.assertEqual(code, 0)
        box = self.read_home("outbox.json")
        self.assertEqual([p["subscription_id"] for p in box["pending"]], ["b"], "fail の出来事は送信待ちに残ること")
        self.assertEqual(box["round"]["messages"][1]["reason"], "No agent named '受信 b' is reachable.")

    def test_unknown_or_already_recorded(self):
        before = self.home_files(ignore_lock=True)
        code, out, _ = self.cli("ack", "000000000000")
        self.assertEqual(code, 3)
        self.assertIn("この回", out["errors"][0])
        self.assertEqual(self.home_files(ignore_lock=True), before)
        self.cli("ack", self.ids["a"])
        code, out, _ = self.cli("fail", self.ids["a"], "--reason", "x")
        self.assertEqual(code, 3)
        self.assertIn("既に ack", out["errors"][0])

    def test_settle_then_ack_is_refused(self):
        """settle の後は、その回のメッセージの ID を受け付けない (計画のレビューの 12 回目 #4)。"""
        self.cli("fail", self.ids["a"], "--reason", "x")
        code, out, _ = self.cli("settle")
        self.assertEqual(code, 0)
        self.assertEqual({r["subscription_id"]: r["result"] for r in out["settled"]["results"]},
                         {"a": "failed", "b": "unrecorded"})
        self.assertEqual([s["subscription_id"] for s in out["settled"]["became_unreachable"]], ["a"])
        self.assertEqual(self.read_home("subscriptions.json")["subscriptions"][0]["consecutive_failures"], 3)
        before = self.home_files()
        code, out, _ = self.cli("ack", self.ids["b"])
        self.assertEqual(code, 3)
        self.assertEqual(self.home_files(), before, "送信待ちも続けて届かなかった回数も変えないこと")
        code, out, _ = self.cli("settle")
        self.assertEqual((code, out["settled"]), (0, None), "集計する対応が無ければ何もしない")

    def test_other_session(self):
        self.as_session("local_other")
        self.assertEqual(self.cli("ack", self.ids["a"])[0], 3)
        self.assertEqual(self.cli("settle")[0], 3)


if __name__ == "__main__":
    unittest.main()
