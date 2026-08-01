"""通知済み状態と更新の判定（pr-teeth プラグイン）。

CONCEPTS.md 第10節ステップ4・第11節の実装。

`mode=changes-only` で「前回から変わったか」を判定する。判定を head SHA だけに
すると、コミットを伴わない更新（PR本文の書き直し、レビューコメントの追加、
ラベルやベースブランチの変更）を取りこぼす。レビュー依頼の文脈では本文の補足も
重要な更新なので、`updated_at` も併せて見る。

state.json の形:

    {"notified": {"<owner>/<repo>#<number>": {"sha": "...", "updated_at": "..."}}}

旧形式（値が head SHA の文字列）も読める。移行のために利用者へ再設定を求めない。
"""

NEW = "new"
UPDATED = "updated"
UNCHANGED = "unchanged"


def key(repo, number):
    return str(repo) + "#" + str(number)


def _entry(value):
    """記録済みエントリを正規化する。旧形式（SHA の文字列）も受ける。"""
    if isinstance(value, str):
        return {"sha": value, "updated_at": None}
    if isinstance(value, dict):
        return {"sha": value.get("sha"), "updated_at": value.get("updated_at")}
    return None


def load_notified(state):
    """state.json の中身から notified マップを取り出す。"""
    if not isinstance(state, dict):
        return {}
    notified = state.get("notified")
    if not isinstance(notified, dict):
        return {}
    return notified


def classify(notified, repo, number, sha, updated_at):
    """PR 1件が new / updated / unchanged のどれかを返す。

    戻り値: (状態, 前回のSHA)
    前回のSHA は updated のときに差分の起点として使う（第10節ステップ5）。
    """
    prev = _entry(load_notified({"notified": notified}).get(key(repo, number)))
    if prev is None:
        return NEW, None

    # sha か updated_at のどちらかが変わっていれば更新。
    # 旧形式で updated_at が無い場合は sha だけで判定する（比較できないものを
    # 「変わった」とみなすと、移行直後に全件が更新扱いになってしまう）。
    changed = False
    if sha and prev.get("sha") and sha != prev["sha"]:
        changed = True
    if updated_at and prev.get("updated_at") and updated_at != prev["updated_at"]:
        changed = True

    if changed:
        return UPDATED, prev.get("sha")
    return UNCHANGED, prev.get("sha")


def select_targets(state, prs):
    """対象PRを選ぶ。

    prs: [{"repo","number","sha","updated_at", ...}]
    戻り値: 対象だけを、`status` と `base_sha`（差分の起点）を足して返す。
    """
    notified = load_notified(state)
    out = []
    for pr in prs:
        status, base = classify(
            notified, pr.get("repo"), pr.get("number"), pr.get("sha"), pr.get("updated_at")
        )
        if status == UNCHANGED:
            continue
        item = dict(pr)
        item["status"] = status
        # 差分の起点。new のときは無い（全体を説明する）。
        item["base_sha"] = base if status == UPDATED else None
        out.append(item)
    return out


def record_notified(state, prs):
    """通知済みとして記録した新しい state を返す。

    オープンな依頼に無いエントリは掃除する（第11節）。閉じた PR の記録を
    残し続けると、再オープン時に「変化なし」と誤判定しうる。
    """
    notified = {}
    for pr in prs:
        notified[key(pr.get("repo"), pr.get("number"))] = {
            "sha": pr.get("sha"),
            "updated_at": pr.get("updated_at"),
        }
    new_state = dict(state or {})
    new_state["notified"] = notified
    return new_state
