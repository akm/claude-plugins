"""サブコマンド links-fix (手書きの Markdown の定義の行とファイルのアンカーを直す)。

直し方が 1 通りに決まるものだけを書き換え、判断の要るものは「パス:行:列: メッセージ」の形で報告する。本文の文は変えない。
  - 先頭にファイルの ID のアンカーが無ければ、足す
  - 定義の無いラベルのうち、参照先の候補が 1 件のものに、定義の行を足す (本文で最初に使った順に、末尾のまとまりの後ろへ)
  - 定義の行の title が参照先の完全な名前と違えば、書き換える (引用符の種類は変えない。title が無ければ「"」で足す)
  - 使われていない定義の行を消す。ただし、同じファイルに定義の無いラベルが残るときは、消さずに報告する
    (ラベルの書き間違いのことがあるため)
  - 本文の途中の定義の行と、段落の一部になった定義の行を、末尾のまとまりに移す
  - 同じラベルの定義の行のうち、参照先が同じものは後の行を消す。参照先が違えば報告する
reference-style の画像だけが使うラベルの定義の行は、画像が規則の対象でないので、消さず書き換えない (末尾のまとまりへは移す)。
判断の要るもの: 参照先の候補が 0 件か複数のラベル・消さなかった使われていない定義の行・参照先の違う同じラベルの定義の行。
利用者が選んだ参照先は、Choice (オプション --choose) で受け取り、定義の行の href と title はツールが作る。
"""

from dataclasses import dataclass, field
from pathlib import Path

from . import markdown
from .documents import HandwrittenFile, Index
from .links import candidate_text, definition_line, image_only_labels, is_external, resolve, strip_angle


@dataclass(frozen=True)
class Choice:
    """利用者が選んだ参照先。value は参照先の ID か、外部の URL (http:// か https:// で始まるもの)。"""

    path: str  # リポジトリのルートからの相対パス
    label: str
    value: str


class ChoiceError(ValueError):
    """--choose の値が使えない。メッセージは利用者に見せる文。"""


@dataclass(frozen=True)
class Report:
    """判断の要るもの。"""

    path: str
    line: int
    column: int
    message: str

    def format(self) -> str:
        return f"{self.path}:{self.line}:{self.column}: {self.message}"


@dataclass
class FixResult:
    changed: list[str] = field(default_factory=list)  # 書き換えたファイル
    reports: list[Report] = field(default_factory=list)


def _label_text(label: str) -> str:
    """定義の行に書くラベル。本文のラベルが改行をまたぐときは、空白 1 つにする。"""
    return " ".join(label.split())


def _definition_key(handwritten: HandwrittenFile, definition: markdown.Definition, index: Index) -> str | None:
    """定義の行の参照先を比べる値。外部の URL ならその URL、内部なら参照先の ID。求められなければ None。"""
    if is_external(definition.destination):
        return strip_angle(definition.destination)
    resolved = resolve(handwritten, definition, index)
    return resolved.target.id if resolved.target else None


def _choice_line(choice: Choice, label: str, handwritten: HandwrittenFile, index: Index) -> str:
    if choice.value.startswith(("http://", "https://")):
        return f"[{label}]: {choice.value}"
    target = index.targets.get(choice.value)
    if target is None:
        raise ChoiceError(f"--choose の参照先 {choice.value} が無い (参照先の ID か、http:// か https:// で始まる URL を渡す)")
    return definition_line(label, target, handwritten.path)


class _FileFixer:
    def __init__(self, handwritten: HandwrittenFile, index: Index, choices: list[Choice]):
        self.file = handwritten
        self.document = handwritten.document
        self.index = index
        self.choices = choices
        self.reports: list[Report] = []

    def report(self, line: int, column: int, message: str) -> None:
        self.reports.append(Report(self.file.path, line, column, message))

    def fix(self) -> list[str] | None:
        """直した行を返す。直すものが無ければ None。"""
        document = self.document
        lines = list(document.lines)
        # 定義の行の番号 (1 から数える) から、その行に書く内容への対応。None なら消す
        replaced: dict[int, str | None] = {}
        used_order: list[tuple[str, markdown.Reference]] = []
        seen_used: set[str] = set()
        for reference in document.references:
            key = markdown.normalize_label(reference.label)
            if reference.form != "collapsed" and key not in seen_used:
                seen_used.add(key)
                used_order.append((key, reference))

        images = image_only_labels(document)
        chosen: dict[str, str] = {}
        for choice in self.choices:
            key = markdown.normalize_label(choice.label)
            reference = next((r for k, r in used_order if k == key), None)
            if reference is None:
                raise ChoiceError(f"--choose のラベル {choice.label} は、{self.file.path} の本文で使われていない")
            chosen[key] = _choice_line(choice, _label_text(reference.label), self.file, self.index)

        # 同じラベルの定義の行
        first: dict[str, markdown.Definition] = {}
        for definition in document.definitions:
            key = markdown.normalize_label(definition.label)
            if key in chosen:
                # 選んだ参照先で置き換えるので、同じラベルの今の定義の行はすべて消す
                replaced[definition.line] = None
                continue
            if key not in first:
                first[key] = definition
                continue
            earlier = first[key]
            this_key = _definition_key(self.file, definition, self.index)
            if this_key is not None and this_key == _definition_key(self.file, earlier, self.index):
                replaced[definition.line] = None
            else:
                self.report(
                    definition.line, definition.column,
                    f"ラベル {definition.label} の定義の行が {earlier.line} 行目にもあり、参照先が違う"
                    f" ({strip_angle(earlier.destination)} と {strip_angle(definition.destination)})。"
                    "--choose で参照先を 1 つ選ぶ",
                )

        # title の書き換え
        for key, definition in first.items():
            if key in images or is_external(definition.destination):
                continue
            resolved = resolve(self.file, definition, self.index)
            if resolved.target is None:
                continue
            full_name = resolved.target.full_name()
            if definition.title_text == full_name:
                continue
            line = lines[definition.line - 1]
            quote = definition.quote or '"'
            head = line[: definition.title_start].rstrip()
            replaced[definition.line] = f"{head} {quote}{markdown.escape_title(full_name, quote)}{markdown.closing_quote(quote)}"

        # 定義の無いラベル
        added: list[str] = []
        unresolved = False
        for key, reference in used_order:
            if key in chosen:
                added.append(chosen[key])
                continue
            if key in first:
                continue
            candidates = self.index.candidates(reference.label)
            label = _label_text(reference.label)
            if len(candidates) == 1:
                added.append(definition_line(label, candidates[0], self.file.path))
                continue
            unresolved = True
            where = (reference.label_line, reference.label_column)
            if candidates:
                self.report(
                    *where,
                    f"ラベル {label} の参照先の候補が {len(candidates)} 件ある: {candidate_text(candidates)}。--choose で選ぶ",
                )
            else:
                self.report(*where, f"ラベル {label} の参照先の候補が無い。参照先の ID か外部の URL を --choose で渡す")

        # 使われていない定義の行
        for key, definition in first.items():
            if key in seen_used or key in chosen or key in images:
                continue
            if unresolved:
                self.report(
                    definition.line, definition.column,
                    f"ラベル {definition.label} の定義の行が本文で使われていないが、定義の無いラベルが残っているので消さなかった"
                    " (ラベルの書き間違いのことがある)",
                )
            else:
                replaced[definition.line] = None

        moved = [d.line for d in document.definitions if d.in_paragraph or d.line <= document.body_end]
        needs_anchor = self.needs_file_anchor()
        if not replaced and not added and not moved and not needs_anchor:
            return None
        return self.rebuild(lines, replaced, added, needs_anchor)

    def needs_file_anchor(self) -> bool:
        first = self.document.first_nonblank()
        anchor = next((a for a in self.document.anchors if a.line == first), None)
        return anchor is None or anchor.name != self.file.id

    def rebuild(self, lines: list[str], replaced: dict[int, str | None], added: list[str], needs_anchor: bool) -> list[str]:
        """本文の途中の定義の行を末尾のまとまりへ移し、末尾のまとまりを「本文 + 空行 + 定義の行」の形に組み直す
        (段落の一部になった定義の行は、前に空行が入るので、定義の行として読まれるようになる)。"""
        document = self.document
        definition_lines = document.definition_lines()
        body: list[str] = []
        moved_lines: list[str] = []
        for number in range(1, document.body_end + 1):
            line = lines[number - 1]
            if number in definition_lines:
                kept = replaced.get(number, line)
                if kept is not None:
                    moved_lines.append(kept)
                # 消した定義の行の前後が両方とも空行なら、空行を 1 つにする
                if body and not body[-1].strip() and (number == document.body_end or not lines[number].strip()):
                    body.pop()
                continue
            body.append(line)
        trailing: list[str] = []
        for number in range(document.body_end + 1, len(lines) + 1):
            line = lines[number - 1]
            if number in definition_lines:
                kept = replaced.get(number, line)
                if kept is None:
                    continue
                trailing.append(kept)
            elif trailing and trailing[-1].strip():
                trailing.append("")  # 定義の行の間の空行を 1 つだけ残す
        while trailing and not trailing[-1].strip():
            trailing.pop()
        block = moved_lines + trailing + added
        while body and not body[-1].strip():
            body.pop()
        if needs_anchor:
            start = 0
            while start < len(body) and not body[start].strip():
                start += 1
            body = [f'<a name="{self.file.id}"></a>', ""] + body[start:]
        result = body
        if block:
            result = body + [""] + block
        return result


def fix_files(root: Path, index: Index, paths: list[str] | None, choices: list[Choice]) -> FixResult:
    """paths (リポジトリのルートからの相対パス) の手書きの Markdown を直す。paths が None なら、すべての手書きの Markdown。

    --choose の値が使えなければ、何も書かずに ChoiceError を送出する。
    """
    targets = index.files if paths is None else [f for f in index.files if f.path in paths]
    for choice in choices:
        if index.file(choice.path) is None:
            raise ChoiceError(f"--choose のファイル {choice.path} は、手書きの Markdown でない")
        handwritten = index.file(choice.path)
        if handwritten not in targets:
            targets.append(handwritten)
    result = FixResult()
    outputs: dict[str, list[str]] = {}
    for handwritten in targets:
        fixer = _FileFixer(handwritten, index, [c for c in choices if c.path == handwritten.path])
        fixed = fixer.fix()
        result.reports += fixer.reports
        if fixed is not None:
            outputs[handwritten.path] = fixed
    for path, fixed in outputs.items():
        target = root / path
        raw = target.read_bytes()
        newline = "\r\n" if b"\r\n" in raw else "\n"
        bom = "﻿" if raw.startswith(b"\xef\xbb\xbf") else ""
        text = bom + newline.join(fixed) + newline
        if text.encode("utf-8") != raw:
            target.write_bytes(text.encode("utf-8"))
            result.changed.append(path)
    result.reports.sort(key=lambda r: (r.path, r.line, r.column))
    return result


def unknown_paths(index: Index, paths: list[str]) -> list[str]:
    return [p for p in paths if index.file(p) is None]

