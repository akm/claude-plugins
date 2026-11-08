"""ドメインの YAML から、人が読む Markdown を生成する。

ドメインのディレクトリの直下に README.md・models.md・unclassified_app_terms.md・terms.md を、全体の用語の索引
docs/glossary.md を生成する。生成するファイルの中身の SSOT はプラグインの規則の文書
(ファイル doc-structured/rules/doc-structured-domains.md)。要点:
  - 先頭に、生成したファイルの先頭の記述 (モジュール generated_header) を書く
  - 定義ごとに <a name="ID"></a> と見出しを書く。見出しは「種類 + 日本語名」の後に英語名をコードの書式で書く
  - リンクは reference-style で、ラベルを ID にし、定義の行 [ID]: 相対パス#ID "完全な名前" をファイルの末尾に書く
  - 用語の索引は定義の文を持たず、日本語名の文字コードの順 (同じなら ID の順) に、定義へのリンクを並べる
  - 定義が 1 つも無い種類のファイルは作らない
同じ入力からは、いつも同じ出力を作る (時刻や環境に依存する値を書かない)。
"""

import posixpath
from pathlib import Path

from . import generated_header, names
from .domains import DOMAINS_DIR, Domain, Entry, Project

GLOSSARY_PATH = "docs/glossary.md"
README = "README.md"
FILE_DESCRIPTIONS = {
    "models": "モデル・属性・値の定義",
    "unclassified_app_terms": "未分類のアプリケーション用語の定義",
    "terms": "このドメインの用語の索引",
}
# 見出しの深さ。モデル 2・属性 3・値 4。未分類のアプリケーション用語は 2
HEADING_LEVELS = {"m": 2, "a": 3, "v": 4, "ut": 2}


def escape_link_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def escape_cell(text: str) -> str:
    return text.replace("|", "\\|")


class _Links:
    """1 つのファイルの reference-style のリンクと、末尾に書く定義の行。"""

    def __init__(self, file: str):
        self.file = file
        self.definitions: dict[str, tuple[str, str]] = {}

    def link(self, text: str, target_id: str, target_file: str, title: str) -> str:
        if target_file == self.file:
            href = f"#{target_id}"
        else:
            relative = posixpath.relpath(target_file, posixpath.dirname(self.file))
            href = f"{relative}#{target_id}"
        self.definitions[target_id] = (href, title)
        return f"[{escape_link_text(text)}][{target_id}]"

    def lines(self) -> list[str]:
        return [f'[{label}]: {href} "{title}"' for label, (href, title) in sorted(self.definitions.items())]


def _file_path(domain: Domain, symbol: str) -> str:
    return f"{domain.dir}/{names.FILE_KINDS[symbol]}"


def _file_id(domain: Domain, symbol: str) -> str:
    return names.build_id([names.Part("d", domain.name), names.Part(symbol, None)])


def _file_title(domain: Domain, symbol: str) -> str:
    return names.join_parts([domain.full_name(), names.format_part(symbol, names.FILE_KINDS[symbol])])


def _entry_file(entry: Entry) -> str:
    symbol = "unclassified_app_terms" if entry.symbol == "ut" else "models"
    return _file_path(entry.domain, symbol)


def _entry_link(links: _Links, entry: Entry, text: str) -> str:
    return links.link(text, entry.id, _entry_file(entry), entry.full_name())


def _reference_text(entry: Entry, from_domain: Domain) -> str:
    """ほかの定義を指すリンクの表示の文。同じドメインなら「種類 + 名前」、ほかのドメインなら完全な名前。"""
    if entry.domain is from_domain:
        return names.format_part(entry.symbol, entry.name_ja)
    return entry.full_name()


def _document(source: str, anchor: str | None, blocks: list[str], links: _Links) -> str:
    parts = [generated_header.markdown_line(source)]
    if anchor:
        parts.append(f'<a name="{anchor}"></a>')
    text = "\n".join(parts) + "\n\n" + "\n\n".join(blocks)
    definition_lines = links.lines()
    if definition_lines:
        text += "\n\n" + "\n".join(definition_lines)
    return text + "\n"


def _definition_block(entry: Entry, extra: str = "") -> str:
    heading = "#" * HEADING_LEVELS[entry.symbol]
    title = f"{names.format_part(entry.symbol, entry.name_ja)} `{entry.name}`"
    body = entry.definition
    if extra:
        body += extra if body.endswith("。") else f" {extra}"
    return f'<a name="{entry.id}"></a>\n\n{heading} {title}\n\n{body}'


def _referencing_models(project: Project) -> dict[str, list[Entry]]:
    """モデルの ID から、そのモデルを参照するモデルへの対応。定義の並び順で、重複は除く。"""
    result: dict[str, list[Entry]] = {}
    for domain in project.domains:
        for model in domain.models:
            for attribute in model.children:
                target = attribute.refers_to
                if target in project.entries and model not in result.setdefault(target, []):
                    result[target].append(model)
    return result


def render_models(project: Project, domain: Domain, referencing: dict[str, list[Entry]]) -> str:
    path = _file_path(domain, "models")
    links = _Links(path)
    blocks = [f"# {domain.full_name()} のモデル"]
    for model in domain.models:
        blocks.append(_definition_block(model))
        users = referencing.get(model.id, [])
        if users:
            listed = "・".join(_entry_link(links, m, _reference_text(m, domain)) for m in users)
            blocks.append(f"このモデルを参照するモデル: {listed}")
        for attribute in model.children:
            extra = ""
            if attribute.refers_to in project.entries:
                target = project.entries[attribute.refers_to]
                extra = "参照先: " + _entry_link(links, target, _reference_text(target, domain))
            blocks.append(_definition_block(attribute, extra))
            for value in attribute.children:
                blocks.append(_definition_block(value))
    return _document(f"{domain.dir}/", _file_id(domain, "models"), blocks, links)


def render_unclassified_app_terms(domain: Domain) -> str:
    path = _file_path(domain, "unclassified_app_terms")
    links = _Links(path)
    blocks = [f"# {domain.full_name()} の{names.KINDS['ut'].label}"]
    blocks += [_definition_block(term) for term in domain.terms]
    return _document(f"{domain.dir}/", _file_id(domain, "unclassified_app_terms"), blocks, links)


def _kind_text(entry: Entry) -> str:
    """用語の索引の「種類」の列。ドメインの中の親の「種類 + 名前」と、自分の種類の名前。"""
    parents = [names.format_part(e.symbol, e.name_ja) for e in entry.lineage()[:-1]]
    return names.join_parts([*parents, entry.kind_label])


def _sorted_terms(entries: list[Entry]) -> list[Entry]:
    return sorted(entries, key=lambda e: (e.name_ja, e.id))


def render_terms(domain: Domain) -> str:
    path = _file_path(domain, "terms")
    links = _Links(path)
    rows = ["| 用語 | 種類 | 英語名 |", "|---|---|---|"]
    for entry in _sorted_terms(list(domain.entries())):
        term = escape_cell(_entry_link(links, entry, entry.name_ja))
        rows.append(f"| {term} | {escape_cell(_kind_text(entry))} | `{entry.name}` |")
    blocks = [f"# {domain.full_name()} の用語の索引", "\n".join(rows)]
    return _document(f"{domain.dir}/", _file_id(domain, "terms"), blocks, links)


def render_glossary(project: Project) -> str:
    links = _Links(GLOSSARY_PATH)
    rows = ["| 用語 | 種類 | 英語名 | ドメイン |", "|---|---|---|---|"]
    all_entries = [e for d in project.domains for e in d.entries()]
    for entry in _sorted_terms(all_entries):
        domain = entry.domain
        term = escape_cell(_entry_link(links, entry, entry.name_ja))
        domain_link = links.link(f"`{domain.name}`", domain.id, f"{domain.dir}/{README}", domain.full_name())
        rows.append(f"| {term} | {escape_cell(_kind_text(entry))} | `{entry.name}` | {domain_link} |")
    blocks = ["# 用語の索引", "\n".join(rows)]
    return _document(f"{DOMAINS_DIR.as_posix()}/", None, blocks, links)


def render_readme(domain: Domain, files: list[str]) -> str:
    """files は、このドメインで生成するファイルの種類の記号 (models・unclassified_app_terms・terms)。"""
    path = f"{domain.dir}/{README}"
    links = _Links(path)
    blocks = [f"# {domain.full_name()}"]
    if domain.description:
        blocks.append(domain.description)
    if files:
        rows = ["| 文書 | 中身 |", "|---|---|"]
        for symbol in files:
            link = links.link(
                f"`{names.FILE_KINDS[symbol]}`", _file_id(domain, symbol), _file_path(domain, symbol),
                _file_title(domain, symbol),
            )
            rows.append(f"| {link} | {FILE_DESCRIPTIONS[symbol]} |")
        blocks.append("\n".join(rows))
    return _document(f"{domain.dir}/", domain.id, blocks, links)


def render_project(project: Project) -> dict[str, str]:
    """生成するファイルの、リポジトリのルートからの相対パスと内容。"""
    outputs: dict[str, str] = {}
    referencing = _referencing_models(project)
    for domain in project.domains:
        files: list[str] = []
        if domain.models:
            outputs[_file_path(domain, "models")] = render_models(project, domain, referencing)
            files.append("models")
        if domain.terms:
            outputs[_file_path(domain, "unclassified_app_terms")] = render_unclassified_app_terms(domain)
            files.append("unclassified_app_terms")
        if domain.models or domain.terms:
            outputs[_file_path(domain, "terms")] = render_terms(domain)
            files.append("terms")
        outputs[f"{domain.dir}/{README}"] = render_readme(domain, files)
    if any(d.models or d.terms for d in project.domains):
        outputs[GLOSSARY_PATH] = render_glossary(project)
    return dict(sorted(outputs.items()))


def generated_files(root: Path) -> dict[str, generated_header.Header]:
    """ディレクトリ docs/ の下の、先頭の記述を持つファイル (生成したファイル) と、その記述。"""
    found: dict[str, generated_header.Header] = {}
    docs = root / "docs"
    if not docs.is_dir():
        return found
    for path in sorted(docs.rglob("*")):
        if not path.is_file() or path.suffix not in (".md", ".yaml"):
            continue
        with path.open(encoding="utf-8", errors="replace") as f:
            head = "".join(f.readline() for _ in range(generated_header.HEADER_LINES))
        header = generated_header.read_header(head)
        if header is not None:
            found[path.relative_to(root).as_posix()] = header
    return found


def write_outputs(root: Path, outputs: dict[str, str]) -> tuple[list[str], list[str]]:
    """生成したファイルを書き、生成し直すと無くなるファイルを消す。書いたファイルと消したファイルを返す。

    消すのは、先頭の記述を持つファイル (生成したファイル) だけ。手書きのファイルは消さない。
    内容が同じファイルは書かない。
    """
    written: list[str] = []
    for relative, content in outputs.items():
        path = root / relative
        if path.is_file() and path.read_text(encoding="utf-8") == content:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        written.append(relative)
    deleted: list[str] = []
    for relative in generated_files(root):
        if relative not in outputs:
            (root / relative).unlink()
            deleted.append(relative)
    return written, deleted
