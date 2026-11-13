"""手書きの Markdown の読み取り。

検査 b・k とサブコマンド links-fix が使う要素 (ラベル・リンク・URL・定義の行・アンカー・見出し) を、行と列付きで取り出す。

- ブロックの構造 (コードブロック・HTML のブロック・段落・見出し・表の行の範囲) は、markdown-it-py で CommonMark のとおりに求める。
- 行の中のラベル・インラインコード・エスケープ・インラインの HTML は、このモジュールが自分で読む
  (markdown-it-py は行の範囲を返すが列を返さず、定義の無いラベルをただの文字列として扱うため)。
- コードブロック・mermaid の図・HTML のブロックの中は読まない。行の中では、インラインコード・HTML のコメントとタグ・
  エスケープした「\\[」の中を読まない。
- 画像 (![説明](パス)・![説明][ラベル]) は、リンクとして読まない。reference-style の画像のラベルだけを image_labels に残す
  (その定義の行を、リンクの規則の対象から外すため)。脚注 ([^1])・タスクリストのチェックボックス ([ ]・[x])・
  GitHub の注記 ([!NOTE] など) はラベルとして扱わない。

行と列は 1 から数える。列は文字 (コードポイント) で数える。
書き方の扱いの SSOT は、プラグインの規則の文書 (ファイル doc-structured/rules/doc-structured-docs.md)。
"""

import re
from dataclasses import dataclass, field

from markdown_it import MarkdownIt

# CommonMark で、バックスラッシュでエスケープできる文字 (ASCII の記号)
ASCII_PUNCTUATION = set("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")

# 定義の行。CommonMark の link reference definition のうち、1 行に書いたもの
DEFINITION_RE = re.compile(
    r"^(?P<indent> {0,3})\[(?P<label>(?:[^\[\]\\]|\\.)+)\]:[ \t]*"
    r"(?P<destination><[^<>\n]*>|\S+)"
    r"(?:(?P<space>[ \t]+)(?P<title>\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'|\((?:[^()\\]|\\.)*\)))?"
    r"[ \t]*$"
)
# 行の全体に書いたアンカー
ANCHOR_RE = re.compile(r'^\s*<a name="(?P<name>[^"]*)"></a>\s*$')
# 行頭のタスクリストのチェックボックス。引用とリストの記号の後の [ ]・[x]・[X]
TASK_RE = re.compile(r"^[ \t>]*(?:[-+*]|\d{1,9}[.)])[ \t]+(?P<box>\[[ xX]\])(?=[ \t]|$)")
# 引用の先頭の GitHub の注記 ([!NOTE] など)
ALERT_RE = re.compile(r"^[ \t>]*>[ \t]*(?P<alert>\[![A-Za-z]+\])[ \t]*$")
# 山括弧で囲んだ URL (CommonMark の autolink)
AUTOLINK_RE = re.compile(r"<(?P<url>[A-Za-z][A-Za-z0-9+.\-]{1,31}:[^\s<>]*)>")
# メールアドレスの autolink
EMAIL_AUTOLINK_RE = re.compile(r"<(?P<url>[A-Za-z0-9.!#$%&'*+/=?^_`{|}~\-]+@[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?)*)>")
# インラインの HTML のタグ
HTML_TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9\-]*(?:\s+[^<>]*?)?/?>")
# 文中にそのまま書いた URL。空白・山括弧・ASCII 以外の文字の手前までを URL とする
BARE_URL_RE = re.compile(r"https?://[\x21-\x3b\x3d\x3f-\x7e]+")
# 文中にそのまま書いた URL の末尾から除く文字 (文の句読点として書くことが多いもの)
BARE_URL_TRAILING = ".,:;!?'\")]*_~"


@dataclass(frozen=True)
class Reference:
    """reference-style のリンクの、本文での使用。"""

    form: str  # "shortcut" ([ラベル])・"full" ([文][ラベル])・"collapsed" ([ラベル][])
    text: str  # 最初の角括弧の中
    label: str  # 定義の行と比べるラベル。shortcut と collapsed では text と同じ
    line: int
    column: int  # 最初の「[」の列
    label_line: int  # ラベルの「[」の行 (shortcut と collapsed では line と同じ)
    label_column: int
    end_line: int  # リンクの最後の「]」がある行
    end_column: int  # リンクの最後の「]」がある列


@dataclass(frozen=True)
class InlineLink:
    """[文](URL) の形のリンク。"""

    text: str
    destination: str
    line: int
    column: int


@dataclass(frozen=True)
class Url:
    """<URL> の形のリンク (form が "autolink") と、文中にそのまま書いた URL (form が "bare")。"""

    form: str
    url: str
    line: int
    column: int


@dataclass(frozen=True)
class Definition:
    """定義の行。"""

    label: str  # 角括弧の中 (エスケープはそのまま)
    destination: str  # 書いたとおり (山括弧で囲んだものは囲みを含む)
    title: str | None  # 引用符の中 (エスケープはそのまま)。title が無ければ None
    quote: str | None  # title の開きの引用符 (「"」「'」「(」)
    line: int
    column: int  # 「[」の列
    in_paragraph: bool  # 直前の段落の一部になり、CommonMark では定義の行として読まれない
    title_start: int  # 行の中の、title の開きの引用符の位置 (0 から数える)。title が無ければ行の長さ

    @property
    def title_text(self) -> str | None:
        """title のエスケープを解いた文。"""
        return None if self.title is None else unescape(self.title)


@dataclass(frozen=True)
class Anchor:
    name: str
    line: int
    column: int


@dataclass(frozen=True)
class Heading:
    level: int
    text: str  # 行頭の「#」と前後の空白、末尾の閉じの「#」を除いた文
    line: int
    atx: bool  # 「#」で書いた見出しなら True、下線 (=== や ---) で書いた見出しなら False


@dataclass
class Document:
    lines: list[str]  # 改行を除いた行
    references: list[Reference] = field(default_factory=list)
    inline_links: list[InlineLink] = field(default_factory=list)
    urls: list[Url] = field(default_factory=list)
    definitions: list[Definition] = field(default_factory=list)
    anchors: list[Anchor] = field(default_factory=list)
    headings: list[Heading] = field(default_factory=list)
    # reference-style の画像 (![説明][ラベル]・![ラベル][]・![ラベル]) が使うラベル
    image_labels: list[str] = field(default_factory=list)
    # 本文の行数。末尾の定義の行のまとまり (定義の行と、その間と前後の空行) を除いた、先頭からの行数
    body_end: int = 0

    def definition_lines(self) -> set[int]:
        return {d.line for d in self.definitions}

    def next_nonblank(self, line: int) -> int | None:
        """line (1 から数える) の後の、空行でない最初の行。無ければ None。"""
        for index in range(line, len(self.lines)):
            if self.lines[index].strip():
                return index + 1
        return None

    def first_nonblank(self) -> int | None:
        return self.next_nonblank(0)

    def heading_at(self, line: int) -> Heading | None:
        for heading in self.headings:
            if heading.line == line:
                return heading
        return None


def normalize_label(label: str) -> str:
    """CommonMark のとおりにラベルを比べる形にする (英字の大文字と小文字の違いと、連続する空白の違いを無視する)。"""
    return " ".join(label.split()).casefold()


def unescape(text: str) -> str:
    """バックスラッシュのエスケープを解く。"""
    result = []
    i = 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text) and text[i + 1] in ASCII_PUNCTUATION:
            result.append(text[i + 1])
            i += 2
            continue
        result.append(text[i])
        i += 1
    return "".join(result)


def escape_title(text: str, quote: str) -> str:
    """title に書く文を、引用符の種類に合わせてエスケープする。"""
    text = text.replace("\\", "\\\\")
    if quote == '"':
        return text.replace('"', '\\"')
    if quote == "'":
        return text.replace("'", "\\'")
    return text.replace("(", "\\(").replace(")", "\\)")


def closing_quote(quote: str) -> str:
    return ")" if quote == "(" else quote


def heading_text(line: str) -> str:
    """「#」で書いた見出しの行から、見出しの文を取り出す。"""
    text = line.strip()
    text = text.lstrip("#")
    text = text.strip()
    # 末尾の閉じの「#」は、前に空白があるときだけ除く (CommonMark のとおり)
    match = re.search(r"(?:^|[ \t])#+$", text)
    if match:
        text = text[: match.start()]
    return text.strip()


_PARSER = MarkdownIt("commonmark").enable("table")


def parse(text: str) -> Document:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    document = Document(lines=lines)
    tokens = _PARSER.parse("\n".join(lines) + "\n")

    code_lines: set[int] = set()  # 0 から数える。コードブロック・HTML のブロックの行
    inline_ranges: list[tuple[int, int]] = []
    paragraph_lines: set[int] = set()
    for token in tokens:
        if token.map is None:
            continue
        start, end = token.map
        if token.type in ("fence", "code_block", "html_block"):
            code_lines.update(range(start, end))
        elif token.type == "inline":
            if (start, end) not in inline_ranges:
                inline_ranges.append((start, end))
        elif token.type == "paragraph_open":
            paragraph_lines.update(range(start, end))
        elif token.type == "heading_open":
            if token.markup.startswith("#"):
                document.headings.append(
                    Heading(len(token.markup), heading_text(lines[start]), start + 1, True)
                )
            else:
                level = 1 if token.markup == "=" else 2
                document.headings.append(Heading(level, lines[start].strip(), start + 1, False))

    definition_indexes: set[int] = set()
    for index, line in enumerate(lines):
        if index in code_lines:
            continue
        match = DEFINITION_RE.match(line)
        if match and not match.group("label").startswith("^"):
            title = match.group("title")
            document.definitions.append(
                Definition(
                    label=match.group("label"),
                    destination=match.group("destination"),
                    title=title[1:-1] if title else None,
                    quote=title[0] if title else None,
                    line=index + 1,
                    column=len(match.group("indent")) + 1,
                    in_paragraph=index in paragraph_lines,
                    title_start=match.start("title") if title else len(line),
                )
            )
            definition_indexes.add(index)
            continue
        anchor = ANCHOR_RE.match(line)
        if anchor:
            document.anchors.append(Anchor(anchor.group("name"), index + 1, line.index("<") + 1))

    for start, end in inline_ranges:
        _InlineScanner(document, lines, start, end, definition_indexes).scan()

    document.references.sort(key=lambda r: (r.line, r.column))
    document.inline_links.sort(key=lambda r: (r.line, r.column))
    document.urls.sort(key=lambda r: (r.line, r.column))
    document.body_end = _body_end(lines, definition_indexes)
    return document


def _body_end(lines: list[str], definition_indexes: set[int]) -> int:
    index = len(lines)
    found = False
    while index > 0:
        previous = index - 1
        if previous in definition_indexes:
            found = True
        elif lines[previous].strip():
            break
        index -= 1
    return index if found else len(lines)


class _InlineScanner:
    """段落・見出し・表の 1 つのブロックの中の、行の中の要素を読む。"""

    def __init__(self, document: Document, lines: list[str], start: int, end: int, skip: set[int]):
        self.document = document
        # 定義の行 (段落の一部になったもの) は、行の中の要素として読まない
        kept = [i for i in range(start, end) if i not in skip]
        self.text = ""
        self.positions: list[tuple[int, int]] = []  # text の各文字の (行, 列)。どちらも 1 から数える
        self.line_starts: dict[int, int] = {}  # text の中の、各行の先頭の位置
        for i in kept:
            self.line_starts[i] = len(self.text)
            for column, _ in enumerate(lines[i]):
                self.positions.append((i + 1, column + 1))
            self.text += lines[i]
            self.positions.append((i + 1, len(lines[i]) + 1))
            self.text += "\n"
        self.ignored: set[int] = set()  # ラベルとして扱わない「[」の位置
        for i in kept:
            for regex, group in ((TASK_RE, "box"), (ALERT_RE, "alert")):
                match = regex.match(lines[i])
                if match:
                    self.ignored.add(self.line_starts[i] + match.start(group))

    def position(self, offset: int) -> tuple[int, int]:
        return self.positions[offset]

    def scan(self) -> None:
        text = self.text
        i = 0
        while i < len(text):
            char = text[i]
            if char == "\\" and i + 1 < len(text) and text[i + 1] in ASCII_PUNCTUATION:
                i += 2
            elif char == "`":
                i = self.skip_code(i)
            elif char == "<":
                i = self.read_angle(i)
            elif char == "!" and text.startswith("[", i + 1):
                i = self.skip_image(i + 1)
            elif char == "[":
                i = self.read_bracket(i)
            elif text.startswith(("http://", "https://"), i) and (i == 0 or not text[i - 1].isalnum()):
                i = self.read_bare_url(i)
            else:
                i += 1

    def skip_code(self, i: int) -> int:
        """インラインコードを読み飛ばす。閉じが無ければ、バッククォートの並びだけを読み飛ばす。"""
        text = self.text
        run_end = i
        while run_end < len(text) and text[run_end] == "`":
            run_end += 1
        run = run_end - i
        j = run_end
        while j < len(text):
            if text[j] == "`":
                k = j
                while k < len(text) and text[k] == "`":
                    k += 1
                if k - j == run:
                    return k
                j = k
            else:
                j += 1
        return run_end

    def angle_end(self, i: int) -> tuple[int, str | None]:
        """text[i] の「<」で始まる要素 (HTML のコメント・autolink・HTML のタグ) の終わりの位置と、autolink なら その URL。
        どれでもなければ、「<」の次の位置。"""
        text = self.text
        if text.startswith("<!--", i):
            end = text.find("-->", i + 4)
            return (len(text) if end < 0 else end + 3), None
        for regex in (AUTOLINK_RE, EMAIL_AUTOLINK_RE):
            match = regex.match(text, i)
            if match:
                return match.end(), match.group("url")
        match = HTML_TAG_RE.match(text, i)
        if match:
            return match.end(), None
        return i + 1, None

    def read_angle(self, i: int) -> int:
        end, url = self.angle_end(i)
        if url is not None:
            line, column = self.position(i)
            self.document.urls.append(Url("autolink", url, line, column))
        return end

    def read_bare_url(self, i: int) -> int:
        match = BARE_URL_RE.match(self.text, i)
        url = match.group(0).rstrip(BARE_URL_TRAILING)
        if url.endswith("://") or len(url) <= len("https://"):
            return i + len(url) if url else i + 1
        line, column = self.position(i)
        self.document.urls.append(Url("bare", url, line, column))
        return i + len(url)

    def matching_bracket(self, i: int) -> int | None:
        """text[i] の「[」に対応する「]」の位置。インラインコードとエスケープの中の角括弧は数えない。"""
        text = self.text
        depth = 0
        j = i
        while j < len(text):
            char = text[j]
            if char == "\\" and j + 1 < len(text) and text[j + 1] in ASCII_PUNCTUATION:
                j += 2
                continue
            if char == "`":
                j = self.skip_code(j)
                continue
            if char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    return j
            j += 1
        return None

    def matching_paren(self, i: int) -> int | None:
        text = self.text
        depth = 0
        j = i
        while j < len(text):
            char = text[j]
            if char == "\\" and j + 1 < len(text) and text[j + 1] in ASCII_PUNCTUATION:
                j += 2
                continue
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return j
            j += 1
        return None

    def skip_image(self, i: int) -> int:
        close = self.matching_bracket(i)
        if close is None:
            return i + 1
        after = close + 1
        if self.text.startswith("(", after):
            paren = self.matching_paren(after)
            if paren is not None:
                return paren + 1
        inner = self.text[i + 1 : close]
        if self.text.startswith("[", after):
            label_close = self.matching_bracket(after)
            if label_close is not None:
                label = self.text[after + 1 : label_close]
                self.document.image_labels.append(label if label.strip() else inner)
                return label_close + 1
        if inner.strip():
            self.document.image_labels.append(inner)
        return after

    def scan_images(self, start: int, end: int) -> None:
        """text[start:end] (リンクの文) の中の画像を読む。エスケープ・インラインコード・HTML・autolink の中は読まない。"""
        text = self.text
        j = start
        while j < end:
            char = text[j]
            if char == "\\" and j + 1 < len(text) and text[j + 1] in ASCII_PUNCTUATION:
                j += 2
            elif char == "`":
                j = self.skip_code(j)
            elif char == "<":
                j = self.angle_end(j)[0]
            elif char == "!" and text.startswith("[", j + 1):
                j = self.skip_image(j + 1)
            else:
                j += 1

    def read_bracket(self, i: int) -> int:
        text = self.text
        if i in self.ignored or text.startswith("[^", i):
            close = self.matching_bracket(i)
            return i + 1 if close is None else close + 1
        close = self.matching_bracket(i)
        if close is None:
            return i + 1
        inner = text[i + 1 : close]
        if not inner.strip():
            # [] はリンクにならない (CommonMark のとおり)
            return close + 1
        line, column = self.position(i)
        # リンクの文の中の画像 ([![CI][ci-badge]][ci] のようなバッジ) のラベルも残す
        self.scan_images(i + 1, close)
        after = close + 1
        if text.startswith("(", after):
            paren = self.matching_paren(after)
            if paren is not None:
                destination = text[after + 1 : paren].strip().split(maxsplit=1)
                self.document.inline_links.append(
                    InlineLink(inner, destination[0] if destination else "", line, column)
                )
                return paren + 1
        if text.startswith("[", after):
            label_close = self.matching_bracket(after)
            if label_close is not None:
                label = text[after + 1 : label_close]
                label_line, label_column = self.position(after)
                end = self.position(label_close)
                if label.strip():
                    self.document.references.append(
                        Reference("full", inner, label, line, column, label_line, label_column, *end)
                    )
                else:
                    self.document.references.append(
                        Reference("collapsed", inner, inner, line, column, line, column, *end)
                    )
                return label_close + 1
        self.document.references.append(
            Reference("shortcut", inner, inner, line, column, line, column, *self.position(close))
        )
        return after
