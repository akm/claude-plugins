#!/usr/bin/env python3
"""pr-teeth の機械的ロジックのテスト。

標準ライブラリの unittest だけで動く（利用者の環境に pytest 等を要求しない）。

  python3 -m unittest discover -s pr-teeth/tests

ここでテストするのは、モデルの裁量ではなく決定的に決まるべき部分:
  - 言語の解決順序（第5.3節）
  - レビュー範囲の glob 判定と優先度（第7節）
  - 用語集のステータス遷移と言語別定義（第8節）
  - 設定 (config.toml) の読み込み
"""

import argparse
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from prteeth import (  # noqa: E402
    agent_input, auth, bodies, config, document, glossary, labels, prspec, render, repos,
    scope, state, store,
)


class TestConfigDir(unittest.TestCase):
    def setUp(self):
        os.environ.pop(config.CONFIG_DIR_ENV, None)

    tearDown = setUp

    def test_uses_plugin_source_literal(self):
        d = config.config_dir("github.com/akm/claude-plugins")
        self.assertEqual(
            d,
            os.path.join(os.path.expanduser("~"), "config", "github.com/akm/claude-plugins", "pr-teeth"),
        )

    def test_env_override_wins(self):
        os.environ[config.CONFIG_DIR_ENV] = "/tmp/pr-teeth-test"
        self.assertEqual(config.config_dir("github.com/akm/claude-plugins"), "/tmp/pr-teeth-test")

    def test_defaults_to_the_bundled_plugin_source(self):
        # SKILL.md からは渡さない運用。書き換え箇所を config.py の1箇所に保つ（#15）。
        self.assertEqual(config.config_dir(), config.config_dir(config.PLUGIN_SOURCE))

    def test_empty_source_falls_back_to_the_constant(self):
        # 空でも設定ディレクトリが分かれない。以前は例外にしていた。
        self.assertEqual(config.config_dir(""), config.config_dir(config.PLUGIN_SOURCE))

    def test_plugin_source_is_not_duplicated_in_skills(self):
        # 3つの SKILL.md に散ると fork 時の書き換え漏れを招き、コマンドによって
        # 別の設定ディレクトリを見る状態になる（#15）。
        skills = os.path.join(os.path.dirname(__file__), "..", "skills")
        offenders = []
        for root, _, names in os.walk(skills):
            for name in names:
                if not name.endswith(".md"):
                    continue
                path = os.path.join(root, name)
                with open(path, encoding="utf-8") as f:
                    if "--plugin-source" in f.read():
                        offenders.append(os.path.relpath(path, skills))
        self.assertEqual(offenders, [])


class TestLanguageResolution(unittest.TestCase):
    """言語の解決順序（第5.3節）。設定は config.toml 1枚に統合されている。"""

    def test_defaults_to_japanese(self):
        self.assertEqual(config.resolve_language("o/r", {}), "ja")

    def test_user_default(self):
        self.assertEqual(config.resolve_language("o/r", {"language": "en"}), "en")

    def test_repo_overrides_user(self):
        cfg = {"language": "en", "repos": {"o/r": {"language": "ko"}}}
        self.assertEqual(config.resolve_language("o/r", cfg), "ko")

    def test_repo_without_language_falls_back(self):
        cfg = {"language": "en", "repos": {"o/r": {"must_review": ["src/**"]}}}
        self.assertEqual(config.resolve_language("o/r", cfg), "en")

    def test_cli_beats_everything(self):
        cfg = {"language": "en", "repos": {"o/r": {"language": "ko"}}}
        self.assertEqual(config.resolve_language("o/r", cfg, cli_lang="fr"), "fr")

    def test_scheduled_run_uses_files_only(self):
        # 第14節: 無人実行では cli_lang が無く、2〜4段だけで決まる。
        cfg = {"language": "en", "repos": {"o/r": {"language": "ko"}}}
        self.assertEqual(config.resolve_language("o/r", cfg, None), "ko")

    def test_default_language_ignores_repo_setting(self):
        # 通知の地の文はユーザー既定。リポジトリ単位設定に引きずられない。
        cfg = {"language": "en", "repos": {"o/r": {"language": "ko"}}}
        self.assertEqual(config.default_language(cfg, None), "en")

    def test_malformed_config_does_not_crash(self):
        # 利用者が手で書くファイルなので、想定外の型でも落とさず既定へ倒す。
        for bad in ({"repos": "nope"}, {"repos": {"o/r": "nope"}}, {"language": 42}):
            self.assertEqual(config.resolve_language("o/r", bad), "ja")


class TestScopeGlob(unittest.TestCase):
    def test_star_does_not_cross_directories(self):
        entry = {"must_review": ["src/*.py"]}
        self.assertEqual(scope.classify_file("src/a.py", entry), scope.MUST)
        self.assertEqual(scope.classify_file("src/sub/a.py", entry), scope.SHOULD)

    def test_doublestar_crosses_directories(self):
        entry = {"must_review": ["src/auth/**"]}
        self.assertEqual(scope.classify_file("src/auth/deep/x.go", entry), scope.MUST)

    def test_leading_doublestar_matches_root_level(self):
        entry = {"ignore": ["**/*.md"]}
        self.assertEqual(scope.classify_file("README.md", entry), scope.IGNORE)
        self.assertEqual(scope.classify_file("docs/a/b.md", entry), scope.IGNORE)

    def test_bare_directory_matches_contents(self):
        entry = {"ignore": ["docs/"]}
        self.assertEqual(scope.classify_file("docs/guide/x.md", entry), scope.IGNORE)

    def test_must_wins_over_ignore(self):
        # 重要な範囲を ignore で隠さない（第7節）。
        entry = {"must_review": ["src/auth/**"], "ignore": ["**/*.go"]}
        self.assertEqual(scope.classify_file("src/auth/x.go", entry), scope.MUST)

    def test_unmatched_default_is_configurable(self):
        entry = {"must_review": ["src/**"]}
        self.assertEqual(scope.classify_file("other.txt", entry, scope.IGNORE), scope.IGNORE)

    def test_character_class_matches(self):
        entry = {"must_review": ["src/[abc].go"]}
        self.assertEqual(scope.classify_file("src/a.go", entry), scope.MUST)
        self.assertEqual(scope.classify_file("src/d.go", entry), scope.SHOULD)

    def test_character_range_matches(self):
        entry = {"must_review": ["src/[a-c].go"]}
        self.assertEqual(scope.classify_file("src/b.go", entry), scope.MUST)
        self.assertEqual(scope.classify_file("src/z.go", entry), scope.SHOULD)

    def test_negated_class_is_not_inverted(self):
        # glob は [!x]、正規表現は [^x] で否定する。そのままコピーすると `!` が
        # リテラル扱いになり、判定が正反対になる。
        entry = {"must_review": ["src/[!t]*.py"]}
        self.assertEqual(scope.classify_file("src/main.py", entry), scope.MUST)
        self.assertEqual(scope.classify_file("src/test_auth.py", entry), scope.SHOULD)

    def test_caret_also_negates(self):
        # gitignore / bash / POSIX と同じく ^ も否定として受ける。
        entry = {"must_review": ["src/[^t]*.py"]}
        self.assertEqual(scope.classify_file("src/main.py", entry), scope.MUST)
        self.assertEqual(scope.classify_file("src/test_auth.py", entry), scope.SHOULD)

    def test_bracket_right_after_negation_is_literal(self):
        # `[!]x]` は「] か x 以外」。閉じ括弧の位置を誤判定しない。
        self.assertTrue(scope._translate("[!]x]a").match("ba"))
        self.assertFalse(scope._translate("[!]x]a").match("]a"))
        self.assertFalse(scope._translate("[!]x]a").match("xa"))

    def test_character_class_does_not_cross_directories(self):
        # クラス内の / を許すと、パターンが階層境界を跨いでしまう。
        self.assertFalse(scope._translate("[a/b].go").match("a/b.go"))

    def test_unclosed_bracket_is_literal(self):
        # 閉じていない `[` で落ちない（リテラルとして扱う）。
        self.assertTrue(scope._translate("src/[abc.go").match("src/[abc.go"))

    def test_character_classes_match_fnmatch(self):
        """文字クラスの解釈が標準の glob と一致することを突き合わせる。

        `*` の扱いは**意図的に fnmatch と異なる**（fnmatch は `*` が `/` を越えるが、
        ここでは越えさせない。test_star_does_not_cross_directories 参照）ため、
        突き合わせるのは文字クラスを含むパターンだけにする。
        """
        import fnmatch

        cases = [
            ("[!t]main.py", ["main.py", "tmain.py"]),
            ("[abc].go", ["a.go", "d.go"]),
            ("[a-c].go", ["b.go", "z.go"]),
            ("[!]x]a", ["]a", "xa", "ba"]),
            ("[0-9][0-9].txt", ["12.txt", "1a.txt"]),
        ]
        for pattern, paths in cases:
            for path in paths:
                self.assertEqual(
                    bool(scope._translate(pattern).match(path)),
                    fnmatch.fnmatchcase(path, pattern),
                    msg=pattern + " vs " + path,
                )


class TestClassifyFiles(unittest.TestCase):
    def test_unconfigured_repo_is_should_review(self):
        # 設定し忘れたリポジトリの変更を黙って隠さない（安全側）。
        r = scope.classify_files(["a.md", "b.go"], "o/r", {"repos": {}})
        self.assertEqual(r["priority"], scope.SHOULD)
        self.assertEqual(r["counts"][scope.SHOULD], 2)

    def test_priority_and_counts(self):
        repos = {
            "repos": {"o/r": {"must_review": ["src/auth/**"], "ignore": ["docs/**"]}},
            "repo_defaults": {"unmatched": "should_review"},
        }
        r = scope.classify_files(
            ["src/auth/a.go", "src/api/b.go", "docs/c.md", "docs/d.md"], "o/r", repos
        )
        self.assertEqual(r["priority"], scope.MUST)
        self.assertEqual(r["counts"][scope.MUST], 1)
        self.assertEqual(r["counts"][scope.SHOULD], 1)
        self.assertEqual(r["counts"][scope.IGNORE], 2)

    def test_ignore_only_pr_sorts_last(self):
        repos = {"repos": {"o/r": {"ignore": ["**/*.md"]}}}
        ignore_only = scope.classify_files(["a.md"], "o/r", repos)
        must = scope.classify_files(["x.go"], "o/r", {"repos": {"o/r": {"must_review": ["**/*.go"]}}})
        self.assertLess(scope.sort_key(must), scope.sort_key(ignore_only))


class TestGlossary(unittest.TestCase):
    def test_seed_terms_are_known(self):
        g = glossary.load_or_seed({})
        self.assertEqual(glossary.status_of(g, "SSoT"), glossary.KNOWN)
        self.assertFalse(glossary.needs_explanation(g, "SSoT"))

    def test_unknown_term_needs_full_explanation(self):
        g = glossary.load_or_seed({})
        self.assertEqual(glossary.status_of(g, "reconciliation loop"), glossary.NEW)

    def test_auto_promotion_to_learning(self):
        g = glossary.load_or_seed({})
        for _ in range(glossary.LEARNING_THRESHOLD):
            glossary.record(g, "widget")
        self.assertEqual(glossary.status_of(g, "widget"), glossary.LEARNING)

    def test_never_auto_promotes_to_known(self):
        # 推定だけで説明を消さない（第8節）。
        g = glossary.load_or_seed({})
        for _ in range(50):
            glossary.record(g, "widget")
        self.assertEqual(glossary.status_of(g, "widget"), glossary.LEARNING)

    def test_explicit_promotion_to_known(self):
        g = glossary.load_or_seed({})
        glossary.record(g, "widget")
        glossary.set_status(g, "widget", glossary.KNOWN, now="2026-08-01T00:00:00Z")
        self.assertFalse(glossary.needs_explanation(g, "widget"))
        self.assertEqual(g["terms"]["widget"]["known_since"], "2026-08-01T00:00:00Z")

    def test_status_is_shared_across_languages(self):
        # 日本語で known にした語は、英語出力でも説明が省かれる（第8節）。
        g = glossary.load_or_seed({})
        glossary.record(g, "widget", language="ja", definition="部品")
        glossary.set_status(g, "widget", glossary.KNOWN)
        self.assertFalse(glossary.needs_explanation(g, "widget"))
        self.assertIsNone(glossary.definition_for(g, "widget", "en"))

    def test_definitions_are_per_language(self):
        g = glossary.load_or_seed({})
        glossary.record(g, "widget", language="ja", definition="部品")
        glossary.record(g, "widget", language="en", definition="a part")
        self.assertEqual(glossary.definition_for(g, "widget", "ja"), "部品")
        self.assertEqual(glossary.definition_for(g, "widget", "en"), "a part")

    def test_existing_definition_is_not_overwritten(self):
        g = glossary.load_or_seed({})
        glossary.record(g, "widget", language="ja", definition="最初の定義")
        glossary.record(g, "widget", language="ja", definition="別の定義")
        self.assertEqual(glossary.definition_for(g, "widget", "ja"), "最初の定義")

    def test_occurrences_shared_across_languages(self):
        g = glossary.load_or_seed({})
        glossary.record(g, "widget", language="ja", definition="部品")
        glossary.record(g, "widget", language="en", definition="a part")
        self.assertEqual(g["terms"]["widget"]["occurrences"], 2)

    def test_other_language_definitions_are_visible(self):
        g = glossary.load_or_seed({})
        glossary.record(g, "widget", language="ja", definition="部品")
        self.assertEqual(glossary.other_language_definitions(g, "widget", "en"), {"ja": "部品"})

class TestToml(unittest.TestCase):
    """設定の読み込み（第5節）。

    以前は PyYAML があればそれを、無ければ同梱の簡易パーサを使う二重実装だった。
    両者は実際に食い違い（リスト項目を親キーと同じインデントに置く正当な YAML を
    簡易パーサが拒否し、レビュー範囲設定が丸ごと無効化された）、しかも PyYAML の
    有無で挙動が変わるため、利用者のマシン構成に依存する不具合になっていた。
    tomllib は標準ライブラリなので実装は1つで済み、この種の食い違いが起きない。
    """

    def _write(self, d, text):
        p = os.path.join(d, "config.toml")
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def test_parses_documented_example(self):
        text = "\n".join([
            'language = "ja"',
            "",
            "[repo_defaults]",
            'unmatched = "should_review"',
            "",
            '[repos."owner/service-api"]',
            'must_review = ["src/payments/**", "src/auth/**"]',
            'ignore = ["docs/**"]',
            "",
            '[repos."someorg/oss-library"]',
            'language = "en"',
            'should_review = ["src/**"]',
            "",
        ])
        with tempfile.TemporaryDirectory() as d:
            cfg = store.load_toml(self._write(d, text), {})
        self.assertEqual(cfg["language"], "ja")
        self.assertEqual(
            cfg["repos"]["owner/service-api"]["must_review"],
            ["src/payments/**", "src/auth/**"],
        )
        self.assertEqual(cfg["repos"]["someorg/oss-library"]["language"], "en")
        self.assertEqual(cfg["repo_defaults"]["unmatched"], "should_review")

    def test_repo_names_with_slashes_round_trip(self):
        # リポジトリ名は owner/repo 形式なので、キーに引用符が要る。
        with tempfile.TemporaryDirectory() as d:
            cfg = store.load_toml(
                self._write(d, '[repos."o/r"]\nignore = ["docs/**"]\n'), {}
            )
        self.assertEqual(cfg["repos"]["o/r"]["ignore"], ["docs/**"])

    def test_list_style_that_broke_the_old_parser(self):
        # 旧簡易パーサはこの形（複数行の配列）を扱えず、設定を丸ごと捨てていた。
        text = '[repos."o/r"]\nmust_review = [\n  "src/auth/**",\n  "src/api/**",\n]\n'
        with tempfile.TemporaryDirectory() as d:
            cfg = store.load_toml(self._write(d, text), {})
        self.assertEqual(cfg["repos"]["o/r"]["must_review"], ["src/auth/**", "src/api/**"])

    def test_hash_inside_quotes_is_kept(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = store.load_toml(self._write(d, 'a = "x#y"  # コメント\n'), {})
        self.assertEqual(cfg["a"], "x#y")

    def test_missing_file_returns_default(self):
        self.assertEqual(store.load_toml("/nonexistent/config.toml", {"a": 1}), {"a": 1})

    def test_broken_toml_warns_and_defaults(self):
        # 壊れていても落とさないが、黙って握りつぶさず理由を残す。
        with tempfile.TemporaryDirectory() as d:
            warnings = []
            cfg = store.load_toml(self._write(d, "this is not toml ==\n"), {}, warnings)
        self.assertEqual(cfg, {})
        self.assertTrue(warnings)

    def test_empty_file_returns_default(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(store.load_toml(self._write(d, "\n"), {"a": 1}), {"a": 1})


class TestStore(unittest.TestCase):
    def test_missing_file_returns_default(self):
        self.assertEqual(store.load_json("/nonexistent/x.json", {"a": 1}), {"a": 1})

    def test_broken_json_warns_and_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.json")
            with open(p, "w") as f:
                f.write("{not json")
            warnings = []
            self.assertEqual(store.load_json(p, {}, warnings), {})
            self.assertTrue(warnings)

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "sub", "g.json")
            store.save_json(p, {"terms": {"あ": {"term": "あ"}}})
            self.assertEqual(store.load_json(p, {})["terms"]["あ"]["term"], "あ")


class TestPreciousData(unittest.TestCase):
    """蓄積データの読み込み（docs/design/data-integrity.md）。

    壊れているのに既定値を返すと、呼び出し側がそれを保存して元データを失わせる。
    「無い」（正常な初回実行）と「壊れている」を区別できることが要点。
    """

    def _write(self, d, text, name="glossary.json"):
        p = os.path.join(d, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def test_missing_file_is_not_corrupt(self):
        # 初回実行を止めない。
        self.assertEqual(store.load_precious("/nonexistent/g.json", {"a": 1}), {"a": 1})

    def test_empty_file_is_not_corrupt(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(store.load_precious(self._write(d, ""), {"a": 1}), {"a": 1})

    def test_broken_json_raises_corrupt(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, "{not json")
            with self.assertRaises(store.Corrupt) as cm:
                store.load_precious(p, {})
        self.assertEqual(cm.exception.path, p)

    def test_non_object_raises_corrupt(self):
        # 用語集は常にオブジェクト。配列なら別物を読んでいる。
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(store.Corrupt):
                store.load_precious(self._write(d, "[1,2,3]"), {})

    def test_valid_file_round_trips(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write(d, '{"terms": {"a": {"term": "a"}}}')
            self.assertEqual(store.load_precious(p, {})["terms"]["a"]["term"], "a")

    def test_lock_is_exclusive_between_processes(self):
        # ロックが効いていなければ、子プロセスが即座に取得できてしまう。
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "g.json")
            with store.locked(p):
                self.assertFalse(self._child_can_lock(p))
            # 解放後は取れる。
            self.assertTrue(self._child_can_lock(p))

    def test_lock_times_out_instead_of_hanging(self):
        # 取れないまま無限に待つと、利用者からは固まったようにしか見えない。
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "g.json")
            holder = self._spawn_holder(p, hold=3.0)
            try:
                self._wait_until_locked(p)
                with self.assertRaises(store.Busy):
                    with store.locked(p, timeout=0.2):
                        pass
            finally:
                holder.kill()
                holder.wait()

    def test_lock_is_released_when_the_body_raises(self):
        # 例外で抜けたあとロックが残ると、以降の実行が全部 Busy になる。
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "g.json")
            with self.assertRaises(RuntimeError):
                with store.locked(p):
                    raise RuntimeError("boom")
            self.assertTrue(self._child_can_lock(p))

    def test_lock_survives_the_atomic_replace(self):
        # save_json は os.replace で inode を差し替える。データファイル自体を
        # ロック対象にしていると、置換後のファイルには何も保証が無い。
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "g.json")
            with store.locked(p):
                store.save_json(p, {"terms": {}})
                self.assertFalse(self._child_can_lock(p))

    def _lock_snippet(self, path, body):
        scripts = os.path.join(os.path.dirname(__file__), "..", "scripts")
        return [sys.executable, "-c", "\n".join([
            "import sys, time",
            "sys.path.insert(0, " + repr(scripts) + ")",
            "from prteeth import store",
            body.replace("<PATH>", repr(path)),
        ])]

    def _child_can_lock(self, path):
        """別プロセスがロックを取れるか。取れれば exit=0。"""
        import subprocess
        cmd = self._lock_snippet(path, "\n".join([
            "try:",
            "    with store.locked(<PATH>, timeout=0.2):",
            "        sys.exit(0)",
            "except store.Busy:",
            "    sys.exit(3)",
        ]))
        return subprocess.run(cmd, capture_output=True).returncode == 0

    def _spawn_holder(self, path, hold):
        """ロックを掴んだまま待つ子プロセスを起こす。"""
        import subprocess
        cmd = self._lock_snippet(path, "\n".join([
            "with store.locked(<PATH>):",
            "    open(<PATH> + '.held', 'w').close()",
            "    time.sleep(" + str(hold) + ")",
        ]))
        return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _wait_until_locked(self, path, timeout=5.0):
        """子がロックを掴むまで待つ。掴んだ合図はファイルの出現で受ける。"""
        import time
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if os.path.exists(path + ".held"):
                return
            time.sleep(0.02)
        self.fail("子プロセスがロックを取得しませんでした")

    def test_load_json_still_fails_soft_for_config(self):
        # 設定向けの load_json は従来どおり既定値を返す（種別で態度を変える）。
        with tempfile.TemporaryDirectory() as d:
            warnings = []
            self.assertEqual(store.load_json(self._write(d, "{bad"), {}, warnings), {})
            self.assertTrue(warnings)


class TestAgentInput(unittest.TestCase):
    """エージェント入力の検証（docs/design/data-integrity.md）。

    エージェントが毎回組み立てるため、設定ファイルより間違いが起きやすい。
    形が違えば止め、項目単位の不備はスキップして件数を返す。
    """

    def test_accepts_valid_terms(self):
        items, skipped = agent_input.terms(
            {"terms": [{"term": "a", "language": "ja", "definition": "x"}]}
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(skipped, [])

    def test_missing_terms_key_is_an_error(self):
        # 黙って0件記録して成功を返すと、記録できたと誤解される。
        with self.assertRaises(agent_input.InvalidInput) as cm:
            agent_input.terms({"glossary": []})
        self.assertIn("terms", str(cm.exception))
        self.assertIn("glossary", str(cm.exception))  # 実際のキーも示す

    def test_bare_array_is_an_error(self):
        with self.assertRaises(agent_input.InvalidInput):
            agent_input.terms([{"term": "a"}])

    def test_terms_not_a_list_is_an_error(self):
        with self.assertRaises(agent_input.InvalidInput):
            agent_input.terms({"terms": "a"})

    def test_error_message_shows_expected_shape(self):
        # エージェントが自力で直せるよう、期待する形を必ず含める。
        with self.assertRaises(agent_input.InvalidInput) as cm:
            agent_input.terms({})
        self.assertIn('"terms"', str(cm.exception))

    def test_item_without_term_is_skipped_not_fatal(self):
        # 1件の不備で正常な語まで失わない。
        items, skipped = agent_input.terms({"terms": [
            {"term": "good", "definition": "x"},
            {"definition": "term キーなし"},
            {"term": "   "},
        ]})
        self.assertEqual([i["term"] for i in items], ["good"])
        self.assertEqual(len(skipped), 2)

    def test_skip_reason_names_the_index(self):
        _, skipped = agent_input.terms({"terms": [{"term": "ok"}, {"bad": 1}]})
        self.assertIn("terms[1]", skipped[0])

    def test_prs_accepts_wrapped_and_bare(self):
        pr = {"repo": "o/r", "number": 1, "sha": "a"}
        for payload in ([pr], {"prs": [pr]}):
            items, skipped = agent_input.prs(payload)
            self.assertEqual(len(items), 1)
            self.assertEqual(skipped, [])

    def test_prs_without_sha_or_updated_at_is_skipped(self):
        # どちらも無いと更新判定ができず、永遠に「変化なし」になる。
        items, skipped = agent_input.prs([{"repo": "o/r", "number": 1}])
        self.assertEqual(items, [])
        self.assertIn("更新を判定できません", skipped[0])

    def test_prs_missing_repo_is_skipped(self):
        items, skipped = agent_input.prs([{"number": 1, "sha": "a"}])
        self.assertEqual(items, [])
        self.assertTrue(skipped)

    def test_prs_non_list_is_an_error(self):
        with self.assertRaises(agent_input.InvalidInput):
            agent_input.prs("nope")


class TestState(unittest.TestCase):
    """更新の判定（第10節ステップ4）。"""

    def _state(self, sha="aaa", updated="2026-08-01T00:00:00Z"):
        return {"notified": {"o/r#1": {"sha": sha, "updated_at": updated}}}

    def _pr(self, sha="aaa", updated="2026-08-01T00:00:00Z"):
        return {"repo": "o/r", "number": 1, "sha": sha, "updated_at": updated}

    def test_unknown_pr_is_new(self):
        t = state.select_targets({}, [self._pr()])
        self.assertEqual(t[0]["status"], state.NEW)
        self.assertIsNone(t[0]["base_sha"])

    def test_unchanged_is_excluded(self):
        self.assertEqual(state.select_targets(self._state(), [self._pr()]), [])

    def test_new_commit_is_an_update(self):
        t = state.select_targets(self._state(), [self._pr(sha="bbb")])
        self.assertEqual(t[0]["status"], state.UPDATED)
        # 差分の起点として前回の SHA を渡す。
        self.assertEqual(t[0]["base_sha"], "aaa")

    def test_updated_at_change_alone_is_an_update(self):
        # 本文の書き直しやレビューコメントはコミットを伴わない。
        # sha だけ見ていると取りこぼす。
        t = state.select_targets(self._state(), [self._pr(updated="2026-08-02T00:00:00Z")])
        self.assertEqual(t[0]["status"], state.UPDATED)

    def test_legacy_string_state_is_readable(self):
        # 旧形式（値が SHA の文字列）でも読める。利用者に再設定を求めない。
        legacy = {"notified": {"o/r#1": "aaa"}}
        self.assertEqual(state.select_targets(legacy, [self._pr()]), [])
        t = state.select_targets(legacy, [self._pr(sha="bbb")])
        self.assertEqual(t[0]["status"], state.UPDATED)

    def test_legacy_state_does_not_mass_update_on_migration(self):
        # 旧形式には updated_at が無い。比較できないものを「変わった」とみなすと
        # 移行直後に全件が更新扱いになってしまう。
        legacy = {"notified": {"o/r#1": "aaa"}}
        self.assertEqual(state.select_targets(legacy, [self._pr(updated="9999")]), [])

    def test_record_merges_by_default(self):
        # 渡された一覧が完全とは限らない（取得失敗・件数上限・処理分だけ）。
        # 全置換すると、まだオープンな PR の記録が消えて再通知される。
        prev = {"notified": {"o/r#1": {"sha": "a"}, "o/r#2": {"sha": "b"}}}
        new = state.record_notified(prev, [self._pr(sha="a2")])
        self.assertEqual(new["notified"]["o/r#1"]["sha"], "a2")  # 更新される
        self.assertIn("o/r#2", new["notified"])                  # 消えない

    def test_partial_list_does_not_cause_renotification(self):
        prev = state.record_notified({}, [
            {"repo": "o/r", "number": 1, "sha": "a", "updated_at": "t"},
            {"repo": "o/r", "number": 2, "sha": "b", "updated_at": "t"},
        ])
        # #1 だけ渡す（#2 の取得に失敗した想定）
        after = state.record_notified(prev, [{"repo": "o/r", "number": 1, "sha": "a", "updated_at": "t"}])
        targets = state.select_targets(after, [
            {"repo": "o/r", "number": 1, "sha": "a", "updated_at": "t"},
            {"repo": "o/r", "number": 2, "sha": "b", "updated_at": "t"},
        ])
        self.assertEqual(targets, [])  # どちらも再通知されない

    def test_prune_to_removes_closed_prs(self):
        # 完全な一覧を宣言したときだけ掃除する。閉じた PR の記録を残し続けると
        # 再オープン時に「変化なし」と誤判定しうるため、掃除自体は要る。
        prev = {"notified": {"o/r#1": {"sha": "a"}, "o/r#99": {"sha": "z"}}}
        new = state.record_notified(prev, [self._pr()], prune_to=[self._pr()])
        self.assertIn("o/r#1", new["notified"])
        self.assertNotIn("o/r#99", new["notified"])

    def test_record_stores_both_fields(self):
        new = state.record_notified({}, [self._pr(sha="s", updated="u")])
        self.assertEqual(new["notified"]["o/r#1"], {"sha": "s", "updated_at": "u"})


class TestAuth(unittest.TestCase):
    """トークンの探索順序（第6節）。

    `gh auth token` を実際に呼ぶと実行環境の認証状態に左右されるため、
    その段だけ差し替えて順序を検証する。
    """

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in (auth.ENV_TOKEN, auth.ENV_TOKEN_FILE)}
        for k in self._saved:
            os.environ.pop(k, None)
        self._real_gh = auth._from_gh_cli
        auth._from_gh_cli = lambda: (None, None)

    def tearDown(self):
        auth._from_gh_cli = self._real_gh
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_env_token_wins(self):
        os.environ[auth.ENV_TOKEN] = "tok-env"
        auth._from_gh_cli = lambda: ("tok-gh", "gh auth token")
        token, source, err = auth.resolve()
        self.assertEqual(token, "tok-env")
        self.assertIn(auth.ENV_TOKEN, source)
        self.assertIsNone(err)

    def test_token_file_used_when_env_absent(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t")
            with open(p, "w") as f:
                f.write("tok-file")
            os.environ[auth.ENV_TOKEN_FILE] = p
            token, source, err = auth.resolve()
        self.assertEqual(token, "tok-file")
        self.assertIn(auth.ENV_TOKEN_FILE, source)

    def test_env_beats_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t")
            with open(p, "w") as f:
                f.write("tok-file")
            os.environ[auth.ENV_TOKEN] = "tok-env"
            os.environ[auth.ENV_TOKEN_FILE] = p
            token, _, _ = auth.resolve()
        self.assertEqual(token, "tok-env")

    def test_gh_cli_is_last(self):
        auth._from_gh_cli = lambda: ("tok-gh", "gh auth token")
        token, source, _ = auth.resolve()
        self.assertEqual(token, "tok-gh")
        self.assertEqual(source, "gh auth token")

    def test_missing_everything_is_an_error(self):
        token, source, err = auth.resolve()
        self.assertIsNone(token)
        self.assertIsNone(source)

    def test_whitespace_is_trimmed(self):
        # 改行付きのままヘッダに入れると認証が通らず、原因も分かりにくい。
        os.environ[auth.ENV_TOKEN] = "  tok-env\n"
        self.assertEqual(auth.resolve()[0], "tok-env")

    def test_token_file_trailing_newline_is_trimmed(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "t")
            with open(p, "w") as f:
                f.write("tok-file\n\n")
            os.environ[auth.ENV_TOKEN_FILE] = p
            self.assertEqual(auth.resolve()[0], "tok-file")

    def test_empty_env_falls_through(self):
        # 空文字を「設定済み」と誤認して止まらない。
        os.environ[auth.ENV_TOKEN] = "   "
        auth._from_gh_cli = lambda: ("tok-gh", "gh auth token")
        self.assertEqual(auth.resolve()[0], "tok-gh")

    def test_unreadable_token_file_reports_reason(self):
        # 指定されたのに読めないのは設定ミス。黙って進むと原因が分からない。
        os.environ[auth.ENV_TOKEN_FILE] = "/nonexistent/token"
        token, _, err = auth.resolve()
        self.assertIsNone(token)
        self.assertIn(auth.ENV_TOKEN_FILE, err)

    def test_unreadable_file_still_falls_back_to_gh(self):
        os.environ[auth.ENV_TOKEN_FILE] = "/nonexistent/token"
        auth._from_gh_cli = lambda: ("tok-gh", "gh auth token")
        token, _, err = auth.resolve()
        self.assertEqual(token, "tok-gh")
        self.assertIsNone(err)


class TestLabels(unittest.TestCase):
    def test_known_languages(self):
        self.assertEqual(labels.for_language("ja")["summary"], "概要")
        self.assertEqual(labels.for_language("en")["summary"], "Summary")

    def test_region_tag_matches_primary(self):
        self.assertEqual(labels.for_language("ja-JP")["summary"], "概要")

    def test_unknown_language_falls_back_to_english(self):
        # 日本語に倒すと、日本語を読めない利用者に読めない画面を出すことになる。
        self.assertEqual(labels.for_language("ko")["summary"], "Summary")
        self.assertEqual(labels.for_language("")["summary"], "Summary")


class TestLabelContext(unittest.TestCase):
    """文脈別ラベル（#16）。

    番号指定でマージ済み PR を読むときに「レビュー必須」と出るのは意味がずれる。
    表示だけを差し替え、分類の内部の値は変えない。
    """

    def test_patrol_is_the_default(self):
        self.assertEqual(labels.for_language("ja")["must_review"], "必須")

    def test_pick_relabels_scopes(self):
        L = labels.for_language("ja", labels.CONTEXT_PICK)
        self.assertEqual(L["must_review"], "重点")
        self.assertEqual(L["should_review"], "参考")
        self.assertEqual(L["ignore"], "周辺")

    def test_pick_relabels_in_english_too(self):
        L = labels.for_language("en", labels.CONTEXT_PICK)
        self.assertEqual(L["must_review"], "Focus")
        self.assertEqual(L["ignore"], "Periphery")

    def test_pick_keeps_unrelated_labels(self):
        # 上書き表に無いキーは巡回時のものがそのまま使われる。
        self.assertEqual(labels.for_language("ja", labels.CONTEXT_PICK)["summary"], "概要")

    def test_pick_has_its_own_page_title(self):
        L = labels.for_language("ja", labels.CONTEXT_PICK)
        self.assertEqual(L["page_title"], "指定した PR")

    def test_unknown_language_gets_english_pick_labels(self):
        # 未知の言語は英語にフォールバックする。文脈の上書きも英語側を使う。
        self.assertEqual(labels.for_language("ko", labels.CONTEXT_PICK)["must_review"], "Focus")

    def test_region_tag_gets_japanese_pick_labels(self):
        self.assertEqual(labels.for_language("ja-JP", labels.CONTEXT_PICK)["must_review"], "重点")

    def test_pick_table_has_no_unknown_keys(self):
        # 上書き表にタイポがあると、そのキーだけ差し替わらず巡回時の文言が残る。
        base = set(labels.for_language("ja"))
        for lang in ("ja", "en"):
            self.assertEqual(set(labels._PICK_OVERRIDES[lang]) - base, set())


class TestPRSpec(unittest.TestCase):
    """PR 指定の解釈（#16）。

    URL からの取り違えは、**別の PR の解説を正しい体裁で出す**という気づけない
    誤りになるため、モデルに任せず機械的に確定させる。
    """

    def test_short_form(self):
        self.assertEqual(prspec.parse_one("owner/repo#123"), {"repo": "owner/repo", "number": 123})

    def test_url_form(self):
        self.assertEqual(
            prspec.parse_one("https://github.com/owner/repo/pull/123"),
            {"repo": "owner/repo", "number": 123},
        )

    def test_url_with_trailing_path_is_the_same_pr(self):
        # /files や /commits を貼られても番号は変わらない。
        for suffix in ("/files", "/commits", "/", "?w=1", "#discussion_r1"):
            self.assertEqual(
                prspec.parse_one("https://github.com/o/r/pull/123" + suffix)["number"], 123
            )

    def test_url_without_scheme(self):
        self.assertEqual(prspec.parse_one("github.com/o/r/pull/9")["repo"], "o/r")

    def test_any_host_parses_but_host_is_discarded(self):
        # ホストは照合するだけで捨てる。GHE の URL を貼っても、リンクは
        # document.GITHUB_HOST（公開 github.com）から組まれる。GHE 対応は
        # そちらが未対応なので、ここで受けても対応にはならない。
        self.assertEqual(
            prspec.parse_one("https://ghe.example.com/o/r/pull/5"),
            {"repo": "o/r", "number": 5},
        )

    def test_hostlike_prefix_does_not_become_the_repo(self):
        # 素のパスの先頭がホストとして食われると、打っていないリポジトリに
        # 解決される（`foo/bar/baz/pull/9` -> `bar/baz`）。これが起きると
        # 「別の PR の解説が正しい体裁で出る」= 読み手が誤りに気づけない。
        for bad in ("foo/bar/baz/pull/9", "orgs/owner/repo/pull/5"):
            with self.assertRaises(prspec.InvalidSpec):
                prspec.parse_one(bad)

    def test_schemeless_url_fragment_does_not_fall_through_to_short_form(self):
        # `github.com/akm/123` が _SHORT に落ちると `github.com/akm` になる。
        # owner にドットを許さないことで塞いでいる。
        with self.assertRaises(prspec.InvalidSpec):
            prspec.parse_one("github.com/akm/123")

    def test_repo_case_is_normalized(self):
        # GitHub は大文字小文字を区別しないが、設定の引き当ては素の辞書引き。
        # 揃えないと [repos."owner/repo"] を取りこぼし、出力言語とレビュー範囲が
        # 黙って既定値に落ちる。
        self.assertEqual(prspec.parse_one("Akm/Claude-Plugins#1")["repo"], "akm/claude-plugins")

    def test_case_variants_are_deduplicated(self):
        targets, _ = prspec.parse(["Akm/Claude-Plugins#1", "akm/claude-plugins#1"])
        self.assertEqual(len(targets), 1)

    def test_slash_form_when_hash_is_eaten_by_shell(self):
        self.assertEqual(prspec.parse_one("owner/repo/123"), {"repo": "owner/repo", "number": 123})

    def test_git_suffix_is_stripped(self):
        self.assertEqual(prspec.parse_one("https://github.com/o/r.git/pull/3")["repo"], "o/r")

    def test_surrounding_whitespace_is_ignored(self):
        self.assertEqual(prspec.parse_one("  owner/repo#1  ")["number"], 1)

    def test_unparseable_spec_raises(self):
        for bad in ("", "   ", "just-text", "owner/repo", "owner/repo#abc", "#123"):
            with self.assertRaises(prspec.InvalidSpec):
                prspec.parse_one(bad)

    def test_error_message_shows_expected_shape(self):
        with self.assertRaises(prspec.InvalidSpec) as cm:
            prspec.parse_one("nonsense")
        self.assertIn("owner/repo#123", str(cm.exception))

    def test_parse_keeps_order_and_reports_errors(self):
        targets, errors = prspec.parse(["o/r#2", "bogus", "o/r#1"])
        self.assertEqual([t["number"] for t in targets], [2, 1])
        self.assertEqual(len(errors), 1)
        self.assertIn("bogus", errors[0])

    def test_invalid_spec_does_not_drop_the_valid_ones(self):
        # 1件の誤りで全体を止めない（取得・解析の失敗と同じ扱い）。
        targets, _ = prspec.parse(["bogus", "o/r#1"])
        self.assertEqual(len(targets), 1)

    def test_duplicates_are_collapsed_first_wins(self):
        # 同じ PR を2回解説しても情報が増えない。
        targets, errors = prspec.parse(["o/r#1", "https://github.com/o/r/pull/1"])
        self.assertEqual(len(targets), 1)
        self.assertEqual(errors, [])  # 利用者の誤りではないので警告にしない

    def test_same_number_in_different_repos_is_not_a_duplicate(self):
        targets, _ = prspec.parse(["a/r#1", "b/r#1"])
        self.assertEqual(len(targets), 2)


class TestBodies(unittest.TestCase):
    """PR 本文の保管（scripts/prteeth/bodies.py）。

    本文は state.json に入れず 1件1ファイルで持つ。state を人が開いて確認できる
    大きさに保ち、本文だけを独立して消せるようにするため（#11）。
    """

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.dir = os.path.join(self._dir.name, "bodies")

    def tearDown(self):
        self._dir.cleanup()

    def test_round_trips(self):
        bodies.save(self.dir, "o/r", 1, "## 背景\n本文")
        self.assertEqual(bodies.load(self.dir, "o/r", 1), "## 背景\n本文")

    def test_missing_body_is_none_not_an_error(self):
        # 無いことは異常ではない（初回・掃除済み）。呼び出し側は全体を説明する。
        self.assertIsNone(bodies.load(self.dir, "o/r", 999))

    def test_file_name_is_sanitized(self):
        # パスの組み立てに使う値。.. や / が混ざる経路を作らない。
        p = bodies.path_for(self.dir, "Owner/repo.js", 7)
        self.assertEqual(os.path.dirname(p), self.dir)
        self.assertNotIn("/", os.path.basename(p).replace(".md", ""))

    def test_different_prs_do_not_collide(self):
        bodies.save(self.dir, "o/r", 1, "first")
        bodies.save(self.dir, "o/r", 2, "second")
        self.assertEqual(bodies.load(self.dir, "o/r", 1), "first")
        self.assertEqual(bodies.load(self.dir, "o/r", 2), "second")

    def test_separator_ambiguity_does_not_collide(self):
        # acme/web-api と acme-web/api はどちらも正当な GitHub のリポジトリ。
        # 区切りを潰すと同名になり、一方の本文が他方の差分の基準に使われる（#9）。
        bodies.save(self.dir, "acme/web-api", 1, "web-api の本文")
        bodies.save(self.dir, "acme-web/api", 1, "api の本文")
        self.assertEqual(bodies.load(self.dir, "acme/web-api", 1), "web-api の本文")
        self.assertEqual(bodies.load(self.dir, "acme-web/api", 1), "api の本文")

    def test_case_difference_does_not_collide(self):
        bodies.save(self.dir, "o/r", 1, "小文字")
        bodies.save(self.dir, "O/R", 1, "大文字")
        self.assertEqual(bodies.load(self.dir, "o/r", 1), "小文字")
        self.assertEqual(bodies.load(self.dir, "O/R", 1), "大文字")

    def test_number_and_repo_boundary_does_not_collide(self):
        # `o/r-1` #2 と `o/r` #"1-2" は、区切りを潰すと同じ綴りになりうる。
        bodies.save(self.dir, "o/r-1", 2, "A")
        bodies.save(self.dir, "o/r", "1-2", "B")
        self.assertEqual(bodies.load(self.dir, "o/r-1", 2), "A")
        self.assertEqual(bodies.load(self.dir, "o/r", "1-2"), "B")

    def test_degenerate_names_still_get_distinct_files(self):
        # 記号だけのリポジトリ名でも、ハッシュがあるので同じファイルに集まらない。
        bodies.save(self.dir, "///", 1, "A")
        bodies.save(self.dir, "@@@", 1, "B")
        self.assertEqual(bodies.load(self.dir, "///", 1), "A")
        self.assertEqual(bodies.load(self.dir, "@@@", 1), "B")

    def test_name_has_no_parent_directory_segments(self):
        # os.path.join では無害だが、ファイル名に .. が残ると紛らわしい。
        self.assertNotIn("..", bodies._name("a/../../b", 1))
        self.assertNotIn("..", bodies._name("..", 1))

    def test_name_matches_the_state_key(self):
        # state の記録と本文の対応が定義上ずれないよう、鍵を共有する。
        import hashlib
        key = state.key("o/r", 7)
        expected = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        self.assertIn(expected, bodies._name("o/r", 7))

    def test_long_body_is_truncated(self):
        # 自動生成のログ貼り付け等で state ディレクトリが膨らむのを止める。
        body = "x" * (bodies.MAX_BODY_BYTES + 5000)
        _, truncated = bodies.save(self.dir, "o/r", 1, body)
        self.assertTrue(truncated)
        self.assertLessEqual(
            len(bodies.load(self.dir, "o/r", 1).encode("utf-8")), bodies.MAX_BODY_BYTES)

    def test_truncation_does_not_break_utf8(self):
        # マルチバイトの途中で切ると読めない文字が残る。
        body = "あ" * bodies.MAX_BODY_BYTES
        bodies.save(self.dir, "o/r", 1, body)
        loaded = bodies.load(self.dir, "o/r", 1)
        self.assertTrue(loaded.startswith("あ"))
        self.assertNotIn("�", loaded)

    def test_truncated_body_currently_yields_a_spurious_diff(self):
        # 既知の問題(#25)。切り詰めた前回と完全な今回を比較するため、本文が
        # 変わっていなくても差分が出る。実測では上限に遠く現実にはほぼ起きないため
        # 未対応。**直したらこのテストを「差分が出ない」に変える。**
        body = "あ" * (bodies.MAX_BODY_BYTES // 2)
        bodies.save(self.dir, "o/r", 1, body)
        stored = bodies.load(self.dir, "o/r", 1)
        self.assertNotEqual(stored, body)  # 切り詰められている
        self.assertNotEqual(bodies.diff(stored, body), "")

    def test_normal_body_is_not_truncated(self):
        # 実測では中央値 1.4KB・最大 5KB 程度。通常は掛からない。
        _, truncated = bodies.save(self.dir, "o/r", 1, "x" * 5000)
        self.assertFalse(truncated)

    def test_prune_removes_bodies_for_dead_prs(self):
        # 閉じた PR の本文を残し続けない（state の掃除と歩調を合わせる）。
        bodies.save(self.dir, "o/r", 1, "alive")
        bodies.save(self.dir, "o/r", 2, "closed")
        removed = bodies.prune(self.dir, {("o/r", 1)})
        self.assertEqual(len(removed), 1)
        self.assertEqual(bodies.load(self.dir, "o/r", 1), "alive")
        self.assertIsNone(bodies.load(self.dir, "o/r", 2))

    def test_prune_enforces_the_count_limit(self):
        for i in range(5):
            path, _ = bodies.save(self.dir, "o/r", i, "b")
            os.utime(path, (1000 + i, 1000 + i))
        alive = {("o/r", i) for i in range(5)}
        bodies.prune(self.dir, alive, max_bodies=3)
        # 古い順に消える。
        self.assertIsNone(bodies.load(self.dir, "o/r", 0))
        self.assertIsNone(bodies.load(self.dir, "o/r", 1))
        self.assertEqual(bodies.load(self.dir, "o/r", 4), "b")

    def test_prune_does_not_delete_in_flight_temp_files(self):
        # store の原子的書き込みは一時ファイル + os.replace。ここで消すと、
        # 並走する保存が replace に失敗する（#22 で入れた保証が崩れる）。
        bodies.save(self.dir, "o/r", 1, "alive")
        tmp = os.path.join(self.dir, ".tmp-abc123.txt")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("書き込み中")
        removed = bodies.prune(self.dir, {("o/r", 1)})
        self.assertEqual(removed, [])
        self.assertTrue(os.path.exists(tmp))

    def test_prune_temp_files_do_not_consume_the_count_limit(self):
        # 一時ファイルを件数に数えると、生きた本文が上限で追い出される。
        for i in range(3):
            path, _ = bodies.save(self.dir, "o/r", i, "b")
            os.utime(path, (1000 + i, 1000 + i))
        with open(os.path.join(self.dir, ".tmp-xyz.txt"), "w") as f:
            f.write("x")
        bodies.prune(self.dir, {("o/r", i) for i in range(3)}, max_bodies=3)
        for i in range(3):
            self.assertEqual(bodies.load(self.dir, "o/r", i), "b")

    def test_prune_without_alive_applies_only_the_count_limit(self):
        # alive が分からない場合でも件数の上限は効かせる。ただし生死による
        # 削除はしない（どれが閉じたか分からないため）。
        for i in range(4):
            path, _ = bodies.save(self.dir, "o/r", i, "b")
            os.utime(path, (1000 + i, 1000 + i))
        removed = bodies.prune(self.dir, None, max_bodies=2)
        # ファイル名の綴りではなく「どの PR が消えたか」を見る。
        self.assertEqual(sorted(removed),
                         sorted([bodies._name("o/r", 0), bodies._name("o/r", 1)]))
        self.assertIsNone(bodies.load(self.dir, "o/r", 0))
        self.assertEqual(bodies.load(self.dir, "o/r", 3), "b")

    def test_prune_without_alive_keeps_everything_under_the_limit(self):
        bodies.save(self.dir, "o/r", 1, "b")
        self.assertEqual(bodies.prune(self.dir, None, max_bodies=200), [])
        self.assertEqual(bodies.load(self.dir, "o/r", 1), "b")

    def test_prune_is_safe_on_missing_dir(self):
        self.assertEqual(bodies.prune(self.dir, set()), [])

    def test_save_is_atomic(self):
        # 途中で中断されても既存の本文を壊さない。
        bodies.save(self.dir, "o/r", 1, "original")
        leftovers = [n for n in os.listdir(self.dir) if n.startswith(".tmp-")]
        self.assertEqual(leftovers, [])

    def test_diff_shows_added_lines(self):
        d = bodies.diff("## 背景\n古い説明", "## 背景\n古い説明\n\n## 追記\n新しい段落")
        self.assertIn("+## 追記", d)
        self.assertIn("+新しい段落", d)

    def test_diff_shows_removed_lines(self):
        d = bodies.diff("残る行\n消える行", "残る行")
        self.assertIn("-消える行", d)

    def test_diff_is_empty_when_unchanged(self):
        # 変わっていないのに「本文が変わった」と出すと、読み手を惑わせる。
        self.assertEqual(bodies.diff("同じ本文", "同じ本文"), "")

    def test_diff_is_empty_without_a_previous_body(self):
        # 初回は全体を説明する。差分の出しようが無い。
        self.assertEqual(bodies.diff(None, "本文"), "")

    def test_diff_is_capped(self):
        # 本文全体を貼り直すのではなく、変わった箇所を示す。
        d = bodies.diff("\n".join(str(i) for i in range(500)), "\n".join("x" for _ in range(500)))
        self.assertLessEqual(len(d.splitlines()), bodies.MAX_DIFF_LINES)
        self.assertIn("中略", d)

    def test_capped_diff_keeps_both_deletions_and_additions(self):
        # 先頭から一律に切ると削除行だけが残り、「全部消された」と読めてしまう。
        # 本文を書き直した PR で誤解を生むため、前後の両方を残す。
        d = bodies.diff("\n".join("old %d" % i for i in range(300)),
                        "\n".join("new %d" % i for i in range(300)))
        lines = d.splitlines()
        self.assertTrue(any(ln.startswith("-") and not ln.startswith("---")
                            for ln in lines), "削除行が残っていない")
        self.assertTrue(any(ln.startswith("+") and not ln.startswith("+++")
                            for ln in lines), "追加行が残っていない")

    def test_diff_is_capped_by_bytes_too(self):
        # 行数だけを縛ってもバイト数は縛れない。長い行が数本あれば、
        # 行数の上限に達しないままモデルの文脈を圧迫する。
        prev = "\n".join("A" * 20000 for _ in range(10))
        cur = "\n".join("B" * 20000 for _ in range(10))
        d = bodies.diff(prev, cur)
        self.assertLessEqual(len(d.encode("utf-8")), bodies.MAX_DIFF_BYTES)

    def test_long_lines_are_clipped(self):
        d = bodies.diff("短い行", "x" * 5000)
        for line in d.splitlines():
            self.assertLessEqual(len(line), bodies.MAX_DIFF_LINE_CHARS + 20)

    def test_diff_keeps_the_header(self):
        # どちらが前回でどちらが今回か分からなくなると読めない。
        d = bodies.diff("\n".join("old %d" % i for i in range(300)),
                        "\n".join("new %d" % i for i in range(300)))
        self.assertIn("前回の本文", d)
        self.assertIn("今回の本文", d)

    def test_short_diff_is_not_clipped(self):
        d = bodies.diff("一行目\n二行目", "一行目\n二行目\n三行目")
        self.assertNotIn("中略", d)
        self.assertIn("+三行目", d)


class TestRepoCache(unittest.TestCase):
    """作業リポジトリの管理（scripts/prteeth/repos.py）。

    ネットワークは使わない。ローカルに作った git リポジトリを origin にして、
    clone / fetch の実際の挙動を確かめる。
    """

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.root = self._dir.name
        self.repos_dir = os.path.join(self.root, "repos")

    def tearDown(self):
        self._dir.cleanup()

    def _git(self, *args, cwd=None):
        import subprocess
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e")
        return subprocess.run(["git"] + list(args), cwd=cwd, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    def _origin(self, name="src"):
        """clone 元になるローカルリポジトリを1つ作る。"""
        path = os.path.join(self.root, name)
        os.makedirs(path)
        self._git("init", "-q", "-b", "main", cwd=path)
        with open(os.path.join(path, "a.txt"), "w") as f:
            f.write("hello\n")
        self._git("add", "a.txt", cwd=path)
        self._git("commit", "-qm", "first", cwd=path)
        return path

    def test_validate_rejects_path_traversal(self):
        # パスの組み立てに使う値。.. や絶対パスが混ざる経路を作らない。
        for bad in ("../../etc", "/etc/passwd", "owner", "a/b/c", ""):
            with self.assertRaises(repos.RepoError):
                repos.validate(bad)

    def test_validate_accepts_normal_names(self):
        self.assertEqual(repos.validate("Owner/repo.js"), "Owner/repo.js")

    def test_path_is_split_by_owner(self):
        p = repos.path_for(self.repos_dir, "o/r")
        self.assertEqual(p, os.path.join(self.repos_dir, "o", "r"))

    def test_clone_then_fetch(self):
        origin = self._origin()
        path, action = repos.ensure(self.repos_dir, "o/r", url=origin)
        self.assertEqual(action, "cloned")
        self.assertTrue(os.path.isdir(os.path.join(path, ".git")))

        # 2回目は clone し直さない。
        path2, action2 = repos.ensure(self.repos_dir, "o/r", url=origin)
        self.assertEqual(action2, "fetched")
        self.assertEqual(path, path2)

    def test_clone_is_blobless(self):
        # 全履歴の blob まで取ると、大きなモノレポでディスクと時間を浪費する。
        origin = self._origin()
        path, _ = repos.ensure(self.repos_dir, "o/r", url=origin)
        with open(os.path.join(path, ".git", "config"), encoding="utf-8") as f:
            self.assertIn("partialclonefilter", f.read().replace(" ", "").lower())

    def test_fetch_sees_new_commits(self):
        origin = self._origin()
        repos.ensure(self.repos_dir, "o/r", url=origin)
        with open(os.path.join(origin, "b.txt"), "w") as f:
            f.write("second\n")
        self._git("add", "b.txt", cwd=origin)
        self._git("commit", "-qm", "second", cwd=origin)

        path, action = repos.ensure(self.repos_dir, "o/r", url=origin)
        self.assertEqual(action, "fetched")
        log = self._git("log", "--oneline", "origin/main", cwd=path).stdout.decode()
        self.assertIn("second", log)

    def test_broken_clone_is_replaced(self):
        # 途中で失敗した clone の残骸を掴んだまま fetch し続けない。
        origin = self._origin()
        path = repos.path_for(self.repos_dir, "o/r")
        os.makedirs(path)
        with open(os.path.join(path, "junk"), "w") as f:
            f.write("leftover\n")

        _, action = repos.ensure(self.repos_dir, "o/r", url=origin)
        self.assertEqual(action, "cloned")
        self.assertTrue(os.path.isdir(os.path.join(path, ".git")))
        self.assertFalse(os.path.exists(os.path.join(path, "junk")))

    def test_failure_raises_repo_error(self):
        # 1件の失敗で巡回全体を止めない形にする（呼び出し側が握れる型）。
        with self.assertRaises(repos.RepoError):
            repos.ensure(self.repos_dir, "o/r",
                         url=os.path.join(self.root, "nonexistent"))

    def test_listing_reports_each_repo(self):
        origin = self._origin()
        repos.ensure(self.repos_dir, "o/r", url=origin)
        repos.ensure(self.repos_dir, "other/x", url=origin)
        names = [e["repo"] for e in repos.list_repos(self.repos_dir)]
        self.assertEqual(names, ["o/r", "other/x"])

    def test_listing_is_empty_before_any_clone(self):
        self.assertEqual(repos.list_repos(self.repos_dir), [])

    def test_touch_records_use(self):
        origin = self._origin()
        path, _ = repos.ensure(self.repos_dir, "o/r", url=origin)
        os.utime(path, (0, 0))
        repos.touch(path)
        self.assertGreater(repos.used_at(path), 0)

    def _fake(self, repo, used_at=None, size=0):
        """clone せずに作業リポジトリらしきものを作る（掃除の判定用）。"""
        path = repos.path_for(self.repos_dir, repo)
        os.makedirs(os.path.join(path, ".git"), exist_ok=True)
        if size:
            with open(os.path.join(path, "big"), "wb") as f:
                f.write(b"x" * size)
        if used_at is not None:
            stamp = os.path.join(path, ".pr-teeth-used")
            with open(stamp, "w") as f:
                f.write("")
            os.utime(stamp, (used_at, used_at))
        return path

    def test_cleanup_removes_oldest_over_the_count_limit(self):
        # 次に使う可能性が最も低いものから消す。
        for i in range(5):
            self._fake("o/r" + str(i), used_at=1000 + i)
        out = repos.cleanup(self.repos_dir, max_repos=3, max_age_days=10 ** 6, now=2000)
        self.assertEqual([r["repo"] for r in out["removed"]], ["o/r0", "o/r1"])
        self.assertEqual(out["kept"], ["o/r2", "o/r3", "o/r4"])

    def test_cleanup_keeps_everything_under_the_limit(self):
        self._fake("o/r", used_at=1000)
        out = repos.cleanup(self.repos_dir, max_repos=3, max_age_days=10 ** 6, now=2000)
        self.assertEqual(out["removed"], [])
        self.assertEqual(out["kept"], ["o/r"])

    def test_cleanup_removes_stale_repos_even_under_the_limit(self):
        # 一度きり見た PR のリポジトリを、以後ずっと持ち続けない。
        now = 100 * 86400
        self._fake("o/old", used_at=now - 40 * 86400)
        self._fake("o/fresh", used_at=now - 1 * 86400)
        out = repos.cleanup(self.repos_dir, max_repos=99, max_age_days=30, now=now)
        self.assertEqual([r["repo"] for r in out["removed"]], ["o/old"])
        self.assertEqual([r["reason"] for r in out["removed"]], ["age"])

    def test_cleanup_respects_the_size_limit(self):
        # 大きなモノレポが数個あると、件数の上限では効かない。
        self._fake("o/a", used_at=1000, size=4000)
        self._fake("o/b", used_at=2000, size=4000)
        out = repos.cleanup(self.repos_dir, max_repos=99, max_bytes=5000,
                            max_age_days=10 ** 6, now=3000)
        self.assertEqual([r["repo"] for r in out["removed"]], ["o/a"])
        self.assertEqual([r["reason"] for r in out["removed"]], ["size"])
        self.assertLessEqual(out["total_bytes"], 5000)

    def test_cleanup_never_removes_protected_repos(self):
        # いま解説中のものを消すと、直後に clone し直すことになる。
        self._fake("o/current", used_at=0)
        self._fake("o/other", used_at=5000)
        out = repos.cleanup(self.repos_dir, max_repos=1, max_age_days=10 ** 6,
                            now=6000, keep=["o/current"])
        self.assertEqual(out["kept"], ["o/current"])
        self.assertEqual([r["repo"] for r in out["removed"]], ["o/other"])

    def test_cleanup_actually_deletes_from_disk(self):
        path = self._fake("o/gone", used_at=0)
        repos.cleanup(self.repos_dir, max_repos=0, max_age_days=10 ** 6, now=1000)
        self.assertFalse(os.path.exists(path))

    def test_cleanup_prunes_empty_owner_dirs(self):
        self._fake("o/only", used_at=0)
        repos.cleanup(self.repos_dir, max_repos=0, max_age_days=10 ** 6, now=1000)
        self.assertFalse(os.path.exists(os.path.join(self.repos_dir, "o")))

    def test_cleanup_is_safe_on_empty_dir(self):
        out = repos.cleanup(self.repos_dir)
        self.assertEqual(out["removed"], [])
        self.assertEqual(out["kept"], [])

    def test_cleanup_order_is_stable_for_equal_timestamps(self):
        # 同着を実行ごとに揺らすと、消えるものが実行のたびに変わる。
        for name in ("o/c", "o/a", "o/b"):
            self._fake(name, used_at=1000)
        out = repos.cleanup(self.repos_dir, max_repos=1, max_age_days=10 ** 6, now=2000)
        self.assertEqual([r["repo"] for r in out["removed"]], ["o/a", "o/b"])


class TestDocument(unittest.TestCase):
    """解説データの型（scripts/prteeth/document.py）。

    素の dict を .get() で読むと、キー名を間違えても None が空文字になり、
    セクションが黙って消える。型で必須を持つことで組み立て時点で検出する。
    """

    def _pr(self, **kw):
        pr = {"repo": "o/r", "number": 1, "title": "T", "priority": "should_review"}
        pr.update(kw)
        return {"prs": [pr]}

    def test_accepts_minimal_pr(self):
        doc = document.from_payload(self._pr())
        self.assertEqual(len(doc.prs), 1)
        self.assertEqual(doc.prs[0].repo, "o/r")

    def test_url_is_derived_not_accepted(self):
        # url を渡す経路が無いので、href に任意の文字列が入らない（#6）。
        doc = document.from_payload(self._pr())
        self.assertEqual(doc.prs[0].url, "https://github.com/o/r/pull/1")
        with self.assertRaises(document.InvalidDocument) as cm:
            document.from_payload(self._pr(url="javascript:alert(1)"))
        self.assertIn("url", str(cm.exception))

    def test_anchor_is_derived_not_accepted(self):
        # url と同じく、任意の文字列が id に入る経路を作らない（#19）。
        doc = document.from_payload(self._pr())
        self.assertEqual(doc.prs[0].anchor, "pr-o-r-1")
        with self.assertRaises(document.InvalidDocument):
            document.from_payload(self._pr(anchor="x"))

    def test_anchor_sanitizes_repo_names(self):
        # リポジトリ名に使える文字はそのまま id に置けない。
        doc = document.from_payload(self._pr(repo="Owner/repo.js"))
        self.assertEqual(doc.prs[0].anchor, "pr-owner-repo-js-1")

    def test_missing_required_key_is_an_error(self):
        # 従来は空文字になって黙って欠落していた。
        for missing in ("repo", "number", "title", "priority"):
            payload = self._pr()
            del payload["prs"][0][missing]
            with self.assertRaises(document.InvalidDocument) as cm:
                document.from_payload(payload)
            self.assertIn(missing, str(cm.exception))

    def test_typo_in_optional_key_is_an_error(self):
        # main_changes のようなタイポを黙って捨てるとセクションが消える。
        with self.assertRaises(document.InvalidDocument) as cm:
            document.from_payload(self._pr(main_changes=["x"]))
        self.assertIn("main_changes", str(cm.exception))

    def test_error_message_lists_usable_keys(self):
        with self.assertRaises(document.InvalidDocument) as cm:
            document.from_payload(self._pr(body="x"))
        self.assertIn("summary", str(cm.exception))  # 正しいキーを示す

    def test_invalid_priority_is_an_error(self):
        with self.assertRaises(document.InvalidDocument):
            document.from_payload(self._pr(priority="urgent"))

    def test_missing_prs_key_is_an_error(self):
        with self.assertRaises(document.InvalidDocument) as cm:
            document.from_payload({"pull_requests": []})
        self.assertIn("prs", str(cm.exception))

    def test_term_without_term_key_is_an_error(self):
        with self.assertRaises(document.InvalidDocument):
            document.from_payload(self._pr(terms=[{"definition": "x"}]))

    def test_ignore_only_pr_is_collapsed(self):
        doc = document.from_payload(self._pr(priority="ignore"))
        self.assertTrue(doc.prs[0].collapsed)

    def test_explicit_collapsed_is_respected(self):
        doc = document.from_payload(self._pr(priority="ignore", collapsed=False))
        self.assertFalse(doc.prs[0].collapsed)

    def test_prs_are_sorted_by_priority(self):
        doc = document.from_payload({"prs": [
            {"repo": "o/r", "number": 3, "title": "c", "priority": "ignore"},
            {"repo": "o/r", "number": 1, "title": "a", "priority": "must_review"},
            {"repo": "o/r", "number": 2, "title": "b", "priority": "should_review"},
        ]})
        self.assertEqual([p.number for p in doc.prs], [1, 2, 3])

    def test_number_zero_is_not_treated_as_missing(self):
        # 0 は falsy だが有効な値。required 判定で誤って弾かない。
        doc = document.from_payload(self._pr(number=0))
        self.assertEqual(doc.prs[0].number, 0)

    def test_context_defaults_to_patrol(self):
        self.assertEqual(document.from_payload(self._pr()).context, labels.CONTEXT_PATROL)

    def test_context_can_be_pick(self):
        payload = self._pr()
        payload["context"] = labels.CONTEXT_PICK
        self.assertEqual(document.from_payload(payload).context, labels.CONTEXT_PICK)

    def test_invalid_context_is_an_error(self):
        # 黙って巡回扱いにすると、番号指定なのに「必須」と出る。
        payload = self._pr()
        payload["context"] = "browsing"
        with self.assertRaises(document.InvalidDocument) as cm:
            document.from_payload(payload)
        self.assertIn("browsing", str(cm.exception))


class TestRender(unittest.TestCase):
    def _doc(self, pr_overrides=None, **kw):
        pr = {
            "repo": "o/r", "number": 1, "title": "T", "language": "en",
            "priority": "should_review", "counts": {"should_review": 1},
            "summary": "S", "changes": ["c"],
        }
        pr.update(pr_overrides or {})
        payload = {"language": "ja", "prs": [pr]}
        payload.update(kw)
        return document.from_payload(payload)

    def test_pr_chrome_uses_pr_language(self):
        # 本文が英語なのに見出しが日本語だと読めない（第5.3節）。
        h = render.render(self._doc())
        self.assertIn("<h3>Summary</h3>", h)
        self.assertNotIn("<h3>概要</h3>", h)

    def test_page_chrome_uses_default_language(self):
        h = render.render(self._doc())
        self.assertIn('<html lang="ja"', h)
        self.assertIn('lang="en"', h)  # PR 側は自分の言語

    def test_escapes_html_in_content(self):
        h = render.render(self._doc({"summary": "<script>alert(1)</script>"}))
        self.assertNotIn("<script>alert(1)</script>", h)
        self.assertIn("&lt;script&gt;", h)

    def test_known_terms_are_not_rendered(self):
        h = render.render(self._doc({"terms": [
            {"term": "SSoT", "status": "known", "definition": "x"},
            {"term": "jitter", "status": "new", "definition": "y"},
        ]}))
        self.assertIn("jitter", h)
        self.assertNotIn("SSoT", h)

    def test_pr_link_is_derived_from_repo_and_number(self):
        # url をエージェントから受け取らないので、href に任意の文字列が入らない。
        h = render.render(self._doc())
        self.assertIn('<a href="https://github.com/o/r/pull/1">', h)

    def _multi(self, prs, **kw):
        payload = {"language": "ja", "prs": prs}
        payload.update(kw)
        return document.from_payload(payload)

    def _two(self, **kw):
        return self._multi([
            {"repo": "o/r", "number": 1, "title": "First", "language": "ja",
             "priority": "must_review"},
            {"repo": "o/other", "number": 2, "title": "Second", "language": "ja",
             "priority": "ignore"},
        ], **kw)

    def test_index_links_to_each_pr(self):
        # 上から順に並べただけでは、目当ての PR がどこにあるか分からない。
        h = render.render(self._two())
        self.assertIn('<a href="#pr-o-r-1">First</a>', h)
        self.assertIn('<a href="#pr-o-other-2">Second</a>', h)

    def test_index_anchors_match_article_ids(self):
        # 飛び先が無いとリンクが黙って効かなくなる。
        h = render.render(self._two())
        self.assertIn('id="pr-o-r-1"', h)
        self.assertIn('id="pr-o-other-2"', h)

    def test_index_is_omitted_for_a_single_pr(self):
        # 1件では意味を持たず、縦を消費するだけになる。
        self.assertNotIn('class="index"', render.render(self._doc()))

    def test_index_shows_scope_distribution(self):
        # 開いた時点で優先度の分布が分かるようにする。
        h = render.render(self._two())
        head = h.split('<article')[0]
        self.assertIn("必須: 1", head)
        self.assertIn("対象外: 1", head)

    def test_index_includes_collapsed_prs(self):
        # ignore は1行に畳まれるが、画面に在ることは目次から分かるべき。
        h = render.render(self._two())
        self.assertIn("Second", h.split('<article')[0])

    def test_index_titles_carry_their_own_language(self):
        # 各行のタイトルはその PR の言語で書かれている（地の文の言語とは別）。
        h = render.render(self._multi([
            {"repo": "o/r", "number": 1, "title": "First", "language": "en",
             "priority": "must_review"},
            {"repo": "o/r", "number": 2, "title": "二番目", "language": "ja",
             "priority": "must_review"},
        ]))
        head = h.split('<article')[0]
        self.assertIn('<li lang="en">', head)
        self.assertIn('<li lang="ja">', head)

    def test_index_badges_follow_the_context(self):
        # 番号指定でマージ済み PR に「必須」と出るのは意味がずれる。
        head = render.render(self._two(context="pick")).split('<article')[0]
        self.assertIn("重点", head)
        self.assertNotIn("必須", head)

    def test_index_escapes_titles(self):
        h = render.render(self._multi([
            {"repo": "o/r", "number": 1, "title": "<script>alert(1)</script>",
             "language": "ja", "priority": "must_review"},
            {"repo": "o/r", "number": 2, "title": "T", "language": "ja",
             "priority": "must_review"},
        ]))
        self.assertNotIn("<script>alert(1)</script>", h)

    def test_no_external_assets_other_than_github_links(self):
        # 図が無ければ CDN を読まない（完全にオフラインで開ける）。
        # PR へのリンクは残るが、これは遷移先であって読み込み対象ではない。
        h = render.render(self._doc())
        self.assertNotIn("<script", h)
        self.assertNotIn("cdnjs", h)

    def test_cdn_script_has_integrity(self):
        # CDN が別の内容を返した場合にブラウザが拒否できるようにする。
        h = render.render(self._doc({"diagram": "flowchart LR\n A-->B"}))
        self.assertIn("cdnjs", h)
        self.assertIn('integrity="sha512-', h)
        self.assertIn('crossorigin="anonymous"', h)

    def test_cdn_version_and_sri_are_consistent(self):
        # バージョンだけ上げて SRI を更新し忘れると、図が黙って出なくなる。
        h = render.render(self._doc({"diagram": "flowchart LR\n A-->B"}))
        self.assertIn(render._MERMAID_VERSION + "/mermaid.min.js", h)
        self.assertIn(render._MERMAID_SRI, h)
        self.assertNotIn("__VER__", h)
        self.assertNotIn("__SRI__", h)

    def test_mermaid_security_level_is_explicit(self):
        # 図のラベルは PR 由来の文字列を含みうる。ライブラリ既定値に依存しない。
        h = render.render(self._doc({"diagram": "flowchart LR\n A-->B"}))
        self.assertIn("securityLevel: 'strict'", h)
        self.assertIn("htmlLabels: false", h)

    def test_diagram_code_survives_when_mermaid_unavailable(self):
        h = render.render(self._doc({"diagram": "flowchart LR\n A-->B"}))
        self.assertIn("mermaid-src", h)
        self.assertIn("flowchart LR", h)

    def test_patrol_context_shows_review_labels(self):
        h = render.render(self._doc({"language": "ja", "priority": "must_review",
                                     "counts": {"must_review": 1}}))
        self.assertIn("必須", h)
        self.assertNotIn("重点", h)

    def test_pick_context_shows_reading_labels(self):
        # マージ済み PR に「レビュー必須」と出るのは意味がずれる（#16）。
        doc = self._doc({"language": "ja", "priority": "must_review",
                         "counts": {"must_review": 1}}, context="pick")
        h = render.render(doc)
        self.assertIn("重点", h)
        self.assertNotIn("必須", h)

    def test_pick_context_changes_page_title(self):
        h = render.render(self._doc(context="pick"))
        self.assertIn("指定した PR", h)
        self.assertNotIn("レビュー依頼の PR", h)

    def test_pick_context_applies_to_pr_language_not_page_language(self):
        # ページは ja、PR は en。文脈は両方に効き、言語はそれぞれのものを使う。
        doc = self._doc({"language": "en", "priority": "must_review",
                         "counts": {"must_review": 1}}, context="pick")
        h = render.render(doc)
        self.assertIn("Focus", h)          # PR 側は英語の pick ラベル
        self.assertIn("指定した PR", h)     # ページ側は日本語の pick ラベル

    def test_priority_classification_is_unchanged_by_context(self):
        # 表示だけを変え、内部の値は変えない（分類・並び替えは共通）。
        doc = self._doc({"priority": "must_review"}, context="pick")
        self.assertEqual(doc.prs[0].priority, "must_review")


class TestOutputPath(unittest.TestCase):
    """HTML の出力先解決（render / glossary-html で規則を揃える）。

    利用者は作業中のリポジトリでコマンドを呼ぶ。相対パスを素直に解決すると
    生成物がそのリポジトリに散らかるため、設定ディレクトリの out/ に寄せる。
    """

    def setUp(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
        import pr_teeth

        self.mod = pr_teeth

    def _paths(self, d):
        return {"out": os.path.join(d, "out")}

    def test_relative_goes_under_out_dir(self):
        with tempfile.TemporaryDirectory() as d:
            p = self.mod._out_path(self._paths(d), "report.html", "default.html")
        self.assertEqual(p, os.path.join(d, "out", "report.html"))

    def test_absolute_is_used_as_is(self):
        with tempfile.TemporaryDirectory() as d:
            p = self.mod._out_path(self._paths(d), "/tmp/x/abs.html", "default.html")
        self.assertEqual(p, "/tmp/x/abs.html")

    def test_default_name_also_goes_under_out_dir(self):
        with tempfile.TemporaryDirectory() as d:
            p = self.mod._out_path(self._paths(d), None, "pr-glossary.html")
        self.assertEqual(p, os.path.join(d, "out", "pr-glossary.html"))

    def test_out_dir_is_created(self):
        with tempfile.TemporaryDirectory() as d:
            self.mod._out_path(self._paths(d), None, "x.html")
            self.assertTrue(os.path.isdir(os.path.join(d, "out")))


class TestCliCommands(unittest.TestCase):
    """CLI の配線（scripts/pr_teeth.py）。

    prspec / labels 単体のテストでは、引数の受け渡しの取り違えが見つからない。
    番号指定では `--context` の渡し忘れがそのまま「マージ済み PR にレビュー必須と
    出る」不具合になるため、ここで配線ごと確かめる。
    """

    def setUp(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
        import pr_teeth

        self.mod = pr_teeth
        self._dir = tempfile.TemporaryDirectory()
        os.environ[config.CONFIG_DIR_ENV] = self._dir.name

    def tearDown(self):
        os.environ.pop(config.CONFIG_DIR_ENV, None)
        self._dir.cleanup()

    def _run(self, fn, **kw):
        """サブコマンドを呼び、stdout に出た JSON を返す。"""
        import contextlib
        import io

        kw.setdefault("plugin_source", "github.com/akm/claude-plugins")
        kw.setdefault("lang", None)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fn(argparse.Namespace(**kw))
        return json.loads(buf.getvalue())

    def _write(self, name, payload):
        path = os.path.join(self._dir.name, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        return path

    def test_resolve_reports_counts_and_language(self):
        out = self._run(self.mod.cmd_resolve, specs=["o/r#1", "https://github.com/a/b/pull/2"])
        self.assertEqual(out["resolved"], 2)
        self.assertEqual(out["requested"], 2)
        self.assertEqual([t["repo"] for t in out["targets"]], ["o/r", "a/b"])
        self.assertTrue(all(t["language"] for t in out["targets"]))

    def test_resolve_keeps_valid_specs_when_one_is_invalid(self):
        # 1件の誤りで全体を止めない。
        out = self._run(self.mod.cmd_resolve, specs=["bogus", "o/r#1"])
        self.assertEqual(out["resolved"], 1)
        self.assertEqual(len(out["invalid"]), 1)

    def test_resolve_does_not_duplicate_errors_into_warnings(self):
        # SKILL.md は invalid と warnings の両方を出すよう指示している。
        # 同じ文言を両方に積むと、利用者には2回並んで見える。
        out = self._run(self.mod.cmd_resolve, specs=["bogus"])
        self.assertEqual(len(out["invalid"]), 1)
        self.assertEqual(out["warnings"], [])

    def test_resolve_uses_repo_language_override(self):
        with open(os.path.join(self._dir.name, "config.toml"), "w", encoding="utf-8") as f:
            f.write('language = "ja"\n[repos."o/r"]\nlanguage = "en"\n')
        out = self._run(self.mod.cmd_resolve, specs=["o/r#1", "other/x#2"])
        by_repo = {t["repo"]: t["language"] for t in out["targets"]}
        self.assertEqual(by_repo["o/r"], "en")
        self.assertEqual(by_repo["other/x"], "ja")

    def test_resolve_mixed_case_spec_finds_repo_config(self):
        # 打った表記の揺れで設定を取りこぼすと、出力言語が黙って変わる。
        with open(os.path.join(self._dir.name, "config.toml"), "w", encoding="utf-8") as f:
            f.write('language = "ja"\n[repos."o/r"]\nlanguage = "en"\n')
        out = self._run(self.mod.cmd_resolve, specs=["O/R#1"])
        self.assertEqual(out["targets"][0]["language"], "en")

    def _render(self, context, payload_context=None):
        payload = {"prs": [{"repo": "o/r", "number": 1, "title": "T",
                            "priority": "must_review", "language": "ja"}]}
        if payload_context:
            payload["context"] = payload_context
        path = self._write("doc.json", payload)
        out = self._run(self.mod.cmd_render, input=path, output=None, context=context)
        with open(out["path"], encoding="utf-8") as f:
            return out, f.read()

    def test_render_context_flag_switches_labels(self):
        _, html = self._render("pick")
        self.assertIn("重点", html)
        self.assertNotIn("必須", html)

    def test_render_defaults_to_patrol_labels(self):
        _, html = self._render(None)
        self.assertIn("必須", html)
        self.assertNotIn("重点", html)

    def test_render_flag_overrides_payload_context(self):
        # コマンド側が文脈を知っているので、フラグが勝つ。
        _, html = self._render("pick", payload_context="patrol")
        self.assertIn("重点", html)

    def test_render_payload_context_applies_without_flag(self):
        _, html = self._render(None, payload_context="pick")
        self.assertIn("重点", html)

    def test_render_output_filename_marks_the_context(self):
        # 巡回と番号指定の生成物が out/ に混ざったとき、名前で見分けられるように。
        pick, _ = self._render("pick")
        patrol, _ = self._render(None)
        self.assertIn("pr-teeth-pick-", os.path.basename(pick["path"]))
        self.assertNotIn("pick", os.path.basename(patrol["path"]))

    def _record_in_subprocess(self, terms, delay=0.0):
        """実際の CLI を別プロセスで動かして record させる。

        _run は同一プロセス内で関数を呼ぶため、プロセスを跨ぐ競合を再現できない。
        delay は「読み込みの直後に保存が遅れる」状況を作り、ロックが無ければ
        必ず lost update になる窓を開けるためのもの。
        """
        import subprocess

        cli = os.path.join(os.path.dirname(__file__), "..", "scripts", "pr_teeth.py")
        payload = self._write("terms-" + terms[0] + ".json", {"terms": [
            {"term": t, "language": "ja", "definition": "d"} for t in terms
        ]})
        env = dict(os.environ, PR_TEETH_CONFIG_DIR=self._dir.name)
        env.pop("PYTHONPATH", None)  # 遅延させない側に hook を継承させない
        if delay:
            # save_json を遅らせる。sitecustomize は子の起動時に自動で読まれる。
            # hook は専用ディレクトリに置く。設定ディレクトリに置くと、
            # PYTHONPATH を渡さない側の子もこれを読む経路が生まれうる。
            hook_dir = os.path.join(self._dir.name, "hook")
            os.makedirs(hook_dir, exist_ok=True)
            hook = os.path.join(hook_dir, "sitecustomize.py")
            with open(hook, "w", encoding="utf-8") as f:
                f.write("\n".join([
                    "import sys, time",
                    "sys.path.insert(0, " + repr(os.path.dirname(cli)) + ")",
                    "from prteeth import store",
                    "_orig = store.save_json",
                    "def _slow(path, data):",
                    "    time.sleep(" + str(delay) + ")",
                    "    return _orig(path, data)",
                    "store.save_json = _slow",
                ]))
            env["PYTHONPATH"] = hook_dir
        return subprocess.Popen(
            [sys.executable, cli, "record", "--input", payload],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def test_concurrent_record_keeps_both_terms(self):
        # Issue #13 の再現。ロックが無いと後から保存したほうが勝ち、
        # 片方のプロセスが足した語が消える。
        import time

        slow = self._record_in_subprocess(["alpha"], delay=0.6)
        # 先行プロセスが「読み終えたが、まだ保存していない」窓に後続を入れる。
        # ここを待たずに起こすと両者が順に走ってしまい、競合を再現できない。
        time.sleep(0.2)
        fast = self._record_in_subprocess(["beta"])
        self.assertEqual(slow.wait(), 0)
        self.assertEqual(fast.wait(), 0)

        with open(os.path.join(self._dir.name, "glossary.json"), encoding="utf-8") as f:
            terms = json.load(f)["terms"]
        self.assertIn("alpha", terms)
        self.assertIn("beta", terms)

    def _record_body(self, body, sha="s1", updated_at="t1"):
        notified = self._write("notified.json", {"prs": [
            {"repo": "o/r", "number": 1, "sha": sha, "updated_at": updated_at,
             "body": body},
        ]})
        terms = self._write("terms.json", {"terms": []})
        return self._run(self.mod.cmd_record, input=terms, notified=notified,
                         open_prs=None)

    def _select(self, body, sha="s2", updated_at="t2"):
        payload = self._write("select.json", {"prs": [
            {"repo": "o/r", "number": 1, "sha": sha, "updated_at": updated_at,
             "body": body},
        ]})
        return self._run(self.mod.cmd_select, input=payload)

    def test_body_diff_round_trips_through_record_and_select(self):
        # #11 の目的。前回の本文を保管し、次回に「どこが変わったか」を出す。
        out = self._record_body("## 背景\n最初の説明")
        self.assertEqual(out["bodies_saved"], 1)

        got = self._select("## 背景\n最初の説明\n\n## 追記\nレビューを受けて補足")
        target = got["targets"][0]
        self.assertEqual(target["status"], "updated")
        self.assertTrue(target["body_diff_available"])
        self.assertIn("+## 追記", target["body_diff"])

    def test_body_diff_is_empty_when_only_code_changed(self):
        # 本文が変わっていないのに差分を出すと、読み手を惑わせる。
        self._record_body("同じ本文")
        target = self._select("同じ本文")["targets"][0]
        self.assertTrue(target["body_diff_available"])
        self.assertEqual(target["body_diff"], "")

    def test_body_diff_is_unavailable_on_first_encounter(self):
        # 初回は前回の本文が無い。異常ではなく、全体を説明すればよい。
        target = self._select("初めての本文", sha="s1", updated_at="t1")["targets"][0]
        self.assertEqual(target["status"], "new")
        self.assertFalse(target["body_diff_available"])

    def test_body_is_not_stored_in_state_json(self):
        # state.json は人が開いて確認できる大きさに保つ（#11 の設計判断）。
        self._record_body("x" * 3000)
        with open(os.path.join(self._dir.name, "state.json"), encoding="utf-8") as f:
            raw = f.read()
        self.assertNotIn("x" * 100, raw)
        self.assertIn("o/r#1", raw)

    def test_body_count_limit_applies_without_open_prs(self):
        # SKILL.md は「迷ったら渡さない」と指示しているので、--open-prs 無しが
        # 通常の経路。そこで上限が効かないと、README に書いた 200 件が成立しない。
        bodies_dir = os.path.join(self._dir.name, "bodies")
        for i in range(5):
            path, _ = bodies.save(bodies_dir, "o/r", i, "old")
            os.utime(path, (1000 + i, 1000 + i))
        original = bodies.MAX_BODIES
        bodies.MAX_BODIES = 3
        try:
            out = self._record_body("新しい本文", sha="s9", updated_at="t9")
        finally:
            bodies.MAX_BODIES = original
        self.assertTrue(out["state_saved"])
        self.assertGreater(out["bodies_pruned"], 0)
        self.assertLessEqual(len(os.listdir(bodies_dir)), 3)

    def test_bodies_are_pruned_with_the_state(self):
        # 閉じた PR の本文を残し続けない。
        self._record_body("残る", sha="s1")
        notified = self._write("n2.json", {"prs": [
            {"repo": "o/other", "number": 9, "sha": "s9", "updated_at": "t9",
             "body": "別の PR"},
        ]})
        open_prs = self._write("open.json", {"prs": [
            {"repo": "o/other", "number": 9, "sha": "s9", "updated_at": "t9"},
        ]})
        terms = self._write("t2.json", {"terms": []})
        out = self._run(self.mod.cmd_record, input=terms, notified=notified,
                        open_prs=open_prs)
        self.assertEqual(out["bodies_pruned"], 1)
        self.assertIsNone(bodies.load(
            os.path.join(self._dir.name, "bodies"), "o/r", 1))

    def test_missing_body_does_not_look_like_a_deleted_description(self):
        # body の渡し忘れが「本文が全部消された」差分になって出ていた。
        # 利用者には嘘の説明として届くため、差分を出さないほうが正しい。
        self._record_body("## 背景\n消えていない本文")
        payload = self._write("nobody.json", {"prs": [
            {"repo": "o/r", "number": 1, "sha": "s2", "updated_at": "t2"},
        ]})
        target = self._run(self.mod.cmd_select, input=payload)["targets"][0]
        self.assertEqual(target["status"], "updated")
        self.assertFalse(target["body_diff_available"])
        self.assertEqual(target["body_diff"], "")

    def test_empty_body_is_still_diffed(self):
        # 「渡し忘れ」と違い、本当に空にした場合は削除として出す。
        self._record_body("消される本文")
        target = self._select("")["targets"][0]
        self.assertTrue(target["body_diff_available"])
        self.assertIn("-消される本文", target["body_diff"])

    def test_non_string_body_does_not_abort_the_run(self):
        # state と用語集は確定済み。本文はキャッシュなので巻き添えにしない。
        notified = self._write("bad.json", {"prs": [
            {"repo": "o/r", "number": 1, "sha": "s1", "updated_at": "t1",
             "body": {"text": "oops"}},
        ]})
        terms = self._write("t.json", {"terms": []})
        out = self._run(self.mod.cmd_record, input=terms, notified=notified,
                        open_prs=None)
        self.assertTrue(out["state_saved"])
        self.assertEqual(out["bodies_saved"], 0)
        self.assertTrue(any("文字列ではない" in w for w in out["warnings"]))

    def test_non_string_body_is_skipped_in_select(self):
        self._record_body("前回の本文")
        payload = self._write("badsel.json", {"prs": [
            {"repo": "o/r", "number": 1, "sha": "s2", "updated_at": "t2",
             "body": ["not", "a", "string"]},
        ]})
        out = self._run(self.mod.cmd_select, input=payload)
        self.assertFalse(out["targets"][0]["body_diff_available"])
        self.assertTrue(any("文字列ではない" in w for w in out["warnings"]))

    def test_long_body_is_reported_as_truncated(self):
        # 黙って切り詰めると、次回の差分がずれた理由が分からない。
        out = self._record_body("あ" * (bodies.MAX_BODY_BYTES))
        self.assertTrue(any("先頭のみ保存" in w for w in out["warnings"]))

    def test_record_holds_the_state_lock_while_writing_bodies(self):
        # state の記録と本文は対で意味を持つ（記録に対応する本文が次回の差分の
        # 基準）。本文の保存がロックの外にあると、state を書き終えてから本文を
        # 書くまでの間に、並走した実行の掃除が入りうる（#4）。
        #
        # 競合そのものは実行のたびに再現するとは限らないため、ここでは
        # 「本文を書いている間ロックを保持しているか」という不変条件を直接見る。
        import threading

        observed = []
        original = bodies.save

        def _watching_save(bodies_dir, repo, number, body):
            # 本文を書いている最中に、別スレッドがロックを取れてしまわないか。
            def _probe():
                try:
                    with store.locked(
                        os.path.join(self._dir.name, "state.json"), timeout=0.2
                    ):
                        observed.append("acquired")
                except store.Busy:
                    observed.append("busy")

            t = threading.Thread(target=_probe)
            t.start()
            t.join()
            return original(bodies_dir, repo, number, body)

        bodies.save = _watching_save
        try:
            self._record_body("本文", sha="s1", updated_at="t1")
        finally:
            bodies.save = original

        self.assertEqual(
            observed, ["busy"],
            "本文の書き込み中に state ロックが取得できた"
            "（保存がロックの外にある）",
        )

    def test_select_holds_the_state_lock_while_reading_bodies(self):
        # 読む側も同じ。record の途中の state と本文の組み合わせを読まない。
        import threading

        self._record_body("前回の本文")
        observed = []
        original = bodies.load

        def _watching_load(bodies_dir, repo, number):
            def _probe():
                try:
                    with store.locked(
                        os.path.join(self._dir.name, "state.json"), timeout=0.2
                    ):
                        observed.append("acquired")
                except store.Busy:
                    observed.append("busy")

            t = threading.Thread(target=_probe)
            t.start()
            t.join()
            return original(bodies_dir, repo, number)

        bodies.load = _watching_load
        try:
            self._select("今回の本文")
        finally:
            bodies.load = original

        self.assertEqual(
            observed, ["busy"],
            "本文の読み込み中に state ロックが取得できた"
            "（読み込みがロックの外にある）",
        )

    def test_render_returns_a_command_that_opens_the_html(self):
        # パスだけでは「どう開くか」が利用者に委ねられる。そのまま実行できる形で返す。
        out, _ = self._render(None)
        self.assertIn(out["path"], out["open_command"])

    def test_open_command_quotes_the_path(self):
        # 設定ディレクトリは利用者のホーム配下にあり、空白を含みうる。
        cmd = self.mod._open_command("/a b/c.html")
        self.assertIn('"/a b/c.html"', cmd)


class TestRenderGlossary(unittest.TestCase):
    def _data(self, language="ja"):
        return {
            "language": language,
            "groups": [
                {"status": "known", "terms": [{"term": "SSoT", "definition": "x", "occurrences": 0}]},
                {"status": "learning", "terms": [{"term": "backoff", "definition": "y", "occurrences": 3}]},
            ],
        }

    def test_has_no_pr_chrome(self):
        # PR 用の描画を流用すると「必須」バッジなど無関係な体裁が付く。
        h = render.render_glossary(self._data())
        self.assertNotIn("必須", h)
        self.assertNotIn("Must review", h)

    def test_groups_are_labelled_in_language(self):
        self.assertIn("理解済み", render.render_glossary(self._data("ja")))
        self.assertIn("Known", render.render_glossary(self._data("en")))

    def test_shows_occurrences(self):
        self.assertIn("×3", render.render_glossary(self._data()))

    def test_is_offline(self):
        h = render.render_glossary(self._data())
        self.assertNotIn("https://", h)


if __name__ == "__main__":
    unittest.main()
