"""手書きの Markdown と、リンクの参照先の一覧。

ドメインのディレクトリの下の手書きの Markdown を見つけ、すべての Markdown (生成したファイルを含む) のアンカーから、
リンクの参照先の一覧を作る。形式の SSOT はプラグインの規則の文書 (ファイル doc-structured/rules/doc-structured-docs.md と
doc-structured/rules/doc-structured-domains.md)。要点:
  - 手書きのファイルは、ドメインのディレクトリの直下の concept.md・problem.md・design.md と、
    その種類と同じ名前のサブディレクトリの <名前>.md (子のファイル。1 階層だけ)
  - ほかの名前・場所の .md は、検査 b のエラーにする
  - 参照先のアンカーは、今のファイルの内容から読む (生成したファイルが古いことは検査 a が報告する)。YAML から決まる参照先
    (ドメイン・定義・生成したファイル) のファイルは、生成する側の対応で決め、そのファイルにアンカーがあるときだけ参照先にする
  - 参照先のラベルの候補は、ID・名前・書ける形 (「種類 + 名前」に、親を直近から 0 個以上足した形。略称のある種類は、
    略称で書いた形も含む)
"""

import posixpath
from dataclasses import dataclass, field
from pathlib import Path

from . import generated_header, markdown, names
from .domains import DOMAINS_DIR, Domain, Project, rel
from .generate import entry_file, file_path
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
    name: str | None  # ラベルの候補にする名前 (日本語名・見出しの文・コードの書式のファイル名)。ドメインは名前を持たない
    abbreviated: str | None = None  # 自分の「種類 + 名前」を略称で書いたもの。種類に略称が無ければ None

    def full_name(self) -> str:
        return names.join_parts(self.parts)

    def writable_forms(self) -> list[str]:
        """本文で最初に指す箇所に書ける形。完全な名前の先頭から親を 0 個以上省いた形で、短い順に並べる。
        略称のある種類は、同じ親の数の形を、略称で書いた形・正式名称で書いた形の順に並べる。"""
        forms: list[str] = []
        for i in range(len(self.parts) - 1, -1, -1):
            if self.abbreviated is not None:
                forms.append(names.join_parts(self.parts[i:-1] + [self.abbreviated]))
            forms.append(names.join_parts(self.parts[i:]))
        return forms

    def form_for(self, from_parts: list[str]) -> str:
        """from_parts (参照するファイルの「種類 + 名前」の並び) のファイルから最初に指す箇所に、サブコマンド links-fix が
        書く形。参照するファイルと共通の親を省き、自分の「種類 + 名前」は略称があれば略称で書く。"""
        common = 0
        while common < len(self.parts) - 1 and common < len(from_parts) and self.parts[common] == from_parts[common]:
            common += 1
        own = self.abbreviated if self.abbreviated is not None else self.parts[-1]
        return names.join_parts(self.parts[common:-1] + [own])

    def labels(self) -> set[str]:
        """ラベルの候補を、比べる形 (markdown.normalize_label) にしたもの。"""
        found = {self.id, *self.writable_forms()}
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

    # 比べる形のラベルから、その候補の参照先への対応。最初の candidates の呼び出しで、参照先の一覧から 1 度だけ作る
    _by_label: dict[str, list[Target]] | None = field(default=None, repr=False)

    def candidates(self, label: str) -> list[Target]:
        if self._by_label is None:
            self._by_label = {}
            for target in sorted(self.targets.values(), key=lambda t: t.id):
                for key in target.labels():
                    self._by_label.setdefault(key, []).append(target)
        return list(self._by_label.get(markdown.normalize_label(label), []))

    def add_file_target(self, handwritten: HandwrittenFile) -> None:
        """手書きのファイルの ID を参照先にする。サブコマンド links-fix が、ファイルのアンカーを足すファイルについて、
        足す前に使う (同じ実行で、ほかのファイルの定義の行の href から参照先を求められるように。A2 (#215))。"""
        self.targets[handwritten.id] = Target(handwritten.id, handwritten.path, handwritten.parts(), f"`{handwritten.display}`")
        self._by_label = None

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

    def add_target(
        self, target_id: str, parts: list[str], name: str | None, path: str, abbreviated: str | None = None
    ) -> None:
        """path のファイルに target_id のアンカーがあれば、参照先にする。"""
        if any(found == path for found, _ in self.index.anchors.get(target_id, [])):
            self.index.targets[target_id] = Target(target_id, path, parts, name, abbreviated)

    def add_targets(self) -> None:
        for domain in self.project.domains:
            # ファイルは、生成する側 (モジュール generate) の対応で決める
            self.add_target(domain.id, [domain.full_name()], None, f"{domain.dir}/{README}")
            for symbol, file_name in names.FILE_KINDS.items():
                file_id = names.build_id([Part("d", domain.name), Part(symbol, None)])
                parts = [domain.full_name(), names.format_part(symbol, file_name)]
                self.add_target(file_id, parts, f"`{file_name}`", file_path(domain, symbol))
            for entry in domain.entries():
                parts = [domain.full_name()] + [names.format_part(e.symbol, e.name_ja) for e in entry.lineage()]
                abbreviated = None
                if entry.symbol in names.ABBREVIATIONS:
                    abbreviated = names.format_part(entry.symbol, entry.name_ja, abbreviated=True)
                self.add_target(entry.id, parts, entry.name_ja, entry_file(entry), abbreviated)
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
