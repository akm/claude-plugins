"""手書きの Markdown の参照の読み取り。

検査 i (Markdown のリンク)・検査 c-2・サブコマンド refs が使う。手書きのファイルごとに、本文でラベルを使った箇所から、
参照している ID と、その箇所の行が属する ID を求める。決めた経緯は Issue #198 のコメント
(https://github.com/akm/claude-plugins/issues/198#issuecomment-6853737355)。要点:
  - 参照している ID は、同じファイルの定義の行の href の「#」の後ろ。参照先のアンカーがあるかどうかは見ない
    (アンカーが無いことは検査 b が報告する。refs は、アンカーが無い ID も探す)
  - 外部の URL (http://・https://) を指す定義の行と、定義の行の無いラベルは、参照にしない
  - 行が属する ID は、その行を含む最も内側のアンカー付きの節の ID。節の範囲は、アンカーを付けた見出しから、
    同じ階層か上の階層の次の見出しの手前まで。どのアンカー付きの節にも入らない行は、ファイルの ID に属する
  - 定義の行だけがあって本文で使われていないラベルも、定義の行の位置の参照として返す (in_body が False)
"""

from dataclasses import dataclass

from . import markdown
from .documents import HandwrittenFile, Index, section_name
from .links import is_external, strip_angle


@dataclass(frozen=True)
class Reference:
    file: HandwrittenFile
    line: int  # 本文の参照なら最初の「[」の行、定義の行だけなら定義の行
    column: int
    written: str  # 書いたとおりの形 ([ラベル]・[文][ラベル]・[ラベル][])
    target_id: str  # 定義の行の href の「#」の後ろ
    definition: markdown.Definition
    owner_id: str  # この行が属する ID
    in_body: bool  # 本文の参照なら True。定義の行だけがあって本文で使われていないラベルなら False

    @property
    def path(self) -> str:
        return self.file.path


@dataclass(frozen=True)
class _Section:
    id: str
    start: int  # 見出しの行
    end: int  # 範囲の最後の行 (この行を含む)


def _sections(handwritten: HandwrittenFile) -> list[_Section]:
    """アンカー付きの節と、その行の範囲。"""
    document = handwritten.document
    headings = sorted(document.headings, key=lambda h: h.line)
    sections: list[_Section] = []
    for anchor in document.anchors:
        if section_name(handwritten.id, anchor.name) is None:
            continue
        following = document.next_nonblank(anchor.line)
        heading = document.heading_at(following) if following else None
        if heading is None or not heading.atx or heading.level < 2:
            continue  # 節のアンカーにならない (検査 b が報告する)
        end = len(document.lines)
        for other in headings:
            if other.line > heading.line and other.level <= heading.level:
                end = other.line - 1
                break
        sections.append(_Section(anchor.name, heading.line, end))
    return sections


def owner_of(handwritten: HandwrittenFile, line: int, sections: list[_Section] | None = None) -> str:
    """line (1 から数える) が属する ID。"""
    if sections is None:
        sections = _sections(handwritten)
    containing = [s for s in sections if s.start <= line <= s.end]
    if not containing:
        return handwritten.id
    return max(containing, key=lambda s: s.start).id


def _written(reference: markdown.Reference) -> str:
    if reference.form == "full":
        return f"[{reference.text}][{reference.label}]"
    if reference.form == "collapsed":
        return f"[{reference.text}][]"
    return f"[{reference.text}]"


def file_references(handwritten: HandwrittenFile) -> list[Reference]:
    """1 つの手書きのファイルの参照。本文の参照を行と列の順に、その後に本文で使われていない定義の行を並べる。"""
    document = handwritten.document
    sections = _sections(handwritten)
    definitions: dict[str, markdown.Definition] = {}
    for definition in document.definitions:
        definitions.setdefault(markdown.normalize_label(definition.label), definition)

    def target_of(definition: markdown.Definition) -> str | None:
        if is_external(definition.destination):
            return None
        _, sep, fragment = strip_angle(definition.destination).partition("#")
        return fragment if sep and fragment else None

    found: list[Reference] = []
    used: set[str] = set()
    for reference in document.references:
        key = markdown.normalize_label(reference.label)
        used.add(key)
        definition = definitions.get(key)
        if definition is None:
            continue
        target = target_of(definition)
        if target is None:
            continue
        found.append(
            Reference(
                handwritten, reference.line, reference.column, _written(reference), target, definition,
                owner_of(handwritten, reference.line, sections), True,
            )
        )
    images = {markdown.normalize_label(label) for label in document.image_labels}
    for key, definition in definitions.items():
        if key in used or key in images:
            continue
        target = target_of(definition)
        if target is None:
            continue
        found.append(
            Reference(
                handwritten, definition.line, definition.column, f"[{definition.label}]", target, definition,
                owner_of(handwritten, definition.line, sections), False,
            )
        )
    return found


def all_references(index: Index) -> list[Reference]:
    """すべての手書きのファイルの参照。パスの文字コードの順。"""
    found: list[Reference] = []
    for handwritten in sorted(index.files, key=lambda f: f.path):
        found += file_references(handwritten)
    return found
