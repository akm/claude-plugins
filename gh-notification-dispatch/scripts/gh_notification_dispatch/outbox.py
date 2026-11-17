"""送信待ち・メッセージの割り当て・ack・fail・settle (計画 docs/plans/2026-11-14-1428-feat-gh-notification-dispatch-plan.md の
R11・R13・R15・KTD6)。

ファイル `outbox.json`・`delivered.json` の様式の SSOT は文書 `gh-notification-dispatch/references/records.md`。

この中の `enqueue`・`expire`・`settle_round`・`allocate` は、読んだ記録を書き換えるだけで、ファイルには書かない
(呼び出し元が、ロックを取った間に書く)。`record` (ack と fail) と `settle` は、サブコマンドから呼ばれ、自分で書く。
"""

import datetime
import uuid

from . import messages, store

UNREACHABLE_AFTER = 3  # 続けて届かなかった回数がこれ以上の登録は、届かない登録 (R15)
EXPIRE_AFTER = datetime.timedelta(days=30)  # 送信待ちに入れてからこれを過ぎた出来事は消す (R15)
MAX_MESSAGES_PER_TICK = 10  # 1 回の取得で出力するメッセージの上限 (R13)


def empty_outbox():
    return {"version": store.VERSION, "pending": [], "round": None}


def empty_delivered():
    return {"version": store.VERSION, "events": []}


def load(tx):
    return tx.read(store.OUTBOX) or empty_outbox(), tx.read(store.DELIVERED) or empty_delivered()


def failures(subscription):
    return subscription.get("consecutive_failures", 0)


def is_unreachable(subscription):
    return failures(subscription) >= UNREACHABLE_AFTER


def summary(subscription):
    """登録を出力に示すときの形 (登録の ID・リポジトリ・種類・受信のセッションの ID と名前)。"""
    return {"subscription_id": subscription["id"], "repo": subscription["repo"], "kind": subscription["kind"],
            "session_id": subscription["session_id"], "session_name": subscription["session_name"]}


# --- 送信待ちに入れる ------------------------------------------------------------------------------------------------

def enqueue(outbox, delivered, subscriptions, events, now_text, enqueued=None):
    """判定した出来事を、(リポジトリ, 種類) が同じすべての登録の送信待ちに入れ、届けた出来事の記録に足す (KD4・R11)。

    (出来事, 登録) が届けた出来事の記録か送信待ちに既にあれば、入れない。重なった範囲で取り直した出来事と、`fail` の後の
    回で取得の範囲に入った出来事が、2 つ目の送信待ちにならないため (KTD6)。届かない登録にも入れる (R15)。
    返り値は、入れた (出来事, 登録) の数。enqueued が配列なら、1 つでも登録の送信待ちに入れた出来事を足す (追跡する PR を
    決めるため。R10)。
    """
    done = {(d["key"], d["subscription_id"]) for d in delivered["events"]}
    done |= {(p["event"]["key"], p["subscription_id"]) for p in outbox["pending"]}
    added = 0
    for event in events:
        for subscription in subscriptions:
            if subscription["kind"] != event["kind"] or subscription["repo"].lower() != event["repo"].lower():
                continue
            pair = (event["key"], subscription["id"])
            if pair in done:
                continue
            done.add(pair)
            outbox["pending"].append({"subscription_id": subscription["id"], "event": event, "enqueued_at": now_text,
                                      "outputs": 0})
            if enqueued is not None and (not enqueued or enqueued[-1] is not event):
                enqueued.append(event)
            delivered["events"].append({"key": event["key"], "subscription_id": subscription["id"], "time": event["time"],
                                        "recorded_at": now_text})
            added += 1
    return added


def prune_delivered(delivered, window_start):
    """出来事の時刻が取得の範囲の起点より前の記録を消す。そのような出来事は時刻で判定から除かれ、二度と送信待ちに入らない。

    送信待ちに入れた時刻で消すと、30 日より長く停止した後の再開で、重なった範囲の出来事を 2 回届けるため
    (計画のレビューで下限未満にした指摘の 12 回目 #2)。返り値は消した数。
    """
    before = len(delivered["events"])
    delivered["events"] = [d for d in delivered["events"] if d["time"] >= window_start]
    return before - len(delivered["events"])


def expire(outbox, subscriptions, now):
    """送信待ちに入れてから 30 日を過ぎた出来事を消し、登録ごとの累計と最後に消した時刻を記録する (R15)。

    返り値は、消した登録と件数の配列。
    """
    cutoff = now - EXPIRE_AFTER
    counts, keep = {}, []
    for item in outbox["pending"]:
        if store.parse_time(item["enqueued_at"]) < cutoff:
            counts[item["subscription_id"]] = counts.get(item["subscription_id"], 0) + 1
        else:
            keep.append(item)
    outbox["pending"] = keep
    now_text = store.format_time(now)
    result = []
    for subscription in subscriptions:
        count = counts.get(subscription["id"])
        if count:
            subscription["expired_events"] = subscription.get("expired_events", 0) + count
            subscription["last_expired_at"] = now_text
            result.append({**summary(subscription), "count": count})
    return result


# --- 集計 (settle) ---------------------------------------------------------------------------------------------------

def settle_round(outbox, subscriptions_data):
    """この回の対応を、登録ごとに集計して消す (R15・KTD6)。対応が無ければ None。

    登録ごとに、`fail` が 1 通でもあれば続けて届かなかった回数に 1 を足す。`fail` が無く `ack` が 1 通でもあれば 0 に
    戻す。`ack` も `fail` も記録されなかったメッセージだけの登録は変えない (届いたかどうかが分からないため)。
    出力した後に削除された登録は数えない。

    集計した回の ID を subscriptions_data の last_settled_round に書く。呼び出し元は、subscriptions.json を書いてから
    outbox.json を書く。間で中断しても、次に呼ばれたときに同じ回を 2 回数えない。
    """
    round_ = outbox.get("round")
    if not round_:
        return None
    outcome = {"round_id": round_["id"], "tick_at": round_["tick_at"], "results": [], "became_unreachable": [],
               "already_counted": subscriptions_data.get("last_settled_round") == round_["id"]}
    if not outcome["already_counted"]:
        by_subscription = {}
        for message in round_["messages"]:
            by_subscription.setdefault(message["subscription_id"], []).append(message["result"])
        subscriptions = {s["id"]: s for s in subscriptions_data["subscriptions"]}
        for subscription_id, results in by_subscription.items():
            subscription = subscriptions.get(subscription_id)
            if subscription is None:
                continue
            before = failures(subscription)
            if "fail" in results:
                subscription["consecutive_failures"], result = before + 1, "failed"
            elif "ack" in results:
                subscription["consecutive_failures"], result = 0, "delivered"
            else:
                result = "unrecorded"
            outcome["results"].append({**summary(subscription), "result": result,
                                       "consecutive_failures": failures(subscription)})
            if before < UNREACHABLE_AFTER <= failures(subscription):
                outcome["became_unreachable"].append(summary(subscription))
        subscriptions_data["last_settled_round"] = round_["id"]
    outbox["round"] = None
    return outcome


def forget_subscription(outbox, subscription_id, pending=True):
    """登録の round の対応を消す。pending が真なら送信待ちも消す (登録の削除のとき。R15)。"""
    if pending:
        outbox["pending"] = [p for p in outbox["pending"] if p["subscription_id"] != subscription_id]
    round_ = outbox.get("round")
    if round_:
        round_["messages"] = [m for m in round_["messages"] if m["subscription_id"] != subscription_id]


# --- 割り当て ---------------------------------------------------------------------------------------------------------

def _sort_key(subscription):
    return (subscription["created_at"], subscription["id"])


def allocate(outbox, subscriptions, last_allocated, now_text, limit=MAX_MESSAGES_PER_TICK):
    """送信待ちから、この回に出力するメッセージを作る (R13・KTD6)。返り値は (メッセージの配列, 次の last_allocated)。

    登録ごとに、前に出力した出来事 (送り直し) と初めて出力する出来事を分け、送り直しの出来事を先にして、それぞれを古い
    出来事から 20 件ずつ 1 通にまとめる。送り直しの回数 (resend) は 1 通に 1 つなので、1 通の出来事がすべて送り直しか、
    すべて初めてかのどちらかでなければ、受信のセッションは出来事ごとに区別できないため。上限 (limit) までの枠は、
    登録日時の順に登録を回して 1 通ずつ割り当て、枠が残る限り、この回に割り当てを始めた登録に戻って繰り返す。
    割り当てを始める登録は、前の回に最後に割り当てた登録 (last_allocated) の、登録日時の順で次の登録にする。届かない
    登録には割り当てない。出力したメッセージの対応は outbox の round に書く。メッセージが無ければ round は None のまま。
    """
    ordered = sorted((s for s in subscriptions if not is_unreachable(s)), key=_sort_key)
    if last_allocated:
        marker = (last_allocated["created_at"], last_allocated["subscription_id"])
        start = next((i for i, s in enumerate(ordered) if _sort_key(s) > marker), 0)
        ordered = ordered[start:] + ordered[:start]
    queues = {}
    size = messages.MAX_EVENTS_PER_MESSAGE
    for subscription in ordered:
        items = sorted((p for p in outbox["pending"] if p["subscription_id"] == subscription["id"]),
                       key=lambda p: (p["event"]["time"], p["enqueued_at"], p["event"]["key"]))
        queues[subscription["id"]] = []
        for group in ([p for p in items if p["outputs"] > 0], [p for p in items if p["outputs"] == 0]):
            queues[subscription["id"]] += [group[i:i + size] for i in range(0, len(group), size)]
    chosen = []
    while len(chosen) < limit and any(queues[s["id"]] for s in ordered):
        for subscription in ordered:
            if len(chosen) >= limit:
                break
            if queues[subscription["id"]]:
                chosen.append((subscription, queues[subscription["id"]].pop(0)))
    if not chosen:
        return [], last_allocated
    round_ = {"id": uuid.uuid4().hex[:12], "tick_at": now_text, "messages": []}
    output = []
    for subscription, items in chosen:
        resend = max(item["outputs"] for item in items)
        for item in items:
            item["outputs"] += 1
        message_id = uuid.uuid4().hex[:12]
        body = messages.notify(subscription["repo"], subscription["kind"], [item["event"] for item in items], resend)
        round_["messages"].append({"message_id": message_id, "subscription_id": subscription["id"],
                                   "event_keys": [item["event"]["key"] for item in items], "result": None, "reason": None})
        output.append({"message_id": message_id, **summary(subscription), "to": subscription["session_name"],
                       "to_session_id": subscription["session_id"], "count": len(items), "resend": resend, "body": body})
    outbox["round"] = round_
    last = chosen[-1][0]
    return output, {"subscription_id": last["id"], "created_at": last["created_at"]}


# --- サブコマンド ack・fail・settle ------------------------------------------------------------------------------------

def record(message_id, result, reason=None):
    """この回に出力したメッセージの結果を記録する。ack なら、そのメッセージの出来事を送信待ちから消す (KTD6)。

    この回 (settle していない最後の tick) に出力したメッセージの ID でないとき・既に記録したときは、何も変えずに
    unsatisfied を返す。前の回のメッセージの対応は、settle か次の tick が消しているため (計画のレビューで下限未満に
    した指摘の 12 回目 #4)。
    """
    payload = {"message_id": message_id, "result": None, "subscription_id": None, "removed_events": 0, "errors": []}
    try:
        with store.transaction() as tx:
            outbox, _ = load(tx)
            round_ = outbox.get("round")
            message = next((m for m in (round_ or {}).get("messages", []) if m["message_id"] == message_id), None)
            if message is None:
                return {"status": "unsatisfied", **payload,
                        "errors": [f"メッセージ {message_id} は、この回 (最後の tick) に出力したメッセージではない。"
                                   "前の回のメッセージの結果は記録できない"]}
            if message["result"] is not None:
                return {"status": "unsatisfied", **payload, "subscription_id": message["subscription_id"],
                        "errors": [f"メッセージ {message_id} の結果は、既に {message['result']} と記録した"]}
            message["result"], message["reason"] = result, reason
            removed = 0
            if result == "ack":
                keys = set(message["event_keys"])
                before = len(outbox["pending"])
                outbox["pending"] = [p for p in outbox["pending"]
                                     if not (p["subscription_id"] == message["subscription_id"] and p["event"]["key"] in keys)]
                removed = before - len(outbox["pending"])
            tx.write(store.OUTBOX, outbox)
            tx.append_log({"time": store.format_time(store.now()), "action": result, "message_id": message_id,
                           "subscription_id": message["subscription_id"], "reason": reason})
    except store.NotDispatcher as e:
        return {"status": "unsatisfied", **payload, "errors": [str(e)]}
    return {"status": "ok", **payload, "result": result, "subscription_id": message["subscription_id"],
            "removed_events": removed}


def settle():
    """この回の対応を集計して消す。対応が無ければ何もしない (settled は null)。"""
    try:
        with store.transaction() as tx:
            outbox, _ = load(tx)
            subscriptions_data = tx.read(store.SUBSCRIPTIONS) or {"version": store.VERSION, "subscriptions": []}
            outcome = settle_round(outbox, subscriptions_data)
            if outcome is not None:
                tx.write(store.SUBSCRIPTIONS, subscriptions_data)
                tx.write(store.OUTBOX, outbox)
                tx.append_log({"time": store.format_time(store.now()), "action": "settle", "round_id": outcome["round_id"],
                               "results": [{"subscription_id": r["subscription_id"], "result": r["result"]}
                                           for r in outcome["results"]]})
    except store.NotDispatcher as e:
        return {"status": "unsatisfied", "settled": None, "errors": [str(e)]}
    return {"status": "ok", "settled": outcome, "errors": []}
