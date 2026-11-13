"""検査 k (モジュール length) のテスト。題材は、サンプルのプロジェクトの貸出のドメインの手書きのファイル。"""

import subprocess

from doc_structured.documents import load_documents
from doc_structured.domains import load_project
from doc_structured.length import check_length
from tooltest import PYTHON, ProjectTestCase, clean_env

CONCEPT = "docs/domains/02-loans/concept.md"
HEAD = '<a name="d-loans-concept"></a>\n\n# ドメイン `loans` の概念\n'
REASON = "<!-- 行数が上限を超える理由: 貸出の規則が 1 つのまとまりで、分けると読む人が行き来する -->\n"


def body(lines: int, head: str = HEAD) -> str:
    """head を含めて lines 行の本文。"""
    count = lines - head.count("\n")
    return head + "".join(f"本文の {i} 行目\n" for i in range(count))


class LengthTest(ProjectTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.copy_sample()

    def problems(self, text: str, path: str = CONCEPT) -> list[tuple[int | None, str]]:
        self.write(path, text)
        project, _ = load_project(self.project)
        index, _ = load_documents(self.project, project)
        return [(p.line, p.message) for p in check_length(index) if p.path == path]

    def test_sample_passes(self):
        project, _ = load_project(self.project)
        index, _ = load_documents(self.project, project)
        self.assertEqual(check_length(index), [])

    def test_100_lines_pass_and_101_lines_fail(self):
        self.assertEqual(self.problems(body(100)), [])
        self.assertEqual(
            self.problems(body(101)),
            [
                (
                    None,
                    "手書きの Markdown が 101 行ある (上限は 100 行)。話題ごとにファイルを分けるか、"
                    "「#」の見出しの次の行に理由のコメント <!-- 行数が上限を超える理由: <理由> --> を書く",
                )
            ],
        )

    def test_reason_comment_after_heading_passes(self):
        self.assertEqual(self.problems(body(150, HEAD + REASON)), [])
        self.assertEqual(self.problems(body(150, HEAD + "\n" + REASON)), [])

    def test_reason_comment_in_other_place_fails(self):
        text = body(150) + REASON
        self.assertEqual(
            self.problems(text), [(151, "理由のコメントは、「#」の見出しの次の行に書く (151 行。上限は 100 行)")]
        )

    def test_empty_reason_fails(self):
        self.assertEqual(
            self.problems(body(150, HEAD + "<!-- 行数が上限を超える理由:  -->\n")), [(4, "理由のコメントの理由が空")]
        )

    def test_trailing_definitions_are_not_counted(self):
        text = body(99) + "[開館日]\n\n" + "".join(
            f'[d{i}]: unclassified_app_terms.md#d-loans-ut-business_day "x"\n\n' for i in range(30)
        )
        self.assertEqual(self.problems(text), [])

    def test_code_blocks_comments_and_blank_lines_in_body_are_counted(self):
        # 本文 90 行 + 空行・コードブロック (3 行)・空行・コメント・空行の 7 行 + 本文 4 行 = 101 行
        text = body(90) + "\n```\nコード\n```\n\n<!-- コメント -->\n\n" + "後の本文\n" * 4
        self.assertEqual(self.problems(text)[0][1].split("。")[0], "手書きの Markdown が 101 行ある (上限は 100 行)")

    def test_child_file(self):
        path = "docs/domains/02-loans/design/overdue_notice.md"
        head = '<a name="d-loans-design-f-overdue_notice"></a>\n\n# 延滞の通知\n'
        self.assertEqual(len(self.problems(body(101, head), path)), 1)

    def test_check_k_runs_with_yaml_errors(self):
        self.write(CONCEPT, body(101))
        self.write("docs/domains/03-members/domain.yaml", "domain:\n  description: [x\n")
        result = subprocess.run(
            [PYTHON, "-m", "doc_structured", "check"], cwd=self.project, env=clean_env(), capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"{CONCEPT}: 検査 k: 手書きの Markdown が 101 行ある", result.stdout)
        self.assertIn("YAML に誤りがあるので、検査 a・b・c-2・i を実行しなかった", result.stdout)
