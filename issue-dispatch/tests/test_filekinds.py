#!/usr/bin/env python3
"""ファイルの種類の決定 (issue-dispatch/scripts/issue_dispatch/filekinds.py) と、CLI の `files classify` のテスト。

標準ライブラリの unittest だけで動く。`gh` は使わない。

  python3 -m unittest discover -s issue-dispatch/tests

種類と属性・パターンの書き方・照合の順の正本は issue-dispatch/skills/issue-dispatch/references/file-kinds.md。
"""

import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest

_SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, _SCRIPTS)

from issue_dispatch import filekinds  # noqa: E402

_CLI = os.path.join(_SCRIPTS, "issue_dispatch.py")
_DOC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skills", "issue-dispatch", "references", "file-kinds.md")
_DEFAULT = filekinds.load_default_table()


class PatternTest(unittest.TestCase):
    """パターンの書き方 (file-kinds.md の「パターンの書き方」)。"""

    def test_star_does_not_cross_directories(self):
        self.assertTrue(filekinds.matches("*.pb.go", "api.pb.go"))
        self.assertFalse(filekinds.matches("*.pb.go", "gen/api.pb.go"), "`*` は `/` を越えないこと")

    def test_double_star_matches_any_depth(self):
        self.assertTrue(filekinds.matches("**/*.pb.go", "api.pb.go"), "`**/` は 0 個のディレクトリにも一致すること")
        self.assertTrue(filekinds.matches("**/*.pb.go", "gen/api.pb.go"))
        self.assertTrue(filekinds.matches("**/*.pb.go", "a/b/c/api.pb.go"))

    def test_single_level(self):
        self.assertTrue(filekinds.matches("src/*.ts", "src/app.ts"))
        self.assertFalse(filekinds.matches("src/*.ts", "src/lib/a.ts"))

    def test_trailing_slash_means_everything_below(self):
        self.assertTrue(filekinds.matches("dist/", "dist/app.js"))
        self.assertTrue(filekinds.matches("dist/", "dist/assets/a.js"))
        self.assertFalse(filekinds.matches("dist/", "dist"), "ディレクトリそのものの名前には一致しないこと")
        self.assertFalse(filekinds.matches("dist/", "distribution/a.js"))

    def test_whole_path_is_matched(self):
        self.assertFalse(filekinds.matches("app.ts", "src/app.ts"), "ルートからのパス全体と照合すること (.gitignore の規則とは違う)")
        self.assertFalse(filekinds.matches("src/app", "src/app.ts"), "前方一致ではないこと")

    def test_double_star_is_special_only_as_a_whole_segment(self):
        self.assertTrue(filekinds.matches("src/**.go", "src/a.go"))
        self.assertFalse(filekinds.matches("src/**.go", "src/x/a.go"), "区切りの一部の `**` は `*` と同じで `/` を越えないこと")
        self.assertFalse(filekinds.matches("a**b", "a/x/b"))
        self.assertFalse(filekinds.matches("foo**/bar", "foobar"))
        self.assertTrue(filekinds.matches("a/**/b", "a/b"))
        self.assertTrue(filekinds.matches("a/**/b", "a/c/d/b"))

    def test_trailing_double_star_needs_a_name(self):
        self.assertFalse(filekinds.matches("dist/**", "dist/"), "名前が空の要素には一致しないこと")
        self.assertFalse(filekinds.matches("dist/**", "dist"))
        self.assertTrue(filekinds.matches("dist/**", "dist/a"))

    def test_character_class(self):
        self.assertTrue(filekinds.matches("[ab].txt", "a.txt"))
        self.assertFalse(filekinds.matches("[ab].txt", "c.txt"))
        self.assertTrue(filekinds.matches("[!ab].txt", "c.txt"))
        self.assertTrue(filekinds.matches("a[.txt", "a[.txt"), "閉じない `[` はそのままの文字であること")

    @unittest.skipUnless(sys.version_info >= (3, 13), "PurePath.full_match は Python 3.13 から")
    def test_same_as_full_match(self):
        """正本の「Python 3.13 の `PurePath.full_match` と同じ規則」を、同じ組で確認する (末尾が `/` のパターンは拡張なので除く)。"""
        from pathlib import PurePosixPath
        patterns = ("*.pb.go", "**/*.pb.go", "src/*.ts", "src/**.go", "**", "dist/**", "**/x", "a/**/b", "[ab].txt",
                    "[!ab].txt", "*.md", "a?.txt", "a**b", "foo**/bar", "a/**b", "**/**/a", "a[.txt")
        paths = ("api.pb.go", "gen/api.pb.go", "src/app.ts", "src/lib/a.ts", "src/a.go", "src/x/a.go", "a", "a/b", "dist",
                 "dist/a", "dist/a/b", "x", "a/b/x", "a/c/b", "a/c/d/b", "a.txt", "c.txt", "README.MD", "ab.txt", "a/x/b",
                 "foobar", "a/xb", "a/x/yb", "a[.txt")
        for pattern in patterns:
            for path in paths:
                with self.subTest(pattern=pattern, path=path):
                    self.assertEqual(filekinds.matches(pattern, path), PurePosixPath(path).full_match(pattern))

    def test_question_mark_and_escaping(self):
        self.assertTrue(filekinds.matches("a?.txt", "ab.txt"))
        self.assertFalse(filekinds.matches("a?.txt", "a/.txt"))
        self.assertFalse(filekinds.matches("a.txt", "aXtxt"), "`.` はそのままの文字として照合すること")


class NormalizePathTest(unittest.TestCase):
    """照合の前のパスのそろえ方 (file-kinds.md の「照合の順」)。"""

    def test_dot_segments_double_slashes_and_trailing_slash(self):
        for raw, expected in (("./a", "a"), ("a/", "a"), ("a//b", "a/b"), ("./src/./a.ts", "src/a.ts"), ("dist/", "dist")):
            with self.subTest(path=raw):
                self.assertEqual(filekinds.normalize_path(raw), (expected, None))

    def test_outside_root_is_rejected(self):
        for raw in ("/abs/a.md", "../x", "a/../../x", ".", "./", ""):
            with self.subTest(path=raw):
                normalized, problem = filekinds.normalize_path(raw)
                self.assertIsNone(normalized)
                self.assertTrue(problem, "差し戻す理由を返すこと")


class ClassifyTest(unittest.TestCase):
    """種類の決定 (file-kinds.md の「照合の順」)。"""

    def test_config_rules_come_before_default_table(self):
        """Covers AE42. 設定の `dist/**` → generated が、デフォルトの表の `**/*.js` → divisible より先。"""
        rules = [{"pattern": "dist/**", "kind": "generated"}]
        r = filekinds.classify("dist/app.js", rules, _DEFAULT)
        self.assertEqual(r["kind"], "generated")
        self.assertEqual(r["matched"], {"source": "config", "pattern": "dist/**"})
        r2 = filekinds.classify("src/app.js", rules, _DEFAULT)
        self.assertEqual(r2["kind"], "divisible", "設定に一致しなければデフォルトの表を使うこと")
        self.assertEqual(r2["matched"]["source"], "default")

    def test_earlier_stage_wins_when_two_rules_match(self):
        """種類の違う 2 つの規則に一致すれば、判定の条件の順で先の種類。"""
        rules = [{"pattern": "gen/**", "kind": "divisible"}, {"pattern": "**/*.go", "kind": "generated"}]
        r = filekinds.classify("gen/a.go", rules, _DEFAULT)
        self.assertEqual(r["kind"], "generated", "規則の並び順ではなく判定の条件の順で決めること")
        self.assertEqual(r["matched"]["pattern"], "**/*.go")

    def test_first_rule_wins_among_the_same_kind(self):
        """同じ種類の 2 つの規則に一致すれば、先に書いた規則の属性。"""
        rules = [{"pattern": "**/package.json", "kind": "divisible", "unit_notation": {"notation": "json-key", "keys": ["dependencies"]}},
                 {"pattern": "**/*.json", "kind": "divisible", "unit_notation": "json-key"}]
        r = filekinds.classify("app/package.json", rules, _DEFAULT)
        self.assertEqual(r["unit_notation"], {"notation": "json-key", "keys": ["dependencies"]})
        self.assertEqual(r["matched"]["pattern"], "**/package.json")
        r2 = filekinds.classify("app/package.json", rules[::-1], _DEFAULT)
        self.assertEqual(r2["unit_notation"], "json-key", "順序を逆にすれば、先に書いた広い規則の属性になること")

    def test_unknown_content_when_nothing_matches(self):
        r = filekinds.classify("notes/x.unknownext", [], _DEFAULT)
        self.assertEqual(r, {"kind": "unknown-content", "unit_notation": None, "split_reference": None,
                             "mergeable": True, "matched": None})

    def test_config_can_declare_unknown_structure(self):
        rules = [{"pattern": "data/**", "kind": "unknown-structure"}]
        self.assertEqual(filekinds.classify("data/a.bin", rules, _DEFAULT)["kind"], "unknown-structure")

    def test_attributes_come_from_the_matched_rule(self):
        rules = [{"pattern": "docs/**/*.md", "kind": "unstable",
                  "unit_notation": {"notation": "markdown-heading"}, "split_reference": "file", "mergeable": True}]
        r = filekinds.classify("docs/a/b.md", rules, _DEFAULT)
        self.assertEqual(r["kind"], "unstable")
        self.assertEqual(r["unit_notation"], {"notation": "markdown-heading"})
        self.assertEqual(r["split_reference"], "file")
        self.assertTrue(r["mergeable"])

    def test_rule_with_unknown_kind_is_an_error(self):
        """`unknown-content` と知らない種類の規則は書けない (設定では config が警告して外す)。"""
        for kind in ("unknown-content", "typo"):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                filekinds.classify("x/y.go", [{"pattern": "**", "kind": kind}], _DEFAULT)


class DefaultTableTest(unittest.TestCase):
    """デフォルトの表 (file-kinds.json) と file-kinds.md の表の一致。"""

    def test_each_default_row_classifies_as_written(self):
        for rule in _DEFAULT:
            sample = rule["pattern"].replace("**/", "a/b/").replace("*", "x")
            with self.subTest(pattern=rule["pattern"]):
                r = filekinds.classify(sample, [], _DEFAULT)
                self.assertEqual(r["kind"], rule["kind"], f"{sample} の種類")
                self.assertEqual(r["mergeable"], rule.get("mergeable", True))

    def test_default_rows_use_known_kinds_and_attributes(self):
        notations = {"json-key", "yaml-key", "toml-table", "markdown-heading", "make-target",
                     "go-mod-directive", "dockerfile-stage", "terraform-block"}
        for rule in _DEFAULT:
            with self.subTest(pattern=rule["pattern"]):
                self.assertIn(rule["kind"], filekinds.RULE_KINDS)
                self.assertLessEqual(set(rule) - {"pattern", "kind", "unit_notation", "split_reference", "mergeable"}, set())
                if "split_reference" in rule:
                    self.assertIn(rule["split_reference"], ("directory", "file"))
                if "unit_notation" in rule:
                    notation = rule["unit_notation"]
                    name = notation if isinstance(notation, str) else notation["notation"]
                    self.assertIn(name, notations, "節の表記の名前は file-kinds.md の表の名前であること")
                    if isinstance(notation, dict):
                        self.assertLessEqual(set(notation), {"notation", "keys"})
                if rule["kind"] in ("unstable", "divisible"):
                    self.assertIn("split_reference", rule, "分けられる種類には参照のされ方が要ること")

    def test_default_rows_appear_in_the_document(self):
        """file-kinds.md の「デフォルトの表」の節に、表のすべてのパターンが書かれている。"""
        with open(_DOC, encoding="utf-8") as f:
            doc = f.read()
        for rule in _DEFAULT:
            with self.subTest(pattern=rule["pattern"]):
                self.assertIn(f"`{rule['pattern']}`", doc)

    def test_specific_rows(self):
        self.assertEqual(filekinds.classify("api/v1/service.pb.go", [], _DEFAULT)["kind"], "generated")
        self.assertEqual(filekinds.classify("infra/terraform.tfstate.backup", [], _DEFAULT)["kind"], "generated")
        self.assertEqual(filekinds.classify("pkg/apis/zz_generated.deepcopy.go", [], _DEFAULT)["kind"], "generated")
        png = filekinds.classify("assets/logo.png", [], _DEFAULT)
        self.assertEqual((png["kind"], png["mergeable"]), ("indivisible", False))
        self.assertEqual(filekinds.classify("db/migrations/001_init.sql", [], _DEFAULT)["kind"], "unstable")
        self.assertEqual(filekinds.classify("report.xlsx", [], _DEFAULT)["kind"], "unknown-structure")
        pkg = filekinds.classify("package.json", [], _DEFAULT)
        self.assertEqual(pkg["unit_notation"], {"notation": "json-key", "keys": ["dependencies", "devDependencies"]},
                         "`**/*.json` より前の `**/package.json` の属性になること")
        self.assertEqual(filekinds.classify("config/app.json", [], _DEFAULT)["unit_notation"], "json-key")
        self.assertEqual(filekinds.classify("a/npm-shrinkwrap.json", [], _DEFAULT)["kind"], "generated",
                         "`**/*.json` より判定の条件の順で先の generated になること")
        self.assertEqual(filekinds.classify("cmd/main.go", [], _DEFAULT)["split_reference"], "directory")
        self.assertEqual(filekinds.classify("src/app.ts", [], _DEFAULT)["split_reference"], "file")


class IndependenceTest(unittest.TestCase):
    """`filekinds` は `issue_dispatch` のほかのモジュールを import しない (KD22)。"""

    def test_no_import_of_sibling_modules(self):
        path = os.path.join(_SCRIPTS, "issue_dispatch", "filekinds.py")
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
                if node.level:
                    imported.add(".")
        self.assertEqual(imported, {"json", "os", "re"}, "標準ライブラリだけを import すること")


class CliTest(unittest.TestCase):
    """`files classify`。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *args):
        return subprocess.run([sys.executable, _CLI, *args], capture_output=True, text=True)

    def test_classify_uses_repo_config_and_default_table(self):
        cfg = os.path.join(self.root, ".claude", "akm-claude-plugins", "issue-dispatch", "config.json")
        os.makedirs(os.path.dirname(cfg))
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump({"files": [{"pattern": "./dist/**", "kind": "generated"}]}, f)
        p = self._run("files", "classify", "--dir", self.root, "dist/app.js", "src/app.js", "x.unknownext")
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        kinds = {r["normalized"]: r["kind"] for r in out["paths"]}
        self.assertEqual(kinds, {"dist/app.js": "generated", "src/app.js": "divisible", "x.unknownext": "unknown-content"})
        self.assertEqual(out["paths"][0]["matched"], {"source": "config", "pattern": "dist/**"},
                         "設定のパターンは config がそろえた形で返ること")
        self.assertEqual(out["paths"][1]["split_reference"], "file")
        self.assertEqual(out["warnings"], [])

    def test_classify_normalizes_paths_and_rejects_outside_root(self):
        """`./src/a.ts`・`src//a.ts`・`src/a.ts/` は設定の `src/*.ts` に一致する。絶対パスと `..` は error。"""
        cfg = os.path.join(self.root, ".claude", "akm-claude-plugins", "issue-dispatch", "config.json")
        os.makedirs(os.path.dirname(cfg))
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump({"files": [{"pattern": "src/*.ts", "kind": "generated"}]}, f)
        p = self._run("files", "classify", "--dir", self.root, "./src/a.ts", "src//a.ts", "src/a.ts/", "/abs/a.ts", "../x/a.ts")
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)["paths"]
        inputs = ["./src/a.ts", "src//a.ts", "src/a.ts/", "/abs/a.ts", "../x/a.ts"]
        self.assertEqual([r["path"] for r in out], inputs, "要素は入力と同じ順序で、path は書いたままの値であること")
        for r in out[:3]:
            with self.subTest(path=r["path"]):
                self.assertEqual(r["normalized"], "src/a.ts", "normalized はそろえた後の値であること")
                self.assertEqual(r["kind"], "generated")
        for r in out[3:]:
            with self.subTest(path=r["path"]):
                self.assertNotIn("kind", r, "差し戻したパスには種類を返さないこと")
                self.assertNotIn("normalized", r)
                self.assertTrue(r["error"])

    def test_classify_without_config(self):
        p = self._run("files", "classify", "--dir", self.root, "a.md")
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual(out["paths"][0]["unit_notation"], "markdown-heading")
        self.assertEqual(out["config_status"], "missing")


if __name__ == "__main__":
    unittest.main()
