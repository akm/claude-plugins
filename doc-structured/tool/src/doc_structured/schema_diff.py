"""設計 (ファイル名が schema で始まる YAML) と実際のスキーマを正規化し、検査 j の項目と正規化した行にする。

比べる項目: テーブルの有無、カラムの名前・型・NULL を許可するか・デフォルト値、主キー、外部キー、一意の制約、インデックスのカラムの組。
比べない項目: カラムの並び順、制約とインデックスの名前、コメント、所有者と権限、CHECK 制約、部分インデックスの条件、
式を含むインデックス、複数のカラムからなる外部キー (YAML に書けないため。#306)。
正規化 (型・デフォルト値・PostgreSQL の別名と連番) と比べ方は、Issue #207 のコメントの 5〜8 で決めた。
形式の SSOT はプラグインの規則の文書 (ファイル doc-structured/rules/doc-structured-domains.md)。
"""

import re
from dataclasses import dataclass

from . import generated_header
from .config import DatabaseConfig
from .generate import ER_TYPE_FORBIDDEN_RE, _table_row, escape_cell
from .domains import Entry, Project
from .impl_diff import Item, Location
from .schema_actual import ActualSchema, ActualTable
from .tables import column_spec, index_is_planned, is_planned, table_spec

# 比べる項目の名前と、メッセージに書く名前
LABELS = {
    "type": "型",
    "null": "NULL を許可するか",  # 英字で始まるので、メッセージでは「の」との間に空白が入る
    "default": "デフォルト値",
    "references": "外部キーの参照先",
    "primary_key": "主キー",
    "unique": "一意かどうか",
}

# 主キーのカラムの NULL が違うときの直し方。YAML の主キーのカラムには nullable を書けない。SQLite では、INTEGER PRIMARY KEY
# 以外の主キーに NOT NULL を書かないと NULL が入る
PRIMARY_KEY_NULL_FIX = "マイグレーションで、主キーのカラムに NOT NULL を付ける (YAML の主キーのカラムには nullable を書けない)"

# PostgreSQL の serial 系の型と、デフォルト値が連番であることを表す、正規化した形の値
SERIAL_DEFAULT = "serial"

# PostgreSQL の型の別名から正式な名前 (format_type が返す名前) への対応。括弧の引数は別に扱う
POSTGRESQL_TYPE_ALIASES = {
    "int": "integer",
    "int4": "integer",
    "int8": "bigint",
    "int2": "smallint",
    "varchar": "character varying",
    "char": "character",
    "bpchar": "character",
    "timestamptz": "timestamp with time zone",
    "timestamp": "timestamp without time zone",
    "timetz": "time with time zone",
    "time": "time without time zone",
    "bool": "boolean",
    "float8": "double precision",
    "float": "double precision",
    "float4": "real",
    "decimal": "numeric",
    "varbit": "bit varying",
}
POSTGRESQL_SERIALS = {
    "serial": "integer",
    "serial4": "integer",
    "bigserial": "bigint",
    "serial8": "bigint",
    "smallserial": "smallint",
    "serial2": "smallint",
}

_TYPE_RE = re.compile(r"^(?P<base>[a-z][a-z0-9_ ]*?)(?P<args>\([^)]*\))?(?P<rest>( with(out)? time zone)?)(?P<array>(\[\d*\])*)$")


# ---------------------------------------------------------------- 正規化


def normalize_type(text: str, kind: str) -> tuple[str, bool]:
    """型を正規化する。2 つ目の値は、PostgreSQL の serial 系の型だったか (デフォルト値を連番として扱う)。"""
    value = re.sub(r"\s+", " ", text.strip())
    value = re.sub(r"\s*([(),])\s*", r"\1", value).replace(",", ", ").lower()
    if kind != "postgresql":
        return value, False
    match = _TYPE_RE.match(value)
    if match is None:
        return value, False
    base, args, rest, array = match["base"].strip(), match["args"] or "", match["rest"], match["array"]
    if base in POSTGRESQL_SERIALS and not args and not rest:
        return POSTGRESQL_SERIALS[base] + array, True
    if base in ("timestamp", "time") and not rest:
        rest = " without time zone"
    elif base in ("timestamptz", "timetz"):
        base, rest = base[:-2], " with time zone"
    elif not rest:
        base = POSTGRESQL_TYPE_ALIASES.get(base, base)
    if base == "character" and not args:
        args = "(1)"
    return f"{base}{args}{rest}{array}", False


def _strip_outer_parens(text: str) -> str:
    while text.startswith("(") and text.endswith(")") and _closes_at_end(text):
        text = text[1:-1].strip()
    return text


def _closes_at_end(text: str) -> bool:
    """先頭の「(」に対応する「)」が、末尾の文字か。"""
    depth = 0
    quote = None
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i == len(text) - 1
    return False


def _lower_outside_quotes(text: str) -> str:
    parts = re.split(r"('(?:[^']|'')*'|\"(?:[^\"]|\"\")*\")", text)
    return "".join(part if part[:1] in ("'", '"') else part.lower() for part in parts)


def normalize_default(text: str | None, kind: str, column_type: str) -> str:
    """デフォルト値を正規化する。column_type は正規化したカラムの型 (PostgreSQL の型変換を除くため)。"""
    if text is None:
        return ""
    value = _lower_outside_quotes(_strip_outer_parens(text.strip()))
    if kind == "postgresql":
        base = column_type.split("(")[0]
        match = re.match(r"^(?P<value>.*?)::(?P<cast>[a-z][a-z0-9_ ]*(\([^)]*\))?(\[\])?)$", value)
        if match is not None and normalize_type(match["cast"], kind)[0].split("(")[0] == base:
            value = _strip_outer_parens(match["value"].strip())
    return value


def _null(nullable: bool) -> str:
    return "null" if nullable else "not null"


# ---------------------------------------------------------------- 設計と実装を、テーブルごとの比べる形にする


@dataclass
class _Column:
    type: str
    nullable: bool
    default: str
    references: str  # 「テーブル.カラム」。外部キーが無ければ空


@dataclass
class _Index:
    columns: tuple[str, ...]
    unique: bool


def _column_values(column: _Column) -> dict[str, str]:
    values = {"type": column.type, "null": "許可する" if column.nullable else "許可しない", "default": column.default}
    if column.references:
        values["references"] = column.references
    return values


def _design_column(project: Project, column: Entry, kind: str) -> _Column:
    spec = column_spec(column)
    type_, serial = normalize_type(spec.type, kind)
    default = SERIAL_DEFAULT if serial and spec.default is None else normalize_default(spec.default, kind, type_)
    reference = column.reference("references")
    target = project.entries.get(reference.target) if reference is not None else None
    references = f"{target.parent.name}.{target.name}" if target is not None and target.parent is not None else ""
    return _Column(type_, spec.nullable, default, references)


def _actual_columns(table: ActualTable, kind: str) -> dict[str, _Column]:
    references: dict[str, list[str]] = {}
    for key in table.foreign_keys:
        if len(key.columns) == 1 and len(key.ref_columns) == 1:
            references.setdefault(key.columns[0], []).append(f"{key.ref_table}.{key.ref_columns[0]}")
    columns = {}
    for column in table.columns:
        type_, _ = normalize_type(column.type, kind)
        default = SERIAL_DEFAULT if column.owned_sequence else normalize_default(column.default, kind, type_)
        columns[column.name] = _Column(
            type_, not column.not_null, default, ", ".join(sorted(references.get(column.name, [])))
        )
    return columns


def _pair_indexes(design: list[_Index], actual: list[_Index]) -> tuple[list[tuple[_Index | None, _Index | None]], list]:
    """インデックスを、カラムの組と一意かどうかが同じものから組にし、残りをカラムの組で組にする。"""
    pairs: list[tuple[_Index | None, _Index | None]] = []
    rest_design = list(design)
    rest_actual = list(actual)
    for matcher in (lambda a, b: a == b, lambda a, b: a.columns == b.columns):
        for d in list(rest_design):
            match = next((a for a in rest_actual if matcher(d, a)), None)
            if match is not None:
                pairs.append((d, match))
                rest_design.remove(d)
                rest_actual.remove(match)
    pairs += [(d, None) for d in rest_design] + [(None, a) for a in rest_actual]
    return pairs, rest_actual


def _index_name(table_name: str, index: _Index) -> str:
    return f"{table_name} のインデックス ({', '.join(index.columns)})"


# ---------------------------------------------------------------- 項目と正規化した行


@dataclass
class SchemaDiff:
    items: list[Item]
    design_lines: list[str]
    actual_lines: list[str]


_KIND_ORDER = {"column": 1, "primary key": 2, "foreign key": 3, "index": 4}


def _sorted_lines(facts: list[tuple[str, str, str]]) -> list[str]:
    """(テーブル, 行の種類, 残り) の事実を並べ、正規化した行にする。"""
    lines = []
    for table, kind, rest in sorted(facts, key=lambda f: (f[0], _KIND_ORDER.get(f[1], 0), f[2])):
        lines.append(f"table {table}" if kind == "table" else f"table {table} {kind} {rest}".rstrip())
    return lines


def _column_fact(name: str, column: _Column) -> str:
    text = f"{name}: {column.type} {_null(column.nullable)}"
    return text + (f" default {column.default}" if column.default else "")


def _table_facts(name: str, columns: dict[str, _Column], primary_key: list[str], indexes: list[_Index]):
    facts = [(name, "table", "")]
    for column_name, column in columns.items():
        facts.append((name, "column", _column_fact(column_name, column)))
        if column.references:
            facts.append((name, "foreign key", f"{column_name}: {column.references}"))
    if primary_key:
        facts.append((name, "primary key", ", ".join(primary_key)))
    for index in indexes:
        facts.append((name, "index", ", ".join(index.columns) + (" unique" if index.unique else "")))
    return facts


def compare(project: Project, actual: ActualSchema) -> SchemaDiff:
    """設計と実際のスキーマを比べる項目と、正規化した行 (設計・実装) を作る。設計の行は、未実装のものを含めない。"""
    kind = actual.kind
    design_tables: dict[str, Entry] = {}
    for domain in project.domains:
        for table in domain.tables:
            design_tables.setdefault(table.name, table)
    items: list[Item] = []
    design_facts: list[tuple[str, str, str]] = []
    actual_facts: list[tuple[str, str, str]] = []

    actual_index_lists: dict[str, list[_Index]] = {}
    actual_column_maps: dict[str, dict[str, _Column]] = {}
    for name, table in actual.tables.items():
        actual_column_maps[name] = _actual_columns(table, kind)
        actual_index_lists[name] = [
            _Index(tuple(index.columns), index.unique) for index in table.indexes if not index.has_expression
        ]
        actual_facts += _table_facts(name, actual_column_maps[name], table.primary_key, actual_index_lists[name])

    for name in sorted(set(design_tables) | set(actual.tables)):
        entry = design_tables.get(name)
        actual_table = actual.tables.get(name)
        actual_columns = actual_column_maps.get(name, {})
        actual_indexes = actual_index_lists.get(name, [])
        if entry is None:
            items.append(Item(f"テーブル {name}", None, {}))
            continue
        spec = table_spec(entry)
        table_planned = spec.planned
        design_columns = {
            column.name: _design_column(project, column, kind) for column in entry.children if not is_planned(column)
        }
        design_indexes = [
            _Index(tuple(index.columns), index.unique) for index in spec.indexes if not index_is_planned(entry, index)
        ]
        if not table_planned:
            design_facts += _table_facts(name, design_columns, spec.primary_key, design_indexes)
        item = Item(
            f"テーブル {entry.id}",
            {"primary_key": ", ".join(spec.primary_key)},
            None if actual_table is None else {"primary_key": ", ".join(actual_table.primary_key)},
            planned=table_planned,
            location=Location(entry.path, entry.line, entry.column),
        )
        items.append(item)
        for column in entry.children:
            actual_column = actual_columns.get(column.name)
            item.children.append(
                Item(
                    f"カラム {column.id}",
                    _column_values(_design_column(project, column, kind)),
                    None if actual_column is None else _column_values(actual_column),
                    planned=column_spec(column).planned,
                    location=Location(column.path, column.line, column.column),
                    fixes={"null": PRIMARY_KEY_NULL_FIX} if column.name in spec.primary_key else {},
                )
            )
        for column_name, actual_column in actual_columns.items():
            if not any(column.name == column_name for column in entry.children):
                item.children.append(Item(f"テーブル {entry.id} のカラム {column_name}", None, _column_values(actual_column)))
        # 未実装のインデックスは、実装にあるかを確かめるために組にする (実装にあれば planned を外す指示を出す)
        all_design = [(index, _Index(tuple(index.columns), index.unique)) for index in spec.indexes]
        pairs, _ = _pair_indexes([d for _, d in all_design], actual_indexes)
        for design_index, actual_index in pairs:
            if design_index is None:
                item.children.append(
                    Item(_index_name(f"テーブル {entry.id}", actual_index), None, {"unique": _yes(actual_index.unique)})
                )
                continue
            spec_index = next(index for index, d in all_design if d is design_index)
            item.children.append(
                Item(
                    _index_name(f"テーブル {entry.id}", design_index),
                    {"unique": _yes(design_index.unique)},
                    None if actual_index is None else {"unique": _yes(actual_index.unique)},
                    planned=spec_index.planned,
                    location=Location(entry.path, spec_index.line, spec_index.column),
                )
            )
    return SchemaDiff(items, _sorted_lines(design_facts), _sorted_lines(actual_facts))


def _yes(value: bool) -> str:
    return "一意" if value else "一意でない"


# ---------------------------------------------------------------- 実際のスキーマのファイル docs/system/schema-actual.md

GENERATE_ALL_COMMAND = "bin/doc-structured generate --all"
ACTUAL_COLUMNS_HEADER = ["カラム", "型", "NULL", "デフォルト値", "参照先"]
DATABASE_NAMES = {"sqlite": "SQLite", "postgresql": "PostgreSQL"}


def _code_span(text: str) -> str:
    """インラインコード。中に「`」があれば、それより長い「`」の並びで囲む。"""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    padded = f" {text} " if longest or text.startswith("`") or text.endswith("`") else text
    return f"{fence}{padded}{fence}"


def _actual_key_marks(table: ActualTable, column: str) -> list[str]:
    marks = []
    if column in table.primary_key:
        marks.append("PK")
    if any(column in key.columns for key in table.foreign_keys):
        marks.append("FK")
    if any(index.unique and not index.has_expression and index.columns == [column] for index in table.indexes):
        marks.append("UK")
    return marks


def _actual_unique_alone(table: ActualTable, columns: list[str]) -> bool:
    return table.primary_key == columns or any(
        index.unique and not index.has_expression and index.columns == columns for index in table.indexes
    )


def _actual_er_diagram(actual: ActualSchema) -> str:
    lines = ["```mermaid", "erDiagram"]
    for table in actual.tables.values():
        if not table.columns:
            lines.append(f'  "{table.name}"')
            continue
        lines.append(f'  "{table.name}" {{')
        for column in table.columns:
            parts = [ER_TYPE_FORBIDDEN_RE.sub("_", column.type) or "_", column.name]
            marks = _actual_key_marks(table, column.name)
            if marks:
                parts.append(", ".join(marks))
            lines.append("    " + " ".join(parts))
        lines.append("  }")
    for table in actual.tables.values():
        for key in table.foreign_keys:
            nullable = any(not (table.column(c) and table.column(c).not_null) for c in key.columns)
            left = "|o" if nullable else "||"
            right = "o|" if _actual_unique_alone(table, key.columns) else "o{"
            lines.append(f'  "{key.ref_table}" {left}--{right} "{table.name}" : "{", ".join(key.columns)}"')
    lines.append("```")
    return "\n".join(lines)


def _actual_table_blocks(table: ActualTable) -> list[str]:
    blocks = [f"## テーブル {_code_span(table.name)}"]
    if table.primary_key:
        blocks.append("主キー: " + "・".join(_code_span(c) for c in table.primary_key))
    references: dict[str, list[str]] = {}
    multi = []
    for key in table.foreign_keys:
        if len(key.columns) == 1:
            ref = key.ref_columns[0] if key.ref_columns else ""
            references.setdefault(key.columns[0], []).append(f"{_code_span(key.ref_table)}.{_code_span(ref)}")
        else:
            multi.append(key)
    if table.columns:
        rows = [_table_row(ACTUAL_COLUMNS_HEADER), "|" + "---|" * len(ACTUAL_COLUMNS_HEADER)]
        for column in table.columns:
            rows.append(_table_row([
                escape_cell(_code_span(column.name)),
                escape_cell(_code_span(column.type)) if column.type else "",
                "" if column.not_null else "許可",
                escape_cell(_code_span(column.default)) if column.default is not None else "",
                escape_cell("・".join(references.get(column.name, []))),
            ]))
        blocks.append("\n".join(rows))
    if multi:
        blocks.append("複数のカラムからなる外部キー:")
        blocks.append("\n".join(
            f"- {'・'.join(_code_span(c) for c in key.columns)} → "
            + "・".join(f"{_code_span(key.ref_table)}.{_code_span(c)}" for c in key.ref_columns)
            for key in multi
        ))
    if table.indexes:
        blocks.append("インデックス:")
        items = []
        for index in table.indexes:
            notes = []
            if index.unique:
                notes.append("一意")
            if index.where:
                notes.append(f"条件: {_code_span(index.where)}")
            text = "・".join(_code_span(c) for c in index.columns)
            items.append(f"- {text} ({'。'.join(notes)})" if notes else f"- {text}")
        blocks.append("\n".join(items))
    if table.checks:
        blocks.append("CHECK 制約:")
        blocks.append("\n".join(f"- {_code_span(check)}" for check in table.checks))
    return blocks


def render_schema_actual(actual: ActualSchema, database: DatabaseConfig) -> str:
    """実際のスキーマのファイル。中身はマイグレーションだけで決まり、設計へのリンク・ID・アンカーを持たない。"""
    name = DATABASE_NAMES[database.kind]
    if database.image:
        name += f" (イメージ {_code_span(database.image)})"
    blocks = [
        "# 実際のスキーマ",
        f"マイグレーション {_code_span(database.migrations)} を {name} に適用したスキーマ。",
    ]
    if actual.tables:
        blocks.append(_actual_er_diagram(actual))
    for table in actual.tables.values():
        blocks += _actual_table_blocks(table)
    header = generated_header.markdown_line(database.migrations, GENERATE_ALL_COMMAND)
    return header + "\n\n" + "\n\n".join(blocks) + "\n"
