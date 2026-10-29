import unittest
from unittest.mock import Mock

from memumusic.desktop import Native


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.native = Native()
        self.native._window = Mock()

    def test_maximize_and_restore_return_current_state(self):
        self.assertTrue(self.native.toggle_maximize()['maximized'])
        self.native._window.maximize.assert_called_once()
        self.assertFalse(self.native.toggle_maximize()['maximized'])
        self.native._window.restore.assert_called_once()

    def test_fullscreen_reports_state_and_notifies_page(self):
        self.assertTrue(self.native.toggle_fullscreen()['fullscreen'])
        self.assertFalse(self.native.toggle_fullscreen()['fullscreen'])
        self.assertEqual(self.native._window.toggle_fullscreen.call_count, 2)
        self.assertIn('music-window-state', self.native._window.evaluate_js.call_args.args[0])

    def test_failed_fullscreen_does_not_change_state(self):
        self.native._window.toggle_fullscreen.side_effect = RuntimeError('unavailable')
        with self.assertRaises(RuntimeError):
            self.native.toggle_fullscreen()
        self.assertFalse(self.native.window_state()['fullscreen'])

    def test_native_state_changes_update_restore_icon(self):
        self.native._notify_state(maximized=True)
        self.assertTrue(self.native.window_state()['maximized'])
        self.assertIn('"maximized": true', self.native._window.evaluate_js.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
