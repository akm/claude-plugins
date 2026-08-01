"""GitHub 認証の取得（pr-teeth プラグイン）。

CONCEPTS.md 第6節の実装。

`review-requested:@me` はトークン所有者本人としての認証が要る。備え付けの環境トークンは
repo 限定スコープに縛られグローバル検索が弾かれるため使えない。

探索順序:
  1. 環境変数 GITHUB_TOKEN … 値をそのまま使う
  2. 環境変数 GITHUB_TOKEN_FILE … そのファイルの中身を使う
  3. `gh auth token` … 正常終了したらその出力を使う
  4. 見つからなければエラー（呼び出し側がその旨だけ伝えて終了する）

トークンを設定ディレクトリに置く経路は設けない。設定ディレクトリに秘密情報が混ざると、
バックアップや同期の対象にしたときに漏れる。ファイルで渡したい場合は
GITHUB_TOKEN_FILE で任意の場所を指す。

トークンの値は返すが、**呼び出し側はログ・生成物・通知・コミットに出してはならない。**
どこから取れたか（source）だけを表示に使う。
"""

import os
import subprocess

ENV_TOKEN = "GITHUB_TOKEN"
ENV_TOKEN_FILE = "GITHUB_TOKEN_FILE"


def _clean(value):
    """前後の空白・改行を落とす。

    ファイルや `gh auth token` の出力は末尾に改行が付く。そのまま HTTP ヘッダに
    入れると認証が通らず、原因も分かりにくいため、入口で必ず落とす。
    """
    if not value:
        return None
    value = value.strip()
    return value or None


def _from_env():
    return _clean(os.environ.get(ENV_TOKEN)), "env:" + ENV_TOKEN


def _from_env_file():
    path = _clean(os.environ.get(ENV_TOKEN_FILE))
    if not path:
        return None, None
    path = os.path.expanduser(path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _clean(f.read()), ENV_TOKEN_FILE + ":" + path
    except OSError as e:
        # 指定されたのに読めないのは設定ミス。黙って次に進むと原因が分からないため、
        # 理由を添えて呼び出し側に返す。
        return None, "error:" + ENV_TOKEN_FILE + " を読めません (" + str(e) + ")"


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
    return _clean(r.stdout), "gh auth token"


def resolve():
    """トークンと入手元を返す。

    戻り値: (token, source, error)
      token が None のとき error に理由が入ることがある（読めないファイルの指定など）。
    """
    token, source = _from_env()
    if token:
        return token, source, None

    token, source = _from_env_file()
    if token:
        return token, source, None
    # ファイル指定が壊れている場合だけ、その理由を持ち越す。
    file_error = source[len("error:"):] if source and source.startswith("error:") else None

    token, source = _from_gh_cli()
    if token:
        return token, source, None

    return None, None, file_error
