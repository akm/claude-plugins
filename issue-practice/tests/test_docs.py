#!/usr/bin/env python3
"""文書とコードの定数・入口の --help が一致することのテスト。

- 文書 `issue-practice/references/record-comments.md` の種類とキーの表が、モジュール records の定数と一致する (計画の KTD4)
"""

import os
import re
import unittest

from fakegh_case import HERE

from issue_practice import records  # noqa: E402

REFERENCES = os.path.join(HERE, "..", "references")


def read_reference(name):
    with open(os.path.join(REFERENCES, name), encoding="utf-8") as f:
        return f.read()


def table_rows(text, header):
    """見出し行が header で始まる Markdown の表の、データの行 (セルの配列) を返す。"""
    rows, inside = [], False
    for line in text.splitlines():
        if line.startswith(header):
            inside = True
            continue
        if inside:
            if not line.startswith("|"):
                inside = False
                continue
            if set(line.replace("|", "").strip()) <= {"-", " "}:
                continue
            rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows


def keys_in(cell):
    return tuple(re.findall(r"`([a-z-]+)`", cell)) if cell != "なし" else ()


class RecordCommentsDocTest(unittest.TestCase):

    def setUp(self):
        self.doc = read_reference("record-comments.md")

    def test_kinds_table_matches_constants(self):
        rows = table_rows(self.doc, "| 種類 | 必須のキー | 任意のキー |")
        documented = {}
        for cells in rows:
            kind = re.fullmatch(r"`([a-z-]+)`", cells[0]).group(1)
            self.assertNotIn(kind, documented, f"種類 {kind} が表に 2 回ある")
            documented[kind] = {"required": keys_in(cells[1]), "optional": keys_in(cells[2])}
        expected = {kind: {"required": spec["required"], "optional": spec["optional"]} for kind, spec in records.KINDS.items()}
        self.assertEqual(documented, expected, "文書の種類の表と records.KINDS が一致すること (キーの順序も)")

    def test_keys_table_matches_constants(self):
        rows = table_rows(self.doc, "| キー | 値 |")
        documented = [re.fullmatch(r"`([a-z-]+)`", cells[0]).group(1) for cells in rows]
        self.assertEqual(sorted(documented), sorted(records.KEYS), "文書のキーの表と records.KEYS が一致すること")
        values = dict(zip(documented, (cells[1] for cells in rows)))
        for name, allowed in (("role", records.ROLES), ("type", records.REPORT_TYPES), ("result", records.RESULTS)):
            with self.subTest(key=name):
                self.assertEqual(tuple(re.findall(r"`([a-z-]+)`", values[name])), allowed, f"キー {name} の値の一覧")

    def test_prefix_and_body_line(self):
        self.assertIn(f"{records.PREFIX} <種類> <キー>=<値>", self.doc)
        self.assertIn(f"{records.PREFIX} created-from draft=<計画案のファイル名> key=<計画案の中のキー>", self.doc)
        body_kinds = [k for k, spec in records.KINDS.items() if spec["where"] == "body"]
        self.assertEqual(body_kinds, ["created-from"])


if __name__ == "__main__":
    unittest.main()
