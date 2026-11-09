"""手書きの Markdown と、リンクの参照先の一覧。

ドメインのディレクトリの下の手書きの Markdown を見つけ、すべての Markdown (生成したファイルを含む) のアンカーから、
リンクの参照先の一覧を作る。形式の SSOT はプラグインの規則の文書 (ファイル doc-structured/rules/doc-structured-docs.md と
doc-structured/rules/doc-structured-domains.md)。要点:
  - 手書きのファイルは、ドメインのディレクトリの直下の concept.md・problem.md・design.md と、
    その種類と同じ名前のサブディレクトリの <名前>.md (子のファイル。1 階層だけ)
  - ほかの名前・場所の .md は、検査 b のエラーにする
  - 参照先のアンカーは、今のファイルの内容から読む (生成したファイルが古いことは検査 a が報告する)
  - 参照先のラベルの候補は、ID・名前・限定付きの名前 (「種類 + 名前」に、親を直近から 0 個以上足した形)
"""

import posixpath
from dataclasses import dataclass, field
from pathlib import Path

from . import generated_header, markdown, names
from .domains import DOMAINS_DIR, Domain, Project, rel
from .names import Part
from .problems import Problem

README = "README.md"
# ドメインのディレクトリの直下の、生成するファイルの名前
GENERATED_NAMES = {README, *names.FILE_KINDS.values()}


@dataclass
class HandwrittenFile:
    """ドメインのディレクトリの下の、手書きのファイル。"""

    path: str  # リポジトリのルートからの相対パス
    domain: Domain
    symbol: str  # 手書きのファイルの種類の記号 (concept・problem・design)
    child: str | None  # 子のファイルなら、その名前
    document: markdown.Document

    @property
    def id(self) -> str:
        parts = [Part("d", self.domain.name), Part(self.symbol, None)]
        if self.child is not None:
            parts.append(Part(names.CHILD_FILE_SYMBOL, self.child))
        return names.build_id(parts)

    @property
    def display(self) -> str:
        """限定付きの名前に書くファイル名。子のファイルは、ドメインのディレクトリからのパス。"""
        if self.child is None:
            return names.HANDWRITTEN_FILE_KINDS[self.symbol]
        return f"{self.symbol}/{self.child}.md"

    def parts(self) -> list[str]:
        symbol = names.CHILD_FILE_SYMBOL if self.child is not None else self.symbol
        return [self.domain.full_name(), names.format_part(symbol, self.display)]

    def full_name(self) -> str:
        return names.join_parts(self.parts())


@dataclass
class Target:
    """リンクの参照先 (アンカーのある定義・ファイル・節)。"""

    id: str
    path: str  # アンカーを書いたファイルの、リポジトリのルートからの相対パス
    parts: list[str]  # ドメインから自分までの「種類 + 名前」
    name: str | None  # ラベルの候補にする名前 (日本語名・見出しの文・コードの書式のファイル名)

    def full_name(self) -> str:
        return names.join_parts(self.parts)

    def qualified_names(self) -> list[str]:
        """限定付きの名前。自分だけの「種類 + 名前」から、すべての親を書いた完全な名前まで。"""
        return [names.join_parts(self.parts[i:]) for i in range(len(self.parts) - 1, -1, -1)]

    def labels(self) -> set[str]:
        """ラベルの候補を、比べる形 (markdown.normalize_label) にしたもの。"""
        found = {self.id, *self.qualified_names()}
        if self.name:
            found.add(self.name)
        return {markdown.normalize_label(label) for label in found}

    def href(self, from_path: str) -> str:
        """from_path のファイルに書く、定義の行の href。"""
        if self.path == from_path:
            return f"#{self.id}"
        return f"{posixpath.relpath(self.path, posixpath.dirname(from_path))}#{self.id}"


@dataclass
class Index:
    files: list[HandwrittenFile] = field(default_factory=list)
    targets: dict[str, Target] = field(default_factory=dict)
    # すべての Markdown のアンカー。ID から、それを書いたファイルとアンカーへの対応 (同じ ID が 2 つあれば 2 つ)
    anchors: dict[str, list[tuple[str, markdown.Anchor]]] = field(default_factory=dict)
    documents: dict[str, markdown.Document] = field(default_factory=dict)  # パスから、読んだ Markdown への対応

    def candidates(self, label: str) -> list[Target]:
        key = markdown.normalize_label(label)
        return sorted((t for t in self.targets.values() if key in t.labels()), key=lambda t: t.id)

    def file(self, path: str) -> HandwrittenFile | None:
        for handwritten in self.files:
            if handwritten.path == path:
                return handwritten
        return None


def section_name(file_id: str, anchor: str) -> str | None:
    """節のアンカーの名前。file_id のファイルの節のアンカーの形 (<ファイルの ID>-h-<名前>) でなければ None。"""
    prefix = f"{file_id}-{names.SECTION.symbol}-"
    if not anchor.startswith(prefix):
        return None
    name = anchor[len(prefix) :]
    return name if names.is_name(name) else None


def read_markdown(path: Path) -> markdown.Document:
    return markdown.parse(generated_header.read_file(path).text)


class _Finder:
    def __init__(self, root: Path, project: Project):
        self.root = root
        self.project = project
        self.index = Index()
        self.problems: list[Problem] = []

    def problem(self, path: str, message: str, line: int | None = None, column: int | None = None) -> None:
        self.problems.append(Problem("b", path, message, line, column))

    def find(self) -> None:
        for domain in self.project.domains:
            self.find_in_domain(domain)
        self.read_anchors()
        self.add_targets()

    def find_in_domain(self, domain: Domain) -> None:
        directory = self.root / domain.dir
        kinds = "・".join(names.HANDWRITTEN_FILE_KINDS.values())
        # 直下のファイルを先に、同じ深さはパスの文字コードの順に
        found = sorted(directory.rglob("*.md"), key=lambda p: (len(p.relative_to(directory).parts), p.as_posix()))
        for path in found:
            relative = path.relative_to(directory)
            if any(part.startswith(".") for part in relative.parts) or not path.is_file():
                continue
            path_rel = rel(self.root, path)
            if len(relative.parts) == 1:
                if relative.name in GENERATED_NAMES:
                    continue
                symbol = relative.stem
                if symbol not in names.HANDWRITTEN_FILE_KINDS:
                    self.problem(
                        path_rel,
                        f"ドメインのディレクトリの直下に書ける手書きの Markdown は {kinds} だけ",
                    )
                    continue
                self.add_file(path, path_rel, domain, symbol, None)
                continue
            parent = relative.parts[0]
            if len(relative.parts) == 2 and parent in names.HANDWRITTEN_FILE_KINDS:
                child = relative.stem
                if not names.is_name(child):
                    self.problem(path_rel, f"子のファイルの名前 {child} が snake_case でない")
                    continue
                self.add_file(path, path_rel, domain, parent, child)
                continue
            if parent in names.HANDWRITTEN_FILE_KINDS:
                self.problem(path_rel, f"子のファイルは、ディレクトリ {parent}/ の直下にだけ書ける (サブディレクトリは 1 階層だけ)")
            else:
                directories = "・".join(f"{s}/" for s in names.HANDWRITTEN_FILE_KINDS)
                self.problem(
                    path_rel,
                    f"ドメインのサブディレクトリに書ける手書きの Markdown は、ディレクトリ {directories} の直下の子のファイルだけ",
                )

    def add_file(self, path: Path, path_rel: str, domain: Domain, symbol: str, child: str | None) -> None:
        document = read_markdown(path)
        self.index.documents[path_rel] = document
        self.index.files.append(HandwrittenFile(path_rel, domain, symbol, child, document))

    def read_anchors(self) -> None:
        domains_dir = self.root / DOMAINS_DIR
        if not domains_dir.is_dir():
            return
        for path in sorted(domains_dir.rglob("*.md")):
            relative = path.relative_to(domains_dir)
            if any(part.startswith(".") for part in relative.parts) or not path.is_file():
                continue
            path_rel = rel(self.root, path)
            document = self.index.documents.get(path_rel)
            if document is None:
                document = read_markdown(path)
                self.index.documents[path_rel] = document
            for anchor in document.anchors:
                self.index.anchors.setdefault(anchor.name, []).append((path_rel, anchor))

    def anchor_path(self, target_id: str) -> str | None:
        found = self.index.anchors.get(target_id)
        return found[0][0] if found else None

    def add_target(self, target_id: str, parts: list[str], name: str | None, path: str | None = None) -> None:
        path = path or self.anchor_path(target_id)
        if path is None:
            return
        self.index.targets[target_id] = Target(target_id, path, parts, name)

    def add_targets(self) -> None:
        for domain in self.project.domains:
            self.add_target(domain.id, [domain.full_name()], None)
            for symbol, file_name in names.FILE_KINDS.items():
                file_id = names.build_id([Part("d", domain.name), Part(symbol, None)])
                parts = [domain.full_name(), names.format_part(symbol, file_name)]
                self.add_target(file_id, parts, f"`{file_name}`")
            for entry in domain.entries():
                parts = [domain.full_name()] + [names.format_part(e.symbol, e.name_ja) for e in entry.lineage()]
                self.add_target(entry.id, parts, entry.name_ja)
        for handwritten in self.index.files:
            document = handwritten.document
            first = document.first_nonblank()
            file_anchor = next((a for a in document.anchors if a.line == first), None)
            if file_anchor is not None and file_anchor.name == handwritten.id:
                self.add_target(handwritten.id, handwritten.parts(), f"`{handwritten.display}`", handwritten.path)
            for anchor in document.anchors:
                if section_name(handwritten.id, anchor.name) is None:
                    continue
                following = document.next_nonblank(anchor.line)
                heading = document.heading_at(following) if following else None
                if heading is None or not heading.atx or heading.level < 2:
                    continue
                parts = handwritten.parts() + [names.format_part(names.SECTION.symbol, heading.text)]
                self.add_target(anchor.name, parts, heading.text, handwritten.path)


def load_documents(root: Path, project: Project) -> tuple[Index, list[Problem]]:
    """手書きの Markdown を見つけ、参照先の一覧を作る。受け付けない名前と場所の Markdown は、検査 b の問題として返す。"""
    finder = _Finder(root, project)
    finder.find()
    return finder.index, finder.problems
