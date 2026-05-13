import unittest

from src.services.remix_match_aggregate import aggregate_match_points_to_segments, normalize_match_path


class TestRemixMatchAggregate(unittest.TestCase):
    def test_remix_gap_splits_two_shots(self):
        """Large hole on remix timeline (ref) splits; default remix gap ~2.5s at 1fps."""
        p = r"D:\media\a.mp4"
        pts = [
            (p, 10.0, 0.9, 0.0),
            (p, 11.0, 0.85, 1.0),
            (p, 20.0, 0.88, 4.0),
            (p, 21.0, 0.87, 5.0),
        ]
        hits = aggregate_match_points_to_segments(
            pts,
            merge_gap_sec=30.0,
            min_segment_sec=0.5,
            min_points=2,
            sample_fps=1.0,
            random_seed=0,
        )
        self.assertEqual(len(hits), 2)
        self.assertEqual(hits[0].video_path, p)
        self.assertEqual(hits[1].video_path, p)
        self.assertAlmostEqual(hits[0].remix_start_sec, 0.0)
        self.assertAlmostEqual(hits[0].remix_end_sec, 1.0)
        self.assertAlmostEqual(hits[1].remix_start_sec, 4.0)
        self.assertAlmostEqual(hits[1].remix_end_sec, 5.0)

    def test_missing_ref_frame_same_cluster(self):
        """~1s missing ref at 1fps stays one cluster; source times stay close."""
        p = r"D:\media\a.mp4"
        pts = [
            (p, 10.0, 0.9, 0.0),
            (p, 11.0, 0.85, 1.0),
            (p, 12.0, 0.88, 3.0),
            (p, 13.0, 0.87, 4.0),
        ]
        hits = aggregate_match_points_to_segments(
            pts,
            merge_gap_sec=5.0,
            min_segment_sec=0.5,
            min_points=2,
            sample_fps=1.0,
            random_seed=0,
        )
        self.assertEqual(len(hits), 1)
        self.assertAlmostEqual(hits[0].remix_start_sec, 0.0)
        self.assertAlmostEqual(hits[0].remix_end_sec, 4.0)
        self.assertAlmostEqual(hits[0].start_sec, 10.0)
        self.assertGreater(hits[0].end_sec, 12.0)

    def test_source_jump_splits_same_remix_continuity(self):
        """Consecutive remix refs but source jumps > merge_gap -> two segments."""
        p = r"D:\media\a.mp4"
        pts = [
            (p, 10.0, 0.9, 0.0),
            (p, 11.0, 0.85, 1.0),
            (p, 100.0, 0.88, 2.0),
            (p, 101.0, 0.87, 3.0),
        ]
        hits = aggregate_match_points_to_segments(
            pts,
            merge_gap_sec=15.0,
            min_segment_sec=0.5,
            min_points=2,
            sample_fps=1.0,
            random_seed=0,
        )
        self.assertEqual(len(hits), 2)

    def test_multi_video_sorted(self):
        a = r"C:\v\a.mkv"
        b = r"C:\v\b.mkv"
        pts = [
            (b, 5.0, 0.8, 0.0),
            (b, 6.0, 0.82, 0.5),
            (a, 1.0, 0.9, 1.0),
            (a, 2.0, 0.85, 2.0),
        ]
        hits = aggregate_match_points_to_segments(
            pts,
            merge_gap_sec=30.0,
            min_segment_sec=0.4,
            min_points=2,
            sample_fps=1.0,
            random_seed=0,
        )
        paths = [h.video_path for h in hits]
        self.assertEqual(len(paths), 2)
        self.assertEqual(paths[0], b)
        self.assertEqual(paths[1], a)

    def test_short_span_filtered_by_min_segment(self):
        p = r"D:\media\a.mp4"
        pts = [
            (p, 10.0, 0.9, 0.0),
            (p, 11.0, 0.85, 1.0),
        ]
        hits = aggregate_match_points_to_segments(
            pts,
            merge_gap_sec=30.0,
            min_segment_sec=1.5,
            min_points=2,
            sample_fps=1.0,
            random_seed=0,
        )
        self.assertEqual(len(hits), 0)

    def test_normalize_match_path_roundtrip(self):
        p = normalize_match_path(r"C:\Folder\file.mp4")
        self.assertTrue(len(p) > 0)


if __name__ == "__main__":
    unittest.main()
