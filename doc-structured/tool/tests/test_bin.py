"""スクリプト bin/doc-structured (ツールの入口) のテスト。

スクリプトをサンプルのプロジェクトにコピーし、プロセスとして実行して、標準出力・標準エラー出力・終了コードと、
キャッシュのディレクトリの状態を見る。キャッシュは環境変数 XDG_CACHE_HOME で一時ディレクトリに向ける。

取得の確認は、GitHub に接続せずに行う。このチェックアウトの doc-structured/tool をコピーした一時的な git のリポジトリに
タグ doc-structured--v9.9.9 を作り、スクリプトの取得元 (変数 repo_url の行) をそのリポジトリの file:// の URL に
書き換えたコピーを使う。取得は本物の pip が行うので、依存 (ruamel.yaml) とビルドの道具 (setuptools) を PyPI から取る
ネットワークは要る。
"""

import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from doc_structured import __version__
from tooltest import BIN_SCRIPT, REPO_ROOT, TOOL_DIR, ProjectTestCase, clean_env

PUBLISHED_VERSION = "9.9.9"  # 一時的なリポジトリに公開した (タグを作った) バージョン
UNPUBLISHED_VERSION = "9.9.8"  # タグの無いバージョン


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", *args],
        cwd=cwd,
        env=clean_env(),
        check=True,
        capture_output=True,
    )


class BinTestCase(ProjectTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.cache_home = self.tmp / "cache"
        self.cache_dir = self.cache_home / "akm-claude-plugins" / "doc-structured"

    def run_bin(self, *args: str, script: Path | None = None, env: dict[str, str] | None = None, cwd=None):
        script = script or (self.project / "bin" / "doc-structured")
        return subprocess.run(
            [str(script), *args],
            cwd=cwd or self.project,
            env=clean_env(XDG_CACHE_HOME=str(self.cache_home), **(env or {})),
            capture_output=True,
            text=True,
        )

    def replace_tool_with_marker(self, venv: Path) -> None:
        """取得済みの venv のツールを目印のスクリプトに置き換える。次の実行がこれを実行すれば、取得し直していない。"""
        marker = venv / "bin" / "doc-structured"
        marker.write_text("#!/bin/sh\necho marker \"$@\"\n", encoding="utf-8")
        marker.chmod(0o755)


class VersionLineTest(BinTestCase):
    """設定の version の行の取り出し。ツールは取得しないので、ネットワークは要らない。"""

    def test_missing_config(self):
        self.install_bin()
        result = self.run_bin("version")
        self.assertEqual(result.returncode, 1)
        self.assertIn("設定ファイルが無い", result.stderr)

    def test_no_version_line(self):
        self.install_bin()
        self.write_config('version: "0.1.0"\n')
        result = self.run_bin("version")
        self.assertEqual(result.returncode, 1)
        self.assertIn("1 行だけ要る", result.stderr)
        self.assertIn("0 行", result.stderr)

    def test_two_version_lines(self):
        self.install_bin()
        self.write_config("version: 0.1.0\nversion: 0.1.1\n")
        result = self.run_bin("version")
        self.assertEqual(result.returncode, 1)
        self.assertIn("2 行", result.stderr)

    def test_old_python(self):
        """python3 が 3.12 より古いときは、取得も実行もせずに終了する。"""
        fake_bin = self.tmp / "fakebin"
        fake_bin.mkdir()
        fake_python = fake_bin / "python3"
        fake_python.write_text(
            '#!/bin/sh\ncase "$1" in --version) echo "Python 3.11.9" ;; *) exit 1 ;; esac\n', encoding="utf-8"
        )
        fake_python.chmod(0o755)
        self.install_bin()
        self.write_config()
        result = self.run_bin("version", env={"PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"})
        self.assertEqual(result.returncode, 1)
        self.assertIn("Python 3.12 以上", result.stderr)
        self.assertIn("Python 3.11.9", result.stderr)
        self.assertFalse(self.cache_dir.exists())


class CheckoutTest(BinTestCase):
    """環境変数 DOC_STRUCTURED_CHECKOUT で、手元のチェックアウトのツールを使う。"""

    def test_runs_tool_of_checkout_and_reuses_venv(self):
        self.install_bin()
        self.write_config("version: 0.0.0\n")  # 取得しないので、公開していないバージョンでもよい
        env = {"DOC_STRUCTURED_CHECKOUT": str(REPO_ROOT)}
        result = self.run_bin("version", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f"doc-structured {__version__}\n")
        venv = self.cache_dir / "checkout"
        self.assertTrue((venv / "bin" / "doc-structured").exists())
        self.assertFalse((self.cache_dir / "0.0.0").exists(), "version の取得をしてはいけない")

        self.replace_tool_with_marker(venv)
        result = self.run_bin("version", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "marker version\n")

    def test_checkout_without_tool(self):
        self.install_bin()
        self.write_config()
        result = self.run_bin("version", env={"DOC_STRUCTURED_CHECKOUT": str(self.tmp / "nowhere")})
        self.assertEqual(result.returncode, 1)
        self.assertIn("DOC_STRUCTURED_CHECKOUT=", result.stderr)
        self.assertIn("pyproject.toml が無い", result.stderr)
        self.assertFalse(self.cache_dir.exists())


class FetchTest(BinTestCase):
    """設定の version のタグから取得して実行する。"""

    def setUp(self) -> None:
        super().setUp()
        self.remote = self.tmp / "remote"
        tool_copy = self.remote / "doc-structured" / "tool"
        shutil.copytree(TOOL_DIR, tool_copy, ignore=shutil.ignore_patterns("__pycache__", "*.egg-info", "tests"))
        init = tool_copy / "src" / "doc_structured" / "__init__.py"
        init.write_text(
            re.sub(r'^__version__ = ".*"$', f'__version__ = "{PUBLISHED_VERSION}"', init.read_text(encoding="utf-8"),
                   flags=re.MULTILINE),
            encoding="utf-8",
        )
        _git(self.remote, "init", "-q")
        _git(self.remote, "add", ".")
        _git(self.remote, "commit", "-q", "-m", "tool")
        _git(self.remote, "tag", f"doc-structured--v{PUBLISHED_VERSION}")

        text = BIN_SCRIPT.read_text(encoding="utf-8")
        line = 'repo_url="https://github.com/akm/claude-plugins"\n'
        self.assertIn(line, text, "スクリプトの取得元の行の形が変わった")
        local_script = self.tmp / "doc-structured-local"
        local_script.write_text(text.replace(line, f'repo_url="file://{self.remote}"\n'), encoding="utf-8")
        local_script.chmod(0o755)
        self.install_bin(script=local_script)

    def test_fetches_version_of_config_and_reuses_it(self):
        self.write_config(f"version: {PUBLISHED_VERSION}\n")
        result = self.run_bin("version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f"doc-structured {PUBLISHED_VERSION}\n")
        venv = self.cache_dir / PUBLISHED_VERSION
        self.assertTrue((venv / "bin" / "doc-structured").exists())
        self.assertTrue((venv / "installed").exists())
        self.assertEqual([p.name for p in self.cache_dir.iterdir()], [PUBLISHED_VERSION])

        self.replace_tool_with_marker(venv)
        result = self.run_bin("version", "--extra")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "marker version --extra\n")

    def test_fetch_failure_exits_without_trying_anything_else(self):
        self.write_config(f"version: {UNPUBLISHED_VERSION}\n")
        result = self.run_bin("version")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ツールの取得に失敗した", result.stderr)
        self.assertIn(f"doc-structured--v{UNPUBLISHED_VERSION}", result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertFalse((self.cache_dir / UNPUBLISHED_VERSION).exists(), "途中の venv が残っている")


if __name__ == "__main__":
    unittest.main()
