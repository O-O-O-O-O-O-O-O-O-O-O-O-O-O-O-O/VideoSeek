import sys
import unittest

from PySide6.QtWidgets import QApplication

from ui.state.app_ui_state import AppUiState


class AppUiStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication(sys.argv)

    def test_indexing_signal_only_on_change(self):
        state = AppUiState()
        seen = []
        state.indexing_changed.connect(seen.append)
        state.set_indexing_running(True)
        state.set_indexing_running(True)
        state.set_indexing_running(False)
        self.assertEqual(seen, [True, False])

    def test_resources_ready_properties(self):
        state = AppUiState()
        state.set_resources_status({"resources_ready": True, "model_ready": True, "ffmpeg_ready": False})
        self.assertTrue(state.resources_ready)
        self.assertTrue(state.model_ready)
        self.assertFalse(state.ffmpeg_ready)

    def test_inference_changed_emits_snapshot(self):
        state = AppUiState()
        payloads = []
        state.inference_changed.connect(payloads.append)
        payload = {"backend": "GPU", "initialized": True}
        state.set_inference_status(payload)
        self.assertEqual(payloads[0], payload)
        self.assertEqual(state.inference_status["backend"], "GPU")


if __name__ == "__main__":
    unittest.main()
