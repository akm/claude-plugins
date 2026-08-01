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

from prteeth import auth, config, glossary, labels, render, scope, state, store  # noqa: E402


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

    def test_record_prunes_closed_prs(self):
        # 閉じた PR の記録を残すと、再オープン時に誤判定しうる。
        prev = {"notified": {"o/r#1": {"sha": "a"}, "o/r#99": {"sha": "z"}}}
        new = state.record_notified(prev, [self._pr()])
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


class TestRender(unittest.TestCase):
    def _doc(self, **kw):
        base = {
            "language": "ja",
            "prs": [
                {
                    "repo": "o/r", "number": 1, "title": "T", "language": "en",
                    "priority": "should_review", "counts": {"should_review": 1},
                    "summary": "S", "changes": ["c"],
                }
            ],
        }
        base.update(kw)
        return base

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
        d = self._doc()
        d["prs"][0]["summary"] = "<script>alert(1)</script>"
        h = render.render(d)
        self.assertNotIn("<script>alert(1)</script>", h)
        self.assertIn("&lt;script&gt;", h)

    def test_known_terms_are_not_rendered(self):
        d = self._doc()
        d["prs"][0]["terms"] = [
            {"term": "SSoT", "status": "known", "definition": "x"},
            {"term": "jitter", "status": "new", "definition": "y"},
        ]
        h = render.render(d)
        self.assertIn("jitter", h)
        self.assertNotIn("SSoT", h)

    def test_no_external_assets_without_diagram(self):
        # 図が無ければ CDN も読まない（完全にオフラインで開ける）。
        h = render.render(self._doc())
        self.assertNotIn("http://", h)
        self.assertNotIn("https://", h)

    def test_diagram_code_survives_when_mermaid_unavailable(self):
        d = self._doc()
        d["prs"][0]["diagram"] = "flowchart LR\n A-->B"
        h = render.render(d)
        self.assertIn("mermaid-src", h)
        self.assertIn("flowchart LR", h)


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
