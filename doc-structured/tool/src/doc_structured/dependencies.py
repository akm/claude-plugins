"""ドメインの依存と読む順、検査 c-1 (YAML の依存に循環が無い)。

あるドメインの YAML の参照 (モジュール yaml_references) が、ほかのドメインの定義を指していれば、参照の種類を問わず、
そのドメインへの依存に数える (決定の一覧の問 5)。ロールはどのドメインにも属さないので、依存に数えない。
決めた経緯は Issue #202 のコメント。要点:
  - 読む順は、依存されるドメインを先にする。並べられるドメイン (依存先がすべて並んだドメイン) が複数あれば、番号の小さいものを
    先にする。循環に入っていて並べられないドメインが残ったら、その中で番号の最も小さいものを先に置き、同じ規則で続ける
  - 検査 c-1 は、ドメイン間の依存と、同じドメインのモデル間の参照 (属性の refers_to) に循環が無いことを確認する。
    モデルの自己参照は報告しない。報告は検査 c-2 と同じ形 (循環のまとまりごとに 1 件で、最も小さい ID から始まる
    最も短い循環を、矢印ごとにその矢印を作る最初の参照の位置と一緒に書く)
規則の SSOT はプラグインの規則の文書 (ファイル doc-structured/rules/doc-structured-domains.md)。
"""

from dataclasses import dataclass, field

from .domains import Domain, Project
from .graphs import shortest_cycle, strongly_connected
from .problems import Problem
from .yaml_references import YamlReference, entry_references, state_machine_references

CHECK = "c-1"


def domain_order_key(domain: Domain) -> tuple[int, str]:
    """ドメインの番号の順に並べるときのキー。"""
    return int(domain.number), domain.number


@dataclass
class DomainDependency:
    """あるドメインから、ほかの 1 つのドメインへの依存。"""

    target: Domain  # 依存先のドメイン
    references: list[YamlReference] = field(default_factory=list)  # 依存の元になった参照。定義の並び順


def references_in_definition_order(project: Project, domain: Domain):
    """ドメインの YAML の参照を、定義の並び順 (models.md・functions.md と同じ) に返す。状態の遷移の参照は、
    状態の遷移を持つ属性の参照の後に返す。ファイルに書く状態の遷移の attribute は、同じドメインの属性だけを指すので返さない。"""
    for entry in domain.entries():
        yield from entry_references(entry)
        machine = project.state_machines.get(entry.id)
        if machine is not None:
            yield from state_machine_references(machine, with_attribute=False)


def domain_dependencies(project: Project, domain: Domain) -> list[DomainDependency]:
    """ドメインの依存を、依存先のドメインの番号の順に返す。"""
    found: dict[str, DomainDependency] = {}
    for reference in references_in_definition_order(project, domain):
        target = project.entries.get(reference.target)
        if target is None or target.domain is None or target.domain is domain:
            continue
        found.setdefault(target.domain.name, DomainDependency(target.domain)).references.append(reference)
    return sorted(found.values(), key=lambda d: domain_order_key(d.target))


def all_dependencies(project: Project) -> dict[str, list[DomainDependency]]:
    """ドメインの名前から、そのドメインの依存への対応。"""
    return {domain.name: domain_dependencies(project, domain) for domain in project.domains}


def reading_order(project: Project, dependencies: dict[str, list[DomainDependency]] | None = None) -> list[Domain]:
    """ドメインの読む順。"""
    if dependencies is None:
        dependencies = all_dependencies(project)
    remaining = sorted(project.domains, key=domain_order_key)
    placed: set[str] = set()
    order: list[Domain] = []
    while remaining:
        ready = [d for d in remaining if all(dep.target.name in placed for dep in dependencies[d.name])]
        # 循環のため並べられるドメインが無ければ、残りの中で番号の最も小さいものを先に置く
        chosen = ready[0] if ready else remaining[0]
        remaining.remove(chosen)
        placed.add(chosen.name)
        order.append(chosen)
    return order


def _where(reference: YamlReference) -> str:
    return f"{reference.path}:{reference.line}:{reference.column}"


def _cycle_problems(graph: dict[str, dict[str, YamlReference]], kind: str, describe, fix: str) -> list[Problem]:
    """グラフの循環のまとまりごとに 1 件の問題。describe は矢印の参照から、矢印の後の括弧に書く文を作る。"""
    problems: list[Problem] = []
    for component in strongly_connected(graph):
        cycle = shortest_cycle(graph, component)
        arrows = [(a, b, graph[a][b]) for a, b in zip(cycle, cycle[1:])]
        steps = "、".join(f"{a} → {b} ({describe(reference)})" for a, b, reference in arrows)
        message = f"{kind}が循環している: {steps}。"
        others = [m for m in component if m not in cycle]
        if others:
            message += f"ほかに循環に関わる ID: {'・'.join(others)}。"
        message += fix
        first = arrows[0][2]
        problems.append(Problem(CHECK, first.path, message, first.line, first.column))
    return problems


def domain_graph(project: Project, dependencies: dict[str, list[DomainDependency]]) -> dict[str, dict[str, YamlReference]]:
    """ドメインの ID から、依存先のドメインの ID と、その依存の元になった最初の参照への対応。"""
    return {
        domain.id: {dep.target.id: dep.references[0] for dep in dependencies[domain.name]}
        for domain in project.domains
    }


def model_graph(domain: Domain) -> dict[str, dict[str, YamlReference]]:
    """同じドメインのモデルの ID から、属性の refers_to で参照するモデルの ID と、その最初の参照への対応。
    自分自身への参照 (自己参照) と、ほかのドメインのモデルへの参照は含めない。"""
    graph: dict[str, dict[str, YamlReference]] = {}
    for model in domain.models:
        for attribute in model.children:
            for reference in entry_references(attribute):
                if reference.key != "refers_to" or reference.target == model.id:
                    continue
                if not reference.target.startswith(f"{domain.id}-"):
                    continue
                graph.setdefault(model.id, {}).setdefault(reference.target, reference)
    return graph


def check_dependency_cycles(project: Project) -> list[Problem]:
    """検査 c-1。ドメインの循環を報告した後、ドメインの番号の順に、モデルの循環を報告する。"""
    dependencies = all_dependencies(project)
    problems = _cycle_problems(
        domain_graph(project, dependencies),
        "ドメインの依存",
        lambda reference: f"{_where(reference)} の {reference.target}",
        "循環のどれかの参照を外すか、参照される定義を別のドメインに移す",
    )
    for domain in sorted(project.domains, key=domain_order_key):
        problems += _cycle_problems(
            model_graph(domain),
            "モデルの参照",
            _where,
            "循環のどれかの refers_to を外す (refers_to は外部キーを持つモデルの属性にだけ書く)",
        )
    return problems
