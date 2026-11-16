"""通知から出来事の種類を判定する (計画 docs/plans/2026-11-14-1428-feat-gh-notification-dispatch-plan.md の R9・KTD4)。

U3 では `review_requested` (自分か、自分の所属するチームへの PR のレビューの依頼) を判定する。種類は、通知の理由
(`reason`) ではなく、PR の timeline の出来事 `review_requested` で判定する。レビューの依頼の通知は、依頼の後に push や
メンションがあるたびに更新され、理由は `review_requested` のままなので、通知の更新だけでは新しい依頼か分からないため。

依頼先のチームは、チームの ID で照合する。名前や slug で照合すると、別の Organization の同じ名前のチームへの依頼を
届けてしまうため (計画のレビューで下限未満にした指摘の 8 回目 #8)。

時刻は UTC の `YYYY-MM-DDTHH:MM:SSZ` の文字列のまま比べる (GitHub の API と記録が同じ形なので、文字列の順が時刻の順になる)。
"""

import re

from . import gh

_PULL_URL_RE = re.compile(r"/repos/[^/]+/[^/]+/pulls/(\d+)$")
TIMELINE_PER_PAGE = 100


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
