#!/usr/bin/env python3
"""外部のコマンドの実行 (ファイル `disk-usage-triage/scripts/disk_usage_triage/proc.py`) のテスト。

外部のコマンドの代わりに、このテストを実行している Python (`sys.executable`) に短いプログラムを渡して実行する。

  python3 -m unittest discover -s disk-usage-triage/tests
"""

import sys
import time
import unittest

import triage_case  # noqa: F401  パッケージ disk_usage_triage を読めるように、sys.path にディレクトリ scripts を加える

from disk_usage_triage import proc  # noqa: E402


def python(code):
    return [sys.executable, "-c", code]


class RunTest(unittest.TestCase):

    def test_success(self):
        result = proc.run(python("print('出力')"), timeout=30)
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["stdout"], "出力\n")
        self.assertFalse(result["timed_out"])
        self.assertIsNone(result["start_error"])

    def test_nonzero_exit_keeps_all_output(self):
        """終了コードが 0 以外でも、標準出力と標準エラー出力をすべて返す (計画の KTD4。du は読めないディレクトリがあると
        終了コード 1 を返すが、ほかの結果は標準出力に出す。標準エラー出力の行は数百になることがある)。"""
        code = ("import sys\n"
                "print('12\\t/a')\n"
                "for i in range(400):\n"
                "    print(f'du: /a/{i}: Operation not permitted', file=sys.stderr)\n"
                "sys.exit(1)\n")
        result = proc.run(python(code), timeout=30)
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(result["stdout"], "12\t/a\n")
        self.assertEqual(len(result["stderr"].splitlines()), 400, "標準エラー出力を省略しないこと")
        self.assertFalse(result["timed_out"])

    def test_stdin_is_empty(self):
        """標準入力を空にして実行する (計画の KTD4)。標準入力を読むコマンドは、すぐにファイルの終端 (EOF) を読む。"""
        result = proc.run(python("import sys; print(repr(sys.stdin.read()))"), timeout=30)
        self.assertEqual(result["stdout"], "''\n")

    def test_timeout(self):
        """時間の上限を超えたら打ち切り、打ち切ったことを返す (計画の R4)。"""
        started = time.monotonic()
        result = proc.run(python("import time; print('途中', flush=True); time.sleep(30)"), timeout=1)
        self.assertLess(time.monotonic() - started, 20)
        self.assertTrue(result["timed_out"])
        self.assertIsNone(result["exit_code"])
        self.assertIsNone(result["start_error"])
        self.assertIsInstance(result["stdout"], str)
        self.assertIsInstance(result["stderr"], str)

    def test_missing_command(self):
        result = proc.run(["disk-usage-triage-no-such-command"], timeout=30)
        self.assertIsNone(result["exit_code"])
        self.assertFalse(result["timed_out"])
        self.assertIn("disk-usage-triage-no-such-command", result["start_error"])

    def test_args_are_returned(self):
        args = python("pass")
        self.assertEqual(proc.run(args, timeout=30)["args"], args)

    def test_timeout_is_required(self):
        """時間の上限を付けずに実行できないこと (計画の KTD4)。"""
        with self.assertRaises(TypeError):
            proc.run(python("pass"))  # pylint: disable=no-value-for-parameter


if __name__ == "__main__":
    unittest.main()
