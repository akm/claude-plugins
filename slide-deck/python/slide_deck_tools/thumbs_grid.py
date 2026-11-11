"""スライドの画像の URL を受け取り、2 列に並べた 1 枚の画像を作る。

スキル publish が、Google スライドに作った資料の見た目を確認するのに使う。
引数・出力・終了コードは、オプション --help が出す文が SSOT (single source of truth。ある事実を定めている唯一の記述)。
決めた場所は、計画 docs/plans/2026-11-09-2343-feat-slide-deck-plugin-plan.md の KTD17。
"""

import argparse
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
  1 つでも取得できない URL があれば、画像を書かない。

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
    except (OSError, ValueError) as e:
        # urlopen が送出する例外 URLError・HTTPError と、応答まで待機する時間の上限を超えたときの例外 TimeoutError は、
        # どれも例外 OSError の派生クラス。URL の形が誤っていると、urlopen は例外 ValueError を送出する
        raise ToolError(f"URL を取得できない: {url}: {e}") from e
    try:
        with Image.open(io.BytesIO(data)) as image:
            return to_rgb(image)
    except OSError as e:
        # Pillow が画像の形式を判別できないときに送出する例外 UnidentifiedImageError も、OSError の派生クラス
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
    try:
        grid.save(Path(arguments.output))
    except (OSError, ValueError) as e:
        # 引数 OUTPUT の拡張子から画像の形式を決められないと、メソッド Image.save は例外 ValueError を送出する
        raise ToolError(f"画像を書けない: {arguments.output}: {e}") from e


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
