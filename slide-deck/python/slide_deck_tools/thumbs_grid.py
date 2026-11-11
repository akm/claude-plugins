"""スライドの画像の URL を受け取り、2 列に並べた 1 枚の画像を作る。

スキル publish が、Google スライドに作った資料の見た目を確認するのに使う。
引数・出力・終了コードは、オプション --help が出す文が SSOT (single source of truth。ある事実を定めている唯一の記述)。
決めた場所は、計画 docs/plans/2026-11-09-2343-feat-slide-deck-plugin-plan.md の KTD17。
"""

import argparse
import http.client
import io
import sys
import urllib.request
from pathlib import Path
from typing import IO

from PIL import Image

# 画像の間の幅 (ピクセル) と、画像の間と空いたマスを塗る色。色は、スライドの境目が分かるように、スライドではあまり使わない色 (マゼンタ) にする
GAP = 6
BACKGROUND = (200, 0, 200)
# 透過のある画像を合成する背景の色。スライドの多くは背景が白なので、表示に近い色にする
TRANSPARENT_BACKGROUND = (255, 255, 255)
# 1 つの URL の取得で、接続と読み取りのそれぞれで応答まで待機する秒数の上限
TIMEOUT_SECONDS = 30

EXIT_OK = 0
EXIT_ERROR = 2

DESCRIPTION = "スライドの画像の URL を受け取り、2 列に並べた 1 枚の画像を作る。"
EPILOG = f"""\
出力:
  引数 OUTPUT のパスに、引数 URL の順に左から右・上から下へ並べた画像を書く。画像の形式は OUTPUT の拡張子で決まる (.png を勧める)。
  大きさの違う画像は、最初の画像の大きさにそろえる。枚数が奇数なら、最後の行の右を空ける。
  透過のある画像は、白 RGB{TRANSPARENT_BACKGROUND} の背景に合成してから並べる。
  画像の間と空いたマスは、色 RGB{BACKGROUND} で塗る。標準出力には何も書かない。
  1 つでも取得できない URL があれば、画像を書かない。画像の形式に変換できなかったときは、OUTPUT にあったファイルを変えない。

終了コード:
  {EXIT_OK}  画像を書いた
  {EXIT_ERROR}  実行の誤り。引数の誤り・取得できない URL (応答が {TIMEOUT_SECONDS} 秒以内に無いものを含む)・
     画像として読めないデータ・画像を書けない OUTPUT。誤りの内容 (URL の誤りなら、その URL) を標準エラー出力に書く
"""


class Arguments(argparse.Namespace):
    output: str
    urls: list[str]


class ToolError(Exception):
    """利用者に示して、終了コード 2 で終える誤り。"""


def parse_arguments(argv: list[str]) -> Arguments:
    parser = argparse.ArgumentParser(
        prog="thumbs_grid.py",
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("output", metavar="OUTPUT", help="書く画像のファイルのパス")
    parser.add_argument("urls", metavar="URL", nargs="+", help="並べる画像の URL (file:// も使える)")
    return parser.parse_args(argv, namespace=Arguments())


def fetch_image(url: str) -> Image.Image:
    try:
        # typeshed (Python の標準ライブラリの型を定めるファイルの集まり) は、関数 urllib.request.urlopen の戻り値の型を
        # Any にしている。mypy の設定 disallow_any_expr は、型注釈を付けた変数に代入する式を検査しないので、
        # 型 IO[bytes] の変数に代入する。戻り値は、http(s):// なら型 http.client.HTTPResponse、file:// なら
        # 型 urllib.response.addinfourl の値で、どちらも IO[bytes] として読める
        response: IO[bytes] = urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS)
        with response:
            data = response.read()
    except (OSError, ValueError, http.client.HTTPException) as e:
        # urlopen が送出する例外 URLError・HTTPError と、応答まで待機する時間の上限を超えたときの例外 TimeoutError は、
        # どれも例外 OSError の派生クラス。URL の形が誤っていると、urlopen は例外 ValueError を送出する。
        # ポートが数字でない URL (InvalidURL) と、本文が途中で切れた応答 (IncompleteRead) は、
        # 例外 http.client.HTTPException の派生クラスで、OSError でも ValueError でもない
        raise ToolError(f"URL を取得できない: {url}: {e}") from e
    try:
        with Image.open(io.BytesIO(data)) as image:
            return to_rgb(image)
    except (OSError, Image.DecompressionBombError) as e:
        # Pillow が画像の形式を判別できないときに送出する例外 UnidentifiedImageError も、OSError の派生クラス。
        # 画素数が Pillow の上限 (Image.MAX_IMAGE_PIXELS) の 2 倍を超える画像の例外 DecompressionBombError は、
        # OSError の派生クラスではない
        raise ToolError(f"URL のデータを画像として読めない: {url}: {e}") from e


def to_rgb(image: Image.Image) -> Image.Image:
    """画像を RGB にする。透過のある画像は、convert("RGB") だとアルファを捨てて透明な画素の RGB の値 (多くは黒) が残るので、背景に合成する。"""
    if not image.has_transparency_data:
        return image.convert("RGB")
    rgba = image.convert("RGBA")
    background = Image.new("RGBA", rgba.size, (*TRANSPARENT_BACKGROUND, 255))
    return Image.alpha_composite(background, rgba).convert("RGB")


def make_grid(images: list[Image.Image]) -> Image.Image:
    width, height = images[0].size
    rows = (len(images) + 1) // 2
    grid = Image.new("RGB", (width * 2 + GAP, rows * height + (rows - 1) * GAP), BACKGROUND)
    for i, image in enumerate(images):
        if image.size != (width, height):
            image = image.resize((width, height), Image.Resampling.LANCZOS)
        grid.paste(image, ((i % 2) * (width + GAP), (i // 2) * (height + GAP)))
    return grid


def run(arguments: Arguments) -> None:
    # すべての URL を取得できてから書く。取得できた画像だけで書くと、確認の対象から外れたスライドがあることに気づけないため
    images = [fetch_image(url) for url in arguments.urls]
    grid = make_grid(images)
    write_image(grid, Path(arguments.output))


def write_image(grid: Image.Image, output: Path) -> None:
    """画像をメモリに書いてから、OUTPUT に書く。

    メソッド Image.save に OUTPUT のパスを渡すと、既にあるファイルを切り詰めてから書き、
    画像の形式に変換する途中で失敗しても元に戻さないので、前の実行の画像が壊れたまま残る。
    一時ファイルに書いて置き換える方法は、OUTPUT のパスに付いた権限・所有者・シンボリックリンクを失う。
    メモリに書いてから OUTPUT に書けば、変換の失敗では OUTPUT を変えず、パスの属性も保つ。
    OUTPUT への書き込みそのものが途中で失敗したとき (ディスクの空きが無い、など) は、書きかけの内容が残る。
    """
    # メモリに書くときは Image.save が拡張子を見ないので、拡張子から形式を求めて渡す
    image_format = Image.registered_extensions().get(output.suffix.lower())
    if image_format is None:
        raise ToolError(f"画像を書けない: {output}: 拡張子 {output.suffix!r} から画像の形式を決められない")
    # registered_extensions は読めるだけの形式 (PSD など) の拡張子も含む。書き出せない形式を Image.save に渡すと、
    # OSError でも ValueError でもない例外 KeyError を送出するので、呼び出す前に確認する
    if image_format not in Image.SAVE:
        raise ToolError(f"画像を書けない: {output}: 画像の形式 {image_format} は書き出せない")
    buffer = io.BytesIO()
    try:
        grid.save(buffer, format=image_format)
        output.write_bytes(buffer.getvalue())
    except (OSError, ValueError) as e:
        raise ToolError(f"画像を書けない: {output}: {e}") from e


def main(argv: list[str]) -> int:
    arguments = parse_arguments(argv)
    try:
        run(arguments)
    except ToolError as e:
        print(f"thumbs_grid.py: {e}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
