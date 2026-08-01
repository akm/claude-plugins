"""設定・状態・用語集の読み書き（pr-teeth プラグイン）。

CONCEPTS.md 第5.1節・第11節の実装。

方針:
  - 読み込みは fail-soft。ファイルが無い・壊れている場合も例外を投げず既定値を返す。
    設定作業で初回実行をブロックしないため（第5.1節）。ただし壊れている場合は
    黙って握りつぶさず、呼び出し側が利用者に伝えられるよう warnings に理由を積む。
  - 書き込みは同一ディレクトリへの一時ファイル + os.replace による原子的置換。
    用語集は実行のたびに更新されるため、途中で中断されても壊れないことを優先する。

YAML について:
  repos.yml はユーザーが手で書く設定なので YAML を使うが、PyYAML は標準ライブラリでは
  なく利用者の環境にあるとは限らない。あればそれを使い、無ければ本ファイルの簡易パーサに
  フォールバックする。簡易パーサは repos.yml が実際に使う部分集合（入れ子のマッピングと
  文字列リスト）だけを解釈する。
"""

import json
import os
import tempfile

try:  # pragma: no cover - 環境依存
    import yaml  # type: ignore

    _HAS_YAML = True
except ImportError:  # pragma: no cover - 環境依存
    yaml = None
    _HAS_YAML = False


def _read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None
    except OSError:
        return None


def load_json(path, default, warnings=None):
    """JSON を読む。無ければ default、壊れていれば default + warnings に理由。"""
    text = _read_text(path)
    if text is None:
        return default
    if not text.strip():
        return default
    try:
        return json.loads(text)
    except ValueError as e:
        if warnings is not None:
            warnings.append(path + " を読めませんでした（JSON として不正: " + str(e) + "）。既定値で続行します。")
        return default


def _normalize(data):
    """値なしキー (`o/r:`) を PyYAML の None ではなく空マッピングに揃える。

    PyYAML の有無で結果が変わると、利用者の環境によって挙動が変わってしまう。
    呼び出し側は範囲設定に対して .get() するため、空マッピングの方が安全。
    """
    if data is None:
        return {}
    if isinstance(data, dict):
        return {k: _normalize(v) for k, v in data.items()}
    return data


def load_yaml(path, default, warnings=None):
    """YAML を読む。無ければ default、壊れていれば default + warnings に理由。"""
    text = _read_text(path)
    if text is None:
        return default
    if not text.strip():
        return default
    try:
        if _HAS_YAML:
            data = _normalize(yaml.safe_load(text))
        else:
            data = parse_simple_yaml(text)
    except Exception as e:
        if warnings is not None:
            warnings.append(path + " を読めませんでした（YAML として不正: " + str(e) + "）。既定値で続行します。")
        return default
    if data is None:
        return default
    if not isinstance(data, dict):
        if warnings is not None:
            warnings.append(path + " の最上位がマッピングではありません。既定値で続行します。")
        return default
    return data


def save_json(path, data):
    """JSON を原子的に書く。途中で中断されても既存ファイルを壊さない。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _strip_comment(line):
    """行末コメントを除去する。引用符の中の # は残す。"""
    out = []
    quote = None
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            continue
        if ch == "#":
            break
        out.append(ch)
    return "".join(out).rstrip()


def _scalar(token):
    token = token.strip()
    if not token:
        return ""
    if len(token) >= 2 and token[0] == token[-1] and token[0] in ("'", '"'):
        return token[1:-1]
    return token


def parse_simple_yaml(text):
    """repos.yml / config.yaml が使う範囲だけを解釈する簡易 YAML パーサ。

    対応するのは以下だけ。これを超える記法が必要になったら PyYAML を前提にするか、
    設定形式そのものを見直す。
      - インデントによる入れ子のマッピング（`key:` の下に字下げして続ける）
      - `key: value` のスカラー
      - `- item` の文字列リスト
      - `#` 以降の行コメント、空行

    未対応の記法（アンカー、複数行文字列、フロー記法 {} []、複合キーなど）は
    値がそのまま文字列として入るため、誤って黙って壊れないよう明確に失敗させる。
    """
    root = {}
    # スタックは (そのコンテナの子が持つインデント幅, コンテナ) の列。
    # 「子のインデント」を持たせるのが要点。行のインデントと直接比較でき、
    # 同じ深さの兄弟行が来ても閉じずに済む。root の子はインデント 0。
    stack = [(0, root)]
    # 値がまだ無い `key:` を覚えておく。次の行の字下げを見て、マッピングかリストかを決める。
    pending = None  # (親マッピング, キー, その行のインデント)

    for raw in text.splitlines():
        line = _strip_comment(raw)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        if "\t" in raw[:indent]:
            raise ValueError("インデントにタブが使われています（スペースを使ってください）")
        body = line.strip()
        is_item = body.startswith("- ") or body == "-"

        # 直前の `key:` に対して字下げされた行が来たら、そこで中身の型が確定する。
        # リストは `key:` と同じインデントに項目が並ぶ書き方も許すため、>= で判定する。
        if pending is not None:
            parent, pkey, pindent = pending
            if indent > pindent or (is_item and indent >= pindent):
                child = [] if is_item else {}
                parent[pkey] = child
                stack.append((indent, child))
            pending = None

        # 現在行より深いコンテナを閉じる。閉じた結果、行のインデントに一致する
        # コンテナが先頭に来る。
        while len(stack) > 1 and indent < stack[-1][0]:
            stack.pop()

        container = stack[-1][1]

        if is_item:
            if not isinstance(container, list):
                raise ValueError("リスト項目 '" + body + "' の入れ先がリストではありません")
            container.append(_scalar(body[2:] if len(body) > 1 else ""))
            continue

        if ":" not in body:
            raise ValueError("解釈できない行です: " + body)

        key, _, rest = body.partition(":")
        key = _scalar(key)
        rest = rest.strip()

        if not isinstance(container, dict):
            raise ValueError("'" + key + "' の入れ先がマッピングではありません")

        if rest:
            if rest[0] in ("{", "["):
                raise ValueError("フロー記法 (" + rest[0] + ") には未対応です")
            container[key] = _scalar(rest)
        else:
            # 値が無い。子が来るまで型は決めない。来なければ空マッピングのまま。
            container[key] = {}
            pending = (container, key, indent)

    return root
