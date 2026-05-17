import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from src.core import image_io


class ImageIoTests(unittest.TestCase):
    def test_load_image_bgr_reads_png_via_opencv(self):
        try:
            import cv2
        except ImportError:
            self.skipTest("opencv not installed")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.png"
            cv2.imwrite(str(path), np.zeros((8, 8, 3), dtype=np.uint8))
            image = image_io.load_image_bgr(str(path))
            self.assertIsNotNone(image)
            self.assertEqual(image.shape, (8, 8, 3))

    def test_normalize_heic_upload_converts_to_jpg(self):
        with tempfile.TemporaryDirectory() as tmp:
            heic_path = Path(tmp) / "phone.heic"
            heic_path.write_bytes(b"fake")
            jpg_path = Path(tmp) / "phone.jpg"
            fake_bgr = np.zeros((4, 4, 3), dtype=np.uint8)

            with patch.object(image_io, "load_image_bgr", return_value=fake_bgr), patch(
                "src.core.image_io.cv2.imwrite", return_value=True
            ) as mock_write:
                result = image_io.normalize_image_upload(str(heic_path))

            self.assertEqual(result, str(jpg_path))
            mock_write.assert_called_once()
            self.assertFalse(heic_path.exists())

    def test_encode_preview_jpeg(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.png"
            fake_bgr = np.zeros((6, 6, 3), dtype=np.uint8)
            with patch.object(image_io, "load_image_bgr", return_value=fake_bgr), patch(
                "src.core.image_io.cv2.imencode", return_value=(True, np.array([1, 2, 3], dtype=np.uint8))
            ):
                payload = image_io.encode_preview_jpeg(str(path))
            self.assertEqual(payload, b"\x01\x02\x03")

    def test_normalize_heic_upload_raises_when_decode_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            heic_path = Path(tmp) / "phone.heic"
            heic_path.write_bytes(b"fake")
            with patch.object(image_io, "load_image_bgr", return_value=None):
                with self.assertRaises(ValueError):
                    image_io.normalize_image_upload(str(heic_path))


if __name__ == "__main__":
    unittest.main()
