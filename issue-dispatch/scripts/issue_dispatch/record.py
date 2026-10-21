"""記録 (管理のセッションが持つ、GitHub から導けないもの) の読み書き。

置き場は `<管理ディレクトリ>/<record_dir>/<owner>-<number>/` で、本体 `record.json` と追記専用の `actions.log` を扱う
(`snapshot.json` と `wait.pid` は別の単位 (観測と待機) が書く)。置き場・キー・扱いの正本は
issue-dispatch/skills/issue-dispatch/references/records.md。

記録は蓄積データなので、壊れていれば `Corrupt` で止めて新規として扱わない (無いときだけ新規)。保存は一時ファイルに
書いて `os.replace` で置き換える (先例 pr-teeth/scripts/prteeth/store.py の `load_precious`・`_save_atomic`)。
更新は操作の配列 (`apply`) で受け、1 つでも誤りがあれば何も適用しない。
呼び出し元: CLI issue-dispatch/scripts/issue_dispatch.py の `record read` / `record apply` / `record log`。
"""

import copy
import json
import os
import re
import tempfile

RECORD_FILE = "record.json"
ACTIONS_LOG = "actions.log"

MANAGER_STATES = ("active", "stopped", "ended")
ACTION_KEYS = ("at", "kind", "target", "before", "after", "reason")
RESEND_LIMIT = 1  # 再送の回数がこれを超えると再送しない (R24)

_ITEM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*#[1-9][0-9]*$")
_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")


class Corrupt(Exception):
    """記録が壊れていて読めない。「無い」(正常な新規) と区別するための型。呼び出し側は保存に進まない。"""

    def __init__(self, path, reason):
        self.path = path
        self.reason = reason
        super().__init__(f"{path} を読めない ({reason})")


def project_key(project):
    """`owner/number` の文字列か `{"owner", "number"}` を `owner/number` にそろえる。"""
    if isinstance(project, dict):
        return f"{project['owner']}/{project['number']}"
    return project


def record_dir(manager_root, record_dir_setting, project):
    """記録の置き場 `<管理ディレクトリ>/<record_dir>/<owner>-<number>/`。"""
    owner, number = project_key(project).split("/")
    return os.path.join(manager_root, record_dir_setting, f"{owner}-{number}")


def new_record(project):
    return {
        "project": project_key(project),
        "manager": None,
        "sessions": {},
        "items": {},
        "opt_in_proposals": {},
        "notices": {},
        "questions": {},
    }


# 要素の形。キー → 許す型の組 (None を許すものは NoneType を含む)
_NONE = type(None)
_MANAGER_SHAPE = {"id": (str,), "name": (str,), "started_at": (str,), "state": (str,), "stop_reason": (str, _NONE),
                  "exchanges_since_input": (int,)}
_SESSION_SHAPE = {"name": (str,), "repo": (str,), "worktree": (str,), "waiting_since": (str, _NONE),
                  "seen_state": (str, _NONE), "refused": (dict, _NONE)}
_ITEM_SHAPE = {"intent": (dict, _NONE), "notified_at": (str, _NONE), "resend_count": (int,), "conflict_choice": (str, _NONE),
               "reported": (dict,), "body_edit_confirmed_at": (str, _NONE)}
_QUESTION_SHAPE = {"item": (str,), "kind": (str,), "options": (list,), "asked_at": (str,), "answer": (str, _NONE),
                   "answered_at": (str, _NONE)}
_OPT_IN_SHAPE = {"proposed_at": (str,), "answer": (bool, _NONE)}


def _check_element(path, where, value, shape):
    if not isinstance(value, dict):
        raise Corrupt(path, f"{where} がオブジェクトではない")
    for key, kinds in shape.items():
        if key not in value:
            raise Corrupt(path, f"{where} に必須のキー {key} が無い")
        if not isinstance(value[key], kinds) or (isinstance(value[key], bool) and bool not in kinds):
            raise Corrupt(path, f"{where} の {key} の型が違う")


def _check_shape(data, path, project):
    if not isinstance(data, dict):
        raise Corrupt(path, "最上位がオブジェクトではない")
    for key, kind in (("project", str), ("sessions", dict), ("items", dict), ("questions", dict)):
        if key not in data:
            raise Corrupt(path, f"必須のキー {key} が無い")
        if not isinstance(data[key], kind):
            raise Corrupt(path, f"{key} が {kind.__name__} ではない")
    if "manager" not in data:
        raise Corrupt(path, "必須のキー manager が無い")
    if data["project"] != project_key(project):
        raise Corrupt(path, f"project が {data['project']!r} で、設定の {project_key(project)!r} と違う")
    for key in ("opt_in_proposals", "notices"):
        data.setdefault(key, {})
        if not isinstance(data[key], dict):
            raise Corrupt(path, f"{key} がオブジェクトではない")
    if data["manager"] is not None:
        _check_element(path, "manager", data["manager"], _MANAGER_SHAPE)
        if data["manager"]["state"] not in MANAGER_STATES:
            raise Corrupt(path, f"manager の state が {data['manager']['state']!r}")
    for sid, s in data["sessions"].items():
        _check_element(path, f"sessions[{sid}]", s, _SESSION_SHAPE)
    for item, it in data["items"].items():
        _check_element(path, f"items[{item}]", it, _ITEM_SHAPE)
    for qid, q in data["questions"].items():
        _check_element(path, f"questions[{qid}]", q, _QUESTION_SHAPE)
    for repo, o in data["opt_in_proposals"].items():
        _check_element(path, f"opt_in_proposals[{repo}]", o, _OPT_IN_SHAPE)


def load(directory, project):
    """記録を読む。無ければ新規の空の記録 (ファイルは作らない)。壊れていれば Corrupt。"""
    path = os.path.join(directory, RECORD_FILE)
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return new_record(project)
    except UnicodeDecodeError as e:
        raise Corrupt(path, f"UTF-8 として読めない: {e}")
    except OSError as e:
        raise Corrupt(path, f"読めない: {e}")
    if not text.strip():
        raise Corrupt(path, "空のファイル")
    try:
        data = json.loads(text)
    except ValueError as e:
        raise Corrupt(path, f"JSON として不正: {e}")
    _check_shape(data, path, project)
    return data


def save(directory, rec):
    """記録を一時ファイルに書いてから置き換える。途中で失敗しても元の記録は残る。"""
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, RECORD_FILE)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".record-", suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ----- 操作 (apply) -----

def _item(rec, item):
    return rec["items"].setdefault(item, {
        "intent": None, "notified_at": None, "resend_count": 0, "conflict_choice": None,
        "reported": {}, "body_edit_confirmed_at": None,
    })


# 省略できるキー (null でもよい)。それ以外のキーは、無い・null を「欠けている」として差し戻す (R31)
OPTIONAL_KEYS = {"set_manager_state": ("stop_reason",), "set_opt_in": ("answer",)}


def _need(op, keys, types=None, optional=()):
    missing = [k for k in keys if op.get(k) is None]
    if missing:
        return f"キー {', '.join(missing)} が無いか null"
    for k, t in (types or {}).items():
        if k not in op:
            continue
        if op[k] is None:
            if k in optional:
                continue
            return f"{k} が null"
        if not isinstance(op[k], t) or (t is int and isinstance(op[k], bool)):
            return f"{k} の型が {t.__name__} ではない"
    if "assignment" in types and op["assignment"] < 1:
        return "assignment は 1 以上の整数"
    if "answer" in keys and op["answer"] == "":
        return "answer は空でない文字列"
    return None


def _op_set_manager(rec, op):
    rec["manager"] = {"id": op["id"], "name": op["name"], "started_at": op["started_at"], "state": "active",
                      "stop_reason": None, "exchanges_since_input": 0}


def _op_set_manager_state(rec, op):
    if rec["manager"] is None:
        return "manager が無い"
    if op["state"] not in MANAGER_STATES:
        return f"state は {', '.join(MANAGER_STATES)} のどれか"
    rec["manager"]["state"] = op["state"]
    rec["manager"]["stop_reason"] = op.get("stop_reason") if op["state"] != "active" else None


def _op_count_exchange(rec, op):
    if rec["manager"] is None:
        return "manager が無い"
    rec["manager"]["exchanges_since_input"] += 1


def _op_reset_exchanges(rec, op):
    if rec["manager"] is None:
        return "manager が無い"
    rec["manager"]["exchanges_since_input"] = 0


def _op_set_session(rec, op):
    s = rec["sessions"].setdefault(op["id"], {"waiting_since": None, "seen_state": None, "refused": None})
    s.update({"name": op["name"], "repo": op["repo"], "worktree": op["worktree"]})


def _session(rec, op):
    s = rec["sessions"].get(op["id"])
    return s, (None if s is not None else f"セッション {op['id']} が無い")


def _op_set_session_state(rec, op):
    s, err = _session(rec, op)
    if err:
        return err
    s["seen_state"] = op["state"]


def _op_set_waiting(rec, op):
    s, err = _session(rec, op)
    if err:
        return err
    s["waiting_since"] = op["since"]


def _op_clear_waiting(rec, op):
    s, err = _session(rec, op)
    if err:
        return err
    s["waiting_since"] = None


def _op_set_refused(rec, op):
    s, err = _session(rec, op)
    if err:
        return err
    if s.get("refused") is None:
        s["refused"] = {"at": op["at"], "signal": op["signal"]}


def _op_set_intent(rec, op):
    it = _item(rec, op["item"])
    it["intent"] = {"session_id": op["session_id"], "session_title": op["session_title"], "status": op["status"],
                    "assignment": op["assignment"], "at": op["at"]}
    it["notified_at"] = None
    it["resend_count"] = 0


def _op_clear_intent(rec, op):
    it = _item(rec, op["item"])
    it["intent"] = None
    it["notified_at"] = None
    it["resend_count"] = 0


def _op_mark_notified(rec, op):
    it = _item(rec, op["item"])
    if it["intent"] is None:
        return f"項目 {op['item']} に意図が無い"
    if it["notified_at"] is None:
        it["notified_at"] = op["at"]


def _op_count_resend(rec, op):
    it = _item(rec, op["item"])
    if it["intent"] is None:
        return f"項目 {op['item']} に意図が無い"
    it["resend_count"] += 1


def _op_set_conflict_choice(rec, op):
    _item(rec, op["item"])["conflict_choice"] = op["choice"]


def _op_mark_reported(rec, op):
    _item(rec, op["item"])["reported"].setdefault(op["kind"], op["at"])


def _op_set_body_edit_confirmed(rec, op):
    _item(rec, op["item"])["body_edit_confirmed_at"] = op["at"]


def _op_set_notice(rec, op):
    rec["notices"].setdefault(op["key"], op["at"])


def _op_set_opt_in(rec, op):
    if not _REPO_RE.match(op["repo"]):
        return f"repo {op['repo']!r} は owner/repo の形ではない"
    rec["opt_in_proposals"][op["repo"]] = {"proposed_at": op["proposed_at"], "answer": op.get("answer")}


def _op_ask(rec, op):
    rec["questions"][op["question_id"]] = {"item": op["item"], "kind": op["kind"], "options": list(op["options"]),
                                           "asked_at": op["at"], "answer": None, "answered_at": None}


def _op_answer(rec, op):
    q = rec["questions"].get(op["question_id"])
    if q is None:
        return f"問い {op['question_id']} が無い"
    if q["options"] and op["answer"] not in q["options"]:
        return f"答え {op['answer']!r} は選択肢 {q['options']} に無い"
    q["answer"] = op["answer"]
    q["answered_at"] = op["at"]


# 操作の種類 → (必須のキー, 型, 関数)。項目のキー (item) は owner/repo#番号 の形を検査する
OPERATIONS = {
    "set_manager": (("id", "name", "started_at"), {"id": str, "name": str, "started_at": str}, _op_set_manager),
    "set_manager_state": (("state",), {"state": str, "stop_reason": str}, _op_set_manager_state),
    "count_exchange": ((), {}, _op_count_exchange),
    "reset_exchanges": ((), {}, _op_reset_exchanges),
    "set_session": (("id", "name", "repo", "worktree"), {"id": str, "name": str, "repo": str, "worktree": str}, _op_set_session),
    "set_session_state": (("id", "state"), {"id": str, "state": str}, _op_set_session_state),
    "set_waiting": (("id", "since"), {"id": str, "since": str}, _op_set_waiting),
    "clear_waiting": (("id",), {"id": str}, _op_clear_waiting),
    "set_refused": (("id", "at", "signal"), {"id": str, "at": str, "signal": str}, _op_set_refused),
    "set_intent": (("item", "session_id", "session_title", "status", "assignment", "at"),
                   {"item": str, "session_id": str, "session_title": str, "status": str, "assignment": int, "at": str}, _op_set_intent),
    "clear_intent": (("item",), {"item": str}, _op_clear_intent),
    "mark_notified": (("item", "at"), {"item": str, "at": str}, _op_mark_notified),
    "count_resend": (("item",), {"item": str}, _op_count_resend),
    "set_conflict_choice": (("item", "choice"), {"item": str, "choice": str}, _op_set_conflict_choice),
    "mark_reported": (("item", "kind", "at"), {"item": str, "kind": str, "at": str}, _op_mark_reported),
    "set_body_edit_confirmed": (("item", "at"), {"item": str, "at": str}, _op_set_body_edit_confirmed),
    "set_notice": (("key", "at"), {"key": str, "at": str}, _op_set_notice),
    "set_opt_in": (("repo", "proposed_at"), {"repo": str, "proposed_at": str, "answer": bool}, _op_set_opt_in),
    "ask": (("question_id", "item", "kind", "options", "at"),
            {"question_id": str, "item": str, "kind": str, "options": list, "at": str}, _op_ask),
    "answer": (("question_id", "answer", "at"), {"question_id": str, "answer": str, "at": str}, _op_answer),
}


def apply(rec, operations):
    """操作の配列を記録に適用した新しい記録と、誤りの配列を返す。1 つでも誤りがあれば元の記録をそのまま返す。"""
    if not isinstance(operations, list):
        return rec, [{"index": None, "message": "操作は配列"}]
    work = copy.deepcopy(rec)
    errors = []
    for i, op in enumerate(operations):
        if not isinstance(op, dict) or not isinstance(op.get("op"), str):
            errors.append({"index": i, "message": "操作はキー op を持つオブジェクト"})
            continue
        spec = OPERATIONS.get(op["op"])
        if spec is None:
            errors.append({"index": i, "message": f"知らない操作 {op['op']!r}"})
            continue
        keys, types, func = spec
        problem = _need(op, keys, types, OPTIONAL_KEYS.get(op["op"], ()))
        if problem is None and "item" in keys and not _ITEM_RE.match(op["item"]):
            problem = f"item {op['item']!r} は owner/repo#番号 の形ではない"
        if problem is None:
            problem = func(work, op)
        if problem:
            errors.append({"index": i, "op": op["op"], "message": problem})
    if errors:
        return rec, errors
    return work, []


# ----- 読み取りの補助 -----

def items_without_notified(rec):
    """割り当ての意図があって印 notified が無い項目 (再入で合図を送り直す候補)。"""
    return sorted(k for k, it in rec["items"].items() if it.get("intent") and it.get("notified_at") is None)


def intent_matches(rec, item, values):
    """Project の値 (session_id・session_title・status) が意図と一致すれば真 (自分の書き込みと判定する)。"""
    intent = rec["items"].get(item, {}).get("intent")
    if not intent:
        return False
    return all(intent.get(k) == v for k, v in values.items())


def can_resend(rec, item):
    """再送の回数が上限 (RESEND_LIMIT) を超えていなければ真。"""
    return rec["items"].get(item, {}).get("resend_count", 0) <= RESEND_LIMIT


def waiting_sessions(rec):
    """待機中のセッションを、待機を始めた時刻の順に。各要素は id を含む辞書。"""
    waiting = [dict(s, id=sid) for sid, s in rec["sessions"].items() if s.get("waiting_since")]
    return sorted(waiting, key=lambda s: (s["waiting_since"], s["id"]))


def is_reported(rec, item, kind):
    return kind in rec["items"].get(item, {}).get("reported", {})


def unanswered_questions(rec):
    return [dict(q, question_id=qid) for qid, q in sorted(rec["questions"].items()) if q.get("answered_at") is None]


# ----- actions.log -----

def append_action(directory, entry):
    """GitHub への書き込みを 1 行 1 JSON で追記する。キーは ACTION_KEYS のすべて。"""
    if not isinstance(entry, dict) or set(entry) != set(ACTION_KEYS):
        raise ValueError(f"actions.log の 1 件はキー {', '.join(ACTION_KEYS)} を持つオブジェクト")
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, ACTIONS_LOG), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
