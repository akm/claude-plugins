#!/usr/bin/env python3
"""登録・一覧・番号での削除と、配信のセッションの記録 (ファイル `gh-notification-dispatch/scripts/gh_notification_dispatch/subscriptions.py`)
のテスト。CLI の入口をサブプロセスで実行し、偽の `gh` と、テストごとの記録のディレクトリ・一時ディレクトリを使う。

  python3 -m unittest discover -s gh-notification-dispatch/tests
"""

import json
import os
import unittest

from fakegh_case import FakeGhCase, fixture

from gh_notification_dispatch import messages  # noqa: E402

DISPATCHER = "local_00000000-0000-4000-8000-000000000000"
RECEIVER_A = "local_00000000-0000-4000-8000-00000000000a"
RECEIVER_B = "local_00000000-0000-4000-8000-00000000000b"
OTHER_DISPATCHER = "local_00000000-0000-4000-8000-000000000009"

REPO_OK = {"prefix": ["api", "repos/akm/claude-plugins"], "stdout": {"fixture": "repo-claude-plugins"}}
REPO_OK_UPPER = {"prefix": ["api", "repos/AKM/Claude-Plugins"], "stdout": {"fixture": "repo-claude-plugins"}}
REPO_OTHER = {"prefix": ["api", "repos/akm/other"], "stdout": {"full_name": "akm/other"}}
REPO_NOT_FOUND = {"prefix": ["api", "repos/akm/no-such-repo"], "stdout": {"fixture": "repo-not-found"},
                  "stderr": fixture("repo-not-found", "stderr"), "exit": 1}


class SubscriptionsCase(FakeGhCase):

    def setUp(self):
        super().setUp()
        os.environ["TZ"] = "UTC"
        self.responses([REPO_OK, REPO_OK_UPPER, REPO_OTHER, REPO_NOT_FOUND])
        self.at("2026-11-16T05:00:00Z")

    def tearDown(self):
        os.environ.pop("TZ", None)
        super().tearDown()

    def start_dispatcher(self, mode="auto", session=DISPATCHER):
        self.as_session(session)
        code, out, err = self.cli("dispatcher", "set", "--name", "配信", "--permission-mode", mode)
        self.assertEqual(code, 0, (out, err))
        return out

    def message_file(self, text):
        path = os.path.join(self.root, "message.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def subscribe(self, session=RECEIVER_A, repo="akm/claude-plugins", kinds="review_requested,merged", mode="auto",
                  name=None, sender=None, at=None):
        """受信のセッションの申し込みを、配信のセッションで記録する。"""
        if at:
            self.at(at)
        text = (f"gh-notification-dispatch: 申し込みます。\ntype: subscribe\nrepo: {repo}\nkinds: {kinds}\n"
                f"session-id: {session}\nsession-name: {name or '受信 ' + session[-1]}\npermission-mode: {mode}\n")
        self.as_session(DISPATCHER)
        return self.cli("subscriptions", "add", "--message-file", self.message_file(text), "--sender", sender or session)

    def subscriptions(self):
        path = os.path.join(self.home, "subscriptions.json")
        if not os.path.exists(path):
            return []
        return self.read_home("subscriptions.json")["subscriptions"]


class DispatcherSetTest(SubscriptionsCase):

    def test_records_dispatcher_from_env(self):
        out = self.start_dispatcher()
        self.assertEqual(out["dispatcher"], {"session_id": DISPATCHER, "name": "配信", "permission_mode": "auto",
                                             "recorded_at": "2026-11-16T05:00:00Z"})
        self.assertFalse(out["switched"])
        self.assertEqual(self.read_home("state.json")["dispatcher"]["session_id"], DISPATCHER)
        self.assertEqual(self.recorded(), [], "gh を実行しないこと")

    def test_same_session_updates_name_and_mode(self):
        self.start_dispatcher()
        self.at("2026-11-16T06:00:00Z")
        code, out, _ = self.cli("dispatcher", "set", "--name", "新しい名前", "--permission-mode", "default")
        self.assertEqual(code, 0)
        self.assertEqual(self.read_home("state.json")["dispatcher"],
                         {"session_id": DISPATCHER, "name": "新しい名前", "permission_mode": "default",
                          "recorded_at": "2026-11-16T06:00:00Z"})
        self.assertFalse(out["switched"])

    def test_other_session_needs_switch(self):
        """記録と違うセッションでは、記録を変えずに終了コード 3 で、記録の配信のセッションの名前と ID を返す (R16)。"""
        self.start_dispatcher()
        before = self.home_files()
        self.as_session(OTHER_DISPATCHER)
        code, out, _ = self.cli("dispatcher", "set", "--name", "別の配信", "--permission-mode", "auto")
        self.assertEqual(code, 3)
        self.assertEqual(out["dispatcher"]["session_id"], DISPATCHER)
        self.assertEqual(out["dispatcher"]["name"], "配信")
        self.assertIn("--switch", out["errors"][0])
        self.assertEqual(self.home_files(), before)
        code, out, _ = self.cli("dispatcher", "set", "--name", "別の配信", "--permission-mode", "auto", "--switch")
        self.assertEqual(code, 0)
        self.assertTrue(out["switched"])
        self.assertEqual(out["previous"]["session_id"], DISPATCHER)
        self.assertEqual(self.read_home("state.json")["dispatcher"]["session_id"], OTHER_DISPATCHER)

    def test_missing_env_or_bad_values(self):
        self.as_session(None)
        code, out, _ = self.cli("dispatcher", "set", "--name", "配信", "--permission-mode", "auto")
        self.assertEqual(code, 3)
        self.assertIn("CLAUDE_CODE_HOST_SESSION_ID", out["errors"][0])
        self.as_session(DISPATCHER)
        code, out, _ = self.cli("dispatcher", "set", "--name", "配信", "--permission-mode", "yolo")
        self.assertEqual(code, 3)
        self.assertFalse(os.path.exists(self.home), "記録しないこと")


class AddTest(SubscriptionsCase):

    def test_two_kinds_become_two_subscriptions(self):
        self.start_dispatcher()
        code, out, err = self.subscribe()
        self.assertEqual(code, 0, (out, err))
        self.assertEqual(out["result"], "accepted")
        self.assertEqual([s["kind"] for s in out["added"]], ["review_requested", "merged"])
        self.assertEqual(out["existing"], [])
        subs = self.subscriptions()
        self.assertEqual([(s["repo"], s["kind"], s["session_id"]) for s in subs],
                         [("akm/claude-plugins", "review_requested", RECEIVER_A), ("akm/claude-plugins", "merged", RECEIVER_A)])
        self.assertEqual({s["created_at"] for s in subs}, {"2026-11-16T05:00:00Z"})
        self.assertEqual(len({s["id"] for s in subs}), 2)
        reply = messages.parse(out["reply_body"])
        self.assertEqual(reply["errors"], [])
        self.assertEqual((reply["type"], reply["fields"]["result"], reply["fields"]["added"]),
                         ("subscribed", "accepted", ["review_requested", "merged"]))
        self.assertNotIn("warning", reply["fields"])

    def test_same_subscription_is_not_added_twice(self):
        """(リポジトリ, 種類, セッション) が同じ登録は増えず、登録済みを返す (R3)。名前と権限モードは申し込みの値に変える。"""
        self.start_dispatcher()
        self.subscribe(kinds="review_requested")
        code, out, _ = self.subscribe(name="名前を変えた受信", mode="default", at="2026-11-16T06:00:00Z")
        self.assertEqual(code, 0)
        self.assertEqual([s["kind"] for s in out["added"]], ["merged"])
        self.assertEqual([s["kind"] for s in out["existing"]], ["review_requested"])
        subs = self.subscriptions()
        self.assertEqual(len(subs), 2)
        self.assertEqual({s["session_name"] for s in subs}, {"名前を変えた受信"})
        self.assertEqual({s["permission_mode"] for s in subs}, {"default"})
        self.assertEqual(subs[0]["created_at"], "2026-11-16T05:00:00Z", "登録日時は変えないこと")
        self.assertIn("登録済み 1 件", out["reply_body"].splitlines()[0])

    def test_repo_is_recorded_with_api_name(self):
        """大文字と小文字が違っても同じリポジトリとして扱い、API が返した正式な名前で記録する。"""
        self.start_dispatcher()
        self.subscribe(repo="AKM/Claude-Plugins", kinds="merged")
        self.assertEqual(self.subscriptions()[0]["repo"], "akm/claude-plugins")
        code, out, _ = self.subscribe(repo="akm/claude-plugins", kinds="merged")
        self.assertEqual(code, 0)
        self.assertEqual(len(out["existing"]), 1)
        self.assertEqual(len(self.subscriptions()), 1)

    def test_other_session_same_repo_and_kind_both_remain(self):
        """同じ (リポジトリ, 種類) で別のセッションの登録は、2 件とも残る (R3・KD4)。"""
        self.start_dispatcher()
        self.subscribe(session=RECEIVER_A, kinds="review_requested")
        code, out, _ = self.subscribe(session=RECEIVER_B, kinds="review_requested")
        self.assertEqual(code, 0)
        self.assertEqual(len(out["added"]), 1)
        self.assertEqual([s["session_id"] for s in self.subscriptions()], [RECEIVER_A, RECEIVER_B])

    def test_unreadable_repo_is_not_recorded(self):
        """読めないリポジトリ (偽の gh が 404 を返す) は登録せず、理由を返す。"""
        self.start_dispatcher()
        code, out, _ = self.subscribe(repo="akm/no-such-repo")
        self.assertEqual(code, 3)
        self.assertEqual(out["result"], "rejected")
        self.assertIn("HTTP 404", out["errors"][0])
        self.assertEqual(self.subscriptions(), [])
        reply = messages.parse(out["reply_body"])
        self.assertEqual((reply["errors"], reply["fields"]["result"]), ([], "rejected"))
        self.assertIn("akm/no-such-repo", reply["fields"]["reason"])

    def test_gh_auth_failure_is_exit_4(self):
        self.start_dispatcher()
        os.environ["FAKE_GH_MODE"] = "auth_expired"
        code, out, _ = self.subscribe()
        self.assertEqual(code, 4)
        self.assertEqual(out["gh_error"]["failure"], "auth")
        self.assertEqual(self.subscriptions(), [])
        self.assertEqual(messages.parse(out["reply_body"])["fields"]["result"], "rejected",
                         "受信のセッションが返事を受け取れるよう、返事の本文を返すこと")

    def test_hold_warning_when_permission_class_differs(self):
        """権限モードの分類が違う登録は、登録したうえで、保留されて 5 分で捨てられることを返事に書く (R4)。"""
        self.start_dispatcher(mode="auto")
        code, out, _ = self.subscribe(mode="bypassPermissions")
        self.assertEqual(code, 0)
        self.assertEqual(len(self.subscriptions()), 2)
        self.assertIn("5 分で捨てられます", out["warning"])
        self.assertIn("5 分で捨てられます", messages.parse(out["reply_body"])["fields"]["warning"])

    def test_no_hold_warning_when_only_mode_differs(self):
        """権限モードが違っても分類が同じ (auto と default) なら書かない。"""
        self.start_dispatcher(mode="auto")
        code, out, _ = self.subscribe(mode="default")
        self.assertEqual(code, 0)
        self.assertIsNone(out["warning"])
        self.assertNotIn("warning:", out["reply_body"])

    def test_no_dispatcher_recorded(self):
        """dispatcher set で配信のセッションを記録していないときは、記録せず、gh も実行せずに終了コード 3。"""
        code, out, _ = self.subscribe()
        self.assertEqual(code, 3)
        self.assertIn("配信のセッションが記録されていない", out["errors"][0])
        self.assertFalse(os.path.exists(self.home))
        self.assertEqual(self.recorded(), [])

    def test_other_session_cannot_write(self):
        """記録の配信のセッションと違うセッションで記録を書くサブコマンドを実行すると、記録を変えずに終了コード 3。"""
        self.start_dispatcher()
        before = self.home_files()
        text = ("gh-notification-dispatch: 申し込みます。\ntype: subscribe\nrepo: akm/claude-plugins\nkinds: merged\n"
                f"session-id: {RECEIVER_A}\nsession-name: 受信\npermission-mode: auto\n")
        self.as_session(OTHER_DISPATCHER)
        code, out, _ = self.cli("subscriptions", "add", "--message-file", self.message_file(text), "--sender", RECEIVER_A)
        self.assertEqual(code, 3)
        self.assertIn(DISPATCHER, out["errors"][0])
        self.assertEqual(self.home_files(), before)
        self.assertEqual(self.recorded(), [])

    def test_sender_must_match_session_id(self):
        """本文の session-id がメッセージの送り手の ID と違う申し込みは受け付けない (計画のレビューの 12 回目 #3)。"""
        self.start_dispatcher()
        code, out, _ = self.subscribe(session=RECEIVER_A, sender=RECEIVER_B)
        self.assertEqual(code, 3)
        self.assertIn("送り手", out["errors"][0])
        self.assertEqual(self.subscriptions(), [])
        self.assertEqual(self.recorded(), [])

    def test_malformed_messages(self):
        self.start_dispatcher()
        cases = {
            "type が無い": "gh-notification-dispatch: x\nrepo: akm/claude-plugins\n",
            "未知の種類": None,
            "owner/repo の形でない": None,
            "必須のキーが無い": "gh-notification-dispatch: x\ntype: subscribe\nrepo: akm/claude-plugins\n",
            "type が違う": "gh-notification-dispatch: x\ntype: removed\nremoved: akm/claude-plugins merged\n",
        }
        for name, text in cases.items():
            with self.subTest(name=name):
                if name == "未知の種類":
                    code, out, _ = self.subscribe(kinds="closed")
                elif name == "owner/repo の形でない":
                    code, out, _ = self.subscribe(repo="claude-plugins")
                else:
                    self.as_session(DISPATCHER)
                    code, out, _ = self.cli("subscriptions", "add", "--message-file", self.message_file(text),
                                            "--sender", RECEIVER_A)
                self.assertEqual(code, 3)
                self.assertTrue(out["errors"])
                self.assertEqual(messages.parse(out["reply_body"])["fields"]["result"], "rejected")
        self.assertEqual(self.subscriptions(), [])
        self.assertEqual(self.recorded(), [], "形が違う申し込みでは gh を実行しないこと")


class ListTest(SubscriptionsCase):

    def setUp(self):
        super().setUp()
        self.start_dispatcher()
        self.subscribe(session=RECEIVER_A, kinds="review_requested", at="2026-11-16T05:01:00Z")
        self.subscribe(session=RECEIVER_B, kinds="merged", at="2026-11-16T05:02:00Z")
        self.subscribe(session=RECEIVER_A, kinds="merged", repo="akm/other", at="2026-11-16T05:03:00Z")
        self.at("2026-11-16T05:10:00Z")

    def list_as(self, session, *extra):
        self.as_session(session)
        return self.cli("subscriptions", "list", "--viewer", session, *extra)

    def test_dispatcher_list_numbers_by_created_at(self):
        code, out, err = self.list_as(DISPATCHER)
        self.assertEqual(code, 0, (out, err))
        self.assertEqual([(r["number"], r["session_id"], r["kind"]) for r in out["subscriptions"]],
                         [(1, RECEIVER_A, "review_requested"), (2, RECEIVER_B, "merged"), (3, RECEIVER_A, "merged")])
        self.assertEqual(out["snapshot"], os.path.join(self.home, "snapshots", f"{DISPATCHER}.json"))
        snapshot = self.read_home(f"snapshots/{DISPATCHER}.json")
        self.assertEqual([e["number"] for e in snapshot["entries"]], [1, 2, 3])
        self.assertEqual(snapshot["listed_at"], "2026-11-16T05:10:00Z")
        self.assertIn("| 番号 | リポジトリ | 種類 | 登録日時 | 届け先のセッション |", out["table"])
        self.assertIn("| 1 | akm/claude-plugins | review_requested | 2026-11-16 05:01 +0000 | 受信 a |", out["table"])

    def test_order_follows_created_at_not_file_order(self):
        data = self.read_home("subscriptions.json")
        data["subscriptions"].reverse()
        self.write_home("subscriptions.json", data)
        _, out, _ = self.list_as(DISPATCHER)
        self.assertEqual([r["created_at"] for r in out["subscriptions"]],
                         ["2026-11-16T05:01:00Z", "2026-11-16T05:02:00Z", "2026-11-16T05:03:00Z"])

    def test_receiver_mine_list_does_not_change_home(self):
        """受信のセッションの一覧は自分の登録だけに番号を振り、対応を一時ディレクトリに書き、記録のディレクトリを変えない。
        配信のセッションかの確認で、終了コード 3 にならない (計画のレビューの 11 回目 #7)。"""
        before = self.home_files()
        code, out, err = self.list_as(RECEIVER_A, "--mine")
        self.assertEqual(code, 0, (out, err))
        self.assertEqual([(r["number"], r["repo"]) for r in out["subscriptions"]],
                         [(1, "akm/claude-plugins"), (2, "akm/other")])
        path = os.path.join(self.tmpdir, "gh-notification-dispatch", RECEIVER_A, "snapshot.json")
        self.assertEqual(out["snapshot"], path)
        with open(path, encoding="utf-8") as f:
            self.assertTrue(json.load(f)["mine"])
        self.assertEqual(self.home_files(), before)

    def test_viewer_dispatcher_from_other_session(self):
        before = self.home_files()
        self.as_session(RECEIVER_A)
        code, out, _ = self.cli("subscriptions", "list", "--viewer", DISPATCHER)
        self.assertEqual(code, 3)
        self.assertEqual(self.home_files(), before)

    def test_bad_viewer(self):
        code, out, _ = self.list_as("../etc")
        self.assertEqual(code, 3)


class RemoveTest(ListTest):

    def remove(self, *numbers):
        self.as_session(DISPATCHER)
        return self.cli("subscriptions", "remove", "--viewer", DISPATCHER, *map(str, numbers))

    def test_remove_by_number_and_notify_other_sessions(self):
        self.list_as(DISPATCHER)
        code, out, err = self.remove(2, 3)
        self.assertEqual(code, 0, (out, err))
        self.assertEqual([(r["number"], r["session_id"]) for r in out["removed"]], [(2, RECEIVER_B), (3, RECEIVER_A)])
        self.assertEqual([(s["session_id"], s["kind"]) for s in self.subscriptions()], [(RECEIVER_A, "review_requested")])
        self.assertEqual(sorted(m["to_session_id"] for m in out["messages"]), [RECEIVER_A, RECEIVER_B],
                         "削除した登録の受信のセッションごとに 1 つ通知すること (R6)")
        to_b = next(m for m in out["messages"] if m["to_session_id"] == RECEIVER_B)
        self.assertEqual(to_b["to"], "受信 b")
        parsed = messages.parse(to_b["body"])
        self.assertEqual((parsed["errors"], parsed["type"], parsed["fields"]["removed"]),
                         ([], "removed", "akm/claude-plugins merged"))

    def test_number_keeps_listed_subscription_after_new_one(self):
        """一覧の後に別の登録が増えても、指定した番号の登録だけが消える。"""
        self.list_as(DISPATCHER)
        self.subscribe(session=RECEIVER_B, kinds="review_requested", at="2026-11-16T05:00:30Z")  # 一覧では 1 番より前になる
        code, out, _ = self.remove(1)
        self.assertEqual(code, 0)
        self.assertEqual((out["removed"][0]["session_id"], out["removed"][0]["kind"]), (RECEIVER_A, "review_requested"))
        self.assertIn((RECEIVER_B, "review_requested"), [(s["session_id"], s["kind"]) for s in self.subscriptions()])

    def test_invalid_numbers_remove_nothing(self):
        self.list_as(DISPATCHER)
        self.remove(1)
        before = self.subscriptions()
        cases = {"既に無い": (1,), "範囲の外": (4,), "正しい番号と混ざる": (2, 4)}
        for name, numbers in cases.items():
            with self.subTest(name=name):
                code, out, _ = self.remove(*numbers)
                self.assertEqual(code, 3)
                self.assertTrue(out["errors"])
                self.assertEqual(self.subscriptions(), before, "何も消さないこと")
        _, out, _ = self.remove(1)
        self.assertIn("一覧の表示からやり直す", out["errors"][0])

    def test_without_listing(self):
        code, out, _ = self.remove(1)
        self.assertEqual(code, 3)
        self.assertIn("一覧を表示していない", out["errors"][0])
        self.assertEqual(len(self.subscriptions()), 3)

    def test_receiver_cannot_remove(self):
        self.list_as(RECEIVER_A, "--mine")
        before = self.home_files()
        code, _, _ = self.cli("subscriptions", "remove", "--viewer", RECEIVER_A, "1")
        self.assertEqual(code, 3)
        self.assertEqual(self.home_files(), before)


class ResolveAndUnsubscribeTest(ListTest):

    def resolve(self, *numbers, session=RECEIVER_A):
        self.as_session(session)
        return self.cli("subscriptions", "resolve", "--viewer", session, "--name", "受信 a", *map(str, numbers))

    def unsubscribe(self, text, sender=RECEIVER_A):
        self.as_session(DISPATCHER)
        return self.cli("subscriptions", "unsubscribe", "--message-file", self.message_file(text), "--sender", sender)

    def test_resolve_and_unsubscribe(self):
        self.list_as(RECEIVER_A, "--mine")
        before = self.home_files()
        code, out, err = self.resolve(2)
        self.assertEqual(code, 0, (out, err))
        self.assertEqual(self.home_files(), before, "resolve は記録のディレクトリを変えないこと")
        self.assertEqual([s["repo"] for s in out["subscriptions"]], ["akm/other"])
        self.assertEqual(out["dispatcher"]["name"], "配信")
        parsed = messages.parse(out["message_body"])
        self.assertEqual((parsed["errors"], parsed["type"], parsed["fields"]["subscription-ids"]),
                         ([], "unsubscribe", out["subscription_ids"]))
        code, out, err = self.unsubscribe(out["message_body"])
        self.assertEqual(code, 0, (out, err))
        self.assertEqual([s["repo"] for s in out["removed"]], ["akm/other"])
        self.assertEqual(len(self.subscriptions()), 2)
        reply = messages.parse(out["reply_body"])
        self.assertEqual((reply["errors"], reply["fields"]["removed"]), ([], "akm/other merged"))

    def test_resolve_errors(self):
        code, out, _ = self.resolve(1)
        self.assertIn("一覧を表示していない", out["errors"][0])
        self.assertEqual(code, 3)
        self.list_as(RECEIVER_A, "--mine")
        self.assertEqual(self.resolve(3)[0], 3, "自分の一覧の範囲の外")
        self.list_as(RECEIVER_A)  # --mine の無い一覧
        code, out, _ = self.resolve(2)
        self.assertEqual(code, 3)
        self.assertIn("このセッションの登録ではない", out["errors"][0])

    def test_unsubscribe_others_subscription_is_refused(self):
        """unsubscribe のメッセージにある ID が、送ったセッションの登録でないときは消さない。"""
        b_id = next(s["id"] for s in self.subscriptions() if s["session_id"] == RECEIVER_B)
        a_id = next(s["id"] for s in self.subscriptions() if s["session_id"] == RECEIVER_A)
        before = self.subscriptions()
        text = messages.unsubscribe([a_id, b_id], RECEIVER_A, "受信 a")
        code, out, _ = self.unsubscribe(text)
        self.assertEqual(code, 3)
        self.assertIn("送り手のセッションの登録ではない", out["errors"][0])
        self.assertEqual(self.subscriptions(), before)
        self.assertEqual(messages.parse(out["reply_body"])["fields"]["result"], "rejected")

    def test_unsubscribe_sender_must_match(self):
        a_id = next(s["id"] for s in self.subscriptions() if s["session_id"] == RECEIVER_A)
        before = self.subscriptions()
        code, out, _ = self.unsubscribe(messages.unsubscribe([a_id], RECEIVER_A, "受信 a"), sender=RECEIVER_B)
        self.assertEqual(code, 3)
        self.assertEqual(self.subscriptions(), before)

    def test_unsubscribe_missing_id(self):
        before = self.subscriptions()
        code, out, _ = self.unsubscribe(messages.unsubscribe(["0123456789ab"], RECEIVER_A, "受信 a"))
        self.assertEqual(code, 3)
        self.assertIn("既に無い", out["errors"][0])
        self.assertEqual(self.subscriptions(), before)


class RequestTest(SubscriptionsCase):

    def test_request_body(self):
        self.start_dispatcher()
        self.as_session(RECEIVER_A)
        before = self.home_files()
        code, out, err = self.cli("subscriptions", "request", "--name", "受信 a", "--permission-mode", "auto",
                                  "--repo", "akm/claude-plugins", "--kind", "merged")
        self.assertEqual(code, 0, (out, err))
        self.assertEqual(self.home_files(), before)
        self.assertEqual(out["dispatcher"]["name"], "配信")
        parsed = messages.parse(out["message_body"])
        self.assertEqual(parsed["errors"], [])
        self.assertEqual(parsed["fields"], {"repo": "akm/claude-plugins", "kinds": ["merged"], "session-id": RECEIVER_A,
                                            "session-name": "受信 a", "permission-mode": "auto"})
        self.assertEqual(self.recorded(), [], "--repo があれば gh を実行しないこと")

    def test_defaults_repo_from_working_directory_and_both_kinds(self):
        """リポジトリを省くと作業ディレクトリのリポジトリ、種類を省くと 2 つとも (R2)。"""
        self.responses([{"prefix": ["repo", "view"], "stdout": {"fixture": "repo-view"}}])
        self.as_session(RECEIVER_A)
        code, out, _ = self.cli("subscriptions", "request", "--name", "受信 a", "--permission-mode", "default")
        self.assertEqual(code, 0)
        self.assertIsNone(out["dispatcher"])
        self.assertEqual(out["repo"], "akm/claude-plugins")
        self.assertEqual(messages.parse(out["message_body"])["fields"]["kinds"], list(messages.KINDS))
        self.assertFalse(os.path.exists(self.home))

    def test_not_a_repository_is_exit_4(self):
        self.responses([{"prefix": ["repo", "view"], "stderr": fixture("repo-view-not-git", "stderr"), "exit": 1}])
        self.as_session(RECEIVER_A)
        code, out, _ = self.cli("subscriptions", "request", "--name", "受信 a", "--permission-mode", "auto")
        self.assertEqual(code, 4)
        self.assertIn("not a git repository", out["gh_error"]["stderr_tail"])

    def test_errors(self):
        self.as_session(None)
        code, out, _ = self.cli("subscriptions", "request", "--name", "受信", "--permission-mode", "auto",
                                "--repo", "akm/claude-plugins")
        self.assertEqual(code, 3)
        self.as_session(RECEIVER_A)
        code, out, _ = self.cli("subscriptions", "request", "--name", "受信", "--permission-mode", "auto",
                                "--repo", "akm/claude-plugins", "--kind", "closed")
        self.assertEqual(code, 3)
        self.assertEqual(self.recorded(), [])


if __name__ == "__main__":
    unittest.main()
