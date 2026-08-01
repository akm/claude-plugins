"""GitHub 認証の取得（pr-teeth プラグイン）。

CONCEPTS.md 第6節の実装。

`review-requested:@me` はトークン所有者本人としての認証が要る。備え付けの環境トークンは
repo 限定スコープに縛られグローバル検索が弾かれるため使えない。

トークンの値は返すが、**呼び出し側はログ・生成物・通知・コミットに出してはならない。**
どこから取れたか（token_source）だけを表示に使う。
"""

import os
import subprocess

# 優先度順に見る環境変数。
_ENV_VARS = ("GH_TOKEN", "GITHUB_TOKEN")


def _from_env():
    for name in _ENV_VARS:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value, "env:" + name
    return None, None


def _from_gh_cli():
    try:
        r = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None, None
    if r.returncode != 0:
        return None, None
    value = (r.stdout or "").strip()
    if not value:
        return None, None
    return value, "gh auth"


def _from_file(config_dir):
    path = os.path.join(config_dir, "token.txt")
    try:
        with open(path, "r", encoding="utf-8") as f:
            value = f.read().strip()
    except OSError:
        return None, None
    if not value:
        return None, None
    # 1行目だけを使う（末尾の改行やメモ書きを拾わない）。
    return value.splitlines()[0].strip(), "token.txt"


def resolve(config_dir):
    """トークンと入手元を返す。見つからなければ (None, None)。

    順序は第6節のとおり: 環境変数 → gh auth → 設定ディレクトリの token.txt。
    """
    for getter in (_from_env, _from_gh_cli):
        value, source = getter()
        if value:
            return value, source
    return _from_file(config_dir)
