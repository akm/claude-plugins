"""PostToolUse の hook (ツールの実行の直後に動く処理) の本体。

Edit / MultiEdit / Write で Markdown に書き足した文字列を textlint で検査し、結果を Claude に返す。
振る舞いの正本はファイル `wording-guard/skills/wording-guard/references/textlint.md` の「hook」。

  - 検査するのは、設定キー textlint.hook を true にしたリポジトリの Markdown だけ。それ以外は何もしない
    (プラグインの hook は、プラグインを有効にしたすべてのリポジトリで動くため)。textlint.hook は設定の型を
    検査する前に見るので、有効にしていないリポジトリでは設定の誤りでも何もしない。
  - Edit / MultiEdit は、書き換える前の文字列 (old_string) と後の文字列 (new_string) を両方検査し、
    後で増えた検出だけを返す。new_string には、一意に特定するために変えていない前後の行も入るので、
    そこにあった検出 (他の人が既に書いた文章) を、今回持ち込んだものとして扱わないため。
  - Write は、書いた内容の全体を検査する (書き換える前の内容は hook に渡されない)。
  - error (用語ファイルの避ける語) があれば decision: block で直すよう求め、warning (規則集の候補) だけなら
    additionalContext で判断の材料として渡す。
  - 設定・用語ファイルの誤りや、textlint が入っていないときは、検査を省略せずに、Claude と利用者に知らせる。
"""

import collections
import os
import sys

from . import config

MAX_ITEMS = 30
EVENT_NAME = "PostToolUse"


def _pairs(tool, tool_input):
    """(書き換える前の文字列, 後の文字列) の組を返す。対象外のツールなら空のリスト。"""
    if tool == "Edit":
        return [(tool_input.get("old_string", ""), tool_input.get("new_string", ""))]
    if tool == "MultiEdit":
        return [(e.get("old_string", ""), e.get("new_string", "")) for e in tool_input.get("edits", [])]
    if tool == "Write":
        return [("", tool_input.get("content", ""))]
    return []


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
    tool_input = event.get("tool_input") or {}
    path = tool_input.get("file_path") or ""
    pairs = _pairs(event.get("tool_name"), tool_input)
    if not pairs or not path.endswith(".md"):
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
        texts = [t for pair in pairs for t in pair]
        results = check_texts(root, cfg, term_list, texts, filename=os.path.basename(path))
    except (config.ConfigError, terms.TermsError, textlint.TextlintError) as e:
        return _failure(str(e))

    errors, warnings = [], []
    for i, (_, after_text) in enumerate(pairs):
        for f in introduced(results[2 * i], results[2 * i + 1]):
            (errors if f["severity"] == "error" else warnings).append((after_text, f))
    if not errors and not warnings:
        return None
    rel = os.path.relpath(os.path.realpath(path), os.path.realpath(root))
    parts = []
    if errors:
        parts.append(f"{rel} に書き足した文章に、用語ファイルで言い換えを決めた語がある。"
                     f"言い換えの候補から文脈に合うものを選んで直す (引用なら直さず、そのことを報告する):\n"
                     + _format(errors))
    if warnings:
        parts.append(f"{rel} に書き足した文章に、不自然な言い回しの候補がある (textlint の warning)。"
                     f"原則に照らして判断する。候補であって、直すべきものとは限らない:\n" + _format(warnings))
    message = "\n\n".join(parts)
    if errors:
        return {"decision": "block", "reason": message}
    return {"hookSpecificOutput": {"hookEventName": EVENT_NAME, "additionalContext": message}}
