"""追跡する PR (計画 docs/plans/2026-11-14-1428-feat-gh-notification-dispatch-plan.md の R10・KTD4)。

レビューの依頼を送信待ちに入れた PR を追跡し、毎回の tick で状態を読んで、通知が来なくても (自分でマージした場合など)
マージを届ける (R10 の (a))。ファイル `tracked.json` の様式の SSOT は文書 `gh-notification-dispatch/references/records.md`。

ここの関数は、読んだ記録を書き換えるだけで、ファイルには書かない (呼び出し元が、ロックを取った間に書く)。
"""

import datetime

from . import store

TRACK_FOR = datetime.timedelta(days=30)  # 最後に依頼を送信待ちに入れてから、これを過ぎた PR は追跡をやめる (R10)


def empty():
    return {"version": store.VERSION, "prs": []}


def load(tx):
    return tx.read(store.TRACKED) or empty()


def merged_repos(subscriptions):
    """`merged` の登録があるリポジトリの名前 (小文字) の集合。"""
    return {s["repo"].lower() for s in subscriptions if s["kind"] == "merged"}


def _key(repo, number):
    return repo.lower(), number


def track(tracked, events, subscriptions, now_text):
    """送信待ちに入れたレビューの依頼の PR を追跡に足す (R10)。返り値は、足した PR の数。

    既に追跡していれば、最後に依頼を送信待ちに入れた時刻 (追跡する期間の起点) を now_text にする。依頼のやり直しで
    起点が変わるため。そのリポジトリに `merged` の登録が無ければ足さない。状態を読んでも、届ける先が無いため。
    """
    repos = merged_repos(subscriptions)
    by_key = {_key(p["repo"], p["number"]): p for p in tracked["prs"]}
    added = 0
    for event in events:
        if event["kind"] != "review_requested" or event["repo"].lower() not in repos:
            continue
        key = _key(event["repo"], event["number"])
        if key in by_key:
            by_key[key]["enqueued_at"] = now_text
            continue
        pr = {"repo": event["repo"], "number": event["number"], "enqueued_at": now_text}
        tracked["prs"].append(pr)
        by_key[key] = pr
        added += 1
    return added


def prune(tracked, subscriptions, now):
    """状態を読まずに追跡から外す PR を外す (R10・KTD4)。返り値は、外した PR の配列。

    外すのは、そのリポジトリに `merged` の登録が無くなった PR と、最後に依頼を送信待ちに入れてから 30 日を過ぎた PR。
    状態を読まないまま追跡に残すと、後で届ける古いマージと、増え続ける API の呼び出しが生じるため。
    """
    repos = merged_repos(subscriptions)
    cutoff = now - TRACK_FOR
    keep, removed = [], []
    for pr in tracked["prs"]:
        alive = pr["repo"].lower() in repos and store.parse_time(pr["enqueued_at"]) >= cutoff
        (keep if alive else removed).append(pr)
    tracked["prs"] = keep
    return removed


def stop(tracked, keys):
    """マージされたか閉じた PR を、追跡から外す。keys は (リポジトリ, 番号) の集合。"""
    stopped = {_key(repo, number) for repo, number in keys}
    tracked["prs"] = [p for p in tracked["prs"] if _key(p["repo"], p["number"]) not in stopped]
