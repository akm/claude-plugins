"""ドメインの YAML の読み込みと、検査 h (YAML の形式と、参照する名前があること)。

ディレクトリ docs/domains/ の直下のディレクトリ NN-<名前> がドメインで、その下のどの深さの .yaml も読む。
形式の SSOT はプラグインの規則の文書 (ファイル doc-structured/rules/doc-structured-domains.md)。要点:
  - 直下の domain.yaml にだけ、キー domain (説明 description) を書く
  - どのファイルにも、キー models (モデル・属性・値) と unclassified_app_terms (未分類のアプリケーション用語) を書ける
  - 英語名をマッピングのキーにし、日本語名を name_ja、定義を definition に書く
  - 属性は、ほかのモデルへの参照 refers_to (完全な ID) と、値 values を持てる
誤りは読み飛ばさず、すべて Problem (検査 h) として返す。誤りがあっても、読めた部分の定義は返す。
"""

from dataclasses import dataclass, field
from pathlib import Path
import re

from ruamel.yaml import YAMLError
from ruamel.yaml.comments import CommentedMap

from . import names, yamlio
from .names import IdError, Part
from .problems import Problem

DOMAINS_DIR = Path("docs/domains")
DOMAIN_FILE = "domain.yaml"
DOMAIN_DIR_RE = re.compile(r"^(\d{2,})-(.+)$")

TOP_KEYS = ("domain", "models", "unclassified_app_terms")
DOMAIN_KEYS = ("description",)
MODEL_KEYS = ("name_ja", "definition", "attributes")
ATTRIBUTE_KEYS = ("name_ja", "definition", "values", "refers_to")
VALUE_KEYS = ("name_ja", "definition")
TERM_KEYS = ("name_ja", "definition")
REQUIRED_KEYS = ("name_ja", "definition")
# read_yaml が、YAML として読めないファイルに返す値 (空のファイルの None と区別する)
_UNREADABLE = object()

# 日本語名に使えない文字。完全な名前を定義の行の title ("…") に書くため
NAME_JA_FORBIDDEN = ("\n", "\r", '"')

# 定義 (definition) と、ドメインの説明 (description) に使えない文字。生成したファイルは改行の CR を LF として読むので、
# CR を含む文は、生成し直した内容と一致しなくなるため
CR = "\r"


@dataclass
class Entry:
    """名前と定義を持つ 1 つの定義 (モデル・属性・値・未分類のアプリケーション用語)。"""

    id: str
    symbol: str
    name: str
    name_ja: str
    definition: str
    path: str  # 定義を書いた YAML の、リポジトリのルートからの相対パス
    line: int
    column: int
    domain: "Domain"
    parent: "Entry | None" = None
    children: list["Entry"] = field(default_factory=list)
    refers_to: str | None = None
    refers_to_line: int = 0
    refers_to_column: int = 0

    @property
    def kind_label(self) -> str:
        return names.KINDS[self.symbol].label

    def lineage(self) -> list["Entry"]:
        """親から自分までの定義 (ドメインは含まない)。"""
        chain: list[Entry] = []
        entry: Entry | None = self
        while entry is not None:
            chain.append(entry)
            entry = entry.parent
        return list(reversed(chain))

    def full_name(self) -> str:
        parts = [names.format_part("d", self.domain.name)]
        parts += [names.format_part(e.symbol, e.name_ja) for e in self.lineage()]
        return names.join_parts(parts)

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


@dataclass
class Domain:
    number: str
    name: str
    dir: str  # リポジトリのルートからの相対パス (docs/domains/01-loans)
    description: str = ""
    models: list[Entry] = field(default_factory=list)
    terms: list[Entry] = field(default_factory=list)  # 未分類のアプリケーション用語
    yaml_files: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return names.build_id([Part("d", self.name)])

    def full_name(self) -> str:
        return names.format_part("d", self.name)

    def entries(self):
        """モデル (その属性と値を含む) と未分類のアプリケーション用語を、定義の並び順に返す。"""
        for model in self.models:
            yield from model.walk()
        yield from self.terms


@dataclass
class Project:
    root: Path
    domains: list[Domain] = field(default_factory=list)
    entries: dict[str, Entry] = field(default_factory=dict)


def rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


class _Loader:
    def __init__(self, root: Path):
        self.root = root
        self.problems: list[Problem] = []
        self.project = Project(root=root)

    def problem(self, path: str, message: str, line: int | None = None, column: int | None = None) -> None:
        self.problems.append(Problem("h", path, message, line, column))

    def load(self) -> None:
        domains_dir = self.root / DOMAINS_DIR
        if not domains_dir.is_dir():
            return
        numbers: dict[str, str] = {}
        domain_names: dict[str, str] = {}
        for child in sorted(domains_dir.iterdir(), key=lambda p: p.name):
            if child.name.startswith(".") or not child.is_dir():
                continue
            child_rel = rel(self.root, child)
            match = DOMAIN_DIR_RE.match(child.name)
            if not match or not names.is_name(match.group(2)):
                self.problem(
                    child_rel,
                    f"ドメインのディレクトリ名 {child.name} は、NN-<名前> の形でなければならない "
                    "(NN は 2 桁以上の数字、名前は snake_case)",
                )
                continue
            number, name = match.group(1), match.group(2)
            if number in numbers:
                self.problem(child_rel, f"ドメインの番号 {number} は、{numbers[number]} と同じ")
                continue
            if name in domain_names:
                self.problem(child_rel, f"ドメインの名前 {name} は、{domain_names[name]} と同じ")
                continue
            numbers[number] = child_rel
            domain_names[name] = child_rel
            domain = Domain(number=number, name=name, dir=child_rel)
            self.project.domains.append(domain)
            self.load_domain(domain, child)
        self.resolve_references()

    def yaml_files(self, domain: Domain, directory: Path) -> list[Path]:
        """ドメインのディレクトリの下の YAML を、直下の domain.yaml を先にし、残りはパスの文字コードの順に返す。"""
        found: list[Path] = []
        for path in sorted(directory.rglob("*")):
            relative = path.relative_to(directory)
            if any(part.startswith(".") for part in relative.parts) or not path.is_file():
                continue
            if path.suffix == ".yml":
                self.problem(rel(self.root, path), "拡張子は .yaml にする (.yml のファイルは読まない)")
            elif path.suffix == ".yaml":
                found.append(path)
        found.sort(key=lambda p: (p != directory / DOMAIN_FILE, p.relative_to(directory).as_posix()))
        return found

    def load_domain(self, domain: Domain, directory: Path) -> None:
        files = self.yaml_files(domain, directory)
        root_file = directory / DOMAIN_FILE
        if root_file not in files:
            self.problem(domain.dir, f"ドメインのディレクトリの直下に {DOMAIN_FILE} が無い")
        model_names: dict[str, Entry] = {}
        term_names: dict[str, Entry] = {}
        for path in files:
            path_rel = rel(self.root, path)
            domain.yaml_files.append(path_rel)
            data = self.read_yaml(path, path_rel)
            if data is _UNREADABLE:
                # 読めないファイルは、キー domain があるかどうかが分からないので、無いとは報告しない
                continue
            if data is None:
                if path == root_file:
                    self.problem(path_rel, "キー domain (ドメインの説明) が無い")
                continue
            for key in data:
                line, column = _key_position(data, key)
                if key == "domain":
                    if path != root_file:
                        self.problem(
                            path_rel, "キー domain は、ドメインのディレクトリの直下の domain.yaml にだけ書ける", line, column
                        )
                        continue
                    self.load_domain_description(domain, data, path_rel)
                elif key == "models":
                    self.load_models(domain, data, path_rel, model_names)
                elif key == "unclassified_app_terms":
                    self.load_terms(domain, data, path_rel, term_names)
                else:
                    self.unknown_key(path_rel, key, TOP_KEYS, line, column)
            if path == root_file and "domain" not in data:
                self.problem(path_rel, "キー domain (ドメインの説明) が無い", 1, 1)

    def read_yaml(self, path: Path, path_rel: str) -> CommentedMap | None | object:
        """YAML を読む。空のファイルは None、読めないファイルは問題を報告して _UNREADABLE を返す。"""
        try:
            data = yamlio.load(path.read_text(encoding="utf-8"))
        except YAMLError as e:
            mark = getattr(e, "problem_mark", None) or getattr(e, "context_mark", None)
            reason = getattr(e, "problem", None) or str(e)
            if mark is not None:
                self.problem(path_rel, f"YAML として読めない: {reason}", mark.line + 1, mark.column + 1)
            else:
                self.problem(path_rel, f"YAML として読めない: {reason}")
            return _UNREADABLE
        if data is None:
            return None
        if not isinstance(data, CommentedMap):
            self.problem(path_rel, "ファイルの全体は、キーと値のマッピングでなければならない", 1, 1)
            return _UNREADABLE
        return data

    def unknown_key(self, path_rel: str, key, allowed: tuple[str, ...], line: int, column: int) -> None:
        self.problem(path_rel, f"知らないキー {key} (書けるキー: {', '.join(allowed)})", line, column)

    def mapping_of(self, parent: CommentedMap, key: str, path_rel: str) -> CommentedMap | None:
        value = parent[key]
        if not isinstance(value, CommentedMap):
            line, column = _value_position(parent, key)
            self.problem(path_rel, f"{key} の値は、キーと値のマッピングでなければならない", line, column)
            return None
        return value

    def load_domain_description(self, domain: Domain, data: CommentedMap, path_rel: str) -> None:
        mapping = self.mapping_of(data, "domain", path_rel)
        if mapping is None:
            return
        for key in mapping:
            if key not in DOMAIN_KEYS:
                self.unknown_key(path_rel, key, DOMAIN_KEYS, *_key_position(mapping, key))
        line, column = _key_position(data, "domain")
        description = self.without_cr(
            mapping, "description", self.text(mapping, "description", path_rel, line, column, "domain"), path_rel, "domain"
        )
        if description is not None:
            domain.description = description

    def text(self, mapping: CommentedMap, key: str, path_rel: str, line: int, column: int, owner: str) -> str | None:
        """必須の文字列の項目を読む。無い・文字列でない・空なら問題を足して None を返す。"""
        if key not in mapping:
            self.problem(path_rel, f"{owner} に必須の項目 {key} が無い", line, column)
            return None
        value = mapping[key]
        vline, vcolumn = _value_position(mapping, key)
        if not isinstance(value, str) or not value.strip():
            self.problem(path_rel, f"{owner} の {key} は、空でない文字列でなければならない", vline, vcolumn)
            return None
        return value.strip()

    def without_cr(self, mapping: CommentedMap, key: str, value: str | None, path_rel: str, owner: str) -> str | None:
        """関数 text で読んだ値に CR があれば、問題を足して None を返す。"""
        if value is not None and CR in value:
            self.problem(path_rel, f"{owner} の {key} に、CR は使えない", *_value_position(mapping, key))
            return None
        return value

    def entry(
        self,
        domain: Domain,
        parent_map: CommentedMap,
        name,
        symbol: str,
        allowed: tuple[str, ...],
        path_rel: str,
        parent: Entry | None,
    ) -> tuple[Entry | None, CommentedMap | None]:
        """1 つの定義を読む。名前・項目・日本語名を検査する。"""
        line, column = _key_position(parent_map, name)
        label = names.KINDS[symbol].label
        if not isinstance(name, str) or not names.is_name(name):
            self.problem(path_rel, f"{label}の名前 {name} が snake_case でない", line, column)
            return None, None
        mapping = parent_map[name]
        if not isinstance(mapping, CommentedMap):
            self.problem(path_rel, f"{label} {name} の値は、キーと値のマッピングでなければならない", line, column)
            return None, None
        for key in mapping:
            if key not in allowed:
                self.unknown_key(path_rel, key, allowed, *_key_position(mapping, key))
        owner = f"{label} {name}"
        name_ja = self.text(mapping, "name_ja", path_rel, line, column, owner)
        definition = self.without_cr(
            mapping, "definition", self.text(mapping, "definition", path_rel, line, column, owner), path_rel, owner
        )
        if name_ja is not None and any(ch in name_ja for ch in NAME_JA_FORBIDDEN):
            self.problem(
                path_rel, f'{owner} の name_ja に、改行と " は使えない', *_value_position(mapping, "name_ja")
            )
            name_ja = None
        parent_parts = names.parse_id(parent.id) if parent else [Part("d", domain.name)]
        entry = Entry(
            id=names.build_id([*parent_parts, Part(symbol, name)]),
            symbol=symbol,
            name=name,
            name_ja=name_ja or name,
            definition=definition or "",
            path=path_rel,
            line=line,
            column=column,
            domain=domain,
            parent=parent,
        )
        if parent is not None:
            parent.children.append(entry)
        return entry, mapping

    def load_models(self, domain: Domain, data: CommentedMap, path_rel: str, seen: dict[str, Entry]) -> None:
        models = self.mapping_of(data, "models", path_rel)
        if models is None:
            return
        for name in models:
            model, mapping = self.entry(domain, models, name, "m", MODEL_KEYS, path_rel, None)
            if model is None:
                continue
            if name in seen:
                other = seen[name]
                self.problem(
                    path_rel, f"モデル {name} は、{other.path}:{other.line} にもある", model.line, model.column
                )
                continue
            seen[name] = model
            domain.models.append(model)
            if "attributes" in mapping:
                self.load_attributes(domain, model, mapping, path_rel)

    def load_attributes(self, domain: Domain, model: Entry, model_map: CommentedMap, path_rel: str) -> None:
        attributes = self.mapping_of(model_map, "attributes", path_rel)
        if attributes is None:
            return
        for name in attributes:
            attribute, mapping = self.entry(domain, attributes, name, "a", ATTRIBUTE_KEYS, path_rel, model)
            if attribute is None:
                continue
            if "refers_to" in mapping:
                value = mapping["refers_to"]
                vline, vcolumn = _value_position(mapping, "refers_to")
                if isinstance(value, str) and value.strip():
                    attribute.refers_to = value.strip()
                    attribute.refers_to_line, attribute.refers_to_column = vline, vcolumn
                else:
                    self.problem(path_rel, f"属性 {name} の refers_to は、モデルの ID の文字列でなければならない", vline, vcolumn)
            if "values" in mapping:
                values = self.mapping_of(mapping, "values", path_rel)
                if values is None:
                    continue
                for value_name in values:
                    self.entry(domain, values, value_name, "v", VALUE_KEYS, path_rel, attribute)

    def load_terms(self, domain: Domain, data: CommentedMap, path_rel: str, seen: dict[str, Entry]) -> None:
        terms = self.mapping_of(data, "unclassified_app_terms", path_rel)
        if terms is None:
            return
        for name in terms:
            term, _ = self.entry(domain, terms, name, "ut", TERM_KEYS, path_rel, None)
            if term is None:
                continue
            if name in seen:
                other = seen[name]
                self.problem(
                    path_rel,
                    f"未分類のアプリケーション用語 {name} は、{other.path}:{other.line} にもある",
                    term.line,
                    term.column,
                )
                continue
            seen[name] = term
            domain.terms.append(term)

    def resolve_references(self) -> None:
        entries = self.project.entries
        for domain in self.project.domains:
            for entry in domain.entries():
                entries[entry.id] = entry
        for domain in self.project.domains:
            for entry in domain.entries():
                if entry.refers_to is None:
                    continue
                where = (entry.path, entry.refers_to_line, entry.refers_to_column)
                try:
                    kind = names.kind_of(entry.refers_to)
                except IdError as e:
                    self.problem(where[0], f"refers_to の値が ID の形でない: {e}", *where[1:])
                    continue
                if kind != "m":
                    self.problem(where[0], f"refers_to の参照先 {entry.refers_to} はモデルでない (参照できるのはモデルだけ)", *where[1:])
                elif entry.refers_to not in entries:
                    self.problem(where[0], f"refers_to の参照先 {entry.refers_to} が無い", *where[1:])


def _key_position(mapping: CommentedMap, key) -> tuple[int, int]:
    line, column = mapping.lc.key(key)
    return line + 1, column + 1


def _value_position(mapping: CommentedMap, key) -> tuple[int, int]:
    line, column = mapping.lc.value(key)
    return line + 1, column + 1


def load_project(root: Path) -> tuple[Project, list[Problem]]:
    """リポジトリのルートからドメインの YAML を読む。検査 h の問題も返す。"""
    loader = _Loader(root)
    loader.load()
    return loader.project, loader.problems
