"""wording-guard の設定ファイルを読む。

設定ファイルの置き場は、リポジトリのルートからの相対パス
`.claude/akm-claude-plugins/wording-guard/config.json`。各キーの意味の正本は
ファイル `wording-guard/skills/wording-guard/references/project-config.md`。

ここで型を検査するのは、このパッケージが使うキー (`terms_paths`・`frozen_paths`・`textlint`) だけ。
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


def read_raw(root):
    """リポジトリ root の設定ファイルを JSON として読み、型を検査せずに dict で返す。無ければ None を返す。

    JSON として読めない・最上位がオブジェクトでないときは ConfigError を送出する。
    hook が、型の検査の前に textlint.hook を見るために使う。
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
    return data


def hook_enabled(raw):
    """read_raw で読んだ設定で、設定キー textlint.hook が true か (型を検査する前の判定)。"""
    settings = (raw or {}).get("textlint")
    return isinstance(settings, dict) and settings.get("hook") is True


def load(root):
    """リポジトリ root の設定を読んで dict で返す。設定ファイルが無ければ None を返す。

    設定ファイルが無いことはエラーではない (wording-guard は設定なしで実行できる)。
    ファイルがあるのに読めない・様式に合わないときは ConfigError を送出する。
    """
    data = read_raw(root)
    if data is None:
        return None
    path = os.path.join(root, CONFIG_RELPATH)
    for key in ("terms_paths", "frozen_paths"):
        if key in data and not _is_str_list(data[key]):
            raise ConfigError(f"設定ファイル {path} のキー {key} は文字列の配列にする")
    if "textlint" in data:
        _check_textlint(data["textlint"], path)
    return data


TEXTLINT_KEYS = {"config", "hook"}


def _check_textlint(value, path):
    if not isinstance(value, dict):
        raise ConfigError(f"設定ファイル {path} のキー textlint はオブジェクトにする")
    unknown = sorted(set(value) - TEXTLINT_KEYS)
    if unknown:
        raise ConfigError(f"設定ファイル {path} のキー textlint に知らないキーがある: {', '.join(unknown)}")
    if "config" in value and (not isinstance(value["config"], str) or not value["config"]):
        raise ConfigError(f"設定ファイル {path} のキー textlint.config は空でない文字列にする")
    if "hook" in value and not isinstance(value["hook"], bool):
        raise ConfigError(f"設定ファイル {path} のキー textlint.hook は true か false にする")


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


def textlint_settings(cfg):
    """設定キー textlint の値を返す。textlint を使わないリポジトリ (キーが無い) では None を返す。"""
    if not cfg:
        return None
    return cfg.get("textlint")


def textlint_config_path(root, cfg):
    """設定キー textlint.config が指す textlint の設定ファイルの絶対パスを返す。未設定なら None を返す。"""
    settings = textlint_settings(cfg) or {}
    if "config" not in settings:
        return None
    full = os.path.expanduser(settings["config"])
    if not os.path.isabs(full):
        full = os.path.join(root, full)
    if not os.path.isfile(full):
        raise ConfigError(f"設定キー textlint.config の {settings['config']} が無い (探した場所: {full})")
    return full


def is_frozen(root, cfg, path):
    """パス path が、設定キー frozen_paths (書き換えない過去の記録のパス接頭辞) のどれかで始まれば True。"""
    if not cfg or "frozen_paths" not in cfg:
        return False
    # macOS の /tmp と /private/tmp のように、同じ場所を指す別のパスがあるので、実体のパスで比べる
    rel = os.path.relpath(os.path.realpath(path), os.path.realpath(root))
    if rel == ".." or rel.startswith(".." + os.sep):
        return False
    rel = rel.replace(os.sep, "/")
    return any(rel.startswith(prefix) for prefix in cfg["frozen_paths"])
