import json
import os
import tempfile
import unittest

import numpy as np

from src.storage.asset_store import save_vector_payload
from src.storage.video_id_migration import (
    VIDEO_ID_FORMAT_VERSION,
    iter_model_asset_storage_roots,
    legacy_video_ids_pending,
    migrate_legacy_video_ids,
    migrate_model_storage_root,
    video_id_migration_completed,
)
from src.utils import get_legacy_video_hash, get_video_hash


class VideoIdMigrationTests(unittest.TestCase):
    def test_legacy_and_current_hash_differ_when_mtime_included(self):
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            handle.write(b"videoseek-test-content")
            path = handle.name
        try:
            self.assertNotEqual(get_legacy_video_hash(path), get_video_hash(path))
        finally:
            os.remove(path)

    def test_migrate_renames_assets_and_updates_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            base_dir = os.path.join(data_dir, "model_assets", "openai-clip", "vit-base-patch32")
            vector_dir = os.path.join(base_dir, "vector")
            index_dir = os.path.join(base_dir, "index")
            library_root = os.path.join(tmp, "library")
            os.makedirs(vector_dir, exist_ok=True)
            os.makedirs(index_dir, exist_ok=True)
            os.makedirs(library_root, exist_ok=True)

            video_path = os.path.join(library_root, "clip.mp4")
            with open(video_path, "wb") as handle:
                handle.write(b"x" * 2048)

            legacy_vid = get_legacy_video_hash(video_path)
            new_vid = get_video_hash(video_path)
            vectors = np.zeros((3, 512), dtype=np.float32)
            timestamps = [0.0, 1.0, 2.0]
            save_vector_payload(vectors, timestamps, os.path.join(vector_dir, f"{legacy_vid}_vectors.npy"))

            meta = {
                "schema_version": 2,
                "libraries": {
                    library_root: {
                        "files": {
                            "clip.mp4": {
                                "vid": legacy_vid,
                                "mod_time": os.path.getmtime(video_path),
                                "asset_state": "ready",
                            }
                        }
                    }
                },
            }
            meta_file = os.path.join(base_dir, "meta.json")
            with open(meta_file, "w", encoding="utf-8") as handle:
                json.dump(meta, handle)

            config = {
                "data_root": tmp,
                "meta_file": meta_file,
                "vector_dir": vector_dir,
                "index_dir": index_dir,
            }
            roots = list(iter_model_asset_storage_roots(config))
            self.assertEqual(len(roots), 1)

            stats = migrate_model_storage_root(roots[0])
            self.assertEqual(stats["migrated"], 1)
            self.assertTrue(os.path.isfile(os.path.join(vector_dir, f"{new_vid}_vectors.npy")))
            self.assertFalse(os.path.isfile(os.path.join(vector_dir, f"{legacy_vid}_vectors.npy")))

            with open(meta_file, "r", encoding="utf-8") as handle:
                migrated_meta = json.load(handle)
            entry = migrated_meta["libraries"][library_root]["files"]["clip.mp4"]
            self.assertEqual(entry["vid"], new_vid)
            self.assertNotEqual(migrated_meta.get("global_index_state"), "stale")

    def test_migration_marks_state_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            os.makedirs(data_dir, exist_ok=True)
            config = {"data_root": tmp}
            self.assertFalse(video_id_migration_completed(config))
            result = migrate_legacy_video_ids(config=config)
            self.assertEqual(result["video_id_format"], VIDEO_ID_FORMAT_VERSION)
            self.assertTrue(video_id_migration_completed(config))

    def test_pending_when_meta_has_new_vid_but_vectors_use_legacy_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            base_dir = os.path.join(data_dir, "model_assets", "openai-clip", "vit-base-patch32")
            vector_dir = os.path.join(base_dir, "vector")
            library_root = os.path.join(tmp, "library")
            os.makedirs(vector_dir, exist_ok=True)
            os.makedirs(library_root, exist_ok=True)

            video_path = os.path.join(library_root, "clip.mp4")
            with open(video_path, "wb") as handle:
                handle.write(b"x" * 2048)

            legacy_vid = get_legacy_video_hash(video_path)
            new_vid = get_video_hash(video_path)
            save_vector_payload(
                np.zeros((2, 512), dtype=np.float32),
                [0.0, 1.0],
                os.path.join(vector_dir, f"{legacy_vid}_vectors.npy"),
            )

            meta = {
                "libraries": {
                    library_root: {
                        "files": {
                            "clip.mp4": {"vid": new_vid, "mod_time": os.path.getmtime(video_path), "asset_state": "ready"},
                        }
                    }
                }
            }
            meta_file = os.path.join(base_dir, "meta.json")
            with open(meta_file, "w", encoding="utf-8") as handle:
                json.dump(meta, handle)

            state_file = os.path.join(data_dir, "migration_state.json")
            with open(state_file, "w", encoding="utf-8") as handle:
                json.dump({"video_id_format": 2, "completed": True}, handle)

            config = {"data_root": tmp}
            self.assertTrue(legacy_video_ids_pending(config))
            stats = migrate_model_storage_root(
                {
                    "meta_file": meta_file,
                    "vector_dir": vector_dir,
                    "index_dir": os.path.join(base_dir, "index"),
                    "base_dir": base_dir,
                    "label": "test",
                }
            )
            self.assertEqual(stats["migrated"], 1)
            self.assertTrue(os.path.isfile(os.path.join(vector_dir, f"{new_vid}_vectors.npy")))

    def test_completed_flag_ignored_while_legacy_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            base_dir = os.path.join(data_dir, "model_assets", "openai-clip", "vit-base-patch32")
            vector_dir = os.path.join(base_dir, "vector")
            library_root = os.path.join(tmp, "library")
            os.makedirs(vector_dir, exist_ok=True)
            os.makedirs(library_root, exist_ok=True)

            video_path = os.path.join(library_root, "clip.mp4")
            with open(video_path, "wb") as handle:
                handle.write(b"x" * 2048)

            legacy_vid = get_legacy_video_hash(video_path)
            new_vid = get_video_hash(video_path)
            save_vector_payload(
                np.zeros((2, 512), dtype=np.float32),
                [0.0, 1.0],
                os.path.join(vector_dir, f"{legacy_vid}_vectors.npy"),
            )

            meta = {
                "libraries": {
                    library_root: {
                        "files": {
                            "clip.mp4": {"vid": legacy_vid, "mod_time": os.path.getmtime(video_path), "asset_state": "ready"},
                        }
                    }
                }
            }
            meta_file = os.path.join(base_dir, "meta.json")
            with open(meta_file, "w", encoding="utf-8") as handle:
                json.dump(meta, handle)

            state_file = os.path.join(data_dir, "migration_state.json")
            with open(state_file, "w", encoding="utf-8") as handle:
                json.dump({"video_id_format": 2, "completed": True}, handle)

            config = {"data_root": tmp}
            self.assertTrue(legacy_video_ids_pending(config))
            self.assertFalse(video_id_migration_completed(config))
            result = migrate_legacy_video_ids(config=config)
            self.assertEqual(result["migrated_video_ids"], 1)
            self.assertFalse(result.get("pending_legacy"))
            self.assertTrue(video_id_migration_completed(config))


if __name__ == "__main__":
    unittest.main()
