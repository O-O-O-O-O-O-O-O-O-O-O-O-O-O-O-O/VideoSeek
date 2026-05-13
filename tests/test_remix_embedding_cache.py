import os
import tempfile
import unittest

import numpy as np

from src.services import remix_embedding_cache as rec


class TestRemixEmbeddingCache(unittest.TestCase):
    def test_save_load_roundtrip_stable_key(self):
        with tempfile.TemporaryDirectory() as td:
            vpath = os.path.join(td, "mix.mp4")
            with open(vpath, "wb") as f:
                f.write(b"x" * 4000)
            cfg = {"data_root": td}

            vectors = np.random.randn(3, 12).astype(np.float32)
            ref_times = np.array([0.0, 1.0, 2.0], dtype=np.float64)
            rec.save_remix_embedding_cache(
                vpath,
                sample_fps=1.0,
                model_profile_id="prof_a",
                index_dim=12,
                vectors=vectors,
                ref_times=ref_times,
                config=cfg,
            )
            got = rec.try_load_remix_embedding_cache(
                vpath,
                sample_fps=1.0,
                model_profile_id="prof_a",
                index_dim=12,
                config=cfg,
            )
            self.assertIsNotNone(got)
            gv, gt = got
            self.assertEqual(gv.shape, (3, 12))
            np.testing.assert_allclose(gv, vectors, rtol=0, atol=1e-6)
            np.testing.assert_allclose(gt, ref_times)

    def test_get_remix_embed_cache_dir_creates_folder(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = {"data_root": td}
            d = rec.get_remix_embed_cache_dir(cfg)
            self.assertTrue(os.path.isdir(d))
            self.assertTrue(d.replace("\\", "/").rstrip("/").endswith("remix_embed"))
