"""hook SessionStart (計画 docs/plans/2026-11-14-1428-feat-gh-notification-dispatch-plan.md の R17・R18・KTD10)。

ファイル `gh-notification-dispatch/hooks/hooks.json` が、起動 (`startup`) と会話の再開 (`resume`) のときに、サブコマンド
`hook session-start` として実行する。起動したセッションが記録の配信のセッションで、記録の定期の予定が動いているときだけ、
スキル dispatch の resume で定期の予定を作り直すよう、`additionalContext` で伝える。Claude Desktop を再起動した後は、
定期の予定が実行されないか、再起動の前の予定が残っていることがあるため (計画の U1)。予定の有無はスクリプトから読めないので、
伝えるのは作り直すことだけにする。記録の期限を過ぎていれば、期限切れであることも伝える (KTD9)。

会話の要約 (`compact`) と `/clear` のときは、同じプロセスに定期の予定が残っているので、何も出力しない。記録のディレクトリは
読むだけで、書かない (受信のセッションを含む、すべてのセッションで実行されるため)。
"""

import json

from . import schedule as schedule_module
from . import store

SOURCES = ("startup", "resume")


def session_start(input_text):
    """hook の入力の JSON を受け、出力する JSON を返す。何も出力しないときは None。"""
    data = json.loads(input_text)
    if data.get("source") not in SOURCES:
        return None
    state = store.read(store.STATE)
    recorded = store.dispatcher(state)
    current = store.current_session_id()
    if not recorded or current is None or recorded.get("session_id") != current:
        return None
    schedule = state.get("schedule")
    if not schedule_module.is_running(schedule):
        return None
    text = ("このセッションは gh-notification-dispatch の配信のセッション (定期の予定でスキル tick を実行し、GitHub の通知を"
            "受信のセッションへ届ける) で、記録では定期の予定が動いている。Claude Desktop を再起動した後は、定期の予定が"
            "実行されないか、再起動の前の予定が残っていることがある。利用者に、"
            f"{schedule_module.RESUME_COMMAND} を実行して定期の予定を作り直すよう伝える (resume は、残った予定を消してから"
            "作り直す)。")
    if schedule_module.is_expired(schedule, store.now()):
        text += f"また、記録の定期の予定は期限 ({schedule_module.local_text(schedule['expires_at'])}) を過ぎている。"
    return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}
