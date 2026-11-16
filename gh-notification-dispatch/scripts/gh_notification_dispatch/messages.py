"""セッション間のメッセージの生成と解析 (計画 docs/plans/2026-11-14-1428-feat-gh-notification-dispatch-plan.md の KTD8)。

様式の SSOT は文書 `gh-notification-dispatch/references/messages.md`。このモジュールの定数は、その文書の表と一致する
(ファイル `gh-notification-dispatch/tests/test_docs.py` で確認する)。

解析した値は、登録の情報としてだけ扱う (計画の R7)。本文は利用者や別のセッションが書いた文字列なので、このモジュールは
値の形だけを検査し、値に書かれた文を解釈しない。
"""

import re

PREFIX = "gh-notification-dispatch:"

KINDS = ("review_requested", "merged")
PERMISSION_MODES = ("default", "acceptEdits", "plan", "auto", "dontAsk", "bypassPermissions")
# 権限の確認を省く権限モード。これとそれ以外で、メッセージを保留するかが決まる (計画の R4)
SKIP_CONFIRMATION_MODES = ("bypassPermissions",)
RESULTS = ("accepted", "rejected")

# type ごとの (必須のキー, 任意のキー)。type の行の後に、この順に書く。出来事を届ける notify は U3 で足す
FIELDS = {
    "subscribe": (("repo", "kinds", "session-id", "session-name", "permission-mode"), ()),
    "unsubscribe": (("subscription-ids", "session-id", "session-name"), ()),
    "subscribed": (("result",), ("repo", "added", "existing", "warning", "reason")),
    "unsubscribed": (("result",), ("removed", "reason")),
    "removed": (("removed",), ()),
}
TYPES = tuple(FIELDS)

REPO_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}")
SESSION_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,100}")
SUBSCRIPTION_ID_RE = re.compile(r"[0-9a-f]{12}")
MAX_NAME_LENGTH = 200

_LINE_RE = re.compile(r"([a-z][a-z-]*):(?: (.*))?")


def permission_class(mode):
    """権限モードの分類。`skip` (確認を省く) か `confirm` (確認する)。"""
    return "skip" if mode in SKIP_CONFIRMATION_MODES else "confirm"


def check_repo(value):
    """`owner/repo` の形なら None、違えば理由。"""
    if not REPO_RE.fullmatch(value or "") or value.split("/")[1] in (".", ".."):
        return f"リポジトリ {value!r} が owner/repo の形でない"
    return None


def check_session_id(value):
    if not SESSION_ID_RE.fullmatch(value or ""):
        return f"セッションの ID {value!r} が英数字・_・- の 100 文字以内でない"
    return None


def check_name(value):
    if not value or not value.strip():
        return "セッションの名前が空"
    if len(value) > MAX_NAME_LENGTH or "\n" in value or "\r" in value:
        return f"セッションの名前が 1 行の {MAX_NAME_LENGTH} 文字以内でない"
    return None


def check_permission_mode(value):
    if value not in PERMISSION_MODES:
        return f"権限モード {value!r} が {'・'.join(PERMISSION_MODES)} のどれでもない"
    return None


def parse_kinds(value):
    """種類のカンマ区切りを読む。返り値は (種類の配列, 理由の配列)。同じ種類は 1 つにする。"""
    if not (value or "").strip():
        return [], ["種類が無い"]
    kinds, errors = [], []
    for item in value.split(","):
        item = item.strip()
        if item not in KINDS:
            errors.append(f"種類 {item!r} が {'・'.join(KINDS)} のどれでもない")
        elif item not in kinds:
            kinds.append(item)
    return kinds, errors


def parse_subscription_ids(value):
    """登録の ID のカンマ区切りを読む。返り値は (ID の配列, 理由の配列)。同じ ID は 1 つにする。"""
    if not (value or "").strip():
        return [], ["登録の ID が無い"]
    ids, errors = [], []
    for item in value.split(","):
        item = item.strip()
        if not SUBSCRIPTION_ID_RE.fullmatch(item):
            errors.append(f"登録の ID {item!r} が 12 桁の 16 進数でない")
        elif item not in ids:
            ids.append(item)
    return ids, errors


def _check_value(key, value):
    """キーごとの値の検査。返り値は (読んだ値, 理由の配列)。"""
    if key == "repo":
        error = check_repo(value)
        return value, [error] if error else []
    if key in ("kinds", "added", "existing"):
        return parse_kinds(value)
    if key == "session-id":
        error = check_session_id(value)
        return value, [error] if error else []
    if key == "session-name":
        error = check_name(value)
        return value, [error] if error else []
    if key == "permission-mode":
        error = check_permission_mode(value)
        return value, [error] if error else []
    if key == "subscription-ids":
        return parse_subscription_ids(value)
    if key == "result":
        return value, [] if value in RESULTS else [f"result {value!r} が {'・'.join(RESULTS)} のどれでもない"]
    if not value:
        return value, [f"キー {key} の値が空"]
    return value, []


def parse(text):
    """メッセージの本文を解析する。

    返り値: {"type" (読めなければ None), "head" (先頭行), "fields" (キーと読んだ値。kinds・added・existing・subscription-ids は
    配列), "errors" (形の誤りの配列)}。errors が空のときだけ、type と fields を使う。
    """
    lines = [line.rstrip() for line in (text or "").replace("\r\n", "\n").split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    while lines and not lines[0]:
        lines.pop(0)
    result = {"type": None, "head": lines[0] if lines else "", "fields": {}, "errors": []}
    errors = result["errors"]
    if not lines or not lines[0].startswith(PREFIX):
        errors.append(f"1 行目が {PREFIX} で始まらない")
        return result
    pairs = []
    for number, line in enumerate(lines[1:], start=2):
        match = _LINE_RE.fullmatch(line)
        if not match:
            errors.append(f"{number} 行目が <キー>: <値> の形でない")
            continue
        pairs.append((match.group(1), (match.group(2) or "").strip()))
    if errors:
        return result
    if not pairs or pairs[0][0] != "type":
        errors.append("2 行目が type: の行でない")
        return result
    type_ = pairs[0][1]
    if type_ not in FIELDS:
        errors.append(f"type {type_!r} が {'・'.join(TYPES)} のどれでもない")
        return result
    result["type"] = type_
    required, optional = FIELDS[type_]
    seen = set()
    for key, value in pairs[1:]:
        if key in seen:
            errors.append(f"キー {key} が 2 回ある")
            continue
        seen.add(key)
        if key not in required and key not in optional:
            errors.append(f"type {type_} に無いキー {key} がある")
            continue
        parsed, value_errors = _check_value(key, value)
        errors.extend(value_errors)
        result["fields"][key] = parsed
    for key in required:
        if key not in seen:
            errors.append(f"必須のキー {key} が無い")
    return result


def compose(type_, head, fields):
    """本文を作る。fields は (キー, 値) の配列で、値が None か空の配列のキーは書かない。配列の値はカンマで区切る。"""
    required, optional = FIELDS[type_]
    lines = [f"{PREFIX} {head}", f"type: {type_}"]
    values = dict(fields)
    for key in values:
        if key not in required and key not in optional:
            raise ValueError(f"type {type_} に無いキー {key}")
    for key in (*required, *optional):
        value = values.get(key)
        if value is None or value == [] or value == "":
            if key in required:
                raise ValueError(f"type {type_} の必須のキー {key} が無い")
            continue
        text = ",".join(value) if isinstance(value, (list, tuple)) else str(value)
        if "\n" in text or "\r" in text:
            raise ValueError(f"キー {key} の値が 1 行でない")
        lines.append(f"{key}: {text}")
    return "\n".join(lines) + "\n"


def _kinds_text(kinds):
    return "・".join(kinds)


def subscribe(repo, kinds, session_id, session_name, permission_mode):
    head = f"{repo} の {_kinds_text(kinds)} の登録を申し込みます。"
    return compose("subscribe", head, [("repo", repo), ("kinds", list(kinds)), ("session-id", session_id),
                                       ("session-name", session_name), ("permission-mode", permission_mode)])


def unsubscribe(subscription_ids, session_id, session_name):
    head = f"登録 {len(subscription_ids)} 件の削除を申し込みます。"
    return compose("unsubscribe", head, [("subscription-ids", list(subscription_ids)), ("session-id", session_id),
                                         ("session-name", session_name)])


def hold_warning(dispatcher_mode, subscriber_mode):
    """権限モードの分類が違えば、返事のキー warning の文。同じなら None (計画の R4)。"""
    if permission_class(dispatcher_mode) == permission_class(subscriber_mode):
        return None
    return (f"配信のセッション (権限モード {dispatcher_mode}) と受信のセッション (権限モード {subscriber_mode}) は、"
            "権限モードの分類が違います。配信のセッションから届くメッセージは受信のセッションで保留され、"
            "Claude Desktop では承認の画面を出せないので、5 分で捨てられます。")


def subscribed_accepted(repo, added, existing, warning=None):
    head = f"{repo} の登録を受け付けました (追加 {len(added)} 件・登録済み {len(existing)} 件)。"
    return compose("subscribed", head, [("result", "accepted"), ("repo", repo), ("added", list(added)),
                                        ("existing", list(existing)), ("warning", warning)])


def subscribed_rejected(reasons, repo=None):
    return compose("subscribed", "登録の申し込みを受け付けませんでした。",
                   [("result", "rejected"), ("repo", repo), ("reason", _reason_text(reasons))])


def _subscription_text(subscriptions):
    return [f"{s['repo']} {s['kind']}" for s in subscriptions]


def unsubscribed_accepted(removed):
    return compose("unsubscribed", f"登録 {len(removed)} 件を削除しました。",
                   [("result", "accepted"), ("removed", _subscription_text(removed))])


def unsubscribed_rejected(reasons):
    return compose("unsubscribed", "登録の削除の申し込みを受け付けませんでした。",
                   [("result", "rejected"), ("reason", _reason_text(reasons))])


def removed(subscriptions):
    head = f"配信のセッションで、このセッションの登録 {len(subscriptions)} 件が削除されました。"
    return compose("removed", head, [("removed", _subscription_text(subscriptions))])


def _reason_text(reasons):
    if not reasons:
        raise ValueError("受け付けなかった理由が無い")
    return "; ".join(r.replace("\r", " ").replace("\n", " ") for r in reasons)
