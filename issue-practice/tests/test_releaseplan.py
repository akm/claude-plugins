#!/usr/bin/env python3
"""リリース計画 Issue の順番の表の読み取りと、「今」と「次」の判定のテスト (計画の R36・U2)。

偽の gh (ファイル `issue-practice/tests/fake-gh`) で、リリース計画 Issue・リリース Issue・マイルストーン・記録のコメントを返す。
"""

import os
import unittest

from fakegh_case import HERE, FakeGhCase, fixture_json

from issue_practice import releaseplan  # noqa: E402

REPO = "o/r"
LOGIN = "akm"


def table(*rows, header="| 順 | リリース Issue | 主題 |"):
    lines = ["## リリースの順番", "", header, "| --- | --- | --- |"]
    lines += [f"| {order} | {ref} | {subject} |" for order, ref, subject in rows]
    return "\n".join(lines) + "\n"


def issue_url(number):
    return f"https://github.com/{REPO}/issues/{number}"


def milestone_url(number):
    return f"https://github.com/{REPO}/milestone/{number}"


class ParseTableTest(unittest.TestCase):

    def test_reads_rows(self):
        body = "# 計画\n\n" + table((1, "#12", "バックアップ一式"), (2, "#15", "一覧の絞り込み")) + "\n## メモ\n\n| a |\n"
        parsed = releaseplan.parse_table(body)
        self.assertEqual([(r["order"], r["number"], r["subject"]) for r in parsed["rows"]],
                         [(1, 12, "バックアップ一式"), (2, 15, "一覧の絞り込み")])
        self.assertEqual(parsed["rows"][0]["line"], 7, "行番号は本文の 1 行目を 1 として数える")

    def test_errors(self):
        cases = {
            "見出しの行が違う": table((1, "#12", "a"), header="| 順 | Issue | 主題 |"),
            "連番でない": table((1, "#12", "a"), (3, "#15", "b")),
            "参照の形が違う": table((1, "https://github.com/o/r/issues/12", "a")),
            "同じリリース Issue が 2 回": table((1, "#12", "a"), (2, "#12", "b")),
            "主題が空": table((1, "#12", "")),
            "行が無い": table(),
            "節が無い": "## 別の節\n\n| 順 | リリース Issue | 主題 |\n| --- | --- | --- |\n| 1 | #12 | a |\n",
            "表が 2 つ": table((1, "#12", "a")) + "\n| x | y |\n",
        }
        for name, body in cases.items():
            with self.subTest(name):
                self.assertIn("errors", releaseplan.parse_table(body))

    def test_table_in_code_block_is_ignored(self):
        body = "## リリースの順番\n\n```markdown\n| 順 | リリース Issue | 主題 |\n| --- | --- | --- |\n| 1 | #12 | a |\n```\n"
        self.assertIn("errors", releaseplan.parse_table(body), "コードブロックの中の表は数えない")


class DecideTest(unittest.TestCase):

    def decide(self, states):
        """states は (番号, 状態, 題名) の配列。表の順にする。"""
        rows = [{"order": i, "number": n, "subject": "s", "line": i} for i, (n, _, _) in enumerate(states, start=1)]
        issues = {n: {"number": n, "url": issue_url(n), "state": s, "title": t, "body": ""} for n, s, t in states}
        result = releaseplan.decide(rows, lambda n: (issues[n], None))
        return (result["current"] and result["current"]["number"], result["next"] and result["next"]["number"])

    def test_current_is_first_open_without_draft_and_next_is_below(self):
        self.assertEqual(self.decide([(10, "CLOSED", "🔖 リリース R10 (a)"), (11, "OPEN", "🔖 リリース R11 (b)"),
                                      (12, "OPEN", "[DRAFT] 🔖 リリース R12 (c)"), (13, "OPEN", "[DRAFT] 🔖 リリース R13 (d)")]),
                         (11, 12))

    def test_no_next_when_current_is_last(self):
        self.assertEqual(self.decide([(10, "CLOSED", "a"), (11, "OPEN", "b")]), (11, None))

    def test_first_closed_and_second_draft(self):
        self.assertEqual(self.decide([(10, "CLOSED", "a"), (11, "OPEN", "[DRAFT] b"), (12, "OPEN", "[DRAFT] c")]),
                         (None, 11), "「今」が無いときは、閉じていない最初のリリース Issue が「次」")

    def test_next_skips_closed_rows(self):
        self.assertEqual(self.decide([(10, "OPEN", "a"), (11, "CLOSED", "b"), (12, "OPEN", "[DRAFT] c")]), (10, 12))

    def test_all_closed(self):
        self.assertEqual(self.decide([(10, "CLOSED", "a")]), (None, None))

    def test_pull_request_is_error(self):
        rows = [{"order": 1, "number": 5, "subject": "s", "line": 3}]
        result = releaseplan.decide(rows, lambda n: ({"number": 5, "url": f"https://github.com/{REPO}/pull/5",
                                                      "state": "OPEN", "title": "x", "body": ""}, None))
        self.assertTrue(result["errors"])


class ChoosePlanTest(unittest.TestCase):

    def test_counts(self):
        self.assertEqual(releaseplan.choose_plan([]), {"plan": None, "swapping": False})
        old = {"number": 3, "created_at": "2026-11-01T00:00:00Z"}
        new = {"number": 9, "created_at": "2026-11-10T00:00:00Z"}
        self.assertEqual(releaseplan.choose_plan([new, old]), {"plan": new, "swapping": True},
                         "2 つなら後に作られたほうを読む")
        self.assertIn("error", releaseplan.choose_plan([old, new, {"number": 10, "created_at": "2026-11-11T00:00:00Z"}]))


class ReleaseCurrentCliTest(FakeGhCase):
    """サブコマンド `release current` を、偽の gh で実行する。"""

    def setup_repo(self, plans, issues, milestones, comments=None, labels=("bug",)):
        """plans は (番号, 作った日時, 本文) の配列、issues は (番号, 状態, 題名, 本文) の配列、
        milestones は (番号, 名前, 説明) の配列、comments はリリース Issue の番号から (1 行目の配列) への辞書。"""
        entries = [
            {"prefix": ["label", "list"], "stdout": [{"name": n} for n in labels]},
            {"prefix": ["issue", "list"], "stdout": [
                {"number": n, "url": issue_url(n), "title": f"リリース計画 {created[:10].replace('-', '')}", "body": body,
                 "createdAt": created} for n, created, body in plans]},
            {"prefix": ["api", "user"], "stdout": {"login": LOGIN}},
            {"prefix": ["api", f"repos/{REPO}/milestones?state=open&per_page=100"], "stdout": [[
                {"number": n, "title": title, "description": description, "html_url": milestone_url(n), "state": "open"}
                for n, title, description in milestones]]},
        ]
        for number, state, title, body in issues:
            entries.append({"prefix": ["issue", "view", str(number)],
                            "stdout": {"number": number, "url": issue_url(number), "state": state, "title": title,
                                       "body": body}})
        for number, lines in (comments or {}).items():
            entries.append({"prefix": ["api", f"repos/{REPO}/issues/{number}/comments"], "stdout": [[
                {"id": i, "html_url": f"{issue_url(number)}#issuecomment-{i}", "created_at": "2026-11-14T00:00:00Z",
                 "updated_at": "2026-11-14T00:00:00Z", "body": f"{line}\n\n本文", "user": {"login": LOGIN}}
                for i, line in enumerate(lines, start=1)]]})
        self.responses(entries)

    def standard(self, current_comments=("issue-practice: draft-removed date=2026-11-10",)):
        self.setup_repo(
            plans=[(20, "2026-11-10T00:00:00Z", table((1, "#10", "初回"), (2, "#11", "二回目"), (3, "#12", "三回目")))],
            issues=[(10, "CLOSED", "🔖 リリース R10 (初回)", ""),
                    (11, "OPEN", "🔖 リリース R11 (二回目)", f"マイルストーン: {milestone_url(2)}"),
                    (12, "OPEN", "[DRAFT] 🔖 リリース R12 (三回目)", f"マイルストーン: {milestone_url(3)}")],
            milestones=[(2, "R11 (二回目)", issue_url(11)), (3, "R12 (三回目)", issue_url(12))],
            comments={11: list(current_comments)})

    def test_current_and_next(self):
        self.standard()
        code, out, err = self.cli("release", "current", "--repo", REPO)
        self.assertEqual(code, 0, err)
        self.assertEqual(out["plan"]["number"], 20)
        self.assertEqual((out["current"]["number"], out["current"]["milestone"]["title"], out["current"]["selectable"]),
                         (11, "R11 (二回目)", True))
        self.assertEqual((out["next"]["number"], out["next"]["draft"]), (12, True))
        self.assertFalse(out["swapping"])

    def test_running_current_is_not_selectable_for_carve_out(self):
        self.standard(current_comments=("issue-practice: draft-removed date=2026-11-10", "issue-practice: release-start"))
        code, out, err = self.cli("release", "current", "--repo", REPO, "--carve-out")
        self.assertEqual(code, 0, err)
        self.assertTrue(out["current"]["running"])
        self.assertFalse(out["current"]["selectable"])
        self.assertTrue(out["current"]["reason"])
        self.assertTrue(out["next"]["selectable"])
        code, out, err = self.cli("release", "current", "--repo", REPO)
        self.assertTrue(out["current"]["selectable"], "--carve-out を付けなければ、実行中でも選べる")

    def test_current_without_draft_removed_is_error(self):
        self.standard(current_comments=())
        code, out, _ = self.cli("release", "current", "--repo", REPO)
        self.assertEqual(code, 3)
        self.assertIsNone(out["current"])
        self.assertTrue(any("draft-removed" in e for e in out["errors"]))

    def test_no_plan(self):
        self.setup_repo(plans=[], issues=[], milestones=[])
        code, out, err = self.cli("release", "current", "--repo", REPO)
        self.assertEqual(code, 0, err)
        self.assertEqual((out["plan"], out["current"], out["next"]), (None, None, None))

    def test_swapping_reads_newer_plan(self):
        self.setup_repo(
            plans=[(20, "2026-11-01T00:00:00Z", table((1, "#10", "古い計画"))),
                   (21, "2026-11-12T00:00:00Z", table((1, "#12", "新しい計画")))],
            issues=[(10, "OPEN", "🔖 リリース R10 (古い計画)", ""),
                    (12, "OPEN", "[DRAFT] 🔖 リリース R12 (新しい計画)", milestone_url(3))],
            milestones=[(3, "R12 (新しい計画)", issue_url(12))])
        code, out, err = self.cli("release", "current", "--repo", REPO)
        self.assertEqual(code, 0, err)
        self.assertTrue(out["swapping"])
        self.assertEqual(out["plan"]["number"], 21)
        self.assertEqual((out["current"], out["next"]["number"]), (None, 12))

    def test_three_current_plans_is_error(self):
        body = table((1, "#10", "a"))
        self.setup_repo(plans=[(20, "2026-11-01T00:00:00Z", body), (21, "2026-11-02T00:00:00Z", body),
                               (22, "2026-11-03T00:00:00Z", body)], issues=[], milestones=[])
        code, out, _ = self.cli("release", "current", "--repo", REPO)
        self.assertEqual(code, 3)
        self.assertIn("3 つ", out["errors"][0])

    def test_milestone_without_issue_url_is_error(self):
        self.setup_repo(
            plans=[(20, "2026-11-10T00:00:00Z", table((1, "#12", "a")))],
            issues=[(12, "OPEN", "[DRAFT] 🔖 リリース R12 (a)", milestone_url(3))],
            milestones=[(3, "R12 (a)", "説明に URL が無い")])
        code, out, _ = self.cli("release", "current", "--repo", REPO)
        self.assertEqual(code, 3)
        self.assertTrue(any("説明に" in e for e in out["errors"]))

    def test_missing_milestone_is_error(self):
        self.setup_repo(plans=[(20, "2026-11-10T00:00:00Z", table((1, "#12", "a")))],
                        issues=[(12, "OPEN", "[DRAFT] 🔖 リリース R12 (a)", "")], milestones=[(3, "R99 (別)", "")])
        code, out, _ = self.cli("release", "current", "--repo", REPO)
        self.assertEqual(code, 3)

    def test_release_targets(self):
        self.setup_repo(plans=[], issues=[], milestones=[], labels=("release-target:api", "release-target:web"))
        code, out, _ = self.cli("release", "current", "--repo", REPO)
        self.assertEqual(code, 3, "リリース対象が複数あるのに指定が無ければ、満たさない")
        self.assertEqual(out["targets"], ["api", "web"])
        code, out, err = self.cli("release", "current", "--repo", REPO, "--target", "api")
        self.assertEqual(code, 0, err)
        listed = [a for a in self.recorded() if a[:2] == ["issue", "list"]][-1]
        self.assertIn("release-target:api", listed, "リリース対象のラベルで計画を絞る")
        code, out, _ = self.cli("release", "current", "--repo", REPO, "--target", "mobile")
        self.assertEqual(code, 3)

    def test_milestone_with_target(self):
        self.setup_repo(
            plans=[(20, "2026-11-10T00:00:00Z", table((1, "#12", "a")))],
            issues=[(12, "OPEN", "[DRAFT] 🔖 リリース R12 api (a)", milestone_url(3))],
            milestones=[(4, "R12 (a)", issue_url(12)), (3, "R12 api (a)", issue_url(12))],
            labels=("release-target:api", "release-target:web"))
        code, out, err = self.cli("release", "current", "--repo", REPO, "--target", "api")
        self.assertEqual(code, 0, err)
        self.assertEqual(out["next"]["milestone"]["number"], 3, "リリース対象の名前を含むマイルストーンを選ぶ")

    def test_gh_failure(self):
        os.environ["FAKE_GH_MODE"] = "network"
        code, out, _ = self.cli("release", "current", "--repo", REPO)
        self.assertEqual(code, 4)
        self.assertEqual(out["gh_error"]["failure"], "network")

    def test_bad_repo(self):
        code, out, _ = self.cli("release", "current", "--repo", "not-a-repo")
        self.assertEqual(code, 3)
        self.assertEqual(self.recorded(), [], "リポジトリの形が違えば gh を実行しない")


class SandboxFixtureTest(unittest.TestCase):
    """確認用のリポジトリで取った固定データの形が、モジュールが読む形と合うこと。"""

    def test_milestone_list_shape(self):
        pages = fixture_json("sandbox-milestones-list")
        milestone = pages[0][0]
        self.assertEqual(releaseplan.find_milestone([milestone], 5, None)["milestone"]["html_url"],
                         "https://github.com/akm/issue-practice-sandbox/milestone/1")


    def test_plan_list_shape(self):
        plans = fixture_json("sandbox-issue-list-current")
        self.assertEqual([p["number"] for p in plans], [8])
        self.assertTrue(plans[0]["createdAt"])
        rows = releaseplan.parse_table(plans[0]["body"])["rows"]
        self.assertEqual([(r["order"], r["number"]) for r in rows], [(1, 6), (2, 7)])


class DocTest(unittest.TestCase):
    """文書 `issue-practice/references/release-plan-table.md` の書式と、モジュールの定数が一致すること。"""

    def test_header_and_section(self):
        with open(os.path.join(HERE, "..", "references", "release-plan-table.md"), encoding="utf-8") as f:
            doc = f.read()
        self.assertIn(f"`| {' | '.join(releaseplan.HEADER)} |`", doc)
        self.assertIn(f"`## {releaseplan.SECTION_TITLE}`", doc)
        self.assertIn(f"`{releaseplan.DRAFT_MARK}`", doc)
        self.assertIn(f"`{releaseplan.TARGET_LABEL_PREFIX}<名前>`", doc)


if __name__ == "__main__":
    unittest.main()
