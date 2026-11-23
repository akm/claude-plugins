"""YAML のファイルを、行の単位で書き換える (サブコマンド impl-diff-resolve が使う)。

ruamel.yaml で読んで書き換える場所 (キーの行と桁、次のキーの行) を求め、元の文字列の行を足す・消す・置き換える。
書き換えない行は 1 文字も変えない。ruamel.yaml の round-trip モードで書き出さないのは、ツールの設定と違うインデントの
ファイルの全体が書き換わり、消したキーの直前のコメントが残って次のキーの直前のコメントが消えるため
(決めた経緯は Issue #208 のコメントの 8)。

  - 足す行のインデントは、そのマッピングのほかのキー (配列なら、ほかの項目の「-」) に合わせる。新しく作る入れ子の
    インデントは、ファイルの中の既存の入れ子から求める
  - 消す項目は、キーの行から次の兄弟の項目の直前までを消し、その項目の直前に空行を挟まずに書かれたコメントの行も
    一緒に消す。項目の後ろのコメントのうち、項目のキーより深く下げていないものは、次の項目のコメントとして残す
  - 書き換えるたびに、書き換えた文字列を再度読み込み、読んだ構造に同じ書き換えを加えたものと一致するかを確認する。
    一致しなければ YamlEditError を投げる
  - フロースタイル (`{...}`) のマッピングの中は書き換えず、YamlEditError を投げる
"""

import copy
from typing import Any

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from . import yamlio

FLOW_STYLE_MESSAGE = "フロースタイルで書かれているので書き換えられない。ブロックスタイルで書いてから実行する"


class YamlEditError(Exception):
    """書き換えられない。メッセージは利用者に見せる文。"""


class Double(str):
    """二重引用符で囲んで書く文字列。"""


class Flow(list):
    """フロースタイル (`[a, b]`) で書く配列。項目は文字列だけ。"""


Path = tuple  # マッピングのキーと配列の位置を、ドキュメントの根から順に並べたもの


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _blank(line: str) -> bool:
    return not line.strip()


def _comment(line: str) -> bool:
    return line.lstrip(" ").startswith("#")


def _is_flow(node: Any) -> bool:
    return isinstance(node, (CommentedMap, CommentedSeq)) and bool(node.fa.flow_style())


# ---------------------------------------------------------------- 値を文字列にする


def _double_quoted(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
    return f'"{escaped}"'


def _plain_safe(text: str) -> bool:
    """引用符で囲まずに書いても、同じ文字列として読まれるか。"""
    if not text or text != text.strip() or "\n" in text:
        return False
    try:
        data = yamlio.load(f"k: {text}\n")
    except Exception:  # ruamel.yaml の読み込みの誤りは、引用符で囲む理由になる
        return False
    return isinstance(data, CommentedMap) and list(data) == ["k"] and type(data["k"]).__name__ in ("str",) and data["k"] == text


def scalar(value: Any) -> str:
    """スカラーか、フロースタイルの配列を、YAML の 1 行の値にする。"""
    if value is True:
        return "true"
    if isinstance(value, Flow):
        return "[" + ", ".join(scalar(item) for item in value) + "]"
    if isinstance(value, Double):
        return _double_quoted(str(value))
    if isinstance(value, str):
        return value if _plain_safe(value) else _double_quoted(value)
    raise TypeError(f"書けない値: {value!r}")


# ---------------------------------------------------------------- 比べるための形


def _python(node: Any) -> Any:
    """ruamel.yaml の値を、dict・list・スカラーにする (書き換えを加えて、再度読み込んだ値と比べるため)。"""
    if isinstance(node, dict):
        return {key: _python(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_python(item) for item in node]
    if isinstance(node, str):
        return str(node)
    return node


def _canonical(value: Any) -> Any:
    """キーの順序も比べる形。"""
    if isinstance(value, dict):
        return ("map", [(key, _canonical(item)) for key, item in value.items()])
    if isinstance(value, list):
        return ("seq", [_canonical(item) for item in value])
    return (type(value).__name__, value)


def _insert_at(mapping: dict, index: int, key: str, value: Any) -> dict:
    items = list(mapping.items())
    items.insert(index, (key, value))
    mapping.clear()
    mapping.update(items)
    return mapping


# ---------------------------------------------------------------- ドキュメント


class Document:
    """1 つの YAML のファイルの文字列と、それを読んだ構造。書き換えは、このクラスのメソッドで行う。"""

    def __init__(self, text: str):
        if text and not text.endswith("\n"):
            text += "\n"
        self.lines = text.splitlines(keepends=True)
        self.data = yamlio.load(text)

    @property
    def text(self) -> str:
        return "".join(self.lines)

    # ---- 場所を求める

    def node(self, path: Path) -> Any:
        node = self.data
        for key in path:
            node = node[key]
        return node

    def _mapping(self, path: Path) -> CommentedMap:
        node = self.data
        for i, key in enumerate(path):
            if _is_flow(node):
                raise YamlEditError(f"{self._where(path[:i])}は{FLOW_STYLE_MESSAGE}")
            node = node[key]
        if not isinstance(node, CommentedMap):
            raise YamlEditError(f"{self._where(path)}は、キーと値のマッピングでない")
        if _is_flow(node):
            raise YamlEditError(f"{self._where(path)}は{FLOW_STYLE_MESSAGE}")
        return node

    def _where(self, path: Path) -> str:
        if not path:
            return "ファイルの全体"
        return " の ".join(str(key) if not isinstance(key, int) else f"{key + 1} 番目" for key in path) + " "

    def _block_end(self, start: int, col: int, sequence_value: bool) -> int:
        """start の行から始まる項目の、次の兄弟 (か親の兄弟) の行。col より深く下げた行・空行・コメントの行は項目に含める。
        sequence_value が真なら、col と同じ桁の「-」で始まる行 (キーと同じ桁に書いた配列の項目) も含める。"""
        i = start + 1
        while i < len(self.lines):
            line = self.lines[i]
            if _blank(line) or _comment(line):
                i += 1
                continue
            indent = _indent(line)
            if indent > col or (sequence_value and indent == col and line.lstrip(" ").startswith("-")):
                i += 1
                continue
            break
        return i

    def _core_end(self, start: int, end: int, col: int) -> int:
        """項目の行の範囲 [start, end) の末尾から、空行と、col より深く下げていないコメントの行 (次の項目のコメント) を除く。"""
        while end > start + 1:
            line = self.lines[end - 1]
            if _blank(line) or (_comment(line) and _indent(line) <= col):
                end -= 1
                continue
            break
        return end

    def _lead_start(self, start: int, col: int) -> int:
        """項目の直前に、空行を挟まずに col と同じ桁で書かれたコメントの行の始まり。"""
        while start > 0 and _comment(self.lines[start - 1]) and _indent(self.lines[start - 1]) == col:
            start -= 1
        return start

    def _key_range(self, mapping: CommentedMap, key: str) -> tuple[int, int, int, int]:
        """キーの (コメントを含む始まり, キーの行, 中身の終わり, キーの桁)。"""
        start, col = mapping.lc.key(key)
        value = mapping[key]
        sequence_value = isinstance(value, CommentedSeq) and not _is_flow(value)
        end = self._block_end(start, col, sequence_value)
        return self._lead_start(start, col), start, self._core_end(start, end, col), col

    def _item_range(self, sequence: CommentedSeq, index: int) -> tuple[int, int, int, int]:
        """配列の項目の (コメントを含む始まり, 項目の行, 中身の終わり, 「-」の桁)。"""
        start, col = sequence.lc.item(index)
        dash = self.lines[start].rfind("-", 0, col)
        if dash < 0 or self.lines[start][:dash].strip():
            raise YamlEditError("配列の項目の「-」の位置を求められない")
        end = self._block_end(start, dash, False)
        return self._lead_start(start, dash), start, self._core_end(start, end, dash), dash

    def _shares_line(self, mapping: CommentedMap, key: str) -> bool:
        """キーが、配列の項目の「-」と同じ行に書かれているか (その行は、キーだけを消したり置き換えたりできない)。"""
        line, col = mapping.lc.key(key)
        return bool(self.lines[line][:col].strip())

    # ---- インデント

    def _units(self) -> tuple[int, int, int]:
        """(入れ子のマッピングのインデント, 配列の「-」の親のキーからのインデント, 「-」から項目の中身までの桁数)。
        ファイルの中の既存の入れ子から求め、無ければ 2・マッピングと同じ・2 にする。"""
        unit = seq_dash = seq_content = None

        def walk(node: Any) -> None:
            nonlocal unit, seq_dash, seq_content
            if not isinstance(node, CommentedMap) or _is_flow(node):
                return
            for key, value in node.items():
                if unit is None and isinstance(value, CommentedMap) and value and not _is_flow(value):
                    unit = value.lc.key(next(iter(value)))[1] - node.lc.key(key)[1]
                if seq_dash is None and isinstance(value, CommentedSeq) and value and not _is_flow(value):
                    line, col = value.lc.item(0)
                    dash = self.lines[line].rfind("-", 0, col)
                    if dash >= 0:
                        seq_dash = dash - node.lc.key(key)[1]
                        seq_content = col - dash
                walk(value)
                if isinstance(value, CommentedSeq):
                    for item in value:
                        walk(item)

        walk(self.data)
        unit = unit if unit and unit > 0 else 2
        if seq_dash is None or seq_dash < 0:
            seq_dash = unit
        if not seq_content or seq_content < 2:
            seq_content = 2
        return unit, seq_dash, seq_content

    def render(self, key: str, value: Any, col: int) -> list[str]:
        """キーと値を、桁 col から書いた行にする。値が dict なら入れ子のマッピング、dict の list なら配列にする。"""
        unit, seq_dash, seq_content = self._units()
        return _render(key, value, col, unit, seq_dash, seq_content)

    def render_item(self, item: dict, dash: int) -> list[str]:
        unit, seq_dash, seq_content = self._units()
        return _render_item(item, dash, unit, seq_dash, seq_content)

    # ---- 書き換え

    def _apply(self, new_lines: list[str], expected: Any) -> None:
        """行を置き換え、再度読み込んだ構造が expected と一致するかを確認する。"""
        text = "".join(new_lines)
        try:
            data = yamlio.load(text)
        except Exception as e:  # 書き換えた文字列が YAML として読めないのは、ツールの誤り
            raise YamlEditError(f"書き換えた YAML を読めない (ツールの誤り): {e}") from e
        if _canonical(_python(data)) != _canonical(expected):
            raise YamlEditError("書き換えた YAML が、意図した内容と一致しない (ツールの誤り)")
        self.lines = new_lines
        self.data = data

    def _expected(self) -> Any:
        return copy.deepcopy(_python(self.data))

    def _separated(self, mapping: CommentedMap) -> bool:
        """マッピングの項目 (2 つ目以降) の前に空行があるか (新しい項目の前後にも空行を入れる)。"""
        keys = list(mapping)
        if len(keys) < 2:
            return False
        lead, _, _, _ = self._key_range(mapping, keys[1])
        return lead > 0 and _blank(self.lines[lead - 1])

    def insert_key(self, path: Path, key: str, value: Any, index: int) -> None:
        """マッピングの index 番目 (0 から数える。キーの数なら最後) に、キーと値を足す。"""
        mapping = self._mapping(path)
        keys = list(mapping)
        if key in mapping:
            raise YamlEditError(f"{self._where(path)}には、すでに {key} がある")
        if not keys:
            raise YamlEditError(f"{self._where(path)}が空なので、キーを足す位置を決められない")
        col = mapping.lc.key(keys[0])[1]
        rendered = self.render(key, value, col)
        separated = self._separated(mapping) and isinstance(value, dict)
        if index < len(keys):
            if self._shares_line(mapping, keys[index]):
                raise YamlEditError(f"{self._where(path)}の {keys[index]} の前には、キーを足せない")
            at, _, _, _ = self._key_range(mapping, keys[index])
            insert = rendered + (["\n"] if separated else [])
        else:
            _, _, at, _ = self._key_range(mapping, keys[-1])
            insert = (["\n"] if separated else []) + rendered
        expected = self._expected()
        _insert_at(self._resolve(expected, path), index, key, _python(value))
        self._apply(self.lines[:at] + insert + self.lines[at:], expected)

    def set_key(self, path: Path, key: str, value: Any, order: tuple[str, ...]) -> None:
        """キーの値を書き換える。キーが無ければ、order (キーの順) で前にあるキーの後ろに足す。"""
        mapping = self._mapping(path)
        if key not in mapping:
            self.insert_key(path, key, value, self._index_by_order(mapping, key, order))
            return
        if self._shares_line(mapping, key):
            raise YamlEditError(f"{self._where(path)}の {key} は、配列の項目の「-」と同じ行にあるので書き換えられない")
        lead, start, core_end, col = self._key_range(mapping, key)
        rendered = self.render(key, value, col)
        if len(rendered) == 1 and core_end == start + 1:
            comment = self._eol_comment(mapping, key, start)
            if comment:
                rendered = [rendered[0].rstrip("\n") + "  " + comment + "\n"]
        expected = self._expected()
        self._resolve(expected, path)[key] = _python(value)
        self._apply(self.lines[:start] + rendered + self.lines[core_end:], expected)

    def _eol_comment(self, mapping: CommentedMap, key: str, line: int) -> str:
        """キーの行の、値の後ろのコメント (「#」から行末まで)。無ければ空。"""
        tokens = mapping.ca.items.get(key)
        if not tokens or len(tokens) < 3 or tokens[2] is None:
            return ""
        token = tokens[2]
        if token.start_mark.line != line:
            return ""
        return self.lines[line][token.start_mark.column :].rstrip("\n")

    def _index_by_order(self, mapping: CommentedMap, key: str, order: tuple[str, ...]) -> int:
        rank = order.index(key) if key in order else len(order)
        index = 0
        for i, existing in enumerate(mapping):
            if existing in order and order.index(existing) < rank:
                index = i + 1
        return index

    def delete_key(self, path: Path, key: str) -> None:
        """キーを、値と直前のコメントごと消す。"""
        mapping = self._mapping(path)
        if key not in mapping:
            raise YamlEditError(f"{self._where(path)}に {key} が無い")
        if len(mapping) == 1:
            raise YamlEditError(f"{self._where(path)}の最後のキー {key} は消せない")
        if self._shares_line(mapping, key):
            raise YamlEditError(f"{self._where(path)}の {key} は、配列の項目の「-」と同じ行にあるので消せない")
        lead, _, core_end, col = self._key_range(mapping, key)
        expected = self._expected()
        del self._resolve(expected, path)[key]
        self._apply(self._without(lead, core_end, col), expected)

    def append_item(self, path: Path, item: dict) -> None:
        """配列の最後に、マッピングの項目を足す。"""
        sequence = self.node(path)
        if not isinstance(sequence, CommentedSeq) or not sequence:
            raise YamlEditError(f"{self._where(path)}は、項目のある配列でない")
        if _is_flow(sequence):
            raise YamlEditError(f"{self._where(path)}は{FLOW_STYLE_MESSAGE}")
        _, _, core_end, dash = self._item_range(sequence, len(sequence) - 1)
        expected = self._expected()
        self._resolve(expected, path).append(_python(item))
        self._apply(self.lines[:core_end] + self.render_item(item, dash) + self.lines[core_end:], expected)

    def delete_item(self, path: Path, index: int) -> None:
        """配列の項目を、直前のコメントごと消す。"""
        sequence = self.node(path)
        if not isinstance(sequence, CommentedSeq) or _is_flow(sequence):
            raise YamlEditError(f"{self._where(path)}は{FLOW_STYLE_MESSAGE}")
        if len(sequence) == 1:
            raise YamlEditError(f"{self._where(path)}の最後の項目は消せない")
        lead, _, core_end, dash = self._item_range(sequence, index)
        expected = self._expected()
        del self._resolve(expected, path)[index]
        self._apply(self._without(lead, core_end, dash), expected)

    def _without(self, start: int, end: int, col: int) -> list[str]:
        """行 [start, end) を消した行。消した後に空行が続くか、消した範囲が親の項目の最後なら、直前の空行も消す。"""
        lines = self.lines[:start] + self.lines[end:]
        if start > 0 and _blank(lines[start - 1]):
            after = lines[start] if start < len(lines) else None
            if after is None or _blank(after) or (not _comment(after) and _indent(after) < col):
                del lines[start - 1]
        return lines

    @staticmethod
    def _resolve(data: Any, path: Path) -> Any:
        for key in path:
            data = data[key]
        return data


def _render(key: str, value: Any, col: int, unit: int, seq_dash: int, seq_content: int) -> list[str]:
    space = " " * col
    if isinstance(value, dict):
        lines = [f"{space}{key}:\n"]
        for child_key, child in value.items():
            lines += _render(child_key, child, col + unit, unit, seq_dash, seq_content)
        return lines
    if isinstance(value, list) and not isinstance(value, Flow):
        lines = [f"{space}{key}:\n"]
        for item in value:
            lines += _render_item(item, col + seq_dash, unit, seq_dash, seq_content)
        return lines
    return [f"{space}{key}: {scalar(value)}\n"]


def _render_item(item: dict, dash: int, unit: int, seq_dash: int, seq_content: int) -> list[str]:
    lines: list[str] = []
    for i, (key, value) in enumerate(item.items()):
        rendered = _render(key, value, dash + seq_content, unit, seq_dash, seq_content)
        if i == 0:
            rendered[0] = " " * dash + "-" + " " * (seq_content - 1) + rendered[0].lstrip(" ")
        lines += rendered
    return lines


def new_document(key: str, value: Any) -> Document:
    """トップのキーが 1 つの、新しいファイルの文字列を作る。インデントはツールの設定 (マッピング 2・配列の「-」は 2 下げる)。"""
    text = "".join(_render(key, value, 0, 2, 2, 2))
    document = Document(text)
    if _canonical(_python(document.data)) != _canonical({key: _python(value)}):
        raise YamlEditError("新しく作る YAML が、意図した内容と一致しない (ツールの誤り)")
    return document
