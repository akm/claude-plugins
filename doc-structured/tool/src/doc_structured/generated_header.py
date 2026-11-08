"""生成したファイルの先頭の記述。

生成したファイルには、決まった文字列 doc-structured:generated で始まる 1 行のコメントを、ファイルの書式のコメントで書く。
  frontmatter の無い Markdown (1 行目):
    <!-- doc-structured:generated 生成元: <パス> コマンド: <コマンド> (このファイルを直接編集せず、生成元を直して生成し直す) -->
  frontmatter のある Markdown (frontmatter の中の 2 行目)・YAML (1 行目)・シェルスクリプト (shebang の次の 2 行目):
    # doc-structured:generated 生成元: <パス> コマンド: <コマンド> (このファイルを直接編集せず、生成元を直して生成し直す)
判定の規則 (バージョンをまたいで変えない): 先頭の 3 行の中に、HTML_PREFIX か HASH_PREFIX で始まる行があれば、生成したファイル。
生成したファイルを読むときは、どの処理も関数 decode の読み方 (UTF-8 として読めないバイトは置き換え、先頭の BOM を除き、改行の CRLF と CR を LF にする) で読む。
生成元は、リポジトリのルートからの相対パス (複数の YAML から作るときはディレクトリで、末尾に「/」)。
形式の SSOT はプラグインの規則の文書 (ファイル doc-structured/rules/doc-structured-docs.md)。
sub-issue 3 の hook も、このモジュールで生成したファイルかどうかを判定する。
"""

import codecs
import re
from dataclasses import dataclass
from pathlib import Path

MARKER = "doc-structured:generated"
HTML_PREFIX = f"<!-- {MARKER} "
HASH_PREFIX = f"# {MARKER} "
HEADER_LINES = 3
NOTE = "(このファイルを直接編集せず、生成元を直して生成し直す)"
GENERATE_COMMAND = "bin/doc-structured generate"
# 生成した .gitattributes の直し方。内容は YAML ではなく生成したファイルの一覧から作るので、YAML を直す案内をしない。
# 検査 a と hook が使う
GITATTRIBUTES_GUIDE = (
    "内容は生成したファイルの一覧から作る。"
    "手で属性を足すときは、リポジトリのルートの .gitattributes に、リポジトリのルートからの相対のパターンで書く"
)

_FIELDS_RE = re.compile(r"生成元: (?P<source>\S+) コマンド: (?P<command>.+?) \(")


@dataclass(frozen=True)
class Header:
    source: str
    command: str


def _body(source: str, command: str) -> str:
    return f"{MARKER} 生成元: {source} コマンド: {command} {NOTE}"


def markdown_line(source: str, command: str = GENERATE_COMMAND) -> str:
    """frontmatter の無い Markdown の 1 行目。"""
    return f"<!-- {_body(source, command)} -->"


def hash_line(source: str, command: str = GENERATE_COMMAND) -> str:
    """YAML・シェルスクリプト・frontmatter の中に書く行。"""
    return f"# {_body(source, command)}"


def read_header(text: str) -> Header | None:
    """ファイルの内容から先頭の記述を読む。生成したファイルでなければ None。

    生成元とコマンドを取り出せないときも、生成したファイルとして扱い、空の文字列を入れて返す
    (判定の規則は先頭の文字列だけで、取り出せるかどうかに頼らないため)。
    """
    for line in text.splitlines()[:HEADER_LINES]:
        if line.startswith(HTML_PREFIX) or line.startswith(HASH_PREFIX):
            match = _FIELDS_RE.search(line)
            if match is None:
                return Header(source="", command="")
            return Header(source=match.group("source"), command=match.group("command"))
    return None


def decode(raw: bytes) -> str:
    """生成したファイルのバイト列を文字列にする。生成したファイルの読み方は、この関数だけが決める。

    UTF-8 として読めないバイトは置き換え (判定に使うのは決まった ASCII の接頭辞だけのため)、
    先頭の BOM (U+FEFF。エディタが保存のときに付けることがある) を除き、改行の CRLF と CR を LF にする
    (git の設定 core.autocrlf やエディタが改行を変えても、内容は変わっていないため)。
    """
    text = raw.decode("utf-8", errors="replace").removeprefix("\ufeff")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _is_exact(raw: bytes) -> bool:
    """バイト列を decode で読むときに、BOM の除去も、UTF-8 として読めないバイトの置き換えも無いか。改行の違いは数えない。"""
    if raw.startswith(codecs.BOM_UTF8):
        return False
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


@dataclass(frozen=True)
class FileContent:
    """関数 read_file で読んだファイル。"""

    text: str  # decode で読んだ内容
    header: Header | None  # 先頭の記述。生成したファイルでなければ None
    exact: bool  # BOM の除去も、UTF-8 として読めないバイトの置き換えも無かったか (改行の違いは数えない)

    @property
    def is_blank(self) -> bool:
        """空白と BOM (U+FEFF) だけ (空を含む) か。"""
        return self.text.replace("\ufeff", "").strip() == ""

    def matches(self, expected: str) -> bool:
        """生成し直した内容 expected と同じか。generate の書く前の比較と検査 a が、この判定を使う。"""
        return self.text == expected and self.exact


def read_file(path: str | Path) -> FileContent:
    """ファイルの全体を decode の読み方で読む。ファイルを読めないときの OSError は、呼び出し元に渡す。"""
    raw = Path(path).read_bytes()
    text = decode(raw)
    return FileContent(text=text, header=read_header(text), exact=_is_exact(raw))


def read_file_header(path: str | Path) -> Header | None:
    """ファイルの先頭の HEADER_LINES 行 (LF で区切る) を decode の読み方で読み、先頭の記述を返す。生成したファイルでなければ None。

    全体を読まずに判定する処理 (プラグインの hook (hook-scripts/guard-generated.py) と、generate の生成したファイルの一覧) が使う。
    LF で区切った先頭の 3 行は、関数 read_file が splitlines で分けた先頭の 3 行を必ず含むので、判定は read_file と同じになる。
    ファイルを読めないときの OSError は、呼び出し元に渡す。
    """
    with open(path, "rb") as f:
        head = b"".join(f.readline() for _ in range(HEADER_LINES))
    return read_header(decode(head))
