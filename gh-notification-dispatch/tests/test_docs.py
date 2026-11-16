#!/usr/bin/env python3
"""文書とコードの定数が一致することのテスト。

- 文書 `gh-notification-dispatch/references/messages.md` の type とキーの表・値の一覧・例が、モジュール messages の
  定数と解析に一致する (計画 docs/plans/2026-11-14-1428-feat-gh-notification-dispatch-plan.md の KTD8)

  python3 -m unittest discover -s gh-notification-dispatch/tests
"""

import os
import re
import unittest

from fakegh_case import HERE

from gh_notification_dispatch import messages  # noqa: E402

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


def code_tokens(cell):
    return tuple(re.findall(r"`([^`]+)`", cell)) if cell != "なし" else ()


def code_blocks(text, section):
    """見出し `## <section>` の節にある ```text のコードブロックの中身の配列。"""
    body = text.split(f"\n## {section}\n", 1)[1].split("\n## ", 1)[0]
    return re.findall(r"```text\n(.*?)```", body, re.DOTALL)


class MessagesDocTest(unittest.TestCase):

    def setUp(self):
        self.doc = read_reference("messages.md")

    def test_type_table_matches_fields(self):
        rows = table_rows(self.doc, "| type | 送り手 → 受け手 | 必須のキー | 任意のキー |")
        documented = {}
        for cells in rows:
            type_ = re.fullmatch(r"`([a-z]+)`", cells[0]).group(1)
            self.assertNotIn(type_, documented, f"type {type_} が表に 2 回ある")
            documented[type_] = (code_tokens(cells[2]), code_tokens(cells[3]))
        self.assertEqual(documented, messages.FIELDS, "文書の type の表と messages.FIELDS が一致すること (キーの順序も)")

    def test_key_table_matches_fields(self):
        rows = table_rows(self.doc, "| キー | 値 |")
        documented = [re.fullmatch(r"`([a-z-]+)`", cells[0]).group(1) for cells in rows]
        used = {key for required, optional in messages.FIELDS.values() for key in (*required, *optional)}
        self.assertEqual(len(documented), len(set(documented)), "同じキーを 2 回書かないこと")
        self.assertEqual(set(documented), used, "文書のキーの表と、messages.FIELDS が使うキーが一致すること")
        values = dict(zip(documented, (cells[1] for cells in rows)))
        for key, allowed in (("kinds", messages.KINDS), ("permission-mode", messages.PERMISSION_MODES),
                             ("result", messages.RESULTS)):
            with self.subTest(key=key):
                self.assertEqual(code_tokens(values[key]), allowed, f"キー {key} の値の一覧")

    def test_permission_classes(self):
        self.assertIn(f"権限の確認を省く `{messages.SKIP_CONFIRMATION_MODES[0]}`", self.doc)
        others = [m for m in messages.PERMISSION_MODES if m not in messages.SKIP_CONFIRMATION_MODES]
        self.assertIn("確認するそれ以外 (" + "・".join(f"`{m}`" for m in others) + ")", self.doc)

    def test_prefix(self):
        self.assertIn(f"gh-notification-dispatch: <先頭行の文>", self.doc)
        self.assertEqual(messages.PREFIX, "gh-notification-dispatch:")

    def test_examples_parse(self):
        examples = code_blocks(self.doc, "例")
        self.assertEqual(len(examples), 6)
        types = []
        for text in examples:
            with self.subTest(head=text.splitlines()[0]):
                parsed = messages.parse(text)
                self.assertEqual(parsed["errors"], [], "例が様式どおりであること")
                types.append(parsed["type"])
        self.assertEqual(sorted(set(types)), sorted(messages.TYPES), "どの type にも例があること")

    def test_examples_match_composed_text(self):
        """例のうち、生成の関数で作れるものは、生成した本文と同じであること (先頭行の文も含めて)。"""
        examples = code_blocks(self.doc, "例")
        session = "local_00000000-0000-4000-8000-000000000001"
        composed = [
            messages.subscribe("akm/claude-plugins", ["review_requested", "merged"], session, "claude-plugins のレビュー",
                               "auto"),
            messages.subscribed_accepted("akm/claude-plugins", ["merged"], ["review_requested"],
                                         messages.hold_warning("bypassPermissions", "auto")),
            messages.subscribed_rejected(
                ["リポジトリ akm/no-such-repo を gh で読めない (HTTP 404)。名前が誤っているか、読む権限が無い"],
                repo="akm/no-such-repo"),
            messages.unsubscribe(["0123456789ab", "ba9876543210"], session, "claude-plugins のレビュー"),
            messages.unsubscribed_accepted([{"repo": "akm/claude-plugins", "kind": "review_requested"},
                                            {"repo": "akm/claude-plugins", "kind": "merged"}]),
            messages.removed([{"repo": "akm/claude-plugins", "kind": "merged"}]),
        ]
        self.assertEqual(examples, composed)


if __name__ == "__main__":
    unittest.main()
