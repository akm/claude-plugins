"""scripts/tests のテストの共通の準備。

名前が test_ で始まらないので、このファイル自体はテストとして集められない。クラス PluginTestCase を継承して使う。

- 偽の claude (scripts/tests/fake-claude) を PATH の先頭のディレクトリに claude の名前で置き、使う前に偽物であることを
  2 つの方法で確認する (関数 check_fake_claude)。本物の claude を実行しないため
- 二重の安全策として、HOME と CLAUDE_CONFIG_DIR を一時ディレクトリにする。HOME を変えると asdf などの python3 が
  起動しなくなるので、PATH の先頭のディレクトリの python3 を、テストを実行している python へのシンボリックリンクにする
- git のテストのために、配布元の代わりの bare リポジトリと、作業用のリポジトリを作る (メソッド make_repos)。
  作業用のリポジトリの remote.origin.url は GitHub の URL にし、git の設定 insteadOf で取得先を bare リポジトリに向ける。
  環境変数 GIT_ALLOW_PROTOCOL を file にするので、GitHub に接続しようとすれば git が失敗する

  python3 -m unittest discover -s scripts/tests
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.realpath(os.path.join(HERE, "..", ".."))
FAKE_CLAUDE = os.path.join(HERE, "fake-claude")
# 偽の claude がオプション --fake-claude-identity を受けたときに出力する文字列。ファイル scripts/tests/fake-claude の定数 IDENTITY と同じにする
FAKE_CLAUDE_IDENTITY = "fake-claude for akm/claude-plugins scripts/tests"
FIXTURE_PLUGIN_LIST = os.path.join(HERE, "fixtures", "plugin-list.json")

MARKETPLACE = "akm-claude-plugins"
# マーケットプレイスを akm/claude-plugins の形で登録したときに、plugin marketplace list --json の repo に入る値
MARKETPLACE_REPO = "akm/claude-plugins"
# marketplace.json の各プラグインの source.url
SOURCE_URL = "https://github.com/akm/claude-plugins"
# 作業用のリポジトリの remote.origin.url
ORIGIN_URL = SOURCE_URL + ".git"
# テストが実行するコマンド (偽の claude・git) の待機の上限 (秒)
TIMEOUT = 60


class FakeClaudeCheckError(AssertionError):
    """偽の claude の確認が失敗したことを表す。属性 check は、失敗した確認 ("path" か "identity")。"""

    def __init__(self, check, message):
        super().__init__(message)
        self.check = check


def check_fake_claude(env, fake=FAKE_CLAUDE, identity=FAKE_CLAUDE_IDENTITY):
    """環境変数 env で claude を実行すると偽の claude が動くことを、次の順に確認する。違えば FakeClaudeCheckError を投げる。

    1. env の PATH で claude を探し、見つかったファイルの実体のパスが fake の実体と同じであること
    2. env で `claude --fake-claude-identity` を実行し、identity と改行だけを出力して終了コード 0 で終えること

    1 つ目で違えば、見つかったファイルを実行しない。本物の claude は、知らない語をプロンプトとして受け取って会話を始める
    可能性があるため、2 つ目の確認だけで判別することはしない。
    """
    found = shutil.which("claude", path=env.get("PATH", ""))
    if found is None or os.path.realpath(found) != os.path.realpath(fake):
        raise FakeClaudeCheckError(
            "path", f"PATH で見つかる claude ({found}) が偽の claude ({fake}) でない。本物の claude を実行しないよう、ここでテストを失敗させる")
    with tempfile.TemporaryDirectory() as cwd:
        try:
            r = subprocess.run(["claude", "--fake-claude-identity"], env=env, cwd=cwd, stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            raise FakeClaudeCheckError("identity", f"claude --fake-claude-identity が {TIMEOUT} 秒で終了しない") from None
    if r.returncode != 0 or r.stdout != identity + "\n":
        raise FakeClaudeCheckError(
            "identity", f"claude --fake-claude-identity が決めた文字列を返さない (終了コード {r.returncode}、標準出力 {r.stdout!r})")


def default_sigint():
    """子のプロセスで、SIGINT の扱いをデフォルトに戻す。subprocess の引数 preexec_fn に渡す。

    Python は、SIGINT の扱いがデフォルトのときだけ KeyboardInterrupt にする。シェルのバックグラウンドのジョブなどでテストを
    実行すると、SIGINT を無視する設定を子のプロセスが受け継ぎ、偽の claude が送る SIGINT (Ctrl-C を模したもの) を
    受け取らない。Ctrl-C のテストで、そのような環境でも同じ結果になるようにする。
    """
    signal.signal(signal.SIGINT, signal.SIG_DFL)


def git_env(base):
    """base から GIT_ で始まる環境変数 (GIT_DIR など、git の実行先を変えるもの) を消し、テストの安全策の値を入れて返す。

    GIT_ALLOW_PROTOCOL=file で、手元のパス以外からの取得を git に拒否させる (GitHub に接続しない)。
    GIT_CONFIG_GLOBAL と GIT_CONFIG_NOSYSTEM で、利用者と system の git の設定を読まない。
    """
    env = {k: v for k, v in base.items() if not k.startswith("GIT_")}
    env.update({"GIT_ALLOW_PROTOCOL": "file", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"})
    return env


def git(path, *args, env=None, check=True):
    """git -C path を、関数 git_env で整えた環境変数 (env を省略したときは os.environ から作る) で実行する。

    check が真で終了コードが 0 以外なら、標準エラー出力を添えて AssertionError を投げる。
    """
    r = subprocess.run(["git", "-C", path, *args], env=git_env(os.environ if env is None else env),
                       stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=TIMEOUT)
    if check and r.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} が終了コード {r.returncode} で失敗した ({path}): {r.stderr}")
    return r


def dump_json(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def marketplace_json(names):
    """配布元の .claude-plugin/marketplace.json の中身を、プラグインの名前の配列 names の順で作る。"""
    return {
        "name": MARKETPLACE,
        "owner": {"name": "akm"},
        "plugins": [{"name": name, "source": {"source": "git-subdir", "url": SOURCE_URL, "path": name, "ref": "main"}}
                    for name in names],
    }


def plugin_json(name, version):
    """配布元の <プラグイン>/.claude-plugin/plugin.json の中身を作る。"""
    return {"name": name, "version": version}


def write_files(root, files):
    """files (root からの相対パス → 中身の文字列) を書く。中身が None のファイルは消す。"""
    for rel, content in files.items():
        path = os.path.join(root, rel)
        if content is None:
            os.remove(path)
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)


def make_source(root, plugins):
    """配布元の代わりの bare リポジトリ <root>/source.git と、そこへコミットを送る作業ツリー <root>/source-tree を作る。

    plugins は (名前, 版) の配列。marketplace.json に名前を渡した順に並べ、各プラグインの plugin.json に版を書いて、
    ブランチ main にコミットする。(作業ツリーのパス, bare リポジトリのパス) を返す。
    """
    tree = os.path.join(root, "source-tree")
    bare = os.path.join(root, "source.git")
    os.makedirs(tree)
    git(tree, "init", "-q", "-b", "main")
    files = {".claude-plugin/marketplace.json": dump_json(marketplace_json([name for name, _ in plugins]))}
    for name, version in plugins:
        files[f"{name}/.claude-plugin/plugin.json"] = dump_json(plugin_json(name, version))
    write_files(tree, files)
    git(tree, "add", "-A")
    git(tree, "commit", "-q", "-m", "配布元の最初のコミット")
    git(root, "clone", "-q", "--bare", tree, bare)
    git(tree, "remote", "add", "origin", bare)
    return tree, bare


def commit_source(tree, files, message):
    """配布元の作業ツリー tree で files (関数 write_files と同じ形) を書いてコミットし、bare リポジトリの main に送る。"""
    write_files(tree, files)
    git(tree, "add", "-A")
    git(tree, "commit", "-q", "-m", message)
    git(tree, "push", "-q", "origin", "main")


def make_work(root, bare, origin_url=ORIGIN_URL):
    """bare リポジトリを clone して、作業用のリポジトリ <root>/work を作り、そのパスを返す。

    remote.origin.url を origin_url にし、git の設定 url.<bare>.insteadOf で、origin_url からの取得を bare に向ける。
    """
    work = os.path.join(root, "work")
    git(root, "clone", "-q", bare, work)
    git(work, "remote", "set-url", "origin", origin_url)
    git(work, "config", f"url.{bare}.insteadOf", origin_url)
    return work


class PluginTestCase(unittest.TestCase):
    """偽の claude を PATH の先頭に置き、HOME と CLAUDE_CONFIG_DIR を一時ディレクトリにした環境変数 self.env を用意する。

    self.env を作った後に関数 check_fake_claude で偽物であることを確認し、違えばその場でテストを失敗させる。
    テストの中で self.bin の claude や self.env の PATH を変えたときは、偽の claude を使う前に、関数 check_fake_claude をもう一度実行する。
    確認の呼び出しは記録に残さない (記録のファイルを消してからテストを始める)。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = os.path.realpath(self._tmp.name)
        self.bin = os.path.join(self.root, "bin")
        os.makedirs(self.bin)
        os.symlink(os.path.realpath(FAKE_CLAUDE), os.path.join(self.bin, "claude"))
        os.symlink(sys.executable, os.path.join(self.bin, "python3"))
        self.home = os.path.join(self.root, "home")
        self.config_dir = os.path.join(self.root, "claude-config")
        os.makedirs(self.home)
        os.makedirs(self.config_dir)
        self.state_path = os.path.join(self.root, "fake-claude-state.json")
        self.record_path = os.path.join(self.root, "fake-claude-record.jsonl")
        # 前のテストや端末が残した FAKE_ で始まる変数は持ち込まない
        env = git_env({k: v for k, v in os.environ.items() if not k.startswith("FAKE_")})
        env.update({
            "PATH": self.bin + os.pathsep + env.get("PATH", ""),
            "HOME": self.home,
            "CLAUDE_CONFIG_DIR": self.config_dir,
            "FAKE_CLAUDE_STATE": self.state_path,
            "FAKE_CLAUDE_RECORD": self.record_path,
        })
        self.env = env
        self.write_state({})
        check_fake_claude(self.env)
        if os.path.exists(self.record_path):
            os.remove(self.record_path)

    # ---- 偽の claude ----

    def write_state(self, state):
        """偽の claude の状態のファイルを書く。state に無いキーは空にする (キーの意味は fake-claude の docstring)。"""
        full = {"marketplaces": [], "clone": {}, "published": {}, "installed": [], "faults": []}
        full.update(state)
        with open(self.state_path, "w", encoding="utf-8") as f:
            f.write(dump_json(full))

    def read_state(self):
        with open(self.state_path, encoding="utf-8") as f:
            return json.load(f)

    def read_record(self):
        """偽の claude の記録を、呼び出しの順に {"args": [...], "cwd": ...} の配列で返す。"""
        if not os.path.exists(self.record_path):
            return []
        with open(self.record_path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def run_claude(self, *args, cwd=None):
        """self.env で claude を実行する。cwd を省略したときは self.root で実行する。"""
        return subprocess.run(["claude", *args], env=self.env, cwd=cwd or self.root, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=TIMEOUT)

    # ---- git のリポジトリ ----

    def make_repos(self, plugins, origin_url=ORIGIN_URL):
        """配布元の代わりの bare リポジトリ (self.source) とその作業ツリー (self.source_tree)、作業用のリポジトリ (self.work) を作る。

        plugins は (名前, 版) の配列 (関数 make_source と同じ)。
        """
        self.source_tree, self.source = make_source(self.root, plugins)
        self.work = make_work(self.root, self.source, origin_url)

    def publish_version(self, name, version):
        """配布元にプラグイン name の新しい版 version をコミットし、偽の claude の状態の配布元の版も version にする。"""
        commit_source(self.source_tree, {f"{name}/.claude-plugin/plugin.json": dump_json(plugin_json(name, version))},
                      f"{name} を {version} にする")
        state = self.read_state()
        state["published"].setdefault(MARKETPLACE, {})[name] = version
        self.write_state(state)

    def copy_into_work(self, paths):
        """このリポジトリのファイル paths (ルートからの相対パスの配列) を、作業用のリポジトリの同じ相対パスにコピーする。

        スクリプトと Makefile をコピーして、コピーした先のリポジトリを読むことを確認するテストに使う。コミットはしない。
        """
        for rel in paths:
            dst = os.path.join(self.work, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(REPO_ROOT, rel), dst)
