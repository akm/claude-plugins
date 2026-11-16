"""通知の取得と取得の位置と、1 回の取得 (サブコマンド tick) の流れ (計画 docs/plans/2026-11-14-1428-feat-gh-notification-dispatch-plan.md
の R8・R11〜R15・KTD4〜KTD6)。

1 回の取得は、次の順に行う。すべて、記録のディレクトリのロックを取った間に行う。

1. 前の回の対応が残っていれば (settle が呼ばれないまま中断した回)、集計して消す (KTD6)。
2. 取得の範囲の起点を決める。`position` の 5 分前と `started_at` の遅いほう。記録が無い最初の回は、今の時刻を
   `started_at` と `position` にする (R8)。
3. 自分のログイン名と所属するチームを、取得してから 1 日を過ぎていれば取得し直す (KTD4)。
4. 通知の一覧を、引数 `all=true` と `since` を付け、ヘッダ `If-None-Match` に前回の `ETag` を付けて読む。304 なら判定しない (KTD5)。
5. レビューの依頼を判定し、送信待ちに入れる。30 日を過ぎた送信待ちを消す。この回に出力するメッセージを割り当てる。
6. `gh` が 1 度も失敗しなければ、`position` を今の時刻に、`etag` をこの回の応答の値にする。失敗したら、1 の集計の
   ほかは何も書かずに、失敗した呼び出しを返す (KTD5・KTD11)。

PR ごとの失敗 (読めなくなったリポジトリの 404 など) を自動で判定から除く規則は置かない (KTD11)。404 は続く失敗で、
除くと、SAML の承認切れのように利用者が直すべき失敗も、利用者に知らせずに配信から外れるため。利用者は、出力の
`failed_call` のリポジトリの登録を削除するか、gh の認証を直す。
"""

import datetime

from . import events as events_module
from . import gh, outbox, store

WINDOW_MARGIN = datetime.timedelta(minutes=5)  # 取得の範囲の起点を取得の位置より前にする幅 (KTD5)
VIEWER_REFRESH = datetime.timedelta(days=1)  # 自分のログイン名と所属するチームを取得し直す間隔 (KTD4)
NOTIFICATIONS_PER_PAGE = 50  # API GET /notifications の 1 ページの上限 (U1)
TEAMS_PER_PAGE = 100


def window_start(state):
    """取得の範囲の起点。`position` の 5 分前と `started_at` の遅いほう (R8・KTD5)。"""
    start = store.parse_time(state["position"]) - WINDOW_MARGIN
    return store.format_time(max(start, store.parse_time(state["started_at"])))


def _viewer_is_stale(viewer, now):
    return not viewer or now - store.parse_time(viewer["fetched_at"]) >= VIEWER_REFRESH


def fetch_viewer(now):
    """自分のログイン名と所属するチームを取得する。返り値は (viewer, 失敗した呼び出し)。"""
    login, failure = gh.viewer_login()
    if failure is not None:
        return None, {"api": "user", "repo": None, "number": None, "result": failure}
    items, _, failure = gh.get_all(f"user/teams?per_page={TEAMS_PER_PAGE}")
    if failure is not None:
        return None, {"api": "user/teams", "repo": None, "number": None, "result": failure}
    teams = [{"id": t["id"], "slug": t["slug"], "organization": (t.get("organization") or {}).get("login")} for t in items]
    return {"login": login, "teams": teams, "fetched_at": store.format_time(now)}, None


def fetch_notifications(since, etag):
    """通知の一覧を読む。返り値は (通知の配列。304 なら None, 1 ページ目の結果, 失敗した呼び出し)。"""
    endpoint = f"notifications?all=true&per_page={NOTIFICATIONS_PER_PAGE}&since={since}"
    items, first, failure = gh.get_all(endpoint, headers={"If-None-Match": etag} if etag else None)
    if failure is not None:
        return None, first, {"api": "notifications", "repo": None, "number": None, "result": failure}
    return items, first, None


def _summary_text(payload):
    parts = []
    if payload["not_modified"]:
        parts.append("通知は前の回から変わっていない (304)")
    else:
        parts.append(f"新しい出来事 {payload['found']} 件を送信待ちに入れた")
    parts.append(f"メッセージ {len(payload['messages'])} 通を出力した" if payload["messages"] else "送るメッセージは無い")
    if payload["waiting"]:
        parts.append(f"送信待ちに {payload['waiting']} 件が残る")
    return "。".join(parts) + "。"


def tick():
    """1 回の取得を行い、この回に送るメッセージを返す。"""
    now = store.now()
    now_text = store.format_time(now)
    payload = {"tick_at": now_text, "window_start": None, "position": None, "not_modified": False, "found": 0,
               "messages": [], "waiting": 0, "expired": [], "previous_round": None, "became_unreachable": [],
               "failed_call": None, "summary": None, "errors": []}
    try:
        with store.transaction() as tx:
            state = tx.read(store.STATE)
            subscriptions_data = tx.read(store.SUBSCRIPTIONS) or {"version": store.VERSION, "subscriptions": []}
            box, delivered = outbox.load(tx)

            previous = outbox.settle_round(box, subscriptions_data)
            if previous is not None:
                tx.write(store.SUBSCRIPTIONS, subscriptions_data)
                tx.write(store.OUTBOX, box)
                payload["previous_round"] = previous
                payload["became_unreachable"] = previous["became_unreachable"]

            if not state.get("started_at"):
                # 最初の回は、今の時刻を開始した時刻と取得の位置にする (R8)。この回の gh が失敗しても、開始した時刻は残す
                state["started_at"] = now_text
                state["position"] = now_text
                tx.write(store.STATE, state)
            since = window_start(state)
            payload["window_start"] = since

            viewer = state.get("viewer")
            if _viewer_is_stale(viewer, now):
                viewer, failure = fetch_viewer(now)
                if failure is not None:
                    return _failed(tx, payload, failure)
            subscriptions = subscriptions_data["subscriptions"]
            repos = {s["repo"].lower() for s in subscriptions if s["kind"] == "review_requested"}
            items, first, failure = fetch_notifications(since, state.get("etag"))
            if failure is not None:
                return _failed(tx, payload, failure)
            payload["not_modified"] = items is None
            found = []
            if items is not None and repos:
                found, failure = events_module.review_requests(items, repos, viewer, since)
                if failure is not None:
                    return _failed(tx, payload, failure)

            payload["found"] = outbox.enqueue(box, delivered, subscriptions, found, now_text)
            outbox.prune_delivered(delivered, since)
            payload["expired"] = outbox.expire(box, subscriptions, now)
            payload["messages"], last_allocated = outbox.allocate(box, subscriptions, state.get("last_allocated"), now_text)
            output_keys = {(m["subscription_id"], k) for m in (box["round"] or {}).get("messages", []) for k in m["event_keys"]}
            payload["waiting"] = sum(1 for p in box["pending"] if (p["subscription_id"], p["event"]["key"]) not in output_keys)

            state["position"] = now_text
            if items is not None:
                state["etag"] = first["headers"].get("etag")
            state["viewer"] = viewer
            state["last_allocated"] = last_allocated
            tx.write(store.OUTBOX, box)
            tx.write(store.DELIVERED, delivered)
            tx.write(store.SUBSCRIPTIONS, subscriptions_data)
            tx.write(store.STATE, state)
            payload["position"] = now_text
            payload["summary"] = _summary_text(payload)
            tx.append_log({"time": now_text, "action": "tick", "window_start": since, "not_modified": payload["not_modified"],
                           "found": payload["found"], "messages": len(payload["messages"]), "waiting": payload["waiting"],
                           "expired": sum(e["count"] for e in payload["expired"])})
    except store.NotDispatcher as e:
        return {"status": "unsatisfied", **payload, "errors": [str(e)]}
    return {"status": "ok", **payload}


def _failed(tx, payload, failure):
    """gh が失敗した回。取得の位置も前回の ETag も変えずに、失敗した呼び出しを返す (KTD5・KTD11)。"""
    payload["failed_call"] = {"api": failure["api"], "repo": failure["repo"], "number": failure["number"]}
    tx.append_log({"time": payload["tick_at"], "action": "tick", "window_start": payload["window_start"],
                   "failed_call": payload["failed_call"], "failure": failure["result"]["failure"]})
    return {"status": "gh_failed", **payload, "gh_error": failure["result"],
            "summary": f"gh が失敗した ({failure['api']})。取得の位置は変えていない。"}
