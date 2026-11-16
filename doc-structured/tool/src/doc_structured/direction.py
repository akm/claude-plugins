"""検査 i (参照の向き)。

YAML の参照 (属性の refers_to・ファイルに書く状態の遷移の attribute と、前提の targets・状態の遷移の operations などの
完全な ID の配列) は、参照する YAML のディレクトリの祖先の
ディレクトリにある YAML の定義を指さない。
同じディレクトリ・子孫のディレクトリ・別のサブツリー・ほかのドメインは指してよい。判定は参照先の定義を書いた場所で行う。
違反したときの直し方は、参照される定義をサブディレクトリの YAML に移すこと (参照しているファイルを移すことではない)。

手書きの Markdown のリンクは、祖先のディレクトリの手書きのファイルを指さない。判定は参照先のアンカーのあるファイルの場所で行う。
生成したファイルを指すリンクは対象にしない (生成したファイルの場所はツールが決め、参照される定義を移して直せないため。
決めた経緯は Issue #198 のコメントの 1)。参照先のアンカーが無いリンクは、検査 b が報告するので数えない。
規則の SSOT はプラグインの規則の文書 (ファイル doc-structured/rules/doc-structured-docs.md と
doc-structured/rules/doc-structured-domains.md)。
"""

from pathlib import PurePosixPath

from .documents import Index
from .domains import Project
from .links import resolve
from .problems import Problem
from .references import all_references
from .yaml_references import yaml_references


def _is_ancestor(target_dir: PurePosixPath, source_dir: PurePosixPath) -> bool:
    return target_dir != source_dir and target_dir in source_dir.parents


def check_direction(project: Project) -> list[Problem]:
    problems: list[Problem] = []
    for reference in yaml_references(project):
        if reference.target not in project.entries:
            continue  # 参照先が無いことは検査 h が報告する
        target = project.entries[reference.target]
        source_dir = PurePosixPath(reference.path).parent
        target_dir = PurePosixPath(target.path).parent
        if _is_ancestor(target_dir, source_dir):
            problems.append(
                Problem(
                    "i",
                    reference.path,
                    f"{reference.prefix} の参照先 {target.id} は、祖先のディレクトリの {target.path} にある。"
                    f"参照される定義 ({target.id}) を、参照するファイルと同じディレクトリかその下に移す",
                    reference.line,
                    reference.column,
                )
            )
    return problems


def check_markdown_direction(index: Index) -> list[Problem]:
    problems: list[Problem] = []
    for reference in all_references(index):
        if not reference.in_body:
            continue  # 本文で使われていない定義の行は、検査 b が報告する
        target = resolve(reference.file, reference.definition, index).target
        if target is None or index.file(target.path) is None:
            continue  # 参照先が無いものは検査 b が報告する。生成したファイルは対象にしない
        source_dir = PurePosixPath(reference.path).parent
        target_dir = PurePosixPath(target.path).parent
        if _is_ancestor(target_dir, source_dir):
            problems.append(
                Problem(
                    "i",
                    reference.path,
                    f"リンク {reference.written} の参照先 {target.id} は、祖先のディレクトリの手書きのファイル {target.path} にある。"
                    "参照される内容を、サブディレクトリの子のファイルに移す",
                    reference.line,
                    reference.column,
                )
            )
    return problems
