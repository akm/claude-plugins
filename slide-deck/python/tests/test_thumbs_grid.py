"""画像をまとめるツール (ファイル slide-deck/python/slide_deck_tools/thumbs_grid.py) のテスト。

入口としての振る舞い (終了コード・標準エラー出力・書いた画像) を確認するため、ツールをスクリプトとして子プロセスで実行する。
URL には、テストで作った画像のファイルの URL (file://) を渡す。
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

SCRIPT = Path(__file__).resolve().parents[1] / "slide_deck_tools" / "thumbs_grid.py"

RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
WHITE = (255, 255, 255)


def run_tool(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


class ThumbsGridTest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)

    def write_image(self, name: str, size: tuple[int, int], color: tuple[int, int, int]) -> str:
        """1 色で塗った画像を PNG で書き、そのファイルの URL を返す。"""
        path = self.dir / name
        Image.new("RGB", size, color).save(path)
        return path.as_uri()

    def read_pixels(self, path: Path, points: list[tuple[int, int]]) -> list[tuple[int, ...] | float | None]:
        with Image.open(path) as image:
            rgb = image.convert("RGB")
            return [rgb.getpixel(point) for point in points]

    def read_size(self, path: Path) -> tuple[int, int]:
        with Image.open(path) as image:
            return image.size

    def test_three_images_make_two_rows_with_bottom_right_empty(self) -> None:
        w, h = 40, 30
        urls = [
            self.write_image("1.png", (w, h), RED),
            self.write_image("2.png", (w, h), GREEN),
            self.write_image("3.png", (w, h), BLUE),
        ]
        out = self.dir / "grid.png"

        result = run_tool(str(out), *urls)

        self.assertEqual(result.returncode, 0, result.stderr)
        width, height = self.read_size(out)
        # 画像の間の幅は、出力の幅から 2 列分の幅を引いて求める (値はツールが決める)
        gap = width - 2 * w
        self.assertGreater(gap, 0, "左右の 2 列の間に隙間が無い")
        self.assertEqual(height, 2 * h + gap, "2 行の高さになっていない")
        left, right = w // 2, w + gap + w // 2
        top, bottom = h // 2, h + gap + h // 2
        background, upper_left, upper_right, lower_left, lower_right = self.read_pixels(
            out, [(w, 0), (left, top), (right, top), (left, bottom), (right, bottom)]
        )
        self.assertEqual(upper_left, RED, "1 枚目が左上に無い")
        self.assertEqual(upper_right, GREEN, "2 枚目が右上に無い")
        self.assertEqual(lower_left, BLUE, "3 枚目が左下に無い")
        self.assertEqual(lower_right, background, "右下が空いていない (隙間と同じ色ではない)")
        self.assertNotIn(background, (RED, GREEN, BLUE), "隙間の色が画像の色と区別できない")

    def test_images_of_other_sizes_are_resized_to_the_first(self) -> None:
        w, h = 40, 30
        urls = [
            self.write_image("1.png", (w, h), RED),
            self.write_image("2.png", (w * 2, h * 2), GREEN),
            self.write_image("3.png", (w // 2, h // 2), BLUE),
        ]
        out = self.dir / "grid.png"

        result = run_tool(str(out), *urls)

        self.assertEqual(result.returncode, 0, result.stderr)
        width, height = self.read_size(out)
        gap = width - 2 * w
        self.assertGreater(gap, 0, "左右の 2 列の間に隙間が無い")
        self.assertEqual(height, 2 * h + gap, "最初の画像の高さでそろっていない")
        # 大きい画像と小さい画像のそれぞれが、最初の画像と同じ範囲を隅まで埋めていることを、範囲の四隅で確認する
        x2, y3 = w + gap, h + gap
        corners2 = [(x2, 0), (x2 + w - 1, 0), (x2, h - 1), (x2 + w - 1, h - 1)]
        corners3 = [(0, y3), (w - 1, y3), (0, y3 + h - 1), (w - 1, y3 + h - 1)]
        for point, pixel in zip(corners2, self.read_pixels(out, corners2)):
            self.assertEqual(pixel, GREEN, f"2 枚目 (大きい画像) が最初の画像の大きさにそろっていない: {point}")
        for point, pixel in zip(corners3, self.read_pixels(out, corners3)):
            self.assertEqual(pixel, BLUE, f"3 枚目 (小さい画像) が最初の画像の大きさにそろっていない: {point}")

    def test_unreachable_url_fails_with_the_url_and_writes_nothing(self) -> None:
        missing = (self.dir / "missing.png").as_uri()
        urls = [
            self.write_image("1.png", (40, 30), RED),
            missing,
            self.write_image("3.png", (40, 30), BLUE),
        ]
        out = self.dir / "grid.png"

        result = run_tool(str(out), *urls)

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(missing, result.stderr, "取得できなかった URL を示していない")
        self.assertFalse(out.exists(), "取得に失敗したのに画像を書いた")

    def test_url_of_data_that_is_not_an_image_fails_with_the_url(self) -> None:
        text = self.dir / "not-image.png"
        text.write_text("画像ではない", encoding="utf-8")
        urls = [self.write_image("1.png", (40, 30), RED), text.as_uri()]
        out = self.dir / "grid.png"

        result = run_tool(str(out), *urls)

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(text.as_uri(), result.stderr, "画像として読めなかった URL を示していない")
        self.assertFalse(out.exists(), "画像として読めなかったのに画像を書いた")

    def test_transparent_pixels_are_composited_on_the_background(self) -> None:
        path = self.dir / "transparent.png"
        Image.new("RGBA", (40, 30), (0, 0, 0, 0)).save(path)
        out = self.dir / "grid.png"

        result = run_tool(str(out), path.as_uri())

        self.assertEqual(result.returncode, 0, result.stderr)
        (pixel,) = self.read_pixels(out, [(20, 15)])
        self.assertEqual(pixel, WHITE, "透明な画素が背景の色で描かれていない")

    def test_help_shows_arguments_output_and_exit_codes(self) -> None:
        result = run_tool("--help")

        self.assertEqual(result.returncode, 0, result.stderr)
        for word in ("OUTPUT", "URL", "出力", "終了コード"):
            self.assertIn(word, result.stdout, f"--help に {word} が無い")
        for code in ("0", "2"):
            self.assertRegex(result.stdout, rf"(?m)^\s+{code}\b", f"--help に終了コード {code} の行が無い")


if __name__ == "__main__":
    unittest.main()
