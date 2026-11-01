"""Position recovery uses desktop coordinates, including negative monitor origins."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtCore import QRect
from polaris_platform.desktop.window import WindowHost


class WindowPositionTests(unittest.TestCase):
    def clamp(self, x, y, bounds):
        screens = [SimpleNamespace(availableGeometry=lambda rect=rect: rect) for rect in bounds]
        view = SimpleNamespace(width=lambda: 280, height=lambda: 320)
        with patch('polaris_platform.desktop.window.QGuiApplication.screens', return_value=screens):
            return WindowHost._clamp(None, view, x, y)

    def test_secondary_screen_position_is_retained(self):
        screens = [QRect(0, 0, 1920, 1040), QRect(1920, 0, 2560, 1400)]
        self.assertEqual(self.clamp(2100, 300, screens), (2100, 300))

    def test_left_and_upper_screens_accept_negative_coordinates(self):
        screens = [QRect(0, 0, 1920, 1040), QRect(-1600, 0, 1600, 860), QRect(0, -1200, 1600, 1160)]
        self.assertEqual(self.clamp(-1000, 200, screens), (-1000, 200))
        self.assertEqual(self.clamp(300, -900, screens), (300, -900))

    def test_gap_uses_nearest_screen_and_removed_screen_recovers(self):
        screens = [QRect(0, 0, 1920, 1040), QRect(2400, 200, 1280, 984)]
        self.assertEqual(self.clamp(2120, 300, screens), (2400, 300))
        self.assertEqual(self.clamp(-1400, 300, screens[:1]), (0, 300))

    def test_release_uses_overlap_and_respects_taskbar(self):
        screens = [QRect(0, 0, 1920, 1040), QRect(1920, 0, 1280, 984)]
        self.assertEqual(self.clamp(1850, 850, screens), (1920, 664))


if __name__ == '__main__':
    unittest.main()
