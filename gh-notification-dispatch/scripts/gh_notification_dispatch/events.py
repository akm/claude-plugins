"""通知から出来事の種類を判定する (計画 docs/plans/2026-11-14-1428-feat-gh-notification-dispatch-plan.md の R9・KTD4)。

`review_requested` (自分か、自分の所属するチームへの PR のレビューの依頼) は、通知の理由 (`reason`) ではなく、PR の
timeline の出来事 `review_requested` で判定する。レビューの依頼の通知は、依頼の後に push やメンションがあるたびに
更新され、理由は `review_requested` のままなので、通知の更新だけでは新しい依頼か分からないため。

`merged` (PR のマージ) は、レビューの依頼を届けた PR (追跡する PR) と、自分か自分のチームへの依頼が残っているか自分の
レビューがある PR のものだけを届ける (R10・KD3)。マージされた PR の通知の理由は `subscribed` か `author` で、理由では
判定できないため、PR の状態とレビュアで判定する。

依頼先のチームは、チームの ID で照合する。名前や slug で照合すると、別の Organization の同じ名前のチームへの依頼を
届けてしまうため (計画のレビューで下限未満にした指摘の 8 回目 #8)。

時刻は UTC の `YYYY-MM-DDTHH:MM:SSZ` の文字列のまま比べる (GitHub の API と記録が同じ形なので、文字列の順が時刻の順になる)。
"""

import re

from . import gh

_PULL_URL_RE = re.compile(r"/repos/[^/]+/[^/]+/pulls/(\d+)$")
TIMELINE_PER_PAGE = 100
REVIEWS_PER_PAGE = 100


def pull_number(notification):
    """通知の対象が PR なら番号、そうでなければ None。"""
    subject = notification.get("subject") or {}
    if subject.get("type") != "PullRequest":
        return None
    match = _PULL_URL_RE.search(subject.get("url") or "")
    return int(match.group(1)) if match else None


def team_names(viewer):
    """所属するチームの ID と、表示する名前 (`<Organization>/<slug>`) の対応。"""
    return {team["id"]: f"{team['organization']}/{team['slug']}" for team in viewer["teams"]}


def review_requests(notifications, repos, viewer, since):
    """通知から、取得の範囲の起点 (since) より後の、自分か自分のチームへのレビューの依頼を集める。

    repos は、`review_requested` の登録があるリポジトリの名前 (小文字) の集合。登録の無いリポジトリの通知では、
    timeline を読まない (KTD4)。viewer は {login, teams}。
    返り値は (出来事の配列, 失敗)。失敗は、`gh` が失敗した呼び出し {api, repo, number, result}。失敗したら出来事は None。
    出来事は {kind, key, repo, number, title, url, time, requested}。key は `review_requested:<timeline の出来事の ID>`。
    """
    login = viewer["login"].lower()
    teams = team_names(viewer)
    events, seen = [], set()
    for notification in notifications:
        number = pull_number(notification)
        if number is None or not notification.get("updated_at") or notification["updated_at"] <= since:
            continue
        repo = (notification.get("repository") or {}).get("full_name") or ""
        if repo.lower() not in repos:
            continue
        items, _, failure = gh.get_all(f"repos/{repo}/issues/{number}/timeline?per_page={TIMELINE_PER_PAGE}")
        if failure is not None:
            return None, {"api": "timeline", "repo": repo, "number": number, "result": failure}
        for item in items:
            if item.get("event") != "review_requested" or not item.get("created_at") or item["created_at"] <= since:
                continue
            reviewer = item.get("requested_reviewer") or {}
            team = item.get("requested_team") or {}
            if (reviewer.get("login") or "").lower() == login:
                requested = viewer["login"]
            elif team.get("id") in teams:
                requested = teams[team["id"]]
            else:
                continue
            key = f"review_requested:{item['id']}"
            if key in seen:
                continue
            seen.add(key)
            events.append({"kind": "review_requested", "key": key, "repo": repo, "number": number,
                           "title": (notification.get("subject") or {}).get("title") or "",
                           "url": f"https://github.com/{repo}/pull/{number}", "time": item["created_at"],
                           "requested": requested})
    return events, None


def merged_event(repo, pull):
    """マージの出来事。キーは `merged:<リポジトリ (小文字)>#<番号>` で、同じ PR のマージは 1 つの出来事になる (R11)。"""
    number = pull["number"]
    return {"kind": "merged", "key": f"merged:{repo.lower()}#{number}", "repo": repo, "number": number,
            "title": pull.get("title") or "", "url": pull.get("html_url") or f"https://github.com/{repo}/pull/{number}",
            "time": pull["merged_at"]}


def merges(tracked_prs, notifications, repos, viewer, since):
    """マージを判定する (R10・KTD4)。返り値は (出来事の配列, 追跡をやめる PR の (リポジトリ, 番号) の集合, 失敗)。

    (a) 追跡する PR (tracked_prs) は、通知が来なくても毎回状態を読む。マージされていれば届け、マージされずに閉じて
    いれば届けない。どちらも追跡をやめる。
    (b) 通知 (notifications) の対象が PR で、通知の更新時刻が取得の範囲の起点 (since) より後のものは、repos (`merged`
    の登録があるリポジトリの名前 (小文字) の集合) のリポジトリについてだけ、マージの時刻が since より後なら、自分か
    自分のチームへの依頼が残っているか、自分のレビューがあるときに届ける。notifications が None (304) なら判定しない。

    同じ PR は 1 回だけ読み、同じマージは 1 つの出来事にする (R11)。失敗は、`gh` が失敗した呼び出し
    {api, repo, number, result}。失敗したら、出来事と追跡をやめる PR は None。
    """
    login = viewer["login"].lower()
    teams = team_names(viewer)
    pulls, found, stopped = {}, {}, set()

    def read(repo, number):
        key = (repo.lower(), number)
        if key not in pulls:
            result = gh.get(f"repos/{repo}/pulls/{number}")
            if gh.failed(result):
                return None, {"api": "pull", "repo": repo, "number": number, "result": result}
            pulls[key] = result["json"]
        return pulls[key], None

    for pr in tracked_prs:
        pull, failure = read(pr["repo"], pr["number"])
        if failure is not None:
            return None, None, failure
        if pull.get("merged_at"):
            event = merged_event(pr["repo"], pull)
            found.setdefault(event["key"], event)
            stopped.add((pr["repo"], pr["number"]))
        elif pull.get("state") == "closed":
            stopped.add((pr["repo"], pr["number"]))

    for notification in notifications or []:
        number = pull_number(notification)
        if number is None or not notification.get("updated_at") or notification["updated_at"] <= since:
            continue
        repo = (notification.get("repository") or {}).get("full_name") or ""
        if repo.lower() not in repos or f"merged:{repo.lower()}#{number}" in found:
            continue
        pull, failure = read(repo, number)
        if failure is not None:
            return None, None, failure
        if not pull.get("merged_at") or pull["merged_at"] <= since:
            continue
        involved, failure = _involved(repo, number, pull, login, teams)
        if failure is not None:
            return None, None, failure
        if involved:
            event = merged_event(repo, pull)
            found[event["key"]] = event
    return list(found.values()), stopped, None


def _involved(repo, number, pull, login, teams):
    """マージの時点で、自分か自分のチームへの依頼が残っているか、自分のレビューがあるか (R10 の (b))。

    返り値は (真偽, 失敗)。依頼が残っていれば、レビューの一覧は読まない。
    """
    if any((r.get("login") or "").lower() == login for r in pull.get("requested_reviewers") or []):
        return True, None
    if any(t.get("id") in teams for t in pull.get("requested_teams") or []):
        return True, None
    items, _, failure = gh.get_all(f"repos/{repo}/pulls/{number}/reviews?per_page={REVIEWS_PER_PAGE}")
    if failure is not None:
        return False, {"api": "reviews", "repo": repo, "number": number, "result": failure}
    return any(((r.get("user") or {}).get("login") or "").lower() == login for r in items), None
