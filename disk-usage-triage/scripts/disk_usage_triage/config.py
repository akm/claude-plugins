"""設定 (計画 docs/plans/2026-11-22-1630-feat-disk-usage-triage-plan.md の R1〜R4・KTD2・KTD3)。

設定は、保存先のディレクトリのファイル `config.json` にある。様式と検査の内容の SSOT は、文書
`disk-usage-triage/references/files.md` の節「`config.json`」と「`config set` の入力」。

- 設定が無いときは、誤りにしない。サブコマンド `config show` が設定が無いことを出力し、スキルが利用者に質問する (計画の R1)。
- 設定が壊れているときは、読むときも書くときも、何も書かずに終了コード 3 で示す (計画の KTD2)。
- `config set` は、Claude が書いた入力のファイルの内容で、設定の全体を置き換える。省いた時間の上限は 300 を書く
  (U2 を実装するときに利用者と決めた。2026-11-23)。
"""

import json
import os
import stat

from . import store

CONFIG = "config.json"
KEYS = ("scan_dirs", "project_dirs", "timeout_seconds")  # files.md のキーの表と同じ順序
PATH_KEYS = ("scan_dirs", "project_dirs")
DEFAULT_TIMEOUT_SECONDS = 300  # 計画の R4


def path():
    """config.json の絶対パス。"""
    return os.path.join(store.home(), CONFIG)


def _dump(value):
    return json.dumps(value, ensure_ascii=False)


def _path_form_error(value):
    """パスの書き方の誤り。誤りが無ければ None。ファイルシステムは見ない。"""
    if not isinstance(value, str):
        return "文字列でない"
    if value == "":
        return "空の文字列"
    if "\0" in value:
        return "NUL 文字を含む"
    if value == "~" or value.startswith("~/"):
        return None
    if value.startswith("~"):
        return "~<利用者名> で始まるパスは受け付けない (~ か ~/ で始まるパスか、絶対パスを書く)"
    if not os.path.isabs(value):
        return "相対パスは受け付けない (絶対パスか、~ か ~/ で始まるパスを書く)"
    return None


def _timeout_error(value):
    if type(value) is not int or value < 1:  # 真偽値 (int の派生) と小数も誤りにする
        return f"timeout_seconds ({_dump(value)}) が 1 以上の整数でない"
    return None


def _shape_errors(data, required):
    """形の誤りの配列。required は必須のキー。ファイルシステムは見ない。"""
    if not isinstance(data, dict):
        return ["JSON のオブジェクトでない"]
    errors = []
    unknown = [key for key in data if key not in KEYS]
    if unknown:
        errors.append("知らないキー: " + "・".join(unknown))
    errors += [f"キー {key} が無い" for key in required if key not in data]
    for key in PATH_KEYS:
        if key not in data:
            continue
        values = data[key]
        if not isinstance(values, list):
            errors.append(f"{key} が配列でない")
            continue
        if not values:
            errors.append(f"{key} が空 (1 つ以上のディレクトリを書く)")
        for index, value in enumerate(values):
            error = _path_form_error(value)
            if error:
                errors.append(f"{key}[{index}] ({_dump(value)}): {error}")
    if "timeout_seconds" in data:
        error = _timeout_error(data["timeout_seconds"])
        if error:
            errors.append(error)
    return errors


def stored_shape_errors(data):
    """config.json の中身 (version を除く) の形の誤りの配列。version は store.read が確認する。"""
    if isinstance(data, dict):
        data = {key: value for key, value in data.items() if key != "version"}
    return _shape_errors(data, KEYS)


def input_shape_errors(data):
    """config set の入力の形の誤りの配列。timeout_seconds は省ける。"""
    return _shape_errors(data, PATH_KEYS)


def _directory_error(value):
    """~ を展開した場所にディレクトリがあるか。誤りが無ければ None。"""
    try:
        mode = os.stat(os.path.expanduser(value)).st_mode  # シンボリックリンクはたどる
    except (FileNotFoundError, NotADirectoryError):
        return "存在しない"
    except OSError as e:
        return f"ディレクトリがあるかを確認できない ({e.strerror})"
    if not stat.S_ISDIR(mode):
        return "ディレクトリでない"
    return None


def _overlap_errors(values):
    """調べるディレクトリの重複と入れ子の誤りの配列。シンボリックリンクを解決した実パスで比べる。"""
    reals = [os.path.realpath(os.path.expanduser(value)) for value in values]
    errors = []
    for i in range(len(values)):
        for j in range(i + 1, len(values)):
            a, b = reals[i], reals[j]
            left, right = f"scan_dirs[{i}] ({_dump(values[i])})", f"scan_dirs[{j}] ({_dump(values[j])})"
            if a == b:
                errors.append(f"{left} と {right} が同じディレクトリ ({a}) を指す")
            elif os.path.commonpath([a, b]) == a:
                errors.append(f"{right} が {left} の下にある (調べるディレクトリは、一方を他方の下にしない)")
            elif os.path.commonpath([a, b]) == b:
                errors.append(f"{left} が {right} の下にある (調べるディレクトリは、一方を他方の下にしない)")
    return errors


def input_errors(data):
    """config set の入力の誤りの配列 (形・ディレクトリがあるか・調べるディレクトリの重複と入れ子)。"""
    errors = input_shape_errors(data)
    if not isinstance(data, dict):
        return errors
    for key in PATH_KEYS:
        values = data.get(key)
        if not isinstance(values, list):
            continue
        for index, value in enumerate(values):
            if _path_form_error(value) is None:
                error = _directory_error(value)
                if error:
                    errors.append(f"{key}[{index}] ({_dump(value)}): {error}")
    scan_dirs = data.get("scan_dirs")
    if not errors and isinstance(scan_dirs, list):
        errors += _overlap_errors(scan_dirs)
    return errors


def _check_stored(data):
    """store が読んだ config.json の中身を確認し、version を除いた設定を返す。無ければ None。形が違えば Corrupt。"""
    if data is None:
        return None
    errors = stored_shape_errors(data)
    if errors:
        raise store.Corrupt(path(), "。".join(errors))
    return {key: data[key] for key in KEYS}


def load():
    """設定 (version を除いたもの) を返す。無ければ None、壊れていれば store.Corrupt を送出する。"""
    return _check_stored(store.read(CONFIG))


def _result(status, **fields):
    return {"status": status, **fields}


def show():
    """サブコマンド config show。"""
    common = {"path": path(), "inputs_dir": store.inputs_dir()}
    try:
        current = load()
    except store.Corrupt as e:
        return _result("unsatisfied", exists=True, config=None, **common, errors=[str(e)])
    return _result("ok", exists=current is not None, config=current, **common, errors=[])


def _read_input(input_file):
    """入力のファイルを読む。返り値は (中身, 誤りの配列)。"""
    try:
        with open(input_file, encoding="utf-8") as f:
            return json.load(f), []
    except FileNotFoundError:
        return None, [f"入力のファイル {input_file} が無い"]
    except ValueError as e:  # JSON として読めない (json.JSONDecodeError) か、UTF-8 として読めない (UnicodeDecodeError)
        return None, [f"入力のファイル {input_file} を JSON として読めない ({e})"]
    except OSError as e:
        return None, [f"入力のファイル {input_file} を読めない ({e.strerror})"]


def set_from_file(input_file):
    """サブコマンド config set。入力に誤りがあるか、config.json が壊れていれば、何も書かない。"""
    data, errors = _read_input(input_file)
    if not errors:
        errors = input_errors(data)
    try:
        load()  # 入力の誤りと一緒に示すため、ロックを取る前にも確認する (保存先のディレクトリを作らない)
    except store.Corrupt as e:
        errors.append(str(e))
    if errors:
        return _result("unsatisfied", config=None, previous=None, path=path(), errors=errors)
    new = {"scan_dirs": list(data["scan_dirs"]), "project_dirs": list(data["project_dirs"]),
           "timeout_seconds": data.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)}
    with store.transaction() as tx:
        try:
            previous = _check_stored(tx.read(CONFIG))  # ロックを取るまでの間に、ほかのプロセスが書いたことがあるため
        except store.Corrupt as e:
            return _result("unsatisfied", config=None, previous=None, path=path(), errors=[str(e)])
        tx.write(CONFIG, {"version": store.VERSION, **new})
    return _result("ok", config=new, previous=previous, path=path(), errors=[])
