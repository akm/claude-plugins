"""サブコマンド impl-diff-resolve: 検査 j の差分を 1 件ずつ、YAML を書き換えて解消する。

1 件は検査 j の項目 (テーブル・カラム・インデックス) の 1 つ。件の ID・フラグの意味・件の一覧の順序・書き換えの形は、
Issue #208 のコメントの 1〜10 で決めた。形式の SSOT はプラグインの規則の文書 (ファイル doc-structured/rules/doc-structured-impl.md)。

  フラグ          件の場合 (決定の一覧の検査 j の結果の表)と、YAML の書き換え
  --planned       YAML にあり実装に無い: planned: true を付ける
  --unplanned     YAML にあり実装にもあり planned がある: planned を外す
  --match-impl    YAML を実装に合わせる (planned を外して比べる項目を合わせる・YAML から消す・YAML に足す・比べる項目を書き換える)
マイグレーション (実装) は書き換えない。
"""

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from . import names
from .documents import load_documents
from .domains import SCHEMA_FILE_PREFIX, Project, load_project
from .impl_diff import (
    MISMATCH,
    MISSING_DESIGN,
    MISSING_IMPLEMENTATION,
    PLANNED_IMPLEMENTED,
    Item,
    different_keys,
    differences,
    messages,
)
from .refs import DEFINITION_ONLY, find_refs
from .schema_actual import ActualColumn, ActualIndex, ActualSchema, ActualTable
from .schema_diff import (
    DOMAIN_PLACEHOLDER,
    LABELS,
    PRIMARY_KEY_NULL_FIX,
    SchemaTarget,
    compare,
    index_id,
    normalize_default,
    normalize_type,
)
from .tables import table_spec
from .yaml_edit import Document, Double, Flow, YamlEditError, new_document

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
    removed: list[str] = field(default_factory=list)  # 消した YAML (最後のテーブルを消したファイル)
    notes: list[str] = field(default_factory=list)  # 書き換えた後に伝えること (YAML に書けなかったもの・消した ID を指すリンク)

    def lines(self) -> list[str]:
        return (
            [f"書き換えた: {path}" for path in self.written]
            + [f"作った: {path}" for path in self.created]
            + [f"消した: {path}" for path in self.removed]
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
        self.deleted: set[str] = set()  # 消すファイル

    def document(self, relative: str) -> Document:
        if relative not in self.documents:
            text = (self.root / relative).read_text(encoding="utf-8")
            self.originals[relative] = text
            self.documents[relative] = Document(text)
        return self.documents[relative]

    def create(self, relative: str, document: Document) -> None:
        self.originals[relative] = None
        self.documents[relative] = document

    def delete(self, relative: str) -> None:
        self.document(relative)
        self.deleted.add(relative)

    def write(self) -> tuple[list[str], list[str], list[str]]:
        written, created, removed = [], [], []
        for relative, document in self.documents.items():
            original = self.originals[relative]
            if relative in self.deleted:
                (self.root / relative).unlink()
                removed.append(relative)
                continue
            if original == document.text:
                continue
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(document.text, encoding="utf-8")
            (created if original is None else written).append(relative)
        return sorted(written), sorted(created), sorted(removed)

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


# PostgreSQL の連番のカラムの、正規化した型から YAML に書く型への対応 (Issue #208 のコメントの 5)
SERIAL_TYPES = {"integer": "serial", "bigint": "bigserial", "smallint": "smallserial"}


@dataclass
class _ColumnValues:
    """YAML に書く、カラムの比べる項目の値 (実装から求めたもの)。"""

    type: str
    nullable: bool
    default: str | None  # 正規化したデフォルト値。無ければ None
    references: str | None  # 参照先のカラムの完全な ID。外部キーが無ければ None


def _design_tables(project: Project) -> dict:
    return {table.name: table for domain in project.domains for table in domain.tables}


def _first(item_ids: list[str]) -> str:
    return "先に " + "・".join(item_ids) + " を解消する"


def _column_values(
    project: Project, actual: ActualSchema, table: ActualTable, column: ActualColumn, adding: "_Adding | None" = None
) -> _ColumnValues:
    """実装のカラムを、YAML に書く値にする。参照先が YAML に無ければ ResolveError。"""
    type_, _ = normalize_type(column.type, actual.kind)
    default: str | None
    if column.owned_sequence:
        if type_ not in SERIAL_TYPES:
            raise ResolveError(f"テーブル {table.name} のカラム {column.name} の連番の型 {type_} を、YAML に書けない")
        type_, default = SERIAL_TYPES[type_], None
    else:
        default = normalize_default(column.default, actual.kind, type_) or None
    keys = [k for k in table.foreign_keys if k.columns == [column.name] and len(k.ref_columns) == 1]
    if len(keys) > 1:
        raise ResolveError(f"テーブル {table.name} のカラム {column.name} には外部キーが 2 つ以上あるので、YAML に書けない")
    references = None
    if keys:
        ref_table, ref_column = keys[0].ref_table, keys[0].ref_columns[0]
        design = _design_tables(project).get(ref_table)
        if adding is not None and ref_table == adding.table:
            return _ColumnValues(type_, not column.not_null, default, f"{adding.table_id}-c-{ref_column}")
        if design is None:
            raise ResolveError(
                f"テーブル {table.name} のカラム {column.name} の外部キーの参照先のテーブル {ref_table} が YAML に無い。"
                + _first([f"d-{DOMAIN_PLACEHOLDER}-t-{ref_table}"])
            )
        target = next((c for c in design.children if c.name == ref_column), None)
        if target is None:
            raise ResolveError(
                f"テーブル {table.name} のカラム {column.name} の外部キーの参照先のカラム {ref_table}.{ref_column} が YAML に無い。"
                + _first([f"{design.id}-c-{ref_column}"])
            )
        references = target.id
    return _ColumnValues(type_, not column.not_null, default, references)


def _set_or_delete(document: Document, path: tuple, key: str, value, order: tuple[str, ...]) -> None:
    """値があれば書き、None なら (キーがあれば) 消す。"""
    if value is None:
        if key in document.node(path):
            document.delete_key(path, key)
    else:
        document.set_key(path, key, value, order)


def _match_table(files: _Files, case: Case) -> None:
    """テーブルの planned を外し、主キーを実装に合わせる。"""
    target = case.target
    document = files.document(_yaml_file(target))
    path = _table_path(target)
    if case.case == PLANNED_IMPLEMENTED:
        document.delete_key(path, "planned")
    primary_key = target.actual_table.primary_key
    if case.case == MISMATCH or primary_key != table_spec(target.table_entry).primary_key:
        existing = {column.name for column in target.table_entry.children}
        missing = [name for name in primary_key if name not in existing]
        if missing:
            raise ResolveError(
                f"テーブル {target.table_entry.id} の実装の主キーのカラム {'・'.join(missing)} が YAML に無い。"
                + _first([f"{target.table_entry.id}-c-{name}" for name in missing])
            )
        _set_or_delete(document, path, "primary_key", Flow(primary_key) if primary_key else None, TABLE_KEY_ORDER)


def _match_column(files: _Files, case: Case, project: Project, actual: ActualSchema) -> None:
    """カラムの planned を外し、比べる項目のうち違うものを実装の値に書き換える。"""
    target = case.target
    column = target.column_entry
    document = files.document(column.path)
    path = _column_path(target)
    if case.case == PLANNED_IMPLEMENTED:
        document.delete_key(path, "planned")
    values = _column_values(project, actual, target.actual_table, target.actual_column)
    different = different_keys(case.item)
    if values.nullable and column.name in table_spec(target.table_entry).primary_key and "null" in different:
        raise ResolveError(f"{column.id} は主キーのカラムなので、YAML に nullable: true を書けない。{PRIMARY_KEY_NULL_FIX}")
    # 連番 (PostgreSQL) は、型 serial などで表し、デフォルト値を書かない
    serial = target.actual_column.owned_sequence
    if "type" in different or (serial and "default" in different):
        document.set_key(path, "type", values.type, COLUMN_KEY_ORDER)
    if "default" in different:
        _set_or_delete(document, path, "default", Double(values.default) if values.default is not None else None, COLUMN_KEY_ORDER)
    if "null" in different:
        _set_or_delete(document, path, "nullable", True if values.nullable else None, COLUMN_KEY_ORDER)
    if "references" in different:
        _set_or_delete(document, path, "references", values.references, COLUMN_KEY_ORDER)


def _match_index(files: _Files, case: Case) -> None:
    """インデックスの planned を外し、一意かどうかを実装に合わせる。"""
    target = case.target
    document = files.document(_yaml_file(target))
    path = _index_path(document, target)
    if case.case == PLANNED_IMPLEMENTED:
        document.delete_key(path, "planned")
    if target.actual_index.unique != target.design_index.unique:
        _set_or_delete(document, path, "unique", True if target.actual_index.unique else None, INDEX_KEY_ORDER)


def _delete(files: _Files, case: Case) -> list[str]:
    """YAML から項目を消す。消した ID (手書きの Markdown のリンクを探すため) を返す。インデックスは ID を持たないので返さない。"""
    target = case.target
    table = target.table_entry
    relative = _yaml_file(target)
    document = files.document(relative)
    if target.kind == "table":
        if len(document.node(("tables",))) == 1:
            # ファイルの最後のテーブルなら、ファイルを消す (ファイル名が schema で始まる YAML には tables だけを書けるため)
            files.delete(relative)
        else:
            document.delete_key(("tables",), target.table)
        return [table.id]
    if target.kind == "column":
        column = target.column_entry
        first = []
        if column.name in table_spec(table).primary_key:
            first.append(table.id)
        first += [index_id(table.id, index.columns) for index in table_spec(table).indexes if column.name in index.columns]
        if first:
            raise ResolveError(f"{column.id} は、YAML の主キーかインデックスに含まれている。" + _first(first))
        document.delete_key(("tables", target.table, "columns"), column.name)
        return [column.id]
    path = _index_path(document, target)
    if len(document.node(path[:-1])) == 1:
        document.delete_key(path[:-2], "indexes")
    else:
        document.delete_item(path[:-1], path[-1])
    return []


def _link_notes(root: Path, deleted: list[str]) -> list[str]:
    """消した ID (と、その下の ID) を指す、手書きの Markdown のリンクの箇所。"""
    if not deleted:
        return []
    project, _ = load_project(root)
    index, _ = load_documents(root, project)
    notes = []
    for deleted_id in deleted:
        result = find_refs(index, deleted_id)
        if not result.references:
            continue
        notes.append(f"消した {deleted_id} (とその下の ID) を指すリンクがある。リンクを直す:")
        notes += [
            f"{r.path}:{r.line}:{r.column}: {r.target_id} {r.written} ({r.owner_id if r.in_body else DEFINITION_ONLY})"
            for r in result.references
        ]
    return notes


# ---- YAML に足す (Issue #208 のコメントの 3・4・5・7)

ADD_OPTIONS_MESSAGE = "--definition・--model・--attribute・--file は、実装にだけあるテーブルかカラムを YAML に足すときだけ使える"


@dataclass
class _Adding:
    """足すテーブルの、自分自身への外部キーを解決するための情報。"""

    table: str
    table_id: str


def _check_add_options(case: Case, request: Request, adding_ids: list[str], table_id: str) -> dict[str, dict[str, str]]:
    """足すものの定義の文と対応を、ID ごとに {"definition"|"model"|"attribute": 値} にする。誤りは ResolveError。"""
    target = case.target
    adding = request.flag == MATCH_IMPL and case.case == MISSING_DESIGN and target.kind != "index"
    given = request.definitions + request.models + request.attributes
    if not adding:
        if given or request.file:
            raise ResolveError(ADD_OPTIONS_MESSAGE)
        return {}
    if request.file and target.kind != "table":
        raise ResolveError("--file は、実装にだけあるテーブルを足すときだけ使える")
    values: dict[str, dict[str, str]] = {item_id: {} for item_id in adding_ids}
    for option, key, pairs in (
        ("--definition", "definition", request.definitions),
        ("--model", "model", request.models),
        ("--attribute", "attribute", request.attributes),
    ):
        for item_id, value in pairs:
            if item_id not in values:
                raise ResolveError(f"{option} の {item_id} は、この件で足すテーブルかカラムでない (足すもの: {'・'.join(adding_ids)})")
            if key == "model" and item_id != table_id:
                raise ResolveError(f"--model は、足すテーブル {table_id} にだけ指定できる ({item_id} はカラム)")
            if key in values[item_id]:
                raise ResolveError(f"{option} に {item_id} が 2 回ある")
            values[item_id][key] = value.strip() if key != "definition" else value
    missing = [item_id for item_id, value in values.items() if not value]
    if missing:
        raise ResolveError(
            "定義の文 (--definition) か対応 (--model・--attribute) が無い: " + "・".join(missing),
            "足すテーブルとカラムには、対応するモデル・属性か、定義の文が要る (検査 h)",
        )
    return values


def _ordered(values: dict, order: tuple[str, ...]) -> dict:
    return {key: values[key] for key in order if key in values}


def _new_column(
    project: Project, actual: ActualSchema, table: ActualTable, column: ActualColumn, mapping: dict[str, str],
    adding: _Adding | None,
) -> dict:
    if column.name in table.primary_key and not column.not_null:
        raise ResolveError(
            f"テーブル {table.name} のカラム {column.name} は主キーのカラムなので、YAML に nullable: true を書けない。{PRIMARY_KEY_NULL_FIX}"
        )
    if not names.is_name(column.name):
        raise ResolveError(f"テーブル {table.name} のカラム名 {column.name} は snake_case でないので、YAML に書けない")
    values = _column_values(project, actual, table, column, adding)
    result: dict = {"type": values.type}
    if values.nullable:
        result["nullable"] = True
    if values.default is not None:
        result["default"] = Double(values.default)
    if values.references is not None:
        result["references"] = values.references
    result.update(mapping)
    return _ordered(result, COLUMN_KEY_ORDER)


def _new_indexes(table: ActualTable) -> list[dict]:
    indexes = []
    for index in table.indexes:
        if index.has_expression:
            continue
        item: dict = {"columns": Flow(index.columns)}
        if index.unique:
            item["unique"] = True
        indexes.append(item)
    return indexes


def _word(name: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", text) is not None


def _unwritten_notes(table: ActualTable, column: str | None = None, index: ActualIndex | None = None) -> list[str]:
    """YAML に書けなかったもの (検査 j が比べないもの) を伝える行。column か index を渡せば、それに関係するものだけ。"""
    notes = []
    if index is None:
        for check in table.checks:
            if column is None or _word(column, check):
                notes.append(f"テーブル {table.name} の CHECK 制約 `{check}` は YAML に書けない。値の持ち方と条件の意味は design.md に書く")
        for key in table.foreign_keys:
            if len(key.columns) > 1 and (column is None or column in key.columns):
                notes.append(
                    f"テーブル {table.name} の複数のカラムからなる外部キー ({', '.join(key.columns)} → "
                    f"{key.ref_table}.{', '.join(key.ref_columns)}) は YAML に書けない (Issue #306 で扱う)"
                )
    for actual_index in table.indexes if column is None and index is None else ([index] if index is not None else []):
        if actual_index.has_expression:
            notes.append(f"テーブル {table.name} の式を含むインデックス ({', '.join(actual_index.columns)}) は YAML に書けない")
        elif actual_index.where:
            notes.append(
                f"テーブル {table.name} のインデックス ({', '.join(actual_index.columns)}) の条件 `{actual_index.where}` は"
                " YAML に書けない。条件の意味は design.md に書く"
            )
    return notes


def _table_file(project: Project, domain_name: str, given: str | None) -> str:
    domain = next(d for d in project.domains if d.name == domain_name)
    if given is None:
        return f"{domain.dir}/schema.yaml"
    path = PurePosixPath(given)
    if not path.name.startswith(SCHEMA_FILE_PREFIX) or path.suffix != ".yaml" or not given.startswith(domain.dir + "/"):
        raise ResolveError(
            f"--file {given} は、ドメイン {domain_name} のディレクトリ {domain.dir} の下の、ファイル名が {SCHEMA_FILE_PREFIX} で始まる YAML でない"
        )
    return given


def _add_table(files: _Files, case: Case, request: Request, project: Project, actual: ActualSchema, domain: str) -> list[str]:
    table = case.target.actual_table
    table_id = f"d-{domain}-t-{table.name}"
    if not names.is_name(table.name):
        raise ResolveError(f"テーブル名 {table.name} は snake_case でないので、YAML に書けない")
    column_ids = {column.name: f"{table_id}-c-{column.name}" for column in table.columns}
    values = _check_add_options(case, request, [table_id, *column_ids.values()], table_id)
    adding = _Adding(table.name, table_id)
    value: dict = dict(values[table_id])
    if table.primary_key:
        value["primary_key"] = Flow(table.primary_key)
    value["columns"] = {
        column.name: _new_column(project, actual, table, column, values[column_ids[column.name]], adding)
        for column in table.columns
    }
    indexes = _new_indexes(table)
    if indexes:
        value["indexes"] = indexes
    value = _ordered(value, TABLE_KEY_ORDER)
    relative = _table_file(project, domain, request.file)
    if (files.root / relative).exists():
        document = files.document(relative)
        tables = document.node(("tables",)) if isinstance(document.data, dict) and "tables" in document.data else None
        if not tables:
            raise ResolveError(f"{relative} に、テーブルを足すトップのキー tables が無いか、空になっている")
        document.insert_key(("tables",), table.name, value, len(tables))
    else:
        files.create(relative, new_document("tables", {table.name: value}))
    return _unwritten_notes(table)


def _add_column(files: _Files, case: Case, request: Request, project: Project, actual: ActualSchema) -> list[str]:
    target = case.target
    table, column = target.actual_table, target.actual_column
    column_id = case.id
    values = _check_add_options(case, request, [column_id], "")
    document = files.document(target.table_entry.path)
    columns_path = ("tables", target.table, "columns")
    existing = list(document.node(columns_path))
    # 実装のカラムの並び順で、直前にあるカラムのうち YAML にあるものの後ろ (無ければ先頭)
    index = 0
    for actual_column in table.columns:
        if actual_column.name == column.name:
            break
        if actual_column.name in existing:
            index = existing.index(actual_column.name) + 1
    document.insert_key(columns_path, column.name, _new_column(project, actual, table, column, values[column_id], None), index)
    return _unwritten_notes(table, column=column.name)


def _add_index(files: _Files, case: Case, request: Request) -> list[str]:
    _check_add_options(case, request, [], "")
    target = case.target
    table = target.table_entry
    existing = {column.name for column in table.children}
    missing = [name for name in target.index_columns if name not in existing]
    if missing:
        raise ResolveError(
            f"{case.id} のカラム {'・'.join(missing)} が YAML に無い。" + _first([f"{table.id}-c-{name}" for name in missing])
        )
    item: dict = {"columns": Flow(target.index_columns)}
    if target.actual_index.unique:
        item["unique"] = True
    document = files.document(table.path)
    table_path = ("tables", target.table)
    if "indexes" in document.node(table_path):
        document.append_item((*table_path, "indexes"), item)
    else:
        document.insert_key(table_path, "indexes", [item], len(document.node(table_path)))
    return _unwritten_notes(target.actual_table, index=target.actual_index)


def resolve(root: Path, project: Project, actual: ActualSchema, request: Request) -> Result:
    """件を 1 つ解消する。解消できなければ、何も書き換えずに ResolveError を投げる。"""
    cases = list_cases(project, actual)
    case, domain = find_case(project, cases, request.id)
    check_flag(case, request.flag)
    if not (request.flag == MATCH_IMPL and case.case == MISSING_DESIGN):
        _check_add_options(case, request, [], "")
    files = _Files(root)
    deleted: list[str] = []
    notes: list[str] = []
    try:
        if request.flag == PLANNED:
            _set_planned(files, case)
        elif request.flag == UNPLANNED:
            _unset_planned(files, case)
        elif case.case in (PLANNED_IMPLEMENTED, MISMATCH):
            if case.target.kind == "table":
                _match_table(files, case)
            elif case.target.kind == "column":
                _match_column(files, case, project, actual)
            else:
                _match_index(files, case)
        elif case.case == MISSING_IMPLEMENTATION:
            deleted = _delete(files, case)
        elif case.target.kind == "table":
            notes = _add_table(files, case, request, project, actual, domain)
        elif case.target.kind == "column":
            notes = _add_column(files, case, request, project, actual)
        else:
            notes = _add_index(files, case, request)
    except YamlEditError as e:
        raise ResolveError(f"{_yaml_file(case.target)}: {e}") from e
    written, created, removed = files.write()
    _, problems = load_project(root)
    if problems:
        files.restore()
        raise ResolveError(
            *[problem.format() for problem in problems],
            f"書き換えた後の YAML に {len(problems)} 件の誤り (検査 h) があるので、元に戻した",
        )
    return Result(written, created, removed, notes + _link_notes(root, deleted))
