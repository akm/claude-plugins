"""設定・状態・用語集の読み書き（pr-teeth プラグイン）。

CONCEPTS.md 第5.1節・第11節の実装。

方針:
  - 読み込みは fail-soft。ファイルが無い・壊れている場合も例外を投げず既定値を返す。
    設定作業で初回実行をブロックしないため（第5.1節）。ただし壊れている場合は
    黙って握りつぶさず、呼び出し側が利用者に伝えられるよう warnings に理由を積む。
  - 書き込みは同一ディレクトリへの一時ファイル + os.replace による原子的置換。
    用語集は実行のたびに更新されるため、途中で中断されても壊れないことを優先する。

設定形式に TOML を使う理由:
  ユーザーが手で書く設定なので構造化テキストが要るが、YAML は標準ライブラリに無い。
  以前は PyYAML があればそれを使い、無ければ同梱の簡易パーサに落ちる二重実装だったが、
  両者を永続的に一致させ続けるのは現実的でなく、実際に食い違った
  （リスト項目を親キーと同じインデントに置く正当な YAML を簡易パーサが拒否し、
  レビュー範囲設定が丸ごと無効化された）。しかも PyYAML の有無で挙動が変わるため、
  利用者のマシン構成によって発現する不具合になっていた。
  tomllib は Python 3.11 以降の標準ライブラリなので、依存ゼロのまま実装は1つで済む。
"""

import json
import os
import tempfile

try:  # pragma: no cover - 環境依存
    import tomllib
except ImportError:  # pragma: no cover - Python 3.10 以下
    tomllib = None


def _read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None
    except OSError:
        return None


class Corrupt(Exception):
    """蓄積データが壊れていて読めない。

    「ファイルが無い」（正常な初回実行）と区別するための型。呼び出し側は
    これを捕まえて保存を中止する。詳細は docs/design/data-integrity.md。
    """

    def __init__(self, path, reason):
        self.path = path
        self.reason = reason
        super().__init__(path + " を読めません（" + reason + "）")


def load_json(path, default, warnings=None):
    """JSON を読む。無ければ default、壊れていれば default + warnings に理由。

    **設定・一時データ向け。** 蓄積データ（用語集・状態）には load_precious を使う。
    こちらは壊れていても既定値を返すため、そのまま保存すると元データを上書きする。
    """
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


def load_precious(path, default):
    """蓄積データ（用語集・状態）を読む。壊れていれば Corrupt を投げる。

    無い場合は default を返す（正常な初回実行）。壊れている場合に既定値を返すと、
    呼び出し側がそれを保存して**元データを失わせる**ため、ここで止める。
    docs/design/data-integrity.md「蓄積データ — 壊れているなら触らない」。
    """
    text = _read_text(path)
    if text is None:
        return default
    if not text.strip():
        return default
    try:
        data = json.loads(text)
    except ValueError as e:
        raise Corrupt(path, "JSON として不正: " + str(e))
    if not isinstance(data, dict):
        raise Corrupt(path, "最上位がオブジェクトではありません")
    return data


def load_toml(path, default, warnings=None):
    """TOML を読む。無ければ default、壊れていれば default + warnings に理由。"""
    if tomllib is None:  # pragma: no cover - Python 3.10 以下
        if warnings is not None:
            warnings.append(
                "Python 3.11 以降が必要です（設定の読み込みに標準ライブラリの tomllib を使います）。"
                "既定値で続行します。"
            )
        return default

    text = _read_text(path)
    if text is None:
        return default
    if not text.strip():
        return default
    try:
        data = tomllib.loads(text)
    except Exception as e:
        if warnings is not None:
            warnings.append(path + " を読めませんでした（TOML として不正: " + str(e) + "）。既定値で続行します。")
        return default
    if not isinstance(data, dict):
        if warnings is not None:
            warnings.append(path + " の最上位がテーブルではありません。既定値で続行します。")
        return default
    return data


def save_json(path, data):
    """JSON を原子的に書く。途中で中断されても既存ファイルを壊さない。"""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory or ".", prefix=".tmp-", suffix=".json")
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
