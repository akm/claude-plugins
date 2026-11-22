"""実際のスキーマ: マイグレーションを一時的なデータベースに適用し、テーブル・カラム・キー・インデックス・CHECK 制約を読む。

対応するデータベースは、設定の database.kind の sqlite と postgresql (決めた経緯は Issue #207 のコメントの 1〜4・6・11)。
  sqlite      Python の標準ライブラリ sqlite3 で、メモリ上にデータベースを作る
  postgresql  Docker でコンテナを起動し、コンテナの中の psql を docker exec で実行する (このモジュールの後半)
マイグレーションは、設定の paths.migrations のパターンに合うファイルを、リポジトリのルートからの相対パスの文字コードの順に適用する。
読んだ値は正規化せず、データベースから読んだ形のまま持つ (正規化はモジュール schema_diff が行う)。ただし、SQLite の
INTEGER PRIMARY KEY のカラム (行の識別子の別名) は NULL を入れられないので、NULL を許可しないカラムとして読む。
"""

import json
import shutil
import signal
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .config import DatabaseConfig
from .impl_diff import ImplementationUnavailable


class MigrationError(Exception):
    """マイグレーションを適用できなかった (SQL の誤り・ファイルが無いなど)。メッセージは利用者に見せる文。

    path は、失敗したマイグレーションのファイルの、リポジトリのルートからの相対パス。ファイルに依らない失敗では None。
    """

    def __init__(self, message: str, path: str | None = None):
        super().__init__(message)
        self.path = path


@dataclass
class ActualColumn:
    name: str
    type: str  # データベースから読んだ型 (SQLite では書いた文字列のまま)
    not_null: bool
    default: str | None  # データベースから読んだデフォルト値の式
    owned_sequence: bool = False  # PostgreSQL で、デフォルト値が、このカラムが持つシーケンスの nextval (serial 系の型)


@dataclass
class ActualForeignKey:
    columns: list[str]
    ref_table: str
    ref_columns: list[str]  # 参照先のカラムを省いた外部キーは、参照先の主キー


@dataclass
class ActualIndex:
    name: str
    columns: list[str]  # インデックスのカラム。式を含むインデックスでは、式の文字列も入る
    unique: bool
    has_expression: bool = False
    where: str | None = None  # 部分インデックスの条件


@dataclass
class ActualTable:
    name: str
    columns: list[ActualColumn] = field(default_factory=list)  # 実際の並び順
    primary_key: list[str] = field(default_factory=list)
    foreign_keys: list[ActualForeignKey] = field(default_factory=list)
    indexes: list[ActualIndex] = field(default_factory=list)  # 主キーのためのインデックスは含まない
    checks: list[str] = field(default_factory=list)  # CHECK 制約の条件の式

    def column(self, name: str) -> ActualColumn | None:
        return next((c for c in self.columns if c.name == name), None)


@dataclass
class ActualSchema:
    kind: str  # 設定の database.kind
    tables: dict[str, ActualTable]  # テーブル名の文字コードの順


def migration_files(root: Path, pattern: str) -> list[str]:
    """パターンに合うファイルを、リポジトリのルートからの相対パスの文字コードの順に返す。"""
    files = sorted(path.relative_to(root).as_posix() for path in root.glob(pattern) if path.is_file())
    if not files:
        raise MigrationError(f"設定の paths.migrations のパターン {pattern} に合うファイルが無い")
    return files


def read_schema(root: Path, database: DatabaseConfig) -> ActualSchema:
    """マイグレーションを一時的なデータベースに適用し、実際のスキーマを読む。

    データベースが無ければ ImplementationUnavailable、適用できなければ MigrationError を投げる。
    """
    if database.kind == "sqlite":
        return _read_sqlite(root, database)
    if database.kind == "postgresql":
        return _read_postgresql(root, database)
    raise AssertionError(f"知らないデータベースの種類: {database.kind}")


# ---------------------------------------------------------------- SQLite


def _read_sqlite(root: Path, database: DatabaseConfig) -> ActualSchema:
    try:
        import sqlite3
    except ImportError as e:
        raise ImplementationUnavailable(
            f"Python の標準ライブラリ sqlite3 を読み込めない ({e})。sqlite3 を含む Python 3.12 以上でツールを実行する"
        ) from e
    files = migration_files(root, database.migrations)
    connection = sqlite3.connect(":memory:")
    try:
        for relative in files:
            text = (root / relative).read_text(encoding="utf-8")
            try:
                connection.executescript(text)
            except sqlite3.Error as e:
                raise MigrationError(f"マイグレーションを SQLite に適用できない: {e}", relative) from e
        return _sqlite_schema(connection)
    finally:
        connection.close()


def _sqlite_schema(connection) -> ActualSchema:
    rows = connection.execute(
        "SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\' ORDER BY name"
    ).fetchall()
    tables: dict[str, ActualTable] = {}
    for name, sql in rows:
        table = ActualTable(name=name)
        info = connection.execute("SELECT name, type, \"notnull\", dflt_value, pk FROM pragma_table_info(?)", (name,)).fetchall()
        keys = sorted((pk, column) for column, _, _, _, pk in info if pk > 0)
        table.primary_key = [column for _, column in keys]
        without_rowid = bool(sql) and _is_without_rowid(sql)
        for column, type_, not_null, default, _ in info:
            # INTEGER PRIMARY KEY (行の識別子の別名) には NULL を入れられない (入れると行の識別子が割り当てられる)
            rowid_alias = (
                table.primary_key == [column] and (type_ or "").strip().upper() == "INTEGER" and not without_rowid
            )
            table.columns.append(ActualColumn(column, type_ or "", bool(not_null) or rowid_alias, default))
        table.foreign_keys = _sqlite_foreign_keys(connection, name)
        table.indexes = _sqlite_indexes(connection, name)
        table.checks = check_constraints(sql or "")
        tables[name] = table
    for table in tables.values():
        for key in table.foreign_keys:
            if not key.ref_columns and key.ref_table in tables:
                key.ref_columns = list(tables[key.ref_table].primary_key)
    return ActualSchema(kind="sqlite", tables=tables)


def _sqlite_foreign_keys(connection, table: str) -> list[ActualForeignKey]:
    rows = connection.execute(
        "SELECT id, seq, \"table\", \"from\", \"to\" FROM pragma_foreign_key_list(?) ORDER BY id, seq", (table,)
    ).fetchall()
    keys: dict[int, ActualForeignKey] = {}
    for key_id, _, ref_table, column, ref_column in rows:
        key = keys.setdefault(key_id, ActualForeignKey([], ref_table, []))
        key.columns.append(column)
        if ref_column is not None:
            key.ref_columns.append(ref_column)
    # pragma の id は、後に書いた外部キーほど小さい。書いた順に並べ直す
    return [keys[key_id] for key_id in sorted(keys, reverse=True)]


def _sqlite_indexes(connection, table: str) -> list[ActualIndex]:
    indexes = []
    rows = connection.execute("SELECT name, \"unique\", origin, partial FROM pragma_index_list(?)", (table,)).fetchall()
    for name, unique, origin, partial in rows:
        if origin == "pk":
            continue
        sql_row = connection.execute("SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?", (name,)).fetchone()
        sql = sql_row[0] if sql_row and sql_row[0] else ""
        info = connection.execute(
            "SELECT seqno, cid, name FROM pragma_index_xinfo(?) WHERE key = 1 ORDER BY seqno", (name,)
        ).fetchall()
        has_expression = any(cid == -2 for _, cid, _ in info)
        if has_expression:
            columns = index_terms(sql)
        else:
            columns = [column for _, _, column in info]
        where = index_where(sql) if partial else None
        indexes.append(ActualIndex(name=name, columns=columns, unique=bool(unique), has_expression=has_expression, where=where))
    indexes.sort(key=lambda index: index.name)
    return indexes


# ---------------------------------------------------------------- PostgreSQL (Docker のコンテナ)

POSTGRES_USER = "postgres"
POSTGRES_PASSWORD = "doc-structured"
POSTGRES_DB = "doc_structured"
# コンテナの名前の接頭辞。後ろに、重ならない文字列を付ける
CONTAINER_PREFIX = "doc-structured-"
# コンテナの起動 (イメージの取得を含む) と、PostgreSQL が接続を受け付けるまでの時間の上限 (秒)
START_TIMEOUT = 600
READY_TIMEOUT = 60
# psql をコンテナの中で実行するときの引数。初期化の途中の一時的なサーバーは TCP を受け付けないので、127.0.0.1 に接続する
_PSQL = ["psql", "-h", "127.0.0.1", "-U", POSTGRES_USER, "-d", POSTGRES_DB, "-X", "-q", "-v", "ON_ERROR_STOP=1"]

# 実際のスキーマを、スキーマ public のテーブルについて、JSON の 1 つの値で返す問い合わせ
_SCHEMA_QUERY = """
SELECT COALESCE(json_agg(t ORDER BY t->>'name'), '[]'::json) FROM (
  SELECT json_build_object(
    'name', c.relname,
    'columns', (
      SELECT COALESCE(json_agg(json_build_object(
        'name', a.attname,
        'type', format_type(a.atttypid, a.atttypmod),
        'not_null', a.attnotnull,
        'default', pg_get_expr(d.adbin, d.adrelid),
        'owned_sequence', d.adbin IS NOT NULL AND pg_get_expr(d.adbin, d.adrelid) LIKE 'nextval(%' AND EXISTS (
          SELECT 1 FROM pg_depend dep JOIN pg_class s ON s.oid = dep.objid AND s.relkind = 'S'
          WHERE dep.refobjid = c.oid AND dep.refobjsubid = a.attnum AND dep.deptype = 'a')
      ) ORDER BY a.attnum), '[]'::json)
      FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
      WHERE a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped),
    'primary_key', (
      SELECT COALESCE(json_agg(a.attname ORDER BY k.ord), '[]'::json)
      FROM pg_constraint con CROSS JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
      JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum
      WHERE con.conrelid = c.oid AND con.contype = 'p'),
    'foreign_keys', (
      SELECT COALESCE(json_agg(json_build_object(
        'columns', (SELECT json_agg(a.attname ORDER BY k.ord) FROM unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
                    JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum),
        'ref_table', rc.relname,
        'ref_columns', (SELECT json_agg(a.attname ORDER BY k.ord) FROM unnest(con.confkey) WITH ORDINALITY AS k(attnum, ord)
                        JOIN pg_attribute a ON a.attrelid = con.confrelid AND a.attnum = k.attnum)
      ) ORDER BY con.conname), '[]'::json)
      FROM pg_constraint con JOIN pg_class rc ON rc.oid = con.confrelid
      WHERE con.conrelid = c.oid AND con.contype = 'f'),
    'indexes', (
      SELECT COALESCE(json_agg(json_build_object(
        'name', ic.relname,
        'unique', i.indisunique,
        'columns', (SELECT json_agg(pg_get_indexdef(i.indexrelid, k.ord, true) ORDER BY k.ord)
                    FROM generate_series(1, i.indnkeyatts::int) AS k(ord)),
        'has_expression', i.indexprs IS NOT NULL,
        'where', pg_get_expr(i.indpred, i.indrelid, true)
      ) ORDER BY ic.relname), '[]'::json)
      FROM pg_index i JOIN pg_class ic ON ic.oid = i.indexrelid
      WHERE i.indrelid = c.oid AND NOT i.indisprimary),
    'checks', (
      SELECT COALESCE(json_agg(pg_get_expr(con.conbin, con.conrelid, true) ORDER BY con.conname), '[]'::json)
      FROM pg_constraint con WHERE con.conrelid = c.oid AND con.contype = 'c')
  ) AS t
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') AND NOT c.relispartition
) AS tables
"""


def _docker(*args: str, input: str | None = None, timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], input=input, capture_output=True, text=True, timeout=timeout)


def _check_docker() -> None:
    """Docker が使えなければ ImplementationUnavailable を投げる。"""
    if shutil.which("docker") is None:
        raise ImplementationUnavailable(
            "コマンド docker が無い (設定の database.kind が postgresql なので、PostgreSQL のコンテナを Docker で起動する)。"
            "Docker をインストールして起動する"
        )
    try:
        result = _docker("info", "--format", "{{.ServerVersion}}", timeout=60)
    except subprocess.TimeoutExpired as e:
        raise ImplementationUnavailable("Docker のデーモンに接続できない (docker info が 60 秒で終了しなかった)。Docker を起動する") from e
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ImplementationUnavailable(f"Docker のデーモンに接続できない ({detail})。Docker を起動する")


def _raise_interrupt(signum, frame):
    raise KeyboardInterrupt(f"シグナル {signum} を受けた")


def _read_postgresql(root: Path, database: DatabaseConfig) -> ActualSchema:
    files = migration_files(root, database.migrations)
    _check_docker()
    name = CONTAINER_PREFIX + uuid.uuid4().hex[:12]
    # 終了のシグナル (SIGTERM) を受けても、コンテナを消してから終了する。Ctrl+C (KeyboardInterrupt) も同じ
    previous = signal.signal(signal.SIGTERM, _raise_interrupt)
    try:
        started = _docker(
            "run", "--detach", "--rm", "--name", name,
            "--env", f"POSTGRES_USER={POSTGRES_USER}", "--env", f"POSTGRES_PASSWORD={POSTGRES_PASSWORD}",
            "--env", f"POSTGRES_DB={POSTGRES_DB}",
            database.image or "", timeout=START_TIMEOUT,
        )
        if started.returncode != 0:
            raise MigrationError(
                f"PostgreSQL のコンテナを起動できない (イメージ {database.image}): {started.stderr.strip()}"
            )
        _wait_ready(name)
        for relative in files:
            text = (root / relative).read_text(encoding="utf-8")
            applied = _docker("exec", "-i", "--env", f"PGPASSWORD={POSTGRES_PASSWORD}", name, *_PSQL, "-f", "-", input=text)
            if applied.returncode != 0:
                raise MigrationError(f"マイグレーションを PostgreSQL に適用できない: {applied.stderr.strip()}", relative)
        queried = _docker(
            "exec", "--env", f"PGPASSWORD={POSTGRES_PASSWORD}", name, *_PSQL, "-A", "-t", "-c", _SCHEMA_QUERY
        )
        if queried.returncode != 0:
            raise MigrationError(f"PostgreSQL から実際のスキーマを読めない: {queried.stderr.strip()}")
        return _postgresql_schema(json.loads(queried.stdout))
    finally:
        # 起動に失敗したときもコンテナが残っていないかを確認して消す (無ければ docker rm が失敗するだけ)
        _docker("rm", "--force", name, timeout=120)
        signal.signal(signal.SIGTERM, previous)


def _wait_ready(name: str) -> None:
    deadline = time.monotonic() + READY_TIMEOUT
    while True:
        ready = _docker("exec", name, "pg_isready", "-h", "127.0.0.1", "-U", POSTGRES_USER, "-d", POSTGRES_DB, timeout=30)
        if ready.returncode == 0:
            return
        if time.monotonic() > deadline:
            raise MigrationError(
                f"PostgreSQL のコンテナが {READY_TIMEOUT} 秒たっても接続を受け付けない: {(ready.stdout + ready.stderr).strip()}"
            )
        time.sleep(0.5)


def _postgresql_schema(rows: list[dict]) -> ActualSchema:
    tables: dict[str, ActualTable] = {}
    for row in rows:
        table = ActualTable(name=row["name"])
        table.columns = [
            ActualColumn(c["name"], c["type"], bool(c["not_null"]), c["default"], bool(c["owned_sequence"]))
            for c in row["columns"]
        ]
        table.primary_key = list(row["primary_key"])
        table.foreign_keys = [
            ActualForeignKey(list(k["columns"]), k["ref_table"], list(k["ref_columns"])) for k in row["foreign_keys"]
        ]
        table.indexes = [
            ActualIndex(i["name"], list(i["columns"]), bool(i["unique"]), bool(i["has_expression"]), i["where"])
            for i in row["indexes"]
        ]
        table.checks = list(row["checks"])
        tables[table.name] = table
    return ActualSchema(kind="postgresql", tables=dict(sorted(tables.items())))


# ---------------------------------------------------------------- SQL の文字列を読む

_OPEN_QUOTES = {"'": "'", '"': '"', "`": "`", "[": "]"}


def _scan(sql: str):
    """SQL の文字列を 1 文字ずつ読み、(位置, 文字, 括弧の深さ) を返す。引用符の中とコメントは返さない。"""
    depth = 0
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch in _OPEN_QUOTES:
            close = _OPEN_QUOTES[ch]
            j = i + 1
            while j < len(sql):
                if sql[j] == close:
                    if close != "]" and j + 1 < len(sql) and sql[j + 1] == close:
                        j += 2
                        continue
                    break
                j += 1
            i = j + 1
            continue
        if sql.startswith("--", i):
            j = sql.find("\n", i)
            i = len(sql) if j < 0 else j + 1
            continue
        if sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            i = len(sql) if j < 0 else j + 2
            continue
        if ch == "(":
            yield i, ch, depth
            depth += 1
        elif ch == ")":
            depth -= 1
            yield i, ch, depth
        else:
            yield i, ch, depth
        i += 1


def _matching_paren(sql: str, start: int) -> int:
    """位置 start の「(」に対応する「)」の位置。"""
    for i, ch, depth in _scan(sql[start:]):
        if ch == ")" and depth == 0:
            return start + i
    return len(sql)


def _keyword_positions(sql: str, keyword: str, depth: int) -> list[int]:
    """括弧の深さ depth で、引用符の外にある語 keyword (大文字・小文字を問わない) の位置。"""
    positions = []
    upper = keyword.upper()
    for i, ch, d in _scan(sql):
        if d != depth or ch.upper() != upper[0]:
            continue
        if sql[i : i + len(keyword)].upper() != upper:
            continue
        before = sql[i - 1] if i > 0 else " "
        after = sql[i + len(keyword)] if i + len(keyword) < len(sql) else " "
        if (before.isalnum() or before == "_") or (after.isalnum() or after == "_"):
            continue
        positions.append(i)
    return positions


def _split_top(text: str) -> list[str]:
    """括弧と引用符の外のカンマで分ける。"""
    parts = []
    start = 0
    for i, ch, depth in _scan(text):
        if ch == "," and depth == 0:
            parts.append(text[start:i].strip())
            start = i + 1
    parts.append(text[start:].strip())
    return [part for part in parts if part]


def check_constraints(create_table: str) -> list[str]:
    """CREATE TABLE の文から、CHECK 制約 (カラムの制約と、テーブルの制約) の条件の式を、書いた順に返す。"""
    open_at = create_table.find("(")
    if open_at < 0:
        return []
    body = create_table[open_at + 1 : _matching_paren(create_table, open_at)]
    checks = []
    for position in _keyword_positions(body, "CHECK", 0):
        paren = body.find("(", position)
        if paren < 0:
            continue
        checks.append(body[paren + 1 : _matching_paren(body, paren)].strip())
    return checks


def _is_without_rowid(create_table: str) -> bool:
    open_at = create_table.find("(")
    rest = create_table[_matching_paren(create_table, open_at) + 1 :] if open_at >= 0 else ""
    return "ROWID" in rest.upper()


def index_terms(create_index: str) -> list[str]:
    """CREATE INDEX の文の、インデックスの項目 (カラムか式) の文字列。"""
    on_positions = _keyword_positions(create_index, "ON", 0)
    if not on_positions:
        return []
    paren = create_index.find("(", on_positions[0])
    if paren < 0:
        return []
    return _split_top(create_index[paren + 1 : _matching_paren(create_index, paren)])


def index_where(create_index: str) -> str | None:
    """CREATE INDEX の文の、部分インデックスの条件 (WHERE の後の式)。"""
    positions = _keyword_positions(create_index, "WHERE", 0)
    if not positions:
        return None
    return create_index[positions[-1] + len("WHERE") :].strip().rstrip(";").strip() or None
