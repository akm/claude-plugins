"""サブコマンド refs (ある ID と、その子孫の ID を参照している箇所)。

決めた経緯は Issue #198 のコメントの 4 と 5。要点:
  - 探すのは、検査 b と同じ手書きのファイル。生成したファイルは探さず、記録は読まないので出ない
  - 参照は、定義の行の href の ID で探す。参照先のアンカーが無い ID も探し、アンカーが無いことを伝える
  - 子孫の ID (渡した ID の後ろに「-<記号>-<名前>」が 1 つ以上続いた ID) を参照している箇所も出す。
    子孫かどうかは、ID を部分に分けて比べる (d-loans-m-loan_item は d-loans-m-loan の子孫ではない)
  - 本文でラベルを使った箇所ごとに 1 行「パス:行:列: <参照している ID> <書いたとおりのリンク> (<行が属する ID>)」。
    定義の行だけがあって本文で使われていないラベルは、定義の行の位置に 1 行。順序はパスの文字コードの順、ファイルの中は行と列の順
"""

from dataclasses import dataclass

from . import names
from .documents import Index
from .references import Reference, all_references

DEFINITION_ONLY = "定義の行だけで、本文で使われていない"


@dataclass
class RefsResult:
    id: str
    anchor_exists: bool
    references: list[Reference]

    def lines(self) -> list[str]:
        found = []
        for reference in self.references:
            where = reference.owner_id if reference.in_body else DEFINITION_ONLY
            found.append(f"{reference.path}:{reference.line}:{reference.column}: {reference.target_id} {reference.written} ({where})")
        if not self.anchor_exists:
            found.append(f"ID {self.id} のアンカーは無い (定義の行の href の ID で探した)")
        if self.references:
            files = len({r.path for r in self.references})
            found.append(f"{self.id} とその子孫を参照している箇所: {len(self.references)} 件 ({files} ファイル)")
        else:
            found.append(f"{self.id} とその子孫を参照している箇所は無い")
        return found


def _parts(text: str) -> list[names.Part] | None:
    try:
        return names.parse_id(text)
    except names.IdError:
        return None


def find_refs(index: Index, target_id: str) -> RefsResult:
    """target_id とその子孫の ID を参照している箇所。target_id の形が違えば names.IdError。"""
    given = names.parse_id(target_id)
    found = []
    for reference in all_references(index):
        parts = _parts(reference.target_id)
        if parts is not None and parts[: len(given)] == given:
            found.append(reference)
    found.sort(key=lambda r: (r.path, r.line, r.column))
    return RefsResult(target_id, target_id in index.anchors, found)
