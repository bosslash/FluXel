from __future__ import annotations

import unittest

from fluxel.ui.tag_manager import split_tags


class TagManagerTest(unittest.TestCase):
    def test_split_tags_supports_japanese_and_deduplicates(self) -> None:
        self.assertEqual(
            ["開発", "経理", "定例"],
            split_tags("開発、 経理, 開発\n定例"),
        )


if __name__ == "__main__":
    unittest.main()
