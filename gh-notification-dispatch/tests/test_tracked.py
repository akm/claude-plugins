#!/usr/bin/env python3
"""追跡する PR (ファイル `gh-notification-dispatch/scripts/gh_notification_dispatch/tracked.py`) のテスト。

計画 docs/plans/2026-11-14-1428-feat-gh-notification-dispatch-plan.md の R10・KTD4 の、追跡に足す・起点を変える・
外すことを確認する。記録のファイルには書かない関数なので、偽の `gh` は使わない。

  python3 -m unittest discover -s gh-notification-dispatch/tests
"""

import datetime
import unittest

import fakegh_case  # noqa: F401  (scripts を import のパスに足す)

from gh_notification_dispatch import store, tracked  # noqa: E402

NOW = "2026-11-16T07:00:00Z"
REPO = "akm/claude-plugins"


def sub(kind, repo=REPO):
    return {"id": f"{kind[:4]}00000000"[:12], "repo": repo, "kind": kind}


def request(number, repo=REPO, kind="review_requested"):
    return {"kind": kind, "key": f"{kind}:{number}", "repo": repo, "number": number}


def ago(days):
    return store.format_time(store.parse_time(NOW) - datetime.timedelta(days=days))


class TrackTest(unittest.TestCase):

    def test_request_on_repo_with_merged_subscription_is_tracked(self):
        box = tracked.empty()
        added = tracked.track(box, [request(301)], [sub("review_requested"), sub("merged")], NOW)
        self.assertEqual(added, 1)
        self.assertEqual(box["prs"], [{"repo": REPO, "number": 301, "enqueued_at": NOW}])

    def test_repo_without_merged_subscription_is_not_tracked(self):
        """merged の登録が無いリポジトリの PR は、状態を読んでも届ける先が無いので足さない。"""
        box = tracked.empty()
        self.assertEqual(tracked.track(box, [request(301)], [sub("review_requested")], NOW), 0)
        self.assertEqual(box["prs"], [])

    def test_only_review_requests_are_tracked(self):
        box = tracked.empty()
        self.assertEqual(tracked.track(box, [request(301, kind="merged")], [sub("merged")], NOW), 0)
        self.assertEqual(box["prs"], [])

    def test_re_request_moves_start_without_duplicate(self):
        """追跡している PR への依頼のやり直しを送信待ちに入れると、追跡する期間の起点をその時刻にする (R10)。"""
        box = {"version": 1, "prs": [{"repo": REPO, "number": 301, "enqueued_at": ago(20)}]}
        added = tracked.track(box, [request(301, repo="AKM/Claude-Plugins")], [sub("merged")], NOW)
        self.assertEqual(added, 0)
        self.assertEqual(box["prs"], [{"repo": REPO, "number": 301, "enqueued_at": NOW}])


class PruneTest(unittest.TestCase):

    def test_repo_without_merged_subscription_is_removed(self):
        box = {"version": 1, "prs": [{"repo": REPO, "number": 1, "enqueued_at": ago(1)},
                                     {"repo": "akm/other", "number": 2, "enqueued_at": ago(1)}]}
        removed = tracked.prune(box, [sub("merged", repo="AKM/Claude-Plugins"), sub("review_requested", repo="akm/other")],
                                store.parse_time(NOW))
        self.assertEqual([p["number"] for p in removed], [2])
        self.assertEqual([p["number"] for p in box["prs"]], [1])

    def test_thirty_days_after_last_request_is_removed(self):
        """最後に依頼を送信待ちに入れてから 30 日を過ぎた PR は外す。30 日ちょうどは残す (R10)。"""
        box = {"version": 1, "prs": [{"repo": REPO, "number": 1, "enqueued_at": ago(30)},
                                     {"repo": REPO, "number": 2, "enqueued_at": store.format_time(
                                         store.parse_time(ago(30)) - datetime.timedelta(seconds=1))}]}
        removed = tracked.prune(box, [sub("merged")], store.parse_time(NOW))
        self.assertEqual([p["number"] for p in removed], [2])
        self.assertEqual([p["number"] for p in box["prs"]], [1])


class StopTest(unittest.TestCase):

    def test_stop_removes_given_prs(self):
        box = {"version": 1, "prs": [{"repo": REPO, "number": 1, "enqueued_at": NOW},
                                     {"repo": REPO, "number": 2, "enqueued_at": NOW}]}
        tracked.stop(box, {(REPO.upper(), 2)})
        self.assertEqual([p["number"] for p in box["prs"]], [1])


if __name__ == "__main__":
    unittest.main()
