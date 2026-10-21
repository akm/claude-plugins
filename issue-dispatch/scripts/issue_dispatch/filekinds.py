"""パスからファイルの種類と属性を決める。リポジトリの設定の `files` の規則を先に、同梱のデフォルトの表
(file-kinds.json) を後に照合し、1 つのパスが種類の違う規則に一致すれば、6 段の問いの順で先の種類にする。

種類と属性の意味、パターンの書き方、照合の順の正本は issue-dispatch/skills/issue-dispatch/references/file-kinds.md。
設定の規則の様式と、読み込むときにそろえる表記の正本は同じディレクトリの project-config.md (そろえるのはモジュール config)。

このモジュールは `issue_dispatch` のほかのモジュールを import しない (種類の決定を GitHub の操作や記録から切り離し、
単独でテストできるようにするため。KD22)。設定ファイルも読まず、そろえた後の規則を引数で受ける。
呼び出し元: CLI issue-dispatch/scripts/issue_dispatch.py の `files classify`。
"""

import json
import os
import re

# 6 段の問いの順 (file-kinds.md の表)。先にあるほど優先する
KINDS = ("unknown-content", "generated", "unknown-structure", "indivisible", "unstable", "divisible")
# 規則に書ける種類 (`unknown-content` は、どの規則にも一致しないパスの種類なので、規則には書けない)
RULE_KINDS = KINDS[1:]

DEFAULT_TABLE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "file-kinds.json")


def load_default_table(path=DEFAULT_TABLE_PATH):
    """同梱のデフォルトの表を読む。返り値は規則の配列 (file-kinds.json の内容そのまま)。"""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _translate_segment(segment):
    """`/` を含まない 1 つの区切りを正規表現に変換する。`*` と `?` は `/` を越えない。`[seq]` は文字の集合
    (`[!seq]` は否定。fnmatch と同じ読み方)。区切りの一部の `**` は `*` と同じ (`full_match` と同じ)。"""
    out = []
    i = 0
    n = len(segment)
    while i < n:
        c = segment[i]
        if c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "[":
            j = i + 1
            if j < n and segment[j] == "!":
                j += 1
            if j < n and segment[j] == "]":
                j += 1
            while j < n and segment[j] != "]":
                j += 1
            if j >= n:
                out.append("\\[")  # 閉じない `[` はそのままの文字
                i += 1
            else:
                stuff = segment[i + 1:j].replace("\\", "\\\\")
                i = j + 1
                if stuff[0] == "!":
                    stuff = "^" + stuff[1:]
                elif stuff[0] in ("^", "["):
                    stuff = "\\" + stuff
                out.append("[" + stuff + "]")
        else:
            out.append(re.escape(c))
            i += 1
    return "".join(out)


def pattern_to_regex(pattern):
    """パターンを、ルートからのパス全体に完全一致で照合する正規表現に変換する。

    規則は Python 3.13 の PurePath.full_match と同じ (3.11 には無いので、ここで変換する。fnmatch は `*` が `/` を
    越えて一致するので使わない)。パターンを `/` で区切り、区切り全体が `**` なら 0 個以上のディレクトリに一致する
    (末尾の `**` は 1 個以上の名前。`dist/**` は `dist` そのものと、名前が空の `dist/` には一致しない)。それ以外の
    区切りは _translate_segment で変換する。`.gitignore` の規則 (`/` を含まないパターンがどの階層にも一致する)
    とは違う。末尾が `/` のパターンは、そのディレクトリの下のすべて (`/**` を付けたもの) と同じ (この文書の拡張)。
    """
    if pattern.endswith("/"):
        pattern = pattern + "**"
    segments = pattern.split("/")
    out = []
    for index, segment in enumerate(segments):
        last = index == len(segments) - 1
        if segment == "**":
            out.append("[^/]+(?:/[^/]+)*" if last else "(?:[^/]+/)*")
        else:
            out.append(_translate_segment(segment) + ("" if last else "/"))
    return re.compile("".join(out) + r"\Z")


def normalize_path(path):
    """パス (リポジトリのルートからの相対パス) を、照合の前にそろえる。返り値は (そろえたパス, None) か (None, 問題)。

    `//` を `/` に、`.` と空の区切りを除き、末尾の `/` を除く (`./a`・`a/`・`a//b` は `a`・`a/b`)。
    絶対パス (`/` で始まる)・`..` を含むパス・ルートそのもの (空になるパス) は、ルートの外を指しうるか
    ファイルを指さないので、そろえずに問題を返す (呼び出し元が差し戻す。KTD9)。
    設定のパターンをそろえる規則 (末尾の `/` を残す) とは違うので、関数を分けている。
    """
    if not isinstance(path, str):
        return None, f"パス {path!r} は文字列ではない"
    if path.startswith("/"):
        return None, f"絶対パス {path!r} は使えない (リポジトリのルートからの相対パスを書く)"
    segments = [s for s in path.split("/") if s not in (".", "")]
    if ".." in segments:
        return None, f"`..` を含むパス {path!r} は使えない (ルートの外を指しうる)"
    if not segments:
        return None, f"パス {path!r} はルートそのものを指すので使えない"
    return "/".join(segments), None


def matches(pattern, path):
    """パターンがパス (ルートからの相対パス) に一致するか。"""
    return pattern_to_regex(pattern).match(path) is not None


def _attributes(rule):
    return {
        "unit_notation": rule.get("unit_notation"),
        "split_reference": rule.get("split_reference"),
        "mergeable": rule.get("mergeable", True),
    }


def _pick(path, rules, source):
    """規則の配列の中で path に一致するものから、6 段の順で先の種類の規則を 1 つ選ぶ。無ければ None。
    同じ種類なら先に書いた規則 (`<` で比べるので、後の規則は置き換えない。file-kinds.md の「照合の順」の 3)。"""
    best = None
    for rule in rules:
        if rule.get("kind") not in RULE_KINDS:
            raise ValueError(f"規則 {rule!r} の kind は {', '.join(RULE_KINDS)} のどれか (設定の規則は config が検査する)")
        if not matches(rule["pattern"], path):
            continue
        if best is None or KINDS.index(rule["kind"]) < KINDS.index(best["kind"]):
            best = rule
    if best is None:
        return None
    return {"kind": best["kind"], **_attributes(best), "matched": {"source": source, "pattern": best["pattern"]}}


def classify(path, rules, default_table):
    """パスの種類と属性を決める。

    rules はリポジトリの設定の `files` (config がそろえた後の規則の配列)、default_table はデフォルトの表。
    設定の規則に一致すればその中で、無ければデフォルトの表の中で、6 段の順で先の種類を選ぶ。
    どちらにも一致しなければ `unknown-content` (属性は無し、`matched` は None)。
    返り値: {"kind", "unit_notation", "split_reference", "mergeable", "matched": {"source": "config" | "default", "pattern"} | None}
    """
    picked = _pick(path, rules, "config") or _pick(path, default_table, "default")
    if picked is None:
        return {"kind": "unknown-content", "unit_notation": None, "split_reference": None, "mergeable": True, "matched": None}
    return picked
