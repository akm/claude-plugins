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
        # 最初の箇所 [モデル「予約」][予約] の文は [文][ラベル] の形なので、書き換えずに報告する
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(
            f"{CONCEPT}:17:6: 参照先 d-loans-m-reservation を最初に指す箇所の表示の文「モデル「予約」」が、"
            "書ける形のどれとも違う。書ける形に置き換えるか、文を修正する。書ける形:\n"
            "  モデル「取り置き」\n"
            "  ドメイン `loans` のモデル「取り置き」\n",
            result.stdout,
        )
        text = self.read(CONCEPT)
        # 引用符の種類は変えない
        self.assertIn("[予約]: models.md#d-loans-m-reservation 'ドメイン `loans` のモデル「取り置き」'", text)
        self.assertIn(
            '[属性「前の予約」]: models.md#d-loans-m-reservation-a-previous "ドメイン `loans` のモデル「取り置き」の属性「前の予約」"',
            text,
        )
        self.assertIn("同じ図書の[モデル「予約」][予約]は", text)
        # 利用者が選んだ書ける形に、文を手で直す
        self.write(CONCEPT, text.replace("[モデル「予約」][予約]", "[モデル「取り置き」][予約]"))
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
    def test_reports_file_anchor_with_other_id_without_adding(self):
        text = self.read(CONCEPT).replace('<a name="d-loans-concept"></a>', '<a name="d-loans-old"></a>', 1)
        self.write(CONCEPT, text)
        result = self.run_tool("links-fix", CONCEPT)
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            f"{CONCEPT}:1:1: 先頭のアンカーの ID d-loans-old が、ファイルの ID d-loans-concept と違う。"
            "アンカーを書き換えるかどうかを決めて、手で直す",
            result.stdout,
        )
        self.assertEqual(self.read(CONCEPT), text)

    def test_adds_missing_file_anchor(self):
        self.write(CONCEPT, self.read(CONCEPT).replace('<a name="d-loans-concept"></a>\n\n', "", 1))
        self.assertEqual(self.run_tool("links-fix").returncode, 0)
        self.assertTrue(self.read(CONCEPT).startswith('<a name="d-loans-concept"></a>\n\n# ドメイン `loans` の概念\n'))
        self.assertCheckPasses()


    def test_definitions_pointing_to_the_added_file_anchor_are_not_reported(self):
        # 同じ実行で足したファイルのアンカーを指す、ほかのファイルの定義の行を、参照先を求められないと報告しない (A2 (#215))
        self.write(CHILD, self.read(CHILD).replace('<a name="d-loans-design-f-overdue_notice"></a>\n\n', "", 1))
        result = self.run_tool("links-fix")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(self.read(CHILD).startswith('<a name="d-loans-design-f-overdue_notice"></a>\n\n# 延滞の通知\n'))
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

    def test_rewrites_href_whose_path_is_stale(self):
        self.write(CONCEPT, f"{HEAD}[モデル「貸出」]\n\n[モデル「貸出」]: terms.md#d-loans-m-loan 'x'\n")
        result = self.run_tool("links-fix")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            self.read(CONCEPT),
            f"{HEAD}[モデル「貸出」]\n\n[モデル「貸出」]: models.md#d-loans-m-loan 'ドメイン `loans` のモデル「貸出」'\n",
        )
        self.assertCheckPasses()

    def test_duplicate_definitions_with_same_stale_href(self):
        stale = "[モデル「貸出」]: terms.md#d-loans-m-loan \"x\""
        self.write(CONCEPT, f"{HEAD}[モデル「貸出」]\n\n{stale}\n{stale}\n")
        result = self.run_tool("links-fix")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.read(CONCEPT), f"{HEAD}[モデル「貸出」]\n\n{LOAN_DEFINITION}\n")
        self.assertCheckPasses()

    def test_reports_definition_whose_href_cannot_be_resolved(self):
        self.write(CONCEPT, f"{HEAD}[貸出]\n\n[貸出]: models.md#d-loans-m-rental \"x\"\n")
        result = self.run_tool("links-fix")
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            f"{CONCEPT}:7:1: ラベル 貸出 の定義の行の href から参照先を求められない "
            "(href の参照先 d-loans-m-rental のアンカーが無い)。--choose で参照先を渡す",
            result.stdout,
        )
        chosen = self.run_tool("links-fix", "--choose", CONCEPT, "貸出", "d-loans-m-loan")
        self.assertEqual(chosen.returncode, 0, chosen.stdout + chosen.stderr)
        self.assertCheckPasses()

    def test_removes_unused_definitions(self):
        self.write(CONCEPT, f"{HEAD}本文\n\n{LOAN_DEFINITION}\n")
        self.assertEqual(self.run_tool("links-fix").returncode, 0)
        self.assertEqual(self.read(CONCEPT), f"{HEAD}本文\n")

    def test_moves_definition_in_middle_to_end(self):
        self.write(CONCEPT, f"{HEAD}[モデル「貸出」]\n\n{LOAN_DEFINITION}\n\n後の段落 [開館日]\n")
        self.assertEqual(self.run_tool("links-fix").returncode, 0)
        self.assertEqual(
            self.read(CONCEPT),
            f"{HEAD}[モデル「貸出」]\n\n後の段落 [未分類の用語「開館日」][開館日]\n\n{LOAN_DEFINITION}\n"
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
            f"{HEAD}[未分類の用語「開館日」][開館日] と [モデル「貸出」]\n\n{LOAN_DEFINITION}\n\n"
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


class FirstUseTest(ScratchTestCase):
    """リンクの表示の文の書き換え: 最初の箇所は書ける形に、2 回目以降は名前が見える形に。"""

    BUSINESS_DAY = (
        '[開館日]: unclassified_app_terms.md#d-loans-ut-business_day "ドメイン `loans` の未分類のアプリケーション用語「開館日」"'
    )

    def fix(self, body: str, definitions: str = "") -> tuple[subprocess.CompletedProcess, str]:
        self.write(CONCEPT, f"{HEAD}{body}\n" + (f"\n{definitions}\n" if definitions else ""))
        result = self.run_tool("links-fix")
        text = self.read(CONCEPT)
        return result, text[len(HEAD) :].split("\n\n")[0]

    def test_first_shortcut_is_rewritten_omitting_shared_parents(self):
        result, body = self.fix(
            "[開館日]・[貸出状態]・[d-catalog-m-book]・[通知する日]・[`design/overdue_notice.md`]・[d-loans]"
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            body,
            "[未分類の用語「開館日」][開館日]・"
            "[モデル「貸出」の属性「貸出状態」][貸出状態]・"
            "[ドメイン `catalog` のモデル「図書」][d-catalog-m-book]・"
            "[ファイル `design/overdue_notice.md` の節「通知する日」][通知する日]・"
            "[ファイル `design/overdue_notice.md`][`design/overdue_notice.md`]・"
            "[ドメイン `loans`][d-loans]",
        )
        self.assertCheckPasses()
        again = self.run_tool("links-fix")
        self.assertEqual((again.returncode, again.stdout), (0, "直すものは無かった\n"))

    def test_shortcut_spanning_lines_is_rewritten(self):
        result, body = self.fix("前の文 [開館\n日] の後", self.BUSINESS_DAY.replace("[開館日]", "[開館 日]"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(body, "前の文 [未分類の用語「開館日」][開館 日] の後")
        self.assertCheckPasses()

    def test_writable_first_use_is_kept(self):
        body = "[ドメイン `loans` の未分類のアプリケーション用語「開館日」][開館日] と [ドメイン `loans`\nのモデル「貸出」][貸出]"
        result, fixed = self.fix(body, self.BUSINESS_DAY + "\n" + LOAN_DEFINITION.replace("[モデル「貸出」]", "[貸出]"))
        self.assertEqual((result.returncode, result.stdout), (0, "直すものは無かった\n"))
        self.assertEqual(fixed, body)

    def test_first_full_reference_is_reported_not_rewritten(self):
        body = "[延滞した貸出][貸出]に通知を送る。[モデル「貸出」][貸出]は 1 回の記録。"
        result, fixed = self.fix(body)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(
            f"{CONCEPT}:5:1: 参照先 d-loans-m-loan を最初に指す箇所の表示の文「延滞した貸出」が、書ける形のどれとも違う。"
            "書ける形に置き換えるか、文を修正する。書ける形:\n"
            "  モデル「貸出」\n"
            "  ドメイン `loans` のモデル「貸出」\n"
            "判断の要るものが 1 件ある (参照先を --choose で渡すか、本文を直して、もう一度実行する)\n",
            result.stdout,
        )
        # 定義の行は足し、2 回目以降の箇所は書き換える。最初の箇所の文は変えない
        self.assertEqual(fixed, "[延滞した貸出][貸出]に通知を送る。[貸出]は 1 回の記録。")
        self.write(CONCEPT, self.read(CONCEPT).replace("[延滞した貸出][貸出]に", "[モデル「貸出」][貸出]のうち、延滞したものに"))
        self.assertCheckPasses()

    def test_later_uses_show_the_name(self):
        definitions = "\n".join([
            LOAN_DEFINITION.replace("[モデル「貸出」]", "[貸出]"),
            LOAN_DEFINITION,
            LOAN_DEFINITION.replace("[モデル「貸出」]", "[d-loans-m-loan]"),
            LOAN_DEFINITION.replace("[モデル「貸出」]", "[貸出の記録]"),
            '[d-loans]: README.md#d-loans "ドメイン `loans`"',
        ])
        result, body = self.fix(
            "[モデル「貸出」][貸出] [d-loans]。"
            "[モデル「貸出」][貸出] [モデル「貸出」] [d-loans-m-loan] [D-Loans-M-Loan] [ドメイン `loans` のモデル「貸出」][d-loans-m-loan] "
            "[延滞した貸出][貸出] [貸出の記録] [d-loans] [ドメイン `loans`][d-loans]",
            definitions,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            body,
            "[モデル「貸出」][貸出] [ドメイン `loans`][d-loans]。"
            "[貸出] [貸出][モデル「貸出」] [貸出][d-loans-m-loan] [貸出][D-Loans-M-Loan] [貸出][d-loans-m-loan] "
            "[延滞した貸出][貸出] [貸出の記録] [d-loans] [ドメイン `loans`][d-loans]",
        )

    def test_first_use_is_counted_per_target(self):
        definitions = LOAN_DEFINITION + "\n" + LOAN_DEFINITION.replace("[モデル「貸出」]", "[貸出]")
        result, body = self.fix("[貸出] と [モデル「貸出」]", definitions)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # 参照先を最初に指すのは [貸出]。ラベル モデル「貸出」 を最初に使う箇所は 2 回目以降として扱う
        self.assertEqual(body, "[モデル「貸出」][貸出] と [貸出][モデル「貸出」]")
        self.assertCheckPasses()

    def test_heading_with_spaces_passes_check_after_links_fix(self):
        # 見出しの文に全角空白と連続する空白がある節を指すリンクも、links-fix の後に検査 b が成功する
        self.write(
            CONCEPT,
            f'{HEAD}<a name="d-loans-concept-h-due"></a>\n\n## 返却　期限  の数え方\n\n[期限] と [節「返却 期限 の数え方」][期限]\n\n'
            '[期限]: #d-loans-concept-h-due "x"\n',
        )
        result = self.run_tool("links-fix")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("[節「返却　期限  の数え方」][期限] と [返却　期限  の数え方][期限]", self.read(CONCEPT))
        self.assertCheckPasses()
        again = self.run_tool("links-fix")
        self.assertEqual((again.returncode, again.stdout), (0, "直すものは無かった\n"))

    def test_documents_with_invalid_first_uses_pass_check_after_links_fix(self):
        # クローズ条件: links-fix を実行すると、検査 b (初出) が成功する (定義の行が無い状態から)
        for path in (CONCEPT, CHILD):
            text = self.read(path)
            text = re.sub(r"\[([^\[\]]+)\]\[([^\[\]]+)\]", r"[\2]", DEFINITION_RE.sub("", text)).rstrip("\n") + "\n"
            self.write(path, text)
        self.assertEqual(self.run_tool("check", "--only", "b").returncode, 1)
        result = self.run_tool("links-fix")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertCheckPasses()


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
