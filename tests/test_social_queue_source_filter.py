from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils import social_queue


class GetPendingSourceFilterTests(unittest.TestCase):
    def _seed(self, queue_path, items):
        for item in items:
            with patch.object(social_queue, "QUEUE_PATH", str(queue_path)):
                social_queue.enqueue(item, platform="instagram")

    def test_source_prefix_returns_only_matching_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = Path(tmp) / "social.json"
            self._seed(
                queue,
                [
                    {"dedup_key": "link:a", "titulo": "A", "source": "nuevarioja_politica"},
                    {"dedup_key": "link:b", "titulo": "B", "source": "paparazzi"},
                    {"dedup_key": "link:c", "titulo": "C", "source": "tiempopopular_locales"},
                ],
            )
            with patch.object(social_queue, "QUEUE_PATH", str(queue)):
                only_paparazzi = social_queue.get_pending("instagram", source_prefix="paparazzi")
                without_paparazzi = social_queue.get_pending(
                    "instagram", exclude_source_prefix="paparazzi"
                )

        self.assertEqual(["link:b"], [i["dedup_key"] for i in only_paparazzi])
        self.assertEqual(
            {"link:a", "link:c"}, {i["dedup_key"] for i in without_paparazzi}
        )

    def test_source_prefix_respects_max_items_independently(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue = Path(tmp) / "social.json"
            self._seed(
                queue,
                [
                    {"dedup_key": f"link:p{i}", "titulo": f"P{i}", "source": "paparazzi"}
                    for i in range(3)
                ]
                + [
                    {"dedup_key": f"link:g{i}", "titulo": f"G{i}", "source": "nuevarioja_politica"}
                    for i in range(9)
                ],
            )
            with patch.object(social_queue, "QUEUE_PATH", str(queue)):
                general = social_queue.get_pending(
                    "instagram", max_items=8, exclude_source_prefix="paparazzi"
                )
                paparazzi = social_queue.get_pending(
                    "instagram", max_items=2, source_prefix="paparazzi"
                )

        self.assertEqual(8, len(general))
        self.assertTrue(all(i["source"] != "paparazzi" for i in general))
        self.assertEqual(2, len(paparazzi))
        self.assertTrue(all(i["source"] == "paparazzi" for i in paparazzi))


if __name__ == "__main__":
    unittest.main()
