#!/usr/bin/env python3
"""wording-guard の設定と用語ファイルの読み込みのテスト。

標準ライブラリの unittest だけで動く。

  python3 -m unittest discover -s wording-guard/tests
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import wording_lint  # noqa: E402
from wordingguard import config, terms  # noqa: E402

AVOID = """
[[terms]]
pattern = "周回"
verdict = "avoid"
replacements = ["ループ", "繰り返し"]
reason = "処理の繰り返しには通じにくい"
decided_in = "#87"
"""

ALLOW = """
[[terms]]
pattern = "正本"
verdict = "allow"
reason = "唯一の参照元の意味で定着している"
decided_in = "#87"
"""


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(text))
    return path


class TermsTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def terms_file(self, text, name="terms.toml"):
        return write(os.path.join(self.dir, name), text)

    def config_file(self, data):
        path = os.path.join(self.dir, config.CONFIG_RELPATH)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(data if isinstance(data, str) else json.dumps(data))


class TestLoadFile(TermsTestCase):
    def test_avoid_and_allow(self):
        loaded = terms.load_file(self.terms_file(AVOID + ALLOW))
        self.assertEqual([t.pattern for t in loaded], ["周回", "正本"])
        avoid, allow = loaded
        self.assertEqual(avoid.replacements, ("ループ", "繰り返し"))
        self.assertFalse(avoid.autofix)
        self.assertEqual(allow.verdict, "allow")
        self.assertEqual(allow.replacements, ())

    def test_empty_file_has_no_terms(self):
        self.assertEqual(terms.load_file(self.terms_file("")), [])

    def assertTermsError(self, text, *fragments):
        with self.assertRaises(terms.TermsError) as cm:
            terms.load_file(self.terms_file(text))
        for fragment in fragments:
            self.assertIn(fragment, str(cm.exception))

    def test_required_keys(self):
        self.assertTermsError('[[terms]]\npattern = "周回"\nverdict = "avoid"\nreplacements = ["ループ"]\n',
                              "reason を空でない文字列で書く", "decided_in を空でない文字列で書く")

    def test_unknown_verdict(self):
        self.assertTermsError(AVOID.replace('"avoid"', '"deny"'), "verdict は avoid か allow にする")

    def test_unknown_key(self):
        self.assertTermsError(AVOID + 'severity = "error"\n', "知らないキーがある: severity")

    def test_unknown_top_level_key(self):
        self.assertTermsError('version = 1\n' + AVOID, "最上位に置けるのは terms だけ")

    def test_avoid_needs_replacements(self):
        text = AVOID.replace('replacements = ["ループ", "繰り返し"]\n', "")
        self.assertTermsError(text, "replacements (言い換えの候補) を 1 つ以上")

    def test_allow_cannot_have_avoid_keys(self):
        self.assertTermsError(ALLOW + 'replacements = ["参照元"]\n', "許容する語には replacements を書けない")

    def test_autofix_needs_single_replacement(self):
        self.assertTermsError(AVOID + "autofix = true\n", "replacements を 1 つに決める")

    def test_autofix_must_be_bool(self):
        text = AVOID.replace('["ループ", "繰り返し"]', '["ループ"]') + 'autofix = "yes"\n'
        self.assertTermsError(text, "autofix は true か false にする")

    def test_unclosed_regex(self):
        self.assertTermsError(AVOID.replace('"周回"', '"/周回"'), "/ で始まる pattern は正規表現として / で閉じる")

    def test_duplicate_pattern_in_one_file(self):
        self.assertTermsError(AVOID + AVOID, "同じ pattern が 1 番目にもある")

    def test_all_errors_are_reported_together(self):
        text = '[[terms]]\npattern = "a"\nverdict = "x"\n[[terms]]\npattern = "b"\nverdict = "allow"\n'
        with self.assertRaises(terms.TermsError) as cm:
            terms.load_file(self.terms_file(text))
        self.assertIn("1 番目", str(cm.exception))
        self.assertIn("2 番目", str(cm.exception))

    def test_invalid_toml(self):
        self.assertTermsError("[[terms]\n", "TOML として読めない")


class TestLoadAll(TermsTestCase):
    def test_later_file_overrides_same_pattern(self):
        user = self.terms_file(AVOID, "user.toml")
        repo = self.terms_file(AVOID.replace('"avoid"', '"allow"').replace(
            'replacements = ["ループ", "繰り返し"]\n', ""), "repo.toml")
        loaded = terms.load_all([user, repo])
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].verdict, "allow")
        self.assertEqual(loaded[0].source, repo)

    def test_errors_from_all_files(self):
        a = self.terms_file("[[terms]]\n", "a.toml")
        b = self.terms_file("[[terms]]\n", "b.toml")
        with self.assertRaises(terms.TermsError) as cm:
            terms.load_all([a, b])
        self.assertIn("a.toml", str(cm.exception))
        self.assertIn("b.toml", str(cm.exception))


class TestConfig(TermsTestCase):
    def test_missing_config_is_none(self):
        self.assertIsNone(config.load(self.dir))

    def test_invalid_json(self):
        self.config_file("{")
        with self.assertRaises(config.ConfigError):
            config.load(self.dir)

    def test_terms_paths_must_be_string_list(self):
        self.config_file({"terms_paths": "terms.toml"})
        with self.assertRaises(config.ConfigError) as cm:
            config.load(self.dir)
        self.assertIn("terms_paths", str(cm.exception))

    def test_terms_paths_relative_to_root(self):
        path = self.terms_file(AVOID, "conf/terms.toml")
        self.config_file({"terms_paths": ["conf/terms.toml"]})
        self.assertEqual(config.terms_paths(self.dir, config.load(self.dir)), [path])

    def test_terms_paths_missing_file_is_error(self):
        self.config_file({"terms_paths": ["missing.toml"]})
        with self.assertRaises(config.ConfigError) as cm:
            config.terms_paths(self.dir, config.load(self.dir))
        self.assertIn("missing.toml", str(cm.exception))

    def test_terms_paths_expands_home(self):
        home = os.path.join(self.dir, "home")
        path = write(os.path.join(home, "terms.toml"), AVOID)
        self.config_file({"terms_paths": ["~/terms.toml"]})
        old = os.environ.get("HOME")
        os.environ["HOME"] = home
        try:
            self.assertEqual(config.terms_paths(self.dir, config.load(self.dir)), [path])
        finally:
            if old is None:
                os.environ.pop("HOME")
            else:
                os.environ["HOME"] = old

    def test_find_root(self):
        subprocess.run(["git", "init", "-q", self.dir], check=True)
        sub = os.path.join(self.dir, "a", "b")
        os.makedirs(sub)
        expected = os.path.realpath(self.dir)
        self.assertEqual(os.path.realpath(config.find_root(sub)), expected)
        # これから作るファイル (まだ無いパス) でも、存在する祖先から探す
        self.assertEqual(os.path.realpath(config.find_root(os.path.join(sub, "new", "x.md"))), expected)

    def test_find_root_outside_repository(self):
        self.assertIsNone(config.find_root(self.dir))


class TestTermsCommand(TermsTestCase):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = wording_lint.main(["terms", "--root", self.dir, *args])
        return code, out.getvalue(), err.getvalue()

    def test_not_configured(self):
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("用語ファイルは設定されていない", out)

    def test_json_output(self):
        self.terms_file(AVOID + ALLOW)
        self.config_file({"terms_paths": ["terms.toml"]})
        code, out, _ = self.run_cli("--format", "json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertTrue(data["configured"])
        self.assertEqual([t["verdict"] for t in data["terms"]], ["avoid", "allow"])
        self.assertNotIn("replacements", data["terms"][1])

    def test_text_output(self):
        self.terms_file(AVOID + ALLOW)
        self.config_file({"terms_paths": ["terms.toml"]})
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("- 周回 → ループ / 繰り返し (自動修正しない)", out)
        self.assertIn("許容する語 (1 件)", out)

    def test_terms_error_exit_code(self):
        self.terms_file("[[terms]]\n")
        self.config_file({"terms_paths": ["terms.toml"]})
        code, _, err = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn("pattern を空でない文字列で書く", err)


if __name__ == "__main__":
    unittest.main()
