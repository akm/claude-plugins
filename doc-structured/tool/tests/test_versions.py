"""プラグインのバージョンとツールのバージョンが同じことのテスト。

公開のタグ doc-structured--v<バージョン> は plugin.json の version から作り、ツールは __version__ を表示する。
2 つが違うと、設定の version で取得したツールが別のバージョンを名乗る。
"""

import json
import re
import unittest

from tooltest import PLUGIN_DIR, TOOL_DIR


class VersionsTest(unittest.TestCase):
    def test_plugin_json_and_package_version_are_same(self):
        plugin = json.loads((PLUGIN_DIR / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        init = (TOOL_DIR / "src" / "doc_structured" / "__init__.py").read_text(encoding="utf-8")
        match = re.search(r'^__version__ = "(\d+\.\d+\.\d+)"$', init, re.MULTILINE)
        self.assertIsNotNone(match, "__init__.py に __version__ = \"X.Y.Z\" の行が要る")
        self.assertEqual(plugin["version"], match.group(1), "plugin.json の version と __version__ が違う")
        self.assertRegex(plugin["version"], r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
