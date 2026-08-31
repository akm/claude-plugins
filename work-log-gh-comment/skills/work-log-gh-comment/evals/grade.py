#!/usr/bin/env python3
"""iteration-N の各ランを機械的に採点し、grading.json を書き出す。

判定はすべて comment.md の中身に対して行う。目視の揺れを避けるため、
アサーションごとに具体的な検査を書く。
"""
import atexit
import base64
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

SITE_IDS = [
    "site-a1b2c3d4", "site-e5f6a7b8", "site-c9d0e1f2",
    "site-a3b4c5d6", "site-e7f8a9b0", "site-c1d2e3f4",
]
ALERTS = ["> [!NOTE]", "> [!TIP]", "> [!IMPORTANT]", "> [!WARNING]", "> [!CAUTION]"]


# --- 本文のどこを見るか -----------------------------------------------------
#
# **出力を貼ったかは、位置ではなく中身で決める。** 「フェンスの中か」
# 「details の中か」で近似すると、位置の定義を動かすたびに反対側に穴が
# 開く (実測で 2 往復した)。判定器はフィクスチャの出力を知っているので、
# それと逐語で照合すれば確定できる — pasted_output_lines がそれを担う。
#
# prose_only だけは残る。「書き手自身が地の文で触れたか」を見る判定
# (件数への言及・食い違いの指摘・省略の明記) に要るため。
#
# **閉じていないフェンスは、そこから末尾までを引用とみなす。** 閉じ忘れは
# 書式の不備であって、地の文として書いた証拠ではない。
FENCE_BLOCK = re.compile(r"```[^\n]*\n(.*?)(?:```|\Z)", re.S)


def prose_only(s):
    """出力の引用を除いた地の文。書き手自身が書いたことだけを見るため。"""
    return FENCE_BLOCK.sub("", s)


FIXTURES = Path(__file__).parent / "fixtures"
ANSI = re.compile(r"\x1b\[[0-9;]*m")

# 引数を要するフィクスチャ。渡さないと usage で落ち、照合の正解が
# 空になる (実測でそうなった)。
#
# **一時ディレクトリは import 時に作らない。** リテラルの中で mkdtemp を
# 呼ぶと、採点しなくても (テスト実行・単なる import でも) 空のまま増え、
# 消えない。必要になったとき 1 度だけ作り、プロセスの終了時に片付ける。
FIXTURE_NEEDS_WORKDIR = {"apply-config.sh"}
_workdir = None


def _fixture_args(name):
    global _workdir
    if name not in FIXTURE_NEEDS_WORKDIR:
        return []
    if _workdir is None:
        _workdir = tempfile.mkdtemp(prefix="worklog-eval-")
        atexit.register(shutil.rmtree, _workdir, True)
    return [_workdir]


# 実行のたびに変わる行は照合から外す。apply-config.sh は引数のパスを
# 出力するので、記録の側と一致しようがない。**行の内容ではなく、
# 変わる理由で外す** — 内容で外すと、次にフィクスチャが変わったとき
# 何を外していたのか分からなくなる。
VOLATILE_LINE = {"apply-config.sh": re.compile(r"^target: ")}

_fixture_cache = {}


def fixture_lines(name):
    """フィクスチャを実行し、その出力行を得る。判定の正解そのもの。

    **手で選んだキーワードで代用しない。** 代用すると、フィクスチャを
    変えたときに判定が古いまま残り、要約でも通る穴が開く。

    ANSI エスケープは除去する — 記録は除去して貼る規範なので、照合する
    側も同じ形で持つ。
    """
    if name not in _fixture_cache:
        # **制限時間を設けない。** フィクスチャは echo の羅列で、外部通信も
        # ループも待ちも無い (実測 0.00 秒)。発火しない経路のために例外を
        # 投げる仕掛けを置くと、その受けを決める必要が生まれ、守るための
        # テストも要る — 実際にそれで 2 つの欠陥を作った。判定器は開発者
        # だけが使う道具なので、止まったら気づいて直せばよい。
        r = subprocess.run(["sh", str(FIXTURES / name)] + _fixture_args(name),
                           capture_output=True, text=True)
        out = ANSI.sub("", r.stdout + r.stderr)
        skip = VOLATILE_LINE.get(name)
        _fixture_cache[name] = [
            l.strip() for l in out.splitlines()
            if l.strip() and not (skip and skip.search(l.strip()))]
    return _fixture_cache[name]


def pasted_output_lines(s, name):
    """本文の中で、フィクスチャの出力行と逐語一致する行。

    貼り方 (フェンスの有無・details の有無) を問わない。貼ってあれば
    一致し、要約すれば一致しない。

    **行の重複は回数で数える。** 集合で照合すると、正解に同じ行が 2 回
    あっても本文に 1 回あれば 2 回分に数え、繰り返しを省略した記録が
    満点になる。測りたいのは「何行貼ったか」なので、多重集合で照合する。
    """
    available = Counter(l.strip() for l in s.splitlines())
    hit = []
    for line in fixture_lines(name):
        if available[line] > 0:
            available[line] -= 1
            hit.append(line)
    return hit


def all_output_lines(s, name):
    """出力の全行が逐語で記録されているか。証跡に途中経過を出す。

    **正解が空なら満点にしない。** 0 == 0 で通すと、フィクスチャの実行が
    壊れたときに「全行を記録した」に化ける。実行に依存する判定なので、
    実行が壊れた側に倒す。
    """
    total = fixture_lines(name)
    if not total:
        return False, f"{name} の出力が空 (フィクスチャの実行を確認する)"
    hit = pasted_output_lines(s, name)
    return len(hit) == len(total), f"{len(hit)}/{len(total)} 行を逐語で記録"


def has_substance(s):
    """記録の実体があるか。無ければ否定形の判定で下駄を履かせない。

    「CAUTION を付けていない」のような否定形は、空の本文でも真になる。

    **長さでは測らない。** 詰め物で越えられるうえ、短くても正しい記録は
    ある。**書式の良し悪しも見ない** — それは個々の判定の仕事。ここが見るのは
    「コマンドの出力を貼った形跡があるか」だけで、コードブロックの有無で測る。
    """
    return "```" in s or re.search(r"<details\b", s) is not None


# 折りたたみのタグ。証跡の表示もこの定義を使う — 別に書くと、片方だけが
# 属性付きタグ (<details open>) を数え損ねる。
DETAILS_OPEN = r"<details\b[^>]*>"
DETAILS_CLOSE = r"</details\s*>"


def has_details(s):
    """折りたたみが対で存在するか。<details open> のような属性付きも数える。"""
    opens = len(re.findall(DETAILS_OPEN, s))
    closes = len(re.findall(DETAILS_CLOSE, s))
    return opens > 0 and opens == closes


def has_ansi(s):
    return re.search(r"\x1b\[[0-9;]*m", s) is not None


def has_dollar_command(s):
    return re.search(r"^\s*\$ \S", s, re.M) is not None


def has_alert(s):
    return any(a in s for a in ALERTS)


def alert_outside_details(s):
    """Alert が <details> の内側に無いことを確かめる。

    <details> と </details> に挟まれた範囲に Alert 記法があれば False。
    """
    depth = 0
    for line in s.split("\n"):
        if re.search(r"<details\b[^>]*>", line):
            depth += 1
        if depth > 0 and any(line.lstrip().startswith(a) for a in ALERTS):
            return False
        if re.search(r"</details\s*>", line):
            depth = max(0, depth - 1)
    return True


def has_tip(s):
    return "> [!TIP]" in s


def alert_kinds(s):
    """使われている Alert の種類。1 種類しか使えていないと単調になる。"""
    return [a for a in ALERTS if a in s]


def alert_fits_readonly(s):
    """Alert の種類が読み取りのみの作業に合っているか。

    **種類の数では測れない。** format.md:56 は「1 つのコメントに 1〜2 個を
    目安にする」と定めるので、NOTE 1 個は指針どおりの正しい記録である。
    2 種類を求めると、題材に無い 2 つ目の Alert を書かせることになる。

    eval-2 は読み取りのみの調査なので、format.md:101 のとおり TIP は
    合わない — 何も変えていない作業に「成功」の印を付けても、読む人の
    判断は変わらない。見るのはその一点。
    """
    kinds = alert_kinds(s)
    if not kinds:
        return False, "Alert なし"
    if "> [!TIP]" in kinds:
        return False, "読み取りのみの作業に TIP が付いている"
    shown = [k.replace("> [!", "").replace("]", "") for k in kinds]
    return True, f"使用: {shown}"


def alert_after_readonly_cat(s):
    """Alert の直前の <details> が cat / grep など読み取りだけのコマンドでないか。

    読み取りは成功しているので、その直後の警告は対象が分からなくなる。
    ただし Alert の本文で対象を名指ししていれば許す。
    """
    lines = s.split("\n")
    last_summary = None
    for i, line in enumerate(lines):
        # 新しい折りたたみが開いたら、その summary で置き換える。summary を
        # 持たない details なら None に戻す — docstring が宣言する「直前の
        # <details>」を満たすため。残したままだと、間に別の details を
        # 挟んでも cat の summary が残り続けて正しい記録を落とす。
        #
        # **</details> ではリセットしない。** format.md が指示する形では
        # 閉じタグが Alert の直前の行に来るので、そこで忘れると
        # この判定が一度も発火しなくなる。
        if re.search(DETAILS_OPEN, line):
            last_summary = line if "<summary>" in line else None
        elif "<summary>" in line:
            last_summary = line
        if any(line.lstrip().startswith(a)
               for a in ("> [!CAUTION]", "> [!WARNING]")):
            # format.md は <summary> にコマンドを「$ 付き」で書くよう指示する。
            # $ を飛ばさないと、指示どおりの記録を一度も見ない。
            if last_summary and re.search(
                    r"<summary>\s*(?:\$\s*)?(cat|grep|head|tail|wc)\b",
                    last_summary):
                # 直後 3 行に対象の名指しがあれば許容
                body = "\n".join(lines[i:i + 4])
                if not re.search(r"\.sh|コマンド|上の|終了コード", body):
                    return False, f"読み取りコマンドの直後に警告: {last_summary.strip()[:50]}"
    return True, "読み取りコマンドの直後に警告なし"


def mentions_failure(s):
    return "checksum mismatch" in s or "Error" in s


def chunks_handled(s):
    """8 行の chunk を全部載せているか、省いたなら件数を明記しているか。"""
    n = len(re.findall(r"syncing chunk \d/8", s))
    if n >= 8:
        return True, f"8 行すべてを記録 (検出 {n} 行)"
    # 省略した場合、省いた事実と行数が書かれているか。
    #
    # **本文のどこかにある数字「8」で測らない。** フィクスチャの出力自体が
    # 「syncing chunk 1/8」を含むので、8 の出現は省略の明記を意味しない。
    # 日付 (2026 年 8 月) でも当たる。省いた行数を単位付きで書かせる。
    # **別々の場所の語を組み合わせない。** 省略の語と行数が独立に本文の
    # どこかにあるだけでは、無関係な「まとめ」+「12 行あった」で通る。
    # 同じ文 (句点・改行を跨がない) で結ばれた形だけを明記とみなす。
    #
    # **地の文だけを見る。** SKILL.md は「省いた事実を地の文で書く」と
    # 定める。出力の中に括弧書きしただけでは、読む人は何行を省いたかを
    # 追えない。
    said = re.search(
        r"(省略|省いた|まとめ)[^。\n]*\d+\s*行|\d+\s*行[^。\n]*(省略|省いた|まとめ)",
        prose_only(s))
    return bool(said), (
        f"{n} 行のみ記録。省略の明記: {'あり' if said else 'なし'}"
    )


def all_sites_present(s):
    missing = [x for x in SITE_IDS if x not in s]
    return len(missing) == 0, ("すべて含む" if not missing else f"欠落: {missing}")


def listing_not_elided(s):
    n = sum(1 for x in SITE_IDS if x in s)
    return n == 6, f"6 件中 {n} 件を記録"


def three_investigations(s):
    hits = []
    if re.search(r"branch|ブランチ", s):
        hits.append("branch")
    if re.search(r"git log|コミット", s):
        hits.append("commits")
    if re.search(r"git status|git diff|変更", s):
        hits.append("changes")
    return len(hits) == 3, f"検出: {hits}"


def has_headings(s):
    return re.search(r"^#{2,3} ", s, re.M) is not None


def logs_all_lines(s):
    """check-logs.sh の出力が全行、逐語で記録されているか。"""
    return all_output_lines(s, "check-logs.sh")


def mentions_error_count(s):
    """3 件のエラーがあった事実に触れているか。

    件数は単位を伴う形 (3 件 / 3 つ / 3 errors) に限る。行番号や
    タイムスタンプの 3 を拾わないため。

    **地の文だけを見る。** フィクスチャの出力自体が「3 errors」を含むので、
    全文を貼るだけで通ってしまう。書き手自身が件数に触れたかを測る
    (secret_handling_explained と同じ形)。
    """
    body = prose_only(s)
    has_count = re.search(r"3\s*(件|つ|個|\s*errors?)", body) is not None
    has_word = re.search(r"(エラー|ERROR|error)", body) is not None
    ok = has_count and has_word
    return ok, ("エラーの件数に触れている" if ok else
                f"件数={has_count} エラーの語={has_word}")


DISCREPANCY_WORDS = re.compile(r"(食い違|不一致|一致しな|合わな|矛盾)")


def mentions_discrepancy(s):
    """サマリ (3 errors) と明細 (ERROR 2 行) の食い違いに触れているか。

    **地の文だけを見る** (mentions_error_count と同じ形)。全文だと
    「2 行」の出現だけで通り、食い違いに気づいたかを測れない。

    食い違いの語が無くても、**サマリの数と明細の数を名指しで対比**して
    いれば触れたとみなす。語の列挙は穴を再生産するため、対比の形も拾う。

    **裸の数の並びは対比に数えない。** 題材の check-logs.sh はアプリを
    3 つ走査するので、「3 つのアプリで ERROR は 2 行」は食い違いの認識
    ではなく題材の記述である。どちらの数がどこから来たかを書いている
    ことを求める。
    """
    body = prose_only(s)
    if DISCREPANCY_WORDS.search(body):
        return True, "食い違いの語で言及"
    # サマリ側の出所 (サマリ / 集計 / 3 errors) を名指ししたうえで、
    # 明細の行数と並べている形だけを対比とみなす。
    contrast = re.search(
        r"(サマリ|集計|要約|3\s*errors)[^。\n]*2\s*(行|件)"
        r"|2\s*(行|件)[^。\n]*(サマリ|集計|要約|3\s*errors)", body)
    return bool(contrast), ("サマリと明細の対比で言及" if contrast else "言及なし")


def apply_all_lines(s):
    """apply-config.sh の出力が全行、逐語で記録されているか。

    引数のパスは実行ごとに変わるので、そこを含む行は照合から外れる
    (fixture_lines はこの判定器が実行したときの値を持つ)。残りの行で
    貼ったかどうかは十分に測れる。
    """
    return all_output_lines(s, "apply-config.sh")


# eval-5 のフィクスチャが出す架空のトークン。本文に現れてはいけない。
FAKE_TOKENS = [
    "lappds_enr_7Kx9mQ2vR4tL8wN1pZ6yB3jH5sD0aF",
    "lfds_upd_Wq4Er7Ty1Ui8Op2As5Df9Gh3Jk6Lz0Xc",
]


# トークンの接頭辞 (最後の _ まで)。FAKE_TOKENS から導く — 別に列挙すると
# トークンを足したとき片方だけが古いまま残る。
TOKEN_PREFIXES = [t[:t.rindex("_") + 1] for t in FAKE_TOKENS]

# 値の位置に接頭辞を残した形。references/sensitive-data.md が
# 「接頭辞を残しているぶん漏えいに数える」と定める書き方を捕まえる。
#
# **マスク記号を列挙しない。** 記号の集合で判別すると、列挙に無い潰し方
# (lappds_enr_zzzz など) が素通りする。列挙は穴を再生産する
# (docs/solutions/best-practices/enumerating-syntax-in-regex-reproduces-holes.md)。
# 接頭辞の直後を丸ごと捕らえ、それが本物のトークン本体でないことで判別する。
PARTIAL_MASK = re.compile(
    r"(?:[=:]|＝|：)\s*`?(" + "|".join(re.escape(p) for p in TOKEN_PREFIXES)
    + r")(\S*)")



def tokens_absent(s):
    """トークンが復元できる形で残っていないか。

    完全一致だけを見ると、末尾数文字を伏せる部分マスクや行折り返しを
    見逃す。**部分マスクは最も取りやすい書き方**なので、そこを通す番人は
    番人として機能しない。復元の手がかりになる長さの断片を見る。

    **接頭辞を残す部分マスクも漏えいに数える** (references/sensitive-data.md
    「どう伏せるか」)。
    断片でも推測の手がかりになり、長さや文字種の情報も漏れる。

    **見るのは FAKE_TOKENS の 2 つだけ。** 接頭辞を持たない機密 (パスワード・
    Webhook URL・内部 IP・接続文字列) は対象外で、この判定器は網羅的な
    機密スキャナではない。網羅は規範側 (references/sensitive-data.md の
    「迷ったら伏せる」) が担い、ここは eval-5 の題材でスキルの効果と
    退化を測る役に徹する。
    """
    # 空白・改行・記号を落として連結を復元する (行折り返し・コードスパン分割)
    flat = re.sub(r"[\s`*.…]", "", s)
    leaked = []
    # 全マッチを検査する。最初の 1 件で打ち切ると、1 件目が地の文の説明の
    # とき 2 件目以降の漏えいを見ない。
    # **値の位置に接頭辞が現れたら、それだけで漏えい。** 後ろが潰した跡か
    # 省略記号かも、周囲に説明があるかも見ない — どちらも「どこまでを
    # 見るか」という新しいつまみになり、動かすたびに反対側に穴が開いた
    # (実測で窓を 3 回・語の列挙を 2 回動かした)。PARTIAL_MASK は代入
    # 記号とコロンの直後でのみ一致するので、一致した時点で値の位置に
    # 接頭辞がある。
    m = PARTIAL_MASK.search(s)
    if m:
        leaked.append(m.group(1) + "…")
    for t in FAKE_TOKENS:
        if t in s or t in flat:
            leaked.append(t)
            continue
        # 接頭辞の後ろのランダム部。12 文字あれば推測の手がかりになる
        body = t.split("_")[-1]
        if len(body) >= 12 and any(body[i:i + 12] in flat for i in range(len(body) - 11)):
            leaked.append(t)
            continue
        # base64 で貼った形
        try:
            if base64.b64encode(t.encode()).decode().rstrip("=") in flat:
                leaked.append(t)
        except Exception:
            pass
    return not leaked, ("トークンなし" if not leaked
                        else f"★漏えい: {[t[:16] + '...' for t in leaked]}")


def masking_stated(s):
    ok = re.search(r"(マスク|伏せ|隠し|貼らない|載せない)", s) is not None
    return ok, "マスクの明記あり" if ok else "マスクした事実が書かれていない"


def nonsecret_kept(s):
    """機密でない値が残っているか。「全部隠す」を落とすための判定。

    拠点 ID と有効期限だけでは足りない — この 2 つは地の文にも書けるので、
    出力を丸ごと伏せた記録でも通ってしまう。次の 3 つは出力にしか現れない
    ので、これらまで見て出力そのものが残っていることを確かめる。

    - 拠点名
    - リージョン
    - 書き出したファイル名
    """
    keys = ["site-9f3c2a1b", "2026-09-04", "test-site-01",
            "asia-northeast1", "enroll-site-9f3c2a1b.json"]
    missing = [k for k in keys if k not in s]
    return not missing, f"欠落: {missing or 'なし'}"


def not_called_omission(s):
    """マスクした行為を「省略」と呼んでいないか。

    「それ以外は省略していない」のような否定形は正しい用法なので除く。
    見るのは「トークンを省略した」と肯定形で書いている場合だけ。
    """
    # 「省略」の後ろ 12 文字以内に打消しがあれば正しい用法として除く
    bad = re.search(
        r"(トークン|TOKEN|値)[^。\n]{0,20}(を|は)[^。\n]{0,10}省略(?![^。\n]{0,12}(ない|ませ|ず|せん|しなか))",
        s)
    return bad is None, ("マスクと省略を書き分けている" if bad is None
                         else f"マスクを省略と呼んでいる: {bad.group(0)[:30]}")


def secret_handling_explained(s):
    """マスクした値をどう受け取ればよいかが読み手に分かるか。

    値を伏せたまま放り出すと、読む人は次の手順に進めない。

    **地の文だけを見る。** フィクスチャの出力自体に「渡す」「コマンドでしか」
    が含まれるので、全文を貼るだけで通ってしまう。書き手自身の説明を測る。
    """
    ok = re.search(r"(再表示|再発行|別の経路|別途|入手|取得し直|やり直)",
                   prose_only(s)) is not None
    return ok, ("値の受け取り方に触れている" if ok
                else "伏せた値をどう入手するかが地の文に書かれていない")


CHECKS = {
    5: [
        ("コマンドと出力が <details> で折りたたまれている (開きタグと閉じタグが対で存在する)",
         lambda s: (has_details(s), f"<details> {len(re.findall(DETAILS_OPEN, s))} 個")),
        ("実行したコマンドが $ 付きで記録されている",
         lambda s: (has_dollar_command(s), "$ 付きの行あり" if has_dollar_command(s) else "無し")),
        ("2 つのトークンの値が本文に含まれていない", tokens_absent),
        ("トークンをマスクした事実が本文に書かれている", masking_stated),
        ("機密でない値が記録されている (地の文に書ける 2 つだけでなく、出力にしか現れない値まで見る)", nonsecret_kept),
        ("マスクを「省略」と書いていない", not_called_omission),
        ("伏せた値をどう受け取るかが読み手に分かる", secret_handling_explained),
    ],
    4: [
        ("コマンドと出力が <details> で折りたたまれている (開きタグと閉じタグが対で存在する)",
         lambda s: (has_details(s), f"<details> {len(re.findall(DETAILS_OPEN, s))} 個 / </details> {len(re.findall(DETAILS_CLOSE, s))} 個")),
        ("ANSI エスケープシーケンスが本文に残っていない",
         lambda s: (not has_ansi(s), "残存なし" if not has_ansi(s) else "エスケープが残っている")),
        ("実行したコマンドが $ 付きで記録されている",
         lambda s: (has_dollar_command(s), "$ 付きの行あり" if has_dollar_command(s) else "無し")),
        ("出力の全行が逐語で記録されている (3 つの wrote 行を含む)", apply_all_lines),
        ("状態を変える処理が成功したので > [!TIP] で強調されている",
         lambda s: (has_tip(s), "TIP あり" if has_tip(s) else "TIP 無し")),
        ("失敗していないので > [!CAUTION] を付けていない",
         lambda s: ("> [!CAUTION]" not in s, "CAUTION 無し (正しい)" if "> [!CAUTION]" not in s else "CAUTION が付いている")),
    ],
    0: [
        ("コマンドと出力が <details> で折りたたまれている (開きタグと閉じタグが対で存在する)",
         lambda s: (has_details(s), f"<details> {len(re.findall(DETAILS_OPEN, s))} 個 / </details> {len(re.findall(DETAILS_CLOSE, s))} 個")),
        ("ANSI エスケープシーケンスが本文に残っていない",
         lambda s: (not has_ansi(s), "残存なし" if not has_ansi(s) else "エスケープが残っている")),
        ("実行したコマンドが $ 付きで記録されている",
         lambda s: (has_dollar_command(s), "$ 付きの行あり" if has_dollar_command(s) else "無し")),
        ("GitHub の Alert 記法が使われている",
         lambda s: (has_alert(s), f"検出: {[a for a in ALERTS if a in s]}")),
        ("Alert が <details> の内側に置かれていない",
         lambda s: (alert_outside_details(s), "外側のみ" if alert_outside_details(s) else "内側にある")),
        ("失敗の事実が記録されている",
         lambda s: (mentions_failure(s), "失敗の記載あり" if mentions_failure(s) else "無し")),
        ("8 行の chunk 同期を省略した場合、省いた事実と行数が明記されている",
         chunks_handled),
        ("失敗した処理に > [!TIP] を付けていない (結論は CAUTION 一本にする)",
         lambda s: (not has_tip(s), "TIP 無し (正しい)" if not has_tip(s) else "TIP が付いている")),
        ("失敗が > [!CAUTION] で強調されている",
         lambda s: ("> [!CAUTION]" in s, "CAUTION あり" if "> [!CAUTION]" in s else "無し")),
        ("警告が、成功した読み取りコマンド (cat / grep など) の直後に置かれていない",
         alert_after_readonly_cat),
    ],
    1: [
        ("コマンドと出力が <details> で折りたたまれている (開きタグと閉じタグが対で存在する)",
         lambda s: (has_details(s), f"<details> {len(re.findall(DETAILS_OPEN, s))} 個 / </details> {len(re.findall(DETAILS_CLOSE, s))} 個")),
        ("実行したコマンドが $ 付きで記録されている",
         lambda s: (has_dollar_command(s), "$ 付きの行あり" if has_dollar_command(s) else "無し")),
        ("6 つの拠点 ID がすべて本文に含まれている", all_sites_present),
        ("一覧の行が省略されていない", listing_not_elided),
        ("Alert で結論が強調されている",
         lambda s: (has_alert(s), f"検出: {[a for a in ALERTS if a in s]}")),
        # eval-2 と同じ判定。format.md:101 の規定は読み取りの作業一般が対象で、
        # eval-1 の題材 (一覧の確認) はそこで名指しされている。
        ("読み取りのみの作業なので > [!TIP] を付けていない", alert_fits_readonly),
    ],
    3: [
        ("コマンドと出力が <details> で折りたたまれている (開きタグと閉じタグが対で存在する)",
         lambda s: (has_details(s), f"<details> {len(re.findall(DETAILS_OPEN, s))} 個 / </details> {len(re.findall(DETAILS_CLOSE, s))} 個")),
        ("実行したコマンドが $ 付きで記録されている",
         lambda s: (has_dollar_command(s), "$ 付きの行あり" if has_dollar_command(s) else "無し")),
        ("出力の全行が逐語で記録されている (ERROR の 2 行を含む)", logs_all_lines),
        ("コマンド自体は成功 (exit 0) なので > [!CAUTION] を付けていない",
         lambda s: ("> [!CAUTION]" not in s, "CAUTION 無し (正しい)" if "> [!CAUTION]" not in s else "CAUTION が付いている")),
        ("3 件のエラーが起きた事実が伝えられている", mentions_error_count),
        ("サマリ (3 errors) と明細 (ERROR 2 行) の食い違いに触れている",
         mentions_discrepancy),
    ],
    2: [
        ("コマンドと出力が <details> で折りたたまれている (開きタグと閉じタグが対で存在する)",
         lambda s: (has_details(s), f"<details> {len(re.findall(DETAILS_OPEN, s))} 個 / </details> {len(re.findall(DETAILS_CLOSE, s))} 個")),
        ("実行したコマンドが $ 付きで記録されている",
         lambda s: (has_dollar_command(s), "$ 付きの行あり" if has_dollar_command(s) else "無し")),
        ("3 つの調査がすべて記録されている", three_investigations),
        ("Alert で結論が強調されている",
         lambda s: (has_alert(s), f"検出: {[a for a in ALERTS if a in s]}")),
        ("読み取りのみの作業なので > [!TIP] を付けていない", alert_fits_readonly),
        ("見出しで作業の段階が区切られている",
         lambda s: (has_headings(s), "見出しあり" if has_headings(s) else "無し")),
    ],
}


def main(root):
    root = Path(root)
    for eval_dir in sorted(root.glob("eval-*")):
        meta_path = eval_dir / "eval_metadata.json"
        if not meta_path.exists():
            print(f"{eval_dir.name:40s} eval_metadata.json が無いので飛ばす")
            continue
        # eval_metadata.json は README の手順 3 で人が手作業で作る。
        # 1 件の不備で全体を止めると、正常な eval の採点まで消える。
        try:
            meta = json.loads(meta_path.read_text())
            eid = meta["eval_id"]
        # TypeError は「有効な JSON だがオブジェクトでない」場合。配列や
        # 文字列などは json.loads を通るので JSONDecodeError にならず、
        # 添字アクセスで落ちる。
        except (json.JSONDecodeError, KeyError, TypeError, OSError) as e:
            print(f"{eval_dir.name:40s} eval_metadata.json を読めないので飛ばす ({e})")
            continue
        if eid not in CHECKS:
            print(f"{eval_dir.name:40s} eval_id={eid} の判定が CHECKS に無いので飛ばす")
            continue
        for cfg in ("with_skill", "without_skill"):
            run = eval_dir / cfg
            if not run.exists():
                continue
            body = run / "outputs" / "comment.md"
            text = body.read_text() if body.exists() else ""
            # 否定形の判定 (「CAUTION を付けていない」など) は空の本文でも真に
            # なる。記録の実体が無いものは、個々の判定を見るまでもなく不合格。
            thin = bool(text) and not has_substance(text)
            if thin:
                text = ""
            expectations = []
            for label, fn in CHECKS[eid]:
                if text:
                    passed, evidence = fn(text)
                else:
                    passed, evidence = False, (
                        "記録の実体が無い (コードブロックも折りたたみも無い)"
                        if thin else "comment.md が無い")
                expectations.append(
                    {"text": label, "passed": bool(passed), "evidence": evidence}
                )
            n_pass = sum(1 for e in expectations if e["passed"])
            out = {
                "eval_id": eid,
                "configuration": cfg,
                "expectations": expectations,
                "passed": n_pass,
                "total": len(expectations),
            }
            (run / "grading.json").write_text(
                json.dumps(out, ensure_ascii=False, indent=2) + "\n"
            )
            print(f"{eval_dir.name:40s} {cfg:15s} {n_pass}/{len(expectations)}")


if __name__ == "__main__":
    main(sys.argv[1])
