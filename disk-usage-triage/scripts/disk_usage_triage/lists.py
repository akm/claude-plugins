"""トリアージ・一覧・選んだ項目 (計画 docs/plans/2026-11-22-1630-feat-disk-usage-triage-plan.md の R4〜R13・R20・KD15・KTD3・
KTD4・KTD15・KTD17)。

調べるディレクトリと一覧の項目をモジュール scan で調べ、英字と番号の付いた一覧にして、トリアージのディレクトリに保存する。
一覧の項目から、消す項目を選ぶ。ファイルの様式の SSOT は、文書 `disk-usage-triage/references/files.md` の節
「トリアージのディレクトリ (`runs/<ID>/`)」。

- 一覧のファイルには、項目の番号・パス・使用量・読めなかったパスを保存し、判定は保存しない。判定は、一覧を示すたびに、その時の
  設定・記録・判定表からモジュール judge で求める (KTD17)。
- 一覧の表 (Markdown) と注記の文は、このモジュールが作る。スキルは、出力の表と注記をそのまま示す (KTD17)。
- 選んだ項目は、パスで区別する。親と子の両方を選ぶと、親だけを残す (R10)。
- 出力に、トリアージのディレクトリのパスを含めない。Claude がそのパスをコマンドに書くと、hook が拒否するため (KTD17)。
"""

import datetime
import os
import re
import shlex
import time

from . import config, judge, records, scan as du_scan, store

RUNS = "runs"
LISTS = "lists"
SELECTION = "selection.json"
SHOWN = 30  # 表に示す項目の数。残りはその他の行にまとめる (R7)
GB = 1_000_000_000  # R8
MB = 1_000_000
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"  # 1 つのトリアージで作れる一覧は 26 個まで (R9)

LIST_KEYS = ("version", "letter", "created_at", "source", "dirs", "items")  # files.md の一覧のキーの表と同じ順序
DIR_KEYS = ("requested", "path", "status", "bytes", "error", "unreadable")
ITEM_KEYS = ("number", "path", "bytes", "unreadable")
SOURCE_KINDS = {"scan_dirs": (), "item": ("number", "path")}
SELECTION_KEYS = ("version", "items")
SELECTED_KEYS = ("number", "path", "bytes")
TABLE_HEADER = "| 番号 | パス | 使用量 | 判定 | 理由 |"

_RUN_ID = re.compile(r"[0-9]{8}-[0-9]{6}\Z")
_NUMBER = re.compile(r"([A-Z])([1-9][0-9]*)\Z")
_LETTER = re.compile(r"[A-Z]\Z")
_RESTART = "このトリアージは使わずに、run start で新しいトリアージを始めて調べ直す"
_DU_NOTE = "使用量は du で測った値で、APFS のクローンとハードリンクのために、消して空く量と一致しないことがある。"


class _Rejected(Exception):
    """入力の誤りか、ファイルが無いか壊れている。errors は利用者に示す理由の配列。"""

    def __init__(self, errors):
        super().__init__("。".join(errors))
        self.errors = list(errors)


# --- 表示 -----------------------------------------------------------------------------------------------------------

def format_size(value):
    """使用量 (バイト) の表示。1 GB (1,000,000,000 バイト) 以上は GB、未満は MB で、どちらも小数 1 桁 (R8)。"""
    if value >= GB:
        return f"{value / GB:.1f} GB"
    return f"{value / MB:.1f} MB"


def display_path(path):
    """パスの表示。ホームディレクトリの下なら ~ で始まる形にし、UTF-8 として読めないバイトは \\xff の形にする (R6・KTD2)。"""
    text = records.display({"kind": "directory", "path": path})
    return text.encode("utf-8", errors="surrogateescape").decode("utf-8", errors="backslashreplace")


def _code(text):
    """Markdown のコードの形。text の中のバッククォートより長いバッククォートで囲む。"""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    padded = f" {text} " if text.startswith("`") or text.endswith("`") else text
    return f"{fence}{padded}{fence}"


def _cell(text):
    """表のセルの文字列。| をエスケープし、改行を空白にする。"""
    return (text or "").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def judgment_label(result):
    """表に示す判定 (R6・R20)。判定の無い項目は「判定なし」。記録で決まった判定には、だれが決めたかと日付を添える。"""
    if result["judgment"] is None:
        return "判定なし"
    label = judge.JUDGMENT_LABELS[result["judgment"]]
    record = result["record"]
    if result["source"] == "record" and record is not None and record["judgment"] == result["judgment"]:
        who = judge.DECIDER_LABELS[record["decided_by"]]
        space = " " if who.isascii() else ""
        verb = "判定" if record["decided_by"] == "claude" else "記録"
        label += f" ({who}{space}が {record['decided_on']} に{verb})"
    return label


def command_text(command):
    """消すコマンドの表示。ツールのコマンドは環境変数を前に付けた形、rm は rm -rf <パス>。削除のシェルスクリプトで実行する形は U7 で決める。"""
    if command is None:
        return None
    if command["type"] == "rm":
        words = ["rm", "-rf", command["path"]]
    else:
        words = [f"{name}={value}" for name, value in command.get("env", {}).items()] + list(command["args"])
    text = " ".join(shlex.quote(word) for word in words)
    return text.encode("utf-8", errors="surrogateescape").decode("utf-8", errors="backslashreplace")


# --- トリアージ -----------------------------------------------------------------------------------------------------

def _name(run, *parts):
    """保存先のディレクトリからの、トリアージのファイルの相対パス (store.read と Transaction.write に渡す)。"""
    return os.path.join(RUNS, run, *parts)


def _check_run(run):
    if not isinstance(run, str) or not _RUN_ID.match(run):
        raise _Rejected([f"トリアージの ID ({run!r}) が YYYYMMDD-HHMMSS の形でない"])
    if not os.path.isdir(os.path.join(store.home(), _name(run))):
        raise _Rejected([f"トリアージ {run} が無い (run start が出力したトリアージの ID を指定する)"])


def _load_config():
    try:
        current = config.load()
    except store.Corrupt as e:
        return None, [str(e)]
    if current is None:
        return None, [f"設定 ({config.path()}) が無い。先に設定を作る"]
    return current, []


class _Context:
    """判定に使う、設定・保護の一覧・判定表・記録。関数 _context が作る。"""

    def __init__(self, current, records_):
        self.config = current
        self.timeout = current["timeout_seconds"]
        self.env = judge.environment(current)
        self.rows = judge.load_table()
        self.records = judge.DirectoryRecords(records_)

    def judge(self, path):
        return judge.judge(path, self.env, self.rows, self.records)


def _context():
    """設定と記録を読む。無いか壊れていれば _Rejected (設定と記録の誤りを一緒に示す)。"""
    current, errors = _load_config()
    try:
        loaded = records.load()
    except store.Corrupt as e:
        errors.append(str(e))
    if errors:
        raise _Rejected(errors)
    return _Context(current, loaded)


def run_start(*, now=None):
    """サブコマンド run start。トリアージのディレクトリを作り、トリアージの ID を返す (KTD17)。"""
    _, errors = _load_config()
    if errors:
        return {"status": "unsatisfied", "run": None, "created_at": None, "errors": errors}
    moment = now or datetime.datetime.now().astimezone()
    run = moment.strftime("%Y%m%d-%H%M%S")
    with store.transaction():
        os.makedirs(os.path.join(store.home(), RUNS), exist_ok=True)
        try:
            os.mkdir(os.path.join(store.home(), _name(run)))
        except FileExistsError:
            return {"status": "unsatisfied", "run": None, "created_at": None,
                    "errors": [f"同じ秒に始めたトリアージ {run} がある。少し待ってから、もう一度 run start を実行する"]}
    return {"status": "ok", "run": run, "created_at": moment.isoformat(timespec="seconds"), "errors": []}


# --- 一覧のファイル -------------------------------------------------------------------------------------------------

def _paths_error(value, key):
    if not isinstance(value, list) or not all(isinstance(p, str) and os.path.isabs(p) for p in value):
        return f"{key} が、絶対パスの配列でない"
    return None


def _bytes_ok(value):
    return type(value) is int and value >= 0  # 真偽値 (int の派生) は誤りにする


def _dir_errors(index, value):
    where = f"dirs[{index}]"
    if not isinstance(value, dict) or set(value) != set(DIR_KEYS):
        return [f"{where} が、キー {'・'.join(DIR_KEYS)} だけを持つオブジェクトでない"]
    errors = []
    if not isinstance(value["requested"], str) or not isinstance(value["path"], str) or not os.path.isabs(value["path"]):
        errors.append(f"{where} の requested が文字列でないか、path が絶対パスでない")
    status = value["status"]
    if status == du_scan.STATUS_OK:
        if not _bytes_ok(value["bytes"]) or value["error"] is not None:
            errors.append(f"{where} の status が ok なのに、bytes が 0 以上の整数でないか、error が null でない")
    elif status in (du_scan.STATUS_TIMED_OUT, du_scan.STATUS_FAILED):
        if value["bytes"] is not None or not isinstance(value["error"], str) or value["unreadable"] != []:
            errors.append(f"{where} の status が {status} なのに、bytes が null でないか、error が文字列でないか、"
                          "unreadable が空でない")
    else:
        errors.append(f"{where} の status が ok・timed_out・failed のどれでもない")
    error = _paths_error(value["unreadable"], f"{where} の unreadable")
    if error:
        errors.append(error)
    return errors


def list_errors(data, letter=None):
    """一覧のファイルの中身の形の誤りの配列 (files.md の節「`lists/<英字>.json`」)。letter はファイル名の英字。"""
    if not isinstance(data, dict):
        return ["JSON のオブジェクトでない"]
    if set(data) != set(LIST_KEYS):
        return [f"キーが {'・'.join(LIST_KEYS)} でない"]
    errors = []
    if not isinstance(data["letter"], str) or not _LETTER.match(data["letter"]):
        errors.append("letter が A〜Z の 1 文字でない")
    elif letter is not None and data["letter"] != letter:
        errors.append(f"letter ({data['letter']}) が、ファイル名の英字 ({letter}) と違う")
    if not isinstance(data["created_at"], str):
        errors.append("created_at が文字列でない")
    else:
        try:
            datetime.datetime.fromisoformat(data["created_at"])
        except ValueError:
            errors.append("created_at が ISO 8601 の時刻でない")
    source = data["source"]
    kind = source.get("kind") if isinstance(source, dict) else None
    if not isinstance(kind, str) or kind not in SOURCE_KINDS or set(source) != {"kind", *SOURCE_KINDS[kind]}:
        errors.append("source が、{\"kind\": \"scan_dirs\"} か {\"kind\": \"item\", \"number\", \"path\"} の形でない")
    elif kind == "item" and (not isinstance(source["number"], str) or not _NUMBER.match(source["number"])
                             or not isinstance(source["path"], str) or not os.path.isabs(source["path"])):
        errors.append("source の number が番号の形でないか、path が絶対パスでない")
    dirs = data["dirs"]
    if not isinstance(dirs, list) or not dirs:
        errors.append("dirs が、1 つ以上の要素を持つ配列でない")
    else:
        for index, value in enumerate(dirs):
            errors += _dir_errors(index, value)
    items = data["items"]
    if not isinstance(items, list):
        return errors + ["items が配列でない"]
    paths = set()
    for index, item in enumerate(items):
        where = f"items[{index}]"
        if not isinstance(item, dict) or set(item) != set(ITEM_KEYS):
            errors.append(f"{where} が、キー {'・'.join(ITEM_KEYS)} だけを持つオブジェクトでない")
            continue
        if type(item["number"]) is not int or item["number"] != index + 1:
            errors.append(f"{where} の number が {index + 1} でない (番号は 1 から順に付ける)")
        if not isinstance(item["path"], str) or not os.path.isabs(item["path"]):
            errors.append(f"{where} の path が絶対パスでない")
        elif item["path"] in paths:
            errors.append(f"{where} の path が、ほかの項目と同じ")
        else:
            paths.add(item["path"])
        if not _bytes_ok(item["bytes"]):
            errors.append(f"{where} の bytes が 0 以上の整数でない")
        error = _paths_error(item["unreadable"], f"{where} の unreadable")
        if error:
            errors.append(error)
    return errors


def _list_file(run, letter):
    return os.path.join(store.home(), _name(run, LISTS, f"{letter}.json"))


def _load_list(run, letter):
    """一覧のファイルを読む。無ければ _Rejected、壊れていれば新しいトリアージで調べ直すよう示す _Rejected。"""
    try:
        data = store.read(_name(run, LISTS, f"{letter}.json"))
    except store.Corrupt as e:
        raise _Rejected([f"一覧 {letter} のファイルが壊れている ({e.reason})。{_RESTART}"]) from None
    if data is None:
        raise _Rejected([f"トリアージ {run} に、一覧 {letter} は無い"])
    errors = list_errors(data, letter)
    if errors:
        raise _Rejected([f"一覧 {letter} のファイルが壊れている ({'。'.join(errors)})。{_RESTART}"])
    return data


def _existing_letters(run):
    directory = os.path.join(store.home(), _name(run, LISTS))
    try:
        names = os.listdir(directory)
    except FileNotFoundError:
        return []
    return sorted(name[0] for name in names if len(name) == 6 and name.endswith(".json") and _LETTER.match(name[0]))


def _next_letter(run):
    """次の一覧の英字。26 個 (A〜Z) を作り終えていれば _Rejected (R9)。"""
    letters = _existing_letters(run)
    index = LETTERS.index(letters[-1]) + 1 if letters else 0
    if index >= len(LETTERS):
        raise _Rejected([f"トリアージ {run} では、一覧を 26 個 (A〜Z) 作り終えたので、これ以上作らない。{_RESTART}"
                         "。今の選んだ項目は、新しいトリアージに引き継がない"])
    return LETTERS[index]


def _parse_number(text):
    match = _NUMBER.match(text) if isinstance(text, str) else None
    if not match:
        raise _Rejected([f"番号 ({text!r}) が、大文字の英字 1 つと、先頭に 0 を付けない 1 以上の整数の形 (例: A3) でない"])
    return match[1], int(match[2])


class _Lists:
    """1 つのトリアージの一覧のファイルを、必要になったときに 1 回だけ読む。"""

    def __init__(self, run):
        self.run = run
        self._loaded = {}

    def get(self, letter):
        if letter not in self._loaded:
            self._loaded[letter] = _load_list(self.run, letter)
        return self._loaded[letter]

    def resolve(self, numbers):
        """番号の配列を、(番号, 一覧の項目) の配列にする。形の誤りか存在しない番号が 1 つでもあれば、すべてを示す _Rejected。"""
        resolved, errors = [], []
        for text in numbers:
            try:
                letter, number = _parse_number(text)
                items = self.get(letter)["items"]
            except _Rejected as e:
                errors += e.errors
                continue
            if number > len(items):
                errors.append(f"番号 {text} は無い (一覧 {letter} は {letter}1〜{letter}{len(items)})" if items
                              else f"番号 {text} は無い (一覧 {letter} に項目は無い)")
                continue
            resolved.append((text, items[number - 1]))
        if errors:
            raise _Rejected(list(dict.fromkeys(errors)))
        return resolved


# --- 一覧を作る・示す -----------------------------------------------------------------------------------------------

def _dir_record(result):
    return {key: result[key] for key in DIR_KEYS}


def _create_list(run, source, results, now):
    """調べた結果から一覧を作って保存し、その中身を返す。項目は使用量の多い順、同じ使用量はパスの順 (R5)。"""
    items = [item for result in results if result["status"] == du_scan.STATUS_OK for item in result["items"]]
    items.sort(key=lambda item: (-item["bytes"], item["path"]))
    moment = now or datetime.datetime.now().astimezone()
    with store.transaction() as tx:
        letter = _next_letter(run)  # du を実行している間に、ほかのプロセスが一覧を作ったことがあるので、ロックを取ってから決める
        data = {"version": store.VERSION, "letter": letter, "created_at": moment.isoformat(timespec="seconds"),
                "source": source, "dirs": [_dir_record(result) for result in results],
                "items": [{"number": index, "path": item["path"], "bytes": item["bytes"],
                           "unreadable": list(item["unreadable"])} for index, item in enumerate(items, start=1)]}
        tx.write(_name(run, LISTS, f"{letter}.json"), data)
    return data


def _number(letter, item):
    return f"{letter}{item['number']}"


def item_view(number, item, result):
    """出力の項目。表に出さない影響と消すコマンドも含める (R6)。"""
    return {"number": number, "path": item["path"], "display": display_path(item["path"]), "bytes": item["bytes"],
            "size": format_size(item["bytes"]), "judgment": result["judgment"], "judgment_label": judgment_label(result),
            "reason": result["reason"], "record": result["record"], "impact": result["impact"],
            "command": result["command"], "command_text": command_text(result["command"]),
            "process_names": list(result["process_names"]), "dedicated_list": result["dedicated_list"],
            "unreadable_count": len(item["unreadable"])}


def _table(letter, shown, others):
    lines = [TABLE_HEADER, "| --- | --- | --- | --- | --- |"]
    for item, result in shown:
        lines.append(f"| {_number(letter, item)} | {_cell(_code(display_path(item['path'])))} | {format_size(item['bytes'])} | "
                     f"{_cell(judgment_label(result))} | {_cell(result['reason'])} |")
    if others:
        total = sum(item["bytes"] for item, _ in others)
        lines.append(f"| | その他 {len(others)} 項目 | 合計 {format_size(total)} | | |")
    return "\n".join(lines)


def _dir_notes(data):
    """調べたディレクトリごとの注記。使用量と、項目に入らない使用量 (直下のファイルなど。R5)、結果を出せなかった理由 (R4)。"""
    notes = []
    for result in data["dirs"]:
        shown = _code(display_path(result["path"]))
        if result["status"] != du_scan.STATUS_OK:
            notes.append(f"{shown} は一覧に入れていない ({result['error']})。")
            continue
        prefix = result["path"].rstrip("/") + "/"
        inside = sum(item["bytes"] for item in data["items"]
                     if item["path"].startswith(prefix) and "/" not in item["path"][len(prefix):])
        note = f"{shown} は {format_size(result['bytes'])}。"
        rest = max(0, result["bytes"] - inside)
        if format_size(rest) != format_size(0):  # 0.0 MB と示すだけの差 (ディレクトリ自身の大きさなど) は示さない
            note += f"うち {format_size(rest)} は項目に入らない (直下のファイルなど。du -d 1 はディレクトリだけを項目にするため)。"
        notes.append(note)
    return notes


def _unreadable_notes(letter, data, shown, others):
    """読めなかったディレクトリの注記 (KTD4)。読めなかったパスそのものは示さない。"""
    notes = []
    numbers = [_number(letter, item) for item, _ in shown if item["unreadable"]]
    hidden = sum(1 for item, _ in others if item["unreadable"])
    if numbers or hidden:
        if numbers:
            text = f"読めなかったディレクトリを含む項目: {'・'.join(numbers)}。"
            if hidden:
                text += f"その他の行にも {hidden} 項目ある。"
        else:
            text = f"その他の行の {hidden} 項目は、読めなかったディレクトリを含む。"
        notes.append(text + "これらの項目の使用量は、実際より少ない。読めなかったパスは、依頼すると示す。")
    unmapped = sum(len(result["unreadable"]) for result in data["dirs"])
    if unmapped:
        notes.append(f"どの項目にも入らない読めなかったディレクトリが {unmapped} 個ある。使用量を測れないので、表にも、"
                     "調べたディレクトリの使用量にも入っていない。")
    return notes


def _deletable(judged):
    return [(item, result) for item, result in judged if result["judgment"] == "deletable"]


def _deletable_note(letter, judged, all_items):
    """「消してよい」の項目をすべて選ぶ選び方の注記 (R11)。

    まとめて選ぶのは番号が 1〜30 の項目 (--all を付けない表の項目) の「消してよい」で、31 番目以降 (その他の行の項目) は、
    そのことも依頼されたときだけ選ぶ (関数 select_add の範囲)。表示している項目では数えない。--all で 31 項目以上を示すと、
    表にその他の行が無く、表の項目と選ぶ範囲が違うため。そのときは、範囲を番号で書く。
    """
    visible, hidden = _deletable(judged[:SHOWN]), _deletable(judged[SHOWN:])
    if not visible and not hidden:
        return []
    if all_items and len(judged) > SHOWN:
        first, rest = f" {letter}1〜{letter}{SHOWN} の", f"{letter}{SHOWN + 1} 以降の"  # 英数字の前に空白を入れる
    else:
        first, rest = "表の", "その他の行の"
    text = ""
    if visible:
        total = sum(item["bytes"] for item, _ in visible)
        text = (f"一覧 {letter} の{first}「消してよい」の項目 ({len(visible)} 項目・合計 {format_size(total)}) は、"
                "依頼すればまとめて選べる。")
    if hidden:
        total = sum(item["bytes"] for item, _ in hidden)
        text += (f"{rest}「消してよい」の項目 ({len(hidden)} 項目・合計 {format_size(total)}) は、そのことも依頼したとき"
                 "だけ選ぶ。")
    return [text]


def _unreadable_view(letter, data, shown):
    return {"items": [{"number": _number(letter, item), "display": display_path(item["path"]),
                       "paths": [display_path(path) for path in item["unreadable"]]}
                      for item, _ in shown if item["unreadable"]],
            "unmapped": [display_path(path) for result in data["dirs"] for path in result["unreadable"]]}


def _source_view(source):
    if source["kind"] == "item":
        return {**source, "display": display_path(source["path"])}
    return dict(source)


_EMPTY_VIEW = {"letter": None, "created_at": None, "source": None, "table": None, "notes": [], "items": [], "others": None,
               "unreadable": None}


def _view(data, ctx, *, all_items=False, unreadable=False):
    """一覧の出力。判定は、その時の設定・記録・判定表から求める (KTD17)。"""
    letter = data["letter"]
    judged = [(item, ctx.judge(item["path"])) for item in data["items"]]
    shown, others = (judged, []) if all_items else (judged[:SHOWN], judged[SHOWN:])
    hidden_deletable = _deletable(others)
    notes = (_dir_notes(data) + _unreadable_notes(letter, data, shown, others) + [_DU_NOTE]
             + _deletable_note(letter, judged, all_items))
    return {"letter": letter, "created_at": data["created_at"], "source": _source_view(data["source"]),
            "table": _table(letter, shown, others), "notes": notes,
            "items": [item_view(_number(letter, item), item, result) for item, result in shown],
            "others": {"count": len(others), "bytes": sum(item["bytes"] for item, _ in others),
                       "size": format_size(sum(item["bytes"] for item, _ in others)),
                       "deletable_count": len(hidden_deletable),
                       "deletable_bytes": sum(item["bytes"] for item, _ in hidden_deletable),
                       "unreadable_count": sum(1 for item, _ in others if item["unreadable"])} if others else None,
            "unreadable": _unreadable_view(letter, data, shown) if unreadable else None}


def scan(run, item=None, *, now=None):
    """サブコマンド scan。item (番号) が無ければ、設定の調べるディレクトリを調べて最初の一覧を作る。item があれば、その項目の
    1 つ下の階層を調べて一覧を作る。専用の一覧の項目 (KTD5) なら、一覧を作らずに専用の一覧の種類を返す (専用の一覧は U10〜U12)。

    同じものをもう一度調べると、そのたびに新しい一覧を作る (R5)。結果を出せた調べるディレクトリが無いときと、項目の下の階層を
    調べて結果を出せなかったときは、一覧を作らない (R4)。
    """
    base = {"run": run, "dedicated_list": None, "item": None}
    try:
        _check_run(run)
        ctx = _context()
        if item is None:
            _next_letter(run)  # du を実行する前に、一覧を作れるかを確かめる
            results = du_scan.scan_directories(ctx.config["scan_dirs"], timeout=ctx.timeout)
            if not any(result["status"] == du_scan.STATUS_OK for result in results):
                raise _Rejected(["どの調べるディレクトリも結果を出せなかったので、一覧を作らない"]
                                + [f"{display_path(result['path'])}: {result['error']}" for result in results])
            source = {"kind": "scan_dirs"}
        else:
            [(number, entry)] = _Lists(run).resolve([item])
            result = ctx.judge(entry["path"])
            base["item"] = item_view(number, entry, result)
            if result["dedicated_list"] is not None:
                return {"status": "ok", **base, "dedicated_list": result["dedicated_list"], **_EMPTY_VIEW, "errors": []}
            _next_letter(run)
            scanned = du_scan.scan_directory(entry["path"], timeout=ctx.timeout)
            if scanned["status"] != du_scan.STATUS_OK:
                raise _Rejected([f"{number} ({display_path(entry['path'])}) の下の階層を調べられなかったので、一覧を作らない "
                                 f"({scanned['error']})"])
            results = [scanned]
            source = {"kind": "item", "number": number, "path": entry["path"]}
        data = _create_list(run, source, results, now)
        return {"status": "ok", **base, **_view(data, ctx), "errors": []}
    except _Rejected as e:
        return {"status": "unsatisfied", **base, **_EMPTY_VIEW, "errors": e.errors}


def show(run, letter, *, all_items=False, unreadable=False):
    """サブコマンド list show。一覧を、その時の判定と一緒に示す。all_items が真ならその他の行にまとめずにすべての項目を、
    unreadable が真なら読めなかったパスも出力する (R7・KTD4)。"""
    try:
        _check_run(run)
        if not isinstance(letter, str) or not _LETTER.match(letter):
            raise _Rejected([f"一覧の英字 ({letter!r}) が、大文字の英字 1 つでない"])
        ctx = _context()
        data = _load_list(run, letter)
        return {"status": "ok", "run": run, **_view(data, ctx, all_items=all_items, unreadable=unreadable), "errors": []}
    except _Rejected as e:
        return {"status": "unsatisfied", "run": run, **_EMPTY_VIEW, "errors": e.errors}


# --- 選んだ項目 -----------------------------------------------------------------------------------------------------

def selection_errors(data):
    """選んだ項目のファイルの中身の形の誤りの配列 (files.md の節「`selection.json`」)。"""
    if not isinstance(data, dict) or set(data) != set(SELECTION_KEYS):
        return [f"キーが {'・'.join(SELECTION_KEYS)} のオブジェクトでない"]
    items = data["items"]
    if not isinstance(items, list):
        return ["items が配列でない"]
    errors, paths = [], []
    for index, item in enumerate(items):
        where = f"items[{index}]"
        if not isinstance(item, dict) or set(item) != set(SELECTED_KEYS):
            errors.append(f"{where} が、キー {'・'.join(SELECTED_KEYS)} だけを持つオブジェクトでない")
            continue
        if not isinstance(item["number"], str) or not _NUMBER.match(item["number"]):
            errors.append(f"{where} の number が番号の形でない")
        if not isinstance(item["path"], str) or not os.path.isabs(item["path"]):
            errors.append(f"{where} の path が絶対パスでない")
            continue
        if not _bytes_ok(item["bytes"]):
            errors.append(f"{where} の bytes が 0 以上の整数でない")
        for other in paths:
            if other == item["path"]:
                errors.append(f"{where} の path が、ほかの項目と同じ")
            elif _is_under(item["path"], other) or _is_under(other, item["path"]):
                errors.append(f"{where} の path が、ほかの項目の親か子")
        paths.append(item["path"])
    return errors


def _check_selection(data):
    """store が読んだ選んだ項目のファイルを確認し、項目の配列を返す。無ければ空の配列。壊れていれば _Rejected。"""
    if data is None:
        return []
    errors = selection_errors(data)
    if errors:
        raise _Rejected([f"選んだ項目のファイルが壊れている ({'。'.join(errors)})。{_RESTART}"])
    return data["items"]


def _read_selection(run, tx=None):
    try:
        data = tx.read(_name(run, SELECTION)) if tx is not None else store.read(_name(run, SELECTION))
    except store.Corrupt as e:
        raise _Rejected([f"選んだ項目のファイルが壊れている ({e.reason})。{_RESTART}"]) from None
    return _check_selection(data)


def _is_under(child, parent):
    """パス child が parent より下にあるか (パスの文字列で比べる。一覧の項目は du が出したパスなので、同じ形で比べられる)。"""
    return child.startswith(parent.rstrip("/") + "/")


def _summary(items):
    total = sum(item["bytes"] for item in items)
    return {"count": len(items), "bytes": total, "size": format_size(total)}


def _short(number, path):
    return {"number": number, "display": display_path(path)}


def _blockers(path, result, ctx, clock):
    """選べない理由の配列 (R12・KTD5)。保護の一覧の項目・判定が「残す」・判定なし・保護の一覧の場所を含む・「残す」の項目を
    含む・下の探索の順に調べ、前の理由があれば後の理由は調べない (下を探すのは時間がかかるため)。"""
    found = judge.protected_blockers(path, ctx.env)
    if found:
        return found
    if result["judgment"] == "keep":
        return [{"kind": "keep", "path": path, "reason": f"判定が「残す」({result['reason']})"}]
    if result["judgment"] is None:
        return [{"kind": "unjudged", "path": path,
                 "reason": "判定なし (Claude が調べて判定を記録してから選ぶ。消すコマンドが決まっていないため)"}]
    return (judge.contained_blockers(path, ctx.env) or judge.keep_blockers(path, ctx.env, ctx.rows, ctx.records)
            or judge.below_blockers(path, timeout=ctx.timeout, clock=clock))


def select_add(run, numbers=(), *, all_deletable=None, include_others=False, clock=time.monotonic):
    """サブコマンド select add。番号の項目か、一覧 all_deletable の「消してよい」の項目を選ぶ (R10〜R12)。

    all_deletable は、番号が 1〜30 の項目 (--all を付けない list show の表の項目。R7) だけから選び、include_others が真なら
    31 番目以降の項目 (その他の行の項目) からも選ぶ (R11)。選べない項目は
    選ばずに理由を返し、選べる項目は選ぶ。形の誤りか存在しない番号が 1 つでもあれば、何も選ばない (R12)。
    """
    base = {"run": run, "added": [], "already": [], "replaced": [], "rejected": [], "others_deletable": None,
            "selection": None}
    try:
        _check_run(run)
        ctx = _context()
        lists = _Lists(run)
        if all_deletable is not None:
            if not isinstance(all_deletable, str) or not _LETTER.match(all_deletable):
                raise _Rejected([f"一覧の英字 ({all_deletable!r}) が、大文字の英字 1 つでない"])
            data = lists.get(all_deletable)
            judged = [(item, ctx.judge(item["path"])) for item in data["items"]]
            scope = judged if include_others else judged[:SHOWN]
            candidates = [(_number(all_deletable, item), item) for item, _ in _deletable(scope)]
            if not include_others:
                hidden = _deletable(judged[SHOWN:])
                base["others_deletable"] = _summary([item for item, _ in hidden])
        else:
            candidates = lists.resolve(numbers)
        snapshot = _read_selection(run)
        accepted, seen = [], set()
        for number, item in candidates:
            path = item["path"]
            if path in seen:
                continue
            seen.add(path)
            if any(selected["path"] == path for selected in snapshot):
                base["already"].append(_short(number, path))
                continue
            parent = next((s for s in snapshot if _is_under(path, s["path"])), None)
            if parent is not None:  # 時間のかかる下の探索の前に除く。最後の判断は、ロックを取ってから行う
                base["rejected"].append({**_short(number, path), "reasons": [
                    f"親のディレクトリの {parent['number']} ({display_path(parent['path'])}) を選んでいる"]})
                continue
            result = ctx.judge(path)
            reasons = _blockers(path, result, ctx, clock)
            if reasons:
                base["rejected"].append({**_short(number, path), "reasons": [r["reason"] for r in reasons]})
            else:
                accepted.append((number, item, result))
        with store.transaction() as tx:
            current = list(_read_selection(run, tx))
            for number, item, result in accepted:
                path = item["path"]
                if any(s["path"] == path for s in current):
                    base["already"].append(_short(number, path))
                    continue
                parent = next((s for s in current if _is_under(path, s["path"])), None)
                if parent is not None:
                    base["rejected"].append({**_short(number, path), "reasons": [
                        f"親のディレクトリの {parent['number']} ({display_path(parent['path'])}) を選んでいる"]})
                    continue
                children = [s for s in current if _is_under(s["path"], path)]
                current = [s for s in current if not _is_under(s["path"], path)]
                base["replaced"] += [{**_short(child["number"], child["path"]), "parent": number} for child in children]
                current.append({"number": number, "path": path, "bytes": item["bytes"]})
                base["added"].append(item_view(number, item, result))
            if base["added"]:
                tx.write(_name(run, SELECTION), {"version": store.VERSION, "items": current})
        base["selection"] = _summary(current)
        return {"status": "ok", **base, "errors": []}
    except _Rejected as e:
        return {"status": "unsatisfied", **base, "added": [], "already": [], "replaced": [], "rejected": [],
                "errors": e.errors}


def select_remove(run, numbers):
    """サブコマンド select remove。番号の項目を、選んだ項目から外す。選んでいない項目は、何もせずにそのことを返す。"""
    base = {"run": run, "removed": [], "not_selected": [], "selection": None}
    try:
        _check_run(run)
        targets = _Lists(run).resolve(numbers)
        _read_selection(run)  # 壊れていれば、ロックを取る前に示す
        with store.transaction() as tx:
            current = list(_read_selection(run, tx))
            removed = False
            for number, item in targets:
                path = item["path"]
                match = next((s for s in current if s["path"] == path), None)
                if match is None:
                    parent = next((s for s in current if _is_under(path, s["path"])), None)
                    reason = (f"選んでいない (親のディレクトリの {parent['number']} ({display_path(parent['path'])}) を選んでいる)"
                              if parent is not None else "選んでいない")
                    if not any(entry["number"] == number for entry in base["not_selected"]):
                        base["not_selected"].append({**_short(number, path), "reason": reason})
                    continue
                current = [s for s in current if s is not match]
                base["removed"].append({**_short(match["number"], path), "size": format_size(match["bytes"])})
                removed = True
            if removed:
                tx.write(_name(run, SELECTION), {"version": store.VERSION, "items": current})
        base["selection"] = _summary(current)
        return {"status": "ok", **base, "errors": []}
    except _Rejected as e:
        return {"status": "unsatisfied", **base, "removed": [], "not_selected": [], "errors": e.errors}


def select_show(run):
    """サブコマンド select show。選んだ項目を、その時の判定と一緒に示す。"""
    base = {"run": run, "items": [], "table": None, "selection": None}
    try:
        _check_run(run)
        ctx = _context()
        selected = _read_selection(run)
        views = []
        lines = ["| 番号 | パス | 使用量 | 判定 |", "| --- | --- | --- | --- |"]
        for entry in selected:
            result = ctx.judge(entry["path"])
            views.append(item_view(entry["number"], {**entry, "unreadable": []}, result))
            lines.append(f"| {entry['number']} | {_cell(_code(display_path(entry['path'])))} | {format_size(entry['bytes'])} | "
                         f"{_cell(judgment_label(result))} |")
        for view in views:
            view.pop("unreadable_count")
        return {"status": "ok", **base, "items": views, "table": "\n".join(lines) if selected else None,
                "selection": _summary(selected), "errors": []}
    except _Rejected as e:
        return {"status": "unsatisfied", **base, "errors": e.errors}


# --- 判定の記録 -----------------------------------------------------------------------------------------------------

def _same_directory(left, right):
    if left == right:
        return True
    try:
        a, b = os.stat(left), os.stat(right)
    except OSError:
        return False
    return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)


def _judge_set_error(number, path, result):
    """judge set を受け付けない理由。受け付けるなら None (R20)。判定の無い項目と、項目そのものの Claude の記録で判定が
    決まった項目 (調べ直し) だけを受け付ける。"""
    if result["judgment"] is None:
        return None
    source, record = result["source"], result["record"]
    if source == "record" and record["decided_by"] == "claude" and _same_directory(record["path"], os.path.realpath(path)):
        return None
    where = f"{number} ({display_path(path)}) の判定は"
    if source == "protected":
        why = "保護の一覧で決まっている"
    elif source == "table":
        why = f"判定表の行 ({result['pattern']}) で決まっている"
    elif source == "usage":
        why = "使われているかどうかで決まっている"
    elif record["decided_by"] == "user" and _same_directory(record["path"], os.path.realpath(path)):
        why = f"利用者の記録 ({record['decided_on']}) で決まっている (調べ直すときは、利用者が先に記録を消す)"
    else:
        why = f"親のディレクトリ {display_path(record['path'])} の記録で決まっている"
    return f"{where}{why}ので、Claude の判定を記録しない"


def judge_set(run, number, input_file, *, today=None):
    """サブコマンド judge set。番号の項目に、入力のファイルの Claude の判定を記録する (R20)。一覧のファイルは変えない (KTD17)。"""
    base = {"run": run, "item": None, "record": None, "previous": None}
    try:
        _check_run(run)
        ctx = _context()
        [(text, item)] = _Lists(run).resolve([number])
        result = ctx.judge(item["path"])
        error = _judge_set_error(text, item["path"], result)
        if error:
            raise _Rejected([error])
        data, errors = records.read_input(input_file)
        if errors:
            raise _Rejected(errors)
        recorded = records.add_claude(item["path"], data, env=ctx.env, today=today)
        if recorded["status"] != "ok":
            raise _Rejected(recorded["errors"])
        after = _context()
        return {"status": "ok", **base, "item": item_view(text, item, after.judge(item["path"])),
                "record": recorded["record"], "previous": recorded["previous"], "errors": []}
    except _Rejected as e:
        return {"status": "unsatisfied", **base, "errors": e.errors}


def add_keep(run, number, input_file):
    """サブコマンド records add に引数 --run と --item を付けたとき。番号の項目を、利用者の「残す」として記録する (KTD3)。"""
    try:
        _check_run(run)
        [(_, item)] = _Lists(run).resolve([number])
    except _Rejected as e:
        return {"status": "unsatisfied", "record": None, "previous": None, "path": records.path(), "errors": e.errors,
                "display": None}
    return records.add_from_file(input_file, item_path=item["path"])
