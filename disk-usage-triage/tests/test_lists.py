#!/usr/bin/env python3
"""トリアージ・一覧・選んだ項目 (ファイル `disk-usage-triage/scripts/disk_usage_triage/lists.py`) のテスト (計画
docs/plans/2026-11-22-1630-feat-disk-usage-triage-plan.md の U6)。

偽の du (ファイル `disk-usage-triage/tests/fakebin/du`) で調べた結果から一覧を作り、サブコマンド run start・scan・list show・
select add・select remove・select show・judge set と、records add の引数 --run・--item を、入口のファイルをサブプロセスで
実行して検査する。

  python3 -m unittest discover -s disk-usage-triage/tests
"""

import datetime
import json
import os
import re
import unittest

from fakedu_case import FakeDuCase, du_args

from disk_usage_triage import lists  # noqa: E402

KIB = 1024
TODAY = datetime.date.today().isoformat()


def user_record(path, judgment, decided_on="2026-11-27"):
    """records.json の、利用者の記録。"""
    return {"target": {"kind": "directory", "path": path}, "judgment": judgment, "decided_by": "user",
            "decided_on": decided_on, "reason": None, "impact": None, "basis": [], "command": None, "process_names": []}


REVIEW_INPUT = {"judgment": "review", "reason": "アプリ Example のキャッシュで、ログインの情報も含む",
                "impact": "次にアプリを起動したときに、ログインし直す",
                "basis": ["https://example.com/docs/cache", "中にファイル Cookies があることを確認した"],
                "command": {"type": "rm"}}


class ListsCase(FakeDuCase):
    """調べるディレクトリ ~/Library/Caches と ~/Library/Developer の設定で始める。"""

    def setUp(self):
        super().setUp()
        self.caches = self.make_dir("user-home", "Library", "Caches")
        self.developer = self.make_dir("user-home", "Library", "Developer")
        self.inputs = self.make_dir("input")
        self.write_config(["~/Library/Caches", "~/Library/Developer"])

    def write_config(self, scan_dirs, timeout=30):
        self.write_home("config.json", {"version": 1, "scan_dirs": scan_dirs, "project_dirs": ["~"],
                                        "timeout_seconds": timeout})

    def write_records(self, *items):
        self.write_home("records.json", {"version": 1, "records": list(items)})

    def du(self, root, entries, *, total=None, stderr="", exit_code=0):
        """root を調べた du の応答の指定。entries は (名前, キロバイト) の配列。total を省くと entries の合計にする。"""
        lines = [f"{kib}\t{root}/{name}" for name, kib in entries]
        lines.append(f"{sum(kib for _, kib in entries) if total is None else total}\t{root}")
        return {"args": du_args(root), "stdout": "\n".join(lines) + "\n", "stderr": stderr, "exit": exit_code}

    def write_input(self, data, name="input.json"):
        path = os.path.join(self.inputs, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        return path

    def start(self):
        code, payload, stderr = self.cli("run", "start")
        self.assertEqual(code, 0, stderr)
        return payload["run"]

    def start_another(self):
        """2 つ目のトリアージを始める。同じ秒に始めたトリアージは作れないので (計画の KTD17)、時刻を 1 分後にする。"""
        later = datetime.datetime.now().astimezone() + datetime.timedelta(minutes=1)
        result = lists.run_start(now=later)
        self.assertEqual(result["status"], "ok", result["errors"])
        return result["run"]

    def scan_ok(self, run, *extra):
        code, payload, stderr = self.cli("scan", "--run", run, *extra)
        self.assertEqual(code, 0, stderr)
        self.assertEqual(payload["errors"], [])
        return payload

    def first_list(self, caches_entries, developer_entries=(), **caches_options):
        """調べるディレクトリ 2 つの偽の du の応答を決め、トリアージを始めて最初の一覧を作る。返り値は (ID, scan の出力)。"""
        self.du_responses([self.du(self.caches, caches_entries, **caches_options),
                           self.du(self.developer, list(developer_entries))])
        run = self.start()
        return run, self.scan_ok(run)

    def list_file(self, run, letter):
        return os.path.join(self.home, "runs", run, "lists", f"{letter}.json")

    def assert_unsatisfied(self, result, *fragments):
        code, payload, stderr = result
        self.assertEqual(code, 3, stderr)
        text = "\n".join(payload["errors"])
        for fragment in fragments:
            self.assertIn(fragment, text)
        return payload


def table_rows(table):
    """一覧の表の、データの行 (セルの配列)。"""
    return [[cell.strip() for cell in line.strip("|").split(" | ")] for line in table.splitlines()[2:]]


class SizeTest(unittest.TestCase):

    def test_format_size(self):
        """使用量の表示 (計画の R8)。1 GB は 1,000,000,000 バイトで、1 GB 以上は GB、未満は MB の小数 1 桁。"""
        self.assertEqual(lists.format_size(1_000_000_000), "1.0 GB")
        self.assertEqual(lists.format_size(999_000_000), "999.0 MB")
        self.assertEqual(lists.format_size(1_500_000_000), "1.5 GB")
        self.assertEqual(lists.format_size(0), "0.0 MB")


class RunStartTest(ListsCase):

    def test_creates_triage_directory(self):
        code, payload, stderr = self.cli("run", "start")
        self.assertEqual(code, 0, stderr)
        self.assertRegex(payload["run"], r"\A[0-9]{8}-[0-9]{6}\Z", "ID は始めた時刻 YYYYMMDD-HHMMSS (計画の KTD17)")
        self.assertTrue(os.path.isdir(os.path.join(self.home, "runs", payload["run"])))
        self.assertNotIn(os.path.join(self.home, "runs"), json.dumps(payload, ensure_ascii=False),
                         "出力にトリアージのディレクトリのパスを含めないこと (計画の KTD17)")

    def test_needs_config(self):
        os.remove(os.path.join(self.home, "config.json"))
        self.assert_unsatisfied(self.cli("run", "start"), "設定")
        self.assertFalse(os.path.exists(os.path.join(self.home, "runs")))

    def test_same_second_is_rejected(self):
        moment = datetime.datetime(2026, 11, 28, 15, 30, 12).astimezone()
        self.assertEqual(lists.run_start(now=moment)["run"], "20261128-153012")
        second = lists.run_start(now=moment)
        self.assertEqual(second["status"], "unsatisfied")
        self.assertIn("同じ秒", second["errors"][0])


class FirstListTest(ListsCase):

    def test_merges_scan_dirs_by_usage(self):
        """最初の一覧は、2 つの調べるディレクトリの項目をまとめて使用量の多い順に並べ、英字 A と番号 A1 から付ける (計画の R5・R9)。
        使用量が同じ項目は、パスの順にする。"""
        run, payload = self.first_list([("a", 100), ("b", 300)], [("c", 200), ("d", 300)])
        self.assertEqual(payload["letter"], "A")
        self.assertEqual(payload["source"], {"kind": "scan_dirs"})
        expected = [("A1", f"{self.caches}/b"), ("A2", f"{self.developer}/d"), ("A3", f"{self.developer}/c"),
                    ("A4", f"{self.caches}/a")]
        self.assertEqual([(item["number"], item["path"]) for item in payload["items"]], expected)
        rows = table_rows(payload["table"])
        self.assertEqual(payload["table"].splitlines()[0], "| 番号 | パス | 使用量 | 判定 | 理由 |", "列は計画の R6 のとおり")
        self.assertEqual(rows[0][:4], ["A1", "`~/Library/Caches/b`", "0.3 MB", "判定なし"])
        with open(self.list_file(run, "A"), encoding="utf-8") as f:
            stored = json.load(f)
        self.assertEqual([item["number"] for item in stored["items"]], [1, 2, 3, 4])
        self.assertNotIn("judgment", stored["items"][0], "一覧のファイルに判定を保存しないこと (計画の KTD17)")

    def test_more_than_30_items(self):
        """31 項目以上のときは、30 項目とその他の行になり、--all で残りも出る (計画の R7)。"""
        run, payload = self.first_list([(f"app{index:02d}", 1000 - index) for index in range(32)])
        self.assertEqual(len(payload["items"]), 30)
        self.assertEqual(payload["others"]["count"], 2)
        last = payload["table"].splitlines()[-1]
        self.assertEqual(last, f"| | その他 2 項目 | 合計 {lists.format_size((969 + 968) * KIB)} | | |")
        code, shown, stderr = self.cli("list", "show", "--run", run, "A", "--all")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(len(shown["items"]), 32)
        self.assertIsNone(shown["others"])
        self.assertNotIn("その他", shown["table"])

    def test_unreadable_notes(self):
        """読めなかったディレクトリを含む項目の番号 (表に示した分) と、その他の行の数を注記に示し、読めなかったパスそのものは
        示さない。どの項目にも入らない読めなかったパスの数も示す (計画の KTD4)。--unreadable で、読めなかったパスを出力する。"""
        entries = [(f"app{index:02d}", 1000 - index) for index in range(32)]
        stderr = (f"du: {self.caches}/app00/Data: Operation not permitted\n"
                  f"du: {self.caches}/app31/Data: Operation not permitted\n"
                  f"du: {self.caches}/hidden: Permission denied\n")
        run, payload = self.first_list(entries, stderr=stderr, exit_code=1)
        notes = "\n".join(payload["notes"])
        self.assertIn("読めなかったディレクトリを含む項目: A1。その他の行にも 1 項目ある。", notes)
        self.assertIn("どの項目にも入らない読めなかったディレクトリが 1 個ある", notes)
        self.assertNotIn("Data", notes + payload["table"], "読めなかったパスそのものは示さないこと")
        self.assertIsNone(payload["unreadable"])
        code, shown, err = self.cli("list", "show", "--run", run, "A", "--unreadable")
        self.assertEqual(code, 0, err)
        self.assertEqual(shown["unreadable"], {"items": [{"number": "A1", "display": "~/Library/Caches/app00",
                                                          "paths": ["~/Library/Caches/app00/Data"]}],
                                               "unmapped": ["~/Library/Caches/hidden"]})

    def test_direct_files_note(self):
        """調べたディレクトリごとに、使用量と、項目に入らない使用量 (直下のファイルなど) を注記に示す (計画の R5)。"""
        _, payload = self.first_list([("a", 1000)], [("c", 300)], total=3000)
        notes = payload["notes"]
        self.assertIn(f"`~/Library/Caches` は {lists.format_size(3000 * KIB)}。うち {lists.format_size(2000 * KIB)} は"
                      "項目に入らない (直下のファイルなど。du -d 1 はディレクトリだけを項目にするため)。", notes)
        self.assertIn(f"`~/Library/Developer` は {lists.format_size(300 * KIB)}。", notes, "差が無ければ示さない")

    def test_partial_failure(self):
        """結果を出せなかった調べるディレクトリは、一覧に入れず理由を注記に示し、ほかのディレクトリの一覧を作る (計画の R4)。"""
        self.write_config(["~/Library/Caches", "~/Library/Developer"], timeout=1)
        self.du_responses([self.du(self.caches, [("a", 100)]), {"args": du_args(self.developer), "hang": True}])
        run = self.start()
        payload = self.scan_ok(run)
        self.assertEqual([item["path"] for item in payload["items"]], [f"{self.caches}/a"])
        self.assertIn("`~/Library/Developer` は一覧に入れていない (時間の上限 (1 秒) までに du が完了しなかった)。",
                      payload["notes"])

    def test_all_failed(self):
        """どの調べるディレクトリも結果を出せなければ、一覧を作らない (計画の R4)。"""
        self.du_responses([self.du(self.caches, [], stderr="du: broken\n", exit_code=2),
                           self.du(self.developer, [], stderr="du: broken\n", exit_code=2)])
        run = self.start()
        payload = self.assert_unsatisfied(self.cli("scan", "--run", run), "どの調べるディレクトリも結果を出せなかった")
        self.assertIsNone(payload["letter"])
        self.assertFalse(os.path.exists(self.list_file(run, "A")))

    def test_judgment_and_command_from_table(self):
        """判定は判定表から求め、影響と消すコマンドは出力の項目にだけ含める (計画の R6)。"""
        _, payload = self.first_list([("Homebrew", 300), ("go-build", 200)])
        homebrew, go_build = payload["items"]
        self.assertEqual(homebrew["judgment"], "deletable")
        self.assertEqual(homebrew["judgment_label"], "消してよい")
        self.assertEqual(homebrew["command_text"], f"rm -rf {self.caches}/Homebrew")
        self.assertTrue(homebrew["impact"])
        self.assertEqual(go_build["command_text"], f"GOCACHE={self.caches}/go-build go clean -cache")
        self.assertNotIn(homebrew["impact"], payload["table"], "影響は表に出さないこと")

    def test_deletable_note(self):
        """一覧の最後に、「消してよい」の項目をまとめて選ぶ選び方を示す。その他の行の項目は、そのことも依頼したときだけ選ぶ (計画の R11)。"""
        entries = [("Homebrew", 2000), ("pnpm", 1900)] + [(f"app{index:02d}", 1000 - index) for index in range(30)]
        entries.append(("ms-playwright", 1))
        _, payload = self.first_list(entries)
        last = payload["notes"][-1]
        self.assertIn(f"一覧 A の表の「消してよい」の項目 (2 項目・合計 {lists.format_size(3900 * KIB)})", last)
        self.assertIn("その他の行の「消してよい」の項目 (1 項目", last)
        self.assertEqual(payload["others"]["deletable_count"], 1)

    def test_path_not_utf8(self):
        """UTF-8 として読めない名前の項目も一覧にでき、表では読めないバイトを \\xff の形で示す (計画の KTD2)。"""
        root = self.caches
        entry = {"args": du_args(root), "stdout": f"100\t{root}/caf\udcff\n100\t{root}\n", "stderr": "", "exit": 0}
        with open(self.du_responses_file, "w", encoding="utf-8") as f:
            json.dump([entry, self.du(self.developer, [])], f)  # ensure_ascii=True で surrogate をエスケープして書く
        run = self.start()
        payload = self.scan_ok(run)
        self.assertEqual(payload["items"][0]["path"], f"{root}/caf\udcff")
        self.assertEqual(payload["items"][0]["display"], "~/Library/Caches/caf\\xff")
        self.assertIn("`~/Library/Caches/caf\\xff`", payload["table"])
        code, shown, stderr = self.cli("list", "show", "--run", run, "A")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(shown["items"][0]["path"], f"{root}/caf\udcff")


class ItemListTest(ListsCase):

    def test_scan_item_makes_next_list(self):
        """scan --item A1 は、A1 の下の階層を英字 B の一覧にする。A1 はその後も指定でき、もう一度調べると新しい一覧 C を作る
        (計画の R5)。"""
        run, _ = self.first_list([("Google", 500)])
        google = f"{self.caches}/Google"
        self.du_responses([self.du(google, [("Chrome", 400), ("Other", 50)])])
        payload = self.scan_ok(run, "--item", "A1")
        self.assertEqual(payload["letter"], "B")
        self.assertEqual(payload["source"], {"kind": "item", "number": "A1", "path": google,
                                             "display": "~/Library/Caches/Google"})
        self.assertEqual(payload["items"][0]["number"], "B1")
        self.assertEqual(payload["items"][0]["judgment"], "deletable", "~/Library/Caches/Google/Chrome は判定表の行")
        self.assertEqual(self.scan_ok(run, "--item", "A1")["letter"], "C")
        code, shown, stderr = self.cli("list", "show", "--run", run, "A")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(shown["items"][0]["number"], "A1")

    def test_dedicated_list_item(self):
        """専用の一覧を持つ項目を指定すると、下の階層を調べずに専用の一覧の種類を返す (計画の KTD5。専用の一覧そのものは U10〜U12)。"""
        asdf = self.make_dir("user-home", ".asdf")
        self.make_dir("user-home", ".asdf", "installs")
        self.write_config(["~/.asdf"])
        self.du_responses([self.du(asdf, [("installs", 100)])])
        run = self.start()
        self.scan_ok(run)
        payload = self.scan_ok(run, "--item", "A1")
        self.assertEqual(payload["dedicated_list"], "asdf")
        self.assertIsNone(payload["letter"])
        self.assertEqual(payload["item"]["number"], "A1")
        self.assertFalse(os.path.exists(self.list_file(run, "B")))
        self.assertEqual(len(self.du_calls()), 1, "専用の一覧の項目の下は du で調べないこと")

    def test_failed_item_scan_uses_no_letter(self):
        """項目の下の階層を調べて結果を出せなければ、一覧を作らず、英字も使わない (計画の R4)。"""
        run, _ = self.first_list([("Google", 500)])
        google = f"{self.caches}/Google"
        self.du_responses([self.du(google, [], stderr="du: broken\n", exit_code=2)])
        self.assert_unsatisfied(self.cli("scan", "--run", run, "--item", "A1"), "A1", "下の階層を調べられなかった")
        self.du_responses([self.du(google, [("Chrome", 400)])])
        self.assertEqual(self.scan_ok(run, "--item", "A1")["letter"], "B")

    def test_27th_list_is_rejected(self):
        """1 つのトリアージで作れる一覧は 26 個 (A〜Z) まで。27 個目は du を実行せずに、新しいトリアージを始めるよう示す (計画の R9)。"""
        run, _ = self.first_list([("Google", 500)])
        with open(self.list_file(run, "A"), encoding="utf-8") as f:
            data = json.load(f)
        for letter in lists.LETTERS[1:]:
            with open(self.list_file(run, letter), "w", encoding="utf-8") as f:
                json.dump({**data, "letter": letter}, f)
        calls = len(self.du_calls())
        self.assert_unsatisfied(self.cli("scan", "--run", run, "--item", "A1"), "26 個", "run start")
        self.assertEqual(len(self.du_calls()), calls)


class ErrorTest(ListsCase):

    def test_unknown_number_letter_and_run(self):
        """存在しない番号・存在しない英字・別のトリアージの ID は、理由を付けて終了コード 3 で返す。"""
        run, _ = self.first_list([("a", 100)])
        self.assert_unsatisfied(self.cli("list", "show", "--run", run, "Z"), "一覧 Z は無い")
        self.assert_unsatisfied(self.cli("select", "add", "--run", run, "A9"), "番号 A9 は無い")
        self.assert_unsatisfied(self.cli("select", "add", "--run", run, "a1"), "大文字の英字 1 つ")
        self.assert_unsatisfied(self.cli("list", "show", "--run", "20000101-000000", "A"), "トリアージ 20000101-000000 が無い")
        self.assert_unsatisfied(self.cli("list", "show", "--run", "../x", "A"), "YYYYMMDD-HHMMSS の形でない")

    def test_corrupt_list_file(self):
        """壊れた一覧のファイルがあると、新しいトリアージで調べ直すよう示す (計画の KTD2)。"""
        run, _ = self.first_list([("a", 100)])
        with open(self.list_file(run, "A"), "w", encoding="utf-8") as f:
            f.write("{")
        self.assert_unsatisfied(self.cli("list", "show", "--run", run, "A"), "一覧 A のファイルが壊れている", "run start")
        self.assert_unsatisfied(self.cli("select", "add", "--run", run, "A1"), "一覧 A のファイルが壊れている")

    def test_corrupt_records_or_config(self):
        """壊れた records.json か config.json があると、scan・select add・list show は一覧を作らず、項目を選ばずに終了コード 3
        で返す (計画の KTD2)。"""
        run, _ = self.first_list([("Homebrew", 100)])
        self.make_dir("user-home", "Library", "Caches", "Homebrew")
        for name in ("records.json", "config.json"):
            with self.subTest(file=name):
                path = os.path.join(self.home, name)
                original = None
                if os.path.exists(path):
                    with open(path, encoding="utf-8") as f:
                        original = f.read()
                self.write_home_text(name, "{")
                self.assert_unsatisfied(self.cli("scan", "--run", run), name)
                self.assert_unsatisfied(self.cli("select", "add", "--run", run, "A1"), name)
                self.assert_unsatisfied(self.cli("list", "show", "--run", run, "A"), name)
                self.assertFalse(os.path.exists(self.list_file(run, "B")))
                self.assertFalse(os.path.exists(os.path.join(self.home, "runs", run, "selection.json")))
                if original is None:
                    os.remove(path)
                else:
                    self.write_home_text(name, original)


class SelectTest(ListsCase):

    def setUp(self):
        super().setUp()
        for name in ("Homebrew", "pnpm", "com.example.app"):
            self.make_dir("user-home", "Library", "Caches", name)
        self.run_id, self.listed = self.first_list([("Homebrew", 3000), ("pnpm", 2000), ("com.example.app", 1000)])

    def select(self, *args):
        return self.cli("select", *args[:1], "--run", self.run_id, *args[1:])

    def test_count_and_total(self):
        """選ぶたびに、選んだ項目の数と合計の使用量を返す。同じ項目を 2 回選んでも 1 つにする (計画の R10)。"""
        code, payload, stderr = self.select("add", "A1")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(payload["selection"], {"count": 1, "bytes": 3000 * KIB, "size": lists.format_size(3000 * KIB)})
        self.assertEqual(payload["added"][0]["command_text"], f"rm -rf {self.caches}/Homebrew", "選んだ項目の消すコマンドを示す")
        code, payload, _ = self.select("add", "A1", "A2", "A2")
        self.assertEqual(code, 0)
        self.assertEqual([entry["number"] for entry in payload["already"]], ["A1"])
        self.assertEqual([entry["number"] for entry in payload["added"]], ["A2"])
        self.assertEqual(payload["selection"]["count"], 2)

    def test_parent_and_child(self):
        """親と子の両方を選ぶと、親だけを残し、そのことを示す (計画の R10)。"""
        for name in ("downloads", "api"):
            self.make_dir("user-home", "Library", "Caches", "Homebrew", name)
        homebrew = f"{self.caches}/Homebrew"
        self.du_responses([self.du(homebrew, [("downloads", 2000), ("api", 500)])])
        self.scan_ok(self.run_id, "--item", "A1")
        code, payload, stderr = self.select("add", "B1")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(len(payload["added"]), 1)
        code, payload, _ = self.select("add", "A1")
        self.assertEqual(payload["replaced"], [{"number": "B1", "display": "~/Library/Caches/Homebrew/downloads",
                                                "parent": "A1"}])
        self.assertEqual(payload["selection"]["count"], 1)
        code, payload, _ = self.select("add", "B2")
        self.assertEqual(code, 0)
        self.assertEqual(payload["added"], [])
        self.assertIn("親のディレクトリの A1", payload["rejected"][0]["reasons"][0])

    def test_unjudged_and_mixed(self):
        """判定の無い項目は選ばずに理由を返し、ほかの選べる項目は選ぶ (計画の R12)。存在しない番号があれば何も選ばない。"""
        code, payload, stderr = self.select("add", "A1", "A3")
        self.assertEqual(code, 0, stderr)
        self.assertEqual([entry["number"] for entry in payload["added"]], ["A1"])
        self.assertEqual(payload["rejected"][0]["number"], "A3")
        self.assertIn("判定なし", payload["rejected"][0]["reasons"][0])
        code, payload, _ = self.select("add", "A2", "A9")
        self.assertEqual(code, 3)
        code, payload, _ = self.select("show")
        self.assertEqual([entry["number"] for entry in payload["items"]], ["A1"], "存在しない番号があれば何も選ばない")

    def test_all_deletable(self):
        """--all-deletable は、その一覧の表の「消してよい」の項目だけを選ぶ。--all を足すと、その他の行の項目からも選ぶ (計画の R11)。"""
        self.make_dir("user-home", "Library", "Caches", "ms-playwright")
        entries = [("Homebrew", 3000), ("pnpm", 2000)] + [(f"app{index:02d}", 1000 - index) for index in range(30)]
        entries.append(("ms-playwright", 1))
        self.du_responses([self.du(self.caches, entries), self.du(self.developer, [])])
        run = self.start_another()
        self.scan_ok(run)
        code, payload, stderr = self.cli("select", "add", "--run", run, "--all-deletable", "A")
        self.assertEqual(code, 0, stderr)
        self.assertEqual([entry["number"] for entry in payload["added"]], ["A1", "A2"])
        self.assertEqual(payload["others_deletable"]["count"], 1)
        code, payload, _ = self.cli("select", "add", "--run", run, "--all-deletable", "A", "--all")
        self.assertEqual([entry["number"] for entry in payload["added"]], ["A33"])
        self.assertEqual(len(payload["already"]), 2)
        self.assertIsNone(payload["others_deletable"])

    def test_argument_errors(self):
        self.assertEqual(self.select("add")[0], 2, "番号も --all-deletable も無いのは引数の誤り")
        self.assertEqual(self.select("add", "A1", "--all-deletable", "A")[0], 2)
        self.assertEqual(self.select("add", "A1", "--all")[0], 2)

    def test_remove_and_show(self):
        self.select("add", "A1", "A2")
        code, payload, stderr = self.select("remove", "A1", "A3")
        self.assertEqual(code, 0, stderr)
        self.assertEqual([entry["number"] for entry in payload["removed"]], ["A1"])
        self.assertEqual(payload["not_selected"], [{"number": "A3", "display": "~/Library/Caches/com.example.app",
                                                    "reason": "選んでいない"}])
        code, payload, stderr = self.select("show")
        self.assertEqual(code, 0, stderr)
        self.assertEqual([entry["number"] for entry in payload["items"]], ["A2"])
        self.assertEqual(payload["items"][0]["judgment_label"], "消してよい")
        self.assertIn("| A2 | `~/Library/Caches/pnpm` |", payload["table"])
        self.assertEqual(payload["selection"]["count"], 1)


class SelectionBlockerTest(ListsCase):
    """調べるディレクトリをホームディレクトリにして、保護の一覧の項目と、それらを含む親を選べないことを検査する (計画の R12・KTD5)。"""

    def setUp(self):
        super().setUp()
        self.write_config(["~"])
        names = [".claude", ".asdf", "Library", "work", "proj"]
        for name in names:
            self.make_dir("user-home", name)
        self.make_dir("user-home", ".asdf", "installs")
        self.make_dir("user-home", "Library", "Application Support", "Claude")
        self.make_dir("user-home", "work", "repo", ".claude", "worktrees")
        self.make_dir("user-home", "proj", "keepme")
        home = self.user_home
        self.write_records(*[user_record(os.path.join(home, name), "deletable") for name in (".asdf", "Library", "work", "proj")],
                           user_record(os.path.join(home, "proj", "keepme"), "keep"))
        self.du_responses([self.du(home, [(name, 100 * (index + 1)) for index, name in enumerate(names)])])
        self.run_id = self.start()
        self.numbers = {os.path.basename(item["path"]): item["number"] for item in self.scan_ok(self.run_id)["items"]}

    def reasons(self, name):
        code, payload, stderr = self.cli("select", "add", "--run", self.run_id, self.numbers[name])
        self.assertEqual(code, 0, stderr)
        self.assertEqual(payload["added"], [])
        return payload["rejected"][0]["reasons"]

    def test_protected(self):
        self.assertIn("保護の一覧にある", self.reasons(".claude")[0])

    def test_contains_protected(self):
        self.assertIn("Claude Desktop のディレクトリ", self.reasons("Library")[0])

    def test_contains_keep_table_row(self):
        """判定表の判定が「残す」の行に一致するディレクトリを含む親は選べない。"""
        self.assertIn("判定表の判定が「残す」", self.reasons(".asdf")[0])

    def test_contains_keep_record(self):
        """記録の「残す」のディレクトリを含む親は選べない。"""
        self.assertIn("「残す」と記録したディレクトリ", self.reasons("proj")[0])

    def test_app_worktree_below(self):
        self.assertIn("アプリの worktree", self.reasons("work")[0])


class JudgeSetTest(ListsCase):

    def setUp(self):
        super().setUp()
        self.app = self.make_dir("user-home", "Library", "Caches", "com.example.app")
        self.make_dir("user-home", "Library", "Caches", "Homebrew")
        self.run_id, _ = self.first_list([("com.example.app", 3000), ("Homebrew", 2000)])

    def judge_set(self, number, data):
        return self.cli("judge", "set", "--run", self.run_id, number, "--input-file", self.write_input(data))

    def test_rejects_invalid_input(self):
        """知らないキー (パスを含む入力)・根拠の無い入力を拒否し、Claude が書いたコマンドを R16 で検査する。"""
        self.assert_unsatisfied(self.judge_set("A1", {**REVIEW_INPUT, "target": {"kind": "directory", "path": self.app}}),
                                "知らないキー")
        self.assert_unsatisfied(self.judge_set("A1", {**REVIEW_INPUT, "basis": []}), "根拠")
        self.assert_unsatisfied(self.judge_set("A1", {**REVIEW_INPUT, "command": {"type": "tool", "args": ["rustup", "run"]}}),
                                "許可していない")
        self.assertFalse(os.path.exists(os.path.join(self.home, "records.json")))

    def test_review_is_shown_in_next_triage(self):
        """「確認が要る」の判定を記録すると、次のトリアージの一覧で、「Claude が <日付> に判定」の「確認が要る」になる (計画の R20)。"""
        code, payload, stderr = self.judge_set("A1", REVIEW_INPUT)
        self.assertEqual(code, 0, stderr)
        label = f"確認が要る (Claude が {TODAY} に判定)"
        self.assertEqual(payload["item"]["judgment_label"], label)
        self.assertEqual(payload["record"]["decided_by"], "claude")
        run = self.start_another()
        listed = self.scan_ok(run)
        self.assertEqual(listed["items"][0]["judgment_label"], label)
        self.assertIn(label, listed["table"])

    def test_rejects_table_item(self):
        self.assert_unsatisfied(self.judge_set("A2", REVIEW_INPUT), "判定表の行")

    def test_rejects_user_record_and_parent_record(self):
        """利用者の記録と、親のディレクトリの記録で判定が決まった項目には記録しない (計画の R20)。"""
        code, _, stderr = self.cli("records", "add", "--run", self.run_id, "--item", "A1", "--input-file",
                                   self.write_input({"judgment": "keep"}, "keep.json"))
        self.assertEqual(code, 0, stderr)
        self.assert_unsatisfied(self.judge_set("A1", REVIEW_INPUT), "利用者の記録")
        self.make_dir("user-home", "Library", "Caches", "com.example.app", "data")
        self.du_responses([self.du(self.app, [("data", 100)])])
        self.scan_ok(self.run_id, "--item", "A1")
        self.assert_unsatisfied(self.judge_set("B1", REVIEW_INPUT), "親のディレクトリ")

    def test_rejudge_own_record(self):
        """項目そのものの Claude の記録は、調べ直して記録し直せる。"""
        self.assertEqual(self.judge_set("A1", REVIEW_INPUT)[0], 0)
        code, payload, stderr = self.judge_set("A1", {**REVIEW_INPUT, "judgment": "deletable"})
        self.assertEqual(code, 0, stderr)
        self.assertEqual(payload["previous"]["judgment"], "review")
        self.assertEqual(payload["item"]["judgment"], "deletable")


class RecordsAddItemTest(ListsCase):

    def setUp(self):
        super().setUp()
        self.app = self.make_dir("user-home", "Library", "Caches", "com.example.app")
        self.run_id, _ = self.first_list([("com.example.app", 3000)])

    def records_add(self, data, *extra):
        return self.cli("records", "add", *extra, "--input-file", self.write_input(data))

    def test_keep_by_number(self):
        """番号で指定した項目を「残す」と記録し、その後の一覧の判定が変わる (計画の KTD3・KTD17)。"""
        code, payload, stderr = self.records_add({"judgment": "keep", "reason": "設定を含む"},
                                                 "--run", self.run_id, "--item", "A1")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(payload["record"]["target"], {"kind": "directory", "path": self.app})
        self.assertEqual(payload["display"], "~/Library/Caches/com.example.app")
        code, shown, stderr = self.cli("list", "show", "--run", self.run_id, "A")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(shown["items"][0]["judgment_label"], f"残す (利用者が {TODAY} に記録)")

    def test_target_with_item_is_rejected(self):
        self.assert_unsatisfied(self.records_add({"target": {"kind": "directory", "path": self.app}, "judgment": "keep"},
                                                 "--run", self.run_id, "--item", "A1"), "target を書かない")

    def test_unknown_number(self):
        self.assert_unsatisfied(self.records_add({"judgment": "keep"}, "--run", self.run_id, "--item", "A2"), "番号 A2 は無い")

    def test_run_without_item_is_argument_error(self):
        self.assertEqual(self.records_add({"judgment": "keep"}, "--run", self.run_id)[0], 2)


class OutputPathTest(ListsCase):

    def test_outputs_have_no_triage_directory(self):
        """出力に、トリアージのディレクトリのパスを含めない (計画の KTD17)。"""
        self.make_dir("user-home", "Library", "Caches", "Homebrew")
        run, scanned = self.first_list([("Homebrew", 100)])
        outputs = [scanned]
        for args in (("list", "show", "--run", run, "A", "--all", "--unreadable"), ("select", "add", "--run", run, "A1"),
                     ("select", "show", "--run", run), ("select", "remove", "--run", run, "A1")):
            code, payload, stderr = self.cli(*args)
            self.assertEqual(code, 0, stderr)
            outputs.append(payload)
        runs = os.path.join(self.home, "runs")
        for payload in outputs:
            self.assertFalse(re.search(re.escape(runs), json.dumps(payload, ensure_ascii=False)))


if __name__ == "__main__":
    unittest.main()
