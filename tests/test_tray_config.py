import unittest

from src.app.config import CONFIG_ENUMS, DEFAULT_CONFIG


class TrayConfigTests(unittest.TestCase):
    def test_close_window_action_default_is_exit(self):
        self.assertEqual(DEFAULT_CONFIG["close_window_action"], "exit")

    def test_close_window_action_enum(self):
        self.assertEqual(CONFIG_ENUMS["close_window_action"], {"exit", "tray"})


if __name__ == "__main__":
    unittest.main()
