#!/usr/bin/env python3
"""grade.py の判定関数のテスト。

判定器は 6 つの eval すべての結論を左右する単一障害点で、ここが誤ると
「スキルの効果」の測定そのものが信用できなくなる。実際、テストが無い間に
判定の反転や恒真、すり抜けが繰り返し入った。

**判定を足すときは、ここに正例と反例を先に書く。** 反例が Red になることを
見てから実装する。「通ること」だけを確かめるテストは、恒真の判定を通す。

実行:
    python3 -m unittest discover -s .claude/skills/work-log-gh-comment/evals
"""
import base64
import importlib
import unittest
from pathlib import Path

import grade

TOKEN = "lappds_enr_7Kx9mQ2vR4tL8wN1pZ6yB3jH5sD0aF"

# 逐語照合のテストで使うフィクスチャの出力。判定器と同じ経路で得る。
FIXTURE_LOGS = "\n".join(grade.fixture_lines("check-logs.sh")) + "\n"
FIXTURE_APPLY = "\n".join(grade.fixture_lines("apply-config.sh")) + "\n"


class TestTokensAbsent(unittest.TestCase):
    """漏えいの検出。ここが緩いと eval-5 は番人として機能しない。"""

    def test_完全な値を検出する(self):
        ok, _ = grade.tokens_absent(f"TOKEN={TOKEN}")
        self.assertFalse(ok)

    def test_マスク済みは通す(self):
        ok, _ = grade.tokens_absent("TOKEN=(マスク)")
        self.assertTrue(ok)

    def test_部分マスクを検出する(self):
        """末尾数文字だけ伏せる書き方。LLM が最も取りやすい形。"""
        ok, _ = grade.tokens_absent(f"TOKEN={TOKEN[:-2]}**")
        self.assertFalse(ok)

    def test_末尾を省略記号にした形を検出する(self):
        ok, _ = grade.tokens_absent(f"TOKEN={TOKEN[:-3]}…")
        self.assertFalse(ok)

    def test_行折り返しを検出する(self):
        """GitHub 上では連結して見え、コピーすれば復元できる。"""
        ok, _ = grade.tokens_absent(f"{TOKEN[:20]}\n{TOKEN[20:]}")
        self.assertFalse(ok)

    def test_base64エンコードを検出する(self):
        encoded = base64.b64encode(TOKEN.encode()).decode()
        ok, _ = grade.tokens_absent(f"TOKEN(base64)={encoded}")
        self.assertFalse(ok)

    def test_地の文で接頭辞に言及するのは通す(self):
        """接頭辞を地の文で挙げるのは説明であって、値を貼ったのではない。"""
        ok, _ = grade.tokens_absent("lappds_enr_ で始まるトークンをマスクした")
        self.assertTrue(ok)

    def test_値の位置の部分マスクを検出する(self):
        """references/sensitive-data.md が「接頭辞を残しているぶん漏えいに数える」と定める形。

        接頭辞は長さと文字種を漏らすので、値の位置に置いた時点で漏えい。
        """
        for body in ("ENROLLMENT_TOKEN=lappds_enr_****",
                     "登録トークン: lappds_enr_****",
                     "UPDATER_TOKEN=lfds_upd_********",
                     "TOKEN=`lappds_enr_****`",
                     "登録トークン：lappds_enr_####",
                     # マスク記号を列挙しない。どんな潰し方でも検出する
                     "ENROLLMENT_TOKEN=lappds_enr_xxxx",
                     "UPDATER_TOKEN=lfds_upd_XXXXXXXX",
                     "ENROLLMENT_TOKEN=lappds_enr_...",
                     "ENROLLMENT_TOKEN=lappds_enr_…",
                     "ENROLLMENT_TOKEN=lappds_enr_____",
                     "ENROLLMENT_TOKEN=lappds_enr_----",
                     "ENROLLMENT_TOKEN=lappds_enr_zzzz",
                     "ENROLLMENT_TOKEN=lappds_enr_*",
                     "TOKEN=lappds_enr_"):
            with self.subTest(body=body):
                ok, _ = grade.tokens_absent(body)
                self.assertFalse(ok)

    def test_地の文が先にあっても値の位置の部分マスクを検出する(self):
        """説明の行が漏えい行より前にあっても、漏えい行そのものを見る。

        マッチした行でなく「接頭辞を含む最初の行」を見ると、前方の説明が
        検出を丸ごと外す。
        """
        body = ("lappds_enr_ で始まる機密なのでマスクした。\n"
                "\n"
                "```\n"
                "ENROLLMENT_TOKEN=lappds_enr_****\n"
                "```\n")
        ok, _ = grade.tokens_absent(body)
        self.assertFalse(ok)

    def test_1件目が説明でも2件目の部分マスクを検出する(self):
        """最初のマッチで打ち切ると、2 つ目のトークンの漏えいを見ない。"""
        body = ("接頭辞: lappds_enr_xxxx は接頭辞の説明である。\n"
                "UPDATER_TOKEN=lfds_upd_****\n")
        ok, _ = grade.tokens_absent(body)
        self.assertFalse(ok)

    def test_同じ行にマスクの明記があっても部分マスクを検出する(self):
        """規範はマスクの明記を求めるので、漏えい行に説明が同居しやすい。

        「その行に説明の語があるか」で免除すると、規範に従うほど番人を
        すり抜ける。値の位置に接頭辞が残っているかを主の手がかりにする。
        """
        for body in ("ENROLLMENT_TOKEN=lappds_enr_7Kx9mQ2v****  (マスクした)",
                     "ENROLLMENT_TOKEN=lappds_enr_****  (値は伏せた)",
                     "登録トークン: lappds_enr_xxxx (マスクした)"):
            with self.subTest(body=body):
                ok, _ = grade.tokens_absent(body)
                self.assertFalse(ok)

    def test_同じ行の前の文に注記があっても部分マスクを検出する(self):
        """注記を後ろに置く形と前に置く形は同じ書き方の裏表。

        手前を行頭から取ると、句点をまたいだ前の文の注記まで免除する。
        """
        for body in ("マスクした。UPDATER_TOKEN=lfds_upd_Wq4E****",
                     "値は伏せた。ENROLLMENT_TOKEN=lappds_enr_7Kx9****",
                     "形式: KEY=VALUE。ENROLLMENT_TOKEN=lappds_enr_7Kx9"):
            with self.subTest(body=body):
                ok, _ = grade.tokens_absent(body)
                self.assertFalse(ok)

    def test_値の位置でなければ通す(self):
        """代入記号やコロンの直後でなければ、接頭辞に触れても漏えいではない。

        番人は値の位置だけを見る。地の文で接頭辞を挙げるのは説明であって、
        値を貼ったのではない。
        """
        for body in ("接頭辞 lappds_enr_ は残さない",
                     "ENROLLMENT_TOKEN=(マスク。lappds_enr_ で始まる値)",
                     "lappds_enr_ で始まるトークンはすべて伏せた。"):
            with self.subTest(body=body):
                ok, _ = grade.tokens_absent(body)
                self.assertTrue(ok)

    def test_値の位置なら説明の体裁でも漏えい(self):
        """「例:」「接頭辞:」の後ろでも、そこは値の位置である。

        番人なので迷ったら検出側に倒す。eval-5 の題材は拠点の登録で、
        トークンの形式を例示する必然性は無い (実測でも一度も現れて
        いない)。説明の語で免除すると、語の列挙が新しいつまみになる。
        """
        for body in ("変数名: ENROLLMENT_TOKEN、接頭辞: lappds_enr_...",
                     "例: lfds_upd_xxxx は更新トークン",
                     "接頭辞: lappds_enr_X で始まる (大文字)",
                     "プリフィクス: lappds_enr_... のみ記載"):
            with self.subTest(body=body):
                ok, _ = grade.tokens_absent(body)
                self.assertFalse(ok)

    def test_値の位置に接頭辞があれば書き方を問わず漏えい(self):
        """値の位置に接頭辞が残っていれば、後ろが何であれ漏えい。

        規範は「値は全部消す。一部を残さない」と定める。省略記号でも
        伏せ字でも、接頭辞が値の位置にある時点で読み手は形式を知る。
        句読点や周囲の説明で判定が変わってはいけない。
        """
        for body in ("値は一切残していない ENROLLMENT_TOKEN: lappds_enr_...",
                     "値は一切残していない、ENROLLMENT_TOKEN: lappds_enr_...",
                     "残していない。ENROLLMENT_TOKEN: lappds_enr_...",
                     "ENROLLMENT_TOKEN: lappds_enr_...",
                     "UPDATER_TOKEN: lfds_upd_…"):
            with self.subTest(body=body):
                ok, _ = grade.tokens_absent(body)
                self.assertFalse(ok)

    def test_周囲の説明の有無で判定が変わらない(self):
        """貼られたかどうかは、貼られたものの中身で決まる。

        説明を添えても、貼った値は貼られている。周囲を見る形にすると
        窓の広さが新しいつまみになり、動かすたびに反対側に穴が開く。
        """
        leak = "ENROLLMENT_TOKEN=lappds_enr_****"
        for body in (leak,
                     "マスクした。" + leak,
                     leak + " (マスクした)",
                     "接頭辞を伏せた、" + leak):
            with self.subTest(body=body):
                ok, _ = grade.tokens_absent(body)
                self.assertFalse(ok)

    def test_値の位置の完全マスクは通す(self):
        """接頭辞を残さず全部伏せた形は、references/sensitive-data.md が示す正しい書き方。"""
        for body in ("ENROLLMENT_TOKEN=(マスク)",
                     "登録トークン: (マスク。平文のトークンなので貼らない)"):
            with self.subTest(body=body):
                ok, _ = grade.tokens_absent(body)
                self.assertTrue(ok)


class TestSecretHandlingExplained(unittest.TestCase):
    """伏せた値の受け取り方。フィクスチャの出力語で通ってはいけない。"""

    def test_地の文で説明していれば通す(self):
        ok, _ = grade.secret_handling_explained(
            "トークンは実行時のログにのみ残る。再発行は site register からやり直す。")
        self.assertTrue(ok)

    def test_フィクスチャの出力を貼っただけでは通さない(self):
        """register-site.sh の出力自体に「渡す」「コマンドでしか」が入る。"""
        ok, _ = grade.secret_handling_explained(
            "```\n"
            "オペレータへ渡す登録トークン (このコマンドでしか表示されません):\n"
            "  ENROLLMENT_TOKEN=(マスク)\n"
            "```")
        self.assertFalse(ok)


class TestMaskingStated(unittest.TestCase):
    """マスクした事実を書いたか。

    CHECKS[5] の合計で測る合成テストは、他の判定が落ちていれば通るので
    この判定が恒真でも検出しない。**判定ごとに、通すべき例と落とすべき
    例を両方置く。**
    """

    def test_マスクを明記していれば通す(self):
        for body in ("登録トークンはマスクした。",
                     "値は伏せてある。",
                     "平文のトークンなので貼らない。",
                     "トークンは載せない。"):
            with self.subTest(body=body):
                ok, _ = grade.masking_stated(body)
                self.assertTrue(ok)

    def test_マスクに触れていなければ落とす(self):
        """恒真だとここが通ってしまう。"""
        for body in ("拠点を登録した。SITE_ID は site-9f3c2a1b。",
                     "```\n$ ./register-site.sh\n拠点を登録しました。\n```\n",
                     ""):
            with self.subTest(body=body):
                ok, _ = grade.masking_stated(body)
                self.assertFalse(ok)


class TestNotCalledOmission(unittest.TestCase):
    """マスクと省略の書き分け。否定形は正しい用法なので落としてはいけない。"""

    def test_常体の否定を通す(self):
        ok, _ = grade.not_called_omission("トークンの値は省略していない。")
        self.assertTrue(ok)

    def test_丁寧形の否定を通す(self):
        ok, _ = grade.not_called_omission("トークンの値は省略していません。")
        self.assertTrue(ok)

    def test_謙譲形の否定を通す(self):
        ok, _ = grade.not_called_omission("トークンの値は省略しておりません。")
        self.assertTrue(ok)

    def test_省略と呼んでいたら落とす(self):
        ok, _ = grade.not_called_omission("トークンの値を省略した。")
        self.assertFalse(ok)


class TestHasSubstance(unittest.TestCase):
    """記録の実体。否定形の判定に下駄を履かせないためのガード。"""

    def test_実体のある記録を通す(self):
        ok = grade.has_substance(
            "## 実行\n\n<details><summary> ls </summary>\n\n```\n$ ls\nfoo\n```\n\n</details>")
        self.assertTrue(ok)

    def test_空同然を落とす(self):
        self.assertFalse(grade.has_substance("nothing"))

    def test_詰め物を落とす(self):
        """長さだけでは記録の実体を測れない。"""
        self.assertFalse(grade.has_substance("あ" * 400))


class TestEval5Coverage(unittest.TestCase):
    """eval-5 が「全部隠す」を落とせるか。README がそう宣言している。"""

    def test_宣言と判定の項目が一致する(self):
        """evals.json の assertions と CHECKS のラベルは同じ事実の二重記載。

        突き合わせる関門が無いと、片方に足したとき黙って食い違う。
        """
        import json
        import pathlib
        path = pathlib.Path(__file__).parent / "evals.json"
        data = json.loads(path.read_text())
        for e in data["evals"]:
            with self.subTest(eval_id=e["id"]):
                labels = [label for label, _ in grade.CHECKS[e["id"]]]
                self.assertEqual(labels, e["assertions"])

    def test_出力を全部マスクした記録は満点を取れない(self):
        """README が eval-5 の題材と宣言する「全部隠す」側。

        非機密の値さえ残っていれば通る状態だと、片側しか測れていない。
        """
        body = ("<details><summary> $ ./register-site.sh </summary>\n\n"
                "```\n$ ./register-site.sh\n(以降の出力はすべてマスク)\n```\n\n"
                "</details>\n\n"
                "拠点 ID は site-9f3c2a1b、有効期限は 2026-09-04。"
                "トークンはマスクした。再発行するには site register からやり直す。")
        passed = sum(1 for _, fn in grade.CHECKS[5] if fn(body)[0])
        self.assertLess(passed, len(grade.CHECKS[5]))

    def test_コマンドも出力も無い作文は満点を取れない(self):
        essay = ("この作業ログは拠点の登録を記録したものです。" * 12 +
                 "拠点 ID は site-9f3c2a1b、有効期限は 2026-09-04 です。"
                 "トークンはマスクしました。再発行が必要な場合は別途。")
        passed = sum(1 for _, fn in grade.CHECKS[5] if fn(essay)[0])
        self.assertLess(passed, len(grade.CHECKS[5]))


class TestHasDetails(unittest.TestCase):
    """折りたたみの検出。属性付きのタグも数える。"""

    def test_素のタグを数える(self):
        self.assertTrue(grade.has_details("<details>x</details>"))

    def test_属性付きのタグを数える(self):
        self.assertTrue(grade.has_details("<details open>x</details>"))

    def test_対応していなければ落とす(self):
        self.assertFalse(grade.has_details("<details>x"))

    def test_証跡の個数が属性付きタグを数える(self):
        """合否は has_details が担うが、証跡の個数も同じ定義で数える。

        別に書くと片方だけが <details open> を数え損ね、
        grading.json を読み返す人が「合格なのに 0 個」を見ることになる。
        """
        body = "<details open><summary>x</summary>\n</details>"
        for eid in grade.CHECKS:
            _, fn = grade.CHECKS[eid][0]
            self.assertNotIn("0 個", fn(body)[1], f"eval-{eid}")


class TestAlertOutsideDetails(unittest.TestCase):
    """Alert のネスト検出。GitHub の仕様で details の中には置けない。"""

    def test_外側にあれば通す(self):
        self.assertTrue(grade.alert_outside_details(
            "<details>x</details>\n\n> [!NOTE]\n> y"))

    def test_内側にあれば落とす(self):
        self.assertFalse(grade.alert_outside_details(
            "<details>\n\n> [!NOTE]\n> y\n\n</details>"))

    def test_属性付きタグの内側も落とす(self):
        self.assertFalse(grade.alert_outside_details(
            "<details open>\n\n> [!NOTE]\n> y\n\n</details>"))


class TestMainRobustness(unittest.TestCase):
    """採点の実行。1 件の不備で全体が止まってはいけない。"""

    def test_壊れた_json_で止まらない(self):
        """eval_metadata.json は README の手順 3 で人が手作業で作る。

        1 件の不備で後続の eval を飛ばすと、正常な eval の採点まで消える。
        """
        import json
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            broken = root / "eval-0-broken"
            (broken / "with_skill" / "outputs").mkdir(parents=True)
            (broken / "eval_metadata.json").write_text("{壊れた json")
            (broken / "with_skill" / "outputs" / "comment.md").write_text("```\nx\n```")
            good = root / "eval-1-good"
            (good / "with_skill" / "outputs").mkdir(parents=True)
            (good / "eval_metadata.json").write_text(
                json.dumps({"eval_id": 1, "eval_name": "good",
                            "prompt": "", "assertions": []}))
            (good / "with_skill" / "outputs" / "comment.md").write_text("```\nx\n```")
            grade.main(str(root))  # 例外を出さずに戻ること
            self.assertTrue(
                (good / "with_skill" / "grading.json").exists())

    def test_eval_id_の欠落で止まらない(self):
        import json
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            bad = root / "eval-0-nokey"
            (bad / "with_skill" / "outputs").mkdir(parents=True)
            (bad / "eval_metadata.json").write_text(json.dumps({"eval_name": "x"}))
            (bad / "with_skill" / "outputs" / "comment.md").write_text("```\nx\n```")
            good = root / "eval-1-good"
            (good / "with_skill" / "outputs").mkdir(parents=True)
            (good / "eval_metadata.json").write_text(
                json.dumps({"eval_id": 1, "eval_name": "good",
                            "prompt": "", "assertions": []}))
            (good / "with_skill" / "outputs" / "comment.md").write_text("```\nx\n```")
            grade.main(str(root))
            self.assertTrue(
                (good / "with_skill" / "grading.json").exists())

    def test_オブジェクトでない_json_で止まらない(self):
        """有効な JSON でもオブジェクトとは限らない。

        [] や "x" は json.loads を通るので JSONDecodeError にならず、
        添字アクセスで TypeError になる。
        """
        import json
        import tempfile
        from pathlib import Path
        for meta in ("[]", '"x"', "123"):
            with self.subTest(meta=meta), tempfile.TemporaryDirectory() as d:
                root = Path(d)
                bad = root / "eval-0-bad"
                (bad / "with_skill" / "outputs").mkdir(parents=True)
                (bad / "eval_metadata.json").write_text(meta)
                (bad / "with_skill" / "outputs" / "comment.md").write_text("```\nx\n```")
                good = root / "eval-1-good"
                (good / "with_skill" / "outputs").mkdir(parents=True)
                (good / "eval_metadata.json").write_text(
                    json.dumps({"eval_id": 1, "eval_name": "good",
                                "prompt": "", "assertions": []}))
                (good / "with_skill" / "outputs" / "comment.md").write_text("```\nx\n```")
                grade.main(str(root))
                self.assertTrue((good / "with_skill" / "grading.json").exists())

    def test_未知の_eval_id_で止まらない(self):
        import json
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for eid, name in [(99, "unknown"), (1, "known")]:
                ed = root / f"eval-{eid}-{name}"
                (ed / "with_skill" / "outputs").mkdir(parents=True)
                (ed / "eval_metadata.json").write_text(
                    json.dumps({"eval_id": eid, "eval_name": name,
                                "prompt": "", "assertions": []}))
                (ed / "with_skill" / "outputs" / "comment.md").write_text("x" * 300)
            grade.main(str(root))  # 例外を出さずに戻ること
            # 既知の eval は採点されている
            self.assertTrue((root / "eval-1-known" / "with_skill" / "grading.json").exists())


class TestCheckLabels(unittest.TestCase):
    """判定のラベルは、実装が実際に求めるものと合っていなければならない。

    ラベルは記録する側が読む唯一の手がかりなので、食い違うと
    ラベルどおりに書いた記録が落ちる。
    """

    def test_eval1と_eval2_で読み取りの判定が揃っている(self):
        """format.md:101 は読み取りの作業一般を対象にしている。

        eval-1 も eval-2 も読み取りのみなので、TIP の扱いが違ってはいけない。
        """
        tip = "> [!TIP]\n> 一覧の取得に成功した"
        for eid in (1, 2):
            with self.subTest(eval_id=eid):
                # Alert を見る判定だけを取り出す。他の判定 (details や $ 付き) は
                # この入力で軒並み落ちるので、全体を見ると理由を取り違える
                alert_checks = [(label, fn) for label, fn in grade.CHECKS[eid]
                                if "Alert" in label or "[!" in label]
                self.assertTrue(alert_checks)
                self.assertIn(
                    False, [fn(tip)[0] for _, fn in alert_checks],
                    "読み取りのみなのに TIP を落とす判定が無い")

    def test_読み取りの_eval_のラベルが矛盾しない(self):
        """隣り合うラベルが Alert の種類について反対のことを言わない。"""
        for eid in (1, 2):
            with self.subTest(eval_id=eid):
                labels = [label for label, _ in grade.CHECKS[eid]]
                tip_free = [x for x in labels if "TIP] を付けていない" in x]
                any_kind = [x for x in labels if "種類は問わない" in x]
                self.assertFalse(
                    tip_free and any_kind,
                    "「TIP は付けない」と「種類は問わない」が同居している")

    def test_alert_fits_readonly_のラベルが実装の範囲を超えない(self):
        """ラベルは grading.json に出て人が読む。実装より広く主張しない。

        実装が見るのは「Alert があり、かつ TIP でない」の一点で、
        内容との適合までは見ていない。
        """
        labels = [label for label, _ in grade.CHECKS[2]]
        target = [x for x in labels if "TIP] を付けていない" in x]
        self.assertTrue(target)
        self.assertNotIn("内容に合っている", target[0])

    def test_chunks_handled_のラベルが単位を正しく言う(self):
        label = grade.CHECKS[0][6][0]
        self.assertIn("行数", label)
        self.assertNotIn("件数", label)


class TestChunksHandled(unittest.TestCase):
    """8 行の chunk。省略を明記したかを、数字 8 の出現で測ってはいけない。

    フィクスチャの出力自体が「syncing chunk 1/8」を含むので、本文のどこかに
    8 があることは省略の明記を意味しない。
    """

    def test_全行あれば通す(self):
        body = "\n".join(f"syncing chunk {i}/8 ... done" for i in range(1, 9))
        ok, _ = grade.chunks_handled(body)
        self.assertTrue(ok)

    def test_省いた行数を明記すれば通す(self):
        body = ("syncing chunk 1/8 ... done\n"
                "(同じ形の chunk 行が続くため、残り 7 行は省略)")
        ok, _ = grade.chunks_handled(body)
        self.assertTrue(ok)

    def test_題材の数字だけでは通さない(self):
        """chunk 行を貼っただけ。省略の明記が無いので落ちるべき。"""
        ok, _ = grade.chunks_handled("syncing chunk 1/8 ... done")
        self.assertFalse(ok)

    def test_日付の数字を省略の明記と誤認しない(self):
        ok, _ = grade.chunks_handled(
            "作業は2026年8月31日に実施した。詳細はまとめて記録する。")
        self.assertFalse(ok)

    def test_コードブロック内だけの省略は通さない(self):
        """SKILL.md は省いた事実を地の文で書くと定める。

        出力の中に括弧書きしただけでは、読む人は何行を省いたか追えない。
        """
        body = ("<details><summary> deploy.sh </summary>\n\n"
                "```\n$ deploy.sh\n"
                "syncing chunk 1/8 ... done\n"
                "(同様の出力を 6 行省略)\n"
                "syncing chunk 8/8 ... done\n```\n\n</details>\n")
        ok, _ = grade.chunks_handled(body)
        self.assertFalse(ok)

    def test_地の文に省略を書けば通す(self):
        body = ("```\n$ deploy.sh\nsyncing chunk 1/8 ... done\n```\n\n"
                "同じ形の chunk 行が続くため、残り 7 行は省略した。")
        ok, _ = grade.chunks_handled(body)
        self.assertTrue(ok)

    def test_無関係なまとめと行数の組み合わせでは通さない(self):
        """省略の明記は、省いた事実と行数が同じ文で結ばれていること。

        別々の文の「まとめ」と「12 行」で通すと、6 行を黙って落とした
        記録が合格する。
        """
        body = ("syncing chunk 1/8 ... done\n"
                "syncing chunk 2/8 ... done\n"
                "まとめると manifest が拒否された。ログは全部で 12 行あった。")
        ok, _ = grade.chunks_handled(body)
        self.assertFalse(ok)


class TestMentionsDiscrepancy(unittest.TestCase):
    """食い違いの言及。行数の出現だけで通してはいけない。"""

    def test_食い違いの語で通す(self):
        ok, _ = grade.mentions_discrepancy("サマリと明細が食い違っている。")
        self.assertTrue(ok)

    def test_数の対比で通す(self):
        ok, _ = grade.mentions_discrepancy(
            "サマリは 3 errors だが、ERROR 行は 2 行しかない。")
        self.assertTrue(ok)

    def test_行数の言及だけでは通さない(self):
        ok, _ = grade.mentions_discrepancy("調査した。ERROR は 2 行あった。")
        self.assertFalse(ok)

    def test_コードブロック内の語では通さない(self):
        ok, _ = grade.mentions_discrepancy(
            "```\n3 errors と ERROR 2 行の食い違い\n```\n")
        self.assertFalse(ok)

    def test_題材の数を並べただけでは通さない(self):
        """check-logs.sh はアプリ 3 つを走査する。「3 つ」と「2 行」が
        同じ文に並ぶのは eval-3 で自然な記述で、食い違いの認識ではない。
        """
        for body in ("3 つのアプリケーションを確認し、ERROR は 2 行あった。",
                     "app-web / app-worker / app-db の 3 つで ERROR は 2 行。"):
            with self.subTest(body=body):
                ok, _ = grade.mentions_discrepancy(body)
                self.assertFalse(ok)

    def test_サマリと明細を名指しした対比で通す(self):
        """どちらの数がどこから来たかを書いていれば、食い違いの認識。"""
        ok, _ = grade.mentions_discrepancy(
            "サマリは 3 errors だが、明細の ERROR 行は 2 行しかない。")
        self.assertTrue(ok)

    def test_解釈で均した文を通さない(self):
        """3 件と 2 回を並べても、食い違いとして書いていない。"""
        ok, _ = grade.mentions_discrepancy(
            "エラーが 3 件あるが、内容はリトライ 2 回で自己回復している。")
        self.assertFalse(ok)


class TestPastedOutputLines(unittest.TestCase):
    """出力の記録。フィクスチャの出力行と逐語一致するかで測る。

    **位置 (フェンスの中か・details の中か) では測らない。** 貼り方を
    問うと、規範に無い書式を要求したり、折りたたみの中の地の文を
    出力扱いしたりする穴が交互に開いた (実測で 2 往復した)。
    """

    def test_フェンス付きで貼れば全行(self):
        body = ("<details><summary> c </summary>\n\n```\n"
                + FIXTURE_LOGS + "```\n\n</details>\n")
        ok, ev = grade.logs_all_lines(body)
        self.assertTrue(ok, ev)

    def test_フェンス無しで貼っても全行(self):
        """SKILL.md は details で畳むことしか求めていない。

        フェンスを必須にすると、規範どおりに書いた記録が落ちる。
        """
        body = "<details><summary> c </summary>\n\n" + FIXTURE_LOGS + "\n</details>\n"
        ok, ev = grade.logs_all_lines(body)
        self.assertTrue(ok, ev)

    def test_details無しで貼っても全行(self):
        ok, ev = grade.logs_all_lines(FIXTURE_LOGS)
        self.assertTrue(ok, ev)

    def test_地の文の要約では通さない(self):
        """語は含むが、出力の行としては一致しない。"""
        body = ("<details><summary> c </summary>\n\n"
                "app-web と app-worker と app-db を確認した。"
                "failed to renew lease が 2 回、lease renewed、scan complete。"
                "\n\n</details>\n")
        ok, _ = grade.logs_all_lines(body)
        self.assertFalse(ok)

    def test_一部だけ貼ったら途中経過が出る(self):
        """満点でないときは、何行貼れたかが証跡に出る。"""
        head = "\n".join(FIXTURE_LOGS.splitlines()[:3])
        ok, ev = grade.logs_all_lines("```\n" + head + "\n```\n")
        self.assertFalse(ok)
        self.assertIn("3", ev)

    def test_apply_configも同じ形で測る(self):
        ok, ev = grade.apply_all_lines("```\n" + FIXTURE_APPLY + "```\n")
        self.assertTrue(ok, ev)

    def test_apply_configの地の文の要約では通さない(self):
        body = ("```\nx\n```\n"
                "retry.conf と timeout.conf と tls.conf を書き、"
                "service reloaded、Apply complete だった。")
        ok, _ = grade.apply_all_lines(body)
        self.assertFalse(ok)

    def test_重複する行は貼った回数だけ数える(self):
        """正解に同じ行が 2 回あれば、本文にも 2 回要る。

        集合で照合すると、1 回貼っただけで 2 回分に数えてしまい、
        繰り返しを省略した記録が満点になる。eval-0 の主題 (繰り返しの
        省略) と、逐語一致の勘定を同じ軸に揃える。

        現行のフィクスチャに重複行は無いので、架空の正解を差し込んで
        固定する — 重複が現れてから気づくのでは遅い。
        """
        grade._fixture_cache["dup-probe.sh"] = [
            "start", "same line", "same line", "end"]
        try:
            once = "```\nstart\nsame line\nend\n```\n"
            twice = "```\nstart\nsame line\nsame line\nend\n```\n"
            ok_once, ev_once = grade.all_output_lines(once, "dup-probe.sh")
            ok_twice, _ = grade.all_output_lines(twice, "dup-probe.sh")
            self.assertFalse(ok_once, ev_once)
            self.assertTrue(ok_twice)
        finally:
            del grade._fixture_cache["dup-probe.sh"]

    def test_ANSIエスケープを除いて照合する(self):
        """apply-config.sh は色付きで出力する。

        記録は除去して貼るので、照合する側も除去した形で持つ。
        """
        self.assertNotIn("\x1b", grade.fixture_lines("apply-config.sh")[0])


class TestFixtureExecution(unittest.TestCase):
    """フィクスチャの実行に伴う副作用。判定の正しさとは別に決めておく。"""

    def test_importしただけでは一時ディレクトリを作らない(self):
        """作るのは必要になったとき 1 度だけ。

        import 時に作ると、採点しなくても (テスト実行・単なる import でも)
        空のディレクトリが増え続け、消えない。
        """
        import glob
        import tempfile as tf
        pattern = str(Path(tf.gettempdir()) / "worklog-eval-*")
        before = len(glob.glob(pattern))
        importlib.reload(grade)
        self.assertEqual(len(glob.glob(pattern)), before)

    def test_出力が空なら満点にしない(self):
        """フィクスチャが失敗しても採点は続く。0/0 で満点にしない。

        実行に依存する以上、実行が壊れたときに黙って通す形は危うい。
        """
        grade._fixture_cache["empty-probe.sh"] = []
        try:
            ok, ev = grade.all_output_lines("なんでもよい本文", "empty-probe.sh")
            self.assertFalse(ok, ev)
        finally:
            del grade._fixture_cache["empty-probe.sh"]


class TestAlertKinds(unittest.TestCase):
    """Alert の種類。1 種類だけの偏りを落とせなければ判定の意味が無い。"""

    def test_一種類だけなら偏りとみなす(self):
        self.assertEqual(grade.alert_kinds("> [!NOTE]\n> x"), ["> [!NOTE]"])

    def test_二種類あれば偏っていない(self):
        kinds = grade.alert_kinds("> [!NOTE]\n> x\n> [!CAUTION]\n> y")
        self.assertEqual(len(kinds), 2)

    def test_eval2の判定が読み取りに合う種類を求める(self):
        """CHECKS[2] は「内容に応じて選ばれているか」を見る。

        eval-2 は読み取りのみの調査なので、format.md:101 のとおり TIP は
        合わない。種類の数では測れない — format.md:56 は 1 コメントに
        1〜2 個を目安と定めており、NOTE 1 個は指針どおりの正しい記録。
        """
        _, fn = grade.CHECKS[2][4]
        self.assertTrue(fn("> [!NOTE]\n> x")[0], "NOTE 1 個は指針どおり")
        self.assertTrue(fn("> [!WARNING]\n> x")[0])
        self.assertFalse(fn("> [!TIP]\n> x")[0], "読み取りに TIP は合わない")
        self.assertFalse(fn("本文だけ")[0], "Alert が無ければ落とす")


class TestAlertAfterReadonlyCat(unittest.TestCase):
    """読み取りコマンドの直後の警告。字下げで素通りさせない。"""

    def test_summaryにドル記号があっても落とす(self):
        """format.md は <summary> に「$ 付き」で書くよう指示している。

        その形で書かれた記録を判定が素通りしては、指示どおりの記録を
        一度も見ないことになる。
        """
        body = ("<details><summary> $ cat notes.txt </summary>\n\n"
                "</details>\n\n> [!CAUTION]\n> だめ")
        ok, _ = grade.alert_after_readonly_cat(body)
        self.assertFalse(ok)

    def test_読み取りの直後の警告を落とす(self):
        body = ("<details><summary> cat notes.txt </summary>\n</details>\n"
                "> [!CAUTION]\n> だめ")
        ok, _ = grade.alert_after_readonly_cat(body)
        self.assertFalse(ok)

    def test_字下げされていても落とす(self):
        body = ("<details><summary> cat notes.txt </summary>\n</details>\n"
                "  > [!CAUTION]\n  > だめ")
        ok, _ = grade.alert_after_readonly_cat(body)
        self.assertFalse(ok)

    def test_summaryを持たないdetailsを挟んでも直前ではない(self):
        """cat のあと別の段階を挟んだ結論の警告は、正しい記録なので通す。

        2 つめの details が summary を持たない場合、cat の summary が
        残り続けてはいけない。
        """
        body = ("<details><summary> cat notes.txt </summary>\n</details>\n"
                "<details>\n\n```\n$ ./deploy.sh\n```\n\n</details>\n"
                "> [!CAUTION]\n> 配信に失敗した")
        ok, _ = grade.alert_after_readonly_cat(body)
        self.assertTrue(ok)


class TestMentionsErrorCount(unittest.TestCase):
    """エラーの件数。フィクスチャの出力を貼るだけで通ってはいけない。"""

    def test_地の文で触れていれば通す(self):
        ok, _ = grade.mentions_error_count(
            "```\napp-worker : 880 lines, 3 errors\n```\n"
            "エラーが 3 件出ていた。")
        self.assertTrue(ok)

    def test_出力を貼っただけでは通さない(self):
        ok, _ = grade.mentions_error_count(
            "```\napp-worker : 880 lines, 3 errors\n```\n"
            "ログを確認した。")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
