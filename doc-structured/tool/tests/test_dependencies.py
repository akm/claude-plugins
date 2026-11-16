"""ドメインの依存と読む順と、検査 c-1 (モジュール dependencies) のテスト。

題材は、サンプルのプロジェクト (図書館の貸出) と、テストの中で書く小さなドメインの YAML。サンプルでは、ドメイン `loans` (02) が
ドメイン `catalog` (01) と `members` (03) を参照し、循環は無い。
"""

import subprocess

from doc_structured.check import run_checks
from doc_structured.dependencies import all_dependencies, check_dependency_cycles, reading_order
from doc_structured.domains import load_project
from doc_structured.generate import render_project
from tooltest import PYTHON, ProjectTestCase, clean_env


def domain_yaml(description: str, body: str = "") -> str:
    return f"domain:\n  description: {description}\n{body}"


def model(name: str, name_ja: str, attributes: str = "") -> str:
    """モデル 1 つの YAML (キー models の下に書く形)。attributes はキー attributes の下に書く属性。"""
    text = f"  {name}:\n    name_ja: {name_ja}\n    definition: {name_ja}の記録。\n"
    if attributes:
        text += "    attributes:\n" + attributes
    return text


def refers_to(name: str, target: str) -> str:
    """属性 1 つの YAML。target を参照する。"""
    return f"      {name}:\n        name_ja: {name}\n        definition: 参照する属性。\n        refers_to: {target}\n"


class DependenciesTest(ProjectTestCase):
    def load(self):
        project, problems = load_project(self.project)
        self.assertEqual(problems, [])
        return project

    def order(self) -> list[str]:
        return [d.dir.rsplit("/", 1)[1] for d in reading_order(self.load())]

    def problems(self) -> list[str]:
        return [p.format() for p in check_dependency_cycles(self.load())]

    def test_sample_dependencies_list_references_in_definition_order(self):
        self.copy_sample()
        dependencies = all_dependencies(self.load())
        self.assertEqual(dependencies["catalog"], [])
        self.assertEqual(dependencies["members"], [])
        loans = dependencies["loans"]
        self.assertEqual([d.target.name for d in loans], ["catalog", "members"])
        self.assertEqual(
            [(r.source.id, r.key, r.target) for r in loans[0].references],
            [
                ("d-loans-m-loan-a-book", "refers_to", "d-catalog-m-book"),
                ("d-loans-m-reservation-a-book", "refers_to", "d-catalog-m-book"),
                ("d-loans-op-lend", "targets", "d-catalog-m-book-a-shelf_status"),
                ("d-loans-pre-book_shelved", "targets", "d-catalog-m-book-a-shelf_status-v-shelved"),
            ],
        )
        self.assertEqual([(r.source.id, r.target) for r in loans[1].references], [("d-loans-m-loan-a-member", "d-members-m-member")])

    def test_reading_order_puts_depended_domains_first(self):
        self.copy_sample()
        self.assertEqual(self.order(), ["01-catalog", "03-members", "02-loans"])

    def test_reading_order_uses_numbers_when_not_decided_by_dependencies(self):
        # 01-a は何にも依存せず、02-b が 01-a に依存し、03-c は何にも依存しない
        self.write("docs/domains/01-a/domain.yaml", domain_yaml("a。", "models:\n" + model("item", "品目")))
        self.write(
            "docs/domains/02-b/domain.yaml",
            domain_yaml("b。", "models:\n" + model("order", "注文", refers_to("item", "d-a-m-item"))),
        )
        self.write("docs/domains/03-c/domain.yaml", domain_yaml("c。"))
        self.assertEqual(self.order(), ["01-a", "02-b", "03-c"])

    def test_numbers_compare_as_integers(self):
        self.write("docs/domains/99-a/domain.yaml", domain_yaml("a。"))
        self.write("docs/domains/100-b/domain.yaml", domain_yaml("b。"))
        self.assertEqual(self.order(), ["99-a", "100-b"])

    def test_operation_only_reference_counts_as_dependency(self):
        self.copy_sample()
        # 利用者のドメインの操作が、蔵書のドメインの図書を対象にする (モデルの参照は無い)
        path = self.project / "docs/domains/03-members/domain.yaml"
        text = path.read_text(encoding="utf-8").replace(
            "      - d-members-m-member\n", "      - d-members-m-member\n      - d-catalog-m-book\n"
        )
        path.write_text(text, encoding="utf-8")
        dependencies = all_dependencies(self.load())
        self.assertEqual([d.target.name for d in dependencies["members"]], ["catalog"])
        self.assertEqual(
            [(r.source.id, r.key) for r in dependencies["members"][0].references], [("d-members-op-register", "targets")]
        )

    def test_state_machine_only_reference_counts_as_dependency(self):
        # 02-b の状態の遷移だけが、01-a の操作を参照する
        self.write(
            "docs/domains/01-a/domain.yaml",
            domain_yaml("a。", "operations:\n  ship:\n    name_ja: 出荷する\n    definition: 品物を送る。\n"),
        )
        self.write(
            "docs/domains/02-b/domain.yaml",
            domain_yaml(
                "b。",
                "models:\n"
                + model(
                    "order",
                    "注文",
                    "      status:\n        name_ja: 注文状態\n        definition: 注文の段階。\n        values:\n"
                    "          open:\n            name_ja: 受付\n            definition: 受け付けた。\n"
                    "          shipped:\n            name_ja: 出荷済み\n            definition: 送った。\n"
                    "        state_machine:\n          transitions:\n"
                    "            - from: [open]\n              to: shipped\n              operations: [d-a-op-ship]\n",
                ),
            ),
        )
        project = self.load()
        dependencies = all_dependencies(project)
        self.assertEqual([d.target.name for d in dependencies["b"]], ["a"])
        reference = dependencies["b"][0].references[0]
        self.assertEqual((reference.source.id, reference.key, reference.in_state_machine), ("d-b-m-order-a-status", "operations", True))
        self.assertEqual(self.order(), ["01-a", "02-b"])
        dependencies_md = render_project(project)["docs/domains/02-b/dependencies.md"]
        self.assertIn(
            "| [`a`][d-a] | [モデル「注文」の属性「注文状態」][d-b-m-order-a-status]の状態の遷移 | `operations` | "
            "[ドメイン `a` の操作「出荷する」][d-a-op-ship] |",
            dependencies_md,
        )

    def test_roles_do_not_count_as_dependency(self):
        self.copy_sample()
        project = self.load()
        self.assertEqual(all_dependencies(project)["members"], [])
        self.assertNotIn("docs/domains/03-members/dependencies.md", render_project(project))

    def test_sample_has_no_cycle(self):
        self.copy_sample()
        self.assertEqual(self.problems(), [])

    def cycle_between_loans_and_members(self) -> None:
        """サンプルの利用者のドメインに、貸出を参照する属性を足し、loans と members の間に循環を作る。"""
        self.copy_sample()
        path = self.project / "docs/domains/03-members/domain.yaml"
        text = path.read_text(encoding="utf-8").replace(
            "        definition: 利用者の名前。\n",
            "        definition: 利用者の名前。\n" + refers_to("current_loan", "d-loans-m-loan"),
        )
        path.write_text(text, encoding="utf-8")

    def test_domain_cycle_fails_with_ids_in_order(self):
        self.cycle_between_loans_and_members()
        self.assertEqual(
            self.problems(),
            [
                "docs/domains/02-loans/domain.yaml:16:20: 検査 c-1: ドメインの依存が循環している: "
                "d-loans → d-members (docs/domains/02-loans/domain.yaml:16:20 の d-members-m-member)、"
                "d-members → d-loans (docs/domains/03-members/domain.yaml:15:20 の d-loans-m-loan)。"
                "循環のどれかの参照を外すか、参照される定義を、それを参照するドメインか、新しいドメインに移す"
            ],
        )

    def test_cycle_of_three_lists_shortest_cycle_and_other_ids(self):
        # 01-a → 02-b → 01-a と、02-b → 03-c → 01-a の 2 つの循環が、1 つのまとまりになる
        self.write("docs/domains/01-a/domain.yaml", domain_yaml("a。", "models:\n" + model("x", "甲", refers_to("y", "d-b-m-y"))))
        self.write(
            "docs/domains/02-b/domain.yaml",
            domain_yaml("b。", "models:\n" + model("y", "乙", refers_to("c", "d-c-m-z") + refers_to("x", "d-a-m-x"))),
        )
        self.write("docs/domains/03-c/domain.yaml", domain_yaml("c。", "models:\n" + model("z", "丙", refers_to("x", "d-a-m-x"))))
        problems = self.problems()
        self.assertEqual(len(problems), 1)
        self.assertIn("ドメインの依存が循環している: d-a → d-b (docs/domains/01-a/domain.yaml:", problems[0])
        self.assertIn("d-b → d-a (docs/domains/02-b/domain.yaml:", problems[0])
        self.assertIn("ほかに循環に関わる ID: d-c。", problems[0])

    def test_cycle_still_generates_reading_order_by_numbers(self):
        self.cycle_between_loans_and_members()
        # loans と members は互いに依存するので、番号の小さい loans を先に並べる
        self.assertEqual(self.order(), ["01-catalog", "02-loans", "03-members"])
        self.install_bin()
        self.write_config()
        result = subprocess.run(
            [PYTHON, "-m", "doc_structured", "generate"], cwd=self.project, env=clean_env(), capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        result = run_checks(self.project, ("a", "c-1"))
        self.assertEqual([(p.check, p.path) for p in result.problems], [("c-1", "docs/domains/02-loans/domain.yaml")])


class ModelCyclesTest(ProjectTestCase):
    def problems(self) -> list[str]:
        project, problems = load_project(self.project)
        self.assertEqual(problems, [])
        return [p.format() for p in check_dependency_cycles(project)]

    def test_self_reference_does_not_fail(self):
        # サンプルの予約は、属性「前の予約」で自分のモデルを参照している
        self.copy_sample()
        project, _ = load_project(self.project)
        self.assertEqual(project.entries["d-loans-m-reservation-a-previous"].refers_to, "d-loans-m-reservation")
        self.assertEqual(self.problems(), [])

    def test_model_cycle_in_same_domain_fails_with_ids_in_order(self):
        # サンプルの貸出は予約を参照している。予約から貸出への参照を足して、循環を作る
        self.copy_sample()
        path = self.project / "docs/domains/02-loans/reservations/reservation.yaml"
        text = path.read_text(encoding="utf-8").replace(
            "        refers_to: d-loans-m-reservation\n",
            "        refers_to: d-loans-m-reservation\n" + refers_to("last_loan", "d-loans-m-loan"),
        )
        path.write_text(text, encoding="utf-8")
        self.assertEqual(
            self.problems(),
            [
                "docs/domains/02-loans/domain.yaml:20:20: 検査 c-1: モデルの参照が循環している: "
                "d-loans-m-loan → d-loans-m-reservation (docs/domains/02-loans/domain.yaml:20:20)、"
                "d-loans-m-reservation → d-loans-m-loan (docs/domains/02-loans/reservations/reservation.yaml:54:20)。"
                "循環のどれかの refers_to を外す (refers_to は外部キーを持つモデルの属性にだけ書く)"
            ],
        )

    def test_model_cycle_across_domains_is_reported_as_domain_cycle(self):
        # ドメインをまたぐモデルの循環は、ドメインの循環として 1 件だけ報告する
        self.write("docs/domains/01-a/domain.yaml", domain_yaml("a。", "models:\n" + model("x", "甲", refers_to("y", "d-b-m-y"))))
        self.write("docs/domains/02-b/domain.yaml", domain_yaml("b。", "models:\n" + model("y", "乙", refers_to("x", "d-a-m-x"))))
        problems = self.problems()
        self.assertEqual(len(problems), 1)
        self.assertIn("検査 c-1: ドメインの依存が循環している: d-a → d-b", problems[0])

    def test_model_cycle_of_three_in_same_domain(self):
        self.write(
            "docs/domains/01-a/domain.yaml",
            domain_yaml(
                "a。",
                "models:\n"
                + model("x", "甲", refers_to("y", "d-a-m-y"))
                + model("y", "乙", refers_to("z", "d-a-m-z"))
                + model("z", "丙", refers_to("x", "d-a-m-x")),
            ),
        )
        problems = self.problems()
        self.assertEqual(len(problems), 1)
        self.assertIn("モデルの参照が循環している: d-a-m-x → d-a-m-y (", problems[0])
        self.assertIn("d-a-m-y → d-a-m-z (", problems[0])
        self.assertIn("d-a-m-z → d-a-m-x (", problems[0])
