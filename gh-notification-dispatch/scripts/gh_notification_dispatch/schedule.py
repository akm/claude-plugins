"""定期の予定の記録と、期限の確認 (計画 docs/plans/2026-11-14-1428-feat-gh-notification-dispatch-plan.md の R16〜R18・KTD9)。

定期の予定そのもの (ツール CronCreate のジョブ) は Claude Code のセッションの中にあり、スクリプトからは作れず、読めない。
スキル dispatch が作り直した予定のジョブの ID と cron の式を、サブコマンド `schedule record` で記録のディレクトリの
state.json のキー `schedule` に書き、`schedule clear` で停止したことを書く。様式の SSOT は文書
`gh-notification-dispatch/references/records.md`。

期限は、記録した時刻の 7 日後にする (ツール CronCreate の定期の予定が、作ってから 7 日で消えるため)。期限切れは state.json に
書かず、tick・status・hook が、記録の期限と今の時刻を比べて判定する (KTD9)。期限を過ぎた後の tick が来ることに頼れないため。
"""

import datetime
import os
import re

from . import outbox, store

RUNNING = "running"
STOPPED = "stopped"
LIFETIME = datetime.timedelta(days=7)  # ツール CronCreate の定期の予定が消えるまでの期間
REMINDER_HOURS = (24, 6, 1)  # 期限までの残りがこれを切った回に、続けるかを確認する (R17)
TICK_PROMPT = "/gh-notification-dispatch:tick"
RENEW_COMMAND = "/gh-notification-dispatch:dispatch renew"
RESUME_COMMAND = "/gh-notification-dispatch:dispatch resume"
PID_ENV = "CLAUDE_PID"  # Claude Code が、Bash ツールのコマンドと hook に、自分のプロセス ID を設定する (公式の文書の環境変数)
START_COMMAND = "/gh-notification-dispatch:dispatch start"

_JOB_ID = re.compile(r"[^\s\x00-\x1f\x7f]+")  # 空白と制御文字を含まない 1 文字以上 (CronCreate の ID の形は決めつけない)
_CRON_FIELD = re.compile(r"[0-9A-Za-z*/,-]+")


def check_job_id(value):
    if not _JOB_ID.fullmatch(value or ""):
        return f"ジョブの ID {value!r} が、空か、空白か制御文字を含む"
    return None


def check_cron(value):
    fields = (value or "").split()
    if len(fields) != 5 or not all(_CRON_FIELD.fullmatch(f) for f in fields):
        return f"cron の式 {value!r} が、5 つの欄 (分・時・日・月・曜日) の形でない"
    return None


def current_pid():
    """スクリプトを実行している Claude Code のプロセス ID (環境変数 CLAUDE_PID)。無いか整数でなければ None。"""
    value = os.environ.get(PID_ENV, "").strip()
    return int(value) if value.isdigit() else None


def record(job_id, cron):
    """作り直した定期の予定を記録する。期限を 7 日後にし、出した確認の記録を消す (R17)。

    予定を作った Claude Code のプロセス ID も記録する。定期の予定はそのプロセスの中だけにあるので、後でプロセス ID が
    違えば、予定を作ったプロセスはもう無い (Claude Desktop を再起動した後など) と判定できる (計画の KTD10)。
    """
    pid = current_pid()
    errors = [e for e in (check_job_id(job_id), check_cron(cron)) if e]
    if pid is None:
        errors.append(f"環境変数 {PID_ENV} が無いので、定期の予定を作ったプロセスを記録できない")
    if errors:
        return {"status": "unsatisfied", "schedule": None, "previous": None, "not_dispatcher": False, "errors": errors}
    now = store.now()
    schedule = {"state": RUNNING, "job_id": job_id, "cron": cron, "pid": pid, "created_at": store.format_time(now),
                "expires_at": store.format_time(now + LIFETIME), "reminders": [], "stopped_at": None}
    return _write(schedule, "schedule record")


def clear():
    """定期の予定を停止したことを記録する。"""
    schedule = {"state": STOPPED, "job_id": None, "cron": None, "pid": None, "created_at": None, "expires_at": None,
                "reminders": [], "stopped_at": store.format_time(store.now())}
    return _write(schedule, "schedule clear")


def _write(schedule, action):
    try:
        with store.transaction() as tx:
            state = tx.read(store.STATE)
            previous = state.get("schedule")
            state["schedule"] = schedule
            tx.write(store.STATE, state)
            tx.append_log({"time": store.format_time(store.now()), "action": action, "job_id": schedule["job_id"],
                           "expires_at": schedule["expires_at"]})
    except store.NotDispatcher as e:
        return {"status": "unsatisfied", "schedule": None, "previous": None, "not_dispatcher": e.other_session,
                "errors": [str(e)]}
    return {"status": "ok", "schedule": schedule, "previous": previous, "not_dispatcher": False, "errors": []}


# --- 期限 ---------------------------------------------------------------------------------------------------------

def is_running(schedule):
    return bool(schedule) and schedule.get("state") == RUNNING


def is_expired(schedule, now):
    """動いている記録の期限を過ぎたか。動いていない記録 (停止した・記録が無い) は期限切れにしない。"""
    return is_running(schedule) and now >= store.parse_time(schedule["expires_at"])


def is_process_changed(schedule, now, pid):
    """動いている記録の期限内で、予定を記録したプロセス ID と pid が違うか。記録か pid が無ければ判定しない (偽)。"""
    if not is_running(schedule) or is_expired(schedule, now):
        return False
    recorded = schedule.get("pid")
    return recorded is not None and pid is not None and recorded != pid


def take_reminder(schedule, now):
    """期限までの残りが、まだ確認を出していない閾値 (24・6・1 時間) を切っていれば、その閾値の最も小さいものを返し、
    切った閾値をすべて出した確認として schedule に書く (呼び出し元が state.json に書く)。無ければ None。

    1 つの回で 2 つ以上の閾値を切ったとき (マシンのスリープの後など) も、確認は 1 回だけにする。
    """
    if not is_running(schedule) or is_expired(schedule, now):
        return None
    remaining = store.parse_time(schedule["expires_at"]) - now
    crossed = [h for h in REMINDER_HOURS if remaining < datetime.timedelta(hours=h)]
    new = [h for h in crossed if h not in schedule.get("reminders", [])]
    if not new:
        return None
    schedule["reminders"] = sorted(set(schedule.get("reminders", [])) | set(crossed), reverse=True)
    return min(new)


def remaining_text(delta):
    minutes = max(0, int(delta.total_seconds() // 60))
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    if days:
        return f"{days} 日 {hours} 時間"
    return f"{hours} 時間 {minutes} 分" if hours else f"{minutes} 分"


def local_text(text):
    """記録の時刻 (UTC) を、このマシンのタイムゾーンの時刻の文にする (利用者に示すため)。"""
    return store.parse_time(text).astimezone().strftime("%Y-%m-%d %H:%M %Z")


def reminder_notice(schedule, now, hours):
    remaining = store.parse_time(schedule["expires_at"]) - now
    return {"kind": "reminder", "hours": hours,
            "text": f"定期の予定の期限 ({local_text(schedule['expires_at'])}) まで残り {remaining_text(remaining)}。"
                    f"配信を続けるなら、{RENEW_COMMAND} で期限を 7 日後にする (期限までは、このまま配信を続ける)。"}


def expired_notice(schedule):
    return {"kind": "expired", "hours": None,
            "text": f"定期の予定は期限 ({local_text(schedule['expires_at'])}) を過ぎたので、これより後は実行されない。"
                    f"配信を続けるなら、配信のセッションで {RESUME_COMMAND} を実行して、定期の予定を作り直す。"}


# --- 状態の表示 -------------------------------------------------------------------------------------------------------

def status():
    """配信のセッション・定期の予定・届かない登録を返す (サブコマンド status)。記録を読むだけで、どのセッションでも実行できる。

    期限切れは、期限を過ぎた後の tick に頼らずに、記録の期限と今の時刻を比べて判定する (R17・KTD9)。
    """
    now = store.now()
    state = store.read(store.STATE) or {}
    recorded = store.dispatcher(state)
    current = store.current_session_id()
    schedule = state.get("schedule")
    subscriptions = (store.read(store.SUBSCRIPTIONS) or {}).get("subscriptions", [])
    pending = (store.read(store.OUTBOX) or {}).get("pending", [])
    expired = is_expired(schedule, now)
    running = is_running(schedule) and not expired
    is_dispatcher = bool(recorded) and current is not None and recorded.get("session_id") == current
    process_changed = is_dispatcher and is_process_changed(schedule, now, current_pid())
    unreachable = [{**outbox.summary(s), "consecutive_failures": outbox.failures(s)}
                   for s in subscriptions if outbox.is_unreachable(s)]
    expired_events = [{**outbox.summary(s), "expired_events": s["expired_events"], "last_expired_at": s.get("last_expired_at")}
                      for s in subscriptions if s.get("expired_events", 0) > 0]
    return {"status": "ok", "dispatcher": recorded,
            "is_dispatcher": is_dispatcher, "schedule": schedule, "expired": expired, "process_changed": process_changed,
            "remaining": remaining_text(store.parse_time(schedule["expires_at"]) - now) if running else None,
            "started_at": state.get("started_at"), "position": state.get("position"),
            "subscriptions": len(subscriptions), "waiting": len(pending), "unreachable": unreachable,
            "expired_events": expired_events, "notice": _status_notice(recorded, schedule, now, process_changed),
            "errors": []}


def _status_notice(recorded, schedule, now, process_changed):
    if not recorded:
        return f"配信のセッションが記録されていない。配信のセッションにするセッションで {START_COMMAND} を実行する。"
    if not schedule:
        return f"定期の予定は、まだ作っていない。配信のセッションで {START_COMMAND} を実行する。"
    if schedule.get("state") == STOPPED:
        return (f"定期の予定は {local_text(schedule['stopped_at'])} に停止した。配信を続けるなら、配信のセッションで "
                f"{RESUME_COMMAND} を実行する。")
    if is_expired(schedule, now):
        return expired_notice(schedule)["text"]
    if process_changed:
        return ("定期の予定を作ったプロセスと、いまの配信のセッションのプロセスが違う (Claude Desktop を再起動した後など)。"
                f"再起動の前の予定が実行されるかは分からないので、配信のセッションで {RESUME_COMMAND} を実行して、"
                "定期の予定を作り直す。")
    remaining = remaining_text(store.parse_time(schedule["expires_at"]) - now)
    return (f"定期の予定は動いている。期限は {local_text(schedule['expires_at'])} (残り {remaining})。"
            f"延長するなら、配信のセッションで {RENEW_COMMAND} を実行する。")
