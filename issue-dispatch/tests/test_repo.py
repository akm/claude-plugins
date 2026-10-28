#!/usr/bin/env python3
"""リポジトリの設定の読み方 (issue-dispatch/scripts/issue_dispatch/repo.py) と、CLI の `repo name` のテスト。

git の動作は一時ディレクトリに作ったリポジトリで確認する。`gh` は使わない。`ssh -G` は偽の ssh
(issue-dispatch/tests/fake-ssh) のディレクトリを PATH の先頭に加えて差し替える。

  python3 -m unittest discover -s issue-dispatch/tests

確認の方法・「読めない」の理由・URL の比べ方の SSOT は issue-dispatch/skills/issue-dispatch/references/repositories.md。
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.join(_HERE, "..", "scripts")
sys.path.insert(0, _SCRIPTS)

from issue_dispatch import config, repo  # noqa: E402

_CLI = os.path.join(_SCRIPTS, "issue_dispatch.py")
_DOC = os.path.join(_HERE, "..", "skills", "issue-dispatch", "references", "repositories.md")
_FAKE_SSH = os.path.join(_HERE, "fake-ssh")
CONFIG_REL = ".claude/akm-claude-plugins/issue-dispatch/config.json"


def _git(path, *args, check=True):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@example.com", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
    return subprocess.run(["git", "-C", path, *args], capture_output=True, text=True, check=check, env=env)


def make_clone(path, origin_url="git@github.com:akm/verify-a.git", config_on_default=None, default_branch="main",
               set_origin_head=True):
    """clone に見えるリポジトリを作る。既定のブランチ (origin/HEAD → origin/<default_branch>) の内容に設定を置ける。"""
    os.makedirs(path, exist_ok=True)
    _git(path, "init", "-q", "-b", default_branch)
    if config_on_default is not None:
        os.makedirs(os.path.join(path, os.path.dirname(CONFIG_REL)))
        with open(os.path.join(path, CONFIG_REL), "w", encoding="utf-8") as f:
            json.dump(config_on_default, f)
    with open(os.path.join(path, "README.md"), "w", encoding="utf-8") as f:
        f.write("default\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "default branch")
    sha = _git(path, "rev-parse", "HEAD").stdout.strip()
    if origin_url:
        _git(path, "remote", "add", "origin", origin_url)
        _git(path, "update-ref", f"refs/remotes/origin/{default_branch}", sha)
        if set_origin_head:
            _git(path, "symbolic-ref", "refs/remotes/origin/HEAD", f"refs/remotes/origin/{default_branch}")
    return sha


class ParseUrlTest(unittest.TestCase):

    def test_url_forms(self):
        for url in ("git@github.com:akm/verify-a.git", "git@github.com:akm/verify-a", "ssh://git@github.com/akm/verify-a.git",
                    "ssh://git@github.com:22/akm/verify-a.git", "https://github.com/akm/verify-a.git", "https://github.com/akm/verify-a",
                    "git://github.com/akm/verify-a.git", "https://github.com/akm/verify-a/"):
            with self.subTest(url=url):
                parsed = repo.parse_origin_url(url)
                self.assertEqual({k: parsed[k] for k in ("host", "owner", "name")}, {"host": "github.com", "owner": "akm", "name": "verify-a"})
                self.assertEqual(parsed["scheme"], "scp" if "://" not in url else url.split("://")[0])

    def test_unparsable_urls(self):
        bad_bytes = b"git@github.com:ak\xffm/x.git".decode("utf-8", errors="surrogateescape")
        for url in ("", "github.com", "/local/path", "file:///tmp/x.git", "https://github.com/akm", "akm/verify-a",
                    "https://github.com/ak m/x", "git@github.com:akm/x y.git", "https://github.com//x", bad_bytes,
                    "https://github.com/akm/x/y", "https://github.com/ak%20m/x"):
            with self.subTest(url=url):
                self.assertIsNone(repo.parse_origin_url(url))

    def test_names_with_dots_underscores_and_hyphens(self):
        """名前に使える文字は英数字と ._- で、位置は問わない (`.github`・`_private`・Enterprise Managed Users の `alice_acme`)。"""
        self.assertEqual(repo.parse_origin_url("git@github.com:akm/.github.git")["name"], ".github")
        self.assertEqual(repo.parse_origin_url("https://github.com/akm/_private")["name"], "_private")
        self.assertEqual(repo.parse_origin_url("https://github.com/alice_acme/notes")["owner"], "alice_acme")
        self.assertEqual(repo.parse_origin_url("https://github.com/my-org/a.b-c_d")["owner"], "my-org")

    def test_same_repository_ignores_case_and_git_suffix(self):
        self.assertTrue(repo.same_repository({"scheme": "https", "host": "github.com", "owner": "AKM", "name": "Verify-A"}, "akm/verify-a"))
        self.assertFalse(repo.same_repository({"scheme": "https", "host": "github.com", "owner": "akm", "name": "verify-b"}, "akm/verify-a"),
                         "名前を変える前の URL は合わない")
        self.assertFalse(repo.same_repository({"scheme": "https", "host": "gitlab.com", "owner": "akm", "name": "verify-a"}, "akm/verify-a"))


class HostTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        bin_dir = os.path.join(self._tmp.name, "bin")
        os.makedirs(bin_dir)
        os.symlink(_FAKE_SSH, os.path.join(bin_dir, "ssh"))
        self._saved = {k: os.environ.get(k) for k in ("PATH", "FAKE_SSH_HOSTS", "FAKE_SSH_FAIL")}
        os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
        os.environ["FAKE_SSH_HOSTS"] = "gh-work=github.com gh-443=ssh.github.com other=example.com"
        os.environ.pop("FAKE_SSH_FAIL", None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    def test_resolve_alias_with_ssh_config(self):
        self.assertEqual(repo.resolve_host("gh-work"), "github.com")
        self.assertEqual(repo.resolve_host("gh-443"), "github.com", "ssh.github.com は github.com と同じ")
        self.assertEqual(repo.resolve_host("github.com"), "github.com")
        self.assertEqual(repo.resolve_host("other"), "example.com")
        self.assertEqual(repo.resolve_host("unknown-host"), "unknown-host", "設定に無い名前はそのまま")

    def test_resolve_when_ssh_fails(self):
        os.environ["FAKE_SSH_FAIL"] = "1"
        self.assertEqual(repo.resolve_host("gh-work"), "gh-work", "ssh が失敗したら名前のまま (GitHub とは合わない)")

    def test_same_repository_resolves_alias(self):
        self.assertTrue(repo.same_repository(repo.parse_origin_url("git@gh-work:akm/verify-a.git"), "akm/verify-a"))
        self.assertTrue(repo.same_repository(repo.parse_origin_url("ssh://git@gh-work/akm/verify-a.git"), "akm/verify-a"))
        self.assertFalse(repo.same_repository(repo.parse_origin_url("git@other:akm/verify-a.git"), "akm/verify-a"))

    def test_https_host_is_not_resolved_with_ssh_config(self):
        """SSH の設定に github.com の別の HostName があっても、https の origin は GitHub と判定する。"""
        os.environ["FAKE_SSH_HOSTS"] = "github.com=ssh-proxy.corp.example"
        self.assertTrue(repo.same_repository(repo.parse_origin_url("https://github.com/akm/verify-a.git"), "akm/verify-a"))
        self.assertTrue(repo.same_repository(repo.parse_origin_url("git://github.com/akm/verify-a.git"), "akm/verify-a"))
        self.assertFalse(repo.same_repository(repo.parse_origin_url("git@github.com:akm/verify-a.git"), "akm/verify-a"),
                         "SSH の形は設定の HostName で解決する")
        self.assertTrue(repo.same_repository(repo.parse_origin_url("https://ssh.github.com/akm/verify-a.git"), "akm/verify-a"))


class ReadRepoConfigTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._tmp.name)
        self.clone = os.path.join(self.root, "clone")

    def tearDown(self):
        self._tmp.cleanup()

    def read(self, repositories, name="akm/verify-a"):
        return repo.read_repo_config(repositories, name)

    def test_reads_default_branch_not_checkout(self):
        """Covers AE42. 既定のブランチの内容を読み、checkout しているブランチと編集中の内容は見ない。"""
        make_clone(self.clone, config_on_default={"files": [{"pattern": "dist/**", "kind": "generated"}]})
        _git(self.clone, "checkout", "-q", "-b", "work")
        with open(os.path.join(self.clone, CONFIG_REL), "w", encoding="utf-8") as f:
            json.dump({"files": [{"pattern": "src/**", "kind": "generated"}]}, f)
        _git(self.clone, "commit", "-q", "-am", "work branch")
        with open(os.path.join(self.clone, CONFIG_REL), "w", encoding="utf-8") as f:
            f.write("{ broken")
        r = self.read({"akm/verify-a": self.clone})
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual(r["config"]["files"][0]["pattern"], "dist/**", "既定のブランチの内容であること")
        self.assertEqual(r["warnings"], [])
        self.assertEqual(r["path"], self.clone)

    def test_repositories_keys_are_case_insensitive(self):
        make_clone(self.clone)
        r = self.read({"akm/Verify-A": self.clone})
        self.assertEqual(r["status"], "missing", "キーの大文字小文字が違っても引けること")
        self.assertEqual(self.read({"AKM/VERIFY-A": self.clone}, "akm/verify-a")["path"], self.clone)

    def test_missing_config_on_default_branch(self):
        make_clone(self.clone)
        r = self.read({"akm/verify-a": self.clone})
        self.assertEqual(r["status"], "missing", "設定が無いことは読めないこととは別")
        self.assertEqual(r["config"]["files"], [], "設定が無いリポジトリと同じデフォルト値")

    def test_unreadable_reasons_in_order(self):
        """「読めない」の理由は、決めた順に確認して最初に当たったものを返す。"""
        r = self.read({})
        self.assertEqual((r["status"], r["reason"]), ("unreadable", "not-in-repositories"))
        self.assertIn("repositories", r["fix"])
        r = self.read({"akm/verify-a": os.path.join(self.root, "nope")})
        self.assertEqual(r["reason"], "directory-missing")
        plain = os.path.join(self.root, "plain")
        os.makedirs(plain)
        r = self.read({"akm/verify-a": plain})
        self.assertEqual(r["reason"], "not-git")
        make_clone(os.path.join(self.root, "noremote"), origin_url=None)
        r = self.read({"akm/verify-a": os.path.join(self.root, "noremote")})
        self.assertEqual(r["reason"], "no-origin")
        self.assertIn("git -C", r["fix"])
        self.assertIn("remote add origin", r["fix"])
        make_clone(os.path.join(self.root, "other"), origin_url="git@github.com:akm/old-name.git")
        r = self.read({"akm/verify-a": os.path.join(self.root, "other")})
        self.assertEqual(r["reason"], "origin-mismatch", "名前を変える前の URL は合わない")
        self.assertIn("remote set-url origin", r["fix"])
        make_clone(os.path.join(self.root, "nohead"), set_origin_head=False)
        r = self.read({"akm/verify-a": os.path.join(self.root, "nohead")})
        self.assertEqual(r["reason"], "no-origin-head", "既定のブランチを推測しない")
        self.assertIn("remote set-head origin --auto", r["fix"])

    def test_subdirectory_and_git_dir_are_not_clone_root(self):
        make_clone(self.clone, config_on_default={"files": []})
        sub = os.path.join(self.clone, "sub")
        os.makedirs(sub)
        r = self.read({"akm/verify-a": sub})
        self.assertEqual((r["status"], r["reason"]), ("unreadable", "not-clone-root"), "設定があっても「無い」ではなく「読めない」")
        self.assertEqual(r["root_hint"], self.clone, "案内するパスは clone のルート")
        r = self.read({"akm/verify-a": os.path.join(self.clone, ".git")})
        self.assertEqual(r["reason"], "not-clone-root")
        self.assertEqual(r["root_hint"], self.clone, ".git の中でもルートを案内する")

    def test_bare_repository_is_not_clone_root(self):
        bare = os.path.join(self.root, "bare.git")
        subprocess.run(["git", "init", "-q", "--bare", bare], check=True)
        r = self.read({"akm/verify-a": bare})
        self.assertEqual(r["reason"], "not-clone-root")
        self.assertIsNone(r["root_hint"], "bare には設定ファイルを読む作業ツリーが無いので案内するパスは無い")

    def test_symlinked_root_and_case_variant_are_roots(self):
        make_clone(self.clone, config_on_default={"files": []})
        link = os.path.join(self.root, "link-to-clone")
        os.symlink(self.clone, link)
        self.assertEqual(self.read({"akm/verify-a": link})["status"], "ok", "シンボリックリンクを経たルートも読む")
        variant = os.path.join(self.root, "CLONE")
        if os.path.isdir(variant) and os.path.samefile(variant, self.clone):
            self.assertEqual(self.read({"akm/verify-a": variant})["status"], "ok", "大文字と小文字だけ違う表記も読む")

    def test_origin_url_forms_and_alias(self):
        for url in ("https://github.com/AKM/Verify-A.git", "ssh://git@github.com/akm/verify-a", "git@ssh.github.com:akm/verify-a.git"):
            with self.subTest(url=url):
                path = os.path.join(self.root, "c-" + str(abs(hash(url)) % 10000))
                make_clone(path, origin_url=url)
                self.assertEqual(self.read({"akm/verify-a": path})["status"], "missing")

    def test_broken_config_on_default_branch_is_unreadable_config(self):
        make_clone(self.clone)
        with open(os.path.join(self.clone, "README.md"), "a", encoding="utf-8") as f:
            f.write("x")
        os.makedirs(os.path.join(self.clone, os.path.dirname(CONFIG_REL)))
        with open(os.path.join(self.clone, CONFIG_REL), "w", encoding="utf-8") as f:
            f.write("{ broken")
        _git(self.clone, "add", "-A")
        _git(self.clone, "commit", "-q", "-m", "broken config")
        sha = _git(self.clone, "rev-parse", "HEAD").stdout.strip()
        _git(self.clone, "update-ref", "refs/remotes/origin/main", sha)
        r = self.read({"akm/verify-a": self.clone})
        self.assertEqual(r["status"], "unreadable")
        self.assertEqual(r["reason"], "config-unreadable", "設定ファイルの JSON の誤りは config の規則で読めない")
        self.assertTrue(r["errors"])
        self.assertIsNone(r["config"], "読めない設定をデフォルト値で続けさせないこと")


class UnreadableBytesTest(unittest.TestCase):

    def test_non_utf8_config_on_default_branch(self):
        """既定のブランチの設定ファイルが UTF-8 でなければ、例外ではなく「読めない」(config-unreadable)。"""
        with tempfile.TemporaryDirectory() as tmp:
            clone = os.path.join(tmp, "clone")
            make_clone(clone)
            os.makedirs(os.path.join(clone, os.path.dirname(CONFIG_REL)))
            with open(os.path.join(clone, CONFIG_REL), "wb") as f:
                f.write(b"\xff\xfe{}")
            _git(clone, "add", "-A")
            _git(clone, "commit", "-q", "-m", "non utf-8 config")
            sha = _git(clone, "rev-parse", "HEAD").stdout.strip()
            _git(clone, "update-ref", "refs/remotes/origin/main", sha)
            r = repo.read_repo_config({"akm/verify-a": clone}, "akm/verify-a")
            self.assertEqual((r["status"], r["reason"]), ("unreadable", "config-unreadable"))
            self.assertIn("UTF-8", r["errors"][0]["message"])


class RepoNameTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *args):
        return subprocess.run([sys.executable, _CLI, *args], capture_output=True, text=True)

    def test_repo_name_from_worktree(self):
        clone = os.path.join(self.root, "clone")
        make_clone(clone, origin_url="https://github.com/AKM/Verify-A.git")
        sub = os.path.join(clone, "sub")
        os.makedirs(sub)
        p = self._run("repo", "name", "--dir", sub)
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual((out["status"], out["repo"], out["host"]), ("ok", "AKM/Verify-A", "github.com"))
        self.assertEqual(out["errors"], [])

    def test_repo_name_errors_without_gh(self):
        noremote = os.path.join(self.root, "noremote")
        make_clone(noremote, origin_url=None)
        out = json.loads(self._run("repo", "name", "--dir", noremote).stdout)
        self.assertEqual((out["status"], out["reason"]), ("error", "no-origin"))
        other = os.path.join(self.root, "other")
        make_clone(other, origin_url="git@gitlab.com:akm/verify-a.git")
        out = json.loads(self._run("repo", "name", "--dir", other).stdout)
        self.assertEqual((out["status"], out["reason"]), ("error", "not-github"))
        plain = os.path.join(self.root, "plain")
        os.makedirs(plain)
        out = json.loads(self._run("repo", "name", "--dir", plain).stdout)
        self.assertEqual((out["status"], out["reason"]), ("error", "not-git"))


class RepositoriesConfigTest(unittest.TestCase):

    def test_keys_differing_only_by_case_are_warned(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = os.path.join(tmp, ".claude", "akm-claude-plugins", "issue-dispatch", "config.json")
            os.makedirs(os.path.dirname(cfg))
            with open(cfg, "w", encoding="utf-8") as f:
                json.dump({"project": {"owner": "akm", "number": 3},
                           "repositories": {"akm/verify-a": "/a", "akm/Verify-A": "/b", "akm/other": "/c"}}, f)
            r = config.load(tmp, "manager")
            self.assertEqual(r["config"]["repositories"], {"akm/verify-a": "/a", "akm/other": "/c"}, "先に書いたものを使うこと")
            self.assertEqual(len([w for w in r["warnings"] if w["key"] == "repositories"]), 1)


class ConfigTextTest(unittest.TestCase):

    def test_load_text_follows_load_rules(self):
        r = config.load_text('{"files": [{"pattern": "./dist/**", "kind": "generated"}], "bogus": 1}', "repo", "origin/HEAD:x")
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["config"]["files"][0]["pattern"], "dist/**", "load と同じくパターンをそろえること")
        self.assertEqual([w["key"] for w in r["warnings"]], ["bogus"])
        self.assertEqual(config.load_text(None, "repo", "x")["status"], "missing")
        r = config.load_text("{ broken", "repo", "x")
        self.assertEqual(r["status"], "unreadable")
        self.assertTrue(r["errors"])


class DocTest(unittest.TestCase):

    def test_reasons_are_documented(self):
        with open(_DOC, encoding="utf-8") as f:
            doc = f.read()
        for reason in repo.REASONS:
            with self.subTest(reason=reason):
                self.assertIn(f"`{reason}`", doc, "「読めない」の理由が文書の表にあること")


if __name__ == "__main__":
    unittest.main()
