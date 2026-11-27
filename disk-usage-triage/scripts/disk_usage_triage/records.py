"""記録 (計画 docs/plans/2026-11-22-1630-feat-disk-usage-triage-plan.md の R18〜R22・KD11・KTD16)。

記録は、利用者と Claude が決めた判定を、次回の判定に使うために保存したもの。保存先のディレクトリのファイル `records.json` に
ある。様式と規則の SSOT は、文書 `disk-usage-triage/references/files.md` の節「`records.json`」「`records add` の入力」
「Claude の判定の入力」。

- 対象 (記録が指すもの) 1 つに、記録は 1 つ。同じ対象を記録し直すと置き換える。ディレクトリが同じ対象かは、パスの文字列と
  ディレクトリの識別子で比べる (関数 find。比べ方は judge.DirectoryRecords)。
- 保護の一覧の場所には、どの判定も記録しない。
- 利用者の記録 (関数 add_user) は、既にある記録を置き換えるときに、判定・だれが決めたか・日付だけを変え、ほかのキーを残す。
  利用者が理由を言ったときだけ、理由を変える。Claude の記録 (関数 add_claude) は、利用者の記録を置き換えない。
- 記録が壊れているときは、読むときも書くときも、何も書かずに理由を返す (計画の KTD2)。
- 記録の一覧 (関数 list_records) は、記録の中身から求めた一覧の ID を返す。削除 (関数 remove) は、一覧の ID が今の記録から
  求めた値と違えば、何も消さない。一覧を示した後に記録が変わると、番号が別の記録を指すため。
"""

import datetime
import hashlib
import json
import os
import re
import stat

from . import commands, judge, store

RECORDS = "records.json"
TOP_KEYS = ("version", "records")
RECORD_KEYS = ("target", "judgment", "decided_by", "decided_on", "reason", "impact", "basis", "command",
               "process_names")  # files.md の記録のキーの表と同じ順序
DECIDERS = ("user", "claude")
USER_JUDGMENTS = ("deletable", "keep")
ADD_INPUT_KEYS = ("target", "judgment", "reason")  # records add の入力
CLAUDE_INPUT_KEYS = ("judgment", "reason", "impact", "basis", "command", "process_names")  # Claude の判定の入力
CLAUDE_REQUIRED_KEYS = ("judgment", "reason", "impact", "basis", "command")

# 対象の種類と、種類ごとのキー。files.md の節「対象」の表と同じ順序で、一覧はこの順に並べる
TARGET_KINDS = {
    "directory": ("path",),
    "docker-volume": ("name",),
    "docker-compose-project": ("name",),
    "docker-image-repository": ("name",),
    "asdf-version": ("tool", "version"),
}

_VOLUME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]+\Z")  # Docker のボリュームの名前の規則
_PROJECT = re.compile(r"[a-z0-9][a-z0-9_-]*\Z")  # Compose のプロジェクトの名前の規則
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")


def path():
    """records.json の絶対パス。"""
    return os.path.join(store.home(), RECORDS)


def _dump(value):
    return json.dumps(value, ensure_ascii=False)


def _has_control(value):
    return any(ord(c) < 32 or ord(c) == 127 for c in value)


# --- 対象 -----------------------------------------------------------------------------------------------------------

def _name_error(kind, key, value):
    """Docker と asdf の名前の形の誤り。誤りが無ければ None。"""
    if not isinstance(value, str) or value == "":
        return f"{key} が空でない文字列でない"
    if kind == "docker-volume" and not _VOLUME.match(value):
        return f"{key} ({_dump(value)}) が、ボリュームの名前の規則 [a-zA-Z0-9][a-zA-Z0-9_.-]+ に合わない"
    if kind == "docker-compose-project" and not _PROJECT.match(value):
        return f"{key} ({_dump(value)}) が、Compose のプロジェクトの名前の規則 [a-z0-9][a-z0-9_-]* に合わない"
    if kind == "docker-image-repository":
        if _has_control(value) or any(c.isspace() for c in value):
            return f"{key} ({_dump(value)}) が、空白か制御文字を含む"
        if "@" in value or ":" in value.rsplit("/", 1)[-1]:
            return f"{key} ({_dump(value)}) が、タグ (:<タグ>) か @ を含む (リポジトリの名前だけを書く)"
    if kind == "asdf-version":
        if "/" in value or _has_control(value) or value in (".", ".."):
            return f"{key} ({_dump(value)}) が、/ か制御文字を含むか、. か .. である"
    return None


def _target_errors(target, stored):
    """対象の形の誤りの配列。stored が真なら records.json の中の形 (ディレクトリは絶対パス)、偽なら入力の形
    (ディレクトリは絶対パスか ~ か ~/ で始まるパス)。ファイルシステムは見ない。"""
    if not isinstance(target, dict):
        return ["target が JSON のオブジェクトでない"]
    kind = target.get("kind")
    if kind not in TARGET_KINDS:
        return [f"target の kind が {'・'.join(TARGET_KINDS)} のどれでもない"]
    keys = TARGET_KINDS[kind]
    errors = []
    unknown = [key for key in target if key not in ("kind", *keys)]
    if unknown:
        errors.append(f"kind が {kind} の target に、知らないキーがある: {'・'.join(unknown)}")
    errors += [f"kind が {kind} の target に、キー {key} が無い" for key in keys if key not in target]
    if errors:
        return errors
    if kind != "directory":
        return [f"target の {e}" for e in (_name_error(kind, key, target[key]) for key in keys) if e]
    value = target["path"]
    if not isinstance(value, str) or value == "" or "\0" in value:
        return ["target の path が、NUL 文字を含まない空でない文字列でない"]
    if stored:
        return [] if os.path.isabs(value) else [f"target の path ({_dump(value)}) が絶対パスでない"]
    if value == "~" or value.startswith("~/") or (os.path.isabs(value) and not value.startswith("~")):
        return []
    if value.startswith("~"):
        return [f"target の path ({_dump(value)}) が ~<利用者名> で始まる (~ か ~/ で始まるパスか、絶対パスを書く)"]
    return [f"target の path ({_dump(value)}) が相対パス (絶対パスか、~ か ~/ で始まるパスを書く)"]


def _resolve_directory(value):
    """入力のディレクトリのパスを、シンボリックリンクを解決した絶対パスにする。返り値は (パス, 誤りの配列)。"""
    expanded = os.path.expanduser(value)
    try:
        mode = os.stat(expanded).st_mode  # シンボリックリンクはたどる
    except (FileNotFoundError, NotADirectoryError):
        return None, [f"target の path ({_dump(value)}) が存在しない"]
    except OSError as e:
        return None, [f"target の path ({_dump(value)}) があるかを確認できない ({e.strerror})"]
    if not stat.S_ISDIR(mode):
        return None, [f"target の path ({_dump(value)}) がディレクトリでない"]
    return os.path.realpath(expanded), []


def _key(target):
    """対象を比べるための値 (ディレクトリは、パスの文字列での比べ方)。"""
    return (target["kind"], *(target[key] for key in TARGET_KINDS[target["kind"]]))


def find(records, target):
    """記録の配列 records から、対象 target の記録を探す。無ければ None。

    ディレクトリは、パスの文字列か、ディレクトリの識別子が同じ記録 (計画の KTD16)。target の path は、シンボリックリンクを
    解決した絶対パス。Docker と asdf は、種類とキーの値が同じ記録。
    """
    if target["kind"] == "directory":
        real = target["path"]
        try:
            st = os.stat(real)
            identity = (st.st_dev, st.st_ino)
        except OSError:
            identity = None
        return judge.DirectoryRecords(records).find((real, identity))
    key = _key(target)
    return next((record for record in records if _key(record["target"]) == key), None)


def display(target):
    """対象を示す文字列。ディレクトリはホームディレクトリの下なら ~ で始まる形、Docker は名前、asdf は「ツール 版」。"""
    kind = target["kind"]
    if kind == "directory":
        home = os.path.realpath(os.path.expanduser("~"))
        value = target["path"]
        if value == home:
            return "~"
        if value.startswith(home + os.sep):
            return "~" + value[len(home):]
        return value
    if kind == "asdf-version":
        return f"{target['tool']} {target['version']}"
    return target["name"]


# --- records.json の形 ----------------------------------------------------------------------------------------------

def _text_or_null_error(record, key, required):
    value = record[key]
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        return f"{key} が空でない文字列でない" + ("" if required else " (null でもない)")
    return None


def _strings_error(value, key, required):
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        return f"{key} が、空でない文字列の配列でない"
    if required and not value:
        return f"{key} が空 (1 つ以上を書く)"
    return None


def _process_names_error(value):
    if not isinstance(value, list) or not all(isinstance(n, str) and n and "/" not in n for n in value):
        return "process_names が、/ を含まない空でない文字列の配列でない"
    return None


def _command_shape_errors(command):
    """records.json の command の形の誤り。Claude が書いたコマンドの検査 (R16) は、削除のシェルスクリプトを作るときに行う。"""
    if not isinstance(command, dict):
        return ["command が JSON のオブジェクトか null でない"]
    if command.get("type") == "rm":
        return [] if set(command) == {"type"} else ["type が rm の command に、知らないキーがある"]
    if command.get("type") != "tool":
        return ["command の type が rm か tool でない"]
    if not set(command) <= {"type", "args", "env"}:
        return ["type が tool の command に、知らないキーがある"]
    args = command.get("args")
    if not isinstance(args, list) or not args or not all(isinstance(a, str) for a in args):
        return ["command の args が、1 つ以上の文字列の配列でない"]
    env = command.get("env", {})
    if not isinstance(env, dict) or not all(isinstance(v, str) for v in env.values()):
        return ["command の env が、値が文字列のオブジェクトでない"]
    return []


def _record_errors(record):
    """records.json の記録 1 つの形の誤りの配列。"""
    if not isinstance(record, dict):
        return ["JSON のオブジェクトでない"]
    errors = []
    unknown = [key for key in record if key not in RECORD_KEYS]
    if unknown:
        errors.append("知らないキー: " + "・".join(unknown))
    missing = [key for key in RECORD_KEYS if key not in record]
    if missing:
        return errors + ["キーが無い: " + "・".join(missing)]
    errors += _target_errors(record["target"], stored=True)
    decided_by = record["decided_by"]
    claude = decided_by == "claude"
    if decided_by not in DECIDERS:
        errors.append(f"decided_by が {'・'.join(DECIDERS)} のどれでもない")
    judgment = record["judgment"]
    allowed = judge.JUDGMENTS if claude else USER_JUDGMENTS
    if judgment not in allowed:
        errors.append(f"judgment が {'・'.join(allowed)} のどれでもない ({decided_by} の記録)")
    decided_on = record["decided_on"]
    try:
        if not isinstance(decided_on, str) or not _DATE.match(decided_on):
            raise ValueError
        datetime.date.fromisoformat(decided_on)
    except ValueError:
        errors.append("decided_on が YYYY-MM-DD の日付でない")
    errors += [e for e in (_text_or_null_error(record, "reason", claude), _text_or_null_error(record, "impact", claude),
                           _strings_error(record["basis"], "basis", claude),
                           _process_names_error(record["process_names"])) if e]
    command = record["command"]
    if command is not None:
        errors += _command_shape_errors(command)
    directory = isinstance(record["target"], dict) and record["target"].get("kind") == "directory"
    if claude and not directory:
        errors.append("Claude の記録の対象が、ディレクトリでない")
    if claude and judgment == "keep" and command is not None:
        errors.append("Claude の記録で、judgment が keep なのに command が null でない")
    if not directory and (command is not None or record["process_names"]):
        errors.append("Docker か asdf の対象の記録に、command か process_names がある")
    if decided_by == "user" and judgment == "deletable" and not directory:
        errors.append("利用者の「消してよい」の記録の対象が、ディレクトリでない")
    return errors


def _check_stored(data):
    """store が読んだ records.json の中身を確認し、記録の配列を返す。無ければ空の配列。形が違えば Corrupt。"""
    if data is None:
        return []
    errors = []
    unknown = [key for key in data if key not in TOP_KEYS]
    if unknown:
        errors.append("知らないキー: " + "・".join(unknown))
    items = data.get("records")
    if not isinstance(items, list):
        errors.append("records が配列でない")
        raise store.Corrupt(path(), "。".join(errors))
    seen = set()
    for index, record in enumerate(items):
        record_errors = _record_errors(record)
        errors += [f"records[{index}]: {e}" for e in record_errors]
        if not record_errors:
            key = _key(record["target"])
            if key in seen:
                errors.append(f"records[{index}]: 同じ対象 ({display(record['target'])}) の記録が 2 つ以上ある")
            seen.add(key)
    if errors:
        raise store.Corrupt(path(), "。".join(errors))
    return items


def load():
    """記録の配列を返す。records.json が無ければ空の配列、壊れていれば store.Corrupt を送出する。"""
    return _check_stored(store.read(RECORDS))


# --- 追加 -----------------------------------------------------------------------------------------------------------

def _result(status, **fields):
    return {"status": status, **fields}


def _rejected(errors):
    return _result("unsatisfied", record=None, previous=None, path=path(), errors=errors)


def _normalize_target(target, env):
    """入力の対象を、記録の形にする。ディレクトリは、あることを確認し、シンボリックリンクを解決し、保護の一覧に無いことを
    確認する。返り値は (対象, 誤りの配列)。"""
    errors = _target_errors(target, stored=False)
    if errors:
        return None, errors
    if target["kind"] != "directory":
        return dict(target), []
    if env is None:
        raise ValueError("ディレクトリの記録には、保護の一覧 (judge.environment の返り値) が要る")
    real, errors = _resolve_directory(target["path"])
    if errors:
        return None, errors
    protected = judge.protection(real, env)
    if protected is not None:
        return None, [f"{display({'kind': 'directory', 'path': real})} は保護の一覧にある ({protected['label']}: "
                      f"{protected['path']}) ので、記録しない (保護の一覧の場所は、常に「残す」と判定する)"]
    return {"kind": "directory", "path": real}, []


def _today(today):
    return today or datetime.date.today().isoformat()


def _write(build):
    """records.json を読み、build(記録の配列) で (新しい記録, 置き換える記録 (無ければ None), 誤りの配列) を求めて書く。

    壊れていれば、何も書かない。ロックを取る前にも読むのは、壊れているときに保存先のディレクトリとロックのファイルを作らない
    ため。ロックを取った後にも読むのは、その間にほかのプロセスが書いたことがあるため。
    """
    try:
        load()
    except store.Corrupt as e:
        return _rejected([str(e)])
    with store.transaction() as tx:
        try:
            current = _check_stored(tx.read(RECORDS))
        except store.Corrupt as e:
            return _rejected([str(e)])
        record, previous, errors = build(current)
        if errors:
            return _rejected(errors)
        kept = [r for r in current if r is not previous]
        tx.write(RECORDS, {"version": store.VERSION, "records": kept + [record]})
    return _result("ok", record=record, previous=previous, path=path(), errors=[])


def add_user(target, judgment, *, reason=None, env=None, today=None):
    """利用者の記録を足す (計画の R21)。judgment は keep か deletable (deletable は、削除のシェルスクリプトを作るときに U7 が渡す)。

    target は入力の対象 (ディレクトリの path は ~ で始まってもよい)。env は保護の一覧 (judge.environment の返り値) で、ディレクトリ
    の対象に要る。既にある記録は、判定・だれが決めたか・日付だけを変えて残し、reason があれば理由も変える。
    返り値: {status ("ok"・"unsatisfied"), record (記録したもの), previous (置き換えた記録), path, errors}。
    """
    errors = []
    if judgment not in USER_JUDGMENTS:
        errors.append(f"利用者の記録の judgment ({_dump(judgment)}) が {'・'.join(USER_JUDGMENTS)} のどれでもない")
    if reason is not None and (not isinstance(reason, str) or not reason.strip()):
        errors.append("reason が空でない文字列でない")
    normalized, target_errors = _normalize_target(target, env)
    errors += target_errors
    if not errors and judgment == "deletable" and normalized["kind"] != "directory":
        errors.append("利用者の「消してよい」は、ディレクトリだけに記録する (Docker と asdf の項目は、選んでも記録しない)")
    if errors:
        return _rejected(errors)
    decided_on = _today(today)

    def build(current):
        previous = find(current, normalized)
        if previous is None:
            record = {"target": normalized, "judgment": judgment, "decided_by": "user", "decided_on": decided_on,
                      "reason": reason, "impact": None, "basis": [], "command": None, "process_names": []}
        else:
            record = {**previous, "target": normalized, "judgment": judgment, "decided_by": "user",
                      "decided_on": decided_on, "reason": reason if reason is not None else previous["reason"]}
        return record, previous, []

    return _write(build)


def claude_input_errors(data):
    """Claude の判定の入力 (files.md の節「Claude の判定の入力」) の誤りの配列。コマンドは R16 で検査する。"""
    if not isinstance(data, dict):
        return ["JSON のオブジェクトでない"]
    errors = []
    unknown = [key for key in data if key not in CLAUDE_INPUT_KEYS]
    if unknown:
        errors.append("知らないキー: " + "・".join(unknown) + " (対象は一覧の番号で指定し、入力には書かない)")
    missing = [key for key in CLAUDE_REQUIRED_KEYS if key not in data]
    if missing:
        return errors + ["キーが無い: " + "・".join(missing)]
    judgment = data["judgment"]
    if judgment not in judge.JUDGMENTS:
        errors.append(f"judgment が {'・'.join(judge.JUDGMENTS)} のどれでもない")
    for key in ("reason", "impact"):
        if not isinstance(data[key], str) or not data[key].strip():
            errors.append(f"{key} が空でない文字列でない")
    error = _strings_error(data["basis"], "basis", required=True)
    if error:
        errors.append(error + " (根拠の無い判定は記録しない)")
    error = _process_names_error(data.get("process_names", []))
    if error:
        errors.append(error)
    command = data["command"]
    if judgment == "keep":
        if command is not None:
            errors.append("judgment が keep なのに、command が null でない")
    elif command is None:
        errors.append("judgment が keep でないのに、command が null (rm で消すなら {\"type\": \"rm\"} を書く)")
    else:
        errors += commands.command_errors(command)
    return errors


def add_claude(path_, data, *, env, today=None):
    """Claude の判定を記録する (計画の R20)。path_ は項目のディレクトリの絶対パス (一覧から U6 が求める)、data は入力。

    利用者の記録がある対象には記録しない。Claude の記録は置き換える。返り値は add_user と同じ。
    """
    errors = claude_input_errors(data)
    normalized, target_errors = _normalize_target({"kind": "directory", "path": path_}, env)
    errors += target_errors
    if errors:
        return _rejected(errors)
    record = {"target": normalized, "judgment": data["judgment"], "decided_by": "claude",
              "decided_on": _today(today), "reason": data["reason"], "impact": data["impact"],
              "basis": list(data["basis"]), "command": data["command"],
              "process_names": list(data.get("process_names", []))}

    def build(current):
        previous = find(current, normalized)
        if previous is not None and previous["decided_by"] == "user":
            return None, previous, [f"{display(normalized)} には利用者の記録がある ({previous['decided_on']} に"
                                    f"「{judge.JUDGMENT_LABELS[previous['judgment']]}」) ので、Claude の判定で置き換えない"
                                    " (調べ直すときは、利用者が先に記録を消す)"]
        return record, previous, []

    return _write(build)


def _read_input(input_file):
    try:
        with open(input_file, encoding="utf-8") as f:
            return json.load(f), []
    except FileNotFoundError:
        return None, [f"入力のファイル {input_file} が無い"]
    except ValueError as e:  # JSON として読めない (json.JSONDecodeError) か、UTF-8 として読めない (UnicodeDecodeError)
        return None, [f"入力のファイル {input_file} を JSON として読めない ({e})"]
    except OSError as e:
        return None, [f"入力のファイル {input_file} を読めない ({e.strerror})"]


def add_input_errors(data):
    """records add の入力の形の誤りの配列。対象の中身は add_user が検査する。"""
    if not isinstance(data, dict):
        return ["JSON のオブジェクトでない"]
    errors = []
    unknown = [key for key in data if key not in ADD_INPUT_KEYS]
    if unknown:
        errors.append("知らないキー: " + "・".join(unknown))
    errors += [f"キー {key} が無い" for key in ("target", "judgment") if key not in data]
    if "judgment" in data and data["judgment"] != "keep":
        errors.append(f"judgment ({_dump(data['judgment'])}) が keep でない (records add は「残す」だけを記録する。"
                      "利用者の「消してよい」は、削除のシェルスクリプトを作るときに記録する)")
    if "reason" in data and (not isinstance(data["reason"], str) or not data["reason"].strip()):
        errors.append("reason が空でない文字列でない")
    return errors


def add_from_file(input_file):
    """サブコマンド records add。入力のファイルの「残す」を記録する。返り値には display (記録した対象を示す文字列) を足す。"""
    from . import config

    data, errors = _read_input(input_file)
    if not errors:
        errors = add_input_errors(data)
    env = None
    if not errors and isinstance(data["target"], dict) and data["target"].get("kind") == "directory":
        try:
            current = config.load()
        except store.Corrupt as e:
            errors.append(str(e))
        else:
            if current is None:
                errors.append(f"設定 ({config.path()}) が無い。ディレクトリの記録には、調べるディレクトリ (保護の一覧に入る) の"
                              "設定が要る")
            else:
                env = judge.environment(current)
    if errors:
        return {**_rejected(errors), "display": None}
    result = add_user(data["target"], "keep", reason=data.get("reason"), env=env)
    result["display"] = display(result["record"]["target"]) if result["record"] is not None else None
    return result


# --- 一覧と削除 -------------------------------------------------------------------------------------------------------

def _ordered(records):
    kinds = list(TARGET_KINDS)
    return sorted(records, key=lambda r: (kinds.index(r["target"]["kind"]), _key(r["target"])[1:]))


def _listing(ordered):
    """一覧の ID。並べた記録の中身から求めたハッシュの値の先頭 16 文字。"""
    text = json.dumps(ordered, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _row(number, record):
    return {"number": number, "display": display(record["target"]), **record}


def list_records():
    """サブコマンド records list。記録を、対象の種類の順・パスか名前の順に並べ、1 から番号を付ける (計画の R22)。"""
    try:
        ordered = _ordered(load())
    except store.Corrupt as e:
        return _result("unsatisfied", records=[], listing=None, path=path(), errors=[str(e)])
    return _result("ok", records=[_row(n, r) for n, r in enumerate(ordered, start=1)], listing=_listing(ordered),
                   path=path(), errors=[])


def remove(listing, numbers):
    """サブコマンド records remove。一覧の ID が listing の一覧の番号 numbers の記録を消す (計画の R22・KTD16)。

    一覧を示した後に記録が変わっているか、範囲の外の番号が 1 つでもあれば、何も消さない。同じ番号は 1 つにする。
    """
    def rejected(errors):
        return _result("unsatisfied", removed=[], path=path(), errors=errors)

    def targets(current):
        ordered = _ordered(current)
        if _listing(ordered) != listing:
            return None, ["一覧を示した後に、記録が変わった (一覧の ID が違う)。records list で一覧を示し直してから、番号を"
                          "指定し直す"]
        wanted = list(dict.fromkeys(numbers))
        outside = [n for n in wanted if not 1 <= n <= len(ordered)]
        if outside:
            listed = f"1〜{len(ordered)}" if ordered else "記録が無い"
            return None, [f"番号 {'・'.join(str(n) for n in outside)} は、一覧の範囲の外 ({listed})"]
        return [(n, ordered[n - 1]) for n in wanted], []

    try:
        _, errors = targets(load())
    except store.Corrupt as e:
        return rejected([str(e)])
    if errors:
        return rejected(errors)
    with store.transaction() as tx:
        try:
            current = _check_stored(tx.read(RECORDS))
        except store.Corrupt as e:
            return rejected([str(e)])
        chosen, errors = targets(current)
        if errors:
            return rejected(errors)
        removed = [record for _, record in chosen]
        tx.write(RECORDS, {"version": store.VERSION,
                           "records": [r for r in current if not any(r is x for x in removed)]})
    return _result("ok", removed=[_row(n, r) for n, r in chosen], path=path(), errors=[])
