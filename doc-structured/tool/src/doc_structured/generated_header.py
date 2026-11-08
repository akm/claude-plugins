"""生成したファイルの先頭の記述。

生成したファイルには、決まった文字列 doc-structured:generated で始まる 1 行のコメントを、ファイルの書式のコメントで書く。
  frontmatter の無い Markdown (1 行目):
    <!-- doc-structured:generated 生成元: <パス> コマンド: <コマンド> (このファイルを直接編集せず、生成元を直して生成し直す) -->
  frontmatter のある Markdown (frontmatter の中の 2 行目)・YAML (1 行目)・シェルスクリプト (shebang の次の 2 行目):
    # doc-structured:generated 生成元: <パス> コマンド: <コマンド> (このファイルを直接編集せず、生成元を直して生成し直す)
判定の規則 (バージョンをまたいで変えない): 先頭の 3 行の中に、HTML_PREFIX か HASH_PREFIX で始まる行があれば、生成したファイル。
生成元は、リポジトリのルートからの相対パス (複数の YAML から作るときはディレクトリで、末尾に「/」)。
形式の SSOT はプラグインの規則の文書 (ファイル doc-structured/rules/doc-structured-docs.md)。
sub-issue 3 の hook も、このモジュールで生成したファイルかどうかを判定する。
"""

import re
from dataclasses import dataclass
from pathlib import Path

MARKER = "doc-structured:generated"
HTML_PREFIX = f"<!-- {MARKER} "
HASH_PREFIX = f"# {MARKER} "
HEADER_LINES = 3
NOTE = "(このファイルを直接編集せず、生成元を直して生成し直す)"
GENERATE_COMMAND = "bin/doc-structured generate"

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


def read_file_header(path: str | Path) -> Header | None:
    """ファイルの先頭の HEADER_LINES 行を読み、先頭の記述を返す。生成したファイルでなければ None。

    ツールの generate と、プラグインの hook (hook-scripts/guard-generated.py) の両方がこの関数で判定する。
    文字コードは UTF-8 で、読めないバイトは置き換えて読む (判定に使うのは決まった ASCII の接頭辞だけのため)。
    ファイルを読めないときの OSError は、呼び出し元に渡す。
    """
    with open(path, encoding="utf-8", errors="replace") as f:
        head = "".join(f.readline() for _ in range(HEADER_LINES))
    return read_header(head)
