#!/usr/bin/env python3
"""このリポジトリのプラグインについて、手元の Claude Code へのインストール状況を表示し、user スコープに無いものをインストールする。

リポジトリのルートの Makefile のターゲット plugins-status と plugins-install から実行する。直接実行するときは次の形にする。

  python3 scripts/plugins.py status  [--plugins <名前>,<名前>...]
  python3 scripts/plugins.py install [--plugins <名前>,<名前>...]

サブコマンド:
  status   対象のプラグインごとに、最新の版とインストール済みの版を表示する
  install  対象のプラグインのうち、user スコープにインストールされていないものをインストールする

対象のプラグインは、origin/main のファイル .claude-plugin/marketplace.json に載っているもの。オプション --plugins に
カンマ区切りの名前を渡すと、そのうちの渡した名前のものだけを対象にする。Makefile は、make のコマンドラインで変数 PLUGINS を
指定したときだけ、その値をこのオプションで渡す。対象は marketplace.json の順に扱い、渡した順にはしない。同じ名前を 2 回
渡してもエラーにしない。最新の版は、origin/main にある <source.path>/.claude-plugin/plugin.json の version。

語:
  配布元      プラグインを配布する GitHub のリポジトリ (ホスト・所有者・リポジトリの組。ファイル CONCEPTS.md の語)。
              作業ツリーの marketplace.json の、各プラグインの source.url から決める
  変える操作  手元の Claude Code の状態を変える claude のコマンド (claude plugin marketplace update と claude plugin install)

前提の検査 (2 つのサブコマンドに共通)。次の順に行い、成り立たないものがあれば、変える操作を 1 つも実行せずに終了コード 3 で
終了する。
  1. Python が 3.11 以上である
  2. --plugins の値に、空の要素 (a,,b・先頭か末尾のカンマ・空の値) が無い
  3. 作業ツリーの .claude-plugin/marketplace.json から、マーケットプレイスの名前と配布元を読める。各プラグインの source.url が
     github.com の URL で、すべて同じ配布元を指す
  4. マーケットプレイスが登録されている (claude plugin marketplace list --json)。登録されていなければ、登録するコマンドを
     表示する。登録は利用者の環境に設定を足す操作なので、このスクリプトでは行わない
  5. 登録したマーケットプレイスの取得元が配布元である。akm/claude-plugins の形で登録したものも、URL の形で登録したものも
     受け付ける
  6. remote origin の URL (git config --get remote.origin.url の値) が配布元を指す
  7. git fetch で origin の main を取得できる。失敗したときは、手元にある古い origin/main を使わない
  8. 取得した直後の origin/main の SHA にある marketplace.json の、マーケットプレイスの名前と配布元が、作業ツリーのものと同じ。
     各プラグインの source が git-subdir で、ref が main。marketplace.json と plugin.json は、どれもこの SHA から読む
  9. --plugins の名前が、すべて origin/main の marketplace.json に載っている
  10. 対象のプラグインの plugin.json が origin/main にあり、version が X.Y.Z (3 つの 10 進の整数) の形である
  11. claude plugin list --json の出力が、必要なキーを持つ。キーを検査するのは、このマーケットプレイスのプラグインの要素だけ。
      対象のプラグインのインストール済みの版が X.Y.Z の形である

状況の表示 (サブコマンド status)。前提の検査と読み取りの後、標準出力に次を表示する。
  - 対象のプラグインごとに、最新の版と、スコープ (user・project・local) ごとのインストール済みの版と、最新の版と比べた結果
    (同じ・古い・新しい)。project / local スコープの行には、プロジェクトのパスを添える
  - user スコープの行には、有効か無効か (user スコープの設定の値)。project / local スコープの行には示さない。
    claude plugin list --json の enabled は、スコープごとの値ではなく、コマンドを実行したディレクトリで有効かを表すため
  - user スコープにインストールされていないプラグインは、user スコープの行に、インストールされていないことを示す
  - user スコープの版が古いもの・user スコープにインストールされていないもの・user スコープで無効なものの名前のまとめ
  - 最後に、古いプラグインはマーケットプレイスの自動更新で更新されること、自動更新が有効かを確認して切り替える方法
    (Claude Code のセッションの /plugin の Marketplaces タブ)、すぐに更新する方法 (同じ画面の「Update marketplace」) と、
    公式ドキュメントの URL。自動更新が有効かは判定しない。設定が 3 か所 (設定ファイルの extraKnownMarketplaces・
    Claude Code が内部に持つファイル・管理者の設定) にあり、claude の CLI の出力からは判定できないため
状況の表示は、インストール済みのプラグインもマーケットプレイスの clone も変えない (claude は plugin marketplace list と
plugin list だけを実行する)。古いものがあっても、終了コード 0 で終了する。

インストール (サブコマンド install)。前提の検査と読み取りの後、次の順に行う。
  1. 対象のプラグインのうち、user スコープにインストールされていないものを、marketplace.json の順に選ぶ。user スコープに
     インストール済みのものは、版が古くても扱わない (更新は、マーケットプレイスの自動更新に任せる)。選んだものが無ければ、
     マーケットプレイスの定義も取得し直さずに、何も変えずに終了コード 0 で終了する
  2. claude plugin marketplace update <マーケットプレイスの名前> で、マーケットプレイスの定義を取得し直す。clone が古いと
     古い版が入り、clone を取得した後に足したプラグインは見つからないため
  3. 選んだものを 1 つずつ、claude plugin install <名前>@<マーケットプレイスの名前> --scope user --json でインストールする。
     -y は付けない (マーケットプレイスが宣言したコマンドを、利用者の確認なしに受け入れないため)。成功するたびに
     claude plugin list --json を再度読み込み、user スコープの版が最新の版と同じかを検査する
  4. 標準出力に、インストールしたものの一覧と、実行の後の案内を表示する
変える操作の出力は解析しない。成否は、終了コードと、その後の再度の読み込みで判定する。進み具合 (取得し直すこと・
インストールするもの・インストールしたもの) は、そのたびに標準出力に表示する。

中止。次のときは、その時点で中止し、残りのプラグインは処理せずに、終了コード 4 で終了する。
  - claude plugin marketplace update か claude plugin install が失敗した (終了コード 0 以外・タイムアウト・起動できない)。
    インストールが失敗したときは、claude plugin list --json を再度読み込み、そのプラグインの実際の状態 (user スコープの版か、
    インストールされていないこと) を示す。この読み込みも失敗したら、版が変わったか分からないと示す。再度読み込んだ版が
    最新の版と同じなら、インストールしたものとして扱う
  - claude plugin install が成功を返したのに、再度読み込んだ user スコープの版が最新の版と同じでない (インストールされて
    いないことも含む)。再度の読み込みが失敗したときも中止し、版が変わったか分からないと示す
中断。Ctrl-C で中断したときは、それ以上コマンドを実行せずに、終了コード 130 で終了する。処理中だったプラグインは、
版が変わったか分からないと示し、make plugins-status で確認するよう案内する。
中止・中断したときは、標準エラー出力に、インストールしたものの一覧・処理中だったものの状態・処理しなかったものの名前と、
実行の後の案内 (要るときだけ) を書き、最後にエラーの文を書く。

実行の後の案内。次のどれかがあれば、表示する。中止・中断したときも同じ。
  - インストールしたもの
  - 版が変わったか分からないもの
  - 処理中だったもので、再度読み込むと user スコープにあったもの (版が最新の版と違っても、user スコープの状態は変わっている)
案内は次の 2 つで、どちらも表示するだけで、実行はしない。
  - Claude Code の再起動が要ること。再起動するまで、実行中のセッションには反映されない
  - wording-guard が上のどれかに当たり、再度読み込んだ要素があれば、textlint を入れるコマンド
    python3 <展開先>/scripts/wording_lint.py setup。展開先は、インストールの後に再度読み込んだ installPath (版ごとに変わるので、
    前の値や組み立てたパスは使わない)。展開先に空白などがあれば、シェルの引用符で囲む。実行しないのは、npm で多くの
    パッケージを取得するため

URL は、scp 形式 (git@github.com:<所有者>/<リポジトリ>.git)・ssh://・https://・git:// を受け付ける。末尾の .git と / を
除き、大文字と小文字を区別せずに、ホスト・所有者・リポジトリを比べる。SSH の設定の Host の別名は解決しないので、別名で書いた
URL は配布元と判定しない。

リポジトリのルートは、このファイルの実体があるディレクトリ scripts/ の親ディレクトリとする。cwd からは決めない。
claude は、実行のたびに作る空の一時ディレクトリを cwd にして実行し、実行が終了したら一時ディレクトリを消す
(claude plugin list --json の enabled が、user スコープの設定の値になるため)。git は -C <ルート> で実行し、実行先の
リポジトリを変える環境変数 (GIT_DIR など) を消す。待機の上限は、読み取りが 60 秒、git fetch が 120 秒、変える操作が 300 秒。

終了コード:
  0    成功
  3    前提の検査か読み取りでエラーになり、何も変えずに終了した
  4    変える操作の途中で中止した。一部が変わっている可能性がある
  130  Ctrl-C で中断した
1 と 2 は Python 自身 (捕まえていない例外・引数の誤り) が使うので、専用の終了コードには使わない。make から実行すると、
スクリプトの終了コードが 0 以外ならどれも make の終了コード 2 になるので、何を変えたかはエラーの文 (標準エラー出力) に書く。
エラーの文は、プログラム名 plugins.py を前に付け、直し方を添える。
"""

# Python 3.9 (macOS に付属の /usr/bin/python3) でも構文エラーにならない書き方にする。関数 python_too_old の案内を表示するため

import argparse
import json
import os
import posixpath
import re
import shlex
import subprocess
import sys
import tempfile
import unicodedata

PROG = "plugins.py"
# リポジトリのルート。このファイルの実体があるディレクトリ scripts/ の親ディレクトリ。cwd からは決めない (KTD3)
ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
MARKETPLACE_RELPATH = ".claude-plugin/marketplace.json"

EXIT_OK = 0
EXIT_PRECONDITION = 3
EXIT_ABORTED = 4
EXIT_INTERRUPTED = 130

# 待機の上限 (秒)。読み取り (plugin list・plugin marketplace list と、fetch 以外の git)・git fetch・変える操作。
# 変える操作は、pr-teeth の CLONE_TIMEOUT と同じにする
READ_TIMEOUT = 60
FETCH_TIMEOUT = 120
CHANGE_TIMEOUT = 300
# 失敗したコマンドの出力のうち、エラーの文に添える末尾の行数
TAIL_LINES = 20

GITHUB_HOST = "github.com"
SCOPES = ("user", "project", "local")
NOTHING_CHANGED = "何も変えていない"
CLI_SHAPE_FIX = ("Claude Code の版が上がって、出力の形が変わった可能性がある。claude の出力を見て、"
                 "scripts/plugins.py の読み方を直す")

# 状況の表示で、最新の版と比べた結果 (関数 compare_versions の値) を示す語
COMPARISON_LABELS = {"same": "同じ", "older": "古い", "newer": "新しい"}
# 状況の表示の最後に示す、自動更新の案内 (R21)。公式ドキュメントの URL と、/plugin の画面の項目の名前は、ここだけに書く。
# URL や画面の項目の名前が変わったら、ここを直す。{marketplace} には、marketplace.json から読んだマーケットプレイスの名前が入る
AUTO_UPDATE_NOTE = (
    "古いプラグインは、マーケットプレイス {marketplace} の自動更新で更新される。\n"
    "自動更新が有効かは、Claude Code のセッションで /plugin を開き、Marketplaces タブで {marketplace} を選ぶと確認できる。"
    "同じ画面で、有効と無効を切り替えられる。\n"
    "すぐに更新したいときは、同じ画面で「Update marketplace」を選ぶ。\n"
    "公式ドキュメント: https://code.claude.com/docs/ja/plugins/install#turn-auto-update-on-or-off-for-a-marketplace"
)

# インストールの後の案内 (R18)。どちらも表示するだけで、実行はしない
RESTART_NOTE = "Claude Code を再起動する必要がある。再起動するまで、実行中のセッションには、インストールしたプラグインが反映されない。"
# textlint を入れるコマンドを案内するプラグインの名前と、そのコマンドのスクリプトの、展開先からの相対パス
WORDING_GUARD = "wording-guard"
WORDING_LINT_RELPATH = os.path.join("scripts", "wording_lint.py")
WORDING_LINT_NOTE = ("wording-guard の textlint による検査 (任意) を使うときは、次のコマンドで textlint を入れる "
                     "(Node と npm が必要。このスクリプトは実行しない):")
# 版が変わったか分からないときの案内
STATUS_HINT = "make plugins-status で確認する"

# 実行先のリポジトリを変える git の環境変数。git rev-parse --local-env-vars の出力 (git 2.50.1)。
# git のフックの中から実行されると、GIT_DIR などが別のリポジトリを指していることがあるので、git を実行する前に消す。
# GIT_ALLOW_PROTOCOL・GIT_CONFIG_GLOBAL のように実行先を変えない変数は残す
GIT_LOCAL_ENV_VARS = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT",
    "GIT_OBJECT_DIRECTORY", "GIT_DIR", "GIT_WORK_TREE", "GIT_IMPLICIT_WORK_TREE", "GIT_GRAFT_FILE",
    "GIT_INDEX_FILE", "GIT_NO_REPLACE_OBJECTS", "GIT_REPLACE_REF_BASE", "GIT_PREFIX", "GIT_SHALLOW_FILE",
    "GIT_COMMON_DIR",
)

_VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
# URL の形。ファイル issue-dispatch/scripts/issue_dispatch/repo.py の関数 parse_origin_url の形を写した
# (issue-dispatch は配布していないので import しない)。scheme は KTD4 が挙げる 4 つに限る
_SCP_RE = re.compile(r"^(?:[^@/:]+@)?(?P<host>[^:/]+):(?P<path>[^/].*)$")
_URL_RE = re.compile(r"^(?P<scheme>ssh|https|git)://(?:[^@/]+@)?(?P<host>[^:/]+)(?::\d+)?/(?P<path>.+)$")
# <所有者>/<リポジトリ> の形。どちらも、名前に使える文字 (英数字と ._-) の 1 文字以上
_REPO_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")


class PluginsError(Exception):
    """前提の検査か読み取りのエラー。message は起きたこと (1 行)、fix は直し方、detail はエラーの文に添える出力 (複数行)。"""

    def __init__(self, message, fix=None, detail=None):
        super().__init__(message)
        self.message = message
        self.fix = fix
        self.detail = detail


class CommandError(PluginsError):
    """外部のコマンド (claude・git) の失敗。returncode は終了コードで、起動できない・タイムアウトのときは None。"""

    def __init__(self, message, fix=None, detail=None, returncode=None):
        super().__init__(message, fix, detail)
        self.returncode = returncode


def python_too_old(version_info=sys.version_info):
    """Python が 3.11 より古ければ、その旨の案内の文を返す。足りていれば None を返す。"""
    if tuple(version_info[:2]) >= (3, 11):
        return None
    used = ".".join(str(v) for v in version_info[:3])
    return f"Python 3.11 以上が必要 (CI と同じ版を前提にしている)。実行した Python: {used}"


# ---- 外部のコマンド (KTD2) ----

def _decode(data):
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    return data.decode("utf-8", errors="replace")


def _output_detail(stdout, stderr):
    """コマンドの標準出力と標準エラー出力の末尾を、エラーの文に添える形にする。どちらも空なら None。"""
    parts = []
    for label, text in (("標準出力", stdout), ("標準エラー出力", stderr)):
        lines = text.rstrip("\n").splitlines()[-TAIL_LINES:]
        if lines:
            parts.append(f"{label}の末尾:")
            parts.extend("  " + line for line in lines)
    return "\n".join(parts) or None


def _run(argv, cwd, env, timeout):
    """argv を実行し、標準出力を文字列で返す。起動できない・タイムアウト・終了コード 0 以外は CommandError にする。"""
    shown = " ".join(argv)
    try:
        p = subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)
    except FileNotFoundError:
        raise CommandError(f"コマンド {argv[0]} が見つからない",
                           f"{argv[0]} をインストールし、環境変数 PATH に含まれるディレクトリに置く") from None
    except OSError as e:
        raise CommandError(f"コマンド {shown} を起動できない: {e}", "コマンドのファイルと権限を確認する") from None
    except subprocess.TimeoutExpired as e:
        raise CommandError(f"コマンド {shown} が {timeout} 秒で終了しなかった",
                           "時間がかかった原因 (ネットワークなど) を取り除いてから、もう一度実行する",
                           _output_detail(_decode(e.stdout), _decode(e.stderr))) from None
    if p.returncode != 0:
        raise CommandError(f"コマンド {shown} が終了コード {p.returncode} で失敗した",
                           "出力を見て原因を取り除いてから、もう一度実行する",
                           _output_detail(_decode(p.stdout), _decode(p.stderr)), p.returncode)
    try:
        return p.stdout.decode("utf-8")
    except UnicodeDecodeError as e:
        raise CommandError(f"コマンド {shown} の標準出力を UTF-8 として読めない: {e}", "出力を見て原因を取り除く") from None


def run_claude(args, timeout):
    """claude を、実行のたびに作る空の一時ディレクトリを cwd にして実行し、標準出力を返す。実行が終了したら一時ディレクトリを消す。

    claude plugin list --json の enabled は、実行したディレクトリの設定も反映する。空のディレクトリなら、user スコープの
    設定の値になる。
    """
    with tempfile.TemporaryDirectory(prefix="plugins-claude-") as cwd:
        return _run(["claude"] + list(args), cwd, None, timeout)


def git_env():
    """git を実行する環境変数。実行先のリポジトリを変える変数 (GIT_LOCAL_ENV_VARS) を消す。"""
    return {k: v for k, v in os.environ.items() if k not in GIT_LOCAL_ENV_VARS}


def run_git(root, args, timeout=READ_TIMEOUT):
    """git -C root を実行し、標準出力を返す。"""
    return _run(["git", "-C", root] + list(args), None, git_env(), timeout)


# ---- 名前・URL・版 ----

def parse_names(value):
    """オプション --plugins の値 (カンマ区切りの名前) を、名前の配列にする。指定しないとき (None) は None を返す。

    空の要素 (a,,b・先頭か末尾のカンマ・空の値) があれば PluginsError を投げる。
    """
    if value is None:
        return None
    names = value.split(",")
    if any(name == "" for name in names):
        raise PluginsError(f"オプション --plugins の値「{value}」に空の要素がある",
                           "名前をカンマで区切り、空の要素 (続けて書いたカンマ・先頭か末尾のカンマ・空の値) を含めずに指定する。"
                           "例: doc-dag,wording-guard")
    return names


def parse_repo_url(url):
    """URL から scheme・host・owner (所有者)・name (リポジトリ) を取り出す。読めない形なら None を返す。

    受け付ける形: scp 形式 (git@host:owner/name.git。scheme は scp)・ssh://・https://・git://。末尾の .git と / は除く。
    大文字と小文字はそのまま返す (比べるときは関数 source_key で小文字にそろえる)。
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
    if len(parts) != 2 or not all(parts) or not _REPO_NAME_RE.match(path):
        return None
    return {"scheme": scheme, "host": host, "owner": parts[0], "name": parts[1]}


def source_key(url):
    """URL を、配布元を比べる形 (ホスト・所有者・リポジトリを小文字にした組) にする。読めない形なら None を返す。

    SSH の設定の Host の別名は解決しないので、別名で書いた URL は github.com の URL と違う組になる。
    """
    parsed = parse_repo_url(url)
    if parsed is None:
        return None
    return (parsed["host"].lower(), parsed["owner"].lower(), parsed["name"].lower())


def format_source(key):
    """関数 source_key の組を、表示する形 (github.com/akm/claude-plugins) にする。"""
    return "/".join(key)


def parse_version(value):
    """版 value が X.Y.Z (3 つの 10 進の整数) の形なら整数の組を、そうでなければ None を返す。"""
    if not isinstance(value, str) or not _VERSION_RE.fullmatch(value):
        return None
    return tuple(int(part) for part in value.split("."))


def compare_versions(installed, latest):
    """インストール済みの版 installed を最新の版 latest と比べ、"same"・"older"・"newer" のどれかを返す。

    どちらも X.Y.Z の形であること。形でなければ ValueError を投げる (形の検査は、読み取りのときに済ませておく)。
    """
    a, b = parse_version(installed), parse_version(latest)
    if a is None or b is None:
        raise ValueError(f"X.Y.Z の形でない版を比べようとした: {installed!r}, {latest!r}")
    if a == b:
        return "same"
    return "older" if a < b else "newer"


# ---- marketplace.json ----

def parse_marketplace(data, what):
    """marketplace.json の中身 data から、マーケットプレイスの名前・配布元 (関数 source_key の組)・プラグインの配列を読む。

    what はエラーの文に書くファイルの説明 (作業ツリーのものか origin/main のものか)。各プラグインに名前と source.url があり、
    名前が重複せず、source.url がどれも github.com の URL で、すべて同じ配布元を指すこと。成り立たなければ PluginsError を投げる。
    """
    def shape(detail):
        return PluginsError(f"{what} の形が想定と違う: {detail}", "marketplace.json を直す")

    if not isinstance(data, dict):
        raise shape("JSON のオブジェクトでない")
    name = data.get("name")
    if not isinstance(name, str) or not name:
        raise shape("マーケットプレイスの名前 (キー name) が無い")
    plugins = data.get("plugins")
    if not isinstance(plugins, list):
        raise shape("キー plugins が配列でない")
    seen = set()
    keys = set()
    for i, plugin in enumerate(plugins):
        if not isinstance(plugin, dict) or not isinstance(plugin.get("name"), str) or not plugin["name"]:
            raise shape(f"{i + 1} 番目のプラグインに名前 (キー name) が無い")
        plugin_name = plugin["name"]
        if plugin_name in seen:
            raise shape(f"プラグインの名前 {plugin_name} が 2 回以上ある")
        seen.add(plugin_name)
        source = plugin.get("source")
        url = source.get("url") if isinstance(source, dict) else None
        if not isinstance(url, str):
            raise shape(f"プラグイン {plugin_name} に source.url が無い")
        key = source_key(url)
        if key is None or key[0] != GITHUB_HOST:
            raise PluginsError(f"{what} のプラグイン {plugin_name} の source.url ({url}) を、github.com のリポジトリの URL として読めない",
                               "source.url を https://github.com/<所有者>/<リポジトリ> の形にする")
        keys.add(key)
    if len(keys) != 1:
        found = ", ".join(format_source(k) for k in sorted(keys)) or "無い"
        raise PluginsError(f"{what} の各プラグインの source.url が、1 つの配布元を指していない (配布元: {found})",
                           "すべてのプラグインの source.url を、同じ GitHub のリポジトリにする")
    return {"name": name, "source": keys.pop(), "plugins": plugins}


def read_local_marketplace(root):
    """作業ツリーの .claude-plugin/marketplace.json から、マーケットプレイスの名前と配布元を読む (KTD4 の 1)。"""
    path = os.path.join(root, MARKETPLACE_RELPATH)
    what = f"作業ツリーの {MARKETPLACE_RELPATH}"
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as e:
        raise PluginsError(f"{what} を読めない ({path}): {e}",
                           "リポジトリのルートに .claude-plugin/marketplace.json があることを確認する。"
                           "ルートは、このスクリプトの実体の位置から決めている") from None
    try:
        data = json.loads(text)
    except ValueError as e:
        raise PluginsError(f"{what} を JSON として読めない: {e}", "marketplace.json を JSON として正しい形に直す") from None
    return parse_marketplace(data, what)


# ---- claude の出力の検査 (KTD7) ----

def _shape_error(what, detail):
    return PluginsError(f"{what} の形が想定と違う: {detail}", CLI_SHAPE_FIX)


def _parse_output_json(text, what):
    try:
        return json.loads(text)
    except ValueError as e:
        raise PluginsError(f"{what} を JSON として読めない: {e}", CLI_SHAPE_FIX) from None


def parse_marketplace_list(text):
    """claude plugin marketplace list --json の出力 text を検査して、要素の配列を返す。

    配列で、各要素が文字列の name と source を持つこと。ほかのキーは、ここでは検査しない。
    """
    what = "claude plugin marketplace list --json の出力"
    data = _parse_output_json(text, what)
    if not isinstance(data, list):
        raise _shape_error(what, "配列でない")
    for i, element in enumerate(data):
        if not isinstance(element, dict) or not isinstance(element.get("name"), str) \
                or not isinstance(element.get("source"), str):
            raise _shape_error(what, f"{i + 1} 番目の要素に、文字列の name か source が無い")
    return data


def parse_plugin_list(text, marketplace):
    """claude plugin list --json の出力 text を検査して、マーケットプレイス marketplace のプラグインの要素を、出力の順に返す。

    すべての要素に id があること。ほかのキーは、id の末尾が @<marketplace> である要素 (このリポジトリのプラグイン) だけを検査する。
    その要素に scope (user・project・local のどれか)・version・installPath があり、user スコープの要素に真偽値の enabled があり、
    project / local スコープの要素に projectPath があること。ほかの要素と、知らないキーは検査しない。
    成り立たなければ PluginsError を投げ、0 件として扱わない。

    返す要素のキー: name (id の @ の前)・scope・version・installPath・enabled (user スコープのときだけ真偽値で、ほかは None)・
    projectPath (project / local スコープのときだけ文字列で、ほかは None)。
    """
    what = "claude plugin list --json の出力"
    data = _parse_output_json(text, what)
    if not isinstance(data, list):
        raise _shape_error(what, "配列でない")
    suffix = "@" + marketplace
    result = []
    for i, element in enumerate(data):
        if not isinstance(element, dict) or not isinstance(element.get("id"), str):
            raise _shape_error(what, f"{i + 1} 番目の要素に id が無い")
        plugin_id = element["id"]
        if not plugin_id.endswith(suffix):
            continue
        for key in ("scope", "version", "installPath"):
            if not isinstance(element.get(key), str):
                raise _shape_error(what, f"要素 {plugin_id} に、文字列の {key} が無い")
        scope = element["scope"]
        if scope not in SCOPES:
            raise _shape_error(what, f"要素 {plugin_id} のスコープ ({scope}) が user・project・local のどれでもない")
        enabled = None
        project_path = None
        if scope == "user":
            enabled = element.get("enabled")
            if not isinstance(enabled, bool):
                raise _shape_error(what, f"user スコープの要素 {plugin_id} に、真偽値の enabled が無い")
        else:
            project_path = element.get("projectPath")
            if not isinstance(project_path, str):
                raise _shape_error(what, f"{scope} スコープの要素 {plugin_id} に、文字列の projectPath が無い")
        result.append({"name": plugin_id[:-len(suffix)], "scope": scope, "version": element["version"],
                       "installPath": element["installPath"], "enabled": enabled, "projectPath": project_path})
    return result


# ---- 前提の検査と読み取り ----

def check_registration(local):
    """マーケットプレイスが登録されていて、その取得元が配布元であることを検査する (R4・R5)。登録はしない。"""
    name = local["name"]
    expected = local["source"]
    add = f"claude plugin marketplace add {expected[1]}/{expected[2]}"
    what = "claude plugin marketplace list --json の出力"
    listed = parse_marketplace_list(run_claude(["plugin", "marketplace", "list", "--json"], READ_TIMEOUT))
    matches = [m for m in listed if m["name"] == name]
    if not matches:
        raise PluginsError(f"マーケットプレイス {name} が登録されていない。登録は利用者の環境に設定を足す操作なので、"
                           "このスクリプトでは行わない",
                           f"次のコマンドで登録してから、もう一度実行する: {add}")
    fix = (f"マーケットプレイス {name} を、配布元から登録したものにする (登録のコマンドは {add})。fork や手元のディレクトリから"
           "登録していると、インストールの取得元が配布元の main でなくなる")
    for m in matches:
        if m["source"] not in ("github", "git"):
            raise PluginsError(f"マーケットプレイス {name} の取得元の種類 (source が {m['source']}) が github でも git でもないので、"
                               f"取得元を配布元 ({format_source(expected)}) と比べられない", fix)
        key = "repo" if m["source"] == "github" else "url"
        value = m.get(key)
        if not isinstance(value, str):
            raise _shape_error(what, f"マーケットプレイス {name} の要素に、文字列の {key} が無い")
        url = "https://github.com/" + value if key == "repo" else value
        if source_key(url) != expected:
            raise PluginsError(f"マーケットプレイス {name} の取得元 ({value}) が、配布元 ({format_source(expected)}) でない", fix)


def check_origin(root, local):
    """remote origin の URL (書き換える前の設定値) が配布元を指すことを検査する (R6)。"""
    expected = local["source"]
    fix = (f"remote origin を配布元 ({format_source(expected)}) にした clone で実行する。URL は scp 形式・ssh://・https://・"
           "git:// のどれかで、ホストを github.com と書く (SSH の設定の Host の別名は解決しない)")
    try:
        url = run_git(root, ["config", "--get", "remote.origin.url"]).rstrip("\n")
    except CommandError as e:
        if e.returncode == 1:
            raise PluginsError(f"リポジトリ {root} に remote origin が無い (git config --get remote.origin.url が値を返さない)",
                               fix) from None
        raise
    if source_key(url) != expected:
        raise PluginsError(f"remote origin の URL ({url}) が、配布元 ({format_source(expected)}) を指していない。"
                           "最新の版を読む origin/main が、配布元の main でなくなる", fix)


def fetch_main(root):
    """git fetch で origin の main だけを取得し、取得した直後の origin/main の SHA を返す (R7・KTD5 の 1)。"""
    try:
        run_git(root, ["fetch", "--quiet", "--no-tags", "origin", "+refs/heads/main:refs/remotes/origin/main"], FETCH_TIMEOUT)
    except CommandError as e:
        raise PluginsError(f"git fetch で origin の main を取得できない。手元にある古い origin/main は使わない ({e.message})",
                           "ネットワークと、GitHub への接続 (認証を含む) を確認してから、もう一度実行する", e.detail) from None
    return run_git(root, ["rev-parse", "--verify", "refs/remotes/origin/main^{commit}"]).strip()


def read_blob(root, sha, relpath):
    """コミット sha にあるファイル relpath (ルートからの相対パス) の中身を返す。そのコミットに無ければ None を返す。"""
    listed = run_git(root, ["ls-tree", "-z", sha, "--", relpath])
    for entry in listed.split("\0"):
        meta, _, path = entry.partition("\t")
        if path == relpath and meta.split(" ")[1:2] == ["blob"]:
            return run_git(root, ["cat-file", "blob", f"{sha}:{relpath}"])
    return None


def plugin_json_path(source_path):
    """source.path から、ルートからの plugin.json の相対パスを作る。リポジトリの中を指す相対パスでなければ None を返す。"""
    if not isinstance(source_path, str) or not source_path or source_path.startswith("/"):
        return None
    relpath = posixpath.normpath(posixpath.join(source_path, ".claude-plugin", "plugin.json"))
    if relpath.startswith("../"):
        return None
    return relpath


def read_published(root, sha, local, names):
    """コミット sha の marketplace.json と、対象のプラグインの plugin.json を読み、対象のプラグインの配列を返す (KTD4 の 4・KTD5)。

    names は対象にする名前の配列 (None ならすべて)。要素のキー: name・path (source.path)・latest (最新の版)・
    installed (インストール済みの要素の配列。ここでは空で、関数 attach_installed が足す)。順序は marketplace.json の順。
    """
    short = sha[:12]
    what = f"origin/main ({short}) の {MARKETPLACE_RELPATH}"
    text = read_blob(root, sha, MARKETPLACE_RELPATH)
    if text is None:
        raise PluginsError(f"origin/main ({short}) に {MARKETPLACE_RELPATH} が無い",
                           "remote origin が配布元を指していることと、配布元の main の構成を確認する")
    try:
        data = json.loads(text)
    except ValueError as e:
        raise PluginsError(f"{what} を JSON として読めない: {e}", "配布元の main の marketplace.json を直す") from None
    published = parse_marketplace(data, what)
    fix_merge = "作業中のブランチでマーケットプレイスの名前か配布元を変えたなら、main にマージしてから実行する"
    if published["name"] != local["name"]:
        raise PluginsError(f"{what} のマーケットプレイスの名前 ({published['name']}) が、作業ツリーのもの ({local['name']}) と違う",
                           fix_merge)
    if published["source"] != local["source"]:
        raise PluginsError(f"{what} の配布元 ({format_source(published['source'])}) が、"
                           f"作業ツリーのもの ({format_source(local['source'])}) と違う", fix_merge)
    entries = []
    for plugin in published["plugins"]:
        plugin_name = plugin["name"]
        source = plugin["source"]
        if source.get("source") != "git-subdir":
            raise PluginsError(f"{what} のプラグイン {plugin_name} の source.source ({source.get('source')!r}) が git-subdir でない",
                               "このスクリプトは、source が git-subdir のプラグインだけを扱う")
        if source.get("ref") != "main":
            raise PluginsError(f"{what} のプラグイン {plugin_name} の source.ref ({source.get('ref')!r}) が main でない",
                               "インストールの取得元は配布元の main だけにする。source.ref を main にする")
        relpath = plugin_json_path(source.get("path"))
        if relpath is None:
            raise PluginsError(f"{what} のプラグイン {plugin_name} の source.path ({source.get('path')!r}) が、"
                               "リポジトリの中のディレクトリを指す相対パスでない",
                               "source.path を、リポジトリのルートからの相対パスにする")
        entries.append({"name": plugin_name, "path": source["path"], "relpath": relpath})

    known = [e["name"] for e in entries]
    if names is not None:
        unknown = [n for n in names if n not in known]
        if unknown:
            shown = "、".join("「" + n + "」" for n in unknown)
            raise PluginsError(f"{what} に載っていない名前がある: {shown}",
                               "載っている名前から選ぶ: " + ", ".join(known))
        entries = [e for e in entries if e["name"] in names]

    targets = []
    for e in entries:
        relpath = e["relpath"]
        text = read_blob(root, sha, relpath)
        if text is None:
            raise PluginsError(f"origin/main ({short}) に {relpath} が無い (プラグイン {e['name']} の source.path は {e['path']})",
                               "marketplace.json の source.path と、配布元の main のディレクトリの構成を確認する")
        try:
            data = json.loads(text)
        except ValueError as err:
            raise PluginsError(f"origin/main ({short}) の {relpath} を JSON として読めない: {err}",
                               "配布元の main の plugin.json を直す") from None
        if not isinstance(data, dict) or "version" not in data:
            raise PluginsError(f"origin/main ({short}) の {relpath} にキー version が無い", "plugin.json に version を書く")
        version = data["version"]
        if parse_version(version) is None:
            raise PluginsError(f"origin/main ({short}) の {relpath} の version ({version!r}) が X.Y.Z (3 つの 10 進の整数) の形でない",
                               "このスクリプトは X.Y.Z の形の版だけを扱う (pre-release などの付いた版は扱わない)。"
                               "plugin.json の version を X.Y.Z の形にする")
        targets.append({"name": e["name"], "path": e["path"], "latest": version, "installed": []})
    return targets


def attach_installed(targets, installed, marketplace):
    """関数 parse_plugin_list が返した要素 installed を、対象のプラグイン targets のキー installed に、出力の順に足す。

    対象のプラグインの要素の版が X.Y.Z の形でなければ PluginsError を投げる (KTD6)。対象でない要素は使わない。
    """
    by_name = {t["name"]: t for t in targets}
    for element in installed:
        target = by_name.get(element["name"])
        if target is None:
            continue
        if parse_version(element["version"]) is None:
            raise PluginsError(f"インストール済みの {element['name']}@{marketplace} ({element['scope']} スコープ) の版 "
                               f"({element['version']!r}) が X.Y.Z (3 つの 10 進の整数) の形でない",
                               "claude plugin list でそのプラグインの版を確認する。このスクリプトは X.Y.Z の形の版だけを扱う")
        target["installed"].append(element)


def prepare(root, names):
    """前提の検査と読み取りを、モジュールの docstring の順に行い、読み取りの結果を返す。成り立たなければ PluginsError を投げる。

    root はリポジトリのルート、names は対象にする名前の配列 (None ならすべて。空の要素の検査は関数 parse_names が行う)。
    変える操作は実行しない。結果のキー: marketplace (マーケットプレイスの名前)・source (配布元を表示する形)・sha (読んだ
    origin/main の SHA)・plugins (対象のプラグインの配列。要素の形は関数 read_published と attach_installed)。
    """
    local = read_local_marketplace(root)
    check_registration(local)
    check_origin(root, local)
    sha = fetch_main(root)
    targets = read_published(root, sha, local, names)
    installed = parse_plugin_list(run_claude(["plugin", "list", "--json"], READ_TIMEOUT), local["name"])
    attach_installed(targets, installed, local["name"])
    return {"marketplace": local["name"], "source": format_source(local["source"]), "sha": sha, "plugins": targets}


# ---- 状況の表示 ----

def display_width(text):
    """端末での表示の幅を返す。全角の文字 (East Asian Width が W か F) を 2、ほかを 1 と数える。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def pad(text, width):
    """text の後ろに空白を足して、表示の幅を width にそろえる。"""
    return text + " " * max(width - display_width(text), 0)


def scope_rows(plugin):
    """対象のプラグイン plugin の、スコープごとの行の元にする (スコープ, インストール済みの要素) の配列を返す。

    user スコープを先にし、project / local スコープを後に並べる (同じスコープの中は claude plugin list --json の出力の順)。
    user スコープにインストールされていなければ、先頭を ("user", None) にする。
    """
    entries = sorted(plugin["installed"], key=lambda e: SCOPES.index(e["scope"]))
    rows = [(e["scope"], e) for e in entries]
    if not any(e["scope"] == "user" for e in entries):
        rows.insert(0, ("user", None))
    return rows


def status_lines(snapshot):
    """関数 prepare の結果 snapshot から、状況の表示の行の配列を作る (R9〜R11・R21)。"""
    marketplace = snapshot["marketplace"]
    plugins = snapshot["plugins"]
    rows = {p["name"]: scope_rows(p) for p in plugins}
    entries = [e for p in plugins for _, e in rows[p["name"]] if e is not None]
    name_width = max([display_width(p["name"]) for p in plugins] + [0])
    scope_width = max(display_width(s) for s in SCOPES)
    version_width = max([display_width(e["version"]) for e in entries] + [0])
    label_width = max(display_width(label) for label in COMPARISON_LABELS.values())

    lines = [
        f"マーケットプレイス {marketplace} のプラグインのインストール状況",
        f"最新の版は、origin/main (コミット {snapshot['sha'][:12]}) にある plugin.json の版。",
        "各スコープの行には、インストール済みの版と、最新の版と比べた結果 (同じ・古い・新しい) を示す。",
        "user スコープの行には有効か無効か (user スコープの設定の値) を、project / local スコープの行にはプロジェクトのパスを示す。",
        "",
    ]
    older, missing, disabled = [], [], []
    for p in plugins:
        lines.append(f"{pad(p['name'], name_width)}  最新の版 {p['latest']}")
        for scope, e in rows[p["name"]]:
            head = "  " + pad(scope, scope_width) + "  "
            if e is None:
                lines.append(head + "インストールされていない")
                missing.append(p["name"])
                continue
            comparison = compare_versions(e["version"], p["latest"])
            if scope == "user":
                note = "有効" if e["enabled"] else "無効"
                if comparison == "older" and p["name"] not in older:
                    older.append(p["name"])
                if not e["enabled"] and p["name"] not in disabled:
                    disabled.append(p["name"])
            else:
                note = e["projectPath"]
            lines.append(head + pad(e["version"], version_width) + "  "
                         + pad(COMPARISON_LABELS[comparison], label_width) + "  " + note)

    lines.append("")
    for label, names in (("user スコープの版が最新の版より古いもの", older),
                         ("user スコープにインストールされていないもの", missing),
                         ("user スコープで無効なもの", disabled)):
        lines.append(f"{label}: {', '.join(names) if names else 'なし'}")
    lines.append("")
    lines.extend(AUTO_UPDATE_NOTE.format(marketplace=marketplace).splitlines())
    return lines


# ---- インストール ----

class InstallAborted(Exception):
    """変える操作の途中で中止したことを表す。message・fix・detail の意味は、クラス PluginsError と同じ。"""

    def __init__(self, message, fix=None, detail=None):
        super().__init__(message)
        self.message = message
        self.fix = fix
        self.detail = detail


class InstallProgress:
    """インストールの進み具合。中止・中断したときに、何を変えたかを表示するために使う。

    targets は、インストールする対象のプラグインの配列 (関数 prepare の結果の plugins の要素。marketplace.json の順)。
    """

    def __init__(self, marketplace, targets):
        self.marketplace = marketplace
        self.targets = targets
        # マーケットプレイスの定義を取得し直している間は真
        self.updating = False
        # 処理を始めた対象の数。targets[started:] が、処理しなかったもの
        self.started = 0
        # 処理中の対象 (targets の要素)。最新の版でインストールしたことを確認したら None に戻す
        self.current = None
        # 最新の版でインストールしたもの。要素は (対象, 再度読み込んだ user スコープの要素)
        self.installed = []
        # 中止・中断したときの、処理中だった対象の状態 (関数 reread_outcome の値と同じ形)
        self.outcome = None

    def remaining(self):
        return [t["name"] for t in self.targets[self.started:]]

    def current_is_installed(self):
        return any(t is self.current for t, _ in self.installed)


def find_user_element(listed, name):
    """関数 parse_plugin_list が返した要素 listed から、プラグイン name の user スコープの要素を返す。無ければ None を返す。"""
    for element in listed:
        if element["name"] == name and element["scope"] == "user":
            return element
    return None


def is_latest(element, target):
    """user スコープの要素 element の版が、対象 target の最新の版と同じなら真を返す。element が None なら偽を返す。"""
    return element is not None and parse_version(element["version"]) == parse_version(target["latest"])


def reread_user_element(marketplace, name):
    """claude plugin list --json を再度読み込み、プラグイン name の user スコープの要素を返す。無ければ None を返す。

    読み込みが失敗したとき (コマンドの失敗・出力の形の誤り) は PluginsError を投げる。
    """
    listed = parse_plugin_list(run_claude(["plugin", "list", "--json"], READ_TIMEOUT), marketplace)
    return find_user_element(listed, name)


def reread_outcome(marketplace, target):
    """インストールが失敗した後に claude plugin list --json を再度読み込み、対象 target の状態を返す (R15・KTD8)。

    返す値のキー: known (読み込めたら真)・element (user スコープの要素。無ければ None)・reason (読み込めなかった理由)。
    """
    try:
        return {"known": True, "element": reread_user_element(marketplace, target["name"]), "reason": None}
    except PluginsError as e:
        return {"known": False, "element": None, "reason": e.message}


def _progress(text):
    """インストールの進み具合を標準出力に表示する。パイプに出力しているときも、すぐに表示されるよう flush する。"""
    print(text, flush=True)


def install_targets(progress):
    """マーケットプレイスの定義を取得し直してから、対象を 1 つずつインストールする (R13・R15・R16・KTD8)。

    中止するときは InstallAborted を投げる。進み具合は progress に書く。Ctrl-C の KeyboardInterrupt は捕まえない。
    """
    marketplace = progress.marketplace
    update = ["plugin", "marketplace", "update", marketplace]
    progress.updating = True
    _progress(f"マーケットプレイス {marketplace} の定義を取得し直す (claude {' '.join(update)})")
    try:
        run_claude(update, CHANGE_TIMEOUT)
    except CommandError as e:
        raise InstallAborted(f"マーケットプレイス {marketplace} の定義の取得し直しが失敗したので、中止した ({e.message})",
                             e.fix, e.detail) from None
    progress.updating = False

    for target in progress.targets:
        name = target["name"]
        latest = target["latest"]
        progress.current = target
        progress.started += 1
        _progress(f"{name} をインストールする (最新の版 {latest})")
        try:
            run_claude(["plugin", "install", f"{name}@{marketplace}", "--scope", "user", "--json"], CHANGE_TIMEOUT)
        except CommandError as e:
            outcome = reread_outcome(marketplace, target)
            if outcome["known"] and is_latest(outcome["element"], target):
                progress.installed.append((target, outcome["element"]))
            progress.outcome = outcome
            raise InstallAborted(f"プラグイン {name} のインストールが失敗したので、中止した ({e.message})",
                                 e.fix, e.detail) from None
        try:
            element = reread_user_element(marketplace, name)
        except PluginsError as e:
            progress.outcome = {"known": False, "element": None, "reason": e.message}
            raise InstallAborted(f"プラグイン {name} のインストールの後、claude plugin list --json を再度読み込めなかったので、"
                                 f"中止した ({e.message})", e.fix, e.detail) from None
        if not is_latest(element, target):
            progress.outcome = {"known": True, "element": element, "reason": None}
            if element is None:
                actual = "user スコープにインストールされていない"
                fix = (f"{STATUS_HINT}。インストールされていなければ、claude plugin install {name}@{marketplace} --scope user を"
                       "手で実行して、出力を確認する")
            else:
                actual = f"user スコープの版は {element['version']}"
                fix = (f"{STATUS_HINT}。git fetch の後に配布元の main が更新されると、最新の版と違う版がインストールされて、"
                       "このエラーになることがある")
            raise InstallAborted(f"プラグイン {name} のインストールは成功を返したが、user スコープの版が最新の版 {latest} に"
                                 f"ならなかったので、中止した (再度読み込んだ結果: {actual})", fix)
        progress.installed.append((target, element))
        progress.current = None
        _progress(f"{name} {element['version']} を user スコープにインストールした")


def outcome_line(progress):
    """中止・中断したときの、処理中だったものの状態を示す行を返す (R15・R17・KTD8)。"""
    if progress.updating:
        return f"処理中だったもの: マーケットプレイス {progress.marketplace} の定義の取得し直し"
    target = progress.current
    if target is None:
        return "処理中だったもの: なし"
    name = target["name"]
    outcome = progress.outcome
    if outcome is None or not outcome["known"]:
        reason = f" (claude plugin list --json を再度読み込めなかった: {outcome['reason']})" if outcome else ""
        return f"処理中だったもの: {name} は、版が変わったか分からない{reason}。{STATUS_HINT}"
    element = outcome["element"]
    if element is None:
        return f"処理中だったもの: {name} は、user スコープにインストールされていない (再度読み込んだ結果)"
    if is_latest(element, target):
        return f"処理中だったもの: {name} は、user スコープに最新の版 {element['version']} でインストールされている (再度読み込んだ結果)"
    return (f"処理中だったもの: {name} は、user スコープの版が {element['version']} で、最新の版 {target['latest']} と違う"
            " (再度読み込んだ結果)")


def after_install_notes(progress):
    """実行の後の案内 (R18) の行を返す。案内が要らなければ、空の配列を返す。

    インストールしたものか、版が変わったか分からないものか、再度読み込んで user スコープにあった処理中のものがあれば、
    再起動が要ることを示す。そのうち wording-guard があれば、再度読み込んだ展開先で、textlint を入れるコマンドを示す。
    """
    changed = {}
    for target, element in progress.installed:
        changed[target["name"]] = element
    outcome = progress.outcome
    if outcome is not None and outcome["element"] is not None:
        changed[progress.current["name"]] = outcome["element"]
    unknown = progress.current is not None and (outcome is None or not outcome["known"])
    if not changed and not unknown:
        return []
    lines = ["", RESTART_NOTE]
    element = changed.get(WORDING_GUARD)
    if element is not None:
        command = shlex.quote(os.path.join(element["installPath"], WORDING_LINT_RELPATH))
        lines.extend([WORDING_LINT_NOTE, f"  python3 {command} setup"])
    return lines


def install_report_lines(progress, aborted):
    """インストールしたものの一覧と、実行の後の案内の行を返す。aborted が真なら、処理中だったものと処理しなかったものも含める。"""
    installed = ", ".join(f"{t['name']} {e['version']}" for t, e in progress.installed) or "なし"
    lines = ["", f"インストールしたもの (user スコープ): {installed}"]
    if aborted:
        lines.append(outcome_line(progress))
        lines.append(f"処理しなかったもの: {', '.join(progress.remaining()) or 'なし'}")
    lines.extend(after_install_notes(progress))
    return lines


def report_install_stop(progress, message, fix=None, detail=None):
    """中止・中断したときに、インストールしたもの・処理中だったものの状態・処理しなかったもの・案内を書いてから、
    エラーの文を書く (KTD8)。どれも標準エラー出力に書く。
    """
    sys.stdout.flush()
    for line in install_report_lines(progress, aborted=True):
        print(line, file=sys.stderr)
    print("", file=sys.stderr)
    _print(message)
    if detail:
        for line in detail.splitlines():
            print("  " + line, file=sys.stderr)
    if fix:
        _print(f"直し方: {fix}")


# ---- サブコマンド ----

def cmd_status(snapshot):
    """状況を標準出力に表示する。何も変えず、古いものがあっても終了コード 0 で終了する (R12・KD18)。"""
    print("\n".join(status_lines(snapshot)))
    return EXIT_OK


def cmd_install(snapshot):
    """user スコープにインストールされていない対象を、user スコープにインストールする (R13・R15〜R18・KTD8・KTD9)。"""
    marketplace = snapshot["marketplace"]
    plugins = snapshot["plugins"]
    present = [p["name"] for p in plugins if any(e["scope"] == "user" for e in p["installed"])]
    targets = [p for p in plugins if p["name"] not in present]
    if present:
        _progress(f"user スコープにインストール済みのもの (版が古くても扱わない): {', '.join(present)}")
    if not targets:
        _progress(f"user スコープにインストールするものが無いので、{NOTHING_CHANGED} (マーケットプレイスの定義も取得し直していない)。")
        return EXIT_OK

    progress = InstallProgress(marketplace, targets)
    try:
        _progress(f"user スコープにインストールするもの: {', '.join(t['name'] for t in targets)}")
        install_targets(progress)
    except InstallAborted as e:
        report_install_stop(progress, e.message, e.fix, e.detail)
        _print("変える操作の途中で中止したので、一部が変わっている可能性がある。変えたものは、"
               "インストールしたものと処理中だったものの行に示した。")
        return EXIT_ABORTED
    except KeyboardInterrupt:
        # 最新の版でインストールしたことを確認した直後に中断したときは、処理中だったものは無いとして扱う
        if progress.outcome is None and progress.current_is_installed():
            progress.current = None
        report_install_stop(progress, "Ctrl-C で中断した。それ以上 claude のコマンドを実行していない。")
        _print(f"変える操作の途中で中断したので、一部が変わっている可能性がある。{STATUS_HINT}。")
        return EXIT_INTERRUPTED
    for line in install_report_lines(progress, aborted=False):
        print(line)
    return EXIT_OK


def _print(text):
    print(f"{PROG}: {text}", file=sys.stderr)


def report_precondition_error(message, fix=None, detail=None):
    """前提の検査か読み取りのエラーを、直し方と、何も変えていないことを添えて標準エラー出力に書く。"""
    _print(message)
    if detail:
        for line in detail.splitlines():
            print("  " + line, file=sys.stderr)
    if fix:
        _print(f"直し方: {fix}")
    _print(f"{NOTHING_CHANGED}。前提の検査か読み取りでエラーになったので、変える操作の前に終了した。")


def build_parser():
    parser = argparse.ArgumentParser(prog=PROG, description="このリポジトリのプラグインのインストール状況の表示と、まとめてのインストール")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, func, help_text in (
            ("status", cmd_status, "対象のプラグインごとに、最新の版とインストール済みの版を表示する"),
            ("install", cmd_install, "対象のプラグインのうち、user スコープにインストールされていないものをインストールする")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--plugins", metavar="名前,名前...",
                       help="対象にするプラグインの名前 (カンマ区切り)。省略すると、origin/main の marketplace.json に載っているすべて")
        p.set_defaults(func=func)
    return parser


def main(argv=None):
    too_old = python_too_old()
    if too_old:
        report_precondition_error(too_old, "3.11 以上の python3 で実行する")
        return EXIT_PRECONDITION
    args = build_parser().parse_args(argv)
    try:
        snapshot = prepare(ROOT, parse_names(args.plugins))
    except PluginsError as e:
        report_precondition_error(e.message, e.fix, e.detail)
        return EXIT_PRECONDITION
    except KeyboardInterrupt:
        _print(f"Ctrl-C で中断した。前提の検査と読み取りの途中だったので、{NOTHING_CHANGED}。")
        return EXIT_INTERRUPTED
    return args.func(snapshot)


if __name__ == "__main__":
    sys.exit(main())
