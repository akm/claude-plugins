"""検査 i のうち、YAML の参照の向き。

YAML の参照 (属性の refers_to) は、参照する YAML のディレクトリの祖先のディレクトリにある YAML の定義を指さない。
同じディレクトリ・子孫のディレクトリ・別のサブツリー・ほかのドメインは指してよい。判定は参照先の定義を書いた場所で行う。
違反したときの直し方は、参照される定義をサブディレクトリの YAML に移すこと (参照しているファイルを移すことではない)。
規則の SSOT はプラグインの規則の文書 (ファイル doc-structured/rules/doc-structured-domains.md)。
"""

from pathlib import PurePosixPath

from .domains import Project
from .problems import Problem


def check_direction(project: Project) -> list[Problem]:
    problems: list[Problem] = []
    for domain in project.domains:
        for entry in domain.entries():
            if entry.refers_to is None or entry.refers_to not in project.entries:
                continue  # 参照先が無いことは検査 h が報告する
            target = project.entries[entry.refers_to]
            source_dir = PurePosixPath(entry.path).parent
            target_dir = PurePosixPath(target.path).parent
            if target_dir != source_dir and target_dir in source_dir.parents:
                problems.append(
                    Problem(
                        "i",
                        entry.path,
                        f"refers_to の参照先 {target.id} は、祖先のディレクトリの {target.path} にある。"
                        f"参照される定義 ({target.id}) を、参照するファイルと同じディレクトリかその下に移す",
                        entry.refers_to_line,
                        entry.refers_to_column,
                    )
                )
    return problems
