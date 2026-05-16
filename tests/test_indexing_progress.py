import unittest

from src.app.indexing_progress import (
    build_progress_token,
    compute_overall_percent,
    format_progress_text,
    parse_progress_token,
)


class IndexingProgressTests(unittest.TestCase):
    def test_parse_and_format_decode_progress(self):
        token = build_progress_token(
            stage="decode",
            video_name="movie.mp4",
            file_index=2,
            file_total=5,
            done=120,
            total=3600,
        )
        payload = parse_progress_token(token)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["stage"], "decode")
        self.assertEqual(payload["done"], 120)
        self.assertEqual(payload["total"], 3600)

        texts = {
            "index_progress_decode": "{name}: frames {count}",
        }
        formatted = format_progress_text(token, texts)
        self.assertIn("movie.mp4", formatted)
        self.assertIn("120/3600", formatted)

    def test_compute_overall_percent_scales_within_file(self):
        percent = compute_overall_percent(2, 10, 1800, 3600, cap=90)
        self.assertGreater(percent, 9)
        self.assertLess(percent, 27)

    def test_format_passthrough_for_legacy_text(self):
        message = "Cleaning stale index source"
        self.assertEqual(format_progress_text(message, {}), message)


if __name__ == "__main__":
    unittest.main()
