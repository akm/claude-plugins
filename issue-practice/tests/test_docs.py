#!/usr/bin/env python3
"""文書とコードの定数・入口の --help が一致することのテスト。

- 文書 `issue-practice/references/record-comments.md` の種類とキーの表が、モジュール records の定数と一致する (計画の KTD4)
- 文書 `issue-practice/references/closing-conditions.md` の範囲の名前とチェックボックスの状態が、モジュール bodies と
  checkboxes の定数と一致する
- 文書 `issue-practice/references/draft-plan.md` の書式の行が、モジュール draft の定数と一致する
- 入口 (ファイル `issue-practice/scripts/issue_practice.py`) の docstring のサブコマンドの一覧と、サブコマンドごとの --help が、
  引数・出力・終了コードを示す (計画の KTD2・KTD10)
"""

import os
import re
import subprocess
import sys
import unittest

from fakegh_case import ENTRY, HERE

from issue_practice import bodies, checkboxes, draft, records  # noqa: E402

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


class ClosingConditionsDocTest(unittest.TestCase):

    def setUp(self):
        self.doc = read_reference("closing-conditions.md")

    def test_regions(self):
        for name in bodies.REGIONS:
            with self.subTest(name=name):
                self.assertIn(f"`{bodies.start_mark(name)}`", self.doc)
                self.assertIn(f"`{bodies.end_mark(name)}`", self.doc)
        names = re.findall(r"`<!-- issue-practice:([a-z-]+) -->`", self.doc)
        self.assertEqual(sorted(set(names)), sorted(bodies.REGIONS), "文書に書いた範囲の名前が bodies.REGIONS と一致すること")

    def test_states(self):
        rows = table_rows(self.doc, "| 状態 | 項目の形 | 満たすか |")
        documented = {re.fullmatch(r"`([a-z_]+)`", cells[0]).group(1): cells[2] for cells in rows}
        self.assertEqual(list(documented), list(checkboxes.STATES))
        self.assertEqual([s for s, v in documented.items() if v == "満たす"], list(checkboxes.SATISFIED))

    def test_link_forms(self):
        self.assertIn("`(根拠: <URL>)`", self.doc)
        self.assertIn("`(切り出し: <URL>)`", self.doc)
        self.assertIn(f"## {checkboxes.SECTION_TITLE}", self.doc)


class DraftPlanDocTest(unittest.TestCase):

    def test_format_lines(self):
        doc = read_reference("draft-plan.md")
        self.assertIn(f"`{draft.DRAFT_DIR}/`", doc)
        self.assertIn(f"## {draft.SOURCES_HEADING}", doc)
        self.assertIn(f"{draft.NONE_ITEM}", doc)
        self.assertIn("本文の SHA-256: <64 桁の 16 進数>", doc)
        self.assertIn("# 計画案: <題>", doc)


def entry_subcommands():
    """入口の docstring の「サブコマンドの一覧」に書いた (グループ, コマンド) の配列。"""
    with open(ENTRY, encoding="utf-8") as f:
        text = f.read()
    doc = text.split('"""')[1]
    listing = doc.split("サブコマンドの一覧:\n", 1)[1].split("\n\n", 1)[0]
    return [tuple(line.split()[:2]) for line in listing.splitlines() if line.startswith("  ")]


def run_entry(*args):
    return subprocess.run([sys.executable, ENTRY, *args], capture_output=True, text=True)


class EntryHelpTest(unittest.TestCase):

    def test_docstring_lists_every_subcommand(self):
        listed = entry_subcommands()
        self.assertTrue(listed)
        groups = sorted({group for group, _ in listed})
        top = run_entry("--help").stdout
        for group in groups:
            with self.subTest(group=group):
                self.assertIn(group, top)
                help_text = run_entry(group, "--help").stdout
                choices = re.search(r"\{([a-z,-]+)\}", help_text).group(1).split(",")
                self.assertEqual(sorted(choices), sorted(cmd for g, cmd in listed if g == group),
                                 f"docstring の一覧と argparse のサブコマンドが一致すること ({group})")

    def test_each_help_shows_arguments_output_and_exit_codes(self):
        for group, command in entry_subcommands():
            with self.subTest(command=f"{group} {command}"):
                completed = run_entry(group, command, "--help")
                self.assertEqual(completed.returncode, 0)
                text = completed.stdout
                self.assertIn("usage:", text)
                self.assertIn("出力 (標準出力の JSON):", text)
                self.assertIn("終了コード:", text)
                codes = re.findall(r"^  ([0-9])  ", text.split("終了コード:", 1)[1], re.MULTILINE)
                self.assertEqual(codes, ["0", "3", "4"], "終了コードは 0・3・4 の 3 つを示すこと")

    def test_docstring_exit_codes(self):
        with open(ENTRY, encoding="utf-8") as f:
            doc = f.read().split('"""')[1]
        exit_section = doc.split("終了コード (計画の KTD10):\n", 1)[1]
        self.assertEqual(re.findall(r"^  ([0-9])  ", exit_section, re.MULTILINE), ["0", "3", "4"])

    def test_argument_error_is_exit_2(self):
        self.assertEqual(run_entry("records", "list").returncode, 2, "引数の誤りは argparse の 2 のまま")
        self.assertEqual(run_entry("no-such").returncode, 2)


if __name__ == "__main__":
    unittest.main()
