"""PR 本文の保管（pr-teeth プラグイン）。

CONCEPTS.md 第15節「PR本文(description)の差分表示」の実装。

「前回からの変更」はコードの差分しか扱えていなかった。レビューを受けて本文が
更新されるケースは多く、レビュアーとしては本文のどこが追記・修正されたかも
知りたい。差分を出すには前回時点の本文が要る。

**本文は state.json に入れず、1件1ファイルで持つ。**
  - state.json は「どの PR をどこまで通知したか」を読むためのファイルで、
    数十 KB の本文が混ざると人が開いて確認できなくなる
  - 1件ずつ独立して消せる。state の記録を残したまま本文だけ捨てられる
  - 保存が本文ごとに原子的で、1件の失敗が他を巻き込まない

**本文はキャッシュであり蓄積データではない**（docs/design/data-integrity.md）。
GitHub から取り直せるので、無ければ「前回の本文が無い」として全体を説明すれば
よく、壊れていたら捨ててよい。用語集と同じ「壊れていたら触らない」は適用しない。
"""

import difflib
import hashlib
import os
import re

from . import store

# 1件あたりの保存上限（バイト）。実測では本文は中央値 1.4KB・最大 5KB 程度で、
# 通常は掛からない。異常に長い本文（自動生成のログ貼り付け等）で state ディレクトリ
# が膨らむのを止めるための歯止め。
MAX_BODY_BYTES = 64 * 1024

# 保管する件数の上限。オープンな PR の数だけあれば足りる。
MAX_BODIES = 200

_SAFE = re.compile(r"[^A-Za-z0-9._-]")


def _name(repo, number):
    """保存名。owner/repo#番号 を1つのファイル名に潰す。

    パスの組み立てに使う値なので、英数字とハイフン等以外は落とす。
    """
    raw = str(repo or "") + "-" + str(number)
    return _SAFE.sub("-", raw).strip("-").lower() + ".md"


def path_for(bodies_dir, repo, number):
    return os.path.join(bodies_dir, _name(repo, number))


def digest(body):
    """本文のハッシュ。保存せずに「変わったか」だけ見たいときに使う。"""
    return hashlib.sha256((body or "").encode("utf-8")).hexdigest()


def save(bodies_dir, repo, number, body):
    """本文を保存する。長すぎる場合は先頭だけ残す。

    戻り値は (path, truncated)。
    """
    os.makedirs(bodies_dir, exist_ok=True)
    text = body or ""
    encoded = text.encode("utf-8")
    truncated = len(encoded) > MAX_BODY_BYTES
    if truncated:
        # UTF-8 の途中で切らない。errors="ignore" で末尾の壊れた文字を落とす。
        text = encoded[:MAX_BODY_BYTES].decode("utf-8", "ignore")

    path = path_for(bodies_dir, repo, number)
    store.save_text(path, text)
    return path, truncated


def load(bodies_dir, repo, number):
    """保存済みの本文を返す。無ければ None。

    無いことは異常ではない（初回・掃除済み・保存に失敗した回）。呼び出し側は
    「前回の本文が無い」として全体を説明する。
    """
    path = path_for(bodies_dir, repo, number)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except (OSError, ValueError):
        return None


def remove(bodies_dir, repo, number):
    try:
        os.unlink(path_for(bodies_dir, repo, number))
    except OSError:
        pass


# 差分として返す最大行数。本文全体を貼り直すのではなく、変わった箇所を示す。
MAX_DIFF_LINES = 200


def diff(previous, current, max_lines=MAX_DIFF_LINES):
    """本文の差分を unified diff で返す。変化が無ければ空文字。

    previous が None（保存が無い）の場合も空文字を返す。「前回の本文が無い」と
    「本文が変わっていない」は呼び出し側で区別する（has_previous を見る）。

    差分の判断はここで完結させる。モデルに2つの本文を渡して「どこが変わったか
    考えさせる」と、実行のたびに揺れるうえ見落としも起きる。
    """
    if previous is None:
        return ""
    before = (previous or "").splitlines()
    after = (current or "").splitlines()
    if before == after:
        return ""

    lines = list(difflib.unified_diff(
        before, after, fromfile="前回の本文", tofile="今回の本文", lineterm="", n=2,
    ))
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines.append("... (差分が長いため以降を省略)")
    return "\n".join(lines)


def prune(bodies_dir, alive, max_bodies=MAX_BODIES):
    """不要になった本文を消す。

    alive: いま記録が生きている (repo, number) の集合。ここに無いものは消す。
           state の掃除と歩調を合わせ、閉じた PR の本文を残し続けない。

    件数が上限を超えている場合は、更新が古い順にさらに消す。

    戻り値は消したファイル名のリスト。
    """
    if not os.path.isdir(bodies_dir):
        return []

    keep = {_name(repo, number) for repo, number in alive}
    removed = []
    entries = []
    for name in sorted(os.listdir(bodies_dir)):
        path = os.path.join(bodies_dir, name)
        if not os.path.isfile(path):
            continue
        if name not in keep:
            try:
                os.unlink(path)
                removed.append(name)
            except OSError:
                pass
            continue
        try:
            entries.append((os.path.getmtime(path), name, path))
        except OSError:
            continue

    over = len(entries) - max_bodies
    if over > 0:
        # 古い順。同着は名前で決めて、消えるものが実行のたびに変わらないようにする。
        entries.sort(key=lambda e: (e[0], e[1]))
        for _, name, path in entries[:over]:
            try:
                os.unlink(path)
                removed.append(name)
            except OSError:
                pass
    return removed
