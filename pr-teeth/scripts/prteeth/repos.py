"""PR を読むための作業リポジトリの管理（pr-teeth プラグイン）。

CONCEPTS.md 第12節「無制限な clone/解析でディスク・時間を浪費しない」の実装。

これまで clone / fetch / checkout は SKILL.md の散文に従ってエージェントが実行して
いた。散文には上限も掃除も書けないため、取得量・リポジトリ数・古いものの削除の
どれも保証されていなかった。フェーズ2（1時間ごとの定期実行）ではレビュー依頼の
たびにリポジトリが増え、削除されないまま溜まり続ける。

判定をコード側に閉じ込める方針（第10節・docs/design/data-integrity.md）に合わせ、
「どこに置くか」「どれだけ取るか」「いつ消すか」はここで決める。

取得量の抑え方:
  --filter=blob:none の部分クローンにする。PR の差分を読むのに必要なのは
  コミットグラフと、実際に触るファイルの中身だけで、全履歴の blob は要らない。
  対象ファイルの中身は必要になった時点で遅延取得される（要ネットワーク）。
"""

import os
import re
import subprocess

# 1リポジトリあたりの取得を打ち切るまでの秒数。巨大なモノレポで無制限に待たない。
CLONE_TIMEOUT = 300

# fetch は clone より軽い（差分だけ）。同じ上限にすると異常時の待ちが長すぎる。
FETCH_TIMEOUT = 120

# owner/repo の形。ここを通さないものはパスに使わない。
_REPO_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")


class RepoError(Exception):
    """取得に失敗した。1件の失敗で巡回全体を止めないため、呼び出し側で握る。"""


def _run(args, cwd=None, timeout=None):
    """git を呼ぶ。失敗は RepoError にして、標準エラーを添える。"""
    try:
        p = subprocess.run(
            args, cwd=cwd, timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except subprocess.TimeoutExpired:
        raise RepoError(" ".join(args[:2]) + " が " + str(timeout) + " 秒で終わりませんでした")
    except FileNotFoundError:
        raise RepoError("git コマンドが見つかりません")
    if p.returncode != 0:
        # トークンが URL に載る経路は作っていないが、念のため生の stderr を
        # そのまま長々と出さず、末尾の要点だけにする。
        err = (p.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        raise RepoError((err[-1] if err else "git の実行に失敗しました"))
    return (p.stdout or b"").decode("utf-8", "replace")


def validate(repo):
    """owner/repo の形を確かめる。

    パスの組み立てに使う値なので、`..` や絶対パスが混ざる経路を作らない。
    エージェントが渡す値であり、GitHub から取れた値とは限らない。
    """
    name = str(repo or "").strip()
    if not _REPO_RE.match(name):
        raise RepoError("リポジトリ名の形が不正です: " + str(repo))
    if ".." in name:
        raise RepoError("リポジトリ名に .. は使えません: " + name)
    return name


def path_for(repos_dir, repo):
    """作業リポジトリの置き場所。owner ごとにディレクトリを分ける。"""
    owner, name = validate(repo).split("/")
    return os.path.join(repos_dir, owner, name)


def ensure(repos_dir, repo, url=None, timeout=None):
    """作業リポジトリを用意する。既にあれば fetch、無ければ clone。

    戻り値は (path, action)。action は "cloned" / "fetched"。
    """
    path = path_for(repos_dir, repo)
    origin = url or ("https://github.com/" + validate(repo) + ".git")

    if os.path.isdir(os.path.join(path, ".git")):
        _run(["git", "fetch", "--prune", "origin"], cwd=path,
             timeout=timeout or FETCH_TIMEOUT)
        return path, "fetched"

    os.makedirs(os.path.dirname(path), exist_ok=True)
    # 途中で失敗した clone が中途半端に残っていることがある。git が無いなら
    # リポジトリではないので、作り直す（残骸を掴んだまま fetch し続けない）。
    if os.path.isdir(path):
        _remove(path)
    _run(["git", "clone", "--filter=blob:none", "--no-checkout", origin, path],
         timeout=timeout or CLONE_TIMEOUT)
    return path, "cloned"


def _remove(path):
    """作業リポジトリを消す。蓄積データではないので作り直せる。"""
    import shutil

    shutil.rmtree(path, ignore_errors=True)


def list_repos(repos_dir):
    """作業リポジトリの一覧を返す。

    各要素は {"repo": "owner/name", "path": ..., "used_at": <epoch 秒>}。
    used_at は最終利用日時（touch で更新する）。無ければディレクトリの mtime。
    """
    out = []
    if not os.path.isdir(repos_dir):
        return out
    for owner in sorted(os.listdir(repos_dir)):
        owner_dir = os.path.join(repos_dir, owner)
        if not os.path.isdir(owner_dir):
            continue
        for name in sorted(os.listdir(owner_dir)):
            path = os.path.join(owner_dir, name)
            if not os.path.isdir(path):
                continue
            out.append({
                "repo": owner + "/" + name,
                "path": path,
                "used_at": used_at(path),
            })
    return out


_STAMP = ".pr-teeth-used"


def touch(path):
    """最終利用日時を記録する。掃除の順序を決めるのに使う。

    git のファイルの mtime は fetch の有無で変わり、「利用した」と一致しない。
    こちらで明示的に印を置く。
    """
    try:
        with open(os.path.join(path, _STAMP), "w", encoding="utf-8") as f:
            f.write("")
    except OSError:
        pass


def used_at(path):
    """最終利用日時（epoch 秒）。印が無ければディレクトリの mtime。"""
    stamp = os.path.join(path, _STAMP)
    for target in (stamp, path):
        try:
            return os.path.getmtime(target)
        except OSError:
            continue
    return 0.0


def disk_usage(path):
    """ディレクトリの合計サイズ（バイト）。"""
    total = 0
    for root, _, names in os.walk(path):
        for n in names:
            try:
                total += os.path.getsize(os.path.join(root, n))
            except OSError:
                continue
    return total
