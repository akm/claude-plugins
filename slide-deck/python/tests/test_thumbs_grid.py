"""画像をまとめるツール (ファイル slide-deck/python/slide_deck_tools/thumbs_grid.py) のテスト。

入口としての振る舞い (終了コード・標準エラー出力・書いた画像) を確認するため、ツールをスクリプトとして子プロセスで実行する。
URL には、テストで作った画像のファイルの URL (file://) を渡す。
"""

import os
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
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

    def test_url_with_a_port_that_is_not_a_number_fails_with_the_url(self) -> None:
        # ポートが数字でない URL は、接続する前に http.client.InvalidURL で失敗するので、ネットワークを使わない
        bad = "http://example.com:abc/x.png"
        urls = [self.write_image("1.png", (40, 30), RED), bad]
        out = self.dir / "grid.png"

        result = run_tool(str(out), *urls)

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(bad, result.stderr, "取得できなかった URL を示していない")
        self.assertFalse(out.exists(), "取得に失敗したのに画像を書いた")

    def test_image_with_too_many_pixels_fails_with_the_url(self) -> None:
        # 1x1 の PNG の IHDR の幅と高さだけを 20000 に書き換える。Pillow は開いた時点で画素数を上限と比べるので、
        # 画素のデータを展開せずに DecompressionBombError になる
        small = self.dir / "small.png"
        Image.new("RGB", (1, 1), RED).save(small)
        data = bytearray(small.read_bytes())
        ihdr = struct.pack(">II", 20000, 20000) + bytes(data[24:29])
        data[16:29] = ihdr
        data[29:33] = struct.pack(">I", zlib.crc32(b"IHDR" + ihdr))
        huge = self.dir / "huge.png"
        huge.write_bytes(bytes(data))
        urls = [self.write_image("1.png", (40, 30), RED), huge.as_uri()]
        out = self.dir / "grid.png"

        result = run_tool(str(out), *urls)

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(huge.as_uri(), result.stderr, "画像として読めなかった URL を示していない")
        self.assertFalse(out.exists(), "画像として読めなかったのに画像を書いた")

    def test_transparent_pixels_are_composited_on_the_background(self) -> None:
        path = self.dir / "transparent.png"
        Image.new("RGBA", (40, 30), (0, 0, 0, 0)).save(path)
        out = self.dir / "grid.png"

        result = run_tool(str(out), path.as_uri())

        self.assertEqual(result.returncode, 0, result.stderr)
        (pixel,) = self.read_pixels(out, [(20, 15)])
        self.assertEqual(pixel, WHITE, "透明な画素が背景の色で描かれていない")

    def test_url_without_a_scheme_fails_with_the_url(self) -> None:
        # スキームの無い URL では、urlopen が ValueError を送出する
        bad = "not-a-url"
        urls = [self.write_image("1.png", (40, 30), RED), bad]
        out = self.dir / "grid.png"

        result = run_tool(str(out), *urls)

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(bad, result.stderr, "取得できなかった URL を示していない")
        self.assertFalse(out.exists(), "取得に失敗したのに画像を書いた")

    def test_output_with_an_unknown_extension_fails_with_the_path(self) -> None:
        # 拡張子から画像の形式を決められないと、write_image が Image.save を呼び出す前に誤りにする
        out = self.dir / "grid.unknown"
        urls = [self.write_image("1.png", (40, 30), RED)]

        result = run_tool(str(out), *urls)

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(str(out), result.stderr, "書けなかった OUTPUT を示していない")
        names: list[str] = sorted(path.name for path in self.dir.iterdir())
        expected: list[str] = ["1.png"]
        self.assertEqual(names, expected, "書けなかったのに OUTPUT が残った")

    def test_output_with_a_format_that_cannot_be_written_fails_with_the_path(self) -> None:
        # 形式 PSD は、Pillow が読めるが書き出せない
        out = self.dir / "grid.psd"
        urls = [self.write_image("1.png", (40, 30), RED)]

        result = run_tool(str(out), *urls)

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(str(out), result.stderr, "書けなかった OUTPUT を示していない")
        self.assertFalse(out.exists(), "書けなかったのに OUTPUT を書いた")

    def test_failed_write_keeps_the_existing_output(self) -> None:
        # 形式 XBM は RGB の画像を書けないので、Image.save が書き込みの途中で失敗する
        out = self.dir / "grid.xbm"
        out.write_bytes(b"previous image")
        urls = [self.write_image("1.png", (40, 30), RED)]

        result = run_tool(str(out), *urls)

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(str(out), result.stderr, "書けなかった OUTPUT を示していない")
        self.assertEqual(out.read_bytes(), b"previous image", "書けなかったのに OUTPUT にあったファイルが変わった")
        names: list[str] = sorted(path.name for path in self.dir.iterdir())
        expected: list[str] = ["1.png", "grid.xbm"]
        self.assertEqual(names, expected, "OUTPUT のほかにファイルが残った")

    def test_new_output_gets_the_permissions_of_the_umask(self) -> None:
        mask = os.umask(0)
        os.umask(mask)
        out = self.dir / "grid.png"

        result = run_tool(str(out), self.write_image("1.png", (40, 30), RED))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o666 & ~mask, "新しい OUTPUT の権限が umask に従っていない")

    def test_existing_output_keeps_its_permissions(self) -> None:
        out = self.dir / "grid.png"
        out.write_bytes(b"previous image")
        out.chmod(0o640)

        result = run_tool(str(out), self.write_image("1.png", (40, 30), RED))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o640, "既にある OUTPUT の権限が変わった")

    def test_symlink_output_writes_to_the_link_target(self) -> None:
        target = self.dir / "real.png"
        target.write_bytes(b"previous image")
        out = self.dir / "grid.png"
        out.symlink_to(target)

        result = run_tool(str(out), self.write_image("1.png", (40, 30), RED))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(out.is_symlink(), "シンボリックリンクの OUTPUT が通常のファイルに置き換わった")
        with Image.open(target) as image:
            self.assertEqual(image.height, 30, "リンク先に画像を書いていない")

    def test_16_bit_grayscale_is_scaled_to_8_bits(self) -> None:
        path = self.dir / "gray16.png"
        Image.new("I;16", (40, 30), 30000).save(path)
        out = self.dir / "grid.png"

        result = run_tool(str(out), path.as_uri())

        self.assertEqual(result.returncode, 0, result.stderr)
        (pixel,) = self.read_pixels(out, [(20, 15)])
        expected = (30000 // 256,) * 3
        self.assertEqual(pixel, expected, "16 ビットの値が 8 ビットに縮められていない")

    def test_transparent_color_of_16_bit_grayscale_is_composited_on_the_background(self) -> None:
        # 左半分を透過色 (30000)、右半分を透過色でない値 (10000) にして、透過色の画素だけが白になることを確認する
        path = self.dir / "gray16-transparent.png"
        image = Image.new("I;16", (40, 30), 30000)
        image.paste(Image.new("I;16", (20, 30), 10000), (20, 0))
        image.save(path, transparency=30000)
        out = self.dir / "grid.png"

        result = run_tool(str(out), path.as_uri())

        self.assertEqual(result.returncode, 0, result.stderr)
        transparent, opaque = self.read_pixels(out, [(10, 15), (30, 15)])
        self.assertEqual(transparent, WHITE, "16 ビットの画像の透過色が白に合成されていない")
        expected = (10000 // 256,) * 3
        self.assertEqual(opaque, expected, "16 ビットの画像の透過色でない画素が、8 ビットに縮めた値で並んでいない")

    def test_help_shows_arguments_output_and_exit_codes(self) -> None:
        result = run_tool("--help")

        self.assertEqual(result.returncode, 0, result.stderr)
        for word in ("OUTPUT", "URL", "出力", "終了コード"):
            self.assertIn(word, result.stdout, f"--help に {word} が無い")
        for code in ("0", "2"):
            self.assertRegex(result.stdout, rf"(?m)^\s+{code}\b", f"--help に終了コード {code} の行が無い")


if __name__ == "__main__":
    unittest.main()
