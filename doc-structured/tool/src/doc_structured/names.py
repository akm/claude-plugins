"""ID と、限定付きの名前。

ID は、種類の記号と名前 (snake_case) をハイフンで交互につなぎ、親から子の順に並べたもの
(例 d-loans-m-loan-a-status-v-on_loan)。ファイルの ID は、親の ID にファイルの種類の記号を足したもの
(例 d-loans-models)。ファイルの種類の記号は名前を取らない。
手書きのファイル (concept・design・problem) の下には、節 (記号 h) と子のファイル (記号 f) の ID を作る
(例 d-loans-concept-h-return_deadline・d-push-design-f-device_operations)。子のファイルの下には節だけを作る。

限定付きの名前は、親から順に「種類 + 名前」を「の」でつないだもの。ユーザーレベルの種類は日本語名をかぎ括弧で、
開発レベルの種類は英語名をコードの書式で書く。名前の形の表の SSOT はプラグインの規則の文書
(ファイル doc-structured/rules/doc-structured-docs.md)。このモジュールの表 KINDS と FILE_KINDS が規則の文書の表と
同じであることは、テスト tests/test_rules_docs.py が検査する。
"""

import re
from dataclasses import dataclass

# 名前 (英語名) の形。英小文字で始まり、英小文字・数字を 1 つの「_」で区切る
NAME_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")


@dataclass(frozen=True)
class Kind:
    """名前を持つ種類。"""

    symbol: str
    label: str  # 種類の名前 (限定付きの名前と文書に書く)
    user_level: bool  # True なら日本語名をかぎ括弧で、False なら英語名をコードの書式で書く
    parents: tuple[str, ...]  # 親になれる種類の記号。空ならいちばん上の種類


# この版のツールが扱う種類。後の sub-issue で種類を足す
KINDS: dict[str, Kind] = {
    k.symbol: k
    for k in (
        Kind("d", "ドメイン", False, ()),
        Kind("m", "モデル", True, ("d",)),
        Kind("a", "属性", True, ("m",)),
        Kind("v", "値", True, ("a",)),
        Kind("ut", "未分類のアプリケーション用語", True, ("d",)),
    )
}

# 生成するファイルの種類の記号と、そのファイル名。親はドメイン
FILE_KINDS: dict[str, str] = {
    "models": "models.md",
    "terms": "terms.md",
    "unclassified_app_terms": "unclassified_app_terms.md",
}
# 手書きのファイルの種類の記号と、そのファイル名。親はドメイン。ドメインの README.md の表に、この順に載せる
HANDWRITTEN_FILE_KINDS: dict[str, str] = {
    "concept": "concept.md",
    "problem": "problem.md",
    "design": "design.md",
}
FILE_KIND_LABEL = "ファイル"

# 種類の名前の略称。本文の最初の箇所では、略称で書いた形も書ける (完全な名前には正式名称を書く)
ABBREVIATIONS: dict[str, str] = {"ut": "未分類の用語"}

# 手書きのファイルの節。名前は書く人が決める snake_case で、限定付きの名前には見出しの文を書く
SECTION = Kind("h", "節", True, ())
# 手書きのファイルの子のファイル (100 行を超えたファイルを分けた先)。限定付きの名前には、ドメインのディレクトリからのパスを書く
CHILD_FILE_SYMBOL = "f"


class IdError(ValueError):
    """ID の形が違う。メッセージは利用者に見せる文。"""


@dataclass(frozen=True)
class Part:
    """ID の 1 つの部分。name が None なら、ファイルの種類の記号。"""

    symbol: str
    name: str | None


def is_name(text: str) -> bool:
    return bool(NAME_RE.match(text))


def build_id(parts: list[Part]) -> str:
    tokens: list[str] = []
    for part in parts:
        tokens.append(part.symbol)
        if part.name is not None:
            tokens.append(part.name)
    return "-".join(tokens)


def parse_id(text: str) -> list[Part]:
    """ID を部分に分ける。種類の記号・名前の形・親子の組み合わせが違えば IdError。"""
    tokens = text.split("-")
    parts: list[Part] = []
    i = 0
    while i < len(tokens):
        symbol = tokens[i]
        parent = parts[-1].symbol if parts else None
        if symbol in KINDS or symbol in (SECTION.symbol, CHILD_FILE_SYMBOL):
            if symbol in KINDS:
                kind = KINDS[symbol]
                allowed = (parent is None and not kind.parents) or (parent is not None and parent in kind.parents)
            elif symbol == SECTION.symbol:
                allowed = parent in HANDWRITTEN_FILE_KINDS or parent == CHILD_FILE_SYMBOL
            else:
                allowed = parent in HANDWRITTEN_FILE_KINDS
            if not allowed:
                raise IdError(f"ID {text} の {symbol} は、{parent or '先頭'} の後に書けない")
            if i + 1 >= len(tokens):
                raise IdError(f"ID {text} の {symbol} の後に名前が無い")
            name = tokens[i + 1]
            if not is_name(name):
                raise IdError(f"ID {text} の名前 {name} が snake_case でない")
            parts.append(Part(symbol, name))
            i += 2
        elif symbol in FILE_KINDS:
            if parent != "d" or i + 1 != len(tokens):
                raise IdError(f"ID {text} のファイルの種類 {symbol} は、ドメインの直後の最後にだけ書ける")
            parts.append(Part(symbol, None))
            i += 1
        elif symbol in HANDWRITTEN_FILE_KINDS:
            if parent != "d":
                raise IdError(f"ID {text} のファイルの種類 {symbol} は、ドメインの直後にだけ書ける")
            parts.append(Part(symbol, None))
            i += 1
        else:
            raise IdError(f"ID {text} に知らない種類の記号 {symbol} がある")
    if not parts:
        raise IdError(f"ID {text!r} が空")
    return parts


def kind_of(text: str) -> str:
    """ID の最後の種類の記号。"""
    return parse_id(text)[-1].symbol


def format_part(symbol: str, display: str, abbreviated: bool = False) -> str:
    """「種類 + 名前」の 1 つ。display は、ユーザーレベルなら日本語名、開発レベルなら英語名、ファイルならファイル名、
    子のファイルならドメインのディレクトリからのパス、節なら見出しの文。
    abbreviated が True なら、種類の名前を略称 (ABBREVIATIONS) で書く。略称の無い種類は、正式名称で書く。"""
    if symbol in FILE_KINDS or symbol in HANDWRITTEN_FILE_KINDS or symbol == CHILD_FILE_SYMBOL:
        return f"{FILE_KIND_LABEL} `{display}`"
    if symbol == SECTION.symbol:
        return f"{SECTION.label}「{display}」"
    kind = KINDS[symbol]
    label = ABBREVIATIONS.get(symbol, kind.label) if abbreviated else kind.label
    if kind.user_level:
        return f"{label}「{display}」"
    return f"{label} `{display}`"


def join_parts(formatted: list[str]) -> str:
    """「種類 + 名前」を親から順に「の」でつなぐ。コードの書式の後には空白を 1 つ入れる (「ドメイン `loans` のモデル」)。"""
    result = ""
    for i, text in enumerate(formatted):
        if i > 0:
            result += " の" if result.endswith("`") else "の"
        result += text
    return result
