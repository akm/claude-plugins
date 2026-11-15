"""状態の遷移 (属性の値の間の遷移) のテスト。読み込みと検査 h (モジュール domains)・検査 i (モジュール direction)・
生成 (モジュール generate) の、失敗する例と成功する例を確認する。"""

import unittest

from doc_structured.direction import check_direction
from doc_structured.domains import load_project
from doc_structured.generate import render_project
from tooltest import ProjectTestCase

PATH = "docs/domains/01-loans/domain.yaml"

# 貸出状態に 3 つの値を持つドメイン。STATE_MACHINE の行を、属性 status の下に足す
DOMAIN = """\
domain:
  description: 図書の貸出と返却を扱う。
models:
  loan:
    name_ja: 貸出
    definition: 利用者が図書を借りてから返すまでの 1 回の記録。
    attributes:
      status:
        name_ja: 貸出状態
        definition: 貸出が今どの段階にあるか。
        values:
          on_loan:
            name_ja: 貸出中
            definition: 手元にある。
          overdue:
            name_ja: 延滞
            definition: 期限を過ぎた。
          returned:
            name_ja: 返却済み
            definition: 戻った。
"""
# DOMAIN の後に足した行の行番号は、この値に 1 を足したものから始まる
DOMAIN_LINES = 20

OPERATIONS = """\
operations:
  return_book:
    name_ja: 返却を受け付ける
    definition: 返された図書を受け取る。
  notify_overdue:
    name_ja: 延滞を通知する
    definition: 延滞を知らせる。
preconditions:
  past_due:
    name_ja: 返却期限を過ぎた
    definition: 今日が返却期限より後。
"""

STATE_MACHINE = """\
        state_machine:
          initial: on_loan
          transitions:
            - from: [on_loan]
              to: overdue
              operations: [d-loans-op-notify_overdue]
            - from: [on_loan, overdue]
              to: returned
              operations: [d-loans-op-return_book]
"""


class AttributeFormTest(ProjectTestCase):
    """属性の下に書く状態の遷移。"""

    def load(self, state_machine: str = STATE_MACHINE, extra: str = OPERATIONS):
        self.write(PATH, DOMAIN + state_machine + extra)
        return load_project(self.project)

    def problems(self, state_machine: str, extra: str = OPERATIONS) -> list[str]:
        _, problems = self.load(state_machine, extra)
        self.assertTrue(all(p.check == "h" for p in problems))
        return [p.format() for p in problems]

    def assert_problem(self, state_machine: str, expected: str, extra: str = OPERATIONS) -> None:
        found = self.problems(state_machine, extra)
        self.assertIn(expected, found)

    def test_valid_state_machine(self):
        project, problems = self.load()
        self.assertEqual([p.format() for p in problems], [])
        machine = project.state_machines["d-loans-m-loan-a-status"]
        self.assertEqual(machine.owner, "属性 status の状態の遷移")
        self.assertEqual(machine.initial.name, "on_loan")
        self.assertEqual(
            [([s.name for s in t.from_values], t.to.name, t.targets("operations")) for t in machine.transitions],
            [
                (["on_loan"], "overdue", ["d-loans-op-notify_overdue"]),
                (["on_loan", "overdue"], "returned", ["d-loans-op-return_book"]),
            ],
        )

    def test_optional_keys_can_be_omitted(self):
        # initial と operations は省ける。前の状態と後の状態が同じ遷移と、同じ組の遷移が 2 つあることは誤りにしない
        text = (
            "        state_machine:\n          transitions:\n"
            "            - from: [on_loan]\n              to: on_loan\n"
            "            - from: [on_loan]\n              to: returned\n"
            "            - from: [on_loan]\n              to: returned\n              operations: [d-loans-op-return_book]\n"
        )
        self.assertEqual(self.problems(text), [])

    def test_transition_to_missing_value_fails(self):
        # クローズ条件: 存在しない値への遷移で、検査 h が失敗する
        text = STATE_MACHINE.replace("to: returned", "to: lost")
        self.assertEqual(
            self.problems(text),
            [f"{PATH}:{DOMAIN_LINES + 8}:19: 検査 h: 属性 status の状態の遷移の to の値 lost は、属性 status の値に無い"],
        )

    def test_from_and_initial_must_be_values(self):
        text = STATE_MACHINE.replace("initial: on_loan", "initial: lent").replace("[on_loan, overdue]", "[on_loan, late]")
        self.assertEqual(
            self.problems(text),
            [
                f"{PATH}:{DOMAIN_LINES + 2}:20: 検査 h: 属性 status の状態の遷移の initial の値 lent は、属性 status の値に無い",
                f"{PATH}:{DOMAIN_LINES + 7}:31: 検査 h: 属性 status の状態の遷移の from の値 late は、属性 status の値に無い",
            ],
        )

    def test_shape_errors(self):
        line = DOMAIN_LINES + 1
        for text, expected in (
            ("        state_machine: []\n", f"{line}:24: 検査 h: state_machine の値は、キーと値のマッピングでなければならない"),
            ("        state_machine:\n          initial: on_loan\n", f"{line}:9: 検査 h: 属性 status の状態の遷移に必須の項目 transitions が無い"),
            ("        state_machine:\n          transitions: []\n", f"{line + 1}:24: 検査 h: 属性 status の状態の遷移の transitions は、空の配列にできない"),
            (
                "        state_machine:\n          transitions: {a: b}\n",
                f"{line + 1}:24: 検査 h: 属性 status の状態の遷移の transitions は、遷移のマッピングの配列でなければならない",
            ),
            (
                "        state_machine:\n          transitions:\n            - on_loan\n",
                f"{line + 2}:15: 検査 h: 属性 status の状態の遷移の transitions は、遷移のマッピングの配列でなければならない",
            ),
            (
                "        state_machine:\n          transitions:\n            - to: returned\n",
                f"{line + 2}:15: 検査 h: 属性 status の状態の遷移に必須の項目 from が無い",
            ),
            (
                "        state_machine:\n          transitions:\n            - from: [on_loan]\n",
                f"{line + 2}:15: 検査 h: 属性 status の状態の遷移に必須の項目 to が無い",
            ),
            (
                "        state_machine:\n          transitions:\n            - from: on_loan\n              to: returned\n",
                f"{line + 2}:21: 検査 h: 属性 status の状態の遷移の from は、値の英語名の配列でなければならない",
            ),
            (
                "        state_machine:\n          transitions:\n            - from: []\n              to: returned\n",
                f"{line + 2}:21: 検査 h: 属性 status の状態の遷移の from は、空の配列にできない",
            ),
            (
                "        state_machine:\n          transitions:\n            - from: [on_loan, on_loan]\n              to: returned\n",
                f"{line + 2}:31: 検査 h: 属性 status の状態の遷移の from に on_loan が 2 回ある",
            ),
            (
                "        state_machine:\n          transitions:\n            - from: [on_loan]\n              to: [returned]\n",
                f"{line + 3}:19: 検査 h: 属性 status の状態の遷移の to は、値の英語名の文字列でなければならない",
            ),
            (
                "        state_machine:\n          initial: [on_loan]\n          transitions:\n            - from: [on_loan]\n              to: returned\n",
                f"{line + 1}:20: 検査 h: 属性 status の状態の遷移の initial は、値の英語名の文字列でなければならない",
            ),
            (
                "        state_machine:\n          final: returned\n          transitions:\n            - from: [on_loan]\n              to: returned\n",
                f"{line + 1}:11: 検査 h: 知らないキー final (書けるキー: initial, transitions)",
            ),
            (
                "        state_machine:\n          transitions:\n            - from: [on_loan]\n              to: returned\n              events: [x]\n",
                f"{line + 4}:15: 検査 h: 知らないキー events (書けるキー: from, to, operations, preconditions)",
            ),
        ):
            with self.subTest(text=text):
                self.setUp()
                self.assert_problem(text, f"{PATH}:{expected}")

    def test_reference_errors(self):
        line = DOMAIN_LINES + 6
        for operations, expected in (
            ("[]", ":27: 検査 h: 属性 status の状態の遷移の operations は、空の配列にできない (参照が無いときは、operations を省く)"),
            ("d-loans-op-notify_overdue", ":27: 検査 h: 属性 status の状態の遷移の operations は、ID の文字列の配列でなければならない"),
            ("[notify_overdue]", ":28: 検査 h: 属性 status の状態の遷移の operations の値が ID の形でない"),
            (
                "[d-loans-pre-past_due]",
                ":28: 検査 h: 属性 status の状態の遷移の operations の参照先 d-loans-pre-past_due は操作でない (参照できるのは操作だけ)",
            ),
            ("[d-loans-op-renew]", ":28: 検査 h: 属性 status の状態の遷移の operations の参照先 d-loans-op-renew が無い"),
            (
                "[d-loans-op-notify_overdue, d-loans-op-notify_overdue]",
                ":55: 検査 h: 属性 status の状態の遷移の operations に d-loans-op-notify_overdue が 2 回ある",
            ),
        ):
            with self.subTest(operations=operations):
                self.setUp()
                text = STATE_MACHINE.replace("[d-loans-op-notify_overdue]", operations)
                found = self.problems(text)
                self.assertTrue(any(p.startswith(f"{PATH}:{line}{expected}") for p in found), found)

    def test_preconditions_cannot_be_written_under_attribute(self):
        text = STATE_MACHINE + "              preconditions: [d-loans-pre-past_due]\n"
        self.assertEqual(
            self.problems(text),
            [
                f"{PATH}:{DOMAIN_LINES + 10}:15: 検査 h: 属性 status の状態の遷移に preconditions があるので、"
                "状態の遷移を属性の下に書けない (state-machines- で始まる名前のファイルに移す)"
            ],
        )

    def test_attribute_with_more_than_three_values_fails(self):
        text = (
            "          lost:\n            name_ja: 紛失\n            definition: 無くした。\n" + STATE_MACHINE
        )
        self.assertEqual(
            self.problems(text),
            [
                f"{PATH}:{DOMAIN_LINES + 4}:9: 検査 h: 属性 status は値が 4 つあるので、"
                "状態の遷移を属性の下に書けない (state-machines- で始まる名前のファイルに移す)"
            ],
        )

    def test_attribute_without_values_fails(self):
        text = (
            "      due_date:\n        name_ja: 返却期限\n        definition: 返す日。\n"
            "        state_machine:\n          transitions:\n            - from: [a]\n              to: b\n"
        )
        self.assertEqual(
            self.problems(text),
            [f"{PATH}:{DOMAIN_LINES + 4}:9: 検査 h: 属性 due_date は値を持たないので、状態の遷移を書けない"],
        )

    def test_operations_of_other_domains_can_be_referred(self):
        self.write(
            "docs/domains/02-catalog/domain.yaml",
            "domain:\n  description: 図書。\noperations:\n  withdraw:\n    name_ja: 除籍する\n    definition: 除く。\n",
        )
        text = STATE_MACHINE.replace("[d-loans-op-return_book]", "[d-loans-op-return_book, d-catalog-op-withdraw]")
        self.assertEqual(self.problems(text), [])


class DirectionTest(ProjectTestCase):
    """検査 i: 状態の遷移の operations・preconditions が、祖先のディレクトリの YAML の定義を指さない。"""

    def test_reference_to_ancestor_directory_fails(self):
        self.write(PATH, "domain:\n  description: 貸出。\n" + OPERATIONS)
        sub = DOMAIN.split("models:\n", 1)[1]
        self.write("docs/domains/01-loans/sub/loan.yaml", "models:\n" + sub + STATE_MACHINE)
        project, problems = load_project(self.project)
        self.assertEqual([p.format() for p in problems], [])
        self.assertEqual(
            [p.format().split(" は、祖先")[0] for p in check_direction(project)],
            [
                "docs/domains/01-loans/sub/loan.yaml:24:28: 検査 i: 属性 status の状態の遷移の operations の参照先 d-loans-op-notify_overdue",
                "docs/domains/01-loans/sub/loan.yaml:27:28: 検査 i: 属性 status の状態の遷移の operations の参照先 d-loans-op-return_book",
            ],
        )

    def test_reference_to_descendant_directory_is_allowed(self):
        self.write(PATH, DOMAIN + STATE_MACHINE)
        self.write("docs/domains/01-loans/sub/operations.yaml", OPERATIONS)
        project, problems = load_project(self.project)
        self.assertEqual([p.format() for p in problems], [])
        self.assertEqual(check_direction(project), [])


class GenerateTest(ProjectTestCase):
    """models.md の、属性の節の表と図。"""

    def models_md(self, state_machine: str) -> str:
        self.write(PATH, DOMAIN + state_machine + OPERATIONS)
        project, problems = load_project(self.project)
        self.assertEqual([p.format() for p in problems], [])
        return render_project(project)["docs/domains/01-loans/models.md"]

    def test_table_and_diagram_between_attribute_and_values(self):
        text = self.models_md(STATE_MACHINE)
        expected = """\
貸出が今どの段階にあるか。

状態の遷移 (最初の状態: [値「貸出中」][d-loans-m-loan-a-status-v-on_loan]):

| 前の状態 | 後の状態 | 操作 | 前提 |
|---|---|---|---|
| [貸出中][d-loans-m-loan-a-status-v-on_loan] | [延滞][d-loans-m-loan-a-status-v-overdue] | [延滞を通知する][d-loans-op-notify_overdue] | |
| [貸出中][d-loans-m-loan-a-status-v-on_loan]・[延滞][d-loans-m-loan-a-status-v-overdue] | [返却済み][d-loans-m-loan-a-status-v-returned] | [返却を受け付ける][d-loans-op-return_book] | |

```mermaid
stateDiagram-v2
  state "貸出中" as v_on_loan
  state "延滞" as v_overdue
  state "返却済み" as v_returned
  [*] --> v_on_loan
  v_on_loan --> v_overdue : 延滞を通知する
  v_on_loan --> v_returned : 返却を受け付ける
  v_overdue --> v_returned : 返却を受け付ける
```

<a name="d-loans-m-loan-a-status-v-on_loan"></a>
"""
        self.assertIn(expected, text)
        self.assertIn('[d-loans-op-return_book]: functions.md#d-loans-op-return_book "ドメイン `loans` の操作「返却を受け付ける」"', text)
        self.assertIn(
            '[d-loans-m-loan-a-status-v-on_loan]: #d-loans-m-loan-a-status-v-on_loan '
            '"ドメイン `loans` のモデル「貸出」の属性「貸出状態」の値「貸出中」"',
            text,
        )

    def test_without_initial_and_operations(self):
        # 最初の状態が無ければ [*] を描かない。操作の無い遷移は、表のセルを空にし、矢印に文字を付けない。
        # 遷移に出てこない値 (延滞) も、状態として描く
        text = self.models_md("        state_machine:\n          transitions:\n            - from: [on_loan]\n              to: returned\n")
        self.assertIn("状態の遷移:\n\n| 前の状態 | 後の状態 | 操作 | 前提 |", text)
        self.assertIn(
            "| [貸出中][d-loans-m-loan-a-status-v-on_loan] | [返却済み][d-loans-m-loan-a-status-v-returned] | | |", text
        )
        self.assertIn('  state "延滞" as v_overdue\n', text)
        self.assertIn('  state "返却済み" as v_returned\n  v_on_loan --> v_returned\n```', text)
        self.assertNotIn("[*]", text)

    def test_attribute_without_state_machine_has_no_table(self):
        text = self.models_md("")
        self.assertNotIn("状態の遷移", text)
        self.assertNotIn("```mermaid", text)


if __name__ == "__main__":
    unittest.main()
