#!/usr/bin/env python3
"""判定表と保護の一覧 (ファイル `disk-usage-triage/scripts/disk_usage_triage/judge.py`) のテスト。

計画 docs/plans/2026-11-22-1630-feat-disk-usage-triage-plan.md の U3 のテストシナリオ。保護の一覧は R14、判定表は KTD5、
保護の一覧の項目を含む親を選べないことは R12 と KTD5 にある。

  python3 -m unittest discover -s disk-usage-triage/tests
"""

import json
import os
import stat
import tempfile
import unittest
from unittest import mock

from triage_case import TriageCase

from disk_usage_triage import commands, judge  # noqa: E402

PYTHON_VERSION = "3.13.3"


class FakeClock:
    """呼ぶたびに step 秒進む時計。探索が時間の上限を超えたときの振る舞いを、実際の時間を使わずに確認するため。"""

    def __init__(self, step):
        self.now = 0.0
        self.step = step

    def __call__(self):
        value = self.now
        self.now += self.step
        return value


class JudgeCase(TriageCase):
    """利用者のホームディレクトリ (環境変数 HOME) の下に、保護の一覧の場所と作業ディレクトリを作る。"""

    def setUp(self):
        super().setUp()
        self.docker = self.make_dir("user-home", "Library", "Containers", "com.docker.docker")
        raw_dir = self.make_dir("user-home", "Library", "Containers", "com.docker.docker", "Data", "vms", "0", "data")
        self.docker_raw = os.path.join(raw_dir, "Docker.raw")
        with open(self.docker_raw, "w", encoding="utf-8"):
            pass
        self.claude_desktop = self.make_dir("user-home", "Library", "Application Support", "Claude")
        self.claude = self.make_dir("user-home", ".claude")
        self.icloud = self.make_dir("user-home", "Library", "Mobile Documents")
        self.cloud_storage = self.make_dir("user-home", "Library", "CloudStorage")
        self.caches = self.make_dir("user-home", "Library", "Caches")
        self.workspace = self.make_dir("user-home", "workspace")
        self.repo = self.make_dir("user-home", "workspace", "org", "repo")
        self.app_worktree = self.make_dir("user-home", "workspace", "org", "repo", ".claude", "worktrees", "feature")
        self.cwd = self.make_dir("user-home", "workspace", "org", "repo", "src")
        saved_cwd = os.getcwd()
        self.addCleanup(os.chdir, saved_cwd)
        os.chdir(self.cwd)
        saved_asdf = os.environ.pop("ASDF_DATA_DIR", None)
        if saved_asdf is not None:
            self.addCleanup(os.environ.__setitem__, "ASDF_DATA_DIR", saved_asdf)
        else:
            self.addCleanup(os.environ.pop, "ASDF_DATA_DIR", None)

    def environment(self, scan_dirs=("~/Library/Caches",), executable="/usr/bin/python3"):
        with mock.patch.object(judge.sys, "executable", executable):
            return judge.environment({"scan_dirs": list(scan_dirs)})

    def make_python(self, data_dir):
        """asdf のデータの場所 data_dir の下に、Python の版のディレクトリと実行ファイルを作り、実行ファイルのパスを返す。"""
        bin_dir = os.path.join(data_dir, "installs", "python", PYTHON_VERSION, "bin")
        os.makedirs(bin_dir, exist_ok=True)
        executable = os.path.join(bin_dir, "python3")
        with open(executable, "w", encoding="utf-8"):
            pass
        return executable


class ProtectionTest(JudgeCase):
    """R14 の場所のそれぞれが「残す」で、保護の一覧からの判定であること。"""

    def assert_protected(self, path, kind, env=None):
        env = env or self.environment()
        result = judge.judge(path, env, [])
        self.assertEqual(result["judgment"], "keep", path)
        self.assertEqual(result["source"], "protected", path)
        self.assertEqual(result["protection"]["kind"], kind, path)
        self.assertIn(result["protection"]["label"], result["reason"])
        self.assertIsNone(result["command"], "保護の一覧の項目には、消すコマンドを付けないこと")
        return result

    def assert_not_protected(self, path, env=None):
        env = env or self.environment()
        self.assertIsNone(judge.protection(path, env), path)

    def test_fixed_locations(self):
        self.assert_protected(self.docker, "docker")
        self.assert_protected(self.claude_desktop, "claude-desktop")
        self.assert_protected(self.claude, "claude")
        self.assert_protected(self.icloud, "icloud")
        self.assert_protected(self.cloud_storage, "cloud-storage")

    def test_docker_raw(self):
        result = self.assert_protected(self.docker_raw, "docker-raw")
        self.assertEqual(result["protection"]["path"], self.docker_raw)

    def test_below_fixed_locations(self):
        """決まった場所の下の階層も保護する (下の階層を消すと、その場所を使うアプリが壊れるか、クラウドから消えるため)。"""
        for top, kind in ((self.docker, "docker"), (self.claude, "claude"), (self.icloud, "icloud"),
                          (self.cloud_storage, "cloud-storage"), (self.claude_desktop, "claude-desktop")):
            with self.subTest(kind=kind):
                below = os.path.join(top, "below")
                os.makedirs(below)
                self.assert_protected(below, kind)

    def test_working_directory_and_its_parents(self):
        """作業ディレクトリ (os.getcwd) とその親は保護し、作業ディレクトリの下は保護しない。"""
        self.assert_protected(self.cwd, "cwd")
        for parent in (self.repo, os.path.dirname(self.repo), self.workspace, self.root):
            with self.subTest(parent=parent):
                self.assert_protected(parent, "cwd-parent")
        below = self.make_dir("user-home", "workspace", "org", "repo", "src", "build")
        self.assert_not_protected(below)

    def test_working_directory_follows_chdir(self):
        other = self.make_dir("user-home", "other-project")
        self.assert_not_protected(other)
        os.chdir(other)
        self.assert_protected(other, "cwd")
        self.assert_not_protected(self.cwd)

    def test_app_worktree_and_its_parent(self):
        """アプリの worktree (.claude/worktrees/ の下) とその下は保護する。親の .claude/worktrees も保護する。"""
        self.assert_protected(self.app_worktree, "app-worktree")
        node_modules = self.make_dir("user-home", "workspace", "org", "repo", ".claude", "worktrees", "feature",
                                     "node_modules")
        self.assert_protected(node_modules, "app-worktree")
        self.assert_protected(os.path.dirname(self.app_worktree), "app-worktree-parent")

    def test_scan_dirs_and_home(self):
        """調べるディレクトリ (設定の scan_dirs) とホームディレクトリ (環境変数 HOME) は保護し、その下は保護しない。"""
        android = self.make_dir("user-home", ".android")
        env = self.environment(scan_dirs=("~/Library/Caches", "~/.android"))
        self.assert_protected(self.caches, "scan-dir", env)
        self.assert_protected(android, "scan-dir", env)
        self.assert_protected(self.user_home, "home", env)
        self.assert_not_protected(self.make_dir("user-home", "Library", "Caches", "go-build"), env)

    def test_home_follows_environment(self):
        other_home = self.make_dir("other-home")
        self.assert_not_protected(other_home)
        with mock.patch.dict(os.environ, {"HOME": other_home}):
            env = self.environment(scan_dirs=())
        self.assertEqual(judge.protection(other_home, env)["kind"], "home")
        self.assertEqual(judge.protection(os.path.join(other_home, ".claude"), env)["kind"], "claude",
                         "決まった場所も、環境変数 HOME のホームディレクトリの下に求めること")

    def test_symlink_to_protected_location(self):
        """シンボリックリンクを解決した先が保護の一覧の場所なら保護する。"""
        link = os.path.join(self.user_home, "claude-link")
        os.symlink(self.claude, link)
        self.assert_protected(link, "claude")

    def test_case_differs_on_case_insensitive_filesystem(self):
        """大文字と小文字を区別しないファイルシステム (macOS の標準) では、大文字と小文字だけが違う書き方も保護する。"""
        upper = os.path.join(self.user_home, "LIBRARY", "CONTAINERS", "COM.DOCKER.DOCKER", "Data")
        if not os.path.isdir(os.path.dirname(upper)):
            self.skipTest("大文字と小文字を区別するファイルシステム")
        os.makedirs(upper, exist_ok=True)
        self.assert_protected(upper, "docker")
        self.assert_protected(os.path.join(self.user_home, "LIBRARY", "CONTAINERS", "COM.DOCKER.DOCKER"), "docker")

    def test_other_directories_are_not_protected(self):
        for path in (self.make_dir("user-home", "Library", "Caches", "Google"),
                     self.make_dir("user-home", "Library", "Application Support", "Code"),
                     self.make_dir("user-home", ".claude-backup")):
            with self.subTest(path=path):
                self.assert_not_protected(path)

    def test_relative_path_is_a_programming_error(self):
        with self.assertRaises(ValueError):
            judge.protection("Library/Caches", self.environment())


class PythonVersionProtectionTest(JudgeCase):
    """プラグインを実行している Python の asdf の版 (計画の KTD10)。"""

    def test_asdf_python_version_is_protected(self):
        data_dir = os.path.join(self.user_home, ".asdf")
        env = self.environment(executable=self.make_python(data_dir))
        version_dir = os.path.join(data_dir, "installs", "python", PYTHON_VERSION)
        result = judge.judge(version_dir, env, [])
        self.assertEqual(result["judgment"], "keep")
        self.assertEqual(result["protection"]["kind"], "python")
        self.assertEqual(result["protection"]["path"], version_dir)
        self.assertEqual(judge.protection(os.path.join(version_dir, "lib"), env)["kind"], "python",
                         "版のディレクトリの下も保護すること")
        self.assertIsNone(judge.protection(os.path.join(data_dir, "installs", "python", "3.12.0"), env),
                          "ほかの版は保護しないこと")

    def test_asdf_data_dir_environment_variable(self):
        data_dir = self.make_dir("asdf-data")
        os.environ["ASDF_DATA_DIR"] = data_dir
        env = self.environment(executable=self.make_python(data_dir))
        version_dir = os.path.join(data_dir, "installs", "python", PYTHON_VERSION)
        self.assertEqual(judge.protection(version_dir, env)["kind"], "python")

    def test_python_outside_asdf_is_not_protected(self):
        data_dir = os.path.join(self.user_home, ".asdf")
        self.make_python(data_dir)
        version_dir = os.path.join(data_dir, "installs", "python", PYTHON_VERSION)
        env = self.environment(executable="/usr/bin/python3")
        self.assertIsNone(judge.protection(version_dir, env))
        self.assertNotIn("python", [location["kind"] for location in judge.locations(env)])

    def test_python_of_another_tool_is_not_protected(self):
        """asdf の installs の下でも、python 以外のツールの下なら版として扱わない。"""
        data_dir = os.path.join(self.user_home, ".asdf")
        bin_dir = os.path.join(data_dir, "installs", "nodejs", "22.0.0", "bin")
        os.makedirs(bin_dir)
        executable = os.path.join(bin_dir, "python3")
        with open(executable, "w", encoding="utf-8"):
            pass
        env = self.environment(executable=executable)
        self.assertNotIn("python", [location["kind"] for location in judge.locations(env)])


class SelectionTest(JudgeCase):
    """保護の一覧の項目と、それを含む親は、まとめて消す対象に選べない (R12・KD8・KTD5)。"""

    def blockers(self, path, timeout=60, clock=None):
        kwargs = {"clock": clock} if clock else {}
        return judge.selection_blockers(path, self.environment(), timeout=timeout, **kwargs)

    def test_ordinary_directory_is_selectable(self):
        self.assertEqual(self.blockers(self.make_dir("user-home", "Library", "Caches", "go-build", "00")), [])

    def test_protected_item_is_not_selectable(self):
        blockers = self.blockers(self.claude)
        self.assertEqual([b["kind"] for b in blockers], ["protected"])
        self.assertEqual(blockers[0]["path"], self.claude)
        self.assertTrue(blockers[0]["reason"])

    def test_parent_of_protected_location_is_not_selectable(self):
        containers = os.path.dirname(self.docker)
        blockers = self.blockers(containers)
        self.assertEqual([b["kind"] for b in blockers], ["contains-protected"])
        self.assertEqual(blockers[0]["path"], self.docker)
        self.assertIn(self.docker, blockers[0]["reason"])

    def test_parent_lists_the_outermost_locations(self):
        """含む場所のうち、ほかの含む場所の下にあるもの (Docker.raw は Docker Desktop のディレクトリの下) は挙げない。"""
        library = os.path.join(self.user_home, "Library")
        paths = [b["path"] for b in self.blockers(library)]
        for path in (self.docker, self.claude_desktop, self.icloud, self.cloud_storage, self.caches):
            self.assertIn(path, paths)
        self.assertNotIn(self.docker_raw, paths)

    def test_missing_location_does_not_block(self):
        """無い場所 (~/Library/CloudStorage が無いマシン) は、含む場所として挙げない。"""
        os.rmdir(self.cloud_storage)
        paths = [b["path"] for b in self.blockers(os.path.join(self.user_home, "Library"))]
        self.assertNotIn(self.cloud_storage, paths)
        self.assertIn(self.icloud, paths)

    def test_app_worktree_three_levels_below(self):
        """3 階層下 (<項目>/<組織>/<リポジトリ>/.claude/worktrees/) にアプリの worktree があれば選べない。"""
        projects = self.make_dir("user-home", "projects")
        worktrees = self.make_dir("user-home", "projects", "org", "repo", ".claude", "worktrees")
        self.make_dir("user-home", "projects", "org", "repo", ".claude", "worktrees", "a")
        blockers = self.blockers(projects)
        self.assertEqual([b["kind"] for b in blockers], ["app-worktree-below"])
        self.assertEqual(blockers[0]["path"], worktrees)

    def test_empty_worktrees_directory_also_blocks(self):
        """.claude/worktrees があれば、中が空でも選べない (アプリが新しいセッションのために作ることがあるため)。"""
        projects = self.make_dir("user-home", "projects")
        self.make_dir("user-home", "projects", "repo", ".claude", "worktrees")
        self.assertEqual([b["kind"] for b in self.blockers(projects)], ["app-worktree-below"])

    def test_git_and_node_modules_are_not_searched(self):
        projects = self.make_dir("user-home", "projects")
        self.make_dir("user-home", "projects", "repo", ".git", "x", ".claude", "worktrees")
        self.make_dir("user-home", "projects", "repo", "node_modules", "pkg", ".claude", "worktrees")
        self.assertEqual(self.blockers(projects), [])

    def test_claude_directory_without_worktrees_is_selectable(self):
        projects = self.make_dir("user-home", "projects")
        self.make_dir("user-home", "projects", "repo", ".claude", "commands")
        self.assertEqual(self.blockers(projects), [])

    def test_search_over_the_time_limit(self):
        """探すのが時間の上限を超えたディレクトリは選べない。"""
        projects = self.make_dir("user-home", "projects")
        for name in ("a", "b", "c"):
            self.make_dir("user-home", "projects", name)
        blockers = self.blockers(projects, timeout=10, clock=FakeClock(step=11))
        self.assertEqual([b["kind"] for b in blockers], ["timeout"])
        self.assertEqual(blockers[0]["path"], projects)
        self.assertIn("10", blockers[0]["reason"])

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root はどのディレクトリも読めるため")
    def test_unreadable_directory_below(self):
        """下に読めないディレクトリがあれば選べず、読めなかったディレクトリを理由に示す。"""
        projects = self.make_dir("user-home", "projects")
        locked = self.make_dir("user-home", "projects", "org", "locked")
        os.chmod(locked, 0)
        try:
            blockers = self.blockers(projects)
        finally:
            os.chmod(locked, stat.S_IRWXU)  # 一時ディレクトリを消せるように、tearDown の前に戻す
        self.assertEqual([b["kind"] for b in blockers], ["unreadable"])
        self.assertEqual(blockers[0]["path"], locked)
        self.assertIn(locked, blockers[0]["reason"])

    def test_symlink_is_not_followed(self):
        """シンボリックリンクの先は探さない (選んだ項目を消しても、リンクの先は消えないため)。"""
        projects = self.make_dir("user-home", "projects")
        os.symlink(self.repo, os.path.join(projects, "repo-link"))
        self.assertEqual(self.blockers(projects), [])


SOURCES = [{"url": "https://example.com/docs", "checked_on": "2026-11-25"}]


def row(pattern, judgment="review", **extra):
    """様式どおりの行。command を省くと、keep の行は null、それ以外の行は rm にする。"""
    data = {"pattern": pattern, "judgment": judgment, "reason": f"{pattern} の理由", "impact": f"{pattern} の影響",
            "command": None if judgment == "keep" else {"type": "rm"}, "sources": SOURCES}
    data.update(extra)
    return data


def tool(*args, env=None):
    command = {"type": "tool", "args": list(args)}
    if env is not None:
        command["env"] = env
    return command


class PatternTest(JudgeCase):
    """判定表のパターンの照合 (KTD5)。行は、パターンに一致したディレクトリと、その下の項目に使う (R13・R19 と同じ考え方)。"""

    def match(self, path, rows):
        return judge.match_table(path, rows, self.environment())

    def test_star_matches_exactly_one_level(self):
        rows = [row("~/*/Caches")]
        matched = self.match(self.caches, rows)
        self.assertEqual(matched["path"], self.caches)
        library_foo_caches = self.make_dir("user-home", "Library", "Foo", "Caches")
        self.assertIsNone(self.match(library_foo_caches, rows), "`*` は 2 つの階層には一致しないこと")
        self.assertIsNone(self.match(self.make_dir("user-home", "Caches"), rows), "`*` は 0 個の階層には一致しないこと")

    def test_row_applies_below_the_matched_directory(self):
        rows = [row("~/Library/Caches/go-build")]
        go_build = os.path.join(self.caches, "go-build")
        self.assertEqual(self.match(go_build, rows)["path"], go_build)
        below = os.path.join(go_build, "00")
        matched = self.match(below, rows)
        self.assertEqual(matched["path"], go_build, "一致したのは親のディレクトリであること")
        self.assertIsNone(self.match(self.caches, rows), "一致したディレクトリの親には使わないこと")
        self.assertIsNone(self.match(os.path.join(self.root, "Library", "Caches", "go-build"), rows),
                          "~ はホームディレクトリだけに一致すること")

    def test_more_levels_win(self):
        """項目とその親のディレクトリに一致する行が複数あれば、階層の多いパターンの行を使う (行の順に関わらない)。"""
        shallow = row("~/Library/Caches/Google", judgment="review")
        deep = row("~/Library/Caches/Google/Chrome", judgment="deletable")
        chrome_default = os.path.join(self.caches, "Google", "Chrome", "Default")
        for rows in ([shallow, deep], [deep, shallow]):
            with self.subTest(order=[r["pattern"] for r in rows]):
                self.assertEqual(self.match(chrome_default, rows)["row"]["pattern"], "~/Library/Caches/Google/Chrome")
                self.assertEqual(self.match(os.path.join(self.caches, "Google", "Other"), rows)["row"]["pattern"],
                                 "~/Library/Caches/Google")

    def test_symlinks_are_resolved_before_matching(self):
        go_build = self.make_dir("user-home", "Library", "Caches", "go-build")
        link = os.path.join(self.user_home, "go-build-link")
        os.symlink(go_build, link)
        self.assertEqual(self.match(link, [row("~/Library/Caches/go-build")])["path"], go_build)


class JudgeOrderTest(JudgeCase):
    """判定の順 (R13 のうち、U3 で扱う保護の一覧と判定表。記録は U4 で足す)。"""

    def test_table_row(self):
        go_build = self.make_dir("user-home", "Library", "Caches", "go-build")
        rows = [row("~/Library/Caches/go-build", judgment="deletable", impact="次のビルドが遅くなる",
                    command=tool("go", "clean", "-cache", env={"GOCACHE": "{path}"}), process_names=["go"])]
        result = judge.judge(go_build, self.environment(), rows)
        self.assertEqual(result["judgment"], "deletable")
        self.assertEqual(result["source"], "table")
        self.assertEqual(result["pattern"], "~/Library/Caches/go-build")
        self.assertEqual(result["matched_path"], go_build)
        self.assertEqual(result["reason"], "~/Library/Caches/go-build の理由")
        self.assertEqual(result["impact"], "次のビルドが遅くなる")
        self.assertEqual(result["command"], {"type": "tool", "args": ["go", "clean", "-cache"],
                                             "env": {"GOCACHE": go_build}}, "{path} を一致したディレクトリにすること")
        self.assertEqual(result["process_names"], ["go"])
        self.assertIsNone(result["protection"])

    def test_name_placeholder(self):
        toolchain = self.make_dir("user-home", ".rustup", "toolchains", "1.80.0-aarch64-apple-darwin")
        rows = [row("~/.rustup/toolchains/*", command=tool("rustup", "toolchain", "uninstall", "{name}"))]
        self.assertEqual(judge.judge(toolchain, self.environment(), rows)["command"]["args"],
                         ["rustup", "toolchain", "uninstall", "1.80.0-aarch64-apple-darwin"])

    def test_rm_row_applies_to_items_below(self):
        """rm の行の下の項目は、行の判定・理由・影響を使い、その項目を rm で消す。"""
        chrome = self.make_dir("user-home", "Library", "Caches", "Google", "Chrome")
        rows = [row("~/Library/Caches/Google", judgment="deletable", process_names=["Google Chrome"])]
        result = judge.judge(chrome, self.environment(), rows)
        self.assertEqual(result["judgment"], "deletable")
        self.assertEqual(result["reason"], "~/Library/Caches/Google の理由")
        self.assertEqual(result["matched_path"], os.path.dirname(chrome))
        self.assertEqual(result["command"], {"type": "rm", "path": chrome}, "下の項目そのものを消すこと")
        self.assertEqual(result["process_names"], ["Google Chrome"])

    def test_items_below_tool_row_are_kept(self):
        """ツールのコマンドの行の下の項目は「残す」。ツールのコマンドは一致したディレクトリをまとめて消すため。"""
        go_build = self.make_dir("user-home", "Library", "Caches", "go-build")
        below = self.make_dir("user-home", "Library", "Caches", "go-build", "00")
        rows = [row("~/Library/Caches/go-build", judgment="deletable",
                    command=tool("go", "clean", "-cache", env={"GOCACHE": "{path}"}))]
        result = judge.judge(below, self.environment(), rows)
        self.assertEqual(result["judgment"], "keep")
        self.assertEqual(result["source"], "table")
        self.assertIsNone(result["command"])
        self.assertIn(go_build, result["reason"])
        self.assertIn("go clean -cache", result["reason"])

    def test_items_below_keep_row_are_kept(self):
        avd = self.make_dir("user-home", ".android", "keys")
        rows = [row("~/.android", judgment="keep")]
        result = judge.judge(avd, self.environment(), rows)
        self.assertEqual(result["judgment"], "keep")
        self.assertEqual(result["reason"], "~/.android の理由")
        self.assertIsNone(result["command"])

    def test_no_row_means_no_judgment(self):
        """どの行にも一致しない項目は「判定なし」(判定・判定の根拠の種類・理由が None)。Claude が調べて判定する。"""
        result = judge.judge(self.make_dir("user-home", "Library", "Caches", "unknown"), self.environment(),
                             [row("~/Library/Caches/go-build")])
        self.assertIsNone(result["judgment"])
        self.assertIsNone(result["source"])
        self.assertIsNone(result["reason"])
        self.assertIsNone(result["command"])
        self.assertIsNone(result["dedicated_list"])

    def test_protection_comes_before_table(self):
        rows = [row("~/.claude", judgment="deletable")]
        result = judge.judge(self.claude, self.environment(), rows)
        self.assertEqual(result["judgment"], "keep")
        self.assertEqual(result["source"], "protected")
        self.assertIsNone(result["command"])

    def test_dedicated_list(self):
        """専用の一覧を持つ行に一致する項目は、専用の一覧の種類を返す。保護の一覧の項目でも返す。下の項目には返さない。"""
        installs = self.make_dir("user-home", ".asdf", "installs")
        rows = [row("~/.asdf/installs", judgment="keep", dedicated_list="asdf"),
                row("~/Library/Containers/com.docker.docker", judgment="keep", dedicated_list="docker")]
        env = self.environment()
        self.assertEqual(judge.judge(installs, env, rows)["dedicated_list"], "asdf")
        docker = judge.judge(self.docker, env, rows)
        self.assertEqual(docker["source"], "protected")
        self.assertEqual(docker["dedicated_list"], "docker")
        self.assertIsNone(judge.judge(self.caches, env, rows)["dedicated_list"])
        nodejs = self.make_dir("user-home", ".asdf", "installs", "nodejs")
        self.assertIsNone(judge.judge(nodejs, env, rows)["dedicated_list"])

    def test_app_worktrees_directory_is_a_dedicated_list(self):
        """どの深さの .claude/worktrees も、専用の一覧の種類 worktree (アプリの worktree の案内) になる。"""
        worktrees = os.path.dirname(self.app_worktree)
        result = judge.judge(worktrees, self.environment(), [])
        self.assertEqual(result["dedicated_list"], "worktree")
        self.assertEqual(result["judgment"], "keep")
        self.assertIsNone(judge.judge(self.app_worktree, self.environment(), [])["dedicated_list"])


class RowFormatTest(unittest.TestCase):
    """判定表の行の様式の検査 (文書 references/judgment-table.md の節「行」)。"""

    def assert_error(self, data, fragment):
        errors = judge.row_errors(data)
        self.assertTrue(any(fragment in error for error in errors), errors)

    def test_valid_rows(self):
        for data in (row("~/Library/Caches/Google", judgment="deletable", process_names=["Google Chrome"]),
                     row("~/.android", judgment="keep"),
                     row("~/.asdf/installs", judgment="keep", dedicated_list="asdf"),
                     row("~/.rustup/toolchains/*", command=tool("rustup", "toolchain", "uninstall", "{name}")),
                     row("~/go/pkg/mod", command=tool("go", "clean", "-modcache", env={"GOMODCACHE": "{path}"}))):
            with self.subTest(pattern=data["pattern"]):
                self.assertEqual(judge.row_errors(data), [])

    def test_unknown_and_missing_keys(self):
        self.assert_error({**row("~/a"), "note": "x"}, "知らないキー: note")
        data = row("~/a")
        del data["sources"]
        self.assert_error(data, "キー sources が無い")

    def test_pattern(self):
        self.assert_error(row("/Users/x/a"), "~/ で始まる")
        self.assert_error(row("~/Library/Caches/com.google.*"), "名前の一部")
        self.assert_error(row("~/a/../b"), "..")
        self.assert_error(row("~/a//b"), "空の名前")

    def test_judgment(self):
        self.assert_error(row("~/a", judgment="delete"), "judgment")

    def test_texts(self):
        self.assert_error(row("~/a", reason=""), "reason")
        self.assert_error(row("~/a", impact=None), "impact")

    def test_command(self):
        self.assert_error(row("~/a", judgment="keep", command={"type": "rm"}), "keep の行の command が null でない")
        self.assert_error(row("~/a", command=None), "command が JSON のオブジェクトでない")
        self.assert_error(row("~/a", command={"type": "shell", "args": ["x"]}), "type")
        self.assert_error(row("~/a", command={"type": "rm", "path": "~/a"}), "知らないキー")
        self.assert_error(row("~/a", command=tool()), "args")
        self.assert_error(row("~/a", command=tool("go", "clean", "--dir={path}")), "{ }")
        self.assert_error(row("~/a", command=tool("{path}", "clean")), "args[0]")
        self.assert_error(row("~/a", command=tool("go", "clean", env={"gocache": "{path}"})), "env の名前")
        self.assert_error(row("~/a", command=tool("go", "clean", env={"GOCACHE": "{dir}"})), "{ }")

    def test_process_names_and_dedicated_list(self):
        self.assert_error(row("~/a", process_names="Google Chrome"), "process_names")
        self.assert_error(row("~/a", process_names=["/Applications/x"]), "process_names")
        self.assert_error(row("~/a", judgment="keep", dedicated_list="worktree"), "dedicated_list")

    def test_sources(self):
        self.assert_error(row("~/a", sources=[]), "sources")
        self.assert_error(row("~/a", sources=[{"url": "http://example.com"}]), "url と checked_on")
        self.assert_error(row("~/a", sources=[{"url": "http://example.com", "checked_on": "2026-11-25"}]), "https://")
        self.assert_error(row("~/a", sources=[{"url": "https://example.com", "checked_on": "2026-11-31"}]), "日付でない")
        self.assert_error(row("~/a", sources=[{"url": "https://example.com", "checked_on": "2026/11/25"}]), "YYYY-MM-DD")

    def test_overlapping_rows_at_the_same_depth(self):
        errors = judge.table_errors([row("~/Library/Caches/*"), row("~/Library/Caches/Google")])
        self.assertTrue(any("同じ深さ" in error for error in errors), errors)
        self.assertEqual(judge.table_errors([row("~/Library/Caches/Google"), row("~/Library/Caches/Google/Chrome")]),
                         [], "深さの違う行は重なってよいこと")
        self.assertEqual(judge.table_errors([row("~/Library/*/Google"), row("~/Library/Caches/go-build")]), [])

    def test_load_table_rejects_invalid_table(self):
        """判定表の様式の誤りは、プラグインの不具合として例外にする (読めた行だけを使わない)。"""
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "judgment-table.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump([row("~/a"), row("~/b", judgment="delete")], f)
            with self.assertRaises(ValueError) as caught:
                judge.load_table(path)
        self.assertIn("judgment", str(caught.exception))


class BundledTableTest(unittest.TestCase):
    """プラグインに入れる判定表 (judgment-table.json) の検査。"""

    def setUp(self):
        self.rows = judge.load_table()

    def test_table_is_valid(self):
        """様式の検査を、判定表のすべての行に行う (load_table が誤りを ValueError で送出する)。"""
        self.assertTrue(self.rows)
        self.assertEqual(judge.table_errors(self.rows), [])

    def test_tool_commands_start_with_allowed_pairs(self):
        """判定表のツールのコマンドは、すべて KTD6 の許可した組 (実行ファイルとサブコマンド) で始まる。"""
        for data in self.rows:
            command = data["command"]
            if command is None or command["type"] != "tool":
                continue
            with self.subTest(pattern=data["pattern"]):
                self.assertTrue(any(tuple(command["args"][:len(pair)]) == pair for pair in commands.ALLOWED),
                                f"{command['args']} が commands.ALLOWED の組で始まらない")

    def test_dedicated_list_rows(self):
        """専用の一覧の行 (asdf の installs・Docker Desktop のディレクトリ) がある (計画の U3)。"""
        kinds = {data.get("dedicated_list") for data in self.rows}
        self.assertIn("asdf", kinds)
        self.assertIn("docker", kinds)


if __name__ == "__main__":
    unittest.main()
