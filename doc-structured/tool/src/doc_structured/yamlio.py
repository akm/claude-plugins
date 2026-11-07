"""YAML の読み書き。

ruamel.yaml の round-trip モードを使い、コメント・記述の順序・空行・引用符を保ったまま書き換えられるようにする。
ツールが YAML を読むときも書くときも、必ずこのモジュールを通す (設定の値を 1 か所にするため)。
インデントは、マッピングが 2・シーケンスが 4 (項目の「- 」を含む)・「- 」の前の空白が 2 で、手書きの YAML の
よくある書き方 (親のキーから 2 文字下げて「- 」を書く) と同じにしている。
"""

import io
from typing import Any

from ruamel.yaml import YAML


def new_yaml() -> YAML:
    """ツールの設定にした YAML の読み書きの器を作る。"""
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    # 長い行を折り返さない (折り返すと、元の記述と差分が出るため)
    yaml.width = 1 << 16
    return yaml


def load(text: str) -> Any:
    """YAML の文字列を読む。形の誤りは ruamel.yaml の例外 (ruamel.yaml.YAMLError) のまま返す。"""
    return new_yaml().load(text)


def dump(data: Any) -> str:
    """load が返したデータを YAML の文字列にする。"""
    out = io.StringIO()
    new_yaml().dump(data, out)
    return out.getvalue()
