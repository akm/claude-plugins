"""ツール doc-structured のテストの共通の準備。

テストは架空の題材「図書館の貸出」のプロジェクトを一時ディレクトリに作って使う。実際のプロジェクトの名前と内容は入れない。
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
TOOL_DIR = TESTS_DIR.parent
PLUGIN_DIR = TOOL_DIR.parent
REPO_ROOT = PLUGIN_DIR.parent
BIN_SCRIPT = PLUGIN_DIR / "bin" / "doc-structured"
CONFIG_RELATIVE_PATH = Path(".claude/akm-claude-plugins/doc-structured/config.yaml")
# 架空の題材「図書館の貸出」のサンプルのプロジェクト。ドメインの YAML と、生成したファイル (コミット済み) を持つ
SAMPLE_PROJECT = TESTS_DIR / "fixtures" / "library-loans"

# 架空の題材の設定。コメント付きで、version の行は決まった形
SAMPLE_CONFIG = """\
# 図書館の貸出 (架空の題材) の、doc-structured の設定
version: 0.1.0
"""


def clean_env(**extra: str) -> dict[str, str]:
    """子プロセスの環境。テストを実行している git の環境変数 (GIT_DIR など) は、子プロセスの git が別のリポジトリを
    書き換えないよう消す。"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.pop("DOC_STRUCTURED_CHECKOUT", None)
    env.update(extra)
    return env


class ProjectTestCase(unittest.TestCase):
    """一時ディレクトリにサンプルのプロジェクトを作るテストの基底。"""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="doc-structured-test-")
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self.tmp = Path(self._tmp).resolve()
        self.project = self.tmp / "library-loans"
        self.project.mkdir()

    def write_config(self, text: str = SAMPLE_CONFIG, project: Path | None = None) -> Path:
        path = (project or self.project) / CONFIG_RELATIVE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def copy_sample(self) -> Path:
        """サンプルのプロジェクトを、一時ディレクトリの self.project にコピーする。"""
        shutil.rmtree(self.project)
        shutil.copytree(SAMPLE_PROJECT, self.project)
        return self.project

    def write(self, relative: str, text: str) -> Path:
        """self.project の下にファイルを書く。"""
        path = self.project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def install_bin(self, project: Path | None = None, script: Path = BIN_SCRIPT) -> Path:
        """プロジェクトに bin/doc-structured を置く (実際のプロジェクトでは生成したファイル)。"""
        dest = (project or self.project) / "bin" / "doc-structured"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(script, dest)
        dest.chmod(0o755)
        return dest


PYTHON = sys.executable
