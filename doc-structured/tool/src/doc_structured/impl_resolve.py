"""サブコマンド impl-diff-resolve: 検査 j の差分を 1 件ずつ、YAML を書き換えて解消する。

1 件は検査 j の項目 (テーブル・カラム・インデックス) の 1 つ。件の ID・フラグの意味・件の一覧の順序・書き換えの形は、
Issue #208 のコメントの 1〜10 で決めた。形式の SSOT はプラグインの規則の文書 (ファイル doc-structured/rules/doc-structured-impl.md)。

  フラグ          件の場合 (決定の一覧の検査 j の結果の表)と、YAML の書き換え
  --planned       YAML にあり実装に無い: planned: true を付ける
  --unplanned     YAML にあり実装にもあり planned がある: planned を外す
  --match-impl    YAML を実装に合わせる (planned を外して比べる項目を合わせる・YAML から消す・YAML に足す・比べる項目を書き換える)
マイグレーション (実装) は書き換えない。
"""

from dataclasses import dataclass, field
from pathlib import Path

from . import names
from .domains import Project, load_project
from .impl_diff import (
    MISMATCH,
    MISSING_DESIGN,
    MISSING_IMPLEMENTATION,
    PLANNED_IMPLEMENTED,
    Item,
    differences,
    messages,
)
from .schema_actual import ActualSchema
from .schema_diff import LABELS, SchemaTarget, compare
from .yaml_edit import Document, YamlEditError

PLANNED = "--planned"
UNPLANNED = "--unplanned"
MATCH_IMPL = "--match-impl"

# 件の場合ごとに使えるフラグ (Issue #208 のコメントの 2)
FLAGS = {
    PLANNED_IMPLEMENTED: (UNPLANNED, MATCH_IMPL),
    MISSING_IMPLEMENTATION: (PLANNED, MATCH_IMPL),
    MISSING_DESIGN: (MATCH_IMPL,),
    MISMATCH: (MATCH_IMPL,),
}


@dataclass
class Case:
    """解消する差分の 1 件。"""

    item: Item
    case: str  # impl_diff の件の場合
    messages: list[str]  # 指示の行のメッセージ

    @property
    def id(self) -> str:
        return self.item.id

    @property
    def target(self) -> SchemaTarget:
        return self.item.target

    @property
    def flags(self) -> tuple[str, ...]:
        return FLAGS[self.case]

    def line(self) -> str:
        """--list の 1 行。「<ID> | 使えるフラグ | 指示の行のメッセージ」。"""
        return f"{self.id} | {' '.join(self.flags)} | {' '.join(self.messages)}"


def _group(case: Case) -> int:
    """件の一覧の順序のまとまり。ほかの件より先に解消しないと検査 h が失敗する件を、一覧の先に並べる (Issue #208 のコメントの 10)。

    0: テーブルの有無 (足す・消す・planned)
    1: 主キーを YAML にあるカラムだけで書き換える件、YAML にあるインデックス (消す・planned・一意かどうか)
    2: カラム
    3: 主キーに YAML に無いカラムを加える件、実装にだけあるインデックス (足す)
    """
    target = case.target
    if target.kind == "table":
        if case.case != MISMATCH:
            return 0
        existing = {column.name for column in target.table_entry.children}
        return 1 if set(target.actual_table.primary_key) <= existing else 3
    if target.kind == "index":
        return 3 if case.case == MISSING_DESIGN else 1
    return 2


def list_cases(project: Project, actual: ActualSchema) -> list[Case]:
    """解消する差分の件を、依存を満たす順序で返す。"""
    result = compare(project, actual)
    cases = [Case(item, case, messages(item, case, LABELS)) for item, case in differences(result.items)]
    return sorted(cases, key=_group)


# ---------------------------------------------------------------- 件の指定


class ResolveError(Exception):
    """件を解消できない。lines は、利用者に見せる文 (1 行に 1 つ)。"""

    def __init__(self, *lines: str):
        super().__init__("\n".join(lines))
        self.lines = list(lines)


@dataclass
class Request:
    """サブコマンドに渡した、解消する件と、足すものの情報。"""

    id: str
    flag: str
    file: str | None = None  # 実装にだけあるテーブルを足す YAML (リポジトリのルートからの相対パス)
    definitions: list[tuple[str, str]] = field(default_factory=list)  # (ID, 定義の文)
    models: list[tuple[str, str]] = field(default_factory=list)  # (テーブルの ID, モデルの ID)
    attributes: list[tuple[str, str]] = field(default_factory=list)  # (テーブルかカラムの ID, 属性の ID)


LIST_HINT = "差分の件は bin/doc-structured impl-diff-resolve --list で見る"


def find_case(project: Project, cases: list[Case], given: str) -> tuple[Case, str]:
    """ID の件と、足すテーブルのドメイン (実装にだけあるテーブルのとき。ほかは空)。"""
    for case in cases:
        if case.id == given:
            return case, ""
    try:
        parts = names.parse_id(given)
    except names.IdError:
        parts = []
    if [p.symbol for p in parts] == ["d", "t"]:
        domain, table = parts[0].name, parts[1].name
        for case in cases:
            if case.target.kind == "table" and case.target.table_entry is None and case.target.table == table:
                if not any(d.name == domain for d in project.domains):
                    raise ResolveError(f"ID {given} のドメイン {domain} は無い (テーブルを足すドメインを ID に書く)")
                return case, domain
    raise ResolveError(f"ID {given} の差分の件は無い。{LIST_HINT}")


def check_flag(case: Case, flag: str) -> None:
    if flag not in case.flags:
        raise ResolveError(f"{case.id} に {flag} は使えない。この項目に使えるフラグは {'・'.join(case.flags)} ({case.messages[0]})")


# ---------------------------------------------------------------- 解消


GENERATE_HINT = "生成したファイルを YAML に合わせるには bin/doc-structured generate を実行する"


@dataclass
class Result:
    written: list[str] = field(default_factory=list)  # 書き換えた YAML (リポジトリのルートからの相対パス)
    created: list[str] = field(default_factory=list)  # 作った YAML
    notes: list[str] = field(default_factory=list)  # 書き換えた後に伝えること (YAML に書けなかったもの・消した ID を指すリンク)

    def lines(self) -> list[str]:
        return (
            [f"書き換えた: {path}" for path in self.written]
            + [f"作った: {path}" for path in self.created]
            + self.notes
            + [GENERATE_HINT]
        )


# YAML に足すキーの順序 (規則の文書の例にならう。Issue #208 のコメントの 3)
TABLE_KEY_ORDER = ("planned", "definition", "model", "attribute", "primary_key", "columns", "indexes")
COLUMN_KEY_ORDER = ("type", "nullable", "default", "references", "attribute", "planned", "in_overview", "definition")
INDEX_KEY_ORDER = ("columns", "unique", "planned")


class _Files:
    """書き換える YAML のファイル。書き換えた後の検査 h が失敗したら、元に戻す。"""

    def __init__(self, root: Path):
        self.root = root
        self.documents: dict[str, Document] = {}
        self.originals: dict[str, str | None] = {}  # 書き換える前の中身。作ったファイルは None

    def document(self, relative: str) -> Document:
        if relative not in self.documents:
            text = (self.root / relative).read_text(encoding="utf-8")
            self.originals[relative] = text
            self.documents[relative] = Document(text)
        return self.documents[relative]

    def create(self, relative: str, document: Document) -> None:
        self.originals[relative] = None
        self.documents[relative] = document

    def write(self) -> tuple[list[str], list[str]]:
        written, created = [], []
        for relative, document in self.documents.items():
            original = self.originals[relative]
            if original == document.text:
                continue
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(document.text, encoding="utf-8")
            (created if original is None else written).append(relative)
        return sorted(written), sorted(created)

    def restore(self) -> None:
        for relative, original in self.originals.items():
            path = self.root / relative
            if original is None:
                path.unlink(missing_ok=True)
            else:
                path.write_text(original, encoding="utf-8")


def _table_path(target: SchemaTarget) -> tuple:
    return ("tables", target.table)


def _column_path(target: SchemaTarget) -> tuple:
    return ("tables", target.table, "columns", target.column_entry.name)


def _index_path(document: Document, target: SchemaTarget) -> tuple:
    """YAML のインデックスの、配列の中の位置までの道筋。カラムの組と一意かどうかで探す (検査 h が、同じものを 2 つ書かないことを確認する)。"""
    indexes = document.node(("tables", target.table, "indexes"))
    spec = target.design_index
    for i, item in enumerate(indexes):
        if list(item.get("columns") or []) == list(spec.columns) and bool(item.get("unique")) == spec.unique:
            return ("tables", target.table, "indexes", i)
    raise ResolveError(f"{target.table} のインデックス ({', '.join(spec.columns)}) が YAML に見つからない (ツールの誤り)")


def _entry_path(document: Document, target: SchemaTarget) -> tuple:
    if target.kind == "table":
        return _table_path(target)
    if target.kind == "column":
        return _column_path(target)
    return _index_path(document, target)


def _key_order(target: SchemaTarget) -> tuple[str, ...]:
    return {"table": TABLE_KEY_ORDER, "column": COLUMN_KEY_ORDER, "index": INDEX_KEY_ORDER}[target.kind]


def _yaml_file(target: SchemaTarget) -> str:
    entry = target.column_entry if target.kind == "column" else target.table_entry
    return entry.path


def _set_planned(files: _Files, case: Case) -> None:
    """planned: true を付ける。テーブルに付けるときは、その下のカラムとインデックスの planned を外す
    (planned のテーブルの下に planned を重ねて書けないため。規則の文書の節「テーブルとカラム」)。"""
    target = case.target
    document = files.document(_yaml_file(target))
    path = _entry_path(document, target)
    document.set_key(path, "planned", True, _key_order(target))
    if target.kind != "table":
        return
    for name, column in list(document.node(("tables", target.table, "columns")).items()):
        if isinstance(column, dict) and "planned" in column:
            document.delete_key(("tables", target.table, "columns", name), "planned")
    indexes = document.node(path).get("indexes")
    for i, item in enumerate(indexes or []):
        if isinstance(item, dict) and "planned" in item:
            document.delete_key(("tables", target.table, "indexes", i), "planned")


def _unset_planned(files: _Files, case: Case) -> None:
    target = case.target
    document = files.document(_yaml_file(target))
    document.delete_key(_entry_path(document, target), "planned")


def resolve(root: Path, project: Project, actual: ActualSchema, request: Request) -> Result:
    """件を 1 つ解消する。解消できなければ、何も書き換えずに ResolveError を投げる。"""
    cases = list_cases(project, actual)
    case, domain = find_case(project, cases, request.id)
    check_flag(case, request.flag)
    files = _Files(root)
    try:
        if request.flag == PLANNED:
            _set_planned(files, case)
        elif request.flag == UNPLANNED:
            _unset_planned(files, case)
        else:
            raise NotImplementedError(case.case)
    except YamlEditError as e:
        raise ResolveError(f"{_yaml_file(case.target)}: {e}") from e
    written, created = files.write()
    _, problems = load_project(root)
    if problems:
        files.restore()
        raise ResolveError(
            *[problem.format() for problem in problems],
            f"書き換えた後の YAML に {len(problems)} 件の誤り (検査 h) があるので、元に戻した",
        )
    return Result(written, created)
