"""待機 (ポーリング)。管理のセッションの `wait` (スナップショットとの差分で終わる) と、作業のセッションの `wait-assignment`・`wait-decision`
(項目の状態 (itemstate) で終わる) を、バックグラウンドのプロセスとして動かす (計画の KTD6)。終わる条件・終了コード・標準出力・`wait.pid` の
様式の正本は issue-dispatch/skills/issue-dispatch/references/observation.md の「待機」。

- 起動時に前の待機を止め (PID の再利用を確かめてから)、`wait.pid` に自分の PID・開始時刻・所有者を書き、標準出力の最初の行に `pid <PID>` を書く。
- 読んだ時点の状態で判定する (起動の前から成り立っていれば最初の読み取りで終わる)。
- SIGTERM を受けると `stopped <PID>` を書いて終了コード 6 で終わる。終わるときは `wait.pid` の PID が自分のときだけ消す。
- スナップショットは読むだけで書かない (書くのは管理のセッションのターン。KTD5)。
"""

import datetime
import json
import os
import signal
import subprocess
import sys
import tempfile
import time

from issue_dispatch import comments, gh, ids, issues, itemstate, observe, project

PID_FILE = "wait.pid"
WAIT_NAMES = ("wait", "wait-assignment", "wait-decision")
# 終了コード (KTD6)
EXIT_CHANGED, EXIT_RATE_LIMIT, EXIT_NETWORK, EXIT_NO_SNAPSHOT, EXIT_STOPPED, EXIT_AUTH, EXIT_TIMEOUT = 0, 3, 4, 5, 6, 8, 124
NETWORK_FAILURE_LIMIT = 3   # ネットワークの失敗がこの回数続けば 4
SLICE_SECONDS = 5.0         # 期限と停止の印を見る間隔
# 終わりの行の先頭の語 (スキルはこの語で分ける)
RESULT_WORDS = ("diff", "assignment", "resumed", "stop", "request", "go", "wait", "stopped")
_NETWORK_LIKE = ("network", "timeout", "other", "missing")


# --- wait.pid -----------------------------------------------------------------------

def process_start(pid):
    """プロセスの開始時刻 (`ps -o lstart=` の文字列のまま)。無ければ None。"""
    try:
        r = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    text = r.stdout.strip()
    return text or None


def process_command(pid):
    try:
        r = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() or None


def read_pid_file(path):
    """`wait.pid` を読む。無い・読めなければ None。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("pid"), int):
        return None
    return data


def write_pid_file(path, owner, name):
    """自分の PID・開始時刻・所有者のセッション ID・待機の名前を一時名に書いてから改名する。"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    entry = {"pid": os.getpid(), "started_at": process_start(os.getpid()), "owner": owner, "wait": name, "written_at": _now()}
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", prefix=".wait-", suffix=".pid.tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False)
    os.replace(tmp, path)
    return entry


def is_our_wait(entry):
    """`wait.pid` の PID が、書かれた開始時刻と同じ開始時刻で動いていて、コマンドがこの CLI の待機なら真 (PID の再利用を見分ける)。"""
    pid = entry["pid"]
    start = process_start(pid)
    if start is None or start != entry.get("started_at"):
        return False
    command = process_command(pid) or ""
    return "issue_dispatch.py" in command and (entry.get("wait") in WAIT_NAMES) and entry["wait"] in command


def stop_previous(path, grace_seconds=10.0):
    """前の待機を止める。`wait.pid` の PID がこの CLI の待機なら SIGTERM を送って終わるのを待ち、そうでなければ止めずに `wait.pid` だけ消す。
    返り値: {"stopped": PID} / {"removed": PID} (再利用されていた) / {"none": True}。"""
    entry = read_pid_file(path)
    if entry is None:
        return {"none": True}
    if not is_our_wait(entry):
        try:
            os.unlink(path)
        except OSError:
            pass
        return {"removed": entry["pid"]}
    try:
        os.kill(entry["pid"], signal.SIGTERM)
    except OSError:
        return {"removed": entry["pid"]}
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline and process_start(entry["pid"]) is not None:
        time.sleep(0.1)
    try:
        if read_pid_file(path) and read_pid_file(path)["pid"] == entry["pid"]:
            os.unlink(path)
    except OSError:
        pass
    return {"stopped": entry["pid"]}


def remove_pid_if_mine(path):
    entry = read_pid_file(path)
    if entry and entry["pid"] == os.getpid():
        try:
            os.unlink(path)
        except OSError:
            pass


def _now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# --- 待機の共通の処理 ---------------------------------------------------------------

class Waiter:
    """期限・間隔・停止 (SIGTERM)・gh の失敗の扱いをまとめた待機。poll() は None (続ける) か (終了コード, 終わりの行) か
    ("failure", 失敗の種類) を返す。"""

    def __init__(self, pid_path, owner, name, minutes, interval_minutes, out=None):
        self.pid_path, self.owner, self.name = pid_path, owner, name
        self.deadline = time.monotonic() + minutes * 60
        self.interval = interval_minutes * 60
        self.out = out or sys.stdout
        self.stopped = False
        self.network_failures = 0

    def _on_term(self, signum, frame):
        self.stopped = True

    def start(self):
        stop_previous(self.pid_path)
        write_pid_file(self.pid_path, self.owner, self.name)
        signal.signal(signal.SIGTERM, self._on_term)
        self._emit(f"pid {os.getpid()}")

    def _emit(self, line):
        self.out.write(line + "\n")
        self.out.flush()

    def _finish(self, code, line=None):
        if line:
            self._emit(line)
        remove_pid_if_mine(self.pid_path)
        return code

    def _sleep(self, seconds):
        """停止と期限を見ながら眠る。返り値は、停止したら "stopped"、期限なら "deadline"、眠り終えたら None。"""
        end = time.monotonic() + seconds
        while True:
            if self.stopped:
                return "stopped"
            now = time.monotonic()
            if now >= end:
                return None
            if now >= self.deadline:
                return "deadline"
            time.sleep(min(SLICE_SECONDS, end - now, 0.05 if seconds < 1 else SLICE_SECONDS))

    def _failure(self, kind):
        """gh の失敗の扱い (KTD6)。返り値は終了コードか None (続ける)。"""
        if kind == "auth":
            return EXIT_AUTH
        if kind == "rate_limit":
            reset = gh.rate_limit_reset_at()
            remaining = self.deadline - time.monotonic()
            if reset is None:
                return EXIT_RATE_LIMIT
            wait_for = max(0.0, reset - time.time()) + 1.0
            if wait_for > remaining:
                return EXIT_RATE_LIMIT
            self.network_failures = 0
            state = self._sleep(wait_for)
            return EXIT_STOPPED if state == "stopped" else None
        self.network_failures += 1
        if self.network_failures >= NETWORK_FAILURE_LIMIT:
            return EXIT_NETWORK
        return None

    def run(self, poll):
        self.start()
        try:
            while True:
                if self.stopped:
                    return self._finish(EXIT_STOPPED, f"stopped {os.getpid()}")
                result = poll()
                if result is None:
                    self.network_failures = 0
                elif result[0] == "failure":
                    code = self._failure(result[1])
                    if code == EXIT_STOPPED:
                        return self._finish(EXIT_STOPPED, f"stopped {os.getpid()}")
                    if code is not None:
                        return self._finish(code)
                else:
                    return self._finish(result[0], result[1])
                if time.monotonic() >= self.deadline:
                    return self._finish(EXIT_TIMEOUT)
                state = self._sleep(self.interval)
                if state == "stopped":
                    return self._finish(EXIT_STOPPED, f"stopped {os.getpid()}")
                if state == "deadline":
                    # 期限切れを宣言する前にもう 1 度確かめる
                    result = poll()
                    if result is not None and result[0] != "failure":
                        return self._finish(result[0], result[1])
                    return self._finish(EXIT_TIMEOUT)
        finally:
            remove_pid_if_mine(self.pid_path)


# --- 読み取りの共通 -------------------------------------------------------------------

def _list_failure(result):
    """project.items の結果が失敗か、項目の一覧そのものが欠けていれば、失敗の種類を返す (無ければ None)。"""
    if result["status"] == "error":
        return result.get("failure") or "other"
    for p in result.get("problems") or []:
        if p.get("what") in observe.LIST_PROBLEMS:
            return p.get("failure") or "other"
    return None


def comment_pr_states(items, login, extra_urls=()):
    """開いている項目のコメントに URL で書かれた PR (と extra_urls) の状態を読む (observe diff と同じ)。
    返り値は (URL → 状態 (読めなければ {"partial": 理由}), 失敗の種類 (認証切れなど。無ければ None))。"""
    states, failure = {}, None
    urls = observe.pr_urls_in_comments(items, login)
    urls += [u for u in extra_urls if u not in urls]
    for url in urls:
        r = issues.pr_state(url)
        if r["status"] == "ok":
            states[url] = {"state": r["state"], "draft": r["draft"], "merged": r["merged"]}
        else:
            states[url] = {"partial": r["message"]}
            if r.get("failure") in ("auth", "rate_limit", "network", "timeout") and failure is None:
                failure = r["failure"]
    return states, failure


def report_pr_states(items, login):
    """項目の `PR の報告` と `依頼` (本文の追記) の PR の状態を issues.observe_pr で読む。返り値は (URL → 結果, 失敗の種類か None)。"""
    urls = itemstate.report_pr_urls(items, login)
    for item in items:
        for c in itemstate.parsed_comments(item, login):
            h = c["header"]
            if h["kind"] == "依頼" and h["values"].get("request_kind") == "本文の追記":
                url = ids.parse_pr_url(h["values"]["pr"])["url"]
                if url not in urls:
                    urls.append(url)
    states, failure = {}, None
    for url in urls:
        r = issues.observe_pr(url, login=login)
        states[url] = r
        if r["status"] != "ok" and r.get("failure") in ("auth", "rate_limit", "network", "timeout") and failure is None:
            failure = r["failure"]
    return states, failure


# --- 管理のセッションの wait ------------------------------------------------------------

def manager_poll(parsed, snapshot, login):
    """Project と PR を読み、スナップショットとの差分があれば ("diff <種類,...>") で終わる。"""
    result = project.items(parsed)
    failure = _list_failure(result)
    if failure:
        return ("failure", failure)
    comment_prs, pr_failure = comment_pr_states(result["items"], login, extra_urls=list(snapshot["comment_prs"]))
    if pr_failure:
        return ("failure", pr_failure)
    current = observe.build_snapshot(result, comment_prs, _now(), previous=snapshot)
    diffs = observe.diff(snapshot, current)
    if not diffs:
        return None
    kinds = []
    for d in diffs:
        if d["kind"] not in kinds:
            kinds.append(d["kind"])
    return (EXIT_CHANGED, "diff " + ",".join(kinds))


# --- 作業のセッションの wait-assignment -------------------------------------------------------

def _field_is_mine(item, session_id):
    return ((item.get("fields") or {}).get(itemstate.FIELD_ID) or {}).get("text") == session_id


def assignment_poll(parsed, session_id, login, blocked, in_review, pending):
    """wait-assignment の終わる条件 (observation.md の表)。複数が当たれば stop → request → resumed → assignment の順。"""
    result = project.items(parsed)
    failure = _list_failure(result)
    if failure:
        return ("failure", failure)
    items = [it for it in result["items"] if it.get("key")]
    mine = [it for it in items if any(c["header"]["kind"] == "割り当て" and c["header"]["values"].get("to") == session_id for c in itemstate.parsed_comments(it, login))]
    pr_states, pr_failure = report_pr_states(mine, login)
    if pr_failure:
        return ("failure", pr_failure)
    watched = {"blocked": list(blocked or []), "in_review": list(in_review or []), "pending": list(pending or [])}
    all_watched = watched["blocked"] + watched["in_review"] + watched["pending"]
    found = {"stop": None, "request": None, "resumed": None, "assignment": None}
    for item in items:
        key = item["key"]
        st = itemstate.derive(item, login, pr_states, parsed["number"])
        wc = itemstate.work_check(item, session_id, login, pr_states)
        is_watched = any(ids.same_issue(key, w) for w in all_watched)
        status = (item.get("status") or {}).get("name")
        if wc["assigned_to_me"] and wc["released"] and is_watched:
            found["stop"] = found["stop"] or f"stop {wc['released']['reason']}"
        if any(ids.same_issue(key, w) for w in watched["in_review"] + watched["pending"]) and st["end"] and st["end"]["kind"] == "normal":
            found["stop"] = found["stop"] or "stop close"
        if wc["assigned_to_me"]:
            for req in wc["pending_requests"]:
                if req["kind"] != "本文の追記":
                    continue
                got = pr_states.get(ids.parse_pr_url(req["values"]["pr"])["url"]) or {}
                if got.get("status") == "ok" and got.get("pr") and got["pr"]["state"] == "OPEN":
                    found["request"] = found["request"] or "request"
        if any(ids.same_issue(key, w) for w in watched["blocked"]) and status == "In Progress" and _field_is_mine(item, session_id):
            found["resumed"] = found["resumed"] or f"resumed {key}"
        if any(ids.same_issue(key, w) for w in watched["pending"]) and item.get("state") == "OPEN" and _field_is_mine(item, session_id) and status in ("In Progress", "Blocked"):
            found["resumed"] = found["resumed"] or f"resumed {key}"
        if (not is_watched and item.get("state") == "OPEN" and _field_is_mine(item, session_id) and wc["assigned_to_me"] and not wc["released"]
                and status == "In Progress"):
            found["assignment"] = found["assignment"] or f"assignment {key}"
    for kind in ("stop", "request", "resumed", "assignment"):
        if found[kind]:
            return (EXIT_CHANGED, found[kind])
    return None


# --- 作業のセッションの wait-decision ----------------------------------------------------------

def decision_poll(parsed, issue, session_id, login, declaration_id, review_update):
    """wait-decision の終わる条件 (observation.md の表)。複数が当たれば stop → go → request → wait の順。"""
    result = project.items(parsed)
    failure = _list_failure(result)
    if failure:
        return ("failure", failure)
    item = next((it for it in result["items"] if it.get("key") and ids.same_issue(it["key"], issue)), None)
    if item is None:
        return None
    pr_states, pr_failure = report_pr_states([item], login)
    if pr_failure:
        return ("failure", pr_failure)
    st = itemstate.derive(item, login, pr_states, parsed["number"])
    asg = st["assignment"]
    if not asg or asg["to"] != session_id:
        return None
    if st["release"]:
        return (EXIT_CHANGED, f"stop {st['release']['reason']}")
    if review_update and st["end"] and st["end"]["kind"] == "normal":
        return (EXIT_CHANGED, "stop close")
    res = itemstate.results_for(itemstate.parsed_comments(item, login), asg, declaration_id)
    if res["go"]:
        return (EXIT_CHANGED, "go")
    if res["returned"]:
        return (EXIT_CHANGED, "request")
    if (item.get("status") or {}).get("name") == "Blocked" and (st.get("declaration") or {}).get("manager_blocked"):
        return (EXIT_CHANGED, "wait")
    return None
