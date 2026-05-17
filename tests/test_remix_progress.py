import unittest

from src.app.remix_progress import (
    build_progress_token,
    compute_remix_percent,
    format_progress_text,
    parse_progress_token,
)


class RemixProgressTests(unittest.TestCase):
    def test_parse_and_format_extract_progress(self):
        token = build_progress_token(
            stage="extract",
            video_name="mix.mp4",
            done=48,
            total=200,
        )
        payload = parse_progress_token(token)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["stage"], "extract")
        self.assertEqual(payload["done"], 48)
        self.assertEqual(payload["total"], 200)

        texts = {
            "remix_progress_extract": "{name}: extracting {count}",
        }
        formatted = format_progress_text(token, texts)
        self.assertIn("mix.mp4", formatted)
        self.assertIn("48/200", formatted)

    def test_legacy_frame_token(self):
        texts = {
            "remix_progress_embed_open": "{name}: embedded {count} frames",
            "remix_progress_unknown_video": "mix",
        }
        formatted = format_progress_text("remix_progress_frames:120", texts)
        self.assertIn("120", formatted)

    def test_compute_percent_within_extract_band(self):
        low = compute_remix_percent("extract", 0, 200)
        mid = compute_remix_percent("extract", 100, 200)
        self.assertLess(low, mid)
        self.assertLess(mid, compute_remix_percent("search", 0, 0))


if __name__ == "__main__":
    unittest.main()
