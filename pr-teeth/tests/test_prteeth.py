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

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from prteeth import (  # noqa: E402
    agent_input, auth, config, document, glossary, labels, render, scope, state, store,
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

    def test_empty_source_is_an_error(self):
        # 黙って変な場所に書くより、はっきり失敗させる。
        with self.assertRaises(ValueError):
            config.config_dir("")


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
