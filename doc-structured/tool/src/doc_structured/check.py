"""サブコマンド check が実行する検査と、検査 a (生成し直して差分が無い)。

検査の群 (決定の一覧の問 12 (3)):
  軽い群 (--light。デフォルト)  文書と YAML だけで実行できる検査。この版では a・h・i
  重い群 (--heavy)              データベースなどが要る検査。この版には無い
--all は両方、--only <検査> は 1 つだけを実行する。
検査 h (YAML の形式) に誤りがあると、定義の一覧が正しく作れないので、検査 a と i は実行せず、そのことを報告する。
"""

import difflib
from dataclasses import dataclass, field
from pathlib import Path

from . import generated_header
from .direction import check_direction
from .domains import Project, load_project
from .generate import generated_files, render_project
from .problems import Problem

LIGHT = ("a", "h", "i")
HEAVY: tuple[str, ...] = ()
ALL = LIGHT + HEAVY


@dataclass
class CheckResult:
    checks: tuple[str, ...]  # 実行するよう指定された検査
    problems: list[Problem] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # 検査 h の誤りのため実行しなかった検査

    @property
    def ok(self) -> bool:
        return not self.problems and not self.skipped


def check_generated(root: Path, project: Project) -> list[Problem]:
    """検査 a: 生成し直した内容と、今のファイルを比べる。"""
    problems: list[Problem] = []
    outputs = render_project(project)
    for relative, expected in outputs.items():
        header = generated_header.read_header(expected)
        how = f"このファイルを直接編集せず、生成元 {header.source} の YAML を直して {header.command} を実行する"
        path = root / relative
        if not path.is_file():
            problems.append(Problem("a", relative, f"生成するはずのファイルが無い。{header.command} を実行する"))
            continue
        actual = path.read_text(encoding="utf-8")
        if actual == expected:
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


def run_checks(root: Path, checks: tuple[str, ...]) -> CheckResult:
    result = CheckResult(checks=checks)
    if not checks:
        return result
    project, yaml_problems = load_project(root)
    if "h" in checks:
        result.problems += yaml_problems
    if yaml_problems:
        result.skipped = [c for c in checks if c in ("a", "i")]
        return result
    if "i" in checks:
        result.problems += check_direction(project)
    if "a" in checks:
        result.problems += check_generated(root, project)
    return result
