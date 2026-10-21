"""リポジトリの設定の読み方。管理ディレクトリの設定 `repositories` のパス (worktree を作った元の clone) から、既定の
ブランチ (`origin/HEAD`) の内容のリポジトリの設定を git で読む。`origin` の URL から host と `owner/name` を取り出して、
設定のリポジトリと合うかを比べる (作業のセッションの CLI `repo name` も同じ関数を使う。KTD9)。

確かめ方・「読めない」の理由の一覧と直し方・URL の形と比べ方の正本は
issue-dispatch/skills/issue-dispatch/references/repositories.md。

git は読むだけで、fetch も書き込みもしない。`gh` は使わない。設定の内容の解釈は config.load_text (U2 の規則)。
"""

import os
import re
import subprocess

from issue_dispatch import config

GITHUB_HOST = "github.com"
GITHUB_HOST_ALIASES = ("github.com", "ssh.github.com")  # GitHub が案内する SSH の接続先 (ポート 443) も同じ host とみなす

# 「読めない」の理由。確かめる順に並べる (read_repo_config の順)
REASONS = ("not-in-repositories", "directory-missing", "not-git", "not-clone-root", "no-origin", "origin-mismatch",
           "no-origin-head", "git-failed", "config-unreadable")

_SCP_RE = re.compile(r"^(?:[^@/:]+@)?(?P<host>[^:/]+):(?P<path>[^/].*)$")
_URL_RE = re.compile(r"^(?P<scheme>ssh|https?|git)://(?:[^@/]+@)?(?P<host>[^:/]+)(?::\d+)?/(?P<path>.+)$")


def _clean_env():
    """git を実行する環境。呼び出し元の GIT_DIR などが別のリポジトリを指していても、-C のパスのリポジトリを読む。"""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def run_git(path, *args):
    """`git -C <path> <args>` を実行し、(終了コード, 標準出力 (末尾の改行を除く), 標準エラー出力) を返す。

    出力はバイト列で受け、UTF-8 として読む。読めないバイトは surrogateescape で文字列に残す (ロケールの文字コードに
    依らず、落ちない)。設定ファイルの中身のように厳密に UTF-8 であるべきものは、呼び出し側が確かめる。
    """
    try:
        p = subprocess.run(["git", "-C", path, *args], capture_output=True, env=_clean_env())
    except OSError as e:
        return None, "", f"git を起動できない: {e}"
    out = p.stdout.decode("utf-8", errors="surrogateescape")
    err = p.stderr.decode("utf-8", errors="surrogateescape")
    return p.returncode, out.rstrip("\n"), err


def parse_origin_url(url):
    """`origin` の URL から scheme と host と owner と name を取り出す。読めない形なら None。

    受け付ける形: scp 形式 (`git@host:owner/name.git`。scheme は `scp`)・`ssh://`・`https://`・`http://`・`git://`。
    末尾の `.git` と `/` は取り除く。owner と name の大文字小文字はそのまま返す (比べるときに区別しない)。
    """
    if not isinstance(url, str) or not url:
        return None
    m = _URL_RE.match(url)
    if m:
        scheme = m.group("scheme")
    else:
        m = _SCP_RE.match(url)
        if not m or "://" in url:
            return None
        scheme = "scp"
    host = m.group("host")
    path = m.group("path").rstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    parts = path.split("/")
    if len(parts) != 2 or not all(parts):
        return None
    return {"scheme": scheme, "host": host, "owner": parts[0], "name": parts[1]}


SSH_SCHEMES = ("scp", "ssh")  # SSH で接続する形。SSH の設定 (Host の別名) が意味を持つのはこの形だけ


def effective_host(parsed):
    """比べるときの host。SSH で接続する形なら `ssh -G` で解決し、それ以外 (https・http・git) は URL の host のまま。
    GitHub の別の接続先 (`ssh.github.com`) はどの形でも `github.com` にそろえる。"""
    host = parsed["host"]
    if parsed.get("scheme") in SSH_SCHEMES:
        return resolve_host(host)
    if host.lower() in GITHUB_HOST_ALIASES:
        return GITHUB_HOST
    return host.lower()


def resolve_host(host):
    """host を実際の接続先に解決する。SSH の設定 (~/.ssh/config) の Host の別名は `ssh -G <別名>` の `hostname` で解決し、
    GitHub の別の接続先 (`ssh.github.com`) は `github.com` にそろえる。ssh が無い・失敗したときは名前のまま返す。"""
    resolved = host
    try:
        p = subprocess.run(["ssh", "-G", host], capture_output=True, text=True, timeout=10)
        if p.returncode == 0:
            for line in p.stdout.splitlines():
                key, _, value = line.partition(" ")
                if key == "hostname" and value:
                    resolved = value
                    break
    except (OSError, subprocess.TimeoutExpired):
        pass
    if resolved.lower() in GITHUB_HOST_ALIASES:
        return GITHUB_HOST
    return resolved


def same_repository(parsed, repo):
    """parse_origin_url の結果が、設定のリポジトリ `owner/name` と同じリポジトリを指すか。
    host は effective_host で github.com と比べ、owner と name は大文字小文字を区別しない。"""
    if not parsed:
        return False
    if effective_host(parsed) != GITHUB_HOST:
        return False
    return f"{parsed['owner']}/{parsed['name']}".lower() == repo.lower()


def _unreadable(reason, message, fix=None, root_hint=None, path=None):
    return {"status": "unreadable", "reason": reason, "message": message, "fix": fix, "root_hint": root_hint,
            "path": path, "config": None, "warnings": [], "errors": []}


def check_clone_root(path, repo):
    """パスが、設定のリポジトリの clone のルートで、既定のブランチの参照を持つかを確かめる。
    問題があれば「読めない」の結果 (理由は REASONS の順で最初に当たったもの)、無ければ None。"""
    if not os.path.isdir(path):
        return _unreadable("directory-missing", f"ディレクトリ {path} が無い",
                           f"repositories の {repo} に、clone のルートの絶対パスを書く", path=path)
    code, out, _ = run_git(path, "rev-parse", "--is-inside-work-tree")
    if code is None:
        return _unreadable("git-failed", out or "git を起動できない", path=path)
    if code != 0:
        return _unreadable("not-git", f"{path} は git リポジトリではない",
                           f"repositories の {repo} に、clone のルートの絶対パスを書く", path=path)
    if out != "true":
        # 作業ツリーの外: bare リポジトリか、.git の中
        code, bare, _ = run_git(path, "rev-parse", "--is-bare-repository")
        hint = None
        if bare != "true":
            code, common, _ = run_git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
            if code == 0 and common:
                hint = os.path.dirname(common.rstrip("/"))
        return _unreadable("not-clone-root", f"{path} は clone のルートではない" + (" (bare リポジトリ)" if bare == "true" else " (.git の中)"),
                           (f"repositories の {repo} に {hint} を書く" if hint else f"repositories の {repo} に、作業ツリーのある clone のルートを書く"),
                           root_hint=hint, path=path)
    code, prefix, _ = run_git(path, "rev-parse", "--show-prefix")
    if prefix != "":
        _, top, _ = run_git(path, "rev-parse", "--show-toplevel")
        return _unreadable("not-clone-root", f"{path} は clone のサブディレクトリで、ルートではない",
                           f"repositories の {repo} に {top} を書く", root_hint=top or None, path=path)
    code, url, _ = run_git(path, "remote", "get-url", "origin")
    if code != 0:
        return _unreadable("no-origin", f"{path} に origin という名前のリモートが無い",
                           f"git -C {path} remote add origin <{repo} の URL>", path=path)
    parsed = parse_origin_url(url)
    if not same_repository(parsed, repo):
        return _unreadable("origin-mismatch", f"{path} の origin の URL {url!r} は {repo} と合わない (別のリポジトリか、名前を変える前の URL)",
                           f"git -C {path} remote set-url origin <{repo} の新しい URL>。別のリポジトリの clone なら repositories の {repo} を直す", path=path)
    code, _, _ = run_git(path, "rev-parse", "--verify", "--quiet", "refs/remotes/origin/HEAD")
    if code != 0:
        return _unreadable("no-origin-head", f"{path} に参照 origin/HEAD が無い (既定のブランチを推測しない)",
                           f"git -C {path} remote set-head origin --auto", path=path)
    return None


def read_repo_config(repositories, repo):
    """設定 `repositories` のパスから、リポジトリ `owner/name` の既定のブランチのリポジトリの設定を読む。

    返り値: {"status": "ok" | "missing" (既定のブランチに設定ファイルが無い) | "unreadable", "reason" (unreadable のとき REASONS の
    どれか)、"message", "fix" (直し方), "root_hint" (案内する clone のルート), "path", "config" (config.load_text の結果の config。
    missing ならデフォルト値), "warnings", "errors"}
    """
    # GitHub のリポジトリ名は大文字小文字を区別しないので、設定のキーも区別せずに引く
    path = None
    if isinstance(repositories, dict):
        path = next((v for k, v in repositories.items() if k.lower() == repo.lower()), None)
    if path is None:
        return _unreadable("not-in-repositories", f"管理ディレクトリの設定の repositories に {repo} が無い",
                           f"repositories に {repo} と、worktree を作った元の clone のルートの絶対パスを書く")
    problem = check_clone_root(path, repo)
    if problem:
        return problem
    code, listed, err = run_git(path, "ls-tree", "--name-only", "refs/remotes/origin/HEAD", "--", config.CONFIG_PATH)
    if code != 0:
        return _unreadable("git-failed", f"git ls-tree が失敗した: {err.strip()}", path=path)
    text = None
    if listed.strip():
        code, text, err = run_git(path, "show", f"refs/remotes/origin/HEAD:{config.CONFIG_PATH}")
        if code != 0:
            return _unreadable("git-failed", f"git show が失敗した: {err.strip()}", path=path)
        try:
            text.encode("utf-8")  # surrogateescape で残った読めないバイトがあれば失敗する
        except UnicodeEncodeError as e:
            result = _unreadable("config-unreadable", "既定のブランチの設定ファイルを UTF-8 として読めない",
                                 f"{repo} の既定のブランチの {config.CONFIG_PATH} を UTF-8 で保存し直す", path=path)
            result["errors"] = [{"key": "(file)", "message": f"UTF-8 として読めない: {e}"}]
            return result
    loaded = config.load_text(text, "repo", f"{path} の origin/HEAD:{config.CONFIG_PATH}")
    result = {"status": loaded["status"], "reason": None, "message": None, "fix": None, "root_hint": None, "path": path,
              "config": loaded["config"], "warnings": loaded["warnings"], "errors": loaded["errors"]}
    if loaded["status"] == "unreadable":
        result.update({"reason": "config-unreadable", "message": "既定のブランチの設定ファイルを読めない (errors に理由)",
                       "fix": f"{repo} の既定のブランチの {config.CONFIG_PATH} を直す"})
    return result


def repo_name(worktree):
    """作業ツリーの `origin` の URL から `owner/name` を決める (CLI `repo name`)。gh は使わない。
    返り値: {"status": "ok", "repo", "host"} か {"status": "error", "reason", "message"}。"""
    code, _, _ = run_git(worktree, "rev-parse", "--is-inside-work-tree")
    if code is None:
        return {"status": "error", "reason": "git-failed", "message": "git を起動できない"}
    if code != 0:
        return {"status": "error", "reason": "not-git", "message": f"{worktree} は git リポジトリではない"}
    code, url, _ = run_git(worktree, "remote", "get-url", "origin")
    if code != 0:
        return {"status": "error", "reason": "no-origin", "message": f"{worktree} に origin という名前のリモートが無い"}
    parsed = parse_origin_url(url)
    if not parsed:
        return {"status": "error", "reason": "url-unparsable", "message": f"origin の URL {url!r} から owner/name を読めない"}
    host = effective_host(parsed)
    if host != GITHUB_HOST:
        return {"status": "error", "reason": "not-github", "message": f"origin の host {host!r} は GitHub ではない"}
    return {"status": "ok", "repo": f"{parsed['owner']}/{parsed['name']}", "host": host}
