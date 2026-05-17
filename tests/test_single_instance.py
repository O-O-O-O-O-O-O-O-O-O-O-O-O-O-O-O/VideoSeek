import sys
import unittest

from PySide6.QtWidgets import QApplication

from src.app.single_instance import (
    SingleInstanceServer,
    single_instance_server_name,
    try_activate_existing_instance,
)


class SingleInstanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication(sys.argv)

    def test_server_name_is_stable_for_session(self):
        self.assertEqual(single_instance_server_name(), single_instance_server_name())

    def test_secondary_launch_activates_primary(self):
        idle_name = f"{single_instance_server_name()}_idle"
        self.assertFalse(try_activate_existing_instance(server_name=idle_name))

        name = f"{single_instance_server_name()}_test"
        activated = []
        server = SingleInstanceServer(server_name=name)
        server.set_activate_handler(lambda: activated.append(True))

        self.assertTrue(try_activate_existing_instance(server_name=name))
        self._app.processEvents()
        self.assertEqual(activated, [True])


if __name__ == "__main__":
    unittest.main()
