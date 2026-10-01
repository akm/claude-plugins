"""wording-guard の設定ファイルを読む。

設定ファイルの置き場は、リポジトリのルートからの相対パス
`.claude/akm-claude-plugins/wording-guard/config.json`。各キーの意味の正本は
ファイル `wording-guard/skills/wording-guard/references/project-config.md`。

ここで型を検査するのは、このモジュールが使うキー (`terms_paths`・`frozen_paths`) だけ。
`convention_paths`・`quote_markers` はスキル (モデル) が読むので、ここでは検査しない。
"""

import json
import os
import subprocess

CONFIG_RELPATH = os.path.join(".claude", "akm-claude-plugins", "wording-guard", "config.json")


class ConfigError(Exception):
    """設定ファイルや用語ファイルが読めない、または様式に合わないときのエラー。"""


def find_root(start):
    """パス start を含む git リポジトリのルートを返す。リポジトリの外なら None を返す。

    start が存在しないパス (これから作るファイルなど) のときは、存在する祖先から探す。
    """
    d = os.path.abspath(start)
    if not os.path.isdir(d):
        d = os.path.dirname(d)
    while not os.path.isdir(d):
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent
    r = subprocess.run(["git", "-C", d, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return r.stdout.strip()


def load(root):
    """リポジトリ root の設定を読んで dict で返す。設定ファイルが無ければ None を返す。

    設定ファイルが無いことはエラーではない (wording-guard は設定なしで実行できる)。
    ファイルがあるのに読めない・様式に合わないときは ConfigError を送出する。
    """
    path = os.path.join(root, CONFIG_RELPATH)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise ConfigError(f"設定ファイル {path} を読めない: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError(f"設定ファイル {path} の最上位が JSON のオブジェクトでない")
    for key in ("terms_paths", "frozen_paths"):
        if key in data and not _is_str_list(data[key]):
            raise ConfigError(f"設定ファイル {path} のキー {key} は文字列の配列にする")
    return data


def _is_str_list(value):
    return isinstance(value, list) and all(isinstance(v, str) and v for v in value)


def terms_paths(root, cfg):
    """設定キー terms_paths が指す用語ファイルの絶対パスを、書かれた順に返す。

    `~` で始まるパスはホームディレクトリに展開し、相対パスはリポジトリのルートからのパスとして扱う。
    ファイルが無ければ ConfigError を送出する (設定に書いたファイルが無いのは誤りなので、無視しない)。
    """
    if not cfg or "terms_paths" not in cfg:
        return []
    result = []
    for p in cfg["terms_paths"]:
        full = os.path.expanduser(p)
        if not os.path.isabs(full):
            full = os.path.join(root, full)
        if not os.path.isfile(full):
            raise ConfigError(f"設定キー terms_paths の {p} が無い (探した場所: {full})")
        result.append(full)
    return result
