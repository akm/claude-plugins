#!/usr/bin/env python3
"""記録 (ファイル `disk-usage-triage/scripts/disk_usage_triage/records.py`) と、判定の順への記録の組み込み
(ファイル `disk-usage-triage/scripts/disk_usage_triage/judge.py`) のテスト。

計画 docs/plans/2026-11-22-1630-feat-disk-usage-triage-plan.md の U4 のテストシナリオのうち、R16 の検査 (test_commands.py) を
除いたもの。記録の様式は R18・KTD16、下の階層への適用は R19、Claude の判定は R20、利用者の記録は R21、一覧と削除は R22、
判定の順は R13 にある。

  python3 -m unittest discover -s disk-usage-triage/tests
"""

import json
import os
import unittest
from unittest import mock

from test_judge import JudgeCase

from disk_usage_triage import judge, records, store  # noqa: E402

TODAY = "2026-11-27"
UDID = "0A1B2C3D-0000-4000-8000-000000000001"  # 端末のディレクトリの名前 (xcrun simctl delete の {name} に置き換える)


def directory(path):
    return {"kind": "directory", "path": path}


def claude_input(judgment="review", **extra):
    data = {"judgment": judgment, "reason": "Claude が調べた理由", "impact": "Claude が調べた影響",
            "basis": ["https://example.com/docs"], "command": None if judgment == "keep" else {"type": "rm"}}
    data.update(extra)
    return data


def row(pattern, judgment="review", **extra):
    data = {"pattern": pattern, "judgment": judgment, "reason": f"{pattern} の理由", "impact": f"{pattern} の影響",
            "command": None if judgment == "keep" else {"type": "rm"},
            "sources": [{"url": "https://example.com/", "checked_on": "2026-11-25"}]}
    data.update(extra)
    return data


def tool(*args, env=None):
    command = {"type": "tool", "args": list(args)}
    if env is not None:
        command["env"] = env
    return command


class RecordsCase(JudgeCase):

    def setUp(self):
        super().setUp()
        self.env = self.environment()

    def add_user(self, target, judgment="keep", **kwargs):
        return records.add_user(target, judgment, env=self.env, today=TODAY, **kwargs)

    def add_claude(self, path, data):
        return records.add_claude(path, data, env=self.env, today=TODAY)

    def assert_ok(self, result):
        self.assertEqual(result["status"], "ok", result["errors"])
        self.assertEqual(result["errors"], [])
        return result

    def assert_unsatisfied(self, result, fragment=None):
        self.assertEqual(result["status"], "unsatisfied")
        self.assertTrue(result["errors"])
        if fragment is not None:
            self.assertTrue(any(fragment in error for error in result["errors"]), result["errors"])
        return result

    def stored(self):
        return self.read_home(records.RECORDS)["records"]

    def judge(self, path, rows=(), usage=None):
        return judge.judge(path, self.env, list(rows), records=judge.DirectoryRecords(records.load()), usage=usage)


class DirectoryKeyTest(RecordsCase):
    """ディレクトリの記録のキー (R18・KTD16)。"""

    def test_symlink_is_resolved(self):
        """シンボリックリンクのパスで記録しても、解決した先のパスで記録し、解決した先の判定に使う。"""
        real = self.make_dir("user-home", "Library", "Caches", "real")
        link = os.path.join(self.user_home, "link")
        os.symlink(real, link)
        result = self.assert_ok(self.add_user(directory(link)))
        self.assertEqual(result["record"]["target"], directory(real))
        self.assertEqual(self.stored()[0]["target"], directory(real))
        for path in (real, link):
            with self.subTest(path=path):
                judged = self.judge(path)
                self.assertEqual(judged["judgment"], "keep")
                self.assertEqual(judged["source"], "record")

    def test_home_prefix_is_expanded(self):
        target = self.make_dir("user-home", "Library", "Caches", "foo")
        self.assert_ok(self.add_user(directory("~/Library/Caches/foo")))
        self.assertEqual(self.stored()[0]["target"]["path"], target)

    def test_invalid_paths(self):
        """無いディレクトリ・ディレクトリでないパス・相対パス・~<利用者名> は記録しない。"""
        file_path = os.path.join(self.user_home, "file")
        with open(file_path, "w", encoding="utf-8"):
            pass
        for path, fragment in ((os.path.join(self.user_home, "missing"), "存在しない"),
                               (file_path, "ディレクトリでない"), ("Library/Caches", "相対パス"),
                               ("~root/Library", "~<利用者名>")):
            with self.subTest(path=path):
                self.assert_unsatisfied(self.add_user(directory(path)), fragment)
        self.assertFalse(os.path.exists(os.path.join(self.home, records.RECORDS)))

    def test_same_directory_is_replaced(self):
        """同じ対象を記録し直すと置き換え、記録は 1 つのまま。"""
        target = self.make_dir("user-home", "Library", "Caches", "foo")
        self.assert_ok(self.add_user(directory(target)))
        result = self.assert_ok(self.add_user(directory(target), reason="利用者の理由"))
        self.assertEqual(len(self.stored()), 1)
        self.assertIsNotNone(result["previous"])
        self.assertEqual(self.stored()[0]["reason"], "利用者の理由")

    def test_same_identity_with_a_different_path_is_replaced(self):
        """パスの文字列が違っても、ディレクトリの識別子が同じなら同じ対象として置き換える (KTD16)。

        大文字と小文字を区別しないファイルシステムで起きる書き方の違いを、関数 os.path.realpath にシンボリックリンクを
        解決させないことで、どのファイルシステムでも作る (test_judge.py の ProtectionTest と同じ方法)。
        """
        target = self.make_dir("user-home", "Library", "Caches", "foo")
        link = os.path.join(self.user_home, "foo-link")
        os.symlink(target, link)
        self.assert_ok(self.add_user(directory(target)))
        with mock.patch.object(records.os.path, "realpath", os.path.abspath), \
                mock.patch.object(judge.os.path, "realpath", os.path.abspath):
            self.assert_ok(self.add_user(directory(link), reason="2 回目"))
        self.assertEqual(len(self.stored()), 1)
        self.assertEqual(self.stored()[0]["reason"], "2 回目")

    def test_record_replaced_by_a_symlink_is_not_used_for_the_link_target(self):
        """記録したディレクトリが後でシンボリックリンクに置き換わったら、リンク先の別のディレクトリに記録を使わない (KTD16)。"""
        recorded = self.make_dir("user-home", "Library", "Caches", "foo")
        other = self.make_dir("user-home", "Library", "Caches", "other")
        self.assert_ok(self.add_user(directory(recorded), "deletable"))
        os.rmdir(recorded)
        os.symlink(other, recorded)
        result = self.judge(other)
        self.assertIsNone(result["record"])
        self.assertIsNone(result["judgment"])
        below = self.make_dir("user-home", "Library", "Caches", "other", "bar")
        self.assertIsNone(self.judge(below)["record"], "リンク先の下の項目にも記録を使わないこと")

    def test_record_whose_parent_is_replaced_by_a_symlink_is_not_used(self):
        """記録したディレクトリの親が後でシンボリックリンクに置き換わっても、リンク先の別のディレクトリに記録を使わない (KTD16)。"""
        recorded = self.make_dir("user-home", "Library", "Caches", "foo", "sub")
        other_sub = self.make_dir("user-home", "Library", "Caches", "other", "sub")
        self.assert_ok(self.add_user(directory(recorded), "deletable"))
        parent = os.path.dirname(recorded)
        os.rmdir(recorded)
        os.rmdir(parent)
        os.symlink(os.path.dirname(other_sub), parent)
        self.assertTrue(os.path.samefile(recorded, other_sub), "記録のパスが、リンク先のディレクトリを指すこと")
        result = self.judge(other_sub)
        self.assertIsNone(result["record"])
        self.assertIsNone(result["judgment"])

    def test_record_matching_the_path_is_replaced_before_one_matching_the_identity(self):
        """パスの文字列で一致する記録を、識別子で一致する記録より先に置き換える。同じパスの記録が 2 つにならない (KTD16)。"""
        recorded = self.make_dir("user-home", "Library", "Caches", "foo")
        other = self.make_dir("user-home", "Library", "Caches", "other")
        self.assert_ok(self.add_user(directory(recorded), "deletable"))
        self.assert_ok(self.add_user(directory(other)))
        os.rmdir(recorded)
        os.symlink(other, recorded)
        self.assert_ok(self.add_user(directory(other), reason="2 回目"))
        stored = {record["target"]["path"]: record for record in self.stored()}
        self.assertEqual(sorted(stored), sorted([recorded, other]))
        self.assertEqual(stored[other]["reason"], "2 回目")
        self.assertEqual(stored[recorded]["judgment"], "deletable")

    def test_path_match_comes_before_identity_match(self):
        """識別子だけで一致する記録が先に並んでいても、パスの文字列で一致する記録を置き換える (KTD16)。

        書き方の違う同じディレクトリの記録が 2 つある records.json (手で書き換えたもの) を、
        test_same_identity_with_a_different_path_is_replaced と同じ方法で作る。
        """
        target = self.make_dir("user-home", "Library", "Caches", "foo")
        link = os.path.join(self.user_home, "foo-link")
        os.symlink(target, link)
        stored = [{"target": directory(path), "judgment": "keep", "decided_by": "user", "decided_on": TODAY,
                   "reason": reason, "impact": None, "basis": [], "command": None, "process_names": []}
                  for path, reason in ((link, "書き方の違う記録"), (target, "パスの文字列で一致する記録"))]
        self.write_home(records.RECORDS, {"version": 1, "records": stored})
        with mock.patch.object(records.os.path, "realpath", os.path.abspath), \
                mock.patch.object(judge.os.path, "realpath", os.path.abspath):
            self.assert_ok(self.add_user(directory(target), reason="2 回目"))
        reasons = {record["target"]["path"]: record["reason"] for record in self.stored()}
        self.assertEqual(reasons, {link: "書き方の違う記録", target: "2 回目"})


class UserRecordTest(RecordsCase):
    """利用者の記録 (R18・R21)。"""

    def test_user_review_is_rejected(self):
        """利用者の記録として「確認が要る」を渡すと記録しない。"""
        target = self.make_dir("user-home", "Library", "Caches", "foo")
        self.assert_unsatisfied(self.add_user(directory(target), "review"), "review")
        self.assertFalse(os.path.exists(os.path.join(self.home, records.RECORDS)))

    def test_user_deletable_is_recorded_for_directories(self):
        """利用者の「消してよい」は、削除のシェルスクリプトを作るとき (U7) にディレクトリだけに記録する。"""
        target = self.make_dir("user-home", "Library", "Caches", "foo")
        record = self.assert_ok(self.add_user(directory(target), "deletable"))["record"]
        self.assertEqual(record["judgment"], "deletable")
        self.assert_unsatisfied(self.add_user({"kind": "docker-volume", "name": "data"}, "deletable"))

    def test_protected_location_is_not_recorded(self):
        """保護の一覧の場所には、「消してよい」も「残す」も記録せず、理由を返す (記録は保護の一覧より優先しない)。"""
        for path in (self.claude, os.path.join(self.claude, "projects"), self.caches):
            os.makedirs(path, exist_ok=True)
            for judgment in ("deletable", "keep"):
                with self.subTest(path=path, judgment=judgment):
                    self.assert_unsatisfied(self.add_user(directory(path), judgment), "保護の一覧")
        self.assertFalse(os.path.exists(os.path.join(self.home, records.RECORDS)))

    def test_fields(self):
        target = self.make_dir("user-home", "Library", "Caches", "foo")
        record = self.assert_ok(self.add_user(directory(target), reason="設定を含む"))["record"]
        self.assertEqual(record, {"target": directory(target), "judgment": "keep", "decided_by": "user",
                                  "decided_on": TODAY, "reason": "設定を含む", "impact": None, "basis": [],
                                  "command": None, "process_names": []})
        self.assertEqual(self.read_home(records.RECORDS)["version"], 1)

    def test_docker_and_asdf_targets(self):
        """Docker の 3 種類のキーと、asdf のツールと版のキーで、記録して検索できる。"""
        targets = [{"kind": "docker-volume", "name": "mysql-data"},
                   {"kind": "docker-compose-project", "name": "myapp"},
                   {"kind": "docker-image-repository", "name": "ghcr.io/org/app"},
                   {"kind": "docker-image-repository", "name": "localhost:5000/app"},
                   {"kind": "asdf-version", "tool": "nodejs", "version": "22.11.0"},
                   {"kind": "asdf-version", "tool": "golang", "version": "ref-v1.2.3"}]
        for target in targets:
            self.assert_ok(records.add_user(target, "keep", today=TODAY))
        stored = records.load()
        self.assertEqual(len(stored), len(targets))
        for target in targets:
            with self.subTest(target=target):
                self.assertEqual(records.find(stored, target)["target"], target)
        self.assertIsNone(records.find(stored, {"kind": "docker-volume", "name": "other"}))
        self.assertIsNone(records.find(stored, {"kind": "asdf-version", "tool": "nodejs", "version": "20.0.0"}))
        self.assertIsNone(records.find(stored, {"kind": "docker-compose-project", "name": "mysql-data"}),
                          "種類が違えば別の対象")

    def test_invalid_names(self):
        for target in ({"kind": "docker-volume", "name": "a"}, {"kind": "docker-volume", "name": "-x"},
                       {"kind": "docker-compose-project", "name": "MyApp"},
                       {"kind": "docker-image-repository", "name": "app:latest"},
                       {"kind": "docker-image-repository", "name": "app@sha256:00"},
                       {"kind": "docker-image-repository", "name": "a b"},
                       {"kind": "asdf-version", "tool": "node/js", "version": "1"},
                       {"kind": "asdf-version", "tool": "nodejs", "version": ".."},
                       {"kind": "asdf-version", "tool": "nodejs"},
                       {"kind": "docker-volume", "name": "data", "path": "/x"},
                       {"kind": "volume", "name": "data"},
                       {"kind": ["docker-volume"], "name": "data"},
                       {"kind": {"docker-volume": 1}, "name": "data"},
                       {"kind": None, "name": "data"}):
            with self.subTest(target=target):
                self.assert_unsatisfied(records.add_user(target, "keep", today=TODAY))

    def test_user_replaces_claude_record(self):
        """利用者の記録が Claude の記録を置き換えるときは、判定・だれ・日付だけを変え、ほかを残す (R21)。"""
        target = self.make_dir("user-home", "Library", "Caches", "foo")
        command = tool("uv", "cache", "prune", "--cache-dir", "{path}")
        self.assert_ok(self.add_claude(target, claude_input(command=command, process_names=["Foo"])))
        record = self.assert_ok(records.add_user(directory(target), "deletable", env=self.env,
                                                 today="2026-12-01"))["record"]
        self.assertEqual(record, {"target": directory(target), "judgment": "deletable", "decided_by": "user",
                                  "decided_on": "2026-12-01", "reason": "Claude が調べた理由",
                                  "impact": "Claude が調べた影響", "basis": ["https://example.com/docs"],
                                  "command": command, "process_names": ["Foo"]})
        record = self.assert_ok(self.add_user(directory(target), reason="利用者の理由"))["record"]
        self.assertEqual(record["reason"], "利用者の理由", "利用者が理由を言ったときは、その理由にすること")
        self.assertEqual(record["command"], command)


class ClaudeRecordTest(RecordsCase):
    """Claude の判定の記録 (R20)。"""

    def setUp(self):
        super().setUp()
        self.target = self.make_dir("user-home", "Library", "Caches", "foo")

    def test_fields(self):
        command = tool("brew", "cleanup", env={"HOMEBREW_CACHE": "{path}"})
        record = self.assert_ok(self.add_claude(self.target, claude_input("deletable", command=command)))["record"]
        self.assertEqual(record, {"target": directory(self.target), "judgment": "deletable", "decided_by": "claude",
                                  "decided_on": TODAY, "reason": "Claude が調べた理由", "impact": "Claude が調べた影響",
                                  "basis": ["https://example.com/docs"], "command": command, "process_names": []})

    def test_review_can_be_recorded(self):
        self.assertEqual(self.assert_ok(self.add_claude(self.target, claude_input("review")))["record"]["judgment"],
                         "review")

    def test_basis_is_required(self):
        for basis in ([], [""], None, "https://example.com"):
            with self.subTest(basis=basis):
                self.assert_unsatisfied(self.add_claude(self.target, claude_input(basis=basis)), "basis")
        self.assertFalse(os.path.exists(os.path.join(self.home, records.RECORDS)))

    def test_input_shape(self):
        """知らないキー (パスを含む)・無いキー・判定の誤り・keep のコマンドは誤りにする。"""
        cases = [(claude_input(path=self.target), "path"),
                 ({k: v for k, v in claude_input().items() if k != "reason"}, "reason"),
                 (claude_input(judgment="maybe"), "judgment"),
                 (claude_input("keep", command={"type": "rm"}), "command"),
                 (claude_input("review", command=None), "command"),
                 (claude_input(process_names=["a/b"]), "process_names")]
        for data, fragment in cases:
            with self.subTest(data=data):
                self.assert_unsatisfied(self.add_claude(self.target, data), fragment)

    def test_command_is_checked(self):
        """Claude が書いたコマンドは、R16 で検査する。"""
        self.assert_unsatisfied(self.add_claude(self.target, claude_input(command=tool("rm", "-rf", "{path}"))),
                                "許可していない実行ファイル")
        self.assert_unsatisfied(self.add_claude(self.target, claude_input(command=tool("brew", "cleanup", "a;b"))),
                                "特殊文字")

    def test_claude_does_not_replace_user_record(self):
        """Claude の判定は、利用者の記録がある対象には記録しない (R20)。"""
        self.assert_ok(self.add_user(directory(self.target)))
        self.assert_unsatisfied(self.add_claude(self.target, claude_input()), "利用者の記録")
        self.assertEqual(self.stored()[0]["decided_by"], "user")

    def test_claude_replaces_claude_record(self):
        self.assert_ok(self.add_claude(self.target, claude_input("review")))
        self.assert_ok(self.add_claude(self.target, claude_input("deletable")))
        self.assertEqual([r["judgment"] for r in self.stored()], ["deletable"])

    def test_protected_location_is_not_recorded(self):
        self.assert_unsatisfied(self.add_claude(self.claude, claude_input()), "保護の一覧")


class CorruptRecordsTest(RecordsCase):
    """壊れた records.json があると、書き込まずに理由を返す (R22・KTD2)。"""

    def setUp(self):
        super().setUp()
        self.target = self.make_dir("user-home", "Library", "Caches", "foo")

    def assert_untouched(self, text, call):
        self.write_home_text(records.RECORDS, text)
        before = self.home_files()
        result = call()
        self.assert_unsatisfied(result, records.RECORDS)
        self.assertEqual(self.home_files(), before, "ファイルを変えないこと")

    def broken_texts(self):
        valid = {"target": directory(self.target), "judgment": "keep", "decided_by": "user", "decided_on": TODAY,
                 "reason": None, "impact": None, "basis": [], "command": None, "process_names": []}
        return {
            "JSON でない": "{",
            "version が違う": json.dumps({"version": 2, "records": []}),
            "records が無い": json.dumps({"version": 1}),
            "知らないキー": json.dumps({"version": 1, "records": [], "extra": 1}),
            "記録の知らないキー": json.dumps({"version": 1, "records": [{**valid, "note": "x"}]}),
            "利用者の review": json.dumps({"version": 1, "records": [{**valid, "judgment": "review"}]}),
            "Claude の根拠が無い": json.dumps({"version": 1, "records": [{**valid, "decided_by": "claude",
                                                                         "reason": "r", "impact": "i"}]}),
            "相対パス": json.dumps({"version": 1, "records": [{**valid, "target": directory("foo")}]}),
            "kind が配列": json.dumps({"version": 1, "records": [{**valid, "target": {"kind": ["directory"],
                                                                                    "path": self.target}}]}),
            "kind がオブジェクト": json.dumps({"version": 1, "records": [{**valid, "target": {"kind": {"a": 1},
                                                                                        "path": self.target}}]}),
            "日付でない": json.dumps({"version": 1, "records": [{**valid, "decided_on": "2026-13-01"}]}),
            "同じ対象が 2 つ": json.dumps({"version": 1, "records": [valid, valid]}),
        }

    def test_add_user_and_add_claude(self):
        for name, text in self.broken_texts().items():
            with self.subTest(name=name):
                self.assert_untouched(text, lambda: self.add_user(directory(self.target)))
                self.assert_untouched(text, lambda: self.add_claude(self.target, claude_input()))

    def test_list_and_remove(self):
        for name, text in self.broken_texts().items():
            with self.subTest(name=name):
                self.assert_untouched(text, records.list_records)
                self.assert_untouched(text, lambda: records.remove("0" * 16, [1]))

    def test_load_raises(self):
        self.write_home_text(records.RECORDS, "{")
        with self.assertRaises(store.Corrupt):
            records.load()

    def test_claude_command_that_fails_the_check_is_not_corrupt(self):
        """記録の後に検査に合わなくなったコマンド (組を外した版など) は、壊れているとしない。検査は U7 でもう一度行う (R20)。"""
        record = {"target": directory(self.target), "judgment": "deletable", "decided_by": "claude",
                  "decided_on": TODAY, "reason": "r", "impact": "i", "basis": ["b"],
                  "command": tool("rustup", "run", "stable", "x"), "process_names": []}
        self.write_home(records.RECORDS, {"version": 1, "records": [record]})
        self.assertEqual(records.load(), [record])


class ListAndRemoveTest(RecordsCase):
    """記録の一覧と、番号での削除 (R22・KTD16)。"""

    def setUp(self):
        super().setUp()
        self.b = self.make_dir("user-home", "Library", "Caches", "b")
        self.a = self.make_dir("user-home", "Library", "Caches", "a")
        self.assert_ok(records.add_user({"kind": "asdf-version", "tool": "nodejs", "version": "22.0.0"}, "keep",
                                        today=TODAY))
        self.assert_ok(records.add_user({"kind": "docker-volume", "name": "zz-data"}, "keep", today=TODAY))
        self.assert_ok(records.add_user({"kind": "docker-compose-project", "name": "app"}, "keep", today=TODAY))
        self.assert_ok(self.add_user(directory(self.b)))
        self.assert_ok(self.add_user(directory(self.a)))

    def test_order_and_numbers(self):
        """対象の種類の順 (ディレクトリ・Docker・asdf)、同じ種類の中ではパスか名前の順に、1 から番号を付ける。"""
        listed = self.assert_ok(records.list_records())
        self.assertEqual([(r["number"], r["display"]) for r in listed["records"]],
                         [(1, "~/Library/Caches/a"), (2, "~/Library/Caches/b"), (3, "zz-data"), (4, "app"),
                          (5, "nodejs 22.0.0")])
        self.assertEqual(listed["records"][0]["target"], directory(self.a))
        self.assertRegex(listed["listing"], r"\A[0-9a-f]{16}\Z")

    def test_empty(self):
        os.remove(os.path.join(self.home, records.RECORDS))
        listed = self.assert_ok(records.list_records())
        self.assertEqual(listed["records"], [])

    def test_remove_by_number(self):
        listing = records.list_records()["listing"]
        result = self.assert_ok(records.remove(listing, [2, 5, 2]))
        self.assertEqual([r["display"] for r in result["removed"]], ["~/Library/Caches/b", "nodejs 22.0.0"])
        self.assertEqual([r["display"] for r in records.list_records()["records"]],
                         ["~/Library/Caches/a", "zz-data", "app"])

    def test_out_of_range_removes_nothing(self):
        """範囲の外の番号が 1 つでもあれば、何も消さずに理由を返す。"""
        listing = records.list_records()["listing"]
        before = self.home_files()
        for numbers in ([6], [1, 6], [0]):
            with self.subTest(numbers=numbers):
                self.assert_unsatisfied(records.remove(listing, numbers), "範囲")
        self.assertEqual(self.home_files(), before)

    def test_changed_after_listing_removes_nothing(self):
        """一覧を示した後に記録が変わっていれば、何も消さない (一覧の ID が違う)。"""
        listing = records.list_records()["listing"]
        self.assert_ok(records.add_user({"kind": "docker-volume", "name": "aa-data"}, "keep", today=TODAY))
        before = self.home_files()
        self.assert_unsatisfied(records.remove(listing, [3]), "records list")
        self.assertEqual(self.home_files(), before)


class JudgeWithRecordsTest(RecordsCase):
    """判定の順 (R13・R19) に、記録と、使われているかどうかによる判定を入れる。"""

    def setUp(self):
        super().setUp()
        self.xcode = self.make_dir("user-home", "Library", "Developer", "Xcode")
        self.support = self.make_dir("user-home", "Library", "Developer", "Xcode", "iOS DeviceSupport")
        self.version = self.make_dir("user-home", "Library", "Developer", "Xcode", "iOS DeviceSupport", "17.0")
        self.rows = [row("~/Library/Developer/Xcode/iOS DeviceSupport", "review")]

    def test_own_record(self):
        target = self.make_dir("user-home", "Library", "Caches", "foo")
        self.assert_ok(self.add_claude(target, claude_input("deletable", process_names=["Foo"])))
        result = self.judge(target)
        self.assertEqual(result["judgment"], "deletable")
        self.assertEqual(result["source"], "record")
        self.assertEqual(result["record"], {"path": target, "decided_by": "claude", "decided_on": TODAY,
                                            "judgment": "deletable"})
        self.assertEqual(result["reason"], "Claude が調べた理由")
        self.assertEqual(result["impact"], "Claude が調べた影響")
        self.assertEqual(result["command"], {"type": "rm", "path": target})
        self.assertEqual(result["process_names"], ["Foo"])

    def test_record_applies_below_and_a_closer_record_wins(self):
        """ディレクトリの記録は下の階層にも適用され、下の階層に別の記録があればそれを使う (R19)。"""
        parent = self.make_dir("user-home", "Library", "Caches", "foo")
        child = self.make_dir("user-home", "Library", "Caches", "foo", "bar")
        grandchild = self.make_dir("user-home", "Library", "Caches", "foo", "bar", "baz")
        self.assert_ok(self.add_claude(parent, claude_input("deletable")))
        self.assert_ok(self.add_claude(child, claude_input("review")))
        below_parent = self.make_dir("user-home", "Library", "Caches", "foo", "other")
        result = self.judge(below_parent)
        self.assertEqual(result["judgment"], "deletable")
        self.assertEqual(result["record"]["path"], parent)
        self.assertIn(parent, result["reason"])
        self.assertEqual(result["command"], {"type": "rm", "path": below_parent}, "下の項目そのものを rm で消すこと")
        self.assertEqual(self.judge(grandchild)["judgment"], "review")
        self.assertEqual(self.judge(grandchild)["record"]["path"], child)

    def test_table_row_between_the_record_and_the_item_wins(self):
        """親の「消してよい」の記録より、記録のディレクトリと項目の間にある判定表の行を使う (R13)。"""
        self.assert_ok(self.add_claude(self.xcode, claude_input("deletable")))
        for path in (self.support, self.version):
            with self.subTest(path=path):
                result = self.judge(path, self.rows)
                self.assertEqual(result["judgment"], "review")
                self.assertEqual(result["source"], "table")

    def test_record_on_the_matched_directory_itself_wins_below(self):
        """記録のディレクトリそのものに一致する判定表の行は、「間にある」行に入らない (2026-11-27 に利用者が決めた)。"""
        self.assert_ok(self.add_user(directory(self.support), "deletable"))
        result = self.judge(self.version, self.rows)
        self.assertEqual(result["judgment"], "deletable")
        self.assertEqual(result["source"], "record")
        self.assertEqual(result["impact"], "~/Library/Developer/Xcode/iOS DeviceSupport の影響",
                         "記録に影響が無ければ、項目に使う判定表の行の影響を使うこと")

    def test_keep_record_of_a_parent_wins_over_table(self):
        """親の「残す」の記録は、子の判定表の行より優先する。"""
        self.assert_ok(self.add_user(directory(self.xcode)))
        for path in (self.support, self.version):
            with self.subTest(path=path):
                result = self.judge(path, self.rows)
                self.assertEqual(result["judgment"], "keep")
                self.assertEqual(result["source"], "record")
                self.assertIsNone(result["command"])

    def test_own_record_wins_over_table(self):
        """記録は判定表より優先する。記録にコマンドが無ければ、項目に使う判定表の行のコマンドを使う。"""
        go_build = self.make_dir("user-home", "Library", "Caches", "go-build")
        rows = [row("~/Library/Caches/go-build", "review", command=tool("go", "clean", "-cache",
                                                                         env={"GOCACHE": "{path}"}))]
        self.assert_ok(self.add_user(directory(go_build), "deletable"))
        result = self.judge(go_build, rows)
        self.assertEqual(result["judgment"], "deletable")
        self.assertEqual(result["source"], "record")
        self.assertEqual(result["command"], {"type": "tool", "args": ["go", "clean", "-cache"],
                                             "env": {"GOCACHE": go_build}})
        self.assert_ok(self.add_user(directory(go_build), "keep"))
        result = self.judge(go_build, rows)
        self.assertEqual(result["judgment"], "keep")
        self.assertIsNone(result["command"])

    def test_protection_comes_before_records(self):
        """記録は保護の一覧より優先しない (記録のファイルに直接書いた記録でも)。"""
        record = {"target": directory(self.claude), "judgment": "deletable", "decided_by": "user",
                  "decided_on": TODAY, "reason": None, "impact": None, "basis": [], "command": None,
                  "process_names": []}
        self.write_home(records.RECORDS, {"version": 1, "records": [record]})
        result = self.judge(self.claude)
        self.assertEqual(result["judgment"], "keep")
        self.assertEqual(result["source"], "protected")

    def test_record_with_a_tool_command_keeps_items_below(self):
        """Claude が書いたツールのコマンドがある記録の下の項目は「残す」(R19)。記録の項目には {path} を置き換えたコマンド。"""
        target = self.make_dir("user-home", "Library", "Caches", "foo")
        below = self.make_dir("user-home", "Library", "Caches", "foo", "bar")
        command = tool("uv", "cache", "prune", "--cache-dir", "{path}")
        self.assert_ok(self.add_claude(target, claude_input("deletable", command=command)))
        self.assertEqual(self.judge(target)["command"],
                         {"type": "tool", "args": ["uv", "cache", "prune", "--cache-dir", target], "env": {}})
        result = self.judge(below)
        self.assertEqual(result["judgment"], "keep")
        self.assertIsNone(result["command"])
        self.assertIn("uv cache prune", result["reason"])

    def test_record_deleted_by_a_table_tool_command_keeps_items_below(self):
        """記録にコマンドが無く、記録のディレクトリそのものに一致する判定表の行にツールのコマンドがあれば、下の項目は「残す」(R19)。"""
        device = self.make_dir("user-home", "Library", "Developer", "CoreSimulator", "Devices", UDID)
        data = self.make_dir("user-home", "Library", "Developer", "CoreSimulator", "Devices", UDID, "data")
        rows = [row("~/Library/Developer/CoreSimulator/Devices/*", command=tool("xcrun", "simctl", "delete", "{name}"))]
        self.assert_ok(self.add_user(directory(device), "deletable"))
        self.assertEqual(self.judge(device, rows)["command"],
                         {"type": "tool", "args": ["xcrun", "simctl", "delete", UDID], "env": {}})
        result = self.judge(data, rows)
        self.assertEqual(result["judgment"], "keep")
        self.assertEqual(result["source"], "record")
        self.assertIsNone(result["command"])
        self.assertIn(f"判定表の行のツールのコマンド (xcrun simctl delete {UDID})", result["reason"])

    def test_record_on_a_device_whose_name_is_not_a_udid_is_kept(self):
        """記録で判定が決まる項目も、判定表の行の {name} を置き換えられなければ「残す」にする (R16)。"""
        device = self.make_dir("user-home", "Library", "Developer", "CoreSimulator", "Devices", "all")
        rows = [row("~/Library/Developer/CoreSimulator/Devices/*", command=tool("xcrun", "simctl", "delete", "{name}"))]
        self.assert_ok(self.add_user(directory(device), "deletable"))
        result = self.judge(device, rows)
        self.assertEqual(result["judgment"], "keep")
        self.assertEqual(result["source"], "record")
        self.assertIsNone(result["command"])
        self.assertIn("端末の UDID", result["reason"])

    def test_claude_record_with_simctl_needs_a_udid_name(self):
        """Claude が xcrun simctl delete {name} を書くときは、項目の名前が端末の UDID の形でなければ記録しない (R16)。"""
        command = tool("xcrun", "simctl", "delete", "{name}")
        target = self.make_dir("user-home", "Library", "Caches", "all")
        self.assert_unsatisfied(self.add_claude(target, claude_input("deletable", command=command)), "端末の UDID")
        device = self.make_dir("user-home", "Library", "Caches", UDID)
        self.assert_ok(self.add_claude(device, claude_input("deletable", command=command)))

    def test_record_below_a_table_tool_row_is_deleted_with_rm(self):
        """ツールのコマンドの行に一致したディレクトリより下の記録では、記録のディレクトリとその下の項目を rm で消す (R19)。

        記録のディレクトリそのものに一致する行が無いため。利用者が、一覧で「残す」と示されたディレクトリを選んで消すと決めたもの。
        """
        sub = self.make_dir("user-home", "Library", "Developer", "CoreSimulator", "Devices", UDID, "sub")
        below = self.make_dir("user-home", "Library", "Developer", "CoreSimulator", "Devices", UDID, "sub", "x")
        rows = [row("~/Library/Developer/CoreSimulator/Devices/*", command=tool("xcrun", "simctl", "delete", "{name}"))]
        self.assert_ok(self.add_user(directory(sub), "deletable"))
        for path in (sub, below):
            with self.subTest(path=path):
                result = self.judge(path, rows)
                self.assertEqual(result["judgment"], "deletable")
                self.assertEqual(result["command"], {"type": "rm", "path": path})

    def test_user_record_without_reason(self):
        target = self.make_dir("user-home", "Library", "Caches", "foo")
        self.assert_ok(self.add_user(directory(target)))
        result = self.judge(target)
        self.assertIn("利用者", result["reason"])
        self.assertIn(TODAY, result["reason"])

    def test_usage_comes_after_keep_records_and_before_other_records(self):
        """使われているかどうかによる判定は、「残す」の記録の後、ほかの記録の前 (R13)。記録の「消してよい」では変えない。"""
        target = self.make_dir("user-home", "Library", "Caches", "foo")
        used = {"judgment": "review", "reason": "参照されている", "impact": "影響", "command": {"type": "rm", "path": target},
                "process_names": []}
        self.assert_ok(self.add_user(directory(target), "deletable"))
        result = self.judge(target, usage=lambda path: used)
        self.assertEqual(result["judgment"], "review")
        self.assertEqual(result["source"], "usage")
        self.assertEqual(result["reason"], "参照されている")
        self.assertEqual(self.judge(target, usage=lambda path: None)["judgment"], "deletable",
                         "使われているかどうかで決まらない項目は、記録の判定にすること")
        self.assert_ok(self.add_user(directory(target), "keep"))
        result = self.judge(target, usage=lambda path: used)
        self.assertEqual(result["judgment"], "keep")
        self.assertEqual(result["source"], "record")

    def test_record_with_the_same_identity_is_used(self):
        """記録のパスと項目のパスの文字列が違っても、ディレクトリの識別子が同じなら記録を使う (KTD16)。"""
        target = self.make_dir("user-home", "Library", "Caches", "foo")
        link = os.path.join(self.user_home, "foo-link")
        os.symlink(target, link)
        self.assert_ok(self.add_user(directory(target)))
        index = judge.DirectoryRecords(records.load())
        with mock.patch.object(judge.os.path, "realpath", os.path.abspath):
            result = judge.judge(os.path.join(link, "bar"), self.env, [], records=index)
        self.assertEqual(result["judgment"], "keep")
        self.assertEqual(result["source"], "record")

    def test_no_records(self):
        """記録を渡さなければ、U3 と同じく保護の一覧と判定表だけで決める。"""
        self.assertEqual(judge.judge(self.version, self.env, self.rows)["source"], "table")


class CliTest(RecordsCase):
    """サブコマンド records list・records add・records remove (入口のファイル disk_usage_triage.py)。"""

    def setUp(self):
        super().setUp()
        self.write_home("config.json", {"version": 1, "scan_dirs": ["~/Library/Caches"],
                                        "project_dirs": ["~/workspace"], "timeout_seconds": 300})
        self.target = self.make_dir("user-home", "Library", "Caches", "foo")

    def write_input(self, data):
        path = os.path.join(self.home, "inputs", "records-add.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        return path

    def test_add_list_remove(self):
        code, payload, _ = self.cli("records", "add", "--input-file",
                                    self.write_input({"target": directory("~/Library/Caches/foo"), "judgment": "keep",
                                                      "reason": "設定を含む"}))
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["record"]["target"], directory(self.target))
        self.assertEqual(payload["display"], "~/Library/Caches/foo")
        self.assertIsNone(payload["previous"])
        self.assertEqual(payload["errors"], [])
        code, listed, _ = self.cli("records", "list")
        self.assertEqual(code, 0)
        self.assertEqual([r["display"] for r in listed["records"]], ["~/Library/Caches/foo"])
        self.assertEqual(listed["path"], os.path.join(self.home, records.RECORDS))
        code, removed, _ = self.cli("records", "remove", "--listing", listed["listing"], "1")
        self.assertEqual(code, 0, removed)
        self.assertEqual([r["display"] for r in removed["removed"]], ["~/Library/Caches/foo"])
        self.assertEqual(self.cli("records", "list")[1]["records"], [])

    def test_add_rejects_other_judgments_and_unknown_keys(self):
        for data in ({"target": directory(self.target), "judgment": "deletable"},
                     {"target": directory(self.target), "judgment": "keep", "decided_by": "user"},
                     {"target": directory(self.target)},
                     {"target": directory(self.target), "judgment": "keep", "reason": ""},
                     {"target": {"kind": ["directory"], "path": self.target}, "judgment": "keep"},
                     [1]):
            with self.subTest(data=data):
                code, payload, _ = self.cli("records", "add", "--input-file", self.write_input(data))
                self.assertEqual(code, 3)
                self.assertTrue(payload["errors"])
                self.assertIsNone(payload["record"])
        self.assertFalse(os.path.exists(os.path.join(self.home, records.RECORDS)))

    def test_add_without_config(self):
        """ディレクトリの記録には設定が要る (調べるディレクトリが保護の一覧に入るため)。Docker と asdf には要らない。"""
        os.remove(os.path.join(self.home, "config.json"))
        code, payload, _ = self.cli("records", "add", "--input-file",
                                    self.write_input({"target": directory(self.target), "judgment": "keep"}))
        self.assertEqual(code, 3)
        self.assertTrue(any("config.json" in error for error in payload["errors"]))
        code, payload, _ = self.cli("records", "add", "--input-file",
                                    self.write_input({"target": {"kind": "docker-volume", "name": "data"},
                                                      "judgment": "keep"}))
        self.assertEqual(code, 0, payload)

    def test_add_with_corrupt_config(self):
        self.write_home_text("config.json", "{")
        code, payload, _ = self.cli("records", "add", "--input-file",
                                    self.write_input({"target": directory(self.target), "judgment": "keep"}))
        self.assertEqual(code, 3)
        self.assertTrue(any("config.json" in error for error in payload["errors"]))

    def test_corrupt_records_exit_3(self):
        """壊れた records.json があると、records add・records remove は書き込まずに、records list も終了コード 3 で返す。"""
        self.write_home_text(records.RECORDS, "{")
        before = self.home_files()
        for args in (("records", "list"), ("records", "remove", "--listing", "0" * 16, "1"),
                     ("records", "add", "--input-file",
                      self.write_input({"target": directory(self.target), "judgment": "keep"}))):
            with self.subTest(args=args[:2]):
                before = self.home_files()
                code, payload, _ = self.cli(*args)
                self.assertEqual(code, 3)
                self.assertTrue(any(records.RECORDS in error for error in payload["errors"]))
                self.assertEqual(self.home_files(), before)

    def test_remove_out_of_range(self):
        self.cli("records", "add", "--input-file", self.write_input({"target": directory(self.target),
                                                                       "judgment": "keep"}))
        listing = self.cli("records", "list")[1]["listing"]
        code, payload, _ = self.cli("records", "remove", "--listing", listing, "1", "2")
        self.assertEqual(code, 3)
        self.assertEqual(payload["removed"], [])
        self.assertEqual(len(self.cli("records", "list")[1]["records"]), 1)

    def test_missing_input_file(self):
        code, payload, _ = self.cli("records", "add", "--input-file", os.path.join(self.home, "inputs", "missing.json"))
        self.assertEqual(code, 3)
        self.assertTrue(payload["errors"])


if __name__ == "__main__":
    unittest.main()
