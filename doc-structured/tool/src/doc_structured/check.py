"""サブコマンド check が実行する検査と、検査 a (生成し直して差分が無い)。

検査の群 (決定の一覧の問 12 (3)):
  軽い群 (--light。デフォルト)  文書と YAML だけで実行できる検査。この版では a・b・c-1・c-2・h・i・k
  重い群 (--heavy)              データベースなどが要る検査。この版では j (設計と実装の差分)
--all は両方、--only <検査> は 1 つだけを実行する。
検査 h (YAML の形式) に誤りがあると、定義の一覧と完全な名前が正しく作れないので、検査 a・b・i は実行せず、そのことを報告する。
検査 c-1 も、参照先が無い参照があると依存を正しく求められないので、実行しない (決めた経緯は Issue #202 のコメントの 10)。
検査 c-2 も、検査 b が確認するリンクの上で数えるので、検査 b と同じく実行しない (決めた経緯は Issue #198 のコメントの 6)。
検査 k (手書きの Markdown の行数) は YAML を使わないので、いつも実行する。
検査 j も、YAML の定義と実装を比べるので、検査 h に誤りがあれば実行しない。データベースが無ければ、CheckResult.unavailable に
理由を入れる (サブコマンドは終了コード 3 で終了する。決めた経緯は Issue #207 のコメントの 11)。
"""

import difflib
from dataclasses import dataclass, field
from pathlib import Path

from . import generated_header
from .config import CONFIG_RELATIVE_PATH, Config
from .cycles import check_cycles
from .dependencies import check_dependency_cycles
from .direction import check_direction, check_markdown_direction
from .documents import load_documents
from .domains import Project, load_project
from .impl_diff import CHECK as IMPL_CHECK, ImplementationUnavailable, Location, judge, unified
from .generate import GITATTRIBUTES_PATH, HANDWRITTEN_MESSAGE, generated_files, handwritten_fix, is_handwritten, render_project
from .length import check_length
from .links import check_links
from .problems import Problem
from .schema_actual import MigrationError, read_schema
from .schema_diff import LABELS as SCHEMA_LABELS, compare as compare_schema

LIGHT = ("a", "b", "c-1", "c-2", "h", "i", "k")
HEAVY = ("j",)
ALL = LIGHT + HEAVY

# 検査 j に差分があったときに、check の出力の最後に添える行
IMPL_DIFF_HINT = "差分は bin/doc-structured impl-diff で見る"


@dataclass
class CheckResult:
    checks: tuple[str, ...]  # 実行するよう指定された検査
    problems: list[Problem] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # 検査 h の誤りのため実行しなかった検査
    unavailable: str | None = None  # データベースが無いため検査 j を実行できなかった理由
    notes: list[str] = field(default_factory=list)  # 問題の後に添える行

    @property
    def ok(self) -> bool:
        return not self.problems and not self.skipped and self.unavailable is None


@dataclass
class ImplDiffResult:
    problems: list[Problem]  # 指示の行。設定やマイグレーションの誤りも含む
    diff: str  # 正規化した形どうしの unified diff。差分が無ければ空


def implementation_diff(config: Config, project: Project) -> ImplDiffResult:
    """検査 j: 設計と実装を比べる。データベースが無ければ ImplementationUnavailable を投げる。"""
    config_path = CONFIG_RELATIVE_PATH.as_posix()
    database = config.database
    if database is None:
        message = "設定に paths.migrations と database が無いので、設計と実装を比べられない。設定に paths.migrations と database を書く"
        return ImplDiffResult([Problem(IMPL_CHECK, config_path, message)], "")
    try:
        actual = read_schema(config.root, database)
    except MigrationError as e:
        line, column = (None, None) if e.path else database.migrations_at
        return ImplDiffResult([Problem(IMPL_CHECK, e.path or config_path, str(e), line, column)], "")
    result = compare_schema(project, actual)
    problems = judge(result.items, SCHEMA_LABELS, Location(config_path, *database.migrations_at))
    diff = unified(
        result.design_lines,
        result.actual_lines,
        "設計 (docs/domains/ の schema*.yaml)",
        f"実装 ({database.migrations} を {database.kind} に適用したもの)",
    )
    return ImplDiffResult(problems, diff)


def check_generated(root: Path, project: Project) -> list[Problem]:
    """検査 a: 生成し直した内容と、今のファイルを比べる。"""
    problems: list[Problem] = []
    outputs = render_project(project)
    for relative, expected in outputs.items():
        header = generated_header.read_header(expected)
        if relative == GITATTRIBUTES_PATH:
            how = f"このファイルを直接編集せず、{header.command} を実行する。{generated_header.GITATTRIBUTES_GUIDE}"
        else:
            how = f"このファイルを直接編集せず、生成元 {header.source} の YAML を直して {header.command} を実行する"
        path = root / relative
        if not path.is_file():
            problems.append(Problem("a", relative, f"生成するはずのファイルが無い。{header.command} を実行する"))
            continue
        content = generated_header.read_file(path)
        if is_handwritten(content):
            problems.append(Problem("a", relative, f"{HANDWRITTEN_MESSAGE}。{handwritten_fix(relative)}"))
            continue
        if content.matches(expected):
            continue
        if content.header is None:
            # 先頭の記述が無く、手で書いたファイルでもない (空白と BOM だけの) ファイル。YAML の修正は要らない
            problems.append(Problem("a", relative, f"生成したファイルの中身が無い。{header.command} を実行する"))
            continue
        actual = content.text
        if actual == expected:
            # 読んだ内容は同じで、BOM か UTF-8 として読めないバイトだけが違う。YAML の修正は要らない
            problems.append(
                Problem(
                    "a", relative,
                    f"生成し直した内容と違う (BOM か、UTF-8 として読めないバイトがある)。{header.command} を実行する",
                )
            )
            continue
        diff = "".join(
            difflib.unified_diff(
                actual.splitlines(keepends=True),
                expected.splitlines(keepends=True),
                fromfile=f"{relative} (今のファイル)",
                tofile=f"{relative} (生成し直した内容)",
            )
        )
        problems.append(Problem("a", relative, f"生成し直した内容と違う。{how}", detail=diff))
    for relative, header in generated_files(root).items():
        if relative in outputs:
            continue
        if header.source and not (root / header.source).exists():
            message = f"生成元 {header.source} が無い。このファイルを消すか、生成元を戻す"
        else:
            command = header.command or generated_header.GENERATE_COMMAND
            message = f"生成し直すと消えるファイルが残っている。{command} を実行して消す"
        problems.append(Problem("a", relative, message))
    return problems


def run_checks(root: Path, checks: tuple[str, ...], config: Config | None = None) -> CheckResult:
    """検査を実行する。検査 j には config (設定) が要る。"""
    result = CheckResult(checks=checks)
    if not checks:
        return result
    project, yaml_problems = load_project(root)
    if "h" in checks:
        result.problems += yaml_problems
    if "b" in checks or "k" in checks or "i" in checks or "c-2" in checks:
        # ドメインの一覧はディレクトリ名から作るので、YAML に誤りがあっても手書きの Markdown を見つけられる
        index, document_problems = load_documents(root, project)
    if "k" in checks:
        result.problems += check_length(index)
    if yaml_problems:
        result.skipped = [c for c in checks if c in ("a", "b", "c-1", "c-2", "i", "j")]
        return result
    if "b" in checks:
        result.problems += document_problems + check_links(index)
    if "i" in checks:
        result.problems += check_direction(project) + check_markdown_direction(index)
    if "c-1" in checks:
        result.problems += check_dependency_cycles(project)
    if "c-2" in checks:
        result.problems += check_cycles(index)
    if "a" in checks:
        result.problems += check_generated(root, project)
    if "j" in checks:
        assert config is not None, "検査 j には設定が要る"
        try:
            impl = implementation_diff(config, project)
        except ImplementationUnavailable as e:
            result.unavailable = str(e)
        else:
            result.problems += impl.problems
            if impl.diff:
                result.notes.append(IMPL_DIFF_HINT)
    return result
