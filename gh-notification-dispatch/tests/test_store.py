#!/usr/bin/env python3
"""記録のディレクトリの読み書き (ファイル `gh-notification-dispatch/scripts/gh_notification_dispatch/store.py`) のテスト。

  python3 -m unittest discover -s gh-notification-dispatch/tests
"""

import datetime
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from fakegh_case import SCRIPTS, FakeGhCase

from gh_notification_dispatch import store  # noqa: E402

DISPATCHER = "local_00000000-0000-4000-8000-000000000000"
OTHER = "local_00000000-0000-4000-8000-000000000009"


class StoreCase(FakeGhCase):

    def record_dispatcher(self, session_id=DISPATCHER):
        self.write_home(store.STATE, {"version": 1, "dispatcher": {"session_id": session_id, "name": "配信",
                                                                  "permission_mode": "auto",
                                                                  "recorded_at": "2026-11-16T05:00:00Z"}})


class DispatcherCheckTest(StoreCase):
    """記録のディレクトリに書くのは配信のセッションだけ (計画の R19・KTD3)。"""

    def test_dispatcher_can_write(self):
        self.record_dispatcher()
        self.as_session(DISPATCHER)
        with store.transaction() as tx:
            tx.write(store.SUBSCRIPTIONS, {"version": 1, "subscriptions": []})
        self.assertEqual(self.read_home(store.SUBSCRIPTIONS), {"version": 1, "subscriptions": []})

    def test_other_session_cannot_write(self):
        self.record_dispatcher()
        self.as_session(OTHER)
        before = self.home_files()
        with self.assertRaises(store.NotDispatcher) as caught:
            with store.transaction() as tx:
                tx.write(store.SUBSCRIPTIONS, {"version": 1, "subscriptions": []})
        self.assertEqual(caught.exception.dispatcher["session_id"], DISPATCHER, "記録の配信のセッションを返すこと")
        self.assertIn(DISPATCHER, str(caught.exception))
        self.assertEqual(self.home_files(), before, "記録を変えないこと")

    def test_no_dispatcher_creates_nothing(self):
        self.as_session(DISPATCHER)
        with self.assertRaises(store.NotDispatcher) as caught:
            with store.transaction():
                pass
        self.assertIsNone(caught.exception.dispatcher)
        self.assertFalse(os.path.exists(self.home), "配信のセッションの記録が無ければ、記録のディレクトリも作らないこと")

    def test_missing_session_env(self):
        self.record_dispatcher()
        self.as_session(None)
        with self.assertRaises(store.NotDispatcher) as caught:
            with store.transaction():
                pass
        self.assertIn(store.SESSION_ENV, str(caught.exception))

    def test_recheck_after_lock(self):
        """ロックを取るまでの間に配信のセッションが切り替わったら、ロックを取った後の記録で拒否する。"""
        self.record_dispatcher()
        self.as_session(DISPATCHER)
        original = store.Transaction.read
        switched = {"done": False}

        def read_after_switch(tx, name):
            if name == store.STATE and not switched["done"]:
                switched["done"] = True
                self.record_dispatcher(OTHER)
            return original(tx, name)

        with mock.patch.object(store.Transaction, "read", read_after_switch):
            with self.assertRaises(store.NotDispatcher):
                with store.transaction():
                    pass

    def test_setting_dispatcher_skips_check(self):
        self.as_session(OTHER)
        with store.transaction(setting_dispatcher=True) as tx:
            tx.write(store.STATE, {"version": 1})
        self.assertEqual(self.read_home(store.STATE), {"version": 1})


class AtomicWriteTest(StoreCase):

    def test_failed_write_keeps_original(self):
        """一時ファイルの名前を変える前に例外が起きても、元のファイルが残り、一時ファイルも残らない。"""
        self.record_dispatcher()
        self.as_session(DISPATCHER)
        original = {"version": 1, "subscriptions": [{"id": "0123456789ab"}]}
        self.write_home(store.SUBSCRIPTIONS, original)
        with mock.patch.object(store.os, "replace", side_effect=OSError("名前を変える前の失敗")):
            with self.assertRaises(OSError):
                with store.transaction() as tx:
                    tx.write(store.SUBSCRIPTIONS, {"version": 1, "subscriptions": []})
        self.assertEqual(self.read_home(store.SUBSCRIPTIONS), original)
        self.assertEqual(sorted(os.listdir(self.home)), [store.LOCK, store.STATE, store.SUBSCRIPTIONS],
                         "一時ファイルを残さないこと")

    def test_failed_serialization_keeps_original(self):
        self.record_dispatcher()
        self.as_session(DISPATCHER)
        original = {"version": 1, "subscriptions": []}
        self.write_home(store.SUBSCRIPTIONS, original)
        with self.assertRaises(TypeError):
            with store.transaction() as tx:
                tx.write(store.SUBSCRIPTIONS, {"version": 1, "subscriptions": [object()]})
        self.assertEqual(self.read_home(store.SUBSCRIPTIONS), original)
        self.assertEqual(sorted(os.listdir(self.home)), [store.LOCK, store.STATE, store.SUBSCRIPTIONS])


class LockTest(StoreCase):

    def test_concurrent_writers_are_serialized(self):
        """複数のプロセスが、ロックを取って読み、書き換え、書いても、書き込みが失われない。"""
        self.record_dispatcher()
        self.as_session(DISPATCHER)
        code = ("import sys, time; sys.path.insert(0, sys.argv[1]); from gh_notification_dispatch import store\n"
                "for _ in range(10):\n"
                "    with store.transaction() as tx:\n"
                "        data = tx.read('counter.json') or {'count': 0}\n"
                "        time.sleep(0.005)\n"
                "        tx.write('counter.json', {'count': data['count'] + 1})\n")
        processes = [subprocess.Popen([sys.executable, "-c", code, SCRIPTS], env=dict(os.environ)) for _ in range(4)]
        for p in processes:
            self.assertEqual(p.wait(timeout=60), 0)
        self.assertEqual(self.read_home("counter.json"), {"count": 40})


class ReceiverSnapshotTest(StoreCase):

    def test_receiver_snapshot_is_outside_home(self):
        """受信のセッションの対応は ${TMPDIR}/gh-notification-dispatch/<ID>/snapshot.json に書き、配信のセッションの確認をしない。"""
        self.record_dispatcher()
        self.as_session(OTHER)
        before = self.home_files()
        store.write_receiver_snapshot(OTHER, {"version": 1, "entries": []})
        path = os.path.join(self.tmpdir, "gh-notification-dispatch", OTHER, "snapshot.json")
        with open(path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"version": 1, "entries": []})
        self.assertEqual(store.read_receiver_snapshot(OTHER), {"version": 1, "entries": []})
        self.assertEqual(self.home_files(), before)

    def test_tmpdir_default(self):
        os.environ["TMPDIR"] = ""
        self.assertEqual(store.receiver_snapshot_path(OTHER), f"/tmp/gh-notification-dispatch/{OTHER}/snapshot.json")

    def test_session_id_must_be_path_safe(self):
        for value in ("../x", "a/b", ""):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    store.receiver_snapshot_path(value)
                with self.assertRaises(ValueError):
                    store.dispatcher_snapshot_name(value)


class TimeTest(StoreCase):

    def test_now_from_env(self):
        self.at("2026-11-16T05:00:00Z")
        self.assertEqual(store.now(), datetime.datetime(2026, 11, 16, 5, 0, tzinfo=datetime.timezone.utc))
        self.assertEqual(store.format_time(store.now()), "2026-11-16T05:00:00Z")

    def test_now_without_env_is_utc_seconds(self):
        value = store.now()
        self.assertEqual(value.tzinfo, datetime.timezone.utc)
        self.assertEqual(value.microsecond, 0)

    def test_default_home(self):
        os.environ.pop(store.HOME_ENV)
        self.assertEqual(store.home(), os.path.expanduser("~/.claude/gh-notification-dispatch"))


if __name__ == "__main__":
    unittest.main()
