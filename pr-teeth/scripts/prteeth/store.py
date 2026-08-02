"""設定・状態・用語集の読み書き（pr-teeth プラグイン）。

CONCEPTS.md 第5.1節・第11節の実装。

方針:
  - 読み込みは fail-soft。ファイルが無い・壊れている場合も例外を投げず既定値を返す。
    設定作業で初回実行をブロックしないため（第5.1節）。ただし壊れている場合は
    黙って握りつぶさず、呼び出し側が利用者に伝えられるよう warnings に理由を積む。
  - 書き込みは同一ディレクトリへの一時ファイル + os.replace による原子的置換。
    用語集は実行のたびに更新されるため、途中で中断されても壊れないことを優先する。
  - 蓄積データの read-modify-write は locked() で囲む。個々の書き込みが原子的でも、
    読んでから保存するまでの間は保護されず、同時実行で片方の記録が失われる。

設定形式に TOML を使う理由:
  ユーザーが手で書く設定なので構造化テキストが要るが、YAML は標準ライブラリに無い。
  以前は PyYAML があればそれを使い、無ければ同梱の簡易パーサに落ちる二重実装だったが、
  両者を永続的に一致させ続けるのは現実的でなく、実際に食い違った
  （リスト項目を親キーと同じインデントに置く正当な YAML を簡易パーサが拒否し、
  レビュー範囲設定が丸ごと無効化された）。しかも PyYAML の有無で挙動が変わるため、
  利用者のマシン構成によって発現する不具合になっていた。
  tomllib は Python 3.11 以降の標準ライブラリなので、依存ゼロのまま実装は1つで済む。
"""

import contextlib
import errno
import json
import os
import tempfile
import time

try:  # pragma: no cover - 環境依存
    import tomllib
except ImportError:  # pragma: no cover - Python 3.10 以下
    tomllib = None

try:  # pragma: no cover - 環境依存
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

# ロック取得を諦めるまでの秒数。用語集の更新は数十ミリ秒で終わるので、これだけ
# 待って取れないのは異常（別プロセスの停止など）と見なしてよい。
LOCK_TIMEOUT = 10.0

# 待ち時間の刻み。取得できるまでこの間隔で再試行する。
_LOCK_POLL = 0.05


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


class Busy(Exception):
    """他のプロセスが同じ蓄積データを更新中で、ロックを取れない。

    Corrupt と同じく「保存に進まない」ための型。待っても取れない場合に投げる。
    """

    def __init__(self, path, seconds):
        self.path = path
        self.seconds = seconds
        super().__init__(
            path + " を " + str(seconds) + " 秒待っても取得できませんでした"
            "（他の pr-teeth が更新中の可能性があります）"
        )


@contextlib.contextmanager
def locked(path, timeout=LOCK_TIMEOUT):
    """蓄積データの read-modify-write を直列化する。

    save_json は個々の書き込みを原子的にするが、**読んでから保存するまでの間は
    保護されない。** 2つの実行が重なると後から保存したほうが勝ち、片方の記録が
    丸ごと失われる（対話実行と定期実行の併走で現実に起こりうる。第14節）。

    `<path>.lock` を対象に flock を取る。データファイル自体をロック対象にしないのは、
    save_json が os.replace で inode を差し替えるため。置換前の inode を掴んだままの
    ロックは、置換後のファイルに対して何も保証しない。

    ロックファイルは残しても害が無いので消さない。削除と取得の間で競合が起き、
    別々の inode を掴んだ2つのプロセスが同時に「取得できた」状態になりうるため。

    flock が無い環境（Windows）ではロックせず素通しする。POSIX では守られ、
    それ以外では従来どおり（悪化はしない）という段階的な守り方にする。
    """
    if fcntl is None:  # pragma: no cover - Windows
        yield
        return

    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    lock_path = path + ".lock"
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as e:
                if e.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                if time.monotonic() >= deadline:
                    raise Busy(path, timeout)
                time.sleep(_LOCK_POLL)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


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
