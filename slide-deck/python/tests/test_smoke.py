"""uv が用意した環境で Pillow を使えることを確認する、最初のテスト。"""

import unittest

from PIL import Image


class SmokeTest(unittest.TestCase):
    def test_pillow_creates_image(self) -> None:
        image = Image.new("RGB", (2, 3), "white")
        self.assertEqual(image.size, (2, 3))


if __name__ == "__main__":
    unittest.main()
