"""設定ファイル .claude/akm-claude-plugins/doc-structured/config.yaml の探索と読み込み。

ツールは起動時に設定の全体を YAML として読み、形が違えばエラー (例外 ConfigError) にする。
設定ファイルは、カレントディレクトリから親へ向かって探す (git がディレクトリ .git を探すのと同じ)。

設定の形 (決定の一覧の問 12 (4)):
  version   プロジェクトが使うツールのバージョン。「version: 1.2.3」の形の 1 行で書く。
            スクリプト bin/doc-structured がこの行だけを文字列の一致で取り出すので、引用符を付けたり、同じ行にコメントを
            書いたりしてはいけない。この制約もここで検査する
  paths.migrations
            マイグレーションの SQL のファイルの glob のパターン 1 つ (リポジトリのルートからの相対。** も使える)
  database  マイグレーションを適用するデータベース。paths.migrations と、どちらも書くか、どちらも書かない
    kind           sqlite か postgresql (必須)
    image          PostgreSQL のコンテナのイメージ。kind が postgresql のときだけ書け、そのときは必須
    schema_actual  true を書くと、実際のスキーマのファイル docs/system/schema-actual.md を作る (true だけを書ける)
知らないキーがあればエラーにする (設定がツールより新しいときに、読み飛ばさずに気づけるように)。
paths のほかのキーと導入する範囲は、それを必要とする sub-issue で足す。
paths と database の形は、sub-issue 11b で決めた (決めた経緯は Issue #207 のコメントの 4・10)。
"""

import re
from dataclasses import dataclass
from pathlib import Path

from ruamel.yaml import YAMLError
from ruamel.yaml.comments import CommentedMap

from . import yamlio

CONFIG_RELATIVE_PATH = Path(".claude/akm-claude-plugins/doc-structured/config.yaml")

# 「version: X.Y.Z」の形の行。スクリプト bin/doc-structured の grep の正規表現と同じにする
VERSION_LINE_RE = re.compile(r"^version: (\d+\.\d+\.\d+)$", re.MULTILINE)

KNOWN_KEYS = ("version", "paths", "database")
PATHS_KEYS = ("migrations",)
DATABASE_KEYS = ("kind", "image", "schema_actual")
DATABASE_KINDS = ("sqlite", "postgresql")


class ConfigError(Exception):
    """設定ファイルが見つからない、または形が違う。メッセージは利用者に見せる文。"""


@dataclass(frozen=True)
class DatabaseConfig:
    """マイグレーションを適用するデータベース (設定の paths.migrations と database)。"""

    kind: str  # DATABASE_KINDS のどれか
    image: str | None  # kind が postgresql のときのコンテナのイメージ
    schema_actual: bool  # docs/system/schema-actual.md を作るか
    migrations: str  # マイグレーションの glob のパターン
    migrations_at: tuple[int, int]  # 設定ファイルの paths.migrations の値の位置 (行・列。1 から数える)


@dataclass(frozen=True)
class Config:
    path: Path
    version: str
    database: DatabaseConfig | None = None

    @property
    def root(self) -> Path:
        """リポジトリのルート (設定ファイルのディレクトリ .claude/ の親)。"""
        return self.path.parents[len(CONFIG_RELATIVE_PATH.parts) - 1]


def find_config(start: Path) -> Path:
    """start (ふつうはカレントディレクトリ) から親へ向かって設定ファイルを探す。"""
    start = start.resolve()
    for directory in (start, *start.parents):
        candidate = directory / CONFIG_RELATIVE_PATH
        if candidate.is_file():
            return candidate
    raise ConfigError(
        f"設定ファイル {CONFIG_RELATIVE_PATH} が見つからない ({start} から親のディレクトリへ向かって探した)"
    )


def load_config(path: Path) -> Config:
    """設定ファイルを読み、形を検査する。"""
    text = path.read_text(encoding="utf-8")
    try:
        data = yamlio.load(text)
    except YAMLError as e:
        raise ConfigError(f"{path} を YAML として読めない: {e}") from e
    if not isinstance(data, CommentedMap):
        raise ConfigError(f"{path} の全体は、キーと値のマッピングでなければならない")

    unknown = [str(key) for key in data if key not in KNOWN_KEYS]
    if unknown:
        raise ConfigError(
            f"{path} に知らないキーがある: {', '.join(unknown)} (このバージョンのツールが知っているキー: {', '.join(KNOWN_KEYS)})"
        )
    if "version" not in data:
        raise ConfigError(f"{path} にキー version が無い")

    version_lines = VERSION_LINE_RE.findall(text)
    if len(version_lines) != 1:
        raise ConfigError(
            f"{path} には「version: X.Y.Z」の形の行が 1 行だけ要る (見つかったのは {len(version_lines)} 行)。"
            "引用符を付けず、同じ行にコメントを書かない"
        )
    version = data["version"]
    if not isinstance(version, str) or version != version_lines[0]:
        raise ConfigError(f"{path} の version の値 {version!r} は、X.Y.Z の形の文字列でなければならない")
    return Config(path=path, version=version, database=_load_database(path, data))


def _mapping(path: Path, data: CommentedMap, key: str, known: tuple[str, ...]) -> CommentedMap | None:
    if key not in data:
        return None
    value = data[key]
    if not isinstance(value, CommentedMap):
        raise ConfigError(f"{path} の {key} は、キーと値のマッピングでなければならない")
    unknown = [str(k) for k in value if k not in known]
    if unknown:
        raise ConfigError(
            f"{path} の {key} に知らないキーがある: {', '.join(unknown)} "
            f"(このバージョンのツールが知っているキー: {', '.join(known)})"
        )
    return value


def _text(path: Path, mapping: CommentedMap, key: str, owner: str) -> str:
    value = mapping[key]
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{path} の {owner}.{key} は、空でない文字列でなければならない")
    return value


def _load_database(path: Path, data: CommentedMap) -> DatabaseConfig | None:
    paths = _mapping(path, data, "paths", PATHS_KEYS)
    database = _mapping(path, data, "database", DATABASE_KEYS)
    has_migrations = paths is not None and "migrations" in paths
    if not has_migrations and database is None:
        return None
    if not has_migrations:
        raise ConfigError(f"{path} に database があるが、paths.migrations が無い。どちらも書くか、どちらも書かない")
    if database is None:
        raise ConfigError(f"{path} に paths.migrations があるが、database が無い。どちらも書くか、どちらも書かない")
    migrations = _text(path, paths, "migrations", "paths")
    if migrations.startswith("/"):
        raise ConfigError(f"{path} の paths.migrations は、リポジトリのルートからの相対パスのパターンで書く: {migrations}")
    line, column = paths.lc.value("migrations")
    if "kind" not in database:
        raise ConfigError(f"{path} の database に kind が無い ({' か '.join(DATABASE_KINDS)} を書く)")
    kind = database["kind"]
    if kind not in DATABASE_KINDS:
        raise ConfigError(f"{path} の database.kind は {' か '.join(DATABASE_KINDS)} でなければならない: {kind}")
    image = None
    if kind == "postgresql":
        if "image" not in database:
            raise ConfigError(f"{path} の database に image が無い (kind が postgresql のときは、コンテナのイメージを書く。例 postgres:17)")
        image = _text(path, database, "image", "database")
    elif "image" in database:
        raise ConfigError(f"{path} の database.image は、kind が postgresql のときだけ書ける")
    schema_actual = False
    if "schema_actual" in database:
        if database["schema_actual"] is not True:
            raise ConfigError(f"{path} の database.schema_actual には true だけを書ける (作らないときは、キーを書かない)")
        schema_actual = True
    return DatabaseConfig(
        kind=kind, image=image, schema_actual=schema_actual, migrations=migrations, migrations_at=(line + 1, column + 1)
    )
