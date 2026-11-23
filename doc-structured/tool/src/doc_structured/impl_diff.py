"""設計 (YAML) と実装の差分の、対象 (スキーマ・画面のルート) に共通する部分。

対象ごとのモジュール (スキーマは schema_diff。画面のルートは sub-issue 12 で足す) が、設計と実装を「項目」と「正規化した行」に変え、
このモジュールが、決定の一覧の検査 j の結果の表で判定し、指示の行と unified diff を作る。

結果の表 (決定の一覧の問 12 の「検査 j」):
  YAML  実装  planned  結果
  ある  ある  なし     成功 (比べる項目が違えばエラー)
  ある  ある  あり     エラー「実装されたので planned を外す」
  ある  ない  あり     成功
  ある  ない  なし     エラー「planned を付けるか YAML から消す」
  ない  ある  -        エラー「YAML に足す (または実装を戻す)」
項目は子を持てる (テーブルのカラムなど)。子は、親が YAML にも実装にもあり、planned でないときだけ判定する
(親だけを報告するため)。決めた経緯は Issue #207 のコメントの 7・8・11・12。
"""

import difflib
from dataclasses import dataclass, field
from typing import Any

from .problems import Problem

CHECK = "j"
# 実装を読めない (データベースが無い) ときの、サブコマンドの終了コード。スキルは、差分がある (1) と区別して扱う
UNAVAILABLE_EXIT_CODE = 3
# unified diff の、変わった行の前後に表示する行の数
CONTEXT_LINES = 3


class ImplementationUnavailable(Exception):
    """実装を読むためのもの (データベースなど) が手元に無い。メッセージは、何が無いかと用意の仕方を書いた、利用者に見せる文。"""


@dataclass(frozen=True)
class Location:
    path: str  # リポジトリのルートからの相対パス
    line: int | None = None
    column: int | None = None


@dataclass
class Item:
    """設計と実装で比べる 1 つの項目 (テーブル・カラム・インデックス・画面など)。

    design と actual は、比べる項目の名前から正規化した値への対応。YAML に無ければ design が、実装に無ければ actual が None。
    """

    name: str  # メッセージに書く、種類と名前 (「カラム d-loans-t-loans-c-book_id」「テーブル fines」)
    design: dict[str, str] | None
    actual: dict[str, str] | None
    planned: bool = False
    location: Location | None = None  # YAML の定義の位置。YAML に無ければ None (報告は対象の既定の位置で行う)
    children: list["Item"] = field(default_factory=list)
    # 比べる項目の名前から、違うときの直し方への対応。無い項目は「YAML か実装を直す」
    fixes: dict[str, str] = field(default_factory=dict)
    # サブコマンド impl-diff-resolve に渡す ID (Issue #208 のコメントの 1)。target は、対象ごとのモジュールが書き換えに使う情報
    id: str = ""
    target: Any = None


# 件の場合 (決定の一覧の検査 j の結果の表で、エラーになる行。決めた経緯は Issue #208 のコメントの 2)
PLANNED_IMPLEMENTED = "planned_implemented"  # YAML にあり、実装にもあり、planned がある
MISSING_IMPLEMENTATION = "missing_implementation"  # YAML にあり、実装に無く、planned が無い
MISSING_DESIGN = "missing_design"  # YAML に無く、実装にある
MISMATCH = "mismatch"  # どちらにもあり、比べる項目が違う


def differences(items: list[Item]) -> list[tuple[Item, str]]:
    """結果の表でエラーになる項目と、その場合。子は、親が YAML にも実装にもあり、planned でないときだけ見る。"""
    found: list[tuple[Item, str]] = []

    def visit(item: Item) -> None:
        if item.design is None:
            if item.actual is not None:
                found.append((item, MISSING_DESIGN))
            return
        if item.actual is None:
            if not item.planned:
                found.append((item, MISSING_IMPLEMENTATION))
            return
        if item.planned:
            found.append((item, PLANNED_IMPLEMENTED))
            return
        if different_keys(item):
            found.append((item, MISMATCH))
        for child in item.children:
            visit(child)

    for item in items:
        visit(item)
    return found


def different_keys(item: Item) -> list[str]:
    """設計と実装で値が違う、比べる項目の名前。どちらかに無い項目は、空の値として比べる。"""
    assert item.design is not None and item.actual is not None
    keys = list(item.design) + [key for key in item.actual if key not in item.design]
    return [key for key in keys if item.design.get(key, "") != item.actual.get(key, "")]


def messages(item: Item, case: str, labels: dict[str, str]) -> list[str]:
    """件の指示の行のメッセージ。比べる項目が違うときは、違う項目ごとに 1 つ (labels の順)。"""
    if case == MISSING_DESIGN:
        return [f"{item.name} が実装にあるが YAML に無い。YAML に足す (または実装を戻す)"]
    if case == MISSING_IMPLEMENTATION:
        return [f"{item.name} が実装に無い。planned: true を付けるか、YAML から消す"]
    if case == PLANNED_IMPLEMENTED:
        return [f"{item.name} は実装されたので、planned を外す"]
    assert item.design is not None and item.actual is not None
    different = different_keys(item)
    result = []
    for key, label in labels.items():
        if key not in different:
            continue
        fix = item.fixes.get(key, "YAML か実装を直す")
        # 英字で始まる名前 (「URL パス」など) は、「の」との間に空白を入れる
        spaced = f" {label}" if label[:1].isascii() else label
        design = item.design.get(key, "")
        actual = item.actual.get(key, "")
        result.append(f"{item.name} の{spaced}が違う (設計 {_shown(design)}、実装 {_shown(actual)})。{fix}")
    return result


def judge(items: list[Item], labels: dict[str, str], fallback: Location) -> list[Problem]:
    """結果の表で項目を判定し、エラーを指示の行 (検査 j の問題) にする。

    labels は比べる項目の名前から、メッセージに書く名前 (「型」など) への対応。fallback は、YAML に無い項目を報告する位置。
    """
    problems: list[Problem] = []
    for item, case in differences(items):
        where = item.location or fallback
        for message in messages(item, case, labels):
            problems.append(Problem(CHECK, where.path, message, where.line, where.column))
    return problems


def _shown(value: str) -> str:
    return value if value else "無し"


def unified(design_lines: list[str], actual_lines: list[str], design_label: str, actual_label: str) -> str:
    """正規化した形どうしの unified diff。削除の行は設計にだけ、追加の行は実装にだけある行。差分が無ければ空の文字列。"""
    return "".join(
        line if line.endswith("\n") else line + "\n"
        for line in difflib.unified_diff(
            design_lines, actual_lines, fromfile=design_label, tofile=actual_label, n=CONTEXT_LINES, lineterm=""
        )
    )
