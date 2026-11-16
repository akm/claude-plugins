"""ドメインの YAML に書いた参照の一覧。検査 i (参照の向き) と、ドメインの依存 (モジュール dependencies) が使う。

参照は、属性の refers_to、完全な ID の配列で書く参照 (操作の targets・preconditions・events・roles と、前提の targets)、
ファイルに書く状態の遷移の attribute、遷移の operations・preconditions。状態の遷移の from・to・initial は値の英語名で、
参照ではないので含めない。
"""

from dataclasses import dataclass

from .domains import STATE_MACHINE_OWNER, Domain, Entry, Project, StateMachine, spaced


@dataclass(frozen=True)
class YamlReference:
    """YAML に書いた参照の 1 つ。"""

    domain: Domain  # 参照を書いたドメイン
    path: str  # 参照を書いた YAML の、リポジトリのルートからの相対パス
    prefix: str  # メッセージの先頭に書く、参照の名前 (「操作 lend の targets」)
    key: str  # 参照を書いたキー
    target: str  # 参照先の ID
    line: int
    column: int
    # 参照を書いた定義。状態の遷移の参照では、状態の遷移を持つ属性 (ファイルに書く形で、attribute の参照先が無ければ None)
    source: Entry | None
    in_state_machine: bool = False  # 状態の遷移の参照なら True


def entry_references(entry: Entry):
    """定義に書いた参照を、書いた順に返す。属性の refers_to を先にする。"""
    if entry.refers_to is not None:
        yield YamlReference(
            entry.domain, entry.path, "refers_to", "refers_to", entry.refers_to, entry.refers_to_line,
            entry.refers_to_column, entry,
        )
    for reference in entry.references:
        yield YamlReference(
            entry.domain, entry.path, f"{entry.owner} の {reference.key}", reference.key, reference.target,
            reference.line, reference.column, entry,
        )


def state_machine_references(machine: StateMachine, with_attribute: bool = True):
    """状態の遷移に書いた参照を、書いた順に返す。with_attribute が True なら、ファイルに書く形の attribute を先に返す。"""
    reference = machine.attribute_reference
    if with_attribute and reference is not None:
        yield YamlReference(
            machine.domain, machine.path, f"{STATE_MACHINE_OWNER}の attribute", "attribute", reference.target,
            reference.line, reference.column, machine.attribute, True,
        )
    for transition in machine.transitions:
        for reference in transition.references:
            yield YamlReference(
                machine.domain, machine.path, f"{spaced(machine.owner)}の {reference.key}", reference.key,
                reference.target, reference.line, reference.column, machine.attribute, True,
            )


def yaml_references(project: Project):
    """すべてのドメインの YAML の参照を返す。ドメインごとに、定義の参照を定義の並び順に返した後、状態の遷移の参照を読んだ順に返す。"""
    for domain in project.domains:
        for entry in domain.entries():
            yield from entry_references(entry)
        for machine in domain.state_machines:
            yield from state_machine_references(machine)
