"""設定ファイル .claude/akm-claude-plugins/doc-structured/config.yaml の探索と読み込み。

ツールは起動時に設定の全体を YAML として読み、形が違えばエラー (例外 ConfigError) にする。
設定ファイルは、カレントディレクトリから親へ向かって探す (git がディレクトリ .git を探すのと同じ)。

設定の形 (決定の一覧の問 12 (4)):
  version   プロジェクトが使うツールのバージョン。「version: 1.2.3」の形の 1 行で書く。
            スクリプト bin/doc-structured がこの行だけを文字列の一致で取り出すので、引用符を付けたり、同じ行にコメントを
            書いたりしてはいけない。この制約もここで検査する
知らないキーがあればエラーにする (設定がツールより新しいときに、読み飛ばさずに気づけるように)。
paths と導入する範囲は、それを必要とする sub-issue で足す。
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

KNOWN_KEYS = ("version",)


class ConfigError(Exception):
    """設定ファイルが見つからない、または形が違う。メッセージは利用者に見せる文。"""


@dataclass(frozen=True)
class Config:
    path: Path
    version: str


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
    return Config(path=path, version=version)
