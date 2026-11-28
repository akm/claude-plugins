#!/usr/bin/env python3
"""ディレクトリの調査 (ファイル `disk-usage-triage/scripts/disk_usage_triage/scan.py`) のテスト (計画
docs/plans/2026-11-22-1630-feat-disk-usage-triage-plan.md の U5)。

偽の du (ファイル `disk-usage-triage/tests/fakebin/du`) と固定データ (ディレクトリ `disk-usage-triage/tests/fixtures/du/`) で、
du の出力の読み方・標準エラー出力の分け方・時間の上限を検査する。クラス RealDuTest だけは、実際の du (/usr/bin/du) を使う。

  python3 -m unittest discover -s disk-usage-triage/tests
"""

import os
import time
import unittest

from fakedu_case import FakeDuCase, du_args
from triage_case import TriageCase

from disk_usage_triage import scan  # noqa: E402

KIB = 1024
VAR_DB = "/private/var/db"  # 固定データ private-var-db を取ったディレクトリ
CACHES = "/Users/u/Library/Caches"  # 固定データ names のパス (一時ディレクトリのパスを置き換えたもの)


def items_by_path(result):
    return {item["path"]: item for item in result["items"]}


def assert_no_result(case, result):
    """結果を出さないこと (計画の KTD4・R4)。"""
    case.assertIsNone(result["bytes"])
    case.assertEqual(result["items"], [])
    case.assertEqual(result["unreadable"], [])


class FixtureTest(FakeDuCase):
    """macOS の /private/var/db の du の出力 (固定データ private-var-db。終了コード 1 で、標準エラー出力は読めないパスの行
    だけ)。"""

    def setUp(self):
        super().setUp()
        self.du_responses([{"args": du_args(VAR_DB), "stdout": {"fixture": "private-var-db"},
                            "stderr": {"fixture": "private-var-db"}, "exit": 1}])

    def test_items_and_total(self):
        """1 つ下の階層の項目と使用量 (バイト) を得る。ディレクトリ自身の行は、項目に入れずに合計に使う。"""
        result = scan.scan_directory(VAR_DB, timeout=30)
        self.assertEqual(result["status"], scan.STATUS_OK)
        self.assertIsNone(result["error"])
        self.assertEqual(result["requested"], VAR_DB)
        self.assertEqual(result["path"], VAR_DB)
        self.assertEqual(result["bytes"], 3668408 * KIB)
        items = items_by_path(result)
        self.assertEqual(len(items), 60, "ディレクトリ自身の行を除いた 60 行が項目になること")
        self.assertNotIn(VAR_DB, items)
        self.assertEqual(items[f"{VAR_DB}/receipts"]["bytes"], 74216 * KIB)
        self.assertEqual(items[f"{VAR_DB}/ExtensibleSSO"]["bytes"], 0)

    def test_unreadable_below_item(self):
        """終了コード 1 で、標準エラー出力が読めないパスの行だけなら結果を使い、項目の下の階層の読めなかったパスを、
        その項目に対応させる (計画の KTD4)。"""
        result = scan.scan_directory(VAR_DB, timeout=30)
        items = items_by_path(result)
        self.assertEqual(items[f"{VAR_DB}/ExtensibleSSO"]["unreadable"], [f"{VAR_DB}/ExtensibleSSO/Configuration"])
        self.assertEqual(items[f"{VAR_DB}/softwareupdate"]["unreadable"],
                         [f"{VAR_DB}/softwareupdate/Library/WebKit", f"{VAR_DB}/softwareupdate/Library/Preferences"])
        self.assertEqual(items[f"{VAR_DB}/dslocal"]["unreadable"], [f"{VAR_DB}/dslocal/nodes/Default"],
                         "2 つ以上下の階層のパスも、それを含む項目に対応させること")
        self.assertEqual(items[f"{VAR_DB}/receipts"]["unreadable"], [])
        mapped = sum(len(item["unreadable"]) for item in result["items"])
        self.assertEqual(mapped, 13)

    def test_unreadable_directory_without_line(self):
        """1 つ下の階層のディレクトリそのものが読めない (du がそのディレクトリの行を出さない) ときは、項目にせず、どの項目にも
        入らない読めなかったパスとして返す (計画の KTD4)。"""
        result = scan.scan_directory(VAR_DB, timeout=30)
        self.assertEqual(len(result["unreadable"]), 47)
        self.assertIn(f"{VAR_DB}/appinstalld", result["unreadable"])  # Operation not permitted の行
        self.assertIn(f"{VAR_DB}/diskimagesiod", result["unreadable"])  # Permission denied の行
        self.assertFalse(set(result["unreadable"]) & set(items_by_path(result)))

    def test_du_args_and_locale(self):
        """du を、引数 -k -d 1 と、環境変数 LC_ALL=en_US.UTF-8 を足して実行する (計画の KTD4)。呼び出し元の LC_ALL は
        引き継がない。"""
        os.environ["LC_ALL"] = "C"
        scan.scan_directory(VAR_DB, timeout=30)
        self.assertEqual(self.du_calls(), [{"args": du_args(VAR_DB), "lc_all": "en_US.UTF-8"}])


class NamesTest(FakeDuCase):

    def test_space_japanese_tab_names(self):
        """空白・日本語・タブ・アクセント付きの文字を含むパスを、そのまま読む (固定データ names)。"""
        self.du_responses([{"args": du_args(CACHES), "stdout": {"fixture": "names"}}])
        result = scan.scan_directory(CACHES, timeout=30)
        self.assertEqual(result["status"], scan.STATUS_OK)
        self.assertEqual({item["path"]: item["bytes"] for item in result["items"]},
                         {f"{CACHES}/a b": 300 * KIB, f"{CACHES}/日本語": 100 * KIB,
                          f"{CACHES}/tab\tname": 40 * KIB, f"{CACHES}/é": 0})
        self.assertEqual(result["bytes"], 440 * KIB)


class OutputCase(FakeDuCase):
    """調べるディレクトリを一時ディレクトリに作り、偽の du の出力をテストの中で書く。"""

    def setUp(self):
        super().setUp()
        self.dir = self.make_dir("scan")

    def respond(self, stdout="", stderr="", exit_code=0, path=None):
        self.du_responses([{"args": du_args(path or self.dir), "stdout": stdout, "stderr": stderr, "exit": exit_code}])

    def scan(self, path=None):
        return scan.scan_directory(path or self.dir, timeout=30)


class StderrTest(OutputCase):

    def test_exit_zero_with_denied_line(self):
        """終了コード 0 で、標準エラー出力が読めないパスの行だけのときも、結果を使う。"""
        self.respond(f"4\t{self.dir}/a\n8\t{self.dir}\n", f"du: {self.dir}/a/b: Permission denied\n", 0)
        result = self.scan()
        self.assertEqual(result["status"], scan.STATUS_OK)
        self.assertEqual(result["items"], [{"path": f"{self.dir}/a", "bytes": 4 * KIB, "unreadable": [f"{self.dir}/a/b"]}])

    def test_other_error_discards_result(self):
        """終了コード 1 で、読めないパスと消えたパスのほかの誤りを含むときは、そのディレクトリの結果を返さずに誤りを返す
        (計画の KTD4)。"""
        self.respond(f"4\t{self.dir}/a\n8\t{self.dir}\n",
                     f"du: {self.dir}/a/b: Operation not permitted\ndu: {self.dir}/c: Input/output error\n", 1)
        result = self.scan()
        self.assertEqual(result["status"], scan.STATUS_FAILED)
        assert_no_result(self, result)
        self.assertIn("Input/output error", result["error"])

    def test_vanished_path_is_accepted(self):
        """消えたパスの行 (No such file or directory) は受け入れて結果を使い、そのパスを項目に対応させない (計画の KTD4)。"""
        self.respond(f"4\t{self.dir}/a\n8\t{self.dir}\n", f"du: {self.dir}/a/tmp-123: No such file or directory\n", 1)
        result = self.scan()
        self.assertEqual(result["status"], scan.STATUS_OK)
        self.assertEqual(result["items"], [{"path": f"{self.dir}/a", "bytes": 4 * KIB, "unreadable": []}])
        self.assertEqual(result["unreadable"], [])

    def test_exit_one_without_stderr(self):
        """終了コード 1 で、標準エラー出力が空のときは、結果を返さない。"""
        self.respond(f"4\t{self.dir}/a\n8\t{self.dir}\n", "", 1)
        result = self.scan()
        self.assertEqual(result["status"], scan.STATUS_FAILED)
        assert_no_result(self, result)

    def test_other_exit_code(self):
        """終了コードが 0 と 1 のほかのときは、結果を返さない。"""
        self.respond(f"4\t{self.dir}/a\n8\t{self.dir}\n", "", 2)
        result = self.scan()
        self.assertEqual(result["status"], scan.STATUS_FAILED)
        assert_no_result(self, result)
        self.assertIn("2", result["error"])

    def test_unexpected_args(self):
        """偽の du は、決めていない引数では終了コード 99 で終了する。そのときも、結果を返さない。"""
        self.respond(f"8\t{self.dir}\n", path=os.path.join(self.root, "other"))
        result = self.scan()
        self.assertEqual(result["status"], scan.STATUS_FAILED)
        self.assertIn("99", result["error"])

    def test_denied_path_with_colon_space_and_japanese(self):
        """読めなかったパスに `: `・空白・日本語があっても、行の最後の `: <理由>` だけを除いてパスにする。"""
        self.respond(f"4\t{self.dir}/日本語 a: b\n8\t{self.dir}\n",
                     f"du: {self.dir}/日本語 a: b/Data: Operation not permitted\n", 1)
        result = self.scan()
        self.assertEqual(result["status"], scan.STATUS_OK)
        self.assertEqual(result["items"][0]["unreadable"], [f"{self.dir}/日本語 a: b/Data"])

    def test_denied_directory_itself_with_line(self):
        """ディレクトリ自身の行があり、ディレクトリそのものが読めなかったという行もあるときは、そのパスを、どの項目にも
        入らない読めなかったパスとして返す (macOS の du は自身の行を出さないので、ふつうは起きない)。"""
        self.respond(f"8\t{self.dir}\n", f"du: {self.dir}: Permission denied\n", 1)
        result = self.scan()
        self.assertEqual(result["status"], scan.STATUS_OK)
        self.assertEqual(result["unreadable"], [self.dir])

    def test_denied_path_outside_directory(self):
        """調べたディレクトリの外のパスが読めなかったという行があれば、結果を返さない。"""
        self.respond(f"4\t{self.dir}/a\n8\t{self.dir}\n", f"du: {self.dir}-other/a: Permission denied\n", 1)
        result = self.scan()
        self.assertEqual(result["status"], scan.STATUS_FAILED)
        assert_no_result(self, result)


class StdoutTest(OutputCase):

    def test_malformed_line(self):
        """標準出力の行が「数字・タブ・パス」の形でなければ、結果を返さない (計画の KTD4)。"""
        for stdout in (f"x\t{self.dir}/a\n8\t{self.dir}\n", f"4 {self.dir}/a\n8\t{self.dir}\n",
                       f"4\t{self.dir}/a\n\n8\t{self.dir}\n", f"４\t{self.dir}/a\n8\t{self.dir}\n"):  # 最後は全角の数字
            with self.subTest(stdout=stdout):
                self.respond(stdout)
                result = self.scan()
                self.assertEqual(result["status"], scan.STATUS_FAILED)
                assert_no_result(self, result)

    def test_newline_in_name(self):
        """名前に改行を含むディレクトリがあると、行が分かれて形が合わなくなるので、結果を返さない。"""
        self.respond(f"4\t{self.dir}/a\nb\n8\t{self.dir}\n")
        result = self.scan()
        self.assertEqual(result["status"], scan.STATUS_FAILED)
        self.assertIn("'b'", result["error"])

    def test_path_neither_directory_nor_child(self):
        """調べたディレクトリでも、その 1 つ下でもないパスの行があれば、結果を返さない。"""
        for stdout in (f"4\t{self.dir}/a/b\n8\t{self.dir}\n", f"4\t{self.dir}-other\n8\t{self.dir}\n",
                       f"4\t{self.dir}/a\n4\t{self.dir}/a\n8\t{self.dir}\n"):
            with self.subTest(stdout=stdout):
                self.respond(stdout)
                result = self.scan()
                self.assertEqual(result["status"], scan.STATUS_FAILED)
                assert_no_result(self, result)

    def test_missing_directory_line(self):
        """ディレクトリ自身の行が無い (調べたディレクトリそのものが無いか、読めない) ときは、結果を返さない。
        誤りには、du の標準エラー出力を含める。"""
        self.respond("", f"du: {self.dir}: Permission denied\n", 1)
        result = self.scan()
        self.assertEqual(result["status"], scan.STATUS_FAILED)
        assert_no_result(self, result)
        self.assertIn(f"du: {self.dir}: Permission denied", result["error"])

    def test_root_directory(self):
        """ルートのディレクトリ (/) を調べたときは、/<名前> を 1 つ下の項目にする。"""
        self.respond("4\t/a\n8\t/\n", path="/")
        result = self.scan("/")
        self.assertEqual(result["status"], scan.STATUS_OK)
        self.assertEqual(result["items"], [{"path": "/a", "bytes": 4 * KIB, "unreadable": []}])
        self.assertEqual(result["bytes"], 8 * KIB)

    def test_directory_only(self):
        """1 つ下の階層にディレクトリが無いときは、項目を空の配列にする。"""
        self.respond(f"8\t{self.dir}\n")
        result = self.scan()
        self.assertEqual(result["status"], scan.STATUS_OK)
        self.assertEqual(result["items"], [])
        self.assertEqual(result["bytes"], 8 * KIB)


class PathTest(OutputCase):

    def test_tilde_is_expanded(self):
        """~ と ~/ で始まるパス (設定の値) を、利用者のホームディレクトリ (環境変数 HOME) の下として展開する。"""
        cache = self.make_dir("user-home", "cache")
        self.respond(f"8\t{cache}\n", path=cache)
        result = self.scan("~/cache")
        self.assertEqual(result["status"], scan.STATUS_OK)
        self.assertEqual(result["requested"], "~/cache")
        self.assertEqual(result["path"], cache)
        self.respond(f"8\t{self.user_home}\n", path=self.user_home)
        self.assertEqual(self.scan("~")["path"], self.user_home)

    def test_symlink_is_resolved(self):
        """シンボリックリンクを解決したパスを du に渡し、項目のパスも解決した後のパスにする (計画の KTD4)。du は、引数の
        シンボリックリンクをたどらないため。"""
        link = os.path.join(self.root, "link")
        os.symlink(self.dir, link)
        self.respond(f"4\t{self.dir}/a\n8\t{self.dir}\n")
        result = self.scan(link)
        self.assertEqual(result["status"], scan.STATUS_OK)
        self.assertEqual(result["path"], self.dir)
        self.assertEqual(result["items"][0]["path"], f"{self.dir}/a")
        self.assertEqual(self.du_calls()[0]["args"], du_args(self.dir))

    def test_trailing_slash_and_dot_dot(self):
        """書いたとおりに保存した設定のパス (末尾の / と途中の .. を含む) も、解決してから渡す。"""
        cache = self.make_dir("user-home", "cache")
        self.make_dir("user-home", "x")
        self.respond(f"8\t{cache}\n", path=cache)
        self.assertEqual(self.scan("~/x/../cache/")["path"], cache)

    def test_invalid_path(self):
        """相対パス・~<利用者名> で始まるパス・空の文字列は、呼び出し元の誤りとして ValueError にする。"""
        for path in ("cache", "~other/cache", ""):
            with self.subTest(path=path), self.assertRaises(ValueError):
                scan.scan_directory(path, timeout=30)
        self.assertEqual(self.du_calls(), [])


class RunTest(FakeDuCase):

    def test_timeout_and_other_directories(self):
        """時間の上限を超えた du は打ち切り、そのディレクトリを「時間内に完了しなかった」として返し、ほかのディレクトリの
        結果は返す (計画の R4)。"""
        slow, fast = self.make_dir("slow"), self.make_dir("fast")
        self.du_responses([{"args": du_args(slow), "hang": True},
                           {"args": du_args(fast), "stdout": f"4\t{fast}/a\n8\t{fast}\n"}])
        started = time.monotonic()
        results = scan.scan_directories([slow, fast], timeout=1)
        self.assertLess(time.monotonic() - started, 20)
        self.assertEqual([r["path"] for r in results], [slow, fast])
        self.assertEqual(results[0]["status"], scan.STATUS_TIMED_OUT)
        assert_no_result(self, results[0])
        self.assertIn("1 秒", results[0]["error"])
        self.assertEqual(results[1]["status"], scan.STATUS_OK)
        self.assertEqual(results[1]["bytes"], 8 * KIB)

    def test_du_cannot_start(self):
        """du を起動できないときは、結果を返さずに誤りを返す。"""
        missing = os.path.join(self.root, "no-such-du")
        os.environ["DISK_USAGE_TRIAGE_DU"] = missing
        result = scan.scan_directory(self.make_dir("scan"), timeout=30)
        self.assertEqual(result["status"], scan.STATUS_FAILED)
        assert_no_result(self, result)
        self.assertIn(missing, result["error"])

    def test_default_du(self):
        """環境変数 DISK_USAGE_TRIAGE_DU が無ければ、/usr/bin/du を絶対パスで実行する (計画の KTD4)。"""
        os.environ.pop("DISK_USAGE_TRIAGE_DU", None)
        self.assertEqual(scan.du_command(), "/usr/bin/du")


@unittest.skipUnless(os.path.exists("/usr/bin/du"), "/usr/bin/du が無い")
class RealDuTest(TriageCase):
    """実際の du (/usr/bin/du) で一時ディレクトリを調べる。macOS と Ubuntu (CI) のどちらでも成功すること。"""

    _KEYS = ("DISK_USAGE_TRIAGE_DU", "LC_ALL", "LANG")

    def setUp(self):
        super().setUp()
        self._real_saved = {k: os.environ.get(k) for k in self._KEYS}
        os.environ.pop("DISK_USAGE_TRIAGE_DU", None)
        # Claude の Bash ツールと同じく C ロケールにする。macOS の du は、C ロケールでは ASCII でない名前を書き換える
        os.environ["LC_ALL"] = "C"
        os.environ["LANG"] = ""

    def tearDown(self):
        for k, v in self._real_saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        super().tearDown()

    def write(self, path, size):
        with open(path, "wb") as f:
            f.write(os.urandom(size))

    def test_written_directory_is_larger(self):
        """ファイルを書き込んだディレクトリが、書き込んでいないディレクトリより大きい。"""
        top = self.make_dir("real")
        full, empty = self.make_dir("real", "full"), self.make_dir("real", "empty")
        self.write(os.path.join(full, "data"), 1024 * KIB)
        result = scan.scan_directory(top, timeout=60)
        self.assertEqual(result["status"], scan.STATUS_OK, result["error"])
        items = items_by_path(result)
        self.assertEqual(set(items), {full, empty})
        self.assertGreater(items[full]["bytes"], items[empty]["bytes"])
        self.assertGreaterEqual(result["bytes"], items[full]["bytes"])

    def test_names_in_c_locale(self):
        """C ロケールの環境から調べても、空白と日本語を含む名前を正しく読む (計画の KTD4)。"""
        top = self.make_dir("names")
        japanese, accented = self.make_dir("names", "日本語 a"), self.make_dir("names", "é b")
        self.write(os.path.join(japanese, "data"), 16 * KIB)
        result = scan.scan_directory(top, timeout=60)
        self.assertEqual(result["status"], scan.STATUS_OK, result["error"])
        self.assertEqual(set(items_by_path(result)), {japanese, accented})


if __name__ == "__main__":
    unittest.main()
