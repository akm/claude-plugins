"""検査 b (文書のリンクとアンカー)。

ドメインのディレクトリの下の手書きの Markdown について、次のことを検査する。形式の SSOT はプラグインの規則の文書
(ファイル doc-structured/rules/doc-structured-docs.md)。
  - 手書きのファイルの名前と場所 (モジュール documents が報告する)
  - 先頭のファイルの ID のアンカーと、その次の「#」の見出し
  - 節のアンカーの ID の形 (<ファイルの ID>-h-<名前>) と、その次の「##」から「######」の見出し。アンカーを付けた見出しにリンクが無い
  - 同じ ID のアンカーが 2 つ無い
  - リンクを reference-style ([ラベル]・[文][ラベル]) だけで書く ([文](URL)・<URL>・文中の URL・[ラベル][] が無い)
  - 定義の無いラベル・使われていない定義の行・同じラベルの定義の行が無い
  - 定義の行を末尾のまとまりに書き、段落の一部になっていない
  - 定義の行の href が、ID の形で、参照先のアンカーのあるファイルを指し、title が参照先の完全な名前と同じ
    (外部の URL の定義の行は、title を検査しない)
画像は規則の対象にしないので、本文のリンクで使われず、reference-style の画像だけが使うラベルの定義の行は、
href・title・使われていないことを検査しない。
"""

import posixpath
from dataclasses import dataclass

from . import markdown, names
from .documents import HandwrittenFile, Index, Target, section_name
from .names import IdError
from .problems import Problem

EXTERNAL_PREFIXES = ("http://", "https://")


def is_external(destination: str) -> bool:
    return strip_angle(destination).startswith(EXTERNAL_PREFIXES)


def strip_angle(destination: str) -> str:
    if destination.startswith("<") and destination.endswith(">"):
        return destination[1:-1]
    return destination


@dataclass(frozen=True)
class Resolved:
    """内部の定義の行の参照先。target が None なら、message が誤りの説明。"""

    target: Target | None
    message: str = ""


def resolve(handwritten: HandwrittenFile, definition: markdown.Definition, index: Index) -> Resolved:
    """内部の定義の行 (外部の URL でないもの) の href から、参照先を求める。"""
    destination = strip_angle(definition.destination)
    path, sep, fragment = destination.partition("#")
    if not sep or not fragment:
        return Resolved(None, f"href {destination} が ID のアンカー (#<ID>) を指していない")
    try:
        names.parse_id(fragment)
    except IdError as e:
        return Resolved(None, f"href の ID の形が違う: {e}")
    target = index.targets.get(fragment)
    if target is None:
        return Resolved(None, f"href の参照先 {fragment} のアンカーが無い")
    resolved = handwritten.path if not path else posixpath.normpath(posixpath.join(posixpath.dirname(handwritten.path), path))
    if resolved != target.path:
        return Resolved(None, f"href が、参照先 {fragment} のアンカーのあるファイルを指していない (正しい href は {target.href(handwritten.path)})")
    return Resolved(target)


def definition_line(label: str, target: Target, from_path: str, quote: str = '"') -> str:
    """参照先 target を指す定義の行。"""
    title = markdown.escape_title(target.full_name(), quote)
    return f"[{label}]: {target.href(from_path)} {quote}{title}{markdown.closing_quote(quote)}"


def image_only_labels(document: markdown.Document) -> set[str]:
    """本文のリンクで使われず、reference-style の画像だけが使うラベル (比べる形)。"""
    used = {markdown.normalize_label(r.label) for r in document.references}
    return {markdown.normalize_label(label) for label in document.image_labels} - used


def candidate_text(targets: list[Target]) -> str:
    return "、".join(f"{t.id} ({t.full_name()})" for t in targets)


class _FileChecker:
    def __init__(self, handwritten: HandwrittenFile, index: Index):
        self.file = handwritten
        self.document = handwritten.document
        self.index = index
        self.problems: list[Problem] = []

    def problem(self, message: str, line: int | None = None, column: int | None = None) -> None:
        self.problems.append(Problem("b", self.file.path, message, line, column))

    def check(self) -> list[Problem]:
        self.check_anchors()
        self.check_link_forms()
        self.check_definitions()
        return self.problems

    def check_anchors(self) -> None:
        document = self.document
        file_id = self.file.id
        first = document.first_nonblank()
        file_anchor = next((a for a in document.anchors if a.line == first), None)
        if file_anchor is None:
            self.problem(f'先頭の行に、ファイルの ID のアンカー <a name="{file_id}"></a> が無い', first or 1, 1)
        elif file_anchor.name != file_id:
            self.problem(
                f"先頭のアンカーの ID {file_anchor.name} が、ファイルの ID {file_id} と違う",
                file_anchor.line, file_anchor.column,
            )
        if file_anchor is not None:
            following = document.next_nonblank(file_anchor.line)
            heading = document.heading_at(following) if following else None
            if heading is None or not heading.atx or heading.level != 1:
                self.problem("ファイルの ID のアンカーの次の行に、「#」の見出しが無い", file_anchor.line, file_anchor.column)
        for anchor in document.anchors:
            if anchor is file_anchor:
                continue
            if section_name(file_id, anchor.name) is None:
                self.problem(
                    f"節のアンカーの ID {anchor.name} は、{file_id}-{names.SECTION.symbol}-<名前> の形にする (名前は snake_case)",
                    anchor.line, anchor.column,
                )
                continue
            following = document.next_nonblank(anchor.line)
            heading = document.heading_at(following) if following else None
            if heading is None or not heading.atx or heading.level < 2:
                self.problem("節のアンカーの次の行に、「##」から「######」の見出しが無い", anchor.line, anchor.column)
                continue
            linked = [r for r in document.references if r.line == heading.line]
            linked += [r for r in document.inline_links if r.line == heading.line]
            if linked:
                self.problem(
                    "アンカーを付けた見出しにリンクを書かない (見出しの文は、参照する定義の行の title になるため)",
                    heading.line, linked[0].column,
                )
        for anchor in document.anchors:
            found = self.index.anchors.get(anchor.name, [])
            if len(found) > 1:
                others = [f"{path}:{a.line}" for path, a in found if not (path == self.file.path and a.line == anchor.line)]
                self.problem(f"同じ ID {anchor.name} のアンカーが {'、'.join(others)} にもある", anchor.line, anchor.column)

    def check_link_forms(self) -> None:
        for link in self.document.inline_links:
            self.problem(
                "[文](URL) の形でリンクを書かない。reference-style ([ラベル] か [文][ラベル]) と定義の行で書く",
                link.line, link.column,
            )
        for url in self.document.urls:
            if url.form == "autolink":
                message = f"<{url.url}> の形でリンクを書かない。reference-style ([ラベル] か [文][ラベル]) と定義の行で書く"
            else:
                message = (
                    f"文中に URL {url.url} をそのまま書かない。reference-style ([ラベル] か [文][ラベル]) と定義の行で書く"
                    "。リンクにしないときは、インラインコードにする"
                )
            self.problem(message, url.line, url.column)
        for reference in self.document.references:
            if reference.form == "collapsed":
                self.problem(
                    f"[{reference.text}][] の形で書かない。[{reference.text}] と書く", reference.line, reference.column
                )

    def check_definitions(self) -> None:
        document = self.document
        defined: dict[str, markdown.Definition] = {}
        images = image_only_labels(document)
        previous_in_paragraph = -1
        for definition in document.definitions:
            key = markdown.normalize_label(definition.label)
            where = (definition.line, definition.column)
            if definition.in_paragraph:
                if previous_in_paragraph != definition.line - 1:
                    self.problem("直前の行と同じ段落になり、定義の行として読まれない。前に空行を入れる", *where)
                previous_in_paragraph = definition.line
            elif definition.line <= document.body_end:
                self.problem("定義の行は、ファイルの末尾のまとまりに書く", *where)
            if key in defined:
                self.problem(f"ラベル {definition.label} の定義の行は、{defined[key].line} 行目にもある", *where)
                continue
            defined[key] = definition
            if key not in images:
                self.check_definition_target(definition)
        used: set[str] = set()
        for reference in document.references:
            key = markdown.normalize_label(reference.label)
            used.add(key)
            if reference.form == "collapsed" or key in defined:
                continue
            candidates = self.index.candidates(reference.label)
            if candidates:
                hint = f"。候補: {candidate_text(candidates)}"
            else:
                hint = "。参照先の候補は無い"
            self.problem(f"ラベル {reference.label} の定義の行が無い{hint}", reference.label_line, reference.label_column)
        for key, definition in defined.items():
            if key not in used and key not in images:
                self.problem(f"ラベル {definition.label} の定義の行が、本文で使われていない", definition.line, definition.column)

    def check_definition_target(self, definition: markdown.Definition) -> None:
        if is_external(definition.destination):
            return
        where = (definition.line, definition.column)
        resolved = resolve(self.file, definition, self.index)
        if resolved.target is None:
            self.problem(resolved.message, *where)
            return
        full_name = resolved.target.full_name()
        if definition.title is None:
            self.problem(f"定義の行に title が無い。参照先の完全な名前「{full_name}」を書く", *where)
        elif definition.title_text != full_name:
            self.problem(f"定義の行の title が、参照先の完全な名前「{full_name}」と違う", *where)


def check_links(index: Index) -> list[Problem]:
    """検査 b: 手書きの Markdown のリンクとアンカー (手書きのファイルの名前と場所は、モジュール documents が報告する)。"""
    problems: list[Problem] = []
    for handwritten in index.files:
        problems += _FileChecker(handwritten, index).check()
    return problems
