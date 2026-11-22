"""テーブルとカラムの、テーブルをまたぐ確認 (検査 h) と、生成と検査が共有する判定。

テーブルとカラムの読み込みと、1 つのテーブルの中で決まる形の確認は、モジュール domains が行う。このモジュールは、
すべての定義と参照先を読んだ後に、次を確認する (決めた経緯は Issue #206 のコメントの 3・6・7・11)。
  - カラムの references の参照先が、そのテーブルの 1 カラムの主キーか、そのカラムだけの一意のインデックスを持つカラム
  - 実装済みのカラムの references が、未実装のカラム (未実装のテーブルのカラムを含む) を指さない
  - in_overview を、書かなくても全体の図に描かれるカラム (キーのカラム) に書かない
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


def check_tables(project: Project) -> list[Problem]:
    problems: list[Problem] = []

    def problem(entry: Entry, message: str, line: int, column: int) -> None:
        problems.append(Problem(CHECK, entry.path, message, line, column))

    for domain in project.domains:
        for table in domain.tables:
            for column in table.children:
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
    return problems
