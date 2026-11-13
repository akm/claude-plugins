"""節「クローズ条件」のチェックボックスと根拠のリンクの解析 (計画の KTD9)。

書式の SSOT は、文書 `issue-practice/references/closing-conditions.md` とこのモジュール。
範囲の決め方: 本文にマーク closing-conditions が 1 つでもあればマークで囲んだ範囲 (管理 Issue)、無ければ見出し
`## クローズ条件` の節 (作業 Issue と自己管理 Issue)。

関数は、解析できた値の辞書か、理由を持つ辞書 (`{"error": <理由>}`) を返す。例外は送出しない。
"""

import re

from issue_practice import bodies

SECTION_TITLE = "クローズ条件"
REGION = "closing-conditions"

STATES = ("unchecked", "checked", "checked_without_evidence", "carved_out")
SATISFIED = ("checked", "carved_out")

_ITEM_RE = re.compile(r"^(?P<indent>[ \t]*)[-*+] \[(?P<mark>[ xX])\] (?P<text>.*)$")
_LINK_RE = re.compile(r"\s*\((?P<label>根拠|切り出し): (?P<url>https://\S+)\)\s*$")
_GROUPS = (("expected", "期待する状態"), ("verification", "確認するポイント"))


def find(body):
    """クローズ条件の範囲を決める。返り値は {"source" (region・section), "lines" ([(行番号, 行)])} か {"error"}。"""
    if bodies.has_region_mark(body, REGION):
        found = bodies.find_region(body, REGION)
        source = "region"
    else:
        found = bodies.find_section(body, SECTION_TITLE)
        source = "section"
    if "error" in found:
        return found
    return {"source": source, "lines": found["lines"]}


def _group(line):
    stripped = line.strip()
    h = bodies.heading(stripped)
    text = h[1] if h else stripped
    text = text.rstrip(":：").strip()
    for key, label in _GROUPS:
        if text == label:
            return key
    return None


def _indent_width(indent):
    return len(indent.expandtabs(4))


def parse_lines(lines):
    """範囲の行 ([(行番号, 行)]) からチェックボックスの項目を読む。コードブロックの中の行は読まない。

    返り値は項目の配列。項目は {"line", "text" (末尾のリンクを除いた文), "raw" (行のまま), "checked", "state",
    "evidence" (根拠の URL か None), "carved_out" (切り出しの URL か None), "group" (expected・verification・None),
    "heading" (直前のレベル 3 以上の見出しか None), "indent", "details" (項目の下の、より深い字下げの行の配列)}。
    """
    texts = [text for _, text in lines]
    visible = bodies.outside_fences(texts)
    items, group, heading_text, current = [], None, None, None
    for index, (number, text) in enumerate(lines):
        if index not in visible:
            continue
        m = _ITEM_RE.match(text)
        if m:
            checked = m.group("mark") != " "
            body_text = m.group("text")
            link = _LINK_RE.search(body_text)
            evidence = carved = None
            if link:
                body_text = body_text[:link.start()]
                if link.group("label") == "根拠":
                    evidence = link.group("url")
                else:
                    carved = link.group("url")
            if not checked:
                state = "unchecked"
            elif carved:
                state = "carved_out"
            elif evidence:
                state = "checked"
            else:
                state = "checked_without_evidence"
            current = {"line": number, "text": body_text.strip(), "raw": text, "checked": checked, "state": state,
                       "evidence": evidence, "carved_out": carved, "group": group, "heading": heading_text,
                       "indent": _indent_width(m.group("indent")), "details": []}
            items.append(current)
            continue
        h = bodies.heading(text)
        if h and h[0] >= 3:
            # 見出しが「期待する状態」か「確認するポイント」ならその分類、ほかの見出しなら分類をいったん無しにする
            heading_text, current, group = h[1], None, _group(text)
            continue
        g = _group(text)
        if g:
            group, current = g, None
            continue
        if current is not None and text.strip():
            if _indent_width(text[:len(text) - len(text.lstrip())]) > current["indent"]:
                current["details"].append(text.strip())
            else:
                current = None
    return items


def summarize(items):
    """項目の状態ごとの数と、満たさない項目の行番号の配列。"""
    counts = {state: 0 for state in STATES}
    for item in items:
        counts[item["state"]] += 1
    return {"counts": counts, "unsatisfied": [item["line"] for item in items if item["state"] not in SATISFIED]}


def parse(body):
    """本文のクローズ条件を読む。返り値は {"source", "items", "summary"} か {"error"}。"""
    found = find(body)
    if "error" in found:
        return found
    items = parse_lines(found["lines"])
    return {"source": found["source"], "items": items, "summary": summarize(items)}
