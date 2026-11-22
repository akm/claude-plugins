"""テーブルとカラムの、テーブルをまたぐ確認 (検査 h) と、生成と検査が共有する判定。

テーブルとカラムの読み込みと、1 つのテーブルの中で決まる形の確認は、モジュール domains が行う。このモジュールは、
すべての定義と参照先を読んだ後に、次を確認する (決めた経緯は Issue #206 のコメントの 3〜7・11)。
  - カラムの references の参照先が、そのテーブルの 1 カラムの主キーか、そのカラムだけの一意のインデックスを持つカラム
  - 実装済みのカラムの references が、未実装のカラム (未実装のテーブルのカラムを含む) を指さない
  - テーブルの model・attribute とカラムの attribute (対応) は、同じドメインの定義を指す。カラムの attribute は、model を書いた
    テーブルのカラムにだけ書け、そのモデルの属性を指す
  - カラムに attribute と references があり、その属性に refers_to があれば、references が指すテーブルの model が refers_to と同じ
  - 対応を書いたテーブルとカラムには definition を書けず、対応を書かないものには definition が必須
  - あるモデルを model で指すテーブルがあれば、そのモデルのすべての属性が、カラムかテーブル (中間テーブル) の attribute から
    指されている (対応の書き忘れを、属性の側から見つける)
  - in_overview を、書かなくても全体の図に描かれるカラム (キーのカラムと、状態の遷移を持つ属性に対応するカラム) に書かない
形式の SSOT はプラグインの規則の文書 (ファイル doc-structured/rules/doc-structured-domains.md)。
"""

from .domains import ColumnSpec, Entry, IndexSpec, Project, TableSpec
from .problems import Problem

CHECK = "h"


def table_spec(table: Entry) -> TableSpec:
    assert isinstance(table.spec, TableSpec), table.id
    return table.spec


def column_spec(column: Entry) -> ColumnSpec:
    assert isinstance(column.spec, ColumnSpec), column.id
    return column.spec


def is_planned(entry: Entry) -> bool:
    """テーブルかカラムが未実装か。カラムは、カラムかテーブルに planned があれば未実装。"""
    if entry.symbol == "t":
        return table_spec(entry).planned
    return column_spec(entry).planned or table_spec(entry.parent).planned


def index_is_planned(table: Entry, index: IndexSpec) -> bool:
    return index.planned or table_spec(table).planned


def is_primary_key(column: Entry) -> bool:
    return column.name in table_spec(column.parent).primary_key


def is_foreign_key(column: Entry) -> bool:
    return column.reference("references") is not None


def has_single_unique(column: Entry) -> bool:
    """そのカラムだけの一意のインデックスを持つか。"""
    return any(index.unique and index.columns == [column.name] for index in table_spec(column.parent).indexes)


def is_unique_alone(column: Entry) -> bool:
    """そのカラムだけで行が 1 つに決まるか (1 カラムの主キーか、そのカラムだけの一意のインデックスを持つ)。"""
    return table_spec(column.parent).primary_key == [column.name] or has_single_unique(column)


def key_marks(column: Entry) -> list[str]:
    """ER 図のカラムに付けるキー (PK・FK・UK) の配列。"""
    marks = []
    if is_primary_key(column):
        marks.append("PK")
    if is_foreign_key(column):
        marks.append("FK")
    if has_single_unique(column):
        marks.append("UK")
    return marks


def target_of(project: Project, entry: Entry, key: str) -> Entry | None:
    """entry の key の参照 (1 つの完全な ID) の参照先。参照が無いか、参照先が無ければ None。"""
    reference = entry.reference(key)
    return project.entries.get(reference.target) if reference is not None else None


def table_model(project: Project, table: Entry) -> Entry | None:
    """テーブルの model が指すモデル。"""
    target = target_of(project, table, "model")
    return target if target is not None and target.symbol == "m" else None


def state_machine_column(project: Project, column: Entry) -> bool:
    """カラムが、状態の遷移を持つ属性に対応するか。"""
    reference = column.reference("attribute")
    return reference is not None and reference.target in project.state_machines


def check_tables(project: Project) -> list[Problem]:
    problems: list[Problem] = []

    def problem(entry: Entry, message: str, line: int, column: int) -> None:
        problems.append(Problem(CHECK, entry.path, message, line, column))

    for domain in project.domains:
        for table in domain.tables:
            _check_mapping(project, table, problem)
            for column in table.children:
                _check_mapping(project, column, problem)
                _check_column_attribute(project, table, column, problem)
                reference = column.reference("references")
                target = project.entries.get(reference.target) if reference is not None else None
                if target is not None and target.symbol == "c":
                    if not is_unique_alone(target):
                        problem(
                            column,
                            f"{column.owner} の references の参照先 {target.id} は、{target.parent.owner} の 1 カラムの主キーでも、"
                            "そのカラムだけの一意のインデックスを持つカラムでもない "
                            "(外部キーの参照先は、主キーか一意の制約を持つカラムにする)",
                            reference.line, reference.column,
                        )
                    if not is_planned(column) and is_planned(target):
                        problem(
                            column,
                            f"{column.owner} は実装済みなので、未実装のカラム {target.id} を references で参照できない "
                            "(このカラムにも planned を書くか、参照先の planned を外す)",
                            reference.line, reference.column,
                        )
                spec = column_spec(column)
                if spec.in_overview and key_marks(column):
                    problem(
                        column,
                        f"{column.owner} はキーのカラム ({', '.join(key_marks(column))}) で、全体の図にいつも描かれるので、"
                        "in_overview を書けない",
                        *spec.in_overview_at,
                    )
                elif spec.in_overview and state_machine_column(project, column):
                    problem(
                        column,
                        f"{column.owner} は状態の遷移を持つ属性 {column.reference('attribute').target} に対応し、"
                        "全体の図にいつも描かれるので、in_overview を書けない",
                        *spec.in_overview_at,
                    )
    _check_attributes_have_columns(project, problem)
    return problems


def _check_mapping(project: Project, entry: Entry, problem) -> None:
    """テーブルかカラムの対応 (model・attribute) が同じドメインの定義を指すことと、definition の有無を確認する。"""
    mapped = False
    for key in ("model", "attribute"):
        reference = entry.reference(key)
        if reference is None:
            continue
        mapped = True
        target = project.entries.get(reference.target)
        if target is not None and target.symbol in ("m", "a") and target.domain is not entry.domain:
            problem(
                entry,
                f"{entry.owner} の {key} の参照先 {target.id} は、ほかのドメインの定義 "
                "(テーブルとカラムは、対応するモデルと属性と同じドメインに書く)",
                reference.line, reference.column,
            )
    definition_at = entry.spec.definition_at
    if mapped and definition_at is not None:
        problem(
            entry,
            f"{entry.owner} には対応する{'モデルか属性' if entry.symbol == 't' else '属性'}を書いたので、definition を書けない "
            "(定義は、対応するモデルか属性にある)",
            *definition_at,
        )
    elif not mapped and definition_at is None:
        what = "対応するモデルか属性を書かないテーブル" if entry.symbol == "t" else "対応する属性を書かないカラム"
        problem(entry, f"{entry.owner} に definition が無い ({what}には、definition が必須)", entry.line, entry.column)


def _check_column_attribute(project: Project, table: Entry, column: Entry, problem) -> None:
    """カラムの attribute が、テーブルの model の属性であることと、外部キーと refers_to の整合を確認する。"""
    reference = column.reference("attribute")
    attribute = target_of(project, column, "attribute")
    if reference is None or attribute is None or attribute.symbol != "a":
        return
    model = table_model(project, table)
    if table.reference("model") is None:
        problem(
            column,
            f"{column.owner} の attribute は、model を書いたテーブルのカラムにだけ書ける "
            "(中間テーブルと、対応するモデルが無いテーブルのカラムには書けない)",
            reference.line, reference.column,
        )
        return
    if model is not None and attribute.parent is not model:
        problem(
            column,
            f"{column.owner} の attribute の参照先 {attribute.id} は、{table.owner} の model ({model.id}) の属性でない",
            reference.line, reference.column,
        )
        return
    foreign = target_of(project, column, "references")
    if attribute.refers_to is None or foreign is None or foreign.symbol != "c":
        return
    foreign_model = table_model(project, foreign.parent)
    if foreign_model is None or foreign_model.id != attribute.refers_to:
        written = foreign_model.id if foreign_model is not None else "無し"
        references = column.reference("references")
        problem(
            column,
            f"{column.owner} の references が指す{foreign.parent.owner} の model ({written}) が、attribute の参照先 "
            f"{attribute.id} の refers_to ({attribute.refers_to}) と違う",
            references.line, references.column,
        )


def _check_attributes_have_columns(project: Project, problem) -> None:
    """model で指されたモデルのすべての属性が、カラムかテーブルの attribute から指されていることを確認する。
    報告の位置は、そのモデルを model で指す最初のテーブルの model。"""
    first_table: dict[str, Entry] = {}
    covered: set[str] = set()
    for domain in project.domains:
        for entry in domain.table_entries():
            model = table_model(project, entry) if entry.symbol == "t" else None
            if model is not None:
                first_table.setdefault(model.id, entry)
            reference = entry.reference("attribute")
            if reference is not None:
                covered.add(reference.target)
    for model_id, table in first_table.items():
        model = project.entries[model_id]
        reference = table.reference("model")
        for attribute in model.children:
            if attribute.id not in covered:
                problem(
                    table,
                    f"{model.owner} の属性 {attribute.name} ({attribute.id}) に対応するカラムが無い ({table.owner} が model で"
                    "このモデルを指すので、属性ごとに、カラムの attribute か中間テーブルの attribute で対応を書く)",
                    reference.line, reference.column,
                )
