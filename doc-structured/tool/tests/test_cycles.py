"""検査 c-2 (モジュール cycles) のテスト。

題材は、サンプルのプロジェクトの貸出のドメインの手書きの concept.md と design.md。サンプルでは、design.md の節
「貸出状態を 2 つの値に限る」(d-loans-design-h-status_values) が、concept.md の節「返却期限」を参照している。
"""

from doc_structured.cycles import check_cycles
from doc_structured.documents import load_documents
from doc_structured.domains import load_project
from tooltest import ProjectTestCase

CONCEPT = "docs/domains/02-loans/concept.md"
DESIGN = "docs/domains/02-loans/design.md"
R = "d-loans-concept-h-return_deadline"
O = "d-loans-concept-h-reservation_order"
S = "d-loans-design-h-status_values"

DEF_R = f'[節「返却期限」]: #{R} "ドメイン `loans` のファイル `concept.md` の節「返却期限」"\n'
DEF_O = f'[節「予約の順番」]: #{O} "ドメイン `loans` のファイル `concept.md` の節「予約の順番」"\n'
DEF_S = f'[節「貸出状態を 2 つの値に限る」]: design.md#{S} "ドメイン `loans` のファイル `design.md` の節「貸出状態を 2 つの値に限る」"\n'
DEF_DESIGN = '[`design.md`]: design.md#d-loans-design "ドメイン `loans` のファイル `design.md`"\n'
DEF_LOAN = '[モデル「貸出」]: models.md#d-loans-m-loan "ドメイン `loans` のモデル「貸出」"\n'


def concept(intro: str = "", deadline: str = "", order: str = "", definitions: str = "") -> str:
    """concept.md。行は 1: ファイルのアンカー・3: 見出し・5: 前置き・7: 節「返却期限」のアンカー・9: 見出し・
    11: 節「返却期限」の本文・13: 節「予約の順番」のアンカー・15: 見出し・17: 節「予約の順番」の本文。"""
    return (
        '<a name="d-loans-concept"></a>\n\n# 概念\n\n'
        f"前置き。{intro}\n\n"
        f'<a name="{R}"></a>\n\n## 返却期限\n\n'
        f"期限の文。{deadline}\n\n"
        f'<a name="{O}"></a>\n\n## 予約の順番\n\n'
        f"予約の文。{order}\n\n" + definitions
    )


class CyclesTest(ProjectTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.copy_sample()

    def problems(self, files: dict[str, str] | None = None) -> list[str]:
        for relative, text in (files or {}).items():
            self.write(relative, text)
        project, yaml_problems = load_project(self.project)
        self.assertEqual(yaml_problems, [])
        index, _ = load_documents(self.project, project)
        return [p.format() for p in check_cycles(index)]

    def test_sample_project_has_no_cycles(self):
        self.assertEqual(self.problems(), [])

    def test_cycle_between_two_sections_of_one_file(self):
        found = self.problems({CONCEPT: concept(deadline="[節「予約の順番」]", order="[節「返却期限」]", definitions=DEF_R + DEF_O)})
        self.assertEqual(found, [
            f"{CONCEPT}:17:6: 検査 c-2: 参照が循環している: {O} → {R} ({CONCEPT}:17:6)、{R} → {O} ({CONCEPT}:11:6)。"
            "循環のどれかのリンクを外すか、参照される内容を別の節に移す"
        ])

    def test_cycle_across_files(self):
        found = self.problems({CONCEPT: concept(deadline="[節「貸出状態を 2 つの値に限る」]", definitions=DEF_S)})
        self.assertEqual(found, [
            f"{CONCEPT}:11:6: 検査 c-2: 参照が循環している: {R} → {S} ({CONCEPT}:11:6)、{S} → {R} ({DESIGN}:9:63)。"
            "循環のどれかのリンクを外すか、参照される内容を別の節に移す"
        ])

    def test_cycle_through_file_id(self):
        # 前置きの文 (ファイルの ID に属する) が design.md の節を指し、その節がファイル concept.md を指す
        design = (self.project / DESIGN).read_text(encoding="utf-8").replace(
            "[節「返却期限」]と今日の日付", "[`concept.md`]と今日の日付"
        ).replace(
            f'[節「返却期限」]: concept.md#{R} "ドメイン `loans` のファイル `concept.md` の節「返却期限」"',
            '[`concept.md`]: concept.md#d-loans-concept "ドメイン `loans` のファイル `concept.md`"',
        )
        found = self.problems({CONCEPT: concept(intro="[節「貸出状態を 2 つの値に限る」]", definitions=DEF_S), DESIGN: design})
        self.assertEqual(len(found), 1, found)
        self.assertIn(f"参照が循環している: d-loans-concept → {S} ({CONCEPT}:5:5)、{S} → d-loans-concept", found[0])

    def test_one_problem_per_group_with_other_ids(self):
        # 返却期限 ↔ 予約の順番 と、返却期限 ↔ 貸出状態 (design.md) の 2 つの循環が、1 つのまとまりになる
        found = self.problems({
            CONCEPT: concept(
                deadline="[節「予約の順番」]、[節「貸出状態を 2 つの値に限る」]", order="[節「返却期限」]",
                definitions=DEF_R + DEF_O + DEF_S,
            )
        })
        self.assertEqual(len(found), 1, found)
        # 最も小さい ID (予約の順番) から始まる最も短い循環を書き、ほかの ID を並べる
        self.assertIn(f"参照が循環している: {O} → {R} ({CONCEPT}:17:6)、{R} → {O} ({CONCEPT}:11:6)。", found[0])
        self.assertIn(f"ほかに循環に関わる ID: {S}。", found[0])

    def test_two_groups_are_two_problems(self):
        child = "docs/domains/02-loans/design/overdue_notice.md"
        found = self.problems({
            CONCEPT: concept(deadline="[節「予約の順番」]", order="[節「返却期限」]", definitions=DEF_R + DEF_O),
            child: '<a name="d-loans-design-f-overdue_notice"></a>\n\n# 延滞の通知\n\n'
            '<a name="d-loans-design-f-overdue_notice-h-a"></a>\n\n## A\n\n[節「B」]\n\n'
            '<a name="d-loans-design-f-overdue_notice-h-b"></a>\n\n## B\n\n[節「A」]\n\n'
            '[節「A」]: #d-loans-design-f-overdue_notice-h-a "ドメイン `loans` のファイル `design/overdue_notice.md` の節「A」"\n'
            '[節「B」]: #d-loans-design-f-overdue_notice-h-b "ドメイン `loans` のファイル `design/overdue_notice.md` の節「B」"\n',
        })
        self.assertEqual(len(found), 2, found)
        self.assertIn(f"{O} → {R}", found[0])
        self.assertIn("d-loans-design-f-overdue_notice-h-a → d-loans-design-f-overdue_notice-h-b", found[1])

    def test_not_cycles(self):
        cases = {
            # 自分自身を指すリンク
            "自分自身": concept(deadline="[節「返却期限」]", definitions=DEF_R),
            # 節「返却期限」がファイル design.md を指し、design.md の節が節「返却期限」を指す (包含関係は矢印にしない)
            "ファイルと節の包含": concept(deadline="[`design.md`]", definitions=DEF_DESIGN),
            # 生成したファイルを指すリンクは数えない
            "生成したファイル": concept(intro="[モデル「貸出」]", deadline="[モデル「貸出」]", definitions=DEF_LOAN),
            # 参照先のアンカーが無いリンクは数えない (検査 b が報告する)
            "アンカーが無い": concept(
                deadline="[節「無い」]",
                definitions=f'[節「無い」]: design.md#d-loans-design-h-missing "ドメイン `loans` のファイル `design.md` の節「無い」"\n',
            ),
        }
        for name, text in cases.items():
            with self.subTest(name):
                self.assertEqual(self.problems({CONCEPT: text}), [])
