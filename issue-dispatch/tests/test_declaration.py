#!/usr/bin/env python3
"""宣言 (issue-dispatch/scripts/issue_dispatch/declaration.py) と、CLI の `declaration parse` / `declaration conflictability` の
テスト。gh は使わない。リポジトリの設定の規則は config.load_text で作り、デフォルトの表は filekinds.load_default_table で読む。

  python3 -m unittest discover -s issue-dispatch/tests

様式の正本は issue-dispatch/skills/issue-dispatch/references/issue-format.md の「宣言」。
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.join(_HERE, "..", "scripts")
sys.path.insert(0, _SCRIPTS)

from issue_dispatch import config, declaration, filekinds  # noqa: E402

_CLI = os.path.join(_SCRIPTS, "issue_dispatch.py")
_DOC = os.path.join(_HERE, "..", "skills", "issue-dispatch", "references", "issue-format.md")
TABLE = filekinds.load_default_table()
REPO = "akm/issue-dispatch-verify-a"
RULES = config.load_text(json.dumps({"files": [{"pattern": "**/*.gen.ts", "kind": "generated"}, {"pattern": "vendor/", "kind": "unknown-structure"}]}),
                         "repo", "test")["config"]["files"]


def decl(files=(), resources=(), split=None):
    """宣言の JSON (dict) を作る。files の要素は "path" か ("path", units)。"""
    out_files = []
    for f in files:
        if isinstance(f, tuple):
            out_files.append({"path": f[0], "units": f[1]})
        else:
            out_files.append({"path": f})
    return {"files": out_files, "resources": list(resources), "split": split if split is not None else {"needed": False, "reason": ""}}


def parsed(files=(), resources=(), split=None, rules=RULES):
    result = declaration.parse(decl(files, resources, split), rules, TABLE)
    assert result["status"] == "ok", result["errors"]
    return result["declaration"]


class ParseTest(unittest.TestCase):

    def test_accepts_minimal_and_empty_files(self):
        """必須キーが揃っていれば受理し、files が 0 件でも受理して件数 0 を返す。"""
        result = declaration.parse(decl(), RULES, TABLE)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["declaration"]["files"], [])
        self.assertEqual(result["count"], 0)

    def test_accepts_full_declaration(self):
        result = declaration.parse(decl([("package.json", [["dependencies", "zod"], ["exports", "./utils"]]), "src/app.ts", "docs/guide.md"],
                                        ["staging-db"], {"needed": True, "reason": "大きい", "remaining": "API の部分", "blocked_by": [f"https://github.com/{REPO}/issues/5"]}),
                                   RULES, TABLE)
        self.assertEqual(result["status"], "ok", result["errors"])
        d = result["declaration"]
        self.assertEqual([f["path"] for f in d["files"]], ["package.json", "src/app.ts", "docs/guide.md"])
        self.assertEqual(d["files"][0]["units"], [["dependencies", "zod"], ["exports", "./utils"]])
        self.assertIsNone(d["files"][1]["units"], "units を省けばファイル全体")
        self.assertEqual(d["files"][0]["kind"]["kind"], "divisible")
        self.assertEqual(d["files"][0]["kind"]["matched"]["pattern"], "**/package.json")
        self.assertEqual(d["resources"], ["staging-db"])
        self.assertEqual(d["split"]["blocked_by"], [f"{REPO}#5"], "blocked_by は owner/repo#番号 の正規形にそろえる")
        self.assertEqual(result["count"], 3)

    def assertRejected(self, obj, key_part, msg_part=None):
        result = declaration.parse(obj, RULES, TABLE)
        self.assertEqual(result["status"], "error", obj)
        self.assertTrue(any(key_part in e["key"] for e in result["errors"]), f"{key_part} を指す errors が無い: {result['errors']}")
        if msg_part:
            self.assertTrue(any(msg_part in e["message"] for e in result["errors"]), f"{msg_part!r} を含む message が無い: {result['errors']}")
        return result

    def test_rejects_unknown_and_missing_keys(self):
        """未知のキー (file の誤字)・欠けた必須キーは、理由と期待する形を含むエラーで拒否する。kind も未知のキー。"""
        self.assertRejected({"file": [], "resources": [], "split": {"needed": False, "reason": ""}}, "file", "未知のキー")
        self.assertRejected({"resources": [], "split": {"needed": False, "reason": ""}}, "files", "必須")
        self.assertRejected({"files": [{"path": "a.md", "kind": "divisible"}], "resources": [], "split": {"needed": False, "reason": ""}}, "files[0].kind", "未知のキー")
        self.assertRejected({"files": [{"units": [["a"]]}], "resources": [], "split": {"needed": False, "reason": ""}}, "files[0].path", "必須")
        self.assertRejected("not an object", "(root)", "オブジェクト")
        self.assertRejected(decl(resources=["db", 1]), "resources[1]", "文字列")

    def test_rejects_bad_split(self):
        """Covers AE44. needed が真なのに reason・remaining・blocked_by のどれかが無ければ拒否し、偽なのに remaining か blocked_by があれば拒否する。"""
        self.assertRejected(decl(split={"needed": True, "reason": "大きい", "remaining": "x"}), "split.blocked_by", "必須")
        self.assertRejected(decl(split={"needed": True, "remaining": "x", "blocked_by": []}), "split.reason", "必須")
        self.assertRejected(decl(split={"needed": True, "reason": "r", "blocked_by": []}), "split.remaining", "必須")
        self.assertRejected(decl(split={"needed": False, "reason": "", "remaining": "x"}), "split.remaining", "needed が偽")
        self.assertRejected(decl(split={"needed": False, "reason": "", "blocked_by": []}), "split.blocked_by", "needed が偽")
        self.assertRejected(decl(split={"needed": "yes", "reason": ""}), "split.needed", "真偽値")
        self.assertRejected(decl(split={"needed": True, "reason": "r", "remaining": "x", "blocked_by": ["not a ref"]}), "split.blocked_by[0]", "Issue の参照")
        ok = declaration.parse(decl(split={"needed": True, "reason": "大きさのため", "remaining": "残り", "blocked_by": []}), RULES, TABLE)
        self.assertEqual(ok["status"], "ok", "blocked_by の空の配列は受け付ける")

    def test_rejects_units_where_no_notation(self):
        """節の表記が無いパスに units があれば拒否し、理由に種類の判断に使った規則を含める。"""
        r = self.assertRejected(decl([("src/app.ts", [["main"]])]), "files[0].units", "unit_notation")
        self.assertTrue(any("**/*.ts" in e["message"] and "default" in e["message"] for e in r["errors"]), r["errors"])
        r = self.assertRejected(decl([("src/a.gen.ts", [["x"]])]), "files[0].units", "generated")
        self.assertTrue(any("**/*.gen.ts" in e["message"] and "config" in e["message"] for e in r["errors"]), r["errors"])
        self.assertRejected(decl([("vendor/lib.json", [["x"]])]), "files[0].units", "unknown-structure")
        self.assertRejected(decl([("bin/tool", [["x"]])]), "files[0].units", "unknown-content")
        self.assertEqual(declaration.parse(decl(["bin/tool", "src/a.gen.ts"]), RULES, TABLE)["status"], "ok", "units が無ければどの種類でも受理する")

    def test_rejects_bad_units_shape(self):
        """units の要素が文字列・空の配列・文字列でない名前なら、理由と期待する形 (文字列の配列の配列) を含むエラー。"""
        for units in (["dependencies.zod"], [[]], [[1]], [["a", None]], "dependencies", [["a"], "b"]):
            with self.subTest(units=units):
                self.assertRejected(decl([("package.json", units)]), "files[0].units", "文字列の配列の配列")

    def test_normalizes_paths(self):
        """Covers AE4. `./src/app.ts`・`src/app.ts`・`src//app.ts`・`src/../src/app.ts` は同じパス。"""
        for path in ("./src/app.ts", "src/app.ts", "src//app.ts", "src/../src/app.ts", "src/./app.ts"):
            with self.subTest(path=path):
                self.assertEqual(parsed([path])["files"][0]["path"], "src/app.ts")

    def test_rejects_outside_paths(self):
        """絶対パスと、ルートの外を指すパス (`../x`、正規化すると `../x` になる `src/../../x`) は拒否する。"""
        for path in ("/etc/passwd", "../x", "src/../../x", ".", "", "src/..", 3):
            with self.subTest(path=path):
                self.assertRejected(decl([path]), "files[0].path")

    def test_duplicate_paths_rejected(self):
        self.assertRejected(decl(["src/app.ts", "./src/app.ts"]), "files[1].path", "同じパス")


class UpdateKindTest(unittest.TestCase):
    """Covers AE46. 更新の種類 (R20)。"""

    def test_held_resources(self):
        go = parsed(["src/app.ts"], ["A", "B", "C"])
        self.assertEqual(declaration.held_resources(go, []), {"A", "B", "C"})
        self.assertEqual(declaration.held_resources(go, [parsed(["src/app.ts"], ["A", "B"]), parsed(["src/app.ts"], ["B"])]), {"B"},
                         "その後のどの更新にも残っているものだけ")
        self.assertEqual(declaration.held_resources(None, []), set(), "開始可の宣言がまだ無ければ空")

    def test_kinds(self):
        go = parsed(["src/app.ts", ("package.json", [["dependencies", "zod"]])], ["A", "B"])
        held = {"A", "B"}
        same_files = lambda res: parsed(["src/app.ts", ("package.json", [["dependencies", "zod"]])], res)  # noqa: E731
        self.assertEqual(declaration.update_kind(None, same_files(["A"]), set()), "initial", "開始可の宣言がまだ無ければ着手の宣言と同じ")
        self.assertEqual(declaration.update_kind(go, same_files(["A"]), held), "resources-removed-only", "B を外しただけ")
        self.assertEqual(declaration.update_kind(go, same_files(["A", "B", "C"]), held), "resources-only", "C を足した")
        self.assertEqual(declaration.update_kind(go, same_files(["A", "C"]), held), "resources-only", "B を外して C を足した (足した資源があるので外すだけではない)")
        self.assertEqual(declaration.update_kind(go, same_files(["A", "B"]), held), "full", "持っている資源と同じ更新は資源だけを変える更新ではない")
        self.assertEqual(declaration.update_kind(go, same_files(["B", "A"]), held), "full", "並びだけ違っても同じ")
        self.assertEqual(declaration.update_kind(go, parsed(["src/app.ts", "src/b.ts"], ["A"]), held), "full", "ファイルが違えばどちらとも判定しない")
        self.assertEqual(declaration.update_kind(go, parsed(["src/app.ts", ("package.json", [["dependencies", "react"]])], ["A"]), held), "full", "節が違っても同じ")
        self.assertEqual(declaration.update_kind(go, parsed([("package.json", [["dependencies", "zod"]]), "src/app.ts"], ["A"]), held),
                         "resources-removed-only", "ファイルの並びは問わない")

    def test_readd_and_successive_removals(self):
        """{A, B} が開始可 → {A} → {A, B} で B を足したと判定する。{X, Y, Z} → {X, Y} → {X} の 2 回目に外すのは Y だけ。"""
        go = parsed(["a.md"], ["A", "B"])
        first = parsed(["a.md"], ["A"])
        held = declaration.held_resources(go, [first])
        self.assertEqual(held, {"A"})
        self.assertEqual(declaration.update_kind(go, parsed(["a.md"], ["A", "B"]), held), "resources-only")
        self.assertEqual(declaration.resource_changes(parsed(["a.md"], ["A", "B"]), held), {"added": ["B"], "removed": []})
        go2 = parsed(["a.md"], ["X", "Y", "Z"])
        u1 = parsed(["a.md"], ["X", "Y"])
        held1 = declaration.held_resources(go2, [])
        self.assertEqual(declaration.resource_changes(u1, held1), {"added": [], "removed": ["Z"]})
        held2 = declaration.held_resources(go2, [u1])
        self.assertEqual(declaration.update_kind(go2, parsed(["a.md"], ["X"]), held2), "resources-removed-only")
        self.assertEqual(declaration.resource_changes(parsed(["a.md"], ["X"]), held2), {"added": [], "removed": ["Y"]}, "2 回目は Y だけを外したと数える")

    def test_rewrite_after_rejection_is_not_removal(self):
        """差し戻された宣言を書き直した更新は、資源が持っている資源より少なくても資源を外すだけの更新と判定しない (開始可が無ければ initial)。"""
        rejected = parsed(["a.md"], ["A", "B"])  # 差し戻された (呼び出し元は比べる相手に渡さない)
        rewritten = parsed(["a.md"], ["A"])
        self.assertEqual(declaration.update_kind(None, rewritten, declaration.held_resources(None, [])), "initial")
        del rejected


class ConflictabilityTest(unittest.TestCase):

    def judge(self, a, b, repo_a=REPO, repo_b=REPO):
        result = declaration.conflictability({"repo": repo_a, "declaration": a}, [{"id": "other", "repo": repo_b, "declaration": b}])
        return result

    def test_same_path_without_units_conflicts(self):
        """Covers AE4. divisible の同じパスを、units を省いた 2 つの宣言が持てば競合しうる。"""
        r = self.judge(parsed(["./src/app.ts"]), parsed(["src//app.ts"]))
        self.assertEqual(r["result"], "conflict")
        self.assertEqual(r["others"][0]["paths"], [{"path": "src/app.ts", "result": "conflict", "reason": r["others"][0]["paths"][0]["reason"]}])
        self.assertIn("units", r["others"][0]["paths"][0]["reason"])

    def test_units_prefix_rule(self):
        """Covers AE41. 両方が units を書けば、節が同じか先頭部分の一致のときだけ競合しうる。"""
        dep = lambda *units: parsed([("package.json", list(units))])  # noqa: E731
        self.assertEqual(self.judge(dep(["dependencies"]), dep(["dependencies", "react"]))["result"], "conflict", "先頭部分の一致")
        self.assertEqual(self.judge(dep(["dependencies", "react"]), dep(["dependencies"]))["result"], "conflict", "逆でも同じ")
        self.assertEqual(self.judge(dep(["dependencies", "zod"]), dep(["dependencies", "zod"]))["result"], "conflict", "同じ節")
        self.assertEqual(self.judge(dep(["dependencies", "react"]), dep(["dependencies", "zod"]))["result"], "none")
        self.assertEqual(self.judge(dep(["dependencies", "react"]), parsed(["package.json"]))["result"], "conflict", "一方が units を省けば競合しうる")
        self.assertEqual(self.judge(dep(["exports", "./utils"]), dep(["exports", "utils"]))["result"], "none", "名前は正規化しない")
        gomod = lambda *units: parsed([("go.mod", list(units))])  # noqa: E731
        self.assertEqual(self.judge(gomod(["require", "github.com/foo/bar"]), gomod(["require", "github"]))["result"], "none", "名前の中の . を区切りにしない")
        self.assertEqual(self.judge(dep(["dependencies", "react"], ["scripts"]), dep(["scripts", "test"]))["result"], "conflict", "複数の節のどれかが一致すれば競合しうる")

    def test_kinds(self):
        self.assertEqual(self.judge(parsed(["src/a.gen.ts"]), parsed(["src/a.gen.ts"]))["result"], "none", "generated は同じパスでも競合しない")
        self.assertEqual(self.judge(parsed(["vendor/lib.json"]), parsed(["vendor/lib.json"]))["result"], "conflict", "unknown-structure は同じパスで競合しうる")
        r = self.judge(parsed(["bin/tool"]), parsed(["bin/tool"]))
        self.assertEqual(r["result"], "needs-user", "unknown-content を含む組で同じパスなら利用者の判定が要る")
        self.assertEqual(self.judge(parsed(["src/app.ts"]), parsed(["src/app.ts"]), repo_b="akm/other")["result"], "none", "別のリポジトリの同じパスは競合しない")
        self.assertEqual(self.judge(parsed(["src/app.ts"]), parsed(["src/app.ts"]), repo_b=REPO.upper())["result"], "conflict", "リポジトリ名の大文字小文字は区別しない")
        self.assertEqual(self.judge(parsed(["src/app.ts"]), parsed(["src/other.ts"]))["result"], "none", "違うパスは競合しない")
        self.assertEqual(self.judge(parsed([]), parsed(["src/app.ts"]))["result"], "none")

    def test_overall_and_per_other(self):
        """相手ごとの結果と全体の結論 (conflict > needs-user > none)。"""
        mine = parsed(["src/app.ts", "bin/tool", "docs/a.md"])
        result = declaration.conflictability({"repo": REPO, "declaration": mine}, [
            {"id": "o1", "repo": REPO, "declaration": parsed(["bin/tool"])},
            {"id": "o2", "repo": REPO, "declaration": parsed(["docs/a.md"])},
            {"id": "o3", "repo": "akm/other", "declaration": parsed(["src/app.ts"])}])
        self.assertEqual([o["result"] for o in result["others"]], ["needs-user", "conflict", "none"])
        self.assertEqual(result["result"], "conflict")
        self.assertEqual([o["id"] for o in result["others"]], ["o1", "o2", "o3"])
        only_user = declaration.conflictability({"repo": REPO, "declaration": mine}, [{"id": "o1", "repo": REPO, "declaration": parsed(["bin/tool"])}])
        self.assertEqual(only_user["result"], "needs-user")
        self.assertEqual(declaration.conflictability({"repo": REPO, "declaration": mine}, [])["result"], "none")


class PrFilesCheckTest(unittest.TestCase):

    def test_reports_undeclared_files_with_other_declarations(self):
        """Covers AE58. 最新の宣言に無いファイル (generated を除く) と、そのファイルを宣言しているほかの開始可の宣言を返す。"""
        latest = parsed(["src/app.ts", ("package.json", [["dependencies", "zod"]])])
        others = [{"id": "o1", "repo": REPO, "declaration": parsed(["src/util.ts"])},
                  {"id": "o2", "repo": REPO, "declaration": parsed(["src/util.ts", "README.md"])},
                  {"id": "o3", "repo": "akm/other", "declaration": parsed(["src/util.ts"])}]
        result = declaration.pr_files_check(["src/app.ts", "./package.json", "src/util.ts", "src/a.gen.ts", "docs/new.md"], REPO, latest, others, RULES, TABLE)
        self.assertEqual([u["path"] for u in result["undeclared"]], ["src/util.ts", "docs/new.md"], "宣言にあるファイルと generated は返さない")
        self.assertEqual(result["undeclared"][0]["declared_by"], ["o1", "o2"], "別のリポジトリの宣言は数えない")
        self.assertEqual(result["undeclared"][1]["declared_by"], [])
        self.assertEqual(result["undeclared"][0]["kind"], "divisible")
        self.assertEqual(result["skipped_generated"], ["src/a.gen.ts"])

    def test_nothing_when_all_declared(self):
        latest = parsed(["src/app.ts"])
        result = declaration.pr_files_check(["src/app.ts"], REPO, latest, [], RULES, TABLE)
        self.assertEqual(result["undeclared"], [])

    def test_bad_changed_path(self):
        result = declaration.pr_files_check(["../x"], REPO, parsed([]), [], RULES, TABLE)
        self.assertEqual(result["undeclared"], [])
        self.assertEqual(result["problems"][0]["path"], "../x")


def _write_config(root, data):
    os.makedirs(os.path.join(root, ".claude", "akm-claude-plugins", "issue-dispatch"), exist_ok=True)
    with open(os.path.join(root, config.CONFIG_PATH), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


class CliTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        _write_config(self.root, {"files": [{"pattern": "**/*.gen.ts", "kind": "generated"}]})

    def tearDown(self):
        self._tmp.cleanup()

    @staticmethod
    def cli(*args, stdin=None):
        r = subprocess.run([sys.executable, _CLI, *args], capture_output=True, text=True, input=stdin)
        return r.returncode, json.loads(r.stdout) if r.stdout.strip() else None, r.stderr

    def test_parse(self):
        code, out, _ = self.cli("declaration", "parse", "--dir", self.root, "--body", json.dumps(decl([("package.json", [["dependencies", "zod"]]), "src/a.gen.ts"])))
        self.assertEqual((code, out["status"], out["count"], out["errors"]), (0, "ok", 2, []))
        self.assertEqual(out["declaration"]["files"][1]["kind"]["kind"], "generated", "リポジトリの設定の規則を --dir から読むこと")
        self.assertEqual(out["config_status"], "ok")
        code, out, _ = self.cli("declaration", "parse", "--dir", self.root, "--body-file", "-", stdin=json.dumps(decl([("src/app.ts", [["x"]])])))
        self.assertEqual((code, out["status"]), (0, "error"))
        self.assertEqual(out["errors"][0]["key"], "files[0].units")
        code, out, _ = self.cli("declaration", "parse", "--dir", self.root, "--body", "{not json")
        self.assertEqual((code, out["status"], out["errors"][0]["key"]), (0, "error", "body"))

    def test_conflictability_reads_repo_config_from_manager_dir(self):
        """管理ディレクトリの設定の repositories から、リポジトリの設定を既定のブランチの内容として読んで判定する。"""
        clone = os.path.join(self.root, "clone")
        os.makedirs(clone)
        env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
        for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
            env.pop(k, None)
        def git(*a):
            subprocess.run(["git", "-C", clone, *a], check=True, capture_output=True, env=env)
        git("init", "-q", "-b", "main")
        _write_config(clone, {"files": [{"pattern": "**/*.gen.ts", "kind": "generated"}]})
        git("add", "."); git("commit", "-q", "-m", "init")
        git("remote", "add", "origin", f"https://github.com/{REPO}.git")
        git("update-ref", "refs/remotes/origin/main", "HEAD")
        git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        manager = os.path.join(self.root, "manager")
        _write_config(manager, {"project": {"owner": "akm", "number": 3}, "repositories": {REPO: clone}})
        body = {"declaration": decl(["src/a.gen.ts", "src/app.ts"]), "others": [
            {"id": f"{REPO}#1", "repo": REPO, "declaration": decl(["src/a.gen.ts"])},
            {"id": f"{REPO}#2", "repo": REPO, "declaration": decl(["src/app.ts"])},
            {"id": "akm/other#9", "repo": "akm/other", "declaration": decl(["src/app.ts"])}]}
        code, out, err = self.cli("declaration", "conflictability", "--dir", manager, "--repo", REPO, "--body-file", "-", stdin=json.dumps(body))
        self.assertEqual((code, out["status"], out["errors"]), (0, "ok", []), err)
        self.assertEqual(out["result"], "conflict")
        self.assertEqual([o["result"] for o in out["others"]], ["none", "conflict", "none"], "generated は設定の規則で決まる")
        self.assertEqual(out["repo_config"]["status"], "ok")

    def test_conflictability_refuses_when_repo_config_unreadable(self):
        """読めないときは判定せず、理由と直し方を返す (KTD9)。"""
        manager = os.path.join(self.root, "manager")
        _write_config(manager, {"project": {"owner": "akm", "number": 3}, "repositories": {}})
        body = {"declaration": decl(["src/app.ts"]), "others": []}
        code, out, _ = self.cli("declaration", "conflictability", "--dir", manager, "--repo", REPO, "--body-file", "-", stdin=json.dumps(body))
        self.assertEqual((code, out["status"]), (0, "error"))
        self.assertEqual(out["errors"][0]["key"], "repo-config")
        self.assertEqual(out["repo_config"]["reason"], "not-in-repositories")
        self.assertIsNone(out["result"])

    def test_conflictability_rejects_bad_declaration(self):
        manager = os.path.join(self.root, "manager")
        clone = os.path.join(self.root, "clone2")
        _write_config(manager, {"project": {"owner": "akm", "number": 3}, "repositories": {REPO: clone}})
        body = {"declaration": {"files": "x"}, "others": []}
        code, out, _ = self.cli("declaration", "conflictability", "--dir", manager, "--repo", REPO, "--body-file", "-", stdin=json.dumps(body))
        self.assertEqual((code, out["status"]), (0, "error"))
        self.assertTrue(any(e["key"].startswith("declaration") or e["key"] == "repo-config" for e in out["errors"]), out["errors"])


class DocTest(unittest.TestCase):

    def test_doc_keys_match_module(self):
        """宣言のテストの必須キーが、issue-format.md の宣言のキーの表と同じ。"""
        with open(_DOC, encoding="utf-8") as f:
            doc = f.read()
        for key in ("`files`", "`files[].path`", "`files[].units`", "`resources`", "`split`", "`split.needed`", "`split.reason`", "`split.remaining`", "`split.blocked_by`"):
            self.assertIn(key, doc, f"キー {key} が文書に無い")
        for word in declaration.UPDATE_KINDS + declaration.CONFLICT_RESULTS:
            self.assertIn(f"`{word}`", doc, f"{word} が文書に無い")
        self.assertIn("この例は様式を示すもので、そのまま写さない", doc)


if __name__ == "__main__":
    unittest.main()
