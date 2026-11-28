#!/usr/bin/env python3
"""Claude が書いたコマンドの検査 (ファイル `disk-usage-triage/scripts/disk_usage_triage/commands.py`) のテスト。

計画 docs/plans/2026-11-22-1630-feat-disk-usage-triage-plan.md の U4 のテストシナリオのうち、R16 の検査。許可する組と
環境変数の名前は KTD6、引数の書き方 ({path}・{name}・パスの形の値) は R16 にある。

  python3 -m unittest discover -s disk-usage-triage/tests
"""

import datetime
import re
import unittest

import triage_case  # noqa: F401  パッケージ disk_usage_triage を読み込めるようにする

from disk_usage_triage import commands  # noqa: E402


def tool(*args, env=None):
    command = {"type": "tool", "args": list(args)}
    if env is not None:
        command["env"] = env
    return command


class AllowedPairTest(unittest.TestCase):

    def assert_accepted(self, command):
        self.assertEqual(commands.command_errors(command), [], command)

    def assert_rejected(self, command, *fragments):
        errors = commands.command_errors(command)
        self.assertTrue(errors, f"{command} を拒否すること")
        for fragment in fragments:
            self.assertTrue(any(fragment in error for error in errors), f"理由に {fragment!r} を含むこと: {errors}")
        return errors

    def test_allowed_forms_are_accepted(self):
        """組の形のコマンドは受け付け、形に引数を足したコマンドは拒否する (R16)。"""
        for entry in commands.ALLOWED:
            for form in entry["forms"]:
                with self.subTest(form=form):
                    self.assert_accepted(tool(*form["args"], env=dict(form["env"]) or None))
                    self.assert_rejected(tool(*form["args"], "--flag", env=dict(form["env"]) or None), "形")

    def test_command_must_match_a_form(self):
        """項目を指さないコマンドと、組に続く引数で対象を広げるコマンドは、形と一致しないので拒否する (R16)。"""
        for command in (tool("xcrun", "simctl", "delete", "all"), tool("go", "clean", "-modcache"),
                        tool("go", "clean", "-modcache", "-cache", env={"GOMODCACHE": "{path}"}),
                        tool("brew", "cleanup", "--prune=all"), tool("npm", "cache", "clean", "--force")):
            with self.subTest(command=command):
                self.assert_rejected(command, "形のどれとも一致しない")

    def test_pairs_added_in_u4(self):
        """U4 で、brew cleanup と uv cache prune を足した (2026-11-27 に利用者が決めた)。"""
        self.assert_accepted(tool("brew", "cleanup", env={"HOMEBREW_CACHE": "{path}"}))
        self.assert_accepted(tool("uv", "cache", "prune", "--cache-dir", "{path}"))

    def test_pairs_that_start_other_commands_are_rejected(self):
        """実行ファイルは許可していても、許可していないサブコマンド (別のコマンドを起動するものなど) は拒否する。"""
        for args in (("rustup", "run", "stable", "rm"), ("uv", "run", "rm"), ("pnpm", "exec", "rm"),
                     ("npm", "exec", "rm"), ("brew", "ruby", "-e", "x"), ("go", "run", "main.go")):
            with self.subTest(args=args):
                if args[0] in {entry["args"][0] for entry in commands.ALLOWED}:
                    self.assert_rejected(tool(*args), "許可していない組")
                else:
                    self.assert_rejected(tool(*args), "許可していない実行ファイル")

    def test_only_the_first_words_match(self):
        """組は引数の配列の先頭と比べる。組の語が後ろにあっても受け付けない。"""
        self.assert_rejected(tool("npm", "exec", "npm", "cache", "clean"), "許可していない組")
        self.assert_rejected(tool("go"), "許可していない組")

    def test_unknown_executable_is_rejected(self):
        for executable in ("rm", "cargo", "sudo", "bash"):
            with self.subTest(executable=executable):
                self.assert_rejected(tool(executable, "clean"), "許可していない実行ファイル")

    def test_docker_asdf_and_git_are_rejected(self):
        """Docker・asdf・git のコマンドは、それぞれのドメインでスクリプトが組み立てるので、Claude は書けない。"""
        for args in (("docker", "volume", "rm", "x"), ("asdf", "uninstall", "nodejs", "22.0.0"),
                     ("git", "worktree", "remove", "x")):
            with self.subTest(args=args):
                errors = self.assert_rejected(tool(*args), args[0])
                self.assertFalse(any("許可していない実行ファイル" in error for error in errors),
                                 "docker・asdf・git は、それとわかる理由で拒否すること")

    def test_executable_written_as_a_path_is_rejected(self):
        for executable in ("/opt/homebrew/bin/brew", "./brew", "bin/go"):
            with self.subTest(executable=executable):
                self.assert_rejected(tool(executable, "cleanup"), "パス")

    def test_placeholder_as_executable_is_rejected(self):
        self.assert_rejected(tool("{name}", "cleanup"), "実行ファイル")


class ArgumentTest(unittest.TestCase):

    def assert_rejected_argument(self, value, fragment):
        for command in (tool("brew", "cleanup", value), tool("brew", "cleanup", env={"HOMEBREW_CACHE": value})):
            with self.subTest(command=command):
                errors = commands.command_errors(command)
                self.assertTrue(any(fragment in error for error in errors), f"理由に {fragment!r} を含むこと: {errors}")

    def test_special_characters_are_rejected(self):
        """シェルの特殊文字 (;・|・&・$・バッククォート・<・>・改行) を含む引数と環境変数の値は拒否する (R16・KTD6)。"""
        self.assertEqual(commands.SPECIAL_CHARACTERS, (";", "|", "&", "$", "`", "<", ">", "\n"))
        for character in commands.SPECIAL_CHARACTERS:
            with self.subTest(character=repr(character)):
                self.assert_rejected_argument(f"a{character}b", "特殊文字")

    def test_nul_and_empty_are_rejected(self):
        """削除のシェルスクリプトに書けない、NUL 文字を含む引数と空の引数は拒否する (2026-11-27 に利用者が決めた)。"""
        self.assert_rejected_argument("a\0b", "NUL")
        self.assert_rejected_argument("", "空")

    def test_non_string_is_rejected(self):
        self.assertTrue(commands.command_errors(tool("brew", "cleanup", 3)))
        self.assertTrue(commands.command_errors({"type": "tool", "args": "brew cleanup"}))
        self.assertTrue(commands.command_errors({"type": "tool", "args": []}))

    def test_value_with_spaces_is_accepted(self):
        """空白は特殊文字ではないので、空白を含む値は値の検査で拒否しない。"""
        self.assertEqual(commands.value_errors("iPhone 15 Pro", "args[3]"), [])
        self.assertEqual(commands.value_errors("日本語 の 名前", "args[3]"), [])

    def test_path_form_is_rejected(self):
        """パスの形の値 (/・~・. で始まる値と、/ を含む値) は拒否し、項目の場所は {path} で書かせる (R16)。"""
        self.assertEqual(commands.PATH_PREFIXES, ("/", "~", "."))
        for value in ("~", "~/cache", "~root/cache", "/Users/u/cache", "./cache", "..", ".cache", "cache/sub",
                      "--cache-dir=/x"):
            with self.subTest(value=value):
                self.assert_rejected_argument(value, "パスの形")
        self.assertEqual(commands.command_errors(tool("uv", "cache", "clean", "--cache-dir", "{path}")), [])
        self.assertEqual(commands.command_errors(tool("go", "clean", "-modcache", env={"GOMODCACHE": "{path}"})), [])

    def test_placeholders(self):
        """{path}・{name} は要素全体にだけ書ける。{ と } は、ほかには書けない。"""
        self.assertEqual(commands.command_errors(tool("xcrun", "simctl", "delete", "{name}")), [])
        self.assertEqual(commands.command_errors(tool("go", "clean", "-cache", env={"GOCACHE": "{path}"})), [])
        self.assert_rejected_argument("--cache-dir={path}", "{path}")
        self.assert_rejected_argument("{other}", "{path}")


class EnvironmentTest(unittest.TestCase):

    def test_allowed_names(self):
        """組に許可した名前の環境変数は受け付ける (KTD6)。"""
        self.assertEqual(commands.command_errors(tool("go", "clean", "-modcache", env={"GOMODCACHE": "{path}"})), [])
        self.assertEqual(commands.command_errors(tool("brew", "cleanup", env={"HOMEBREW_CACHE": "{path}"})), [])

    def test_other_names_are_rejected(self):
        """組に許可していない名前は、別のプログラムを実行させられるものを含めて拒否する。"""
        for name in ("PATH", "NODE_OPTIONS", "DYLD_INSERT_LIBRARIES", "GOFLAGS", "HOMEBREW_CACHE"):
            with self.subTest(name=name):
                errors = commands.command_errors(tool("go", "clean", "-cache", env={name: "x"}))
                self.assertTrue(any(name in error for error in errors), errors)
        errors = commands.command_errors(tool("npm", "cache", "clean", env={"npm_config_cache": "x"}))
        self.assertTrue(any("npm_config_cache" in error for error in errors), errors)

    def test_env_must_be_an_object(self):
        self.assertTrue(commands.command_errors({"type": "tool", "args": ["brew", "cleanup"], "env": ["X=1"]}))


class CommandShapeTest(unittest.TestCase):

    def test_rm(self):
        self.assertEqual(commands.command_errors({"type": "rm"}), [])
        self.assertTrue(commands.command_errors({"type": "rm", "path": "/tmp/x"}), "rm にほかのキーを書けないこと")

    def test_unknown_type_and_keys(self):
        self.assertTrue(commands.command_errors({"type": "shell", "args": ["brew", "cleanup"]}))
        self.assertTrue(commands.command_errors({"type": "tool", "args": ["brew", "cleanup"], "cwd": "/"}))
        self.assertTrue(commands.command_errors(["brew", "cleanup"]))
        self.assertTrue(commands.command_errors(None))


class AllowedConstantTest(unittest.TestCase):
    """定数 ALLOWED の形 (KTD6)。組ごとに、使ってよい環境変数の名前と、Claude が書ける形と、確認した文書の URL と日付を持つ。"""

    def test_entries(self):
        self.assertTrue(commands.ALLOWED)
        for entry in commands.ALLOWED:
            with self.subTest(pair=entry.get("args")):
                self.assertEqual(set(entry), {"args", "env", "forms", "sources"})
                args = entry["args"]
                self.assertIsInstance(args, tuple)
                self.assertGreaterEqual(len(args), 2, "実行ファイルだけで許可しないこと (KD17)")
                self.assertTrue(all(isinstance(a, str) and a and "/" not in a for a in args))
                self.assertNotIn(args[0], commands.DOMAIN_EXECUTABLES)
                self.assertIsInstance(entry["env"], tuple)
                self.assertTrue(all(re.fullmatch(r"[A-Z_][A-Z0-9_]*", name) for name in entry["env"]))
                self.assertTrue(entry["forms"])
                for form in entry["forms"]:
                    self.assertEqual(set(form), {"args", "env"})
                    self.assertEqual(form["args"][:len(args)], args, "形は組で始まること")
                    self.assertTrue(set(form["env"]) <= set(entry["env"]), "形の環境変数は組に許可した名前だけ")
                    values = list(form["args"]) + list(form["env"].values())
                    self.assertTrue(any(v in commands.PLACEHOLDERS for v in values), "形は項目を {path} か {name} で指すこと")
                self.assertTrue(entry["sources"])
                for source in entry["sources"]:
                    self.assertEqual(set(source), {"url", "checked_on"})
                    self.assertTrue(source["url"].startswith("https://"))
                    datetime.date.fromisoformat(source["checked_on"])

    def test_no_pair_is_a_prefix_of_another(self):
        """組どうしの先頭が重ならない (どの組に当たるかが 1 つに決まる)。"""
        pairs = [entry["args"] for entry in commands.ALLOWED]
        self.assertEqual(len(pairs), len(set(pairs)))
        for left in pairs:
            for right in pairs:
                if left != right:
                    self.assertNotEqual(right[:len(left)], left, f"{left} が {right} の先頭と重なる")


if __name__ == "__main__":
    unittest.main()
