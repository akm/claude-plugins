"""用語ファイル (TOML) を読み、様式を検査する。

用語ファイルの様式と意味の正本はファイル `wording-guard/skills/wording-guard/references/terms.md`。
用語ファイルは「決めたことの記録」であって、検査の範囲ではない。
"""

import tomllib
from dataclasses import dataclass, field

VERDICTS = ("avoid", "allow")
REQUIRED_KEYS = ("pattern", "verdict", "reason", "decided_in")
AVOID_ONLY_KEYS = ("replacements", "autofix", "exceptions")
KNOWN_KEYS = set(REQUIRED_KEYS) | set(AVOID_ONLY_KEYS)


class TermsError(Exception):
    """用語ファイルが読めない、または様式に合わないときのエラー。"""


@dataclass(frozen=True)
class Term:
    """用語ファイルの 1 項目。"""

    pattern: str
    verdict: str
    reason: str
    decided_in: str
    replacements: tuple = ()
    autofix: bool = False
    exceptions: tuple = ()
    source: str = field(default="", compare=False)

    def to_dict(self):
        d = {"pattern": self.pattern, "verdict": self.verdict, "reason": self.reason,
             "decided_in": self.decided_in, "source": self.source}
        if self.verdict == "avoid":
            d.update(replacements=list(self.replacements), autofix=self.autofix,
                     exceptions=list(self.exceptions))
        return d


def is_regex(pattern):
    """`/` で始まり `/` で終わる 3 文字以上の文字列を、正規表現として扱う (prh と同じ書き方)。"""
    return len(pattern) >= 3 and pattern.startswith("/") and pattern.endswith("/")


def load_file(path):
    """用語ファイル path を読み、Term のリストを返す。様式の誤りはすべて集めて TermsError で送出する。"""
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except OSError as e:
        raise TermsError(f"用語ファイル {path} を読めない: {e}") from e
    except tomllib.TOMLDecodeError as e:
        raise TermsError(f"用語ファイル {path} が TOML として読めない: {e}") from e

    errors = []
    unknown_top = sorted(set(data) - {"terms"})
    if unknown_top:
        errors.append(f"{path}: 最上位に置けるのは terms だけ (余分なキー: {', '.join(unknown_top)})")
    entries = data.get("terms", [])
    if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
        errors.append(f"{path}: terms は [[terms]] の表の並びにする")
        entries = []

    terms, seen = [], {}
    for i, entry in enumerate(entries, 1):
        where = f"{path}: {i} 番目の [[terms]]"
        if isinstance(entry.get("pattern"), str) and entry["pattern"]:
            where += f" (pattern = {entry['pattern']!r})"
        term, problems = _parse_entry(entry, path)
        errors.extend(f"{where}: {p}" for p in problems)
        if term is None:
            continue
        if term.pattern in seen:
            errors.append(f"{where}: 同じ pattern が {seen[term.pattern]} 番目にもある")
            continue
        seen[term.pattern] = i
        terms.append(term)
    if errors:
        raise TermsError("\n".join(errors))
    return terms


def _parse_entry(entry, path):
    """[[terms]] の表 1 つを検査する。(Term または None, 問題のリスト) を返す。"""
    problems = []
    unknown = sorted(set(entry) - KNOWN_KEYS)
    if unknown:
        problems.append(f"知らないキーがある: {', '.join(unknown)}")
    for key in REQUIRED_KEYS:
        if not isinstance(entry.get(key), str) or not entry[key].strip():
            problems.append(f"{key} を空でない文字列で書く")
    verdict = entry.get("verdict")
    if isinstance(verdict, str) and verdict not in VERDICTS:
        problems.append(f"verdict は {' か '.join(VERDICTS)} にする (書かれた値: {verdict!r})")
    pattern = entry.get("pattern")
    if isinstance(pattern, str) and pattern.startswith("/") and not is_regex(pattern):
        problems.append("/ で始まる pattern は正規表現として / で閉じる")

    if verdict == "allow":
        present = [k for k in AVOID_ONLY_KEYS if k in entry]
        if present:
            problems.append(f"許容する語には {', '.join(present)} を書けない (避ける語だけのキー)")
    elif verdict == "avoid":
        reps = entry.get("replacements")
        if not _is_str_list(reps) or not reps:
            problems.append("避ける語には replacements (言い換えの候補) を 1 つ以上、文字列の配列で書く")
        if "autofix" in entry and not isinstance(entry["autofix"], bool):
            problems.append("autofix は true か false にする")
        if entry.get("autofix") is True and _is_str_list(reps) and len(reps) != 1:
            problems.append("autofix = true の語は、replacements を 1 つに決める (自動修正の置き換え先にするため)")
        if "exceptions" in entry and (not _is_str_list(entry["exceptions"]) or not entry["exceptions"]):
            problems.append("exceptions は空でない文字列の配列にする")

    if problems:
        return None, problems
    return Term(
        pattern=entry["pattern"], verdict=verdict, reason=entry["reason"].strip(),
        decided_in=entry["decided_in"].strip(),
        replacements=tuple(entry.get("replacements", ())), autofix=entry.get("autofix", False),
        exceptions=tuple(entry.get("exceptions", ())), source=path,
    ), []


def _is_str_list(value):
    return isinstance(value, list) and all(isinstance(v, str) and v for v in value)


def load_all(paths):
    """用語ファイルを書かれた順に読み、まとめた Term のリストを返す。

    同じ pattern が複数のファイルにあれば、後に書かれたファイルの項目を使う
    (ユーザー単位のファイルを先に、リポジトリのファイルを後に書けば、リポジトリ側が優先される)。
    """
    merged = {}
    errors = []
    for p in paths:
        try:
            for t in load_file(p):
                merged.pop(t.pattern, None)
                merged[t.pattern] = t
        except TermsError as e:
            errors.append(str(e))
    if errors:
        raise TermsError("\n".join(errors))
    return list(merged.values())
