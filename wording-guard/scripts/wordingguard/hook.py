"""PostToolUse の hook (ツールの実行の直後に動く処理) の本体。

Edit / Write で Markdown に書き足した文章を textlint で検査し、結果を Claude に返す。
振る舞いの正本はファイル `wording-guard/skills/wording-guard/references/textlint.md` の「hook」。

  - 検査するのは、設定キー textlint.hook を true にしたリポジトリの Markdown だけ。それ以外は何もしない
    (プラグインの hook は、プラグインを有効にしたすべてのリポジトリで動くため)。textlint.hook は設定の型を
    検査する前に見るので、有効にしていないリポジトリでは設定の誤りでも何もしない。
  - 書き換えた後のファイルの全体 (ディスクから読む) と、書き換える前のファイルの全体 (Claude Code が hook に渡す
    ツールの結果 tool_response の originalFile) を検査し、書き換えた行にある検出のうち、増えたものだけを返す。
    文字列だけを切り出して検査すると、コードブロックや引用ブロックの中の行が本文として解析されるため、
    ファイルの全体を検査する。書き換えた行の外の検出を比べないのは、message に行番号やファイル全体の件数を
    入れる規則があり、書き換えた箇所の外の既存の検出も message が変わるため。書き換えた行は、tool_response の
    structuredPatch (Claude Code が計算した行の差分) から取り、hook の中では差分を計算しない。ツールの入力
    (new_string) から書き換える前の内容を組み立てないのは、Edit が引用符をファイルに合わせて書き換えたり、
    利用者が提案を変えたりして、ファイルにツールの入力どおりの文字列が無いことがあるため。
  - error の検出があれば decision: block で直すよう求め、warning だけなら additionalContext で判断の材料として渡す。
    重大度は検出の種類ではないので、案内は規則の名前で分ける (規則 prh の検出は言い換えを決めた語、それ以外は
    リポジトリの textlint の設定で error にした規則)。
  - 設定・用語ファイルの誤りや、textlint が入っていないときは、検査を省略せずに、Claude と利用者に知らせる。
"""

import bisect
import collections
import os
import re
import sys

from . import config

MAX_ITEMS = 30
EVENT_NAME = "PostToolUse"


# MultiEdit は Claude Code 2.0 で無くなったツールなので、対象にしない
TOOLS = ("Edit", "Write")


def contents_before(tool, tool_response):
    """書き換える前のファイルの内容を、ツールの結果 (tool_response) の originalFile から返す。

    Write で新しいファイルを作ったとき (originalFile が null で、type が create) は空の文字列を返す。
    originalFile が無い (この版の Claude Code は渡さない) か、それ以外で null (前の内容が大きすぎるなど) の
    ときは ValueError を送出する。tool_response のフィールドは Claude Code の公式の文書に載っていない
    (Claude Code 2.1.273 の Edit と Write の出力の様式で確かめた)。
    """
    if "originalFile" not in tool_response:
        raise ValueError("hook の入力の tool_response に originalFile が無い (この版の Claude Code は書き換える前の内容を渡さない)")
    original = tool_response["originalFile"]
    if original is None and tool == "Write" and tool_response.get("type") == "create":
        return ""
    if not isinstance(original, str):
        raise ValueError(f"hook の入力の tool_response の originalFile が文字列でない ({original!r}。"
                         "書き換える前の内容が大きすぎるときは null になる)")
    return original


def patch_lines(tool, tool_response, before, after):
    """書き換えた行を、ツールの結果 (tool_response) の structuredPatch から (書き換える前の側, 書き換えた後の側) の
    行番号の集合で返す。

    structuredPatch は Claude Code が計算した行の差分で、範囲 (hunk) ごとに oldStart・newStart (1 から数える行番号) と
    lines (先頭の 1 文字が " " は変えていない行、"-" は消した行、"+" は足した行、"\\" は末尾の改行の有無の印) を持つ。
    "-" の行を書き換える前の側、"+" の行を書き換えた後の側にする。行番号は 0 から数える (textlint の行番号と同じ数え方)。
    hook の中では差分を計算しない。structuredPatch は公式の文書に載っていない (Claude Code 2.1.273 で確かめた)。

    次のときは ValueError を送出する (hook の中の差分の計算には戻らない)。
      - structuredPatch が無い、または様式が想定と違う
      - structuredPatch が空なのに、書き換える前と後の内容が違う (Claude Code の差分の計算が時間切れになったときなど)。
        ただし Write で新しいファイルを作ったとき (type が create) は、内容の全体を書き換えた行にする
      - " "・"-"・"+" の行の内容が、前後の内容の行と一致しない (書いた直後に別の処理がファイルを変えたときなど)
    """
    if "structuredPatch" not in tool_response:
        raise ValueError("hook の入力の tool_response に structuredPatch が無い (この版の Claude Code は差分を渡さない)")
    hunks = tool_response["structuredPatch"]
    if not isinstance(hunks, list):
        raise ValueError(f"hook の入力の tool_response の structuredPatch がリストでない ({hunks!r})")
    a, b = before.split("\n"), after.split("\n")
    if not hunks:
        if before == after:
            return set(), set()
        if tool == "Write" and tool_response.get("type") == "create":
            return set(), set(range(len(b)))
        raise ValueError("structuredPatch が空なのに、書き換える前と後の内容が違う "
                         "(Claude Code の差分の計算が時間切れになったときなど)")
    removed, added = set(), set()
    for hunk in hunks:
        try:
            old_no, new_no, lines = int(hunk["oldStart"]), int(hunk["newStart"]), list(hunk["lines"])
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"structuredPatch の範囲の様式が想定と違う ({hunk!r})") from e
        for line in lines:
            mark, text = str(line)[:1], str(line)[1:]
            if mark == "\\":
                continue
            if mark not in (" ", "-", "+"):
                raise ValueError(f"structuredPatch の行の先頭の文字が想定と違う ({line!r})")
            if mark in (" ", "-"):
                _expect_line(a, old_no, text, "書き換える前")
                if mark == "-":
                    removed.add(old_no - 1)
                old_no += 1
            if mark in (" ", "+"):
                _expect_line(b, new_no, text, "書き換えた後")
                if mark == "+":
                    added.add(new_no - 1)
                new_no += 1
    return removed, added


def _expect_line(lines, number, text, side):
    """structuredPatch の number 行目 (1 から数える) の内容 text が、lines の同じ行と一致することを確かめる。

    Claude Code は差分の行の先頭のタブを 1 つにつき空白 2 つに置き換えるので、比べる前にファイルの行も同じく置き換える。
    """
    if not 1 <= number <= len(lines):
        raise ValueError(f"structuredPatch の{side}の {number} 行目が、ファイルの行の数 ({len(lines)}) を越える")
    line = lines[number - 1]
    expected = re.sub(r"^\t+", lambda m: "  " * len(m.group()), line).rstrip("\r")
    if expected != text.rstrip("\r"):
        raise ValueError(f"structuredPatch の{side}の {number} 行目が、ファイルの内容と一致しない "
                         "(書いた直後に別の処理がファイルを変えた可能性がある)")


def in_lines(text, findings, lines):
    """findings (text の検出) のうち、行番号の集合 lines のどれかの行に重なるものを返す。

    検出の行は、始まり (start) から終わり (end) までの Python の文字列の位置から数える。複数の行にまたがる
    検出 (長い文など) は、どれかの行が lines に入れば重なるとする。位置の無い検出は行で絞れないので残す。
    """
    line_starts = [0] + [i + 1 for i, ch in enumerate(text) if ch == "\n"]

    def line_of(index):
        return bisect.bisect_right(line_starts, index) - 1

    result = []
    for f in findings:
        if f.get("start") is not None:
            first = line_of(f["start"])
            last = line_of(max(f.get("end") or f["start"], f["start"] + 1) - 1)
        elif f.get("line"):
            first = last = f["line"] - 1
        else:
            result.append(f)
            continue
        if any(i in lines for i in range(first, last + 1)):
            result.append(f)
    return result


def _key(finding):
    return (finding["rule"], finding["message"], finding["matched"])


def introduced(before, after):
    """after の検出のうち、before に無かったもの (同じ検出が増えた分を含む) を返す。"""
    remaining = collections.Counter(_key(f) for f in before)
    result = []
    for f in after:
        k = _key(f)
        if remaining[k] > 0:
            remaining[k] -= 1
            continue
        result.append(f)
    return result


def _excerpt(text, finding):
    """検出の始まり (finding の start。Python の文字列の位置) を含む行から、前後を抜き出す。

    textlint の column は UTF-16 の単位で数えるので、Python の文字列の切り出しには使わない。
    """
    pos = finding.get("start")
    if pos is None or not 0 <= pos <= len(text):
        return ""
    line_start = text.rfind("\n", 0, pos) + 1
    line_end = text.find("\n", pos)
    src = text[line_start:len(text) if line_end == -1 else line_end]
    col = pos - line_start
    start = max(0, col - 20)
    return ("…" if start > 0 else "") + src[start:col + 30] + ("…" if col + 30 < len(src) else "")


def _format(items):
    shown = items[:MAX_ITEMS]
    lines = []
    for text, f in shown:
        head, _, detail = f["message"].partition("\n")
        matched = f"「{f['matched']}」 " if f["matched"] else ""
        lines.append(f"- {matched}{head}" + (f" — {detail.strip()}" if detail.strip() else "")
                     + f" [{f['rule']}]")
        excerpt = _excerpt(text, f)
        if excerpt:
            lines.append(f"  該当箇所: {excerpt}")
    if len(items) > MAX_ITEMS:
        lines.append(f"- ほか {len(items) - MAX_ITEMS} 件")
    return "\n".join(lines)


def _failure(message):
    """検査できなかったことを、Claude (reason) と利用者 (systemMessage) の両方に知らせる出力。"""
    return {
        "decision": "block",
        "reason": ("wording-guard の hook が、書き足した文章を検査できなかった。次の内容を人間に伝える。"
                   "textlint のセットアップはパッケージを取得するので、人間の承認を得てから実行する。\n" + message),
        "systemMessage": f"wording-guard: 書き足した文章を検査できなかった: {message}",
    }


def handle(event, check_texts=None):
    """hook の入力 (dict) を処理し、Claude Code に返す出力 (dict) を返す。何も返さないときは None。

    check_texts はテストで textlint の実行を差し替えるための引数。
    """
    tool = event.get("tool_name")
    tool_input = event.get("tool_input") or {}
    tool_response = event.get("tool_response")
    if not isinstance(tool_response, dict):
        tool_response = {}
    path = tool_input.get("file_path") or ""
    if tool not in TOOLS or not path.endswith(".md"):
        return None
    if tool_response.get("staged") is True:
        # 書き込みを保留した (ファイルは変わっていない) ので、検査するものが無い
        return None
    root = config.find_root(path)
    if root is None:
        return None
    # hook を有効にしていないリポジトリでは何もしない。型の検査より先に textlint.hook を見るのは、
    # 有効にしていないリポジトリで、設定の誤りを理由に書き込みのたびに止めないため。
    # JSON として読めないときは有効かを決められないので、知らせる (検査を省略しない)
    try:
        if not config.hook_enabled(config.read_raw(root)):
            return None
        cfg = config.load(root)
    except config.ConfigError as e:
        return _failure(str(e))
    if config.is_frozen(root, cfg, path):
        return None

    if sys.version_info < (3, 11):
        return _failure(f"Python 3.11 以降が必要 (用語ファイルを標準ライブラリ tomllib で読むため)。"
                        f"実行した Python: {sys.version.split()[0]}")
    # tomllib を使うモジュールは、Python の版を確かめてから読み込む
    from . import terms, textlint

    if check_texts is None:
        check_texts = textlint.check_texts
    try:
        term_list = terms.load_all(config.terms_paths(root, cfg))
        try:
            before = contents_before(tool, tool_response)
        except ValueError as e:
            return _failure(f"書き換える前の内容が分からない ({path}): {e}")
        try:
            with open(path, encoding="utf-8") as f:
                after = f.read()
        except (OSError, UnicodeDecodeError) as e:
            return _failure(f"書き換えた後のファイル {path} を読めない: {e}")
        try:
            removed, added = patch_lines(tool, tool_response, before, after)
        except ValueError as e:
            return _failure(f"書き換えた行が分からない ({path}): {e}")
        results = check_texts(root, cfg, term_list, [before, after], filename=os.path.basename(path))
    except (config.ConfigError, terms.TermsError, textlint.TextlintError) as e:
        return _failure(str(e))

    # 重大度 (error / warning) は検出の種類ではない。規則集の規則も、重大度を指定しなければ error になる。
    # 種類は規則の名前で見分ける (規則 prh の検出が、用語ファイルかリポジトリの prh の辞書で言い換えを決めた語)
    term_errors, rule_errors, warnings = [], [], []
    for f in introduced(in_lines(before, results[0], removed), in_lines(after, results[1], added)):
        if f["severity"] != "error":
            warnings.append((after, f))
        elif f["rule"] == "prh":
            term_errors.append((after, f))
        else:
            rule_errors.append((after, f))
    if not term_errors and not rule_errors and not warnings:
        return None
    rel = os.path.relpath(os.path.realpath(path), os.path.realpath(root))
    parts = []
    if term_errors:
        parts.append(f"{rel} に書き足した文章に、用語ファイル (またはリポジトリの textlint の設定の prh の辞書) で"
                     f"言い換えを決めた語がある。言い換えの候補から文脈に合うものを選んで直す"
                     f" (引用なら直さず、そのことを報告する):\n" + _format(term_errors))
    if rule_errors:
        parts.append(f"{rel} に書き足した文章に、リポジトリの textlint の設定で error にした規則の検出がある。"
                     f"規則の message に従って直す (引用なら直さず、そのことを報告する。検出が誤りだと考えるなら、"
                     f"直さずにそのことを報告する):\n" + _format(rule_errors))
    if warnings:
        parts.append(f"{rel} に書き足した文章に、不自然な言い回しの候補がある (textlint の warning)。"
                     f"原則に照らして判断する。候補であって、直すべきものとは限らない:\n" + _format(warnings))
    message = "\n\n".join(parts)
    if term_errors or rule_errors:
        return {"decision": "block", "reason": message}
    return {"hookSpecificOutput": {"hookEventName": EVENT_NAME, "additionalContext": message}}
