"""ドメインの YAML の読み込みと、検査 h (YAML の形式と、参照する名前があること)。

ディレクトリ docs/domains/ の直下のディレクトリ NN-<名前> がドメインで、その下のどの深さの .yaml も読む。
形式の SSOT はプラグインの規則の文書 (ファイル doc-structured/rules/doc-structured-domains.md)。要点:
  - 直下の domain.yaml にだけ、キー domain (説明 description) を書く
  - どのファイルにも、キー models (モデル・属性・値)・unclassified_app_terms (未分類のアプリケーション用語)・
    operations (操作)・preconditions (前提)・events (イベント) を書ける
  - 英語名をマッピングのキーにし、日本語名を name_ja、定義を definition に書く
  - 属性は、ほかのモデルへの参照 refers_to (完全な ID) と、値 values を持てる
  - 操作は、モデルか属性への参照 targets・前提への参照 preconditions・イベントへの参照 events・行えるロールへの参照 roles
    (どれも完全な ID の配列) を持てる。roles を省いた操作は、どのロールも行わない操作 (アプリケーションが自分で行う処理)
  - 前提は、モデル・属性・値への参照 targets (完全な ID の配列) を持てる
  - 値を持つ属性は、状態の遷移 state_machine (最初の状態 initial と、遷移の配列 transitions) を持てる。状態は属性の値で、
    遷移の前の状態 from・後の状態 to・initial には値の英語名を書く。遷移は、操作への参照 operations と前提への参照
    preconditions (どちらも完全な ID の配列) を持てる。属性の下に書けるのは、値が 3 つ以下で、どの遷移にも preconditions が
    無いときだけ。それを超えるものは、ファイル名が state-machines- で始まる YAML のトップのキー state_machine に書き、
    属性を attribute (完全な ID。同じドメインの属性だけ) で指す。このファイルには、ほかのトップのキーを書けない
ロールは、ドメインの外のファイル docs/system/roles.yaml のキー roles に書く。ロールは親を持たない (ID は r-<英語名>)。
誤りは読み飛ばさず、すべて Problem (検査 h) として返す。誤りがあっても、読めた部分の定義は返す。
"""

from dataclasses import dataclass, field
from pathlib import Path
import re

from ruamel.yaml import YAMLError
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from . import names, yamlio
from .names import IdError, Part
from .problems import Problem

DOMAINS_DIR = Path("docs/domains")
DOMAIN_FILE = "domain.yaml"
DOMAIN_DIR_RE = re.compile(r"^(\d{2,})-(.+)$")
ROLES_FILE = Path("docs/system/roles.yaml")

TOP_KEYS = ("domain", "models", "unclassified_app_terms", "operations", "preconditions", "events")
DOMAIN_KEYS = ("description",)
MODEL_KEYS = ("name_ja", "definition", "attributes")
ATTRIBUTE_KEYS = ("name_ja", "definition", "values", "refers_to", "state_machine")
VALUE_KEYS = ("name_ja", "definition")
TERM_KEYS = ("name_ja", "definition")
OPERATION_KEYS = ("name_ja", "definition", "targets", "preconditions", "events", "roles")
PRECONDITION_KEYS = ("name_ja", "definition", "targets")
EVENT_KEYS = ("name_ja", "definition")
ROLES_TOP_KEYS = ("roles",)
ROLE_KEYS = ("name_ja", "definition")
# 完全な ID の配列で書く参照。定義の種類の記号とキーから、参照できる種類の記号と、メッセージに書くその名前への対応
LIST_REFERENCES: dict[tuple[str, str], tuple[tuple[str, ...], str]] = {
    ("op", "targets"): (("m", "a"), "モデルか属性"),
    ("op", "preconditions"): (("pre",), "前提"),
    ("op", "events"): (("ev",), "イベント"),
    ("op", "roles"): (("r",), "ロール"),
    ("pre", "targets"): (("m", "a", "v"), "モデル・属性・値"),
}
# 空の配列を書いたときに、メッセージに添える直し方。書いていないキーは「参照が無いときは、<キー> を省く」
EMPTY_LIST_HINTS = {"roles": "行えるロールが無い操作は、roles を省く"}
REQUIRED_KEYS = ("name_ja", "definition")
STATE_MACHINE_KEY = "state_machine"
# 属性の下に書く状態の遷移のキー
STATE_MACHINE_KEYS = ("initial", "transitions")
# ファイルに書く状態の遷移の、ファイル名の始まりとキー
STATE_MACHINE_FILE_PREFIX = "state-machines-"
STATE_MACHINE_FILE_KEYS = ("attribute", "initial", "transitions")
# ファイルに書く状態の遷移で、属性を指す前の、メッセージに書く名前
STATE_MACHINE_OWNER = "状態の遷移"
TRANSITION_KEYS = ("from", "to", "operations", "preconditions")
# 遷移の、完全な ID の配列で書く参照。キーから、参照できる種類の記号と、メッセージに書くその名前への対応
TRANSITION_REFERENCES: dict[str, tuple[tuple[str, ...], str]] = {
    "operations": (("op",), "操作"),
    "preconditions": (("pre",), "前提"),
}
# 状態の遷移を属性の下に書ける、属性の値の数の上限。超えたら、ファイルに書く形に移す
ATTRIBUTE_FORM_MAX_VALUES = 3
# 状態の遷移を属性の下に書けないときに、メッセージに添える直し方
MOVE_TO_FILE_HINT = "state-machines- で始まる名前のファイルに移す"
# read_yaml が、YAML として読めないファイルに返す値 (空のファイルの None と区別する)
_UNREADABLE = object()

# 日本語名に使えない文字。完全な名前を定義の行の title ("…") に書くため
NAME_JA_FORBIDDEN = ("\n", "\r", '"')

# 定義 (definition) と、ドメインの説明 (description) に使えない文字。生成したファイルは改行の CR を LF として読むので、
# CR を含む文は、生成し直した内容と一致しなくなるため
CR = "\r"


@dataclass(frozen=True)
class Reference:
    """完全な ID の配列で書いた参照の 1 つ (前提の targets など)。"""

    key: str  # 参照を書いたキー
    target: str  # 参照先の ID
    line: int
    column: int


@dataclass(frozen=True)
class StateName:
    """状態の遷移の from・to・initial に書いた、値の英語名の 1 つ。"""

    key: str  # 名前を書いたキー
    name: str
    line: int
    column: int


@dataclass
class Transition:
    """状態の遷移の、遷移の 1 つ。"""

    from_values: list[StateName]
    to: StateName | None
    line: int
    column: int
    references: list[Reference] = field(default_factory=list)  # operations と preconditions。書いた順

    def targets(self, key: str) -> list[str]:
        return [r.target for r in self.references if r.key == key]


@dataclass
class StateMachine:
    """1 つの属性の状態の遷移。"""

    owner: str  # 検査 h・i のメッセージに書く名前 (「属性 status の状態の遷移」)
    domain: "Domain"
    path: str  # 状態の遷移を書いた YAML の、リポジトリのルートからの相対パス
    line: int  # 位置。属性の下に書く形ではキー state_machine
    column: int
    attribute: "Entry | None"  # 状態の遷移を持つ属性。ファイルに書く形では、参照先を確認するまで None
    in_file: bool = False  # ファイルに書く形なら True、属性の下に書く形なら False
    attribute_reference: Reference | None = None  # ファイルに書く形の attribute
    initial: StateName | None = None
    transitions: list[Transition] = field(default_factory=list)

    def state_names(self):
        """書いた順の、initial・from・to の値の英語名。"""
        if self.initial is not None:
            yield self.initial
        for transition in self.transitions:
            yield from transition.from_values
            if transition.to is not None:
                yield transition.to


@dataclass
class Entry:
    """名前と定義を持つ 1 つの定義 (モデル・属性・値・未分類のアプリケーション用語・操作・前提・イベント・ロール)。"""

    id: str
    symbol: str
    name: str
    name_ja: str
    definition: str
    path: str  # 定義を書いた YAML の、リポジトリのルートからの相対パス
    line: int
    column: int
    domain: "Domain | None"  # ロールは None
    parent: "Entry | None" = None
    children: list["Entry"] = field(default_factory=list)
    refers_to: str | None = None
    refers_to_line: int = 0
    refers_to_column: int = 0
    references: list[Reference] = field(default_factory=list)  # 完全な ID の配列で書いた参照。書いた順

    @property
    def kind_label(self) -> str:
        return names.KINDS[self.symbol].label

    @property
    def owner(self) -> str:
        """検査 h・i のメッセージに書く、定義の種類と英語名 (「前提 book_shelved」)。"""
        return f"{self.kind_label} {self.name}"

    def lineage(self) -> list["Entry"]:
        """親から自分までの定義 (ドメインは含まない)。"""
        chain: list[Entry] = []
        entry: Entry | None = self
        while entry is not None:
            chain.append(entry)
            entry = entry.parent
        return list(reversed(chain))

    def full_name(self) -> str:
        parts = [names.format_part("d", self.domain.name)] if self.domain is not None else []
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
    operations: list[Entry] = field(default_factory=list)
    preconditions: list[Entry] = field(default_factory=list)
    events: list[Entry] = field(default_factory=list)
    state_machines: list[StateMachine] = field(default_factory=list)  # 読んだ順
    yaml_files: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return names.build_id([Part("d", self.name)])

    def full_name(self) -> str:
        return names.format_part("d", self.name)

    def entries(self):
        """モデル (その属性と値を含む)・未分類のアプリケーション用語・操作・前提・イベントを、定義の並び順に返す。"""
        for model in self.models:
            yield from model.walk()
        yield from self.terms
        yield from self.operations
        yield from self.preconditions
        yield from self.events


@dataclass
class Project:
    root: Path
    domains: list[Domain] = field(default_factory=list)
    roles: list[Entry] = field(default_factory=list)  # ファイル docs/system/roles.yaml に書いた順
    entries: dict[str, Entry] = field(default_factory=dict)
    # 属性の ID から、その属性の状態の遷移への対応。同じ属性に 2 つあれば先に読んだ方。検査 h の誤りがあるときは生成に使わない
    state_machines: dict[str, StateMachine] = field(default_factory=dict)


def spaced(owner: str) -> str:
    """メッセージで、定義の名前の後に「の」「に」を続けるときの形。英語名で終わる名前 (「操作 lend」) には空白を足し、
    日本語で終わる名前 (「属性 status の状態の遷移」) には足さない。"""
    return f"{owner} " if owner[-1].isascii() else owner


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
        self.load_roles()
        domains_dir = self.root / DOMAINS_DIR
        if not domains_dir.is_dir():
            self.resolve_references()
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

    def load_roles(self) -> None:
        """ファイル docs/system/roles.yaml のロールを読む。ファイルが無ければ、ロールは無い。"""
        path = self.root / ROLES_FILE
        if not path.is_file():
            return
        path_rel = ROLES_FILE.as_posix()
        data = self.read_yaml(path, path_rel)
        if data is _UNREADABLE or data is None:
            return
        for key in data:
            if key == "roles":
                self.load_list(None, data, key, "r", ROLE_KEYS, path_rel, {}, self.project.roles)
            else:
                self.unknown_key(path_rel, key, ROLES_TOP_KEYS, *_key_position(data, key))

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
        operation_names: dict[str, Entry] = {}
        precondition_names: dict[str, Entry] = {}
        event_names: dict[str, Entry] = {}
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
            if path.name.startswith(STATE_MACHINE_FILE_PREFIX):
                self.load_state_machine_file(domain, data, path_rel)
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
                elif key == "operations":
                    self.load_list(domain, data, key, "op", OPERATION_KEYS, path_rel, operation_names, domain.operations)
                elif key == "preconditions":
                    self.load_list(domain, data, key, "pre", PRECONDITION_KEYS, path_rel, precondition_names, domain.preconditions)
                elif key == "events":
                    self.load_list(domain, data, key, "ev", EVENT_KEYS, path_rel, event_names, domain.events)
                elif key == STATE_MACHINE_KEY:
                    self.problem(
                        path_rel,
                        f"キー {STATE_MACHINE_KEY} は、ファイル名が {STATE_MACHINE_FILE_PREFIX} で始まる YAML にだけ書ける "
                        "(属性の下に書くときは、属性の下に書く)",
                        line,
                        column,
                    )
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
        domain: Domain | None,
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
        if parent is not None:
            parent_parts = names.parse_id(parent.id)
        else:
            parent_parts = [Part("d", domain.name)] if domain is not None else []
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
            # 状態の遷移は属性の値を指すので、値を読んだ後に読む
            if STATE_MACHINE_KEY in mapping:
                self.load_state_machine(domain, mapping, path_rel, attribute)

    def load_terms(self, domain: Domain, data: CommentedMap, path_rel: str, seen: dict[str, Entry]) -> None:
        self.load_list(domain, data, "unclassified_app_terms", "ut", TERM_KEYS, path_rel, seen, domain.terms)

    def load_list(
        self,
        domain: Domain | None,
        data: CommentedMap,
        key: str,
        symbol: str,
        allowed: tuple[str, ...],
        path_rel: str,
        seen: dict[str, Entry],
        found: list[Entry],
    ) -> None:
        """ドメインの下に並べる種類 (未分類のアプリケーション用語・操作・前提・イベント) と、ロール (domain は None) の定義を読み、
        found に足す。"""
        mapping = self.mapping_of(data, key, path_rel)
        if mapping is None:
            return
        for name in mapping:
            entry, entry_map = self.entry(domain, mapping, name, symbol, allowed, path_rel, None)
            if entry is None:
                continue
            if name in seen:
                other = seen[name]
                self.problem(
                    path_rel, f"{entry.owner} は、{other.path}:{other.line} にもある", entry.line, entry.column
                )
                continue
            seen[name] = entry
            found.append(entry)
            for list_key in allowed:
                if (symbol, list_key) in LIST_REFERENCES and list_key in entry_map:
                    self.load_id_list(entry, entry_map, list_key, path_rel)

    def load_id_list(self, entry: Entry, mapping: CommentedMap, key: str, path_rel: str) -> None:
        entry.references += self.read_id_list(entry.owner, mapping, key, path_rel)

    def read_id_list(self, owner: str, mapping: CommentedMap, key: str, path_rel: str) -> list[Reference]:
        """完全な ID の配列で書いた参照を読む。配列でない・空・文字列でない値・同じ ID が 2 回は、問題を足す。"""
        value = mapping[key]
        not_list = f"{spaced(owner)}の {key} は、ID の文字列の配列でなければならない"
        if not isinstance(value, CommentedSeq):
            self.problem(path_rel, not_list, *_value_position(mapping, key))
            return []
        if not value:
            hint = EMPTY_LIST_HINTS.get(key, f"参照が無いときは、{key} を省く")
            self.problem(path_rel, f"{spaced(owner)}の {key} は、空の配列にできない ({hint})", *_value_position(mapping, key))
            return []
        references: list[Reference] = []
        seen: set[str] = set()
        for i, item in enumerate(value):
            line, column = _item_position(value, i)
            if not isinstance(item, str) or not item.strip():
                self.problem(path_rel, not_list, line, column)
                continue
            target = item.strip()
            if target in seen:
                self.problem(path_rel, f"{spaced(owner)}の {key} に {target} が 2 回ある", line, column)
                continue
            seen.add(target)
            references.append(Reference(key, target, line, column))
        return references

    def load_state_machine(self, domain: Domain, parent_map: CommentedMap, path_rel: str, attribute: Entry) -> None:
        """属性の下の状態の遷移を読む。形式の誤りを報告する。値・参照先は、すべての定義を読んだ後に確認する。"""
        mapping = self.mapping_of(parent_map, STATE_MACHINE_KEY, path_rel)
        if mapping is None:
            return
        for key in mapping:
            if key not in STATE_MACHINE_KEYS:
                self.unknown_key(path_rel, key, STATE_MACHINE_KEYS, *_key_position(mapping, key))
        line, column = _key_position(parent_map, STATE_MACHINE_KEY)
        machine = StateMachine(
            owner=f"{attribute.owner} の状態の遷移", domain=domain, path=path_rel, line=line, column=column,
            attribute=attribute,
        )
        if "initial" in mapping:
            machine.initial = self.state_name(machine.owner, mapping, "initial", path_rel)
        self.load_transitions(machine, mapping, path_rel)
        domain.state_machines.append(machine)

    def load_state_machine_file(self, domain: Domain, data: CommentedMap, path_rel: str) -> None:
        """ファイル名が state-machines- で始まる YAML の、トップのキー state_machine を読む。ほかのキーは誤りにする。"""
        for key in data:
            if key != STATE_MACHINE_KEY:
                self.problem(
                    path_rel,
                    f"ファイル名が {STATE_MACHINE_FILE_PREFIX} で始まる YAML には、キー {STATE_MACHINE_KEY} だけを書ける",
                    *_key_position(data, key),
                )
        if STATE_MACHINE_KEY not in data:
            return
        mapping = self.mapping_of(data, STATE_MACHINE_KEY, path_rel)
        if mapping is None:
            return
        for key in mapping:
            if key not in STATE_MACHINE_FILE_KEYS:
                self.unknown_key(path_rel, key, STATE_MACHINE_FILE_KEYS, *_key_position(mapping, key))
        line, column = _key_position(data, STATE_MACHINE_KEY)
        reference = None
        owner = STATE_MACHINE_OWNER
        if "attribute" not in mapping:
            self.problem(path_rel, f"{owner}に必須の項目 attribute が無い", line, column)
        else:
            value = mapping["attribute"]
            vline, vcolumn = _value_position(mapping, "attribute")
            if isinstance(value, str) and value.strip():
                reference = Reference("attribute", value.strip(), vline, vcolumn)
                line, column = vline, vcolumn
                owner = _owner_of_attribute_id(reference.target)
            else:
                self.problem(path_rel, f"{owner}の attribute は、属性の ID の文字列でなければならない", vline, vcolumn)
        machine = StateMachine(
            owner=owner, domain=domain, path=path_rel, line=line, column=column, attribute=None, in_file=True,
            attribute_reference=reference,
        )
        if "initial" in mapping:
            machine.initial = self.state_name(machine.owner, mapping, "initial", path_rel)
        self.load_transitions(machine, mapping, path_rel)
        domain.state_machines.append(machine)

    def state_name(self, owner: str, mapping: CommentedMap, key: str, path_rel: str) -> StateName | None:
        value = mapping[key]
        line, column = _value_position(mapping, key)
        if not isinstance(value, str) or not value.strip():
            self.problem(path_rel, f"{spaced(owner)}の {key} は、値の英語名の文字列でなければならない", line, column)
            return None
        return StateName(key, value.strip(), line, column)

    def load_transitions(self, machine: StateMachine, mapping: CommentedMap, path_rel: str) -> None:
        owner = machine.owner
        if "transitions" not in mapping:
            self.problem(path_rel, f"{spaced(owner)}に必須の項目 transitions が無い", machine.line, machine.column)
            return
        value = mapping["transitions"]
        not_list = f"{spaced(owner)}の transitions は、遷移のマッピングの配列でなければならない"
        if not isinstance(value, CommentedSeq):
            self.problem(path_rel, not_list, *_value_position(mapping, "transitions"))
            return
        if not value:
            self.problem(path_rel, f"{spaced(owner)}の transitions は、空の配列にできない", *_value_position(mapping, "transitions"))
            return
        for i, item in enumerate(value):
            line, column = _item_position(value, i)
            if not isinstance(item, CommentedMap):
                self.problem(path_rel, not_list, line, column)
                continue
            for key in item:
                if key not in TRANSITION_KEYS:
                    self.unknown_key(path_rel, key, TRANSITION_KEYS, *_key_position(item, key))
            transition = Transition(from_values=self.from_values(owner, item, path_rel, line, column), to=None, line=line, column=column)
            if "to" in item:
                transition.to = self.state_name(owner, item, "to", path_rel)
            else:
                self.problem(path_rel, f"{spaced(owner)}に必須の項目 to が無い", line, column)
            for key in TRANSITION_REFERENCES:
                if key in item:
                    transition.references += self.read_id_list(owner, item, key, path_rel)
            if not machine.in_file and "preconditions" in item:
                self.problem(
                    path_rel,
                    f"{spaced(owner)}に preconditions があるので、状態の遷移を属性の下に書けない ({MOVE_TO_FILE_HINT})",
                    *_key_position(item, "preconditions"),
                )
            machine.transitions.append(transition)

    def from_values(self, owner: str, item: CommentedMap, path_rel: str, line: int, column: int) -> list[StateName]:
        if "from" not in item:
            self.problem(path_rel, f"{spaced(owner)}に必須の項目 from が無い", line, column)
            return []
        value = item["from"]
        not_list = f"{spaced(owner)}の from は、値の英語名の配列でなければならない"
        if not isinstance(value, CommentedSeq):
            self.problem(path_rel, not_list, *_value_position(item, "from"))
            return []
        if not value:
            self.problem(path_rel, f"{spaced(owner)}の from は、空の配列にできない", *_value_position(item, "from"))
            return []
        found: list[StateName] = []
        for i, name in enumerate(value):
            nline, ncolumn = _item_position(value, i)
            if not isinstance(name, str) or not name.strip():
                self.problem(path_rel, not_list, nline, ncolumn)
                continue
            if any(n.name == name.strip() for n in found):
                self.problem(path_rel, f"{spaced(owner)}の from に {name.strip()} が 2 回ある", nline, ncolumn)
                continue
            found.append(StateName("from", name.strip(), nline, ncolumn))
        return found

    def resolve_references(self) -> None:
        entries = self.project.entries
        for role in self.project.roles:
            entries[role.id] = role
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
            for entry in domain.entries():
                for reference in entry.references:
                    self.resolve_list_reference(entry, reference)
        self.resolve_state_machines()

    def resolve_list_reference(self, entry: Entry, reference: Reference) -> None:
        kinds, kinds_text = LIST_REFERENCES[(entry.symbol, reference.key)]
        self.resolve_reference(entry.owner, entry.path, reference, kinds, kinds_text)

    def resolve_reference(self, owner: str, path: str, reference: Reference, kinds: tuple[str, ...], kinds_text: str) -> None:
        prefix = f"{spaced(owner)}の {reference.key}"
        where = (path, reference.line, reference.column)
        try:
            kind = names.kind_of(reference.target)
        except IdError as e:
            self.problem(where[0], f"{prefix} の値が ID の形でない: {e}", *where[1:])
            return
        if kind not in kinds:
            self.problem(
                where[0], f"{prefix} の参照先 {reference.target} は{kinds_text}でない (参照できるのは{kinds_text}だけ)", *where[1:]
            )
        elif reference.target not in self.project.entries:
            self.problem(where[0], f"{prefix} の参照先 {reference.target} が無い", *where[1:])

    def resolve_state_machines(self) -> None:
        """状態の遷移の参照先と、from・to・initial が属性の値であることを確認する。同じ属性の状態の遷移が 2 つあれば
        後の方を報告する。状態の遷移を、属性の ID で Project.state_machines に入れる。"""
        found = self.project.state_machines
        for domain in self.project.domains:
            for machine in domain.state_machines:
                if machine.attribute_reference is not None:
                    machine.attribute = self.resolve_attribute(machine, machine.attribute_reference)
                for transition in machine.transitions:
                    for reference in transition.references:
                        self.resolve_reference(machine.owner, machine.path, reference, *TRANSITION_REFERENCES[reference.key])
                attribute = machine.attribute
                if attribute is None:
                    continue
                if attribute.id in found:
                    other = found[attribute.id]
                    self.problem(machine.path, f"{spaced(machine.owner)}は、{other.path}:{other.line} にもある", machine.line, machine.column)
                    continue
                found[attribute.id] = machine
                self.check_states(machine, attribute)

    def resolve_attribute(self, machine: StateMachine, reference: Reference) -> Entry | None:
        """ファイルに書く状態の遷移の attribute の参照先を確認し、同じドメインの属性なら返す。"""
        before = len(self.problems)
        self.resolve_reference(STATE_MACHINE_OWNER, machine.path, reference, ("a",), "属性")
        if len(self.problems) != before:
            return None
        attribute = self.project.entries[reference.target]
        if attribute.domain is not machine.domain:
            self.problem(
                machine.path,
                f"{STATE_MACHINE_OWNER}の attribute の参照先 {reference.target} は、ほかのドメインの属性 "
                "(状態の遷移は、属性と同じドメインに書く)",
                reference.line,
                reference.column,
            )
            return None
        return attribute

    def check_states(self, machine: StateMachine, attribute: Entry) -> None:
        """from・to・initial が属性の値か、属性の下に書く形なら値の数が上限以下かを確認する。"""
        values = {value.name for value in attribute.children}
        if not values:
            self.problem(machine.path, f"{attribute.owner} は値を持たないので、状態の遷移を書けない", machine.line, machine.column)
            return
        if not machine.in_file and len(values) > ATTRIBUTE_FORM_MAX_VALUES:
            self.problem(
                machine.path,
                f"{attribute.owner} は値が {len(values)} つあるので、状態の遷移を属性の下に書けない ({MOVE_TO_FILE_HINT})",
                machine.line,
                machine.column,
            )
        for state in machine.state_names():
            if state.name not in values:
                self.problem(
                    machine.path, f"{spaced(machine.owner)}の {state.key} の値 {state.name} は、{attribute.owner} の値に無い",
                    state.line, state.column,
                )


def _owner_of_attribute_id(text: str) -> str:
    """ファイルに書く状態の遷移の、メッセージに書く名前。attribute が属性の ID の形なら「属性 status の状態の遷移」。"""
    try:
        last = names.parse_id(text)[-1]
    except IdError:
        return STATE_MACHINE_OWNER
    if last.symbol != "a":
        return STATE_MACHINE_OWNER
    return f"{names.KINDS['a'].label} {last.name} の{STATE_MACHINE_OWNER}"


def _key_position(mapping: CommentedMap, key) -> tuple[int, int]:
    line, column = mapping.lc.key(key)
    return line + 1, column + 1


def _value_position(mapping: CommentedMap, key) -> tuple[int, int]:
    line, column = mapping.lc.value(key)
    return line + 1, column + 1


def _item_position(sequence: CommentedSeq, index: int) -> tuple[int, int]:
    line, column = sequence.lc.item(index)
    return line + 1, column + 1


def load_project(root: Path) -> tuple[Project, list[Problem]]:
    """リポジトリのルートからドメインの YAML とロールの YAML を読む。検査 h の問題も返す。"""
    loader = _Loader(root)
    loader.load()
    return loader.project, loader.problems
