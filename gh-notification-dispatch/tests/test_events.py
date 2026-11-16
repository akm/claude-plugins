#!/usr/bin/env python3
"""種類の判定 (ファイル `gh-notification-dispatch/scripts/gh_notification_dispatch/events.py`) のテスト。

偽の `gh` が返す timeline で、review_requested の判定を確認する (計画の R9・KTD4)。

  python3 -m unittest discover -s gh-notification-dispatch/tests
"""

import unittest

from fakegh_case import FakeGhCase, fixture, http, link_next, notification, timeline_event

from gh_notification_dispatch import events  # noqa: E402

SINCE = "2026-11-16T06:00:00Z"
REPO = "akm/claude-plugins"
VIEWER = {"login": "akm", "teams": [{"id": 101, "slug": "reviewers", "organization": "akm-org"}]}


def timeline_path(repo, number, page=None):
    path = f"repos/{repo}/issues/{number}/timeline?per_page=100"
    return path if page is None else f"{path}&page={page}"


class ReviewRequestsTest(FakeGhCase):

    def serve_timeline(self, repo, number, items, more=None):
        entries = [{"prefix": ["api", "-i", timeline_path(repo, number)],
                    "stdout": http(200, items, {"Link": link_next(timeline_path(repo, number, 2))} if more else None)}]
        if more:
            entries.append({"prefix": ["api", "-i", timeline_path(repo, number, 2)], "stdout": http(200, more)})
        return entries

    def judge(self, notifications, repos=(REPO.lower(),)):
        return events.review_requests(notifications, set(repos), VIEWER, SINCE)

    def test_own_request_after_since(self):
        self.responses(self.serve_timeline(REPO, 1, [
            timeline_event(10, "2026-11-16T05:59:59Z", login="akm"),
            timeline_event(11, SINCE, login="akm"),
            timeline_event(12, "2026-11-16T06:00:01Z", login="akm"),
            timeline_event(13, "2026-11-16T06:00:02Z", login="someone-else"),
        ]))
        found, failure = self.judge([notification(REPO, 1, "2026-11-16T06:01:00Z", title="✨ feat: 通知")])
        self.assertIsNone(failure)
        self.assertEqual(found, [{"kind": "review_requested", "key": "review_requested:12", "repo": REPO, "number": 1,
                                  "title": "✨ feat: 通知", "url": f"https://github.com/{REPO}/pull/1",
                                  "time": "2026-11-16T06:00:01Z", "requested": "akm"}],
                         "起点より後 (起点と同じ時刻は含まない) の、自分への依頼だけ")

    def test_team_request_matches_by_id(self):
        """チームは ID で照合する。同じ slug の別のチームへの依頼は届けない (計画のレビューの 8 回目 #8)。"""
        self.responses(self.serve_timeline(REPO, 2, [
            timeline_event(20, "2026-11-16T06:01:00Z", team_id=101, team_slug="reviewers"),
            timeline_event(21, "2026-11-16T06:02:00Z", team_id=999, team_slug="reviewers"),
        ]))
        found, _ = self.judge([notification(REPO, 2, "2026-11-16T06:03:00Z")])
        self.assertEqual([(e["key"], e["requested"]) for e in found], [("review_requested:20", "akm-org/reviewers")])

    def test_push_after_request_is_not_new(self):
        """依頼の後に push で更新された通知 (理由は review_requested のまま) では、新しい依頼が無いので届けない。"""
        self.responses(self.serve_timeline(REPO, 3, [
            timeline_event(30, "2026-11-16T05:00:00Z", login="akm"),
            {"id": 31, "event": "committed", "created_at": "2026-11-16T06:10:00Z"},
            {"id": 32, "event": "head_ref_force_pushed", "created_at": "2026-11-16T06:11:00Z"},
        ]))
        found, _ = self.judge([notification(REPO, 3, "2026-11-16T06:11:00Z")])
        self.assertEqual(found, [])

    def test_re_request_after_removal_is_new(self):
        self.responses(self.serve_timeline(REPO, 4, [
            timeline_event(40, "2026-11-16T05:00:00Z", login="akm"),
            timeline_event(41, "2026-11-16T06:05:00Z", login="akm", event="review_request_removed"),
            timeline_event(42, "2026-11-16T06:06:00Z", login="akm"),
        ]))
        found, _ = self.judge([notification(REPO, 4, "2026-11-16T06:06:00Z")])
        self.assertEqual([e["key"] for e in found], ["review_requested:42"])

    def test_request_on_second_timeline_page(self):
        self.responses(self.serve_timeline(REPO, 5, [{"id": 50, "event": "commented", "created_at": "2026-11-16T05:00:00Z"}],
                                           more=[timeline_event(51, "2026-11-16T06:30:00Z", login="akm")]))
        found, _ = self.judge([notification(REPO, 5, "2026-11-16T06:30:00Z")])
        self.assertEqual([e["key"] for e in found], ["review_requested:51"])

    def test_unregistered_repo_and_non_pull_are_not_read(self):
        """登録の無いリポジトリの通知・PR でない通知・起点より前に更新された通知では、timeline を読まない。"""
        found, failure = self.judge([
            notification("akm/other", 6, "2026-11-16T06:10:00Z"),
            notification(REPO, 7, "2026-11-16T06:10:00Z", subject_type="Issue"),
            notification(REPO, 8, SINCE),
        ])
        self.assertEqual((found, failure), ([], None))
        self.assertEqual(self.recorded(), [])

    def test_case_insensitive_login_and_repo(self):
        self.responses(self.serve_timeline("AKM/Claude-Plugins", 9, [timeline_event(90, "2026-11-16T06:01:00Z", login="AKM")]))
        found, _ = self.judge([notification("AKM/Claude-Plugins", 9, "2026-11-16T06:02:00Z")])
        self.assertEqual([(e["repo"], e["requested"]) for e in found], [("AKM/Claude-Plugins", "akm")])

    def test_timeline_failure_names_repo_and_number(self):
        self.responses([{"prefix": ["api", "-i", timeline_path(REPO, 10)], "stdout": http(404, {"message": "Not Found"}),
                         "stderr": fixture("repo-not-found", "stderr"), "exit": 1}])
        found, failure = self.judge([notification(REPO, 10, "2026-11-16T06:10:00Z")])
        self.assertIsNone(found)
        self.assertEqual((failure["api"], failure["repo"], failure["number"]), ("timeline", REPO, 10))
        self.assertEqual(failure["result"]["failure"], "not_found")

    def test_same_event_from_two_notifications_once(self):
        self.responses(self.serve_timeline(REPO, 11, [timeline_event(110, "2026-11-16T06:01:00Z", login="akm")]))
        found, _ = self.judge([notification(REPO, 11, "2026-11-16T06:02:00Z"), notification(REPO, 11, "2026-11-16T06:03:00Z")])
        self.assertEqual(len(found), 1)


if __name__ == "__main__":
    unittest.main()
