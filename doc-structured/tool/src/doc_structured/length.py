"""検査 k (手書きの Markdown の行数)。

ドメインのディレクトリの下の手書きの Markdown (子のファイルを含む) が上限の 100 行を超えていて、理由のコメントが無ければ報告する。
指針の 50 行を超えただけでは報告しない。形式の SSOT はプラグインの規則の文書 (ファイル doc-structured/rules/doc-structured-docs.md)。
  - 数えるのは、ファイルの先頭から、末尾の定義の行のまとまり (定義の行と、その間と前後の空行) の直前まで
  - 理由のコメントは「<!-- 行数が上限を超える理由: <理由> -->」の 1 行で、「#」の見出しの次 (空行を除く) の行に書く。
    理由が空でないことだけを確かめ、中身は検査しない
検査 k は YAML を使わないので、YAML に誤りがあっても実行する。
"""

import re

from .documents import HandwrittenFile, Index
from .problems import Problem

LIMIT = 100
REASON_PREFIX = "<!-- 行数が上限を超える理由: "
REASON_RE = re.compile(r"^<!-- 行数が上限を超える理由: (?P<reason>.*?)\s*-->\s*$")


def _reason_line(handwritten: HandwrittenFile) -> int | None:
    """理由のコメントを書く行 (「#」の見出しの次の、空行でない行。1 から数える)。見出しが無ければ None。"""
    document = handwritten.document
    heading = next((h for h in document.headings if h.atx and h.level == 1), None)
    if heading is None:
        return None
    return document.next_nonblank(heading.line)


def check_length(index: Index) -> list[Problem]:
    problems: list[Problem] = []
    for handwritten in index.files:
        document = handwritten.document
        count = document.body_end
        if count <= LIMIT:
            continue
        line = _reason_line(handwritten)
        text = document.lines[line - 1] if line else ""
        match = REASON_RE.match(text)
        if match and match.group("reason").strip():
            continue
        if match:
            problems.append(Problem("k", handwritten.path, "理由のコメントの理由が空", line, 1))
            continue
        how = (
            f"話題ごとにファイルを分けるか、「#」の見出しの次の行に理由のコメント {REASON_PREFIX}<理由> --> を書く"
        )
        elsewhere = next((i + 1 for i, t in enumerate(document.lines) if t.startswith(REASON_PREFIX)), None)
        if elsewhere is not None:
            problems.append(
                Problem("k", handwritten.path, f"理由のコメントは、「#」の見出しの次の行に書く ({count} 行。上限は {LIMIT} 行)", elsewhere, 1)
            )
            continue
        problems.append(Problem("k", handwritten.path, f"手書きの Markdown が {count} 行ある (上限は {LIMIT} 行)。{how}"))
    return problems
