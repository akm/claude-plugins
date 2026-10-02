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
import time
import unittest
from unittest import mock

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
        base = {"rules": {"ja-no-redundant-expression": True, "prh": {"rulePaths": ["own.yml"]}},
                "filters": {"allowlist": {"allow": ["/「[^」\\n]*」/"]}},
                "plugins": {"markdown": True}}
        self.write("conf/textlintrc.json", json.dumps(base))
        cfg = self.configure(textlint={"config": "conf/textlintrc.json"})
        composed, has_rules, work = self.compose(cfg, fix_only=True)
        self.assertTrue(has_rules)
        # 規則は自動修正してよい辞書だけ (リポジトリの規則と、利用者が書いた prh の辞書は入れない)
        self.assertEqual(list(composed["rules"]), ["prh"])
        self.assertEqual(composed["rules"]["prh"]["rulePaths"], [os.path.join(work, "prh-fix.yml")])
        # 規則以外のリポジトリの設定 (検出から除く範囲など) はそのまま使う
        self.assertEqual(composed["filters"]["allowlist"]["allow"][0], "/「[^」\\n]*」/")
        self.assertEqual(composed["plugins"], {"markdown": True})
        self.assertIn("BlockQuote", composed["filters"]["node-types"]["nodeTypes"])

    def test_disabled_prh_is_error(self):
        self.write("conf/textlintrc.json", json.dumps({"rules": {"prh": False}}))
        cfg = self.configure(textlint={"config": "conf/textlintrc.json"})
        with self.assertRaises(config.ConfigError) as cm:
            self.compose(cfg)
        self.assertIn("規則 prh を無効にしている", str(cm.exception))

    def test_prh_without_dictionaries_is_removed(self):
        # リポジトリの設定が規則 prh を宣言し、用語ファイルに避ける語が無い (許容する語だけ)
        self.write(".claude/akm-claude-plugins/wording-guard/terms.toml",
                   '[[terms]]\npattern = "正本"\nverdict = "allow"\nreason = "r"\ndecided_in = "#87"\n')
        self.write("conf/textlintrc.json", json.dumps({"rules": {"prh": {}}}))
        cfg = self.configure(textlint={"config": "conf/textlintrc.json"})
        composed, has_rules, _ = self.compose(cfg)
        self.assertNotIn("prh", composed["rules"])
        self.assertFalse(has_rules)
        self.write("conf/textlintrc.json", json.dumps({"rules": {"prh": {}, "ja-no-redundant-expression": True}}))
        composed, has_rules, _ = self.compose(cfg)
        self.assertEqual(list(composed["rules"]), ["ja-no-redundant-expression"])
        self.assertTrue(has_rules)

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

    def test_info_severity(self):
        # textlint の重大度は 1 = warning・2 = error・3 = info
        f = textlint._finding({"ruleId": "r", "severity": 3, "message": "m", "range": [0, 3]}, "レビューを行う")
        self.assertEqual(f["severity"], "info")

    def test_unknown_severity_is_error(self):
        for value in (0, 4, None):
            with self.assertRaises(textlint.TextlintError):
                textlint._finding({"ruleId": "r", "severity": value, "message": "m"}, "x")

    def test_range_is_utf16_offset(self):
        # 🐛 は UTF-16 では 2 単位なので、「同じ型の」は UTF-16 の [3, 7)、Python の文字列では [2, 6)
        source = "🐛 同じ型の指摘"
        f = textlint._finding({"ruleId": "prh", "severity": 2, "message": "m", "range": [3, 4],
                               "fix": {"range": [3, 7], "text": "同じ種類の"}}, source)
        self.assertEqual(f["matched"], "同じ型の")
        self.assertEqual(f["start"], 2)
        self.assertEqual(f["end"], 6)

    def test_single_character_range_is_not_shown(self):
        f = textlint._finding({"ruleId": "r", "severity": 1, "message": "m", "range": [0, 1]}, "レビューを行う")
        self.assertEqual(f["matched"], "")
        self.assertEqual(f["severity"], "warning")

    def test_utf16_indexer_matches_counting_from_start(self):
        def counted(text, offset):
            units = 0
            for index, ch in enumerate(text):
                if units >= offset:
                    return index
                units += 2 if ord(ch) > 0xFFFF else 1
            return len(text)

        for text in ("", "abc", "🐛 同じ型の指摘", "a🐛b🐛🐛c"):
            to_index = textlint._utf16_indexer(text)
            for offset in range(-1, len(text.encode("utf-16-le")) // 2 + 3):
                self.assertEqual(to_index(offset), counted(text, offset), f"{text!r} の位置 {offset}")

    def test_check_texts_converts_many_findings_in_large_text_quickly(self):
        # 位置の表は文字列ごとに 1 回だけ作る。検出ごとに先頭から数え直すと、この大きさでは数十秒かかる
        text = "🐛" + ("あ" * 99 + "\n") * 2000
        end = len(text.encode("utf-16-le")) // 2
        messages = [{"ruleId": "r", "severity": 1, "message": "m", "range": [end - 4, end - 2]}] * 500

        def run(directory, conf, paths, cwd):
            return [{"filePath": p, "messages": messages} for p in paths]

        with mock.patch.object(textlint, "ensure_installed", return_value="dir"), \
                mock.patch.object(textlint, "compose", return_value=("conf.json", True)), \
                mock.patch.object(textlint, "_run_textlint", side_effect=run):
            started = time.monotonic()
            results = textlint.check_texts("root", {}, [], [text, text])
            elapsed = time.monotonic() - started
        self.assertEqual(len(results[1]), 500)
        self.assertEqual(results[1][0]["matched"], "ああ")
        self.assertLess(elapsed, 5)


class TestRunTextlint(unittest.TestCase):
    """textlint を差し替えて、実行の結果の扱いを確かめる。"""

    def run_fake(self, script):
        with tempfile.TemporaryDirectory() as d:
            binary = textlint.textlint_bin(d)
            os.makedirs(os.path.dirname(binary))
            with open(binary, "w", encoding="utf-8") as f:
                f.write("#!/bin/sh\n" + script)
            os.chmod(binary, 0o755)
            return textlint._run_textlint(d, "conf.json", ["a.md"], cwd=d)

    def test_empty_output_with_exit_1_is_error(self):
        # 規則が例外で終わったときの textlint の形 (標準出力が空のまま終了コード 1)
        with self.assertRaises(textlint.TextlintError) as cm:
            self.run_fake('echo "Unexpected error during file processing" >&2\nexit 1\n')
        self.assertIn("Unexpected error during file processing", str(cm.exception))

    def test_empty_output_with_exit_0_is_error(self):
        with self.assertRaises(textlint.TextlintError):
            self.run_fake("exit 0\n")

    def test_json_with_exit_1_is_result(self):
        result = self.run_fake("echo '[{\"filePath\": \"a.md\", \"messages\": []}]'\nexit 1\n")
        self.assertEqual(result, [{"filePath": "a.md", "messages": []}])


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


class TestExcerpt(unittest.TestCase):
    def test_uses_start_not_column(self):
        text = "一行目\n🐛🐛 ここで効く。\n三行目"
        start = text.index("効く")
        # column は UTF-16 の単位なので、Python の文字列の位置とずれる。抜き出しは start を使う
        excerpt = hook._excerpt(text, {"start": start, "line": 2, "column": 99})
        self.assertEqual(excerpt, "🐛🐛 ここで効く。")
        self.assertEqual(hook._excerpt(text, {"start": None}), "")


class TestIntroduced(unittest.TestCase):
    def test_only_new_findings(self):
        self.assertEqual(hook.introduced([KIKU], [KIKU, KATA]), [KATA])

    def test_counts_duplicates(self):
        self.assertEqual(hook.introduced([KIKU], [KIKU, KIKU]), [KIKU])


class TestChangedLines(unittest.TestCase):
    def test_inserted_line_has_empty_before_range(self):
        self.assertEqual(hook.changed_line_ranges("a\nb\nc\n", "a\nX\nb\nc\n"), ([(1, 1)], [(1, 2)]))

    def test_replaced_line(self):
        self.assertEqual(hook.changed_line_ranges("a\nb\nc\n", "a\nB\nc\n"), ([(1, 2)], [(1, 2)]))

    def test_new_file(self):
        self.assertEqual(hook.changed_line_ranges("", "a\nb\n"), ([(0, 0)], [(0, 2)]))

    def test_in_lines_uses_start_and_end(self):
        text = "一行目\n長い文の\n続き。\n四行目\n"
        long = {"rule": "sentence-length", "start": text.index("長い"), "end": text.index("。") + 1, "line": 2}
        head = {"rule": "r", "start": 0, "end": 3, "line": 1}
        # 長い文は 2 行目から 3 行目にまたがるので、3 行目だけを書き換えても重なる
        self.assertEqual(hook.in_lines(text, [long, head], [(2, 3)]), [long])
        self.assertEqual(hook.in_lines(text, [long, head], [(3, 4)]), [])

    def test_in_lines_without_start_uses_line(self):
        self.assertEqual(hook.in_lines("a\nb\n", [KATA], [(0, 1)]), [KATA])
        self.assertEqual(hook.in_lines("a\nb\n", [KATA], [(1, 2)]), [])


class TestHook(RepoTestCase):
    def event(self, tool="Edit", path="docs/a.md", tool_response=None, **tool_input):
        tool_input.setdefault("file_path", os.path.join(self.root, path))
        event = {"tool_name": tool, "tool_input": tool_input}
        if tool_response is not None:
            event["tool_response"] = tool_response
        return event

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

    def test_multi_edit_is_not_a_target(self):
        # MultiEdit は Claude Code 2.0 で無くなったツールなので、入力が来ても何もしない
        self.configure(textlint={"hook": True})
        event = self.event(tool="MultiEdit", edits=[{"old_string": "a", "new_string": "同じ型の"}])
        self.assertIsNone(hook.handle(event, self.not_called))

    def test_frozen_path(self):
        self.configure(textlint={"hook": True}, frozen_paths=["docs/"])
        self.assertIsNone(hook.handle(self.event(old_string="a", new_string="b"), self.not_called))

    def test_outside_repository(self):
        with tempfile.TemporaryDirectory() as d:
            event = {"tool_name": "Write", "tool_input": {"file_path": os.path.join(d, "a.md"), "content": "x"}}
            self.assertIsNone(hook.handle(event, self.not_called))

    def test_error_blocks_and_ignores_existing_findings(self):
        self.configure(textlint={"hook": True})
        self.write("docs/a.md", "前の行。\nここでも効く。\n同じ型の指摘。\n")
        kiku = finding("prh", KIKU["message"], "効く", line=2)
        kata = finding("prh", KATA["message"], "同じ型の", line=3)
        check, calls = self.fake([[kiku], [kiku, kata]])
        out = hook.handle(self.event(old_string="ここでも効く。", new_string="ここでも効く。\n同じ型の指摘。",
                                     tool_response={"originalFile": "前の行。\nここでも効く。\n"}), check)
        self.assertEqual(out["decision"], "block")
        self.assertIn("「同じ型の」", out["reason"])
        self.assertNotIn("「効く」", out["reason"])
        texts, filename, patterns = calls[0]
        # 書き換える前 (tool_response の originalFile) と後 (ディスク) のファイルの全体を比べる
        self.assertEqual(texts, ["前の行。\nここでも効く。\n", "前の行。\nここでも効く。\n同じ型の指摘。\n"])
        self.assertEqual(filename, "a.md")
        self.assertIn("正本", patterns)

    def test_findings_outside_changed_lines_are_not_returned(self):
        # message に行番号を入れる規則 (sentence-length) は、前に行を足すと既存の検出の message が変わる。
        # 書き換えた行の外の検出は比べないので、返らない
        self.configure(textlint={"hook": True})
        self.write("docs/a.md", "見出し。\n足した行。\n\n長い文。\n")
        before = finding("sentence-length", "Line 3 sentence length(47) exceeds the maximum sentence length of 40.", "長い文。", line=3)
        after = finding("sentence-length", "Line 4 sentence length(47) exceeds the maximum sentence length of 40.", "長い文。", line=4)
        check, _ = self.fake([[before], [after]])
        self.assertIsNone(hook.handle(self.event(old_string="見出し。", new_string="見出し。\n足した行。",
                                                 tool_response={"originalFile": "見出し。\n\n長い文。\n"}), check))

    def test_only_finding_on_changed_line_is_returned(self):
        # message にファイル全体の件数を入れる規則 (no-mix-dearu-desumasu) では、既存の検出の message も変わるが、
        # 書き換えた行にある検出だけを返す
        self.configure(textlint={"hook": True})
        self.write("docs/a.md", "である。\nです。\nである。\n")
        old = finding("no-mix-dearu-desumasu", "混在: です\nTotal:\nである  : 1\nですます: 1", "です", line=2)
        existing = finding("no-mix-dearu-desumasu", "混在: です\nTotal:\nである  : 2\nですます: 1", "です", line=2)
        added = finding("no-mix-dearu-desumasu", "混在: である\nTotal:\nである  : 2\nですます: 1", "である", line=3)
        check, _ = self.fake([[old], [existing, added]])
        out = hook.handle(self.event(old_string="です。", new_string="です。\nである。",
                                     tool_response={"originalFile": "である。\nです。\n"}), check)
        self.assertIn("「である」", out["reason"])
        self.assertNotIn("「です」", out["reason"])

    def test_code_block_keeps_its_context(self):
        # コードブロックの中の行を書き換えても、囲みの ``` を含むファイルの全体を渡す
        self.configure(textlint={"hook": True})
        self.write("docs/a.md", "本文。\n\n```toml\npattern = \"同じ型の\"\n```\n")
        check, calls = self.fake([[], []])
        before = "本文。\n\n```toml\npattern = \"x\"\n```\n"
        self.assertIsNone(hook.handle(self.event(old_string='pattern = "x"', new_string='pattern = "同じ型の"',
                                                 tool_response={"originalFile": before}), check))
        self.assertEqual(calls[0][0], [before, "本文。\n\n```toml\npattern = \"同じ型の\"\n```\n"])

    def test_edit_that_changed_quotes_is_checked(self):
        # Edit は引用符をファイルに合わせて書くので、ファイルにツールの入力 (new_string) どおりの文字列が無いことがある
        self.configure(textlint={"hook": True})
        self.write("docs/a.md", "He said “hello world”.\n")
        check, calls = self.fake([[], []])
        self.assertIsNone(hook.handle(self.event(old_string='"hello"', new_string='"hello world"',
                                                 tool_response={"originalFile": "He said “hello”.\n"}), check))
        self.assertEqual(calls[0][0], ["He said “hello”.\n", "He said “hello world”.\n"])

    def test_warning_only_is_additional_context(self):
        self.configure(textlint={"hook": True})
        self.write("docs/a.md", "レビューを行う。\n")
        check, _ = self.fake([[], [REDUNDANT]])
        out = hook.handle(self.event(old_string="x", new_string="レビューを行う。",
                                     tool_response={"originalFile": "x\n"}), check)
        self.assertNotIn("decision", out)
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PostToolUse")
        self.assertIn("冗長な表現です", out["hookSpecificOutput"]["additionalContext"])

    def test_no_new_findings(self):
        self.configure(textlint={"hook": True})
        self.write("docs/a.md", "効く。B\n")
        check, _ = self.fake([[KIKU], [KIKU]])
        self.assertIsNone(hook.handle(self.event(old_string="効く。A", new_string="効く。B",
                                                 tool_response={"originalFile": "効く。A\n"}), check))

    def test_write_compares_with_original_file(self):
        self.configure(textlint={"hook": True})
        self.write("docs/a.md", "前からある文。\n足した文。\n")
        check, calls = self.fake([[], []])
        hook.handle(self.event(tool="Write", content="前からある文。\n足した文。\n",
                               tool_response={"type": "update", "originalFile": "前からある文。\n"}), check)
        self.assertEqual(calls[0][0], ["前からある文。\n", "前からある文。\n足した文。\n"])

    def test_write_new_file_checks_whole_content(self):
        self.configure(textlint={"hook": True})
        self.write("docs/a.md", "全体\n")
        check, calls = self.fake([[], []])
        hook.handle(self.event(tool="Write", content="全体\n", tool_response={"type": "create", "originalFile": None}), check)
        self.assertEqual(calls[0][0], ["", "全体\n"])

    def test_staged_edit_does_nothing(self):
        # 書き込みを保留した (ファイルは変わっていない) ときは検査しない
        self.configure(textlint={"hook": True})
        event = self.event(old_string="a", new_string="b", tool_response={"originalFile": "a\n", "staged": True})
        self.assertIsNone(hook.handle(event, self.not_called))

    def test_missing_original_file_is_reported(self):
        # 書き換える前の内容が分からないときは、ツールの入力から組み立てずに知らせる
        self.configure(textlint={"hook": True})
        self.write("docs/a.md", "b\n")
        for response in (None, {}, {"type": "text", "text": "ok"}):
            out = hook.handle(self.event(old_string="a", new_string="b", tool_response=response), self.not_called)
            self.assertEqual(out["decision"], "block")
            self.assertIn("originalFile が無い", out["systemMessage"])

    def test_null_original_file_of_existing_file_is_reported(self):
        self.configure(textlint={"hook": True})
        self.write("docs/a.md", "b\n")
        out = hook.handle(self.event(tool="Write", content="b\n", tool_response={"type": "update", "originalFile": None}),
                          self.not_called)
        self.assertEqual(out["decision"], "block")
        self.assertIn("originalFile が文字列でない", out["systemMessage"])

    def test_unreadable_file_is_reported(self):
        self.configure(textlint={"hook": True})
        out = hook.handle(self.event(old_string="a", new_string="b", tool_response={"originalFile": "a\n"}),
                          self.not_called)
        self.assertEqual(out["decision"], "block")
        self.assertIn("読めない", out["systemMessage"])

    def test_config_error_without_hook_is_ignored(self):
        # hook を有効にしていないリポジトリでは、設定の型の誤りがあっても何もしない
        self.write(config.CONFIG_RELPATH, json.dumps({"terms_paths": "terms.toml"}))
        self.assertIsNone(hook.handle(self.event(old_string="a", new_string="b"), self.not_called))

    def test_config_error_with_hook_is_reported(self):
        self.write(config.CONFIG_RELPATH, json.dumps({"terms_paths": "terms.toml", "textlint": {"hook": True}}))
        out = hook.handle(self.event(old_string="a", new_string="b"), self.not_called)
        self.assertEqual(out["decision"], "block")
        self.assertIn("terms_paths", out["systemMessage"])

    def test_unreadable_config_is_reported(self):
        # JSON として読めないと hook が有効かを決められないので、知らせる
        self.write(config.CONFIG_RELPATH, "{")
        out = hook.handle(self.event(old_string="a", new_string="b"), self.not_called)
        self.assertEqual(out["decision"], "block")
        self.assertIn("読めない", out["systemMessage"])

    def test_terms_error_is_reported(self):
        self.configure(textlint={"hook": True})
        self.write(".claude/akm-claude-plugins/wording-guard/terms.toml", "[[terms]]\n")
        out = hook.handle(self.event(old_string="a", new_string="b"), self.not_called)
        self.assertEqual(out["decision"], "block")
        self.assertIn("検査できなかった", out["reason"])
        self.assertIn("pattern を空でない文字列で書く", out["systemMessage"])

    def test_textlint_error_is_reported(self):
        self.configure(textlint={"hook": True})
        self.write("docs/a.md", "b\n")

        def broken(*args, **kwargs):
            raise textlint.TextlintError("textlint が入っていない")

        out = hook.handle(self.event(old_string="a", new_string="b", tool_response={"originalFile": "a\n"}), broken)
        self.assertIn("textlint が入っていない", out["systemMessage"])
        self.assertIn("人間の承認を得てから実行する", out["reason"])


class TestCheckCommand(RepoTestCase):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = wording_lint.main([*args, "--root", self.root])
        return code, out.getvalue(), err.getvalue()

    def test_python_too_old(self):
        self.assertIsNone(wording_lint.python_too_old((3, 11, 0)))
        message = wording_lint.python_too_old((3, 9, 6))
        self.assertIn("Python 3.11 以降が必要", message)
        self.assertIn("3.9.6", message)

    def test_check_requires_textlint_setting(self):
        self.configure()
        self.write("a.md", "x")
        code, _, err = self.run_cli("check", os.path.join(self.root, "a.md"))
        self.assertEqual(code, 2)
        self.assertIn("textlint は設定されていない", err)

    def test_non_markdown_file_is_error(self):
        self.configure(textlint={})
        self.write("notes.txt", "x")
        for command in ("check", "fix"):
            code, out, err = self.run_cli(command, os.path.join(self.root, "notes.txt"))
            self.assertEqual(code, 2, command)
            self.assertIn("Markdown (.md) でない", err)
            self.assertEqual(out, "")

    def test_directory_skips_git_ignored_files(self):
        self.configure(textlint={})
        self.write(".gitignore", "node_modules/\n")
        self.write("docs/a.md", "x")
        self.write("node_modules/pkg/README.md", "x")
        self.write("docs/notes.txt", "x")
        files, skipped = wording_lint._markdown_files(self.root, config.load(self.root), [self.root])
        self.assertEqual(files, [os.path.join(self.root, "docs/a.md")])
        self.assertEqual(skipped, [])

    def test_directory_outside_repository_is_error(self):
        self.configure(textlint={})
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(config.ConfigError):
                wording_lint._markdown_files(self.root, config.load(self.root), [d])

    def test_directory_needs_git_repository_root(self):
        # git リポジトリでないルートでは、ディレクトリの指定は誤りになり、ファイルの指定は対象にできる
        with tempfile.TemporaryDirectory() as tmp:
            d = os.path.realpath(tmp)
            if config.find_root(d) is not None:
                self.skipTest("一時ディレクトリが git リポジトリの中にある")
            os.makedirs(os.path.join(d, "docs"))
            with open(os.path.join(d, "docs", "a.md"), "w", encoding="utf-8") as f:
                f.write("x")
            os.makedirs(os.path.dirname(os.path.join(d, config.CONFIG_RELPATH)))
            with open(os.path.join(d, config.CONFIG_RELPATH), "w", encoding="utf-8") as f:
                json.dump({"textlint": {}}, f)
            err = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                code = wording_lint.main(["check", os.path.join(d, "docs"), "--root", d])
            self.assertEqual(code, 2)
            self.assertIn("ディレクトリの指定は、ルート", err.getvalue())
            self.assertIn("ファイルは直接指定すれば対象にできる", err.getvalue())
            files, _ = wording_lint._markdown_files(d, None, [os.path.join(d, "docs", "a.md")])
            self.assertEqual(files, [os.path.join(d, "docs", "a.md")])

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
