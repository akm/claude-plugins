"""登録・一覧・番号での削除と、配信のセッションの記録 (計画 docs/plans/2026-11-14-1428-feat-gh-notification-dispatch-plan.md の
R1〜R7・R16・R19)。

関数は、CLI の入口 (ファイル `gh-notification-dispatch/scripts/gh_notification_dispatch.py`) が出力する JSON の辞書を返す。
辞書のキー `status` は、`ok` (終了コード 0)・`unsatisfied` (3)・`gh_failed` (4。キー `gh_error` に gh の結果) のどれか。

受信のセッションが実行する関数 (`request`・`list_subscriptions` の受信のセッションの一覧・`resolve`) は、記録のディレクトリに
書かない。配信のセッションが実行する関数の書き込みは、モジュール store の関数 transaction で行う (KTD3)。
"""

import os
import uuid

from . import gh, messages, store

LIST_HEADER = "| 番号 | リポジトリ | 種類 | 登録日時 | 届け先のセッション |"


def _load(tx=None):
    data = tx.read(store.SUBSCRIPTIONS) if tx is not None else store.read(store.SUBSCRIPTIONS)
    return data or {"version": store.VERSION, "subscriptions": []}


def _ordered(subscriptions):
    """登録日時の順。同じ時刻ならファイルの順。"""
    return [s for _, s in sorted(enumerate(subscriptions), key=lambda pair: (pair[1]["created_at"], pair[0]))]


def _new_id(existing):
    while True:
        value = uuid.uuid4().hex[:12]
        if value not in existing:
            return value


def _row(subscription, number=None):
    row = {key: subscription[key] for key in ("id", "repo", "kind", "session_id", "session_name", "permission_mode",
                                              "created_at")}
    if number is not None:
        row = {"number": number, **row}
    return row


def _display_time(text):
    return store.parse_time(text).astimezone().strftime("%Y-%m-%d %H:%M %z")


def _cell(text):
    return text.replace("|", "\\|")


def _table(rows):
    lines = [LIST_HEADER, "| --- | --- | --- | --- | --- |"]
    for r in rows:
        lines.append(f"| {r['number']} | {r['repo']} | {r['kind']} | {_display_time(r['created_at'])} | "
                     f"{_cell(r['session_name'])} |")
    return "\n".join(lines)


def _session_errors(session_id, label):
    if session_id is None:
        return [f"環境変数 {store.SESSION_ENV} が無いので、{label}のセッションの ID が分からない"]
    error = messages.check_session_id(session_id)
    return [f"{label}のセッションの ID: {error}"] if error else []


def _value_errors(*errors):
    return [e for e in errors if e]


# --- 配信のセッションの記録 -----------------------------------------------------------------------------------------

def set_dispatcher(name, permission_mode, switch=False):
    """state.json に配信のセッションを記録する。ID は環境変数 CLAUDE_CODE_HOST_SESSION_ID から読む (KTD3 の確認と同じ値)。

    記録と違うセッションなら、switch が真のときだけ書き換える (R16)。
    """
    session_id = store.current_session_id()
    errors = _session_errors(session_id, "配信") + _value_errors(messages.check_name(name),
                                                                  messages.check_permission_mode(permission_mode))
    if errors:
        return {"status": "unsatisfied", "dispatcher": None, "previous": None, "switched": False, "errors": errors}
    with store.transaction(setting_dispatcher=True) as tx:
        state = tx.read(store.STATE) or {"version": store.VERSION}
        recorded = state.get("dispatcher")
        other = bool(recorded) and recorded.get("session_id") != session_id
        if other and not switch:
            return {"status": "unsatisfied", "dispatcher": recorded, "previous": None, "switched": False,
                    "errors": [f"記録の配信のセッションは、別のセッション ({recorded.get('name')}、{recorded.get('session_id')}) "
                               "である。このセッションに切り替えるなら、--switch を付けて実行し直す"]}
        record = {"session_id": session_id, "name": name, "permission_mode": permission_mode,
                  "recorded_at": store.format_time(store.now())}
        state["dispatcher"] = record
        tx.write(store.STATE, state)
    return {"status": "ok", "dispatcher": record, "previous": recorded if other else None, "switched": other,
            "errors": []}


# --- 受信のセッション: 申し込みの本文 -------------------------------------------------------------------------------

def request(name, permission_mode, repo=None, kinds=None):
    """登録の申し込み (type: subscribe) の本文を作る。記録のディレクトリには書かない。

    repo を省くと、作業ディレクトリのリポジトリ (`gh repo view`) にする。kinds を省くと、2 つの種類にする (R2)。
    """
    session_id = store.current_session_id()
    errors = _session_errors(session_id, "受信") + _value_errors(messages.check_name(name),
                                                                  messages.check_permission_mode(permission_mode))
    if kinds is None:
        kinds = list(messages.KINDS)
    else:
        kinds, kind_errors = messages.parse_kinds(kinds)
        errors += kind_errors
    if repo is not None:
        errors += _value_errors(messages.check_repo(repo))
    payload = {"repo": repo, "kinds": kinds, "session_id": session_id, "dispatcher": None, "message_body": None,
               "errors": errors}
    if errors:
        return {"status": "unsatisfied", **payload}
    if repo is None:
        result = gh.run(["repo", "view", "--json", "nameWithOwner"], expect_json=True)
        if not gh.failed(result):
            value = result["json"].get("nameWithOwner") if isinstance(result["json"], dict) else None
            if not isinstance(value, str) or messages.check_repo(value):
                result = {**result, "json_error": f"応答に owner/repo の形の nameWithOwner が無い: {value!r}"}
        if gh.failed(result):
            return {"status": "gh_failed", "gh_error": result, **payload}
        repo = value
    payload.update(repo=repo, dispatcher=store.dispatcher(),
                   message_body=messages.subscribe(repo, kinds, session_id, name, permission_mode))
    return {"status": "ok", **payload}


# --- 配信のセッション: 登録 -----------------------------------------------------------------------------------------

def _parse_request(message_text, sender, type_):
    """申し込みの本文を解析し、送り手を確認する。返り値は (fields, 理由の配列)。"""
    sender_error = messages.check_session_id(sender)
    if sender_error:
        return None, [f"メッセージの送り手の ID: {sender_error}"]
    try:
        store.check_dispatcher(store.read(store.STATE))
    except store.NotDispatcher as e:
        return None, [str(e)]
    parsed = messages.parse(message_text)
    if parsed["errors"]:
        return parsed["fields"], parsed["errors"]
    if parsed["type"] != type_:
        return parsed["fields"], [f"type が {type_} でない ({parsed['type']})"]
    fields = parsed["fields"]
    if fields["session-id"] != sender:
        return fields, [f"本文の session-id ({fields['session-id']}) が、メッセージの送り手の ID ({sender}) と違う。"
                        "ほかのセッションの登録は申し込めない"]
    return fields, []


def add(message_text, sender):
    """登録の申し込み (type: subscribe) を記録し、返事 (type: subscribed) の本文を返す (R2〜R4)。

    sender は、受け取ったメッセージの属性の送り手の ID。本文の session-id と違えば受け付けない。
    """
    payload = {"result": "rejected", "repo": None, "added": [], "existing": [], "warning": None, "reply_body": None,
               "errors": []}

    def reject(reasons, repo=None):
        payload.update(repo=repo, errors=reasons, reply_body=messages.subscribed_rejected(reasons, repo=repo))
        return {"status": "unsatisfied", **payload}

    fields, errors = _parse_request(message_text, sender, "subscribe")
    repo = (fields or {}).get("repo")
    repo = repo if repo and not messages.check_repo(repo) else None
    if errors:
        return reject(errors, repo)
    result = gh.run(["api", f"repos/{repo}"], expect_json=True)
    if result["failure"] == "not_found":
        return reject([f"リポジトリ {repo} を gh で読めない (HTTP 404)。名前が誤っているか、読む権限が無い"], repo)
    full_name = result["json"].get("full_name") if isinstance(result["json"], dict) else None
    if not gh.failed(result) and (not isinstance(full_name, str) or messages.check_repo(full_name)):
        result = {**result, "json_error": f"応答に owner/repo の形の full_name が無い: {full_name!r}"}
    if gh.failed(result):
        reasons = [f"配信のセッションで gh が失敗したので、リポジトリ {repo} を読めるかを確認できなかった。"
                   "配信のセッションの利用者が gh を直した後に、申し込み直す"]
        payload.update(repo=repo, errors=reasons, reply_body=messages.subscribed_rejected(reasons, repo=repo))
        return {"status": "gh_failed", "gh_error": result, **payload}
    added, existing = [], []
    try:
        with store.transaction() as tx:
            data = _load(tx)
            subscriptions = data["subscriptions"]
            ids = {s["id"] for s in subscriptions}
            now = store.format_time(store.now())
            for kind in fields["kinds"]:
                match = next((s for s in subscriptions if s["repo"].lower() == full_name.lower() and s["kind"] == kind
                              and s["session_id"] == sender), None)
                if match is not None:
                    match.update(repo=full_name, session_name=fields["session-name"],
                                 permission_mode=fields["permission-mode"])
                    existing.append(match)
                    continue
                new = {"id": _new_id(ids), "repo": full_name, "kind": kind, "session_id": sender,
                       "session_name": fields["session-name"], "permission_mode": fields["permission-mode"],
                       "created_at": now}
                ids.add(new["id"])
                subscriptions.append(new)
                added.append(new)
            tx.write(store.SUBSCRIPTIONS, data)
            dispatcher_mode = store.dispatcher(tx.read(store.STATE))["permission_mode"]
    except store.NotDispatcher as e:
        return reject([str(e)], full_name)
    warning = messages.hold_warning(dispatcher_mode, fields["permission-mode"])
    payload.update(result="accepted", repo=full_name, added=[_row(s) for s in added],
                   existing=[_row(s) for s in existing], warning=warning,
                   reply_body=messages.subscribed_accepted(full_name, [s["kind"] for s in added],
                                                           [s["kind"] for s in existing], warning))
    return {"status": "ok", **payload}


# --- 一覧と番号 -----------------------------------------------------------------------------------------------------

def list_subscriptions(viewer, mine=False):
    """登録の一覧を、登録日時の順に 1 から番号を振って返し、番号と登録の ID の対応を記録する (R5・R6)。

    viewer が記録の配信のセッションなら、対応を記録のディレクトリの snapshots/ に書く。それ以外 (受信のセッション) なら、
    記録のディレクトリの外の一時ディレクトリに書き、記録のディレクトリは変えない。
    """
    payload = {"viewer": viewer, "mine": mine, "listed_at": None, "snapshot": None, "subscriptions": [], "table": None,
               "errors": []}
    error = messages.check_session_id(viewer)
    if error:
        return {"status": "unsatisfied", **payload, "errors": [f"--viewer: {error}"]}
    subscriptions = _ordered(_load()["subscriptions"])
    if mine:
        subscriptions = [s for s in subscriptions if s["session_id"] == viewer]
    listed_at = store.format_time(store.now())
    rows = [_row(s, number) for number, s in enumerate(subscriptions, start=1)]
    snapshot = {"version": store.VERSION, "viewer": viewer, "mine": mine, "listed_at": listed_at,
                "entries": [{"number": r["number"], "subscription_id": r["id"]} for r in rows]}
    recorded = store.dispatcher()
    try:
        if recorded and recorded.get("session_id") == viewer:
            name = store.dispatcher_snapshot_name(viewer)
            with store.transaction() as tx:
                tx.write(name, snapshot)
            path = os.path.join(store.home(), name)
        else:
            store.write_receiver_snapshot(viewer, snapshot)
            path = store.receiver_snapshot_path(viewer)
    except store.NotDispatcher as e:
        return {"status": "unsatisfied", **payload, "errors": [str(e)]}
    payload.update(listed_at=listed_at, snapshot=path, subscriptions=rows, table=_table(rows))
    return {"status": "ok", **payload}


def _targets(snapshot, numbers, subscriptions):
    """記録した対応で、番号を登録に変える。返り値は (登録の配列, 理由の配列)。"""
    if not snapshot:
        return [], ["このセッションで一覧を表示していない。一覧を表示してから番号を指定する"]
    by_number = {e["number"]: e["subscription_id"] for e in snapshot["entries"]}
    by_id = {s["id"]: s for s in subscriptions}
    targets, errors = [], []
    for number in dict.fromkeys(numbers):
        if number not in by_number:
            listed = f"1〜{len(by_number)}" if by_number else "登録が無い"
            errors.append(f"番号 {number} は、{snapshot['listed_at']} に表示した一覧に無い ({listed})")
        elif by_number[number] not in by_id:
            errors.append(f"番号 {number} の登録は既に無い。一覧の表示からやり直す")
        else:
            targets.append((number, by_id[by_number[number]]))
    return targets, errors


def remove(viewer, numbers):
    """配信のセッションで、一覧の番号の登録を削除する (R6)。1 つでも指定できない番号があれば、何も削除しない。

    削除した登録が別のセッションのものなら、そのセッションへ送る通知 (type: removed) の本文を返す。
    """
    payload = {"removed": [], "messages": [], "errors": []}
    error = messages.check_session_id(viewer)
    if error:
        return {"status": "unsatisfied", **payload, "errors": [f"--viewer: {error}"]}
    try:
        with store.transaction() as tx:
            data = _load(tx)
            targets, errors = _targets(tx.read(store.dispatcher_snapshot_name(viewer)), numbers, data["subscriptions"])
            if errors:
                return {"status": "unsatisfied", **payload, "errors": errors}
            ids = {s["id"] for _, s in targets}
            data["subscriptions"] = [s for s in data["subscriptions"] if s["id"] not in ids]
            tx.write(store.SUBSCRIPTIONS, data)
    except store.NotDispatcher as e:
        return {"status": "unsatisfied", **payload, "errors": [str(e)]}
    by_session = {}
    for _, s in targets:
        if s["session_id"] != viewer:
            by_session.setdefault(s["session_id"], []).append(s)
    notices = [{"to": group[-1]["session_name"], "to_session_id": session_id, "body": messages.removed(group)}
               for session_id, group in by_session.items()]
    payload.update(removed=[_row(s, number) for number, s in targets], messages=notices)
    return {"status": "ok", **payload}


def resolve(viewer, numbers, name):
    """受信のセッションで、自分の一覧の番号を登録の ID に変え、削除の申し込み (type: unsubscribe) の本文を作る。

    記録のディレクトリには書かない (R6・R19)。
    """
    payload = {"subscription_ids": [], "subscriptions": [], "dispatcher": None, "message_body": None, "errors": []}
    errors = _value_errors(messages.check_session_id(viewer), messages.check_name(name))
    if errors:
        return {"status": "unsatisfied", **payload, "errors": errors}
    targets, errors = _targets(store.read_receiver_snapshot(viewer), numbers, _load()["subscriptions"])
    errors += [f"番号 {number} の登録は、このセッションの登録ではない" for number, s in targets if s["session_id"] != viewer]
    if errors:
        return {"status": "unsatisfied", **payload, "errors": errors}
    ids = [s["id"] for _, s in targets]
    payload.update(subscription_ids=ids, subscriptions=[_row(s, number) for number, s in targets],
                   dispatcher=store.dispatcher(), message_body=messages.unsubscribe(ids, viewer, name))
    return {"status": "ok", **payload}


def unsubscribe(message_text, sender):
    """削除の申し込み (type: unsubscribe) の登録を削除し、返事 (type: unsubscribed) の本文を返す (R6)。

    1 つでも、既に無い登録か、送り手のセッションの登録でない ID があれば、何も削除しない。
    """
    payload = {"result": "rejected", "removed": [], "reply_body": None, "errors": []}

    def reject(reasons):
        payload.update(errors=reasons, reply_body=messages.unsubscribed_rejected(reasons))
        return {"status": "unsatisfied", **payload}

    fields, errors = _parse_request(message_text, sender, "unsubscribe")
    if errors:
        return reject(errors)
    try:
        with store.transaction() as tx:
            data = _load(tx)
            by_id = {s["id"]: s for s in data["subscriptions"]}
            targets, errors = [], []
            for subscription_id in fields["subscription-ids"]:
                s = by_id.get(subscription_id)
                if s is None:
                    errors.append(f"登録 {subscription_id} は既に無い。一覧の表示からやり直す")
                elif s["session_id"] != sender:
                    errors.append(f"登録 {subscription_id} は、送り手のセッションの登録ではない")
                else:
                    targets.append(s)
            if errors:
                return reject(errors)
            ids = {s["id"] for s in targets}
            data["subscriptions"] = [s for s in data["subscriptions"] if s["id"] not in ids]
            tx.write(store.SUBSCRIPTIONS, data)
    except store.NotDispatcher as e:
        return reject([str(e)])
    payload.update(result="accepted", removed=[_row(s) for s in targets],
                   reply_body=messages.unsubscribed_accepted(targets))
    return {"status": "ok", **payload}
