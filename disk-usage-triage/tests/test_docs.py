#!/usr/bin/env python3
"""文書とコードの定数が一致することと、入口のファイルのテスト。

- 文書 `disk-usage-triage/references/files.md` の `config.json` のキーの表と例が、モジュール config の定数と検査に一致する
  (計画 docs/plans/2026-11-22-1630-feat-disk-usage-triage-plan.md の U2)
- 文書 `disk-usage-triage/references/judgment-table.md` の行のキーの表・例・判定の値・コマンドの種類・置き換える文字列が、
  モジュール judge の定数と検査に一致する (計画の U3)
- 文書 `disk-usage-triage/references/files.md` の `records.json` のキーの表・対象の表・例と、入力の例が、モジュール records の
  定数と検査に一致する (計画の U4)
- 入口 (ファイル `disk-usage-triage/scripts/disk_usage_triage.py`) の docstring のサブコマンドの一覧と、サブコマンドごとの
  --help が、引数・出力・終了コードを示す (計画の KTD14)
- 入口は、Python の版が 3.11 より古ければ、版を示して終了コード 3 で終了する (計画の節「Assumptions」)
- ファイル `disk-usage-triage/README.md` のスキルの表が、ディレクトリ `disk-usage-triage/skills/` のスキルをすべて挙げている

  python3 -m unittest discover -s disk-usage-triage/tests
"""

import ast
import contextlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import unittest
from unittest import mock

from triage_case import ENTRY, HERE

from disk_usage_triage import config, judge, records  # noqa: E402

REFERENCES = os.path.join(HERE, "..", "references")


def read_reference(name):
    with open(os.path.join(REFERENCES, name), encoding="utf-8") as f:
        return f.read()


def section(text, heading):
    """見出しが heading の節 (次の同じか上の階層の見出しまで) の本文。"""
    level = heading.split(" ", 1)[0]
    body = text.split(f"\n{heading}\n", 1)[1]
    stop = re.search(rf"^#{{1,{len(level)}}} ", body, re.MULTILINE)
    return body[:stop.start()] if stop else body


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


def json_blocks(text):
    return [json.loads(block) for block in re.findall(r"```json\n(.*?)```", text, re.DOTALL)]


class FilesDocTest(unittest.TestCase):

    def setUp(self):
        self.doc = read_reference("files.md")

    def test_config_keys_match_constants(self):
        rows = table_rows(section(self.doc, "## `config.json`"), "| キー | 値 |")
        documented = [re.fullmatch(r"`([a-z_]+)`", cells[0]).group(1) for cells in rows]
        self.assertEqual(documented, ["version", *config.KEYS], "文書のキーの表と config.KEYS が一致すること (順序も)")

    def test_config_example_is_valid(self):
        examples = json_blocks(section(self.doc, "## `config.json`"))
        self.assertEqual(len(examples), 1)
        self.assertEqual(config.stored_shape_errors(examples[0]), [], "例が様式どおりであること")
        self.assertEqual(list(examples[0]), ["version", *config.KEYS])

    def test_input_example_is_valid(self):
        examples = json_blocks(section(self.doc, "### `config set` の入力"))
        self.assertEqual(len(examples), 1)
        self.assertEqual(config.input_shape_errors(examples[0]), [], "例が様式どおりであること")
        self.assertNotIn("version", examples[0])

    def test_max_timeout(self):
        text = section(self.doc, "## `config.json`")
        self.assertIn("86,400 (1 日) 以下の整数", text)
        self.assertEqual(config.MAX_TIMEOUT_SECONDS, 86400)

    def test_default_timeout(self):
        text = section(self.doc, "### `config set` の入力")
        self.assertIn(f"省くと {config.DEFAULT_TIMEOUT_SECONDS}", text)


class RecordsDocTest(unittest.TestCase):
    """文書 references/files.md の記録の節 (様式の SSOT) と、モジュール records の定数と検査が一致する (計画の U4)。"""

    def setUp(self):
        self.doc = read_reference("files.md")

    def test_top_keys(self):
        rows = table_rows(section(self.doc, "## `records.json`"), "| キー | 値 |")
        documented = [re.fullmatch(r"`([a-z_]+)`", cells[0]).group(1) for cells in rows]
        self.assertEqual(documented[:2], list(records.TOP_KEYS), "最初の表のキーと records.TOP_KEYS が一致すること")

    def test_record_keys_match_constants(self):
        text = section(self.doc, "## `records.json`").split("記録のキー:", 1)[1]
        rows = table_rows(text, "| キー | 値 |")
        documented = [re.fullmatch(r"`([a-z_]+)`", cells[0]).group(1) for cells in rows]
        self.assertEqual(documented, list(records.RECORD_KEYS), "記録のキーの表と records.RECORD_KEYS が一致すること (順序も)")

    def test_target_kinds_match_constants(self):
        rows = table_rows(section(self.doc, "### 対象"), "| `kind` | ほかのキー | 対象 |")
        documented = {cells[0].strip("`"): tuple(re.findall(r"`([a-z_]+)`", cells[1])) for cells in rows}
        self.assertEqual(list(documented), list(records.TARGET_KINDS), "対象の表と records.TARGET_KINDS が一致すること (順序も)")
        self.assertEqual(documented, records.TARGET_KINDS)

    def test_record_example_is_valid(self):
        examples = json_blocks(section(self.doc, "## `records.json`"))
        self.assertEqual(len(examples), 1)
        self.assertEqual(records._check_stored(examples[0]), examples[0]["records"], "例が様式どおりであること")
        self.assertEqual({r["target"]["kind"] for r in examples[0]["records"]} <= set(records.TARGET_KINDS), True)

    def test_add_input(self):
        text = section(self.doc, "### `records add` の入力")
        examples = json_blocks(text)
        self.assertEqual(len(examples), 1)
        self.assertEqual(records.add_input_errors(examples[0]), [], "例が様式どおりであること")
        documented = [cells[0].strip("`") for cells in table_rows(text, "| キー | 値 |")]
        self.assertEqual(documented, list(records.ADD_INPUT_KEYS))

    def test_claude_input(self):
        text = section(self.doc, "### Claude の判定の入力")
        examples = json_blocks(text)
        self.assertEqual(len(examples), 1)
        self.assertEqual(records.claude_input_errors(examples[0]), [], "例が様式どおりであること")
        rows = table_rows(text, "| キー | 値 |")
        self.assertEqual([cells[0].strip("`") for cells in rows], list(records.CLAUDE_INPUT_KEYS))
        required = [cells[0].strip("`") for cells in rows if "必須" in cells[1]]
        self.assertEqual(required, list(records.CLAUDE_REQUIRED_KEYS))


class JudgmentTableDocTest(unittest.TestCase):
    """文書 references/judgment-table.md (判定表の様式の SSOT) と、モジュール judge の定数と検査が一致する (計画の U3)。"""

    def setUp(self):
        self.doc = read_reference("judgment-table.md")

    def test_row_keys_match_constants(self):
        rows = table_rows(section(self.doc, "## 行"), "| キー | 値 |")
        documented = [re.fullmatch(r"`([a-z_]+)`", cells[0]).group(1) for cells in rows]
        self.assertEqual(documented, list(judge.ROW_KEYS), "文書のキーの表と judge.ROW_KEYS が一致すること (順序も)")
        required = [cells[0].strip("`") for cells in rows if "必須" in cells[1]]
        self.assertEqual(required, list(judge.REQUIRED_KEYS), "文書で必須と書いたキーと judge.REQUIRED_KEYS が一致すること")

    def test_example_is_valid(self):
        examples = json_blocks(section(self.doc, "## 行"))
        self.assertEqual(len(examples), 1)
        self.assertEqual(judge.row_errors(examples[0]), [], "例が様式どおりであること")

    def test_judgments_and_dedicated_lists(self):
        terms = self.doc.split("\n## ", 1)[0]  # 最初の節の前 (この文書で使う語)
        for value in judge.JUDGMENTS:
            self.assertIn(f"`{value}`", terms, "語の説明に判定の値を書くこと")
        keys = {cells[0]: cells[1] for cells in table_rows(section(self.doc, "## 行"), "| キー | 値 |")}
        self.assertEqual(re.findall(r"`(deletable|review|keep)`", keys["`judgment`"]), list(judge.JUDGMENTS))
        choices = re.search(r"((?:`[a-z]+`・?)+) のどれか", keys["`dedicated_list`"]).group(1)
        self.assertEqual(re.findall(r"`([a-z]+)`", choices), list(judge.TABLE_DEDICATED_LISTS))

    def test_command_types_and_placeholders(self):
        text = section(self.doc, "## 消すコマンド")
        types = [cells[0].strip("`") for cells in table_rows(text, "| `type` | ほかのキー | 消し方 |")]
        self.assertEqual(types, list(judge.COMMAND_TYPES))
        placeholders = [cells[0].strip("`") for cells in table_rows(text, "| 文字列 | 置き換える値 |")]
        self.assertEqual(placeholders, list(judge.PLACEHOLDERS))


SKILLS = os.path.join(HERE, "..", "skills")
README = os.path.join(HERE, "..", "README.md")


class SkillListingDocTest(unittest.TestCase):
    """スキルを足したときに、README に書き損ねないこと。"""

    def test_readme_lists_every_skill(self):
        skills = sorted(name for name in os.listdir(SKILLS) if os.path.isfile(os.path.join(SKILLS, name, "SKILL.md")))
        self.assertTrue(skills)
        with open(README, encoding="utf-8") as f:
            rows = table_rows(f.read(), "| スキル | すること |")
        listed = sorted(re.match(r"\[([a-z-]+)\]", cells[0]).group(1) for cells in rows)
        self.assertEqual(listed, skills)

    def test_skill_names_match_directories(self):
        for name in os.listdir(SKILLS):
            with self.subTest(skill=name), open(os.path.join(SKILLS, name, "SKILL.md"), encoding="utf-8") as f:
                front = f.read().split("---\n", 2)[1]
                self.assertIn(f"name: {name}\n", front)
                self.assertRegex(front, r"\ndescription: .+\n")


GROUPS = ("config", "records", "hook")  # 下にサブコマンドを持つグループ


def entry_subcommands():
    """入口の docstring の「サブコマンドの一覧」に書いたサブコマンドの配列。(グループ, コマンド) か (コマンド,)。"""
    with open(ENTRY, encoding="utf-8") as f:
        doc = f.read().split('"""')[1]
    listing = doc.split("サブコマンドの一覧:\n", 1)[1].split("\n\n", 1)[0]
    result = []
    for line in listing.splitlines():
        if line.startswith("  "):
            tokens = line.split()
            result.append(tuple(tokens[:2]) if tokens[0] in GROUPS else (tokens[0],))
    return result


def run_entry(*args):
    return subprocess.run([sys.executable, ENTRY, *args], capture_output=True, text=True, stdin=subprocess.DEVNULL)


class EntryHelpTest(unittest.TestCase):

    def test_docstring_lists_every_subcommand(self):
        listed = entry_subcommands()
        self.assertTrue(listed)
        top = re.search(r"\{([a-z,-]+)\}", run_entry("--help").stdout).group(1).split(",")
        self.assertEqual(sorted(top), sorted({entry[0] for entry in listed}),
                         "docstring の一覧と argparse の入口の直下のサブコマンドが一致すること")
        for group in GROUPS:
            with self.subTest(group=group):
                choices = re.search(r"\{([a-z,-]+)\}", run_entry(group, "--help").stdout).group(1).split(",")
                self.assertEqual(sorted(choices), sorted(e[1] for e in listed if e[0] == group),
                                 f"docstring の一覧と argparse のサブコマンドが一致すること ({group})")

    def test_each_help_shows_arguments_output_and_exit_codes(self):
        for entry in entry_subcommands():
            with self.subTest(command=" ".join(entry)):
                completed = run_entry(*entry, "--help")
                self.assertEqual(completed.returncode, 0)
                text = completed.stdout
                self.assertIn("usage:", text)
                self.assertIn("出力 (標準出力の JSON):", text)
                self.assertIn("errors", text.split("出力 (標準出力の JSON):", 1)[1])
                self.assertIn("終了コード:", text)
                codes = re.findall(r"^  ([0-9])  ", text.split("終了コード:", 1)[1], re.MULTILINE)
                self.assertEqual(codes, ["0", "3", "4"], "終了コードは 0・3・4 の 3 つを示すこと")

    def test_docstring_exit_codes(self):
        with open(ENTRY, encoding="utf-8") as f:
            doc = f.read().split('"""')[1]
        exit_section = doc.split("終了コード (計画の KTD14):\n", 1)[1]
        self.assertEqual(re.findall(r"^  ([0-9])  ", exit_section, re.MULTILINE), ["0", "3", "4"])

    def test_argument_error_is_exit_2(self):
        self.assertEqual(run_entry("config", "set").returncode, 2, "引数の誤りは argparse の 2 のまま")
        self.assertEqual(run_entry("no-such").returncode, 2)


def load_entry():
    spec = importlib.util.spec_from_file_location("disk_usage_triage_entry", ENTRY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PythonVersionTest(unittest.TestCase):
    """Python の版が 3.11 より古ければ、版を示して終了コード 3 で終了する (計画の節「Assumptions」と KTD14)。"""

    def run_main(self, version_info, argv, with_stderr=False):
        entry = load_entry()
        output, error = io.StringIO(), io.StringIO()
        with mock.patch.object(entry.sys, "version_info", version_info), contextlib.redirect_stdout(output), \
                contextlib.redirect_stderr(error):
            code = entry.main(argv)
        if with_stderr:
            return code, output.getvalue(), error.getvalue()
        self.assertEqual(error.getvalue(), "")
        return code, output.getvalue()

    def test_old_python_hook_writes_to_stderr(self):
        """サブコマンド hook では、版の誤りを標準エラー出力に書き、標準出力には何も書かない。標準出力の JSON は Claude Code に
        hook の出力として読まれ、hook の誤りとして示されないことがあるため (計画の U8 を実装するときに利用者が決めた。2026-11-24)。"""
        code, output, error = self.run_main((3, 9, 6, "final", 0), ["hook", "pre-tool-use"], with_stderr=True)
        self.assertEqual(code, 3)
        self.assertEqual(output, "")
        self.assertIn("disk-usage-triage", error)
        self.assertIn("3.11", error)
        self.assertIn("3.9.6", error, "実際の版を示すこと")

    def test_old_python_exits_with_3(self):
        code, output = self.run_main((3, 9, 6, "final", 0), ["config", "show"])
        self.assertEqual(code, 3)
        payload = json.loads(output)
        self.assertEqual(len(payload["errors"]), 1)
        self.assertIn("3.11", payload["errors"][0])
        self.assertIn("3.9.6", payload["errors"][0], "実際の版を示すこと")

    def test_old_python_is_checked_before_parsing_arguments(self):
        """古い版では、--help も引数の誤りも、版の誤りとして返す (argparse の終了コード 2 にしない)。"""
        for argv in (["--help"], ["no-such"]):
            with self.subTest(argv=argv):
                code, output = self.run_main((3, 10, 12, "final", 0), argv)
                self.assertEqual(code, 3)
                self.assertIn("3.10.12", json.loads(output)["errors"][0])

    def test_entry_parses_with_old_grammar(self):
        """版を確認する前に、入口のファイルを古い版の Python が読めること (macOS の /usr/bin/python3 は 3.9 のことがある)。"""
        with open(ENTRY, encoding="utf-8") as f:
            ast.parse(f.read(), feature_version=(3, 9))


if __name__ == "__main__":
    unittest.main()
