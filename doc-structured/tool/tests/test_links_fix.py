"""サブコマンド links-fix (モジュール links_fix) のテスト。題材は、サンプルのプロジェクトの貸出のドメインの手書きのファイル。"""

import re
import subprocess

from tooltest import PYTHON, ProjectTestCase, clean_env

LOANS = "docs/domains/02-loans"
CONCEPT = f"{LOANS}/concept.md"
DESIGN = f"{LOANS}/design.md"
CHILD = f"{LOANS}/design/overdue_notice.md"
HEAD = '<a name="d-loans-concept"></a>\n\n# ドメイン `loans` の概念\n\n'
LOAN_DEFINITION = '[モデル「貸出」]: models.md#d-loans-m-loan "ドメイン `loans` のモデル「貸出」"'
DEFINITION_RE = re.compile(r"^\[[^\]]+\]: .*\n", re.MULTILINE)


class LinksFixTestCase(ProjectTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.copy_sample()

    def run_tool(self, *args: str):
        return subprocess.run(
            [PYTHON, "-m", "doc_structured", *args], cwd=self.project, env=clean_env(), capture_output=True, text=True
        )

    def read(self, relative: str) -> str:
        return (self.project / relative).read_text(encoding="utf-8")

    def assertCheckPasses(self) -> None:
        result = self.run_tool("check")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class FromNoDefinitionsTest(LinksFixTestCase):
    def test_adds_definitions_to_documents_without_them(self):
        originals = {path: self.read(path) for path in (CONCEPT, DESIGN, CHILD)}
        for path, text in originals.items():
            stripped = DEFINITION_RE.sub("", text).rstrip("\n") + "\n"
            self.assertNotIn("]: ", stripped)
            self.write(path, stripped)
        self.assertEqual(self.run_tool("check", "--only", "b").returncode, 1)

        result = self.run_tool("links-fix")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(sorted(re.findall(r"書き換えた: (\S+)", result.stdout)), sorted(originals))
        # 本文で最初に使った順に足すので、サンプルのファイル (その順に書いてある) と同じになる
        for path, text in originals.items():
            with self.subTest(path=path):
                self.assertEqual(self.read(path), text)
        self.assertCheckPasses()

        again = self.run_tool("links-fix")
        self.assertEqual((again.returncode, again.stdout), (0, "直すものは無かった\n"))


class RenameTest(LinksFixTestCase):
    def test_check_reports_stale_title_and_links_fix_rewrites_it_keeping_quotes(self):
        concept = self.read(CONCEPT).replace(
            '[予約]: models.md#d-loans-m-reservation "ドメイン `loans` のモデル「予約」"',
            "[予約]: models.md#d-loans-m-reservation 'ドメイン `loans` のモデル「予約」'",
        )
        self.write(CONCEPT, concept)
        self.assertCheckPasses()
        yaml_path = f"{LOANS}/reservations/reservation.yaml"
        self.write(yaml_path, self.read(yaml_path).replace("name_ja: 予約\n", "name_ja: 取り置き\n"))
        self.assertEqual(self.run_tool("generate").returncode, 0)

        check = self.run_tool("check")
        self.assertEqual(check.returncode, 1)
        self.assertIn(
            f"{CONCEPT}:24:1: 検査 b: 定義の行の title が、参照先の完全な名前「ドメイン `loans` のモデル「取り置き」」と違う",
            check.stdout,
        )
        self.assertIn(f"{CONCEPT}:25:1: 検査 b: 定義の行の title が、参照先の完全な名前", check.stdout)

        result = self.run_tool("links-fix")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, f"書き換えた: {CONCEPT}\n")
        text = self.read(CONCEPT)
        # 引用符の種類は変えない。本文 (ラベル [予約]) は変えない
        self.assertIn("[予約]: models.md#d-loans-m-reservation 'ドメイン `loans` のモデル「取り置き」'", text)
        self.assertIn(
            '[属性「前の予約」]: models.md#d-loans-m-reservation-a-previous "ドメイン `loans` のモデル「取り置き」の属性「前の予約」"',
            text,
        )
        self.assertIn("同じ図書の[予約]は", text)
        self.assertCheckPasses()

    def test_heading_change_rewrites_section_title(self):
        self.write(CONCEPT, self.read(CONCEPT).replace("## 返却期限", "## 返す期限"))
        check = self.run_tool("check")
        self.assertIn(f"{DESIGN}:16:1: 検査 b: 定義の行の title が、参照先の完全な名前", check.stdout)
        self.assertEqual(self.run_tool("links-fix").returncode, 0)
        self.assertIn(
            '[節「返却期限」]: concept.md#d-loans-concept-h-return_deadline "ドメイン `loans` のファイル `concept.md` の節「返す期限」"',
            self.read(DESIGN),
        )
        self.assertCheckPasses()

    def test_title_with_double_quote_is_escaped(self):
        self.write(CONCEPT, self.read(CONCEPT).replace("## 返却期限", '## 返却の "期限"'))
        self.assertEqual(self.run_tool("links-fix").returncode, 0)
        self.assertIn('の節「返却の \\"期限\\"」"', self.read(DESIGN))
        self.assertCheckPasses()


class FileAnchorTest(LinksFixTestCase):
    def test_adds_missing_file_anchor(self):
        self.write(CONCEPT, self.read(CONCEPT).replace('<a name="d-loans-concept"></a>\n\n', "", 1))
        self.assertEqual(self.run_tool("links-fix").returncode, 0)
        self.assertTrue(self.read(CONCEPT).startswith('<a name="d-loans-concept"></a>\n\n# ドメイン `loans` の概念\n'))
        self.assertCheckPasses()


class ScratchTestCase(LinksFixTestCase):
    """concept.md を書き換えるテスト。concept.md の節を参照する design.md は、リンクの無い内容にしておく。"""

    def setUp(self) -> None:
        super().setUp()
        self.write(DESIGN, '<a name="d-loans-design"></a>\n\n# ドメイン `loans` の設計\n')


class JudgmentTest(ScratchTestCase):
    def test_label_with_multiple_candidates_is_reported_and_chosen(self):
        self.write(CONCEPT, f"{HEAD}一覧は [`models.md`] にある。\n")
        result = self.run_tool("links-fix")
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            f"{CONCEPT}:5:5: ラベル `models.md` の参照先の候補が 3 件ある: "
            "d-catalog-models (ドメイン `catalog` のファイル `models.md`)、"
            "d-loans-models (ドメイン `loans` のファイル `models.md`)、"
            "d-members-models (ドメイン `members` のファイル `models.md`)。--choose で選ぶ",
            result.stdout,
        )
        self.assertIn("判断の要るものが 1 件ある", result.stdout)
        self.assertNotIn("]: ", self.read(CONCEPT))

        chosen = self.run_tool("links-fix", "--choose", CONCEPT, "`models.md`", "d-loans-models")
        self.assertEqual(chosen.returncode, 0, chosen.stdout + chosen.stderr)
        self.assertTrue(
            self.read(CONCEPT).endswith(
                'にある。\n\n[`models.md`]: models.md#d-loans-models "ドメイン `loans` のファイル `models.md`"\n'
            )
        )
        self.assertCheckPasses()

    def test_label_without_candidates_keeps_unused_definition_until_chosen(self):
        self.write(CONCEPT, f"{HEAD}[開館曰] を数える。\n\n" + '[開館日]: unclassified_app_terms.md#d-loans-ut-business_day "x"\n')
        result = self.run_tool("links-fix")
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"{CONCEPT}:5:1: ラベル 開館曰 の参照先の候補が無い。参照先の ID か外部の URL を --choose で渡す", result.stdout)
        self.assertIn(
            f"{CONCEPT}:7:1: ラベル 開館日 の定義の行が本文で使われていないが、定義の無いラベルが残っているので消さなかった",
            result.stdout,
        )
        # 消さなかった定義の行の title は書き換える
        self.assertIn("の未分類のアプリケーション用語「開館日」\"", self.read(CONCEPT))

        chosen = self.run_tool("links-fix", "--choose", CONCEPT, "開館曰", "https://example.com/calendar")
        self.assertEqual(chosen.returncode, 0, chosen.stdout + chosen.stderr)
        text = self.read(CONCEPT)
        self.assertIn("[開館曰]: https://example.com/calendar\n", text)
        self.assertNotIn("[開館日]:", text)
        self.assertCheckPasses()

    def test_choose_with_unknown_id_or_unused_label_fails_without_writing(self):
        self.write(CONCEPT, f"{HEAD}[休館日] を除く。\n")
        before = self.read(CONCEPT)
        for args, message in (
            (("--choose", CONCEPT, "休館日", "d-loans-ut-closed_day"), "--choose の参照先 d-loans-ut-closed_day が無い"),
            (("--choose", CONCEPT, "開館日", "d-loans-ut-business_day"), "--choose のラベル 開館日 は"),
            (("--choose", f"{LOANS}/models.md", "x", "d-loans-m-loan"), "手書きの Markdown でない"),
        ):
            with self.subTest(args=args):
                result = self.run_tool("links-fix", *args)
                self.assertEqual(result.returncode, 1)
                self.assertIn(message, result.stderr)
                self.assertEqual(self.read(CONCEPT), before)

    def test_duplicate_labels(self):
        same = f"{HEAD}[モデル「貸出」]\n\n{LOAN_DEFINITION}\n{LOAN_DEFINITION.replace('models.md#', './models.md#')}\n"
        self.write(CONCEPT, same)
        self.assertEqual(self.run_tool("links-fix").returncode, 0)
        self.assertEqual(self.read(CONCEPT), f"{HEAD}[モデル「貸出」]\n\n{LOAN_DEFINITION}\n")

        different = f"{HEAD}[モデル「貸出」]\n\n{LOAN_DEFINITION}\n[モデル「貸出」]: models.md#d-loans-m-reservation \"x\"\n"
        self.write(CONCEPT, different)
        result = self.run_tool("links-fix")
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"{CONCEPT}:8:1: ラベル モデル「貸出」 の定義の行が 7 行目にもあり、参照先が違う", result.stdout)

        chosen = self.run_tool("links-fix", "--choose", CONCEPT, "モデル「貸出」", "d-loans-m-loan")
        self.assertEqual(chosen.returncode, 0, chosen.stdout + chosen.stderr)
        self.assertEqual(self.read(CONCEPT), f"{HEAD}[モデル「貸出」]\n\n{LOAN_DEFINITION}\n")


class DefinitionBlockTest(ScratchTestCase):
    def test_keeps_reference_style_image_definitions(self):
        text = f"{HEAD}図は ![貸出の流れ][flow] のとおり。\n\n[flow]: images/flow.png 'x'\n"
        self.write(CONCEPT, text)
        result = self.run_tool("links-fix")
        self.assertEqual((result.returncode, result.stdout), (0, "直すものは無かった\n"))
        self.assertEqual(self.read(CONCEPT), text)
        self.assertCheckPasses()

    def test_label_used_only_as_collapsed_reference_is_kept(self):
        self.write(CONCEPT, f"{HEAD}[モデル「貸出」][]を書く。\n\n{LOAN_DEFINITION}\n")
        result = self.run_tool("links-fix")
        self.assertEqual((result.returncode, result.stdout), (0, "直すものは無かった\n"))
        self.write(CONCEPT, f"{HEAD}[モデル「貸出」][]を書く。\n")
        self.assertEqual(self.run_tool("links-fix").returncode, 0)
        self.assertIn(LOAN_DEFINITION, self.read(CONCEPT))

    def test_removes_unused_definitions(self):
        self.write(CONCEPT, f"{HEAD}本文\n\n{LOAN_DEFINITION}\n")
        self.assertEqual(self.run_tool("links-fix").returncode, 0)
        self.assertEqual(self.read(CONCEPT), f"{HEAD}本文\n")

    def test_moves_definition_in_middle_to_end(self):
        self.write(CONCEPT, f"{HEAD}[モデル「貸出」]\n\n{LOAN_DEFINITION}\n\n後の段落 [開館日]\n")
        self.assertEqual(self.run_tool("links-fix").returncode, 0)
        self.assertEqual(
            self.read(CONCEPT),
            f"{HEAD}[モデル「貸出」]\n\n後の段落 [開館日]\n\n{LOAN_DEFINITION}\n"
            '[開館日]: unclassified_app_terms.md#d-loans-ut-business_day "ドメイン `loans` の未分類のアプリケーション用語「開館日」"\n',
        )
        self.assertCheckPasses()

    def test_inserts_blank_line_before_definitions_in_paragraph(self):
        self.write(CONCEPT, f"{HEAD}[モデル「貸出」]\n{LOAN_DEFINITION}\n")
        self.assertEqual(self.run_tool("links-fix").returncode, 0)
        self.assertEqual(self.read(CONCEPT), f"{HEAD}[モデル「貸出」]\n\n{LOAN_DEFINITION}\n")
        self.assertCheckPasses()

    def test_keeps_order_and_blank_lines_written_by_people(self):
        text = (
            f"{HEAD}[開館日] と [モデル「貸出」]\n\n{LOAN_DEFINITION}\n\n"
            '[開館日]: unclassified_app_terms.md#d-loans-ut-business_day "ドメイン `loans` の未分類のアプリケーション用語「開館日」"\n'
        )
        self.write(CONCEPT, text)
        result = self.run_tool("links-fix")
        self.assertEqual((result.returncode, result.stdout), (0, "直すものは無かった\n"))
        self.assertEqual(self.read(CONCEPT), text)

    def test_keeps_crlf(self):
        self.write(CONCEPT, "")
        (self.project / CONCEPT).write_bytes(f"{HEAD}[モデル「貸出」]\n".replace("\n", "\r\n").encode("utf-8"))
        self.assertEqual(self.run_tool("links-fix").returncode, 0)
        self.assertEqual(
            (self.project / CONCEPT).read_bytes().decode("utf-8"),
            f"{HEAD}[モデル「貸出」]\n\n{LOAN_DEFINITION}\n".replace("\n", "\r\n"),
        )


class ArgumentsTest(LinksFixTestCase):
    def test_paths_limit_targets(self):
        self.write(CONCEPT, f"{HEAD}[モデル「貸出」]\n")
        self.write(DESIGN, self.read(DESIGN).replace('[貸出中]: ', '[貸出中] : '))
        design_before = self.read(DESIGN)
        result = self.run_tool("links-fix", CONCEPT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, f"書き換えた: {CONCEPT}\n")
        self.assertEqual(self.read(DESIGN), design_before)

    def test_unknown_path(self):
        result = self.run_tool("links-fix", f"{LOANS}/models.md")
        self.assertEqual(result.returncode, 1)
        self.assertIn("手書きの Markdown でない", result.stderr)

    def test_yaml_error_stops_without_writing(self):
        self.write(CONCEPT, f"{HEAD}[モデル「貸出」]\n")
        self.write("docs/domains/03-members/domain.yaml", "domain:\n  description: [x\n")
        result = self.run_tool("links-fix")
        self.assertEqual(result.returncode, 1)
        self.assertIn("検査 h: YAML として読めない", result.stderr)
        self.assertIn("何も直さなかった", result.stderr)
        self.assertEqual(self.read(CONCEPT), f"{HEAD}[モデル「貸出」]\n")
