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

from . import state, store

# 1件あたりの保存上限（バイト）。実測では本文は中央値 1.4KB・最大 5KB 程度で、
# 通常は掛からない。異常に長い本文（自動生成のログ貼り付け等）で state ディレクトリ
# が膨らむのを止めるための歯止め。
MAX_BODY_BYTES = 64 * 1024

# 保管する件数の上限。オープンな PR の数だけあれば足りる。
MAX_BODIES = 200

_SAFE = re.compile(r"[^A-Za-z0-9._-]")
_DOTS = re.compile(r"\.{2,}")

# 人が読むための部分の長さ。これ自体は一意性を担わない（末尾のハッシュが担う）。
_STEM_CHARS = 60

# 一意性を担うハッシュの長さ。16 桁 (64bit) あれば、保管上限の 200 件に対して
# 衝突は現実的に起こらない。
_DIGEST_CHARS = 16


def _name(repo, number):
    """保存名。owner/repo#番号 を1つのファイル名に潰す。

    英数字とハイフン等以外を落とすだけでは**別の PR が同じ名前になる**。
    `acme/web-api#1` と `acme-web/api#1` はどちらも正当な GitHub のリポジトリだが、
    区切りを潰すと両方 `acme-web-api-1` になり、一方の本文がもう一方の差分の基準に
    使われる（利用者には気づけない誤った解説になる）。

    そこで**末尾に鍵のハッシュを付けて一意にする**。鍵は state.key と同じ
    `owner/repo#番号` にし、state の記録と本文の対応が定義上ずれないようにする。
    先頭の読みやすい部分は人がファイルを見分けるためのもので、一意性は担わない。
    """
    key = state.key(repo, number)
    fingerprint = hashlib.sha256(key.encode("utf-8")).hexdigest()[:_DIGEST_CHARS]
    stem = _SAFE.sub("-", key).lower()
    # `..` はパスとしては os.path.join で無害だが、ファイル名に残ると紛らわしい。
    # 一意性はハッシュが担うので、読みやすさのために潰してよい。
    stem = _DOTS.sub(".", stem).strip("-.")[:_STEM_CHARS].strip("-.")
    # stem が空になる場合（repo が記号だけ等）でも、ハッシュだけで成立させる。
    return ((stem + "-") if stem else "") + fingerprint + ".md"


def path_for(bodies_dir, repo, number):
    return os.path.join(bodies_dir, _name(repo, number))


def save(bodies_dir, repo, number, body):
    """本文を保存する。長すぎる場合は先頭だけ残す。

    戻り値は (path, truncated)。

    既知の問題: 切り詰めた本文を保存すると、次回は「切り詰めた前回」と「完全な今回」を
    比較するため、本文が変わっていなくても差分が出る（#25）。実測では本文は中央値
    1.4KB・最大 5.3KB で上限の 64KB には遠く、現実にはほぼ起きないため未対応。
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


# 差分として返す最大行数。本文全体を貼り直すのではなく、変わった箇所を示す。
MAX_DIFF_LINES = 200

# 差分として返す最大バイト数。行数だけを縛ってもバイト数は縛れない
# （長い行が数本あれば、200 行以内でも数百 KB になる）。モデルの文脈を圧迫しない。
MAX_DIFF_BYTES = 8 * 1024

# 1行の最大文字数。これを超える行は途中で省略する。折り返しの無い長大な行は、
# それ自体では「どこが変わったか」を伝えないうえ、他の行を押し出す。
MAX_DIFF_LINE_CHARS = 500


def diff(previous, current, max_lines=MAX_DIFF_LINES, max_bytes=None):
    """本文の差分を unified diff で返す。変化が無ければ空文字。

    previous が None（保存が無い）の場合も空文字を返す。「前回の本文が無い」と
    「本文が変わっていない」は呼び出し側で区別する（has_previous を見る）。

    差分の判断はここで完結させる。モデルに2つの本文を渡して「どこが変わったか
    考えさせる」と、実行のたびに揺れるうえ見落としも起きる。

    長い差分は先頭と末尾を残して中略する（_clip_diff 参照）。
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
    lines = [_clip_line(ln) for ln in lines]
    return "\n".join(_clip_diff(lines, max_lines, max_bytes))


def _clip_line(line):
    """長すぎる1行を切り詰める。"""
    if len(line) <= MAX_DIFF_LINE_CHARS:
        return line
    return line[:MAX_DIFF_LINE_CHARS] + " …(行が長いため省略)"


_ELLIPSIS = "... (差分が長いため中略)"


def _clip_diff(lines, max_lines, max_bytes):
    """差分を先頭と末尾に分けて切り詰める。

    先頭から一律に切ると、unified diff の並び上、削除行だけが残って追加行が
    すべて落ちる。本文を書き直した PR では「全部消された」という誤った印象に
    なるため、**先頭と末尾の両方を残す**。

    行数だけでなくバイト数でも縛る。長い行が数本あれば、行数の上限に達しないまま
    モデルの文脈を数百 KB 圧迫しうるため。
    """
    max_bytes = MAX_DIFF_BYTES if max_bytes is None else max_bytes

    def _fits(chunk):
        return len("\n".join(chunk).encode("utf-8")) <= max_bytes

    if len(lines) <= max_lines and _fits(lines):
        return lines

    # ヘッダ（--- / +++）は残す。どちらの本文かが分からなくなるため。
    header = [ln for ln in lines[:2] if ln.startswith(("---", "+++"))]
    body = lines[len(header):]

    # 返す総行数が max_lines を超えないようにする。ヘッダと中略行もその内数。
    budget = max_lines - len(header) - 1
    while budget > 0:
        head_n = budget // 2
        tail_n = budget - head_n
        candidate = header + body[:head_n] + [_ELLIPSIS] + body[-tail_n:]
        if _fits(candidate):
            return candidate
        # バイト数に収まらなければ、前後を均等に削る。
        budget -= 2
    return header + [_ELLIPSIS]


def prune(bodies_dir, alive=None, max_bodies=None):
    """不要になった本文を消す。

    alive: いま記録が生きている (repo, number) の集合。ここに無いものは消す。
           state の掃除と歩調を合わせ、閉じた PR の本文を残し続けない。
           **None なら件数の上限だけを適用する**（どれが生きているか分からない
           ので、生死による削除はしない）。

    件数が上限を超えている場合は、最終更新が古い順にさらに消す。

    戻り値は消したファイル名のリスト。
    """
    if not os.path.isdir(bodies_dir):
        return []

    # 既定値は呼び出し時に読む。定義時に束縛すると、MAX_BODIES を差し替えても
    # 反映されない（設定から上限を変えられるようにする際にも効く）。
    if max_bodies is None:
        max_bodies = MAX_BODIES

    keep = None if alive is None else {_name(repo, number) for repo, number in alive}
    removed = []
    entries = []
    for name in sorted(os.listdir(bodies_dir)):
        path = os.path.join(bodies_dir, name)
        if not os.path.isfile(path):
            continue
        # 他プロセスが書き込み中の一時ファイルには触らない。store の原子的書き込みは
        # 一時ファイル + os.replace で成り立っているため、ここで消すとその保証が崩れる
        # （書き込み側は消えたファイルを replace しようとして失敗する）。
        if name.startswith(".tmp-"):
            continue
        if keep is not None and name not in keep:
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
