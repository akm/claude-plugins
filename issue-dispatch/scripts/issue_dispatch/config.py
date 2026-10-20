"""設定の読み込み。管理ディレクトリとリポジトリの設定ファイルを読み、未設定のキーにデフォルト値を当て、
値の誤りを警告し、`files` のパターンの表記をそろえる。承認を得た後に `third_party_edit_check` へリポジトリを足す。

キーと未設定のときの扱いの正本は issue-dispatch/skills/issue-dispatch/references/project-config.md。
呼び出し元: CLI issue-dispatch/scripts/issue_dispatch.py の `config read` と `config add-edit-check`。
ほかのモジュールは `load()` の結果の `config` を受け取り、設定ファイルを直接読まない。

`files` の規則の意味 (`kind` などの値) はここでは確かめない (正本は file-kinds.md。種類の決定はモジュール filekinds)。
`resources` の属性の意味とデフォルト値もここでは確かめない (正本は resources.md。属性の適用はモジュール resources)。
"""

import json
import os
import re

# 設定ファイルの置き場 (管理ディレクトリとリポジトリのルートからの相対パス。両方で同じ)
CONFIG_PATH = os.path.join(".claude", "akm-claude-plugins", "issue-dispatch", "config.json")

ROLES = ("manager", "repo")

# 役割ごとに読むキー。両方にあるキーは、役割ごとに意味が違ってもここでは同じ名前で扱う
MANAGER_KEYS = ("project", "record_dir", "poll_minutes", "wait_minutes", "declare_deadline_minutes",
                "third_party_edit_check", "resources", "repositories")
REPO_KEYS = ("project", "files", "protected_paths", "hooks", "poll_minutes", "wait_minutes")

# 未設定のときのデフォルト値 (KTD15)。`project` は管理ディレクトリでは必須なのでデフォルト値を持たない。
# `hooks.guard_other_worktrees` は、設定ファイルがあれば真、無ければ偽 (設定の無いリポジトリではフックは何もしない)
DEFAULTS = {
    "record_dir": "tmp/issue-dispatch",
    "poll_minutes": 3,
    "wait_minutes": 60,
    "declare_deadline_minutes": 60,
    "third_party_edit_check": [],
    "resources": {},
    "repositories": {},
    "files": [],
    "protected_paths": [],
}
INTEGER_KEYS = ("poll_minutes", "wait_minutes", "declare_deadline_minutes")

_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")


def config_path(root):
    """ルート (管理ディレクトリかリポジトリのルート) の設定ファイルのパス。"""
    return os.path.join(root, CONFIG_PATH)


def _note(key, message):
    return {"key": key, "message": message}


def _is_int(value):
    # bool は int の部分型なので除く
    return isinstance(value, int) and not isinstance(value, bool)


def _read_file(path):
    """設定ファイルを読む。返り値は (status, data)。status は ok / missing / unreadable。"""
    if not os.path.exists(path):
        return "missing", None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        return "unreadable", str(e)
    if not isinstance(data, dict):
        return "unreadable", "JSON の最上位がオブジェクトではない"
    return "ok", data


def normalize_pattern(pattern):
    """`files` のパターンの表記をそろえる。返り値は (そろえたパターン, 警告の文)。警告の文があれば規則を使わない。

    `.` の区切り (先頭の `./` と途中の `/./`) を取り除き、`//` を `/` にする。末尾の `/` は取り除かない
    (`dist/` をファイル名 `dist` だけに一致するパターンに変えないため、posixpath.normpath は使わない)。
    絶対パスと `..` を含むパターンは使わない。
    """
    if not isinstance(pattern, str) or pattern == "":
        return None, "pattern は空でない文字列"
    if pattern.startswith("/"):
        return None, f"絶対パスのパターン {pattern!r} は使わない (ルートからの相対パスで書く)"
    normalized = re.sub(r"/{2,}", "/", pattern)
    trailing_slash = normalized.endswith("/")
    segments = [s for s in normalized.split("/") if s not in (".", "")]
    normalized = "/".join(segments) + ("/" if trailing_slash and segments else "")
    if normalized == "" or normalized == "/":
        return None, f"パターン {pattern!r} はルートそのものを指すので使わない"
    if ".." in normalized.split("/"):
        return None, f"`..` を含むパターン {pattern!r} は使わない (ルートの外を指しうる)"
    return normalized, None


def _check_project(value, required, errors):
    """`project` (owner と number)。管理ディレクトリでは必須。形が違えばエラー (デフォルト値は無い)。"""
    if value is None:
        if required:
            errors.append(_note("project", "project (owner と number) が無い。管理ディレクトリの設定では必須"))
        return None
    ok = (isinstance(value, dict) and isinstance(value.get("owner"), str) and value["owner"] != ""
          and _is_int(value.get("number")) and value["number"] >= 1
          and set(value.keys()) <= {"owner", "number"})
    if not ok:
        errors.append(_note("project", "project は {\"owner\": <文字列>, \"number\": <1 以上の整数>} の形"))
        return None
    return {"owner": value["owner"], "number": value["number"]}


def _check_integer(key, value, warnings):
    if _is_int(value) and value >= 1:
        return value
    warnings.append(_note(key, f"{key} は 1 以上の整数 (値 {value!r})。デフォルト値 {DEFAULTS[key]} で続ける"))
    return DEFAULTS[key]


def _check_repo_list(key, value, warnings):
    if not isinstance(value, list):
        warnings.append(_note(key, f"{key} は owner/repo の配列 (値 {value!r})。空として続ける"))
        return []
    kept = []
    for element in value:
        if isinstance(element, str) and _REPO_RE.match(element):
            kept.append(element)
        else:
            warnings.append(_note(key, f"{key} の要素 {element!r} は owner/repo の形ではない。使わない"))
    return kept


def _check_repositories(value, warnings):
    if not isinstance(value, dict):
        warnings.append(_note("repositories", f"repositories は owner/repo → 絶対パスのオブジェクト (値 {value!r})。空として続ける"))
        return {}
    kept = {}
    for name, path in value.items():
        if not _REPO_RE.match(name):
            warnings.append(_note("repositories", f"repositories のキー {name!r} は owner/repo の形ではない。使わない"))
        elif not (isinstance(path, str) and os.path.isabs(path)):
            warnings.append(_note("repositories", f"repositories の {name} の値 {path!r} は絶対パスではない。使わない"))
        else:
            kept[name] = path
    return kept


def _check_resources(value, warnings):
    if not isinstance(value, dict):
        warnings.append(_note("resources", f"resources は資源の名前 → 属性のオブジェクト (値 {value!r})。空として続ける"))
        return {}
    kept = {}
    for name, attrs in value.items():
        if isinstance(attrs, dict):
            kept[name] = attrs
        else:
            warnings.append(_note("resources", f"resources の {name} の値 {attrs!r} は属性のオブジェクトではない。使わない"))
    return kept


def _check_files(value, warnings):
    if not isinstance(value, list):
        warnings.append(_note("files", f"files は規則の配列 (値 {value!r})。空として続ける"))
        return []
    kept = []
    for rule in value:
        if not (isinstance(rule, dict) and isinstance(rule.get("kind"), str) and rule["kind"] != ""):
            warnings.append(_note("files", f"files の規則 {rule!r} には pattern と kind が要る。使わない"))
            continue
        normalized, problem = normalize_pattern(rule.get("pattern"))
        if problem:
            warnings.append(_note("files", f"files の規則 {rule!r}: {problem}"))
            continue
        kept.append({**rule, "pattern": normalized})
    return kept


def _check_string_list(key, value, warnings):
    if not isinstance(value, list) or not all(isinstance(s, str) and s != "" for s in value):
        warnings.append(_note(key, f"{key} は空でない文字列の配列 (値 {value!r})。空として続ける"))
        return []
    return list(value)


def _check_hooks(value, file_exists, warnings):
    default = bool(file_exists)
    if value is None:
        return {"guard_other_worktrees": default}
    if not isinstance(value, dict):
        warnings.append(_note("hooks", f"hooks はオブジェクト (値 {value!r})。デフォルト値で続ける"))
        return {"guard_other_worktrees": default}
    guard = value.get("guard_other_worktrees", default)
    if not isinstance(guard, bool):
        warnings.append(_note("hooks.guard_other_worktrees",
                              f"hooks.guard_other_worktrees は真偽値 (値 {guard!r})。デフォルト値 {default} で続ける"))
        guard = default
    for key in value:
        if key != "guard_other_worktrees":
            warnings.append(_note(f"hooks.{key}", f"hooks.{key} は知らないキー。使わない"))
    return {"guard_other_worktrees": guard}


def load(root, role):
    """ルートの設定を読む。

    返り値: {"status": "ok" | "missing" | "unreadable", "path": 設定ファイルのパス, "role": role,
             "config": デフォルト値を当てた後の設定, "warnings": [{"key", "message"}], "errors": [{"key", "message"}]}。
    値の誤りはデフォルト値で続行して warnings に、必須のキーの欠けと読めない設定は errors に入れる。
    """
    if role not in ROLES:
        raise ValueError(f"role は {ROLES} のいずれか: {role!r}")
    path = config_path(root)
    status, data = _read_file(path)
    warnings, errors = [], []
    raw = data if status == "ok" else {}
    if status == "unreadable":
        errors.append(_note("(file)", f"設定ファイル {path} を読めない: {data}。デフォルト値で続ける"))
    keys = MANAGER_KEYS if role == "manager" else REPO_KEYS
    for key in raw:
        if key not in keys:
            warnings.append(_note(key, f"{key} は{'管理ディレクトリ' if role == 'manager' else 'リポジトリ'}の設定では使わないキー"))

    config = {}
    project = _check_project(raw.get("project"), required=(role == "manager"), errors=errors)
    if project is not None:
        config["project"] = project
    if role == "manager":
        record_dir = raw.get("record_dir", DEFAULTS["record_dir"])
        if not (isinstance(record_dir, str) and record_dir != ""):
            warnings.append(_note("record_dir", f"record_dir は空でない文字列 (値 {record_dir!r})。デフォルト値で続ける"))
            record_dir = DEFAULTS["record_dir"]
        config["record_dir"] = record_dir
        config["third_party_edit_check"] = (_check_repo_list("third_party_edit_check", raw["third_party_edit_check"], warnings)
                                            if "third_party_edit_check" in raw else [])
        config["resources"] = _check_resources(raw["resources"], warnings) if "resources" in raw else {}
        config["repositories"] = _check_repositories(raw["repositories"], warnings) if "repositories" in raw else {}
    else:
        config["files"] = _check_files(raw["files"], warnings) if "files" in raw else []
        config["protected_paths"] = (_check_string_list("protected_paths", raw["protected_paths"], warnings)
                                     if "protected_paths" in raw else [])
        config["hooks"] = _check_hooks(raw.get("hooks"), status != "missing", warnings)
    warned = set()
    for key in INTEGER_KEYS:
        if key not in keys:
            continue
        before = len(warnings)
        config[key] = _check_integer(key, raw[key], warnings) if key in raw else DEFAULTS[key]
        if len(warnings) > before:
            warned.add(key)
    # 組の検査は、個別の検査でデフォルト値を当てた後の組で行う (以上なら両方をデフォルト値に戻す。project-config.md)。
    # 個別の検査で既に警告したキーには重ねて警告しない
    if config["poll_minutes"] >= config["wait_minutes"]:
        message = (f"poll_minutes ({config['poll_minutes']}) は wait_minutes ({config['wait_minutes']}) より短くする "
                   "(間隔が期限以上だと、待機が 1 回読むごとに期限で終わる)。両方をデフォルト値で続ける")
        for key in ("poll_minutes", "wait_minutes"):
            if key not in warned:
                warnings.append(_note(key, message))
        config["poll_minutes"], config["wait_minutes"] = DEFAULTS["poll_minutes"], DEFAULTS["wait_minutes"]
    return {"status": status, "path": path, "role": role, "config": config, "warnings": warnings, "errors": errors}


def add_edit_check(root, repo):
    """管理ディレクトリの設定の `third_party_edit_check` にリポジトリを足す (承認を得た後に呼ぶ。R18)。

    ほかのキーは変えない (知らないキーも残す)。既にあれば何も書かない。設定ファイルが無ければ (ルートのディレクトリは
    あること)、このキーだけの設定を作る。読めない設定と、既存の値が配列でない設定は上書きしない。
    返り値: {"changed": bool, "path": パス, "errors": [{"key", "message"}]}。
    """
    path = config_path(root)
    if not (isinstance(repo, str) and _REPO_RE.match(repo)):
        return {"changed": False, "path": path, "errors": [_note("repo", f"{repo!r} は owner/repo の形ではない")]}
    if not os.path.isdir(root):
        return {"changed": False, "path": path,
                "errors": [_note("(dir)", f"ディレクトリ {root} が無いので書かない (--dir の打ち間違いを疑う)")]}
    status, data = _read_file(path)
    if status == "unreadable":
        return {"changed": False, "path": path,
                "errors": [_note("(file)", f"設定ファイル {path} を読めないので書かない: {data}")]}
    data = data if status == "ok" else {}
    current = data.get("third_party_edit_check", [])
    if not isinstance(current, list):
        return {"changed": False, "path": path,
                "errors": [_note("third_party_edit_check",
                                 f"third_party_edit_check の値 {current!r} は配列ではないので書かない (手で直す)")]}
    if repo in current:
        return {"changed": False, "path": path, "errors": []}
    data["third_party_edit_check"] = current + [repo]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    return {"changed": True, "path": path, "errors": []}
