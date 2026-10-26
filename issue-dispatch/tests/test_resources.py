#!/usr/bin/env python3
"""資源 (issue-dispatch/scripts/issue_dispatch/resources.py) と、CLI の `resources attributes` / `resources judge` のテスト。
gh は使わない。判定のテストは resources.md の契機の表の行ごとに書く。

  python3 -m unittest discover -s issue-dispatch/tests

様式と規則の正本は issue-dispatch/skills/issue-dispatch/references/resources.md。
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

from issue_dispatch import config, declaration, filekinds, resources  # noqa: E402

_CLI = os.path.join(_SCRIPTS, "issue_dispatch.py")
_DOC = os.path.join(_HERE, "..", "skills", "issue-dispatch", "references", "resources.md")
TABLE = filekinds.load_default_table()
REPO = "akm/issue-dispatch-verify-a"
I1, I2, I3 = f"{REPO}#1", f"{REPO}#2", f"{REPO}#3"


def decl(res, files=("src/app.ts",)):
    result = declaration.parse({"files": [{"path": p} for p in files], "resources": list(res), "split": {"needed": False, "reason": ""}}, [], TABLE)
    assert result["status"] == "ok", result["errors"]
    return result["declaration"]


def attrs(config_resources=None):
    return resources.attributes(config_resources or {})[0]


class AttributesTest(unittest.TestCase):
    """Covers AE51. 設定に無い資源と属性にデフォルト値を使い、未知の属性と誤った値は警告してデフォルト値を使う。"""

    def test_defaults(self):
        table, warnings = resources.attributes({})
        self.assertEqual(warnings, [])
        a = resources.attributes_of(table, "staging-db")
        self.assertEqual(a, {"name": "staging-db", "capacity": 1, "reserve": "on_assign", "when_busy": "wait", "release_undeclared": "ask"})
        self.assertEqual(resources.DEFAULTS, {"capacity": 1, "reserve": "on_assign", "when_busy": "wait", "release_undeclared": "ask"})

    def test_configured_and_partial(self):
        table, warnings = resources.attributes({"staging-db": {"capacity": 2, "when_busy": "ask"}, "gpu": {"reserve": "on_declare", "release_undeclared": "release"}})
        self.assertEqual(warnings, [])
        self.assertEqual(resources.attributes_of(table, "staging-db"), {"name": "staging-db", "capacity": 2, "reserve": "on_assign", "when_busy": "ask", "release_undeclared": "ask"})
        self.assertEqual(resources.attributes_of(table, "gpu")["reserve"], "on_declare")
        self.assertEqual(resources.attributes_of(table, "GPU")["reserve"], "on_declare", "名前は大文字小文字を区別しない")
        self.assertEqual(resources.attributes_of(table, "GPU")["name"], "gpu", "設定に書かれた表記を返す")

    def test_warns_unknown_and_bad_values(self):
        table, warnings = resources.attributes({"db": {"capacity": 0, "when_busy": "maybe", "color": "red", "reserve": 3}, "x": {"capacity": "2"}})
        keys = sorted(w["key"] for w in warnings)
        self.assertEqual(keys, ["resources.db.capacity", "resources.db.color", "resources.db.reserve", "resources.db.when_busy", "resources.x.capacity"])
        self.assertEqual(resources.attributes_of(table, "db"), {"name": "db", "capacity": 1, "reserve": "on_assign", "when_busy": "wait", "release_undeclared": "ask"})
        self.assertEqual(resources.attributes_of(table, "x")["capacity"], 1, "文字列の 2 は誤った値")
        self.assertTrue(all("デフォルト値" in w["message"] for w in warnings if not w["key"].endswith("color")))

    def test_duplicate_names_differing_in_case(self):
        table, warnings = resources.attributes({"DB": {"capacity": 2}, "db": {"capacity": 3}})
        self.assertEqual(resources.attributes_of(table, "db")["capacity"], 2, "表記だけ違う 2 つ目は使わない")
        self.assertEqual([w["key"] for w in warnings], ["resources.db"])


class HeldResourcesTest(unittest.TestCase):
    """持っている資源 (R20 の (1)) を宣言の配列から求める。"""

    def test_remove_only_update_releases(self):
        """{A, B} が開始可 → {A} (B を外すだけの更新) で B を解放し、持っている資源は {A}。"""
        history = [{"declaration": decl(["A", "B"]), "go": True}, {"declaration": decl(["A"]), "go": False}]
        self.assertEqual(resources.held_from_history(history), ["A"])

    def test_swap_update_waits_then_holds(self):
        """{A, B} が開始可 → {A, C} で、B はその時点で解放し、C が空くまで待機する間の持っている資源は {A}。C が空いて開始可を書くと {A, C}。"""
        go1 = decl(["A", "B"])
        update = decl(["A", "C"])
        self.assertEqual(resources.held_from_history([{"declaration": go1, "go": True}, {"declaration": update, "go": False}]), ["A"])
        self.assertEqual(resources.held_from_history([{"declaration": go1, "go": True}, {"declaration": update, "go": True}]), ["A", "C"])
        later = decl(["A"])
        self.assertEqual(resources.held_from_history([{"declaration": go1, "go": True}, {"declaration": update, "go": True}, {"declaration": later, "go": False}]), ["A"],
                         "その後の {A} では C だけを解放する")

    def test_rejected_and_none(self):
        self.assertEqual(resources.held_from_history([]), [])
        self.assertEqual(resources.held_from_history([{"declaration": decl(["A"]), "go": False}]), [], "開始可の宣言がまだ無ければ空")
        history = [{"declaration": decl(["A", "B"]), "go": True}, {"declaration": decl(["A"]), "go": False, "rejected": True}]
        self.assertEqual(resources.held_from_history(history), ["A", "B"], "差し戻された宣言の資源は持たず、比べる相手にもしない")

    def test_case_insensitive(self):
        history = [{"declaration": decl(["DB", "gpu"]), "go": True}, {"declaration": decl(["db"]), "go": False}]
        self.assertEqual(resources.held_from_history(history), ["DB"], "名前は大文字小文字を区別せず、開始可の宣言の表記で返す")


class AssignTest(unittest.TestCase):
    """契機「割り当て」。"""

    def test_default_attributes_skip_when_busy(self):
        """Covers AE26, AE50. 属性がデフォルト値のとき、資源を持つ項目が 1 つあれば、その資源を要する項目を候補から外す。"""
        r = resources.judge_assign(I2, ["db"], {"db": [I1]}, attrs(), {})
        self.assertEqual((r["result"], r["busy"], r["reserve"]), ("skip", ["db"], []))
        r = resources.judge_assign(I2, ["db", "gpu"], {}, attrs(), {})
        self.assertEqual((r["result"], r["reserve"]), ("assign", ["db", "gpu"]), "空いていれば割り当て、それらを予約する")

    def test_own_holding_does_not_count(self):
        r = resources.judge_assign(I1, ["db"], {"db": [I1]}, attrs(), {})
        self.assertEqual(r["result"], "assign", "自分が持っている分は数えない")
        r = resources.judge_assign(I1, ["db"], {"db": [I1.upper()]}, attrs(), {})
        self.assertEqual(r["result"], "assign", "項目のキーは owner/repo の大文字小文字を区別しない")

    def test_reserve_on_declare_is_not_reserved_at_assign(self):
        """Covers AE51. reserve が on_declare の資源は割り当てで予約せず、空きも待機しない。"""
        r = resources.judge_assign(I2, ["gpu"], {"gpu": [I1]}, attrs({"gpu": {"reserve": "on_declare"}}), {})
        self.assertEqual((r["result"], r["reserve"], r["busy"]), ("assign", [], []))

    def test_capacity(self):
        """capacity が 2 の資源は 2 つ目の項目まで待機させない。"""
        a = attrs({"db": {"capacity": 2}})
        self.assertEqual(resources.judge_assign(I2, ["db"], {"db": [I1]}, a, {})["result"], "assign")
        self.assertEqual(resources.judge_assign(I3, ["db"], {"db": [I1, I2]}, a, {})["result"], "skip")

    def test_when_busy_ask(self):
        """when_busy が ask なら利用者に質問し、回答が wait なら候補から外して、解放されるまで質問し直さない。"""
        a = attrs({"db": {"when_busy": "ask"}})
        r = resources.judge_assign(I2, ["db"], {"db": [I1]}, a, {})
        self.assertEqual((r["result"], r["ask"]), ("ask", ["db"]))
        r = resources.judge_assign(I2, ["db"], {"db": [I1]}, a, {"db": "wait"})
        self.assertEqual((r["result"], r["ask"]), ("skip", []))
        r = resources.judge_assign(I2, ["db"], {"db": [I1]}, a, {"db": "proceed"})
        self.assertEqual((r["result"], r["reserve"]), ("assign", ["db"]), "進めると回答したら割り当てて予約する")
        r = resources.judge_assign(I2, ["db"], {}, a, {"DB": "wait"})
        self.assertEqual(r["result"], "assign", "空いていれば回答に依らず割り当てる (回答は解放で消える前提)")

    def test_case_insensitive_names(self):
        r = resources.judge_assign(I2, ["DB"], {"db": [I1]}, attrs({"Db": {"when_busy": "ask"}}), {})
        self.assertEqual(r["result"], "ask", "ラベル・使用・設定の表記が違っても同じ資源")


class DeclareTest(unittest.TestCase):
    """契機「着手の宣言」。"""

    def test_free_resources_go_and_reserve(self):
        r = resources.judge_declare(I2, ["db", "gpu"], ["db"], {"db": [I2]}, attrs(), {}, {})
        self.assertEqual((r["result"], r["reserve"], r["wait_for"], r["ask"]), ("go", ["gpu"], [], []), "予約していないものだけ空きを確認して予約する")

    def test_busy_waits(self):
        """Covers AE26, AE50. 属性がデフォルト値のとき、資源を持つ項目が 1 つあれば着手の宣言では待機を返す。どれも予約しない。"""
        r = resources.judge_declare(I2, ["db", "gpu"], [], {"db": [I1]}, attrs(), {}, {})
        self.assertEqual((r["result"], r["wait_for"], r["reserve"]), ("wait", ["db"], []))

    def test_when_busy_ask(self):
        a = attrs({"db": {"when_busy": "ask"}})
        r = resources.judge_declare(I2, ["db"], [], {"db": [I1]}, a, {}, {})
        self.assertEqual((r["result"], r["ask"]), ("ask", ["db"]))
        r = resources.judge_declare(I2, ["db"], [], {"db": [I1]}, a, {"db": "wait"}, {})
        self.assertEqual((r["result"], r["wait_for"]), ("wait", ["db"]), "利用者が待機すると回答したら wait と同じ")
        r = resources.judge_declare(I2, ["db"], [], {"db": [I1]}, a, {"db": "proceed"}, {})
        self.assertEqual((r["result"], r["reserve"]), ("go", ["db"]))

    def test_undeclared_default_ask(self):
        """予約したのに宣言に無い資源には「利用者に質問する」を返す。回答待ちの間もほかの判定が済んでいれば開始可で、予約は残す。"""
        r = resources.judge_declare(I2, ["gpu"], ["db", "gpu"], {"db": [I2], "gpu": [I2]}, attrs(), {}, {})
        self.assertEqual((r["result"], r["ask_undeclared"], r["release"], r["keep"]), ("go", ["db"], [], ["db"]))
        r = resources.judge_declare(I2, ["gpu"], ["db", "gpu"], {"db": [I2], "gpu": [I2]}, attrs(), {}, {"db": "release"})
        self.assertEqual((r["result"], r["release"], r["keep"], r["request_rewrite"]), ("go", ["db"], [], []), "解放してよい")
        r = resources.judge_declare(I2, ["gpu"], ["db", "gpu"], {"db": [I2], "gpu": [I2]}, attrs(), {}, {"db": "keep"})
        self.assertEqual((r["result"], r["release"], r["keep"], r["request_rewrite"]), ("go", [], ["db"], ["db"]), "解放してはいけないなら予約を残して修正を頼む")

    def test_undeclared_release(self):
        """Covers AE51. release_undeclared が release なら宣言に無い予約を質問せずに解放する。"""
        r = resources.judge_declare(I2, ["gpu"], ["db", "gpu"], {"db": [I2], "gpu": [I2]}, attrs({"db": {"release_undeclared": "release"}}), {}, {})
        self.assertEqual((r["result"], r["release"], r["ask_undeclared"]), ("go", ["db"], []))

    def test_duplicate_names_reserved_once(self):
        """宣言に同じ資源が表記だけ違えて 2 度あっても (parse を通らない呼び出し)、1 つとして扱う。"""
        r = resources.judge_declare(I2, ["db", "DB"], [], {}, attrs(), {}, {})
        self.assertEqual((r["result"], r["reserve"]), ("go", ["db"]))

    def test_wait_does_not_hold_new_resources(self):
        """待機している宣言は新しく要る資源を持たない (どれも予約しない)。"""
        r = resources.judge_declare(I2, ["db", "gpu"], [], {"db": [I1]}, attrs(), {}, {})
        self.assertEqual(r["reserve"], [])

    def test_attribute_changes_only_affect_their_triggers(self):
        """属性を 1 つ変えたとき、結果が変わるのは、その属性を読む契機だけ。"""
        usage = {"db": [I1]}
        base = attrs()
        on_declare = attrs({"db": {"reserve": "on_declare"}})
        self.assertNotEqual(resources.judge_assign(I2, ["db"], usage, base, {})["result"], resources.judge_assign(I2, ["db"], usage, on_declare, {})["result"], "reserve は割り当てで読む")
        self.assertEqual(resources.judge_declare(I2, ["db"], [], usage, base, {}, {})["result"], resources.judge_declare(I2, ["db"], [], usage, on_declare, {}, {})["result"], "reserve は着手の宣言で読まない")
        release = attrs({"db": {"release_undeclared": "release"}})
        self.assertEqual(resources.judge_assign(I2, ["db"], usage, base, {}), resources.judge_assign(I2, ["db"], usage, release, {}), "release_undeclared は割り当てで読まない")


class UpdateTest(unittest.TestCase):
    """契機「宣言の更新」。外した資源を解放し、足した資源は着手の宣言と同じに空きを確認する。"""

    def test_removed_released_and_added_checked(self):
        r = resources.judge_update(I2, "resources-only", ["A", "B"], ["A", "C"], {"A": [I2], "B": [I2], "C": [I1]}, attrs(), {})
        self.assertEqual((r["result"], r["release"], r["wait_for"], r["reserve"]), ("wait", ["B"], ["C"], []))
        r = resources.judge_update(I2, "resources-only", ["A", "B"], ["A", "C"], {"A": [I2], "B": [I2]}, attrs(), {})
        self.assertEqual((r["result"], r["release"], r["reserve"]), ("go", ["B"], ["C"]))

    def test_remove_only_is_skipped(self):
        """資源を外すだけの更新は判定せず開始可を書かない (skip)。外した資源は解放する。"""
        r = resources.judge_update(I2, "resources-removed-only", ["A", "B"], ["A"], {"A": [I2], "B": [I2]}, attrs(), {})
        self.assertEqual((r["result"], r["release"], r["reserve"]), ("skip", ["B"], []))
        r = resources.judge_update(I2, "full", ["A", "B"], ["A"], {"A": [I2], "B": [I2]}, attrs(), {})
        self.assertEqual((r["result"], r["release"]), ("go", ["B"]), "ファイルも変わる更新は判定する (資源は妨げない)")
        with self.assertRaises(ValueError):
            resources.judge_update(I2, "unknown", ["A"], ["A"], {}, attrs(), {})

    def test_readd_checks_availability(self):
        """前に外した資源を足し直したときも、足したとして空きを確認する。"""
        r = resources.judge_update(I2, "resources-only", ["A"], ["A", "B"], {"A": [I2], "B": [I3]}, attrs(), {})
        self.assertEqual((r["result"], r["wait_for"]), ("wait", ["B"]))


class CloseAndReleaseTest(unittest.TestCase):

    def test_close_releases_all(self):
        """Issue の close・割り当ての解除: その項目が持つ資源をすべて解放する。"""
        r = resources.judge_close(I2, {"db": [I1, I2], "gpu": [I2], "x": [I3]})
        self.assertEqual(r, {"release": ["db", "gpu"]})
        self.assertEqual(resources.judge_close(I2, {"db": [I2.upper()]}), {"release": ["db"]}, "項目の表記が違っても解放する")

    def test_release_returns_waiting_in_post_order(self):
        """資源の解放: その資源で待機していた宣言を、投稿の順 (同じなら Project の中の順) に返す。"""
        waiting = [{"item": I3, "declaration": 30, "posted_at": "2026-10-23T01:00:00Z", "position": 1, "wait_for": ["db", "gpu"]},
                   {"item": I2, "declaration": 20, "posted_at": "2026-10-23T00:00:00Z", "position": 5, "wait_for": ["DB"]},
                   {"item": I1, "declaration": 10, "posted_at": "2026-10-23T00:00:00Z", "position": 2, "wait_for": ["gpu"]},
                   {"item": f"{REPO}#4", "declaration": 40, "posted_at": "2026-10-23T00:00:00Z", "position": 3, "wait_for": ["db"]}]
        r = resources.judge_release("db", waiting)
        self.assertEqual([w["declaration"] for w in r["rejudge"]], [40, 20, 30], "投稿の順、同じなら Project の中の順。表記は区別しない")


class CliTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        os.makedirs(os.path.dirname(os.path.join(self.root, config.CONFIG_PATH)), exist_ok=True)
        with open(os.path.join(self.root, config.CONFIG_PATH), "w", encoding="utf-8") as f:
            json.dump({"project": {"owner": "akm", "number": 3}, "resources": {"db": {"capacity": 2, "color": "red"}}}, f)

    def tearDown(self):
        self._tmp.cleanup()

    @staticmethod
    def cli(*args, stdin=None):
        r = subprocess.run([sys.executable, _CLI, *args], capture_output=True, text=True, input=stdin)
        return r.returncode, json.loads(r.stdout) if r.stdout.strip() else None, r.stderr

    def test_attributes(self):
        code, out, _ = self.cli("resources", "attributes", "--dir", self.root)
        self.assertEqual((code, out["status"], out["errors"]), (0, "ok", []))
        self.assertEqual(out["resources"], [{"name": "db", "capacity": 2, "reserve": "on_assign", "when_busy": "wait", "release_undeclared": "ask"}])
        self.assertEqual(out["defaults"], resources.DEFAULTS)
        self.assertEqual([w["key"] for w in out["warnings"]], ["resources.db.color"])
        code, out, _ = self.cli("resources", "attributes", "--dir", self.root, "--name", "GPU")
        self.assertEqual(out["resources"], [{"name": "GPU", "capacity": 1, "reserve": "on_assign", "when_busy": "wait", "release_undeclared": "ask"}], "設定に無い資源はデフォルト値")

    def test_judge(self):
        body = {"item": I2, "resources": ["db"], "usage": {"db": [I1]}, "answers": {}}
        code, out, _ = self.cli("resources", "judge", "--dir", self.root, "--trigger", "assign", "--body", json.dumps(body))
        self.assertEqual((code, out["status"], out["trigger"], out["result"], out["reserve"]), (0, "ok", "assign", "assign", ["db"]), "capacity 2 なので 2 つ目まで待機させない")
        body = {"item": I2, "declared": ["db", "gpu"], "reserved": ["db"], "usage": {"db": [I2], "gpu": [I1]}, "answers": {}, "undeclared_answers": {}}
        code, out, _ = self.cli("resources", "judge", "--dir", self.root, "--trigger", "declare", "--body", json.dumps(body))
        self.assertEqual((out["result"], out["wait_for"]), ("wait", ["gpu"]))
        body = {"item": I2, "kind": "resources-removed-only", "held": ["db"], "declared": [], "usage": {"db": [I2]}, "answers": {}}
        code, out, _ = self.cli("resources", "judge", "--dir", self.root, "--trigger", "update", "--body", json.dumps(body))
        self.assertEqual((out["result"], out["release"]), ("skip", ["db"]))
        body["kind"] = "nope"
        code, out, _ = self.cli("resources", "judge", "--dir", self.root, "--trigger", "update", "--body", json.dumps(body))
        self.assertEqual((out["status"], out["errors"][0]["key"]), ("error", "body.kind"))
        code, out, _ = self.cli("resources", "judge", "--dir", self.root, "--trigger", "close", "--body", json.dumps({"item": I2, "usage": {"db": [I2]}}))
        self.assertEqual(out["release"], ["db"])
        code, out, _ = self.cli("resources", "judge", "--dir", self.root, "--trigger", "release", "--body",
                                json.dumps({"resource": "db", "waiting": [{"item": I1, "declaration": 1, "posted_at": "t", "position": 1, "wait_for": ["db"]}]}))
        self.assertEqual([w["declaration"] for w in out["rejudge"]], [1])

    def test_judge_rejects_bad_body(self):
        code, out, _ = self.cli("resources", "judge", "--dir", self.root, "--trigger", "assign", "--body", json.dumps({"item": I2}))
        self.assertEqual((code, out["status"]), (0, "error"))
        self.assertEqual(out["errors"][0]["key"], "body")
        code, out, _ = self.cli("resources", "judge", "--dir", self.root, "--trigger", "assign", "--body", json.dumps({"item": I2, "resources": "db", "usage": {}}))
        self.assertEqual(out["status"], "error")
        # 入れ子の中身: usage の値が文字列・資源の名前が数値・回答が文字列でない・waiting の要素の形違い
        for trigger, body, key in (
                ("assign", {"item": I2, "resources": ["db"], "usage": {"db": I1}}, "body.usage.db"),
                ("assign", {"item": I2, "resources": [1], "usage": {}}, "body.resources"),
                ("declare", {"item": I2, "declared": ["db"], "reserved": [""], "usage": {}}, "body.reserved"),
                ("declare", {"item": I2, "declared": ["db"], "reserved": [], "usage": {}, "answers": {"db": 1}}, "body.answers"),
                ("close", {"item": I2, "usage": {"db": [1]}}, "body.usage.db"),
                ("release", {"resource": "db", "waiting": [{"item": I1, "wait_for": "db"}]}, "body.waiting[0]"),
                ("release", {"resource": "db", "waiting": [{"item": I1, "declaration": 1, "posted_at": "t", "position": "1", "wait_for": ["db"]},
                                                           {"item": I2, "declaration": 2, "posted_at": "t", "position": 2, "wait_for": ["db"]}]}, "body.waiting[0]"),
                ("release", {"resource": "db", "waiting": [{"item": I1, "declaration": 1, "posted_at": 5, "position": 1, "wait_for": ["db"]}]}, "body.waiting[0]")):
            with self.subTest(trigger=trigger, key=key):
                code, out, err = self.cli("resources", "judge", "--dir", self.root, "--trigger", trigger, "--body", json.dumps(body))
                self.assertEqual((code, out["status"]), (0, "error"), err)
                self.assertEqual(out["errors"][0]["key"], key)
                self.assertNotIn("Traceback", err)


class DocTest(unittest.TestCase):

    def test_doc_lists_attributes_and_results(self):
        with open(_DOC, encoding="utf-8") as f:
            doc = f.read()
        for name, default in resources.DEFAULTS.items():
            self.assertIn(f"`{name}`", doc)
            self.assertIn(f"`{default}`", doc)
        for value in ("on_assign", "on_declare", "wait", "ask", "release", "assign", "skip", "go", "resources-removed-only"):
            self.assertIn(f"`{value}`", doc, f"{value} が文書に無い")
        for trigger in resources.TRIGGERS:
            self.assertIn(f"`{trigger}`", doc, f"契機 {trigger} が文書に無い")


if __name__ == "__main__":
    unittest.main()
