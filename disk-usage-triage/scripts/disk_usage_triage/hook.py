"""hook PreToolUse (計画 docs/plans/2026-11-22-1630-feat-disk-usage-triage-plan.md の R45・KD14・KTD8・KTD9)。

ファイル `disk-usage-triage/hooks/hooks.json` が、Bash ツール・MCP ツール `mcp__terminal__run_in_terminal` (アプリの Terminal
パネルにコマンドを送るツール)・Write・Edit・MultiEdit・NotebookEdit ツールを実行する前に、サブコマンド `hook pre-tool-use` と
して実行する。Claude が削除のシェルスクリプトを実行することと、書き換えることを拒否する。削除のシェルスクリプトは、利用者が
中身を確認してから端末で実行するもので、Claude は実行しない (計画の KD1)。

拒否するのは、次の文字列のどれかを含むもの (KTD8)。

- 文字列 `disk-usage-triage/runs` (保存先のディレクトリ `~/.claude/disk-usage-triage/` の下の、トリアージのディレクトリ `runs`)
- 保存先のディレクトリの下の `runs` の絶対パス (環境変数 `DISK_USAGE_TRIAGE_HOME` で保存先のディレクトリを変えたときのため)
- 削除のシェルスクリプトのファイル名 `disk-usage-triage-delete.sh`

Bash ツールと `mcp__terminal__run_in_terminal` は、入力 `tool_input` のすべての文字列 (入れ子のオブジェクトと配列の中を含む) を
検査し、実行か読み取りかを区別せずに拒否する (KD14。コマンドの文字列からは、実行するのかを判断しきれないため)。コマンドの
キー `command` だけでなく、タブを開くディレクトリ (キー `cwd`) や説明 (キー `description`) も検査するので、`runs` のディレクトリで
開いたタブのコマンドも拒否でき、入力の形が変わってキー `command` が無くなっても拒否できる (計画の U8 を実装するときに利用者が
決めた。2026-11-24)。Write・Edit・MultiEdit はキー `file_path`、NotebookEdit はキー `notebook_path` (書き込むファイルのパス)
だけを検査する。書く内容 (`content` など) を検査すると、削除のシェルスクリプトのファイル名を書いた文書を、このリポジトリの
開発で直せなくなるため。

コマンドの文字列しか見ないので、パスを別の形で書いたコマンド (変数・相対パス・別のファイルに書いたコマンド) は検出できない
(計画の節「Risks & Dependencies」。KD14 で受け入れた)。保存先のディレクトリは読みも書きもしない。
"""

import json
import os

from . import store

RUNS = "runs"
DEFAULT_RUNS = "disk-usage-triage/runs"
SCRIPT_NAME = "disk-usage-triage-delete.sh"

COMMAND_TOOLS = ("Bash", "mcp__terminal__run_in_terminal")
PATH_KEYS = {"Write": "file_path", "Edit": "file_path", "MultiEdit": "file_path", "NotebookEdit": "notebook_path"}
TOOLS = (*COMMAND_TOOLS, *PATH_KEYS)  # hooks.json の matcher と同じ順序

_POLICY = ("disk-usage-triage は、トリアージのディレクトリ (runs) のパスか、削除のシェルスクリプトのファイル名 "
           f"{SCRIPT_NAME} を含むコマンドを、実行か読み取りかを問わずに拒否し、それらのパスへの書き込みも拒否する。"
           "削除のシェルスクリプトは、利用者が中身を確認してから端末で実行するもので、Claude は実行も書き換えもしない。")


class InvalidInput(Exception):
    """hook の入力が読めない (JSON として読めない・オブジェクトでない・キーの値の型が違う)。"""


def needles():
    """拒否する文字列の配列 (KTD8)。"""
    return [DEFAULT_RUNS, os.path.join(store.home(), RUNS), SCRIPT_NAME]


def _found(text):
    """text が含む、拒否する文字列。含まなければ None。"""
    return next((needle for needle in needles() if needle in text), None)


def _strings(value):
    """value (JSON から読んだ値) の中の、すべての文字列の値。オブジェクトのキーは含まない。"""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _string(tool_input, tool_name, key):
    value = tool_input.get(key)
    if not isinstance(value, str):
        raise InvalidInput(f"{tool_name} の入力 tool_input の {key} が文字列でない")
    return value


def _deny(reason):
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}


def pre_tool_use(input_text):
    """hook の入力の JSON を受け、出力する JSON を返す。拒否しないときは None。入力が読めなければ InvalidInput を送出する。"""
    try:
        event = json.loads(input_text)
    except ValueError as e:
        raise InvalidInput(f"hook の入力を JSON として読めない ({e})") from None
    if not isinstance(event, dict):
        raise InvalidInput("hook の入力が JSON のオブジェクトでない")
    tool_name = event.get("tool_name")
    if not isinstance(tool_name, str):
        raise InvalidInput("hook の入力の tool_name が文字列でない")
    if tool_name not in TOOLS:
        return None
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        raise InvalidInput(f"{tool_name} の入力 tool_input が JSON のオブジェクトでない")

    if tool_name in COMMAND_TOOLS:
        needle = next((found for found in map(_found, _strings(tool_input)) if found is not None), None)
        if needle is None:
            return None
        return _deny(f"disk-usage-triage の hook が、このコマンドを実行する前に拒否した (入力が {needle} を含むため)。"
                     + _POLICY)
    needle = _found(_string(tool_input, tool_name, PATH_KEYS[tool_name]))
    if needle is None:
        return None
    return _deny(f"disk-usage-triage の hook が、このファイルへの書き込みを拒否した (パスが {needle} を含むため)。" + _POLICY)
