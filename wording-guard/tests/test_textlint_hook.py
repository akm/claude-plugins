#!/usr/bin/env python3
"""用語ファイルから textlint の設定を作る処理と、hook の判断のテスト。

textlint そのもの (Node のパッケージ) は CI の環境に無いので、textlint の実行はテストで差し替える。
textlint を実際に実行する確認は、ファイル wording-guard/skills/wording-guard/references/textlint.md の
「動作の確認」の手順で行う。

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
from wordingguard import config, hook, terms, textlint  # noqa: E402

TERMS = """
[[terms]]
pattern = "/効(く|かない)/"
verdict = "avoid"
replacements = ["適用される", "機能する"]
reason = "何がどう働くかを書く"
decided_in = "#35"

[[terms]]
pattern = "同じ型の"
verdict = "avoid"
replacements = ["同じ種類の"]
autofix = true
reason = "type の直訳"
decided_in = "#35"

[[terms]]
pattern = "/触(る|ら|れ)/"
verdict = "avoid"
replacements = ["変更する"]
exceptions = ["触れるに留める"]
reason = "口語"
decided_in = "#35"

[[terms]]
pattern = "正本"
verdict = "allow"
reason = "唯一の参照元の意味で使う"
decided_in = "#87"
"""


class RepoTestCase(unittest.TestCase):
    """一時ディレクトリに git リポジトリを作り、設定と用語ファイルを置くテストの基底。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._tmp.name)
        subprocess.run(["git", "init", "-q", self.root], check=True)
        self.write(".claude/akm-claude-plugins/wording-guard/terms.toml", TERMS)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text if rel.endswith(".json") else textwrap.dedent(text))
        return path

    def configure(self, **extra):
        data = {"terms_paths": [".claude/akm-claude-plugins/wording-guard/terms.toml"]}
        data.update(extra)
        self.write(config.CONFIG_RELPATH, json.dumps(data))
        return config.load(self.root)

    def term_list(self):
        return terms.load_file(os.path.join(self.root, ".claude/akm-claude-plugins/wording-guard/terms.toml"))


class TestConversion(RepoTestCase):
    def test_to_prh_splits_autofix(self):
        fix, detect = terms.to_prh(self.term_list())
        self.assertEqual([r["pattern"] for r in fix], ["同じ型の"])
        self.assertEqual([r["pattern"] for r in detect], ["/効(く|かない)/", "/触(る|ら|れ)/"])
        self.assertEqual(detect[0]["expected"], "適用される")
        self.assertEqual(detect[0]["prh"], "何がどう働くかを書く (言い換えの候補: 適用される・機能する。決めた場所: #35)")

    def test_to_allowlist_has_allowed_terms_and_exceptions(self):
        self.assertEqual(terms.to_allowlist(self.term_list()), ["触れるに留める", "正本"])


class TestConfigTextlint(RepoTestCase):
    def assertConfigError(self, data, fragment):
        self.write(config.CONFIG_RELPATH, json.dumps(data))
        with self.assertRaises(config.ConfigError) as cm:
            config.load(self.root)
        self.assertIn(fragment, str(cm.exception))

    def test_textlint_must_be_object(self):
        self.assertConfigError({"textlint": True}, "キー textlint はオブジェクトにする")

    def test_textlint_unknown_key(self):
        self.assertConfigError({"textlint": {"rules": {}}}, "知らないキーがある: rules")

    def test_hook_must_be_bool(self):
        self.assertConfigError({"textlint": {"hook": "yes"}}, "textlint.hook は true か false にする")

    def test_textlint_config_path_missing(self):
        cfg = self.configure(textlint={"config": "missing.json"})
        with self.assertRaises(config.ConfigError) as cm:
            config.textlint_config_path(self.root, cfg)
        self.assertIn("missing.json", str(cm.exception))

    def test_is_frozen(self):
        cfg = self.configure(frozen_paths=["docs/old/"])
        self.assertTrue(config.is_frozen(self.root, cfg, os.path.join(self.root, "docs/old/a.md")))
        self.assertFalse(config.is_frozen(self.root, cfg, os.path.join(self.root, "docs/new/a.md")))
        self.assertFalse(config.is_frozen(self.root, cfg, "/elsewhere/docs/old/a.md"))


class TestCompose(RepoTestCase):
    def compose(self, cfg, fix_only=False):
        work = os.path.join(self.root, "work")
        os.makedirs(work, exist_ok=True)
        path, has_rules = textlint.compose(self.root, cfg, self.term_list(), work, fix_only=fix_only)
        with open(path, encoding="utf-8") as f:
            return json.load(f), has_rules, work

    def test_merges_repository_config(self):
        base = {
            "rules": {"preset-ja-no-ai-slop": {"sentence-connection": False},
                      "prh": {"rulePaths": ["dict/own.yml"]}},
            "filters": {"allowlist": {"allow": ["既存"], "allowlistConfigPaths": ["allow.yml"]},
                        "node-types": {"nodeTypes": ["CodeBlock"]}},
        }
        self.write("conf/textlintrc.json", json.dumps(base))
        cfg = self.configure(textlint={"config": "conf/textlintrc.json"})
        composed, has_rules, work = self.compose(cfg)
        self.assertTrue(has_rules)
        self.assertEqual(composed["rules"]["preset-ja-no-ai-slop"], {"sentence-connection": False})
        self.assertEqual(composed["rules"]["prh"]["rulePaths"], [
            os.path.join(self.root, "conf", "dict/own.yml"),
            os.path.join(work, "prh-fix.yml"), os.path.join(work, "prh-detect.yml")])
        allowlist = composed["filters"]["allowlist"]
        self.assertEqual(allowlist["allow"], ["既存", "触れるに留める", "正本"])
        self.assertEqual(allowlist["allowlistConfigPaths"], [os.path.join(self.root, "conf", "allow.yml")])
        self.assertEqual(composed["filters"]["node-types"]["nodeTypes"], ["CodeBlock", "BlockQuote"])
        with open(os.path.join(work, "prh-detect.yml"), encoding="utf-8") as f:
            self.assertEqual([r["pattern"] for r in json.load(f)["rules"]], ["/効(く|かない)/", "/触(る|ら|れ)/"])

    def test_fix_only_uses_autofix_terms_only(self):
        self.write("conf/textlintrc.json", json.dumps({"rules": {"ja-no-redundant-expression": True}}))
        cfg = self.configure(textlint={"config": "conf/textlintrc.json"})
        composed, has_rules, work = self.compose(cfg, fix_only=True)
        self.assertTrue(has_rules)
        self.assertEqual(list(composed["rules"]), ["prh"])
        self.assertEqual(composed["rules"]["prh"]["rulePaths"], [os.path.join(work, "prh-fix.yml")])
        self.assertIn("BlockQuote", composed["filters"]["node-types"]["nodeTypes"])

    def test_disabled_prh_is_error(self):
        self.write("conf/textlintrc.json", json.dumps({"rules": {"prh": False}}))
        cfg = self.configure(textlint={"config": "conf/textlintrc.json"})
        with self.assertRaises(config.ConfigError) as cm:
            self.compose(cfg)
        self.assertIn("規則 prh を無効にしている", str(cm.exception))

    def test_no_rules(self):
        self.write(".claude/akm-claude-plugins/wording-guard/terms.toml", "")
        cfg = self.configure(textlint={})
        _, has_rules, _ = self.compose(cfg)
        self.assertFalse(has_rules)


class TestFinding(unittest.TestCase):
    def test_matched_uses_fix_range(self):
        f = textlint._finding({"ruleId": "prh", "severity": 2, "message": "m", "line": 1, "column": 3,
                               "range": [2, 3], "fix": {"range": [2, 6], "text": "x"}}, "設定同じ型のもの")
        self.assertEqual(f["matched"], "同じ型の")
        self.assertEqual(f["severity"], "error")

    def test_single_character_range_is_not_shown(self):
        f = textlint._finding({"ruleId": "r", "severity": 1, "message": "m", "range": [0, 1]}, "レビューを行う")
        self.assertEqual(f["matched"], "")
        self.assertEqual(f["severity"], "warning")


class TestEnsureInstalled(unittest.TestCase):
    def test_missing_textlint_names_setup_command(self):
        with tempfile.TemporaryDirectory() as d:
            old = os.environ.get(textlint.CACHE_ENV)
            os.environ[textlint.CACHE_ENV] = d
            try:
                with self.assertRaises(textlint.TextlintError) as cm:
                    textlint.ensure_installed()
            finally:
                if old is None:
                    os.environ.pop(textlint.CACHE_ENV)
                else:
                    os.environ[textlint.CACHE_ENV] = old
        self.assertIn("wording_lint.py setup", str(cm.exception))
        self.assertIn(d, str(cm.exception))


FAKE_NPM = """#!/bin/sh
# テストで npm の代わりに置くスクリプト。FAKE_NPM_MODE で振る舞いを変える。
case "$FAKE_NPM_MODE" in
  fail) echo "npm ERR! fake" >&2; exit 1 ;;
  race) mkdir -p "$FAKE_NPM_DEST/node_modules/.bin" && touch "$FAKE_NPM_DEST/node_modules/.bin/textlint" ;;
esac
mkdir -p node_modules/.bin && touch node_modules/.bin/textlint
echo called >> "$FAKE_NPM_LOG"
"""


class TestSetup(unittest.TestCase):
    """npm を差し替えて、setup の置き場の状態ごとの扱いを確かめる。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = self._tmp.name
        self.cache = os.path.join(base, "cache")
        bindir = os.path.join(base, "bin")
        os.makedirs(bindir)
        npm = os.path.join(bindir, "npm")
        with open(npm, "w", encoding="utf-8") as f:
            f.write(FAKE_NPM)
        os.chmod(npm, 0o755)
        self.log = os.path.join(base, "npm.log")
        self._saved = {k: os.environ.get(k) for k in
                       ("PATH", textlint.CACHE_ENV, "FAKE_NPM_MODE", "FAKE_NPM_DEST", "FAKE_NPM_LOG")}
        os.environ["PATH"] = bindir + os.pathsep + os.environ.get("PATH", "")
        os.environ[textlint.CACHE_ENV] = self.cache
        os.environ["FAKE_NPM_LOG"] = self.log
        os.environ.pop("FAKE_NPM_MODE", None)
        self.dest = textlint.install_dir()
        os.environ["FAKE_NPM_DEST"] = self.dest

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    def setup_quietly(self):
        return textlint.setup(out=io.StringIO())

    def npm_calls(self):
        if not os.path.exists(self.log):
            return 0
        with open(self.log, encoding="utf-8") as f:
            return len(f.read().split())

    def leftovers(self):
        return [n for n in os.listdir(self.cache) if n != os.path.basename(self.dest)]

    def test_installs_and_leaves_no_work_directory(self):
        self.assertEqual(self.setup_quietly(), self.dest)
        self.assertTrue(os.path.exists(textlint.textlint_bin(self.dest)))
        self.assertEqual(self.leftovers(), [])
        # 2 度目は取得しない
        self.setup_quietly()
        self.assertEqual(self.npm_calls(), 1)

    def test_broken_install_directory_stops_before_npm(self):
        os.makedirs(os.path.join(self.dest, "node_modules"))
        with self.assertRaises(textlint.TextlintError) as cm:
            self.setup_quietly()
        self.assertIn("置き場が壊れている", str(cm.exception))
        self.assertIn("rm -rf", str(cm.exception))
        self.assertEqual(self.npm_calls(), 0)
        self.assertTrue(os.path.isdir(self.dest))

    def test_concurrent_setup_finished_first(self):
        os.environ["FAKE_NPM_MODE"] = "race"
        self.assertEqual(self.setup_quietly(), self.dest)
        self.assertTrue(os.path.exists(textlint.textlint_bin(self.dest)))
        self.assertEqual(self.leftovers(), [])

    def test_npm_failure_is_textlint_error(self):
        os.environ["FAKE_NPM_MODE"] = "fail"
        with self.assertRaises(textlint.TextlintError) as cm:
            self.setup_quietly()
        self.assertIn("npm ci が失敗した", str(cm.exception))
        self.assertFalse(os.path.exists(self.dest))
        self.assertEqual(self.leftovers(), [])

    def test_os_error_is_textlint_error(self):
        # キャッシュの親をファイルにして、ディレクトリを作れないようにする
        os.makedirs(os.path.dirname(self.cache), exist_ok=True)
        with open(self.cache, "w", encoding="utf-8") as f:
            f.write("not a directory")
        with self.assertRaises(textlint.TextlintError) as cm:
            self.setup_quietly()
        self.assertIn("セットアップに失敗した", str(cm.exception))


def finding(rule, message, matched, severity="error", line=1, column=1):
    return {"rule": rule, "severity": severity, "message": message, "line": line, "column": column,
            "matched": matched}


KIKU = finding("prh", "効く => 適用される\n何がどう働くかを書く", "効く")
KATA = finding("prh", "同じ型の => 同じ種類の\ntype の直訳", "同じ型の")
REDUNDANT = finding("ja-no-redundant-expression", "冗長な表現です", "", severity="warning")


class TestIntroduced(unittest.TestCase):
    def test_only_new_findings(self):
        self.assertEqual(hook.introduced([KIKU], [KIKU, KATA]), [KATA])

    def test_counts_duplicates(self):
        self.assertEqual(hook.introduced([KIKU], [KIKU, KIKU]), [KIKU])


class TestHook(RepoTestCase):
    def event(self, tool="Edit", path="docs/a.md", **tool_input):
        tool_input.setdefault("file_path", os.path.join(self.root, path))
        return {"tool_name": tool, "tool_input": tool_input}

    def fake(self, results):
        calls = []

        def check_texts(root, cfg, term_list, texts, filename="text.md"):
            calls.append((texts, filename, [t.pattern for t in term_list]))
            return results

        return check_texts, calls

    def not_called(self, *args, **kwargs):
        raise AssertionError("textlint を実行してはいけない")

    def test_not_configured(self):
        self.assertIsNone(hook.handle(self.event(old_string="a", new_string="b"), self.not_called))

    def test_hook_disabled(self):
        self.configure(textlint={"hook": False})
        self.assertIsNone(hook.handle(self.event(old_string="a", new_string="b"), self.not_called))

    def test_not_markdown(self):
        self.configure(textlint={"hook": True})
        self.assertIsNone(hook.handle(self.event(path="a.go", old_string="a", new_string="b"), self.not_called))

    def test_frozen_path(self):
        self.configure(textlint={"hook": True}, frozen_paths=["docs/"])
        self.assertIsNone(hook.handle(self.event(old_string="a", new_string="b"), self.not_called))

    def test_outside_repository(self):
        with tempfile.TemporaryDirectory() as d:
            event = {"tool_name": "Write", "tool_input": {"file_path": os.path.join(d, "a.md"), "content": "x"}}
            self.assertIsNone(hook.handle(event, self.not_called))

    def test_error_blocks_and_ignores_existing_findings(self):
        self.configure(textlint={"hook": True})
        check, calls = self.fake([[KIKU], [KIKU, KATA]])
        out = hook.handle(self.event(old_string="ここでも効く。", new_string="ここでも効く。\n同じ型の指摘。"), check)
        self.assertEqual(out["decision"], "block")
        self.assertIn("「同じ型の」", out["reason"])
        self.assertNotIn("「効く」", out["reason"])
        texts, filename, patterns = calls[0]
        self.assertEqual(texts, ["ここでも効く。", "ここでも効く。\n同じ型の指摘。"])
        self.assertEqual(filename, "a.md")
        self.assertIn("正本", patterns)

    def test_warning_only_is_additional_context(self):
        self.configure(textlint={"hook": True})
        check, _ = self.fake([[], [REDUNDANT]])
        out = hook.handle(self.event(old_string="x", new_string="レビューを行う。"), check)
        self.assertNotIn("decision", out)
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PostToolUse")
        self.assertIn("冗長な表現です", out["hookSpecificOutput"]["additionalContext"])

    def test_no_new_findings(self):
        self.configure(textlint={"hook": True})
        check, _ = self.fake([[KIKU], [KIKU]])
        self.assertIsNone(hook.handle(self.event(old_string="効く。A", new_string="効く。B"), check))

    def test_multi_edit_and_write_pairs(self):
        self.configure(textlint={"hook": True})
        check, calls = self.fake([[], [KATA], [], []])
        edits = [{"old_string": "a", "new_string": "同じ型の"}, {"old_string": "b", "new_string": "c"}]
        out = hook.handle(self.event(tool="MultiEdit", edits=edits), check)
        self.assertEqual(calls[0][0], ["a", "同じ型の", "b", "c"])
        self.assertEqual(out["decision"], "block")
        check, calls = self.fake([[], []])
        hook.handle(self.event(tool="Write", content="全体"), check)
        self.assertEqual(calls[0][0], ["", "全体"])

    def test_terms_error_is_reported(self):
        self.configure(textlint={"hook": True})
        self.write(".claude/akm-claude-plugins/wording-guard/terms.toml", "[[terms]]\n")
        out = hook.handle(self.event(old_string="a", new_string="b"), self.not_called)
        self.assertEqual(out["decision"], "block")
        self.assertIn("検査できなかった", out["reason"])
        self.assertIn("pattern を空でない文字列で書く", out["systemMessage"])

    def test_textlint_error_is_reported(self):
        self.configure(textlint={"hook": True})

        def broken(*args, **kwargs):
            raise textlint.TextlintError("textlint が入っていない")

        out = hook.handle(self.event(old_string="a", new_string="b"), broken)
        self.assertIn("textlint が入っていない", out["systemMessage"])
        self.assertIn("人間の承認を得てから実行する", out["reason"])


class TestCheckCommand(RepoTestCase):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = wording_lint.main([*args, "--root", self.root])
        return code, out.getvalue(), err.getvalue()

    def test_check_requires_textlint_setting(self):
        self.configure()
        self.write("a.md", "x")
        code, _, err = self.run_cli("check", os.path.join(self.root, "a.md"))
        self.assertEqual(code, 2)
        self.assertIn("textlint は設定されていない", err)

    def test_check_without_textlint_installed(self):
        self.configure(textlint={})
        self.write("a.md", "x")
        with tempfile.TemporaryDirectory() as d:
            old = os.environ.get(textlint.CACHE_ENV)
            os.environ[textlint.CACHE_ENV] = d
            try:
                code, _, err = self.run_cli("check", os.path.join(self.root, "a.md"))
            finally:
                if old is None:
                    os.environ.pop(textlint.CACHE_ENV)
                else:
                    os.environ[textlint.CACHE_ENV] = old
        self.assertEqual(code, 3)
        self.assertIn("textlint が入っていない", err)


if __name__ == "__main__":
    unittest.main()
