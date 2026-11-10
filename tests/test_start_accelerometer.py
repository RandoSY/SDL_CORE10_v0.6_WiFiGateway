"""Regression checks for DHCP changes and stale monitor reuse."""
import io
import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from start_accelerometer import discover_node, existing_monitor, resolve_node, save_node


class AddressDiscoveryTests(unittest.TestCase):
    def test_saved_address_starts_without_accessing_usb(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = Path(folder)/'settings.json'
            settings.write_text('{"node_host":"192.168.0.213"}')
            with patch('start_accelerometer.discover_node', side_effect=AssertionError('USB must not be touched')):
                self.assertEqual(resolve_node(settings_path=settings), '192.168.0.213')

    def test_explicit_hostname_needs_neither_settings_nor_usb(self):
        with patch('start_accelerometer.discover_node', side_effect=AssertionError('USB must not be touched')):
            self.assertEqual(resolve_node(node_host='configured-atom.local'), 'configured-atom.local')

    def test_save_preserves_other_settings_and_reloads_without_usb(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = Path(folder)/'settings.json'
            settings.write_text('{"node_host":"192.168.0.214","operator_note":"retain"}')
            save_node('192.168.0.213', settings)
            self.assertEqual(json.loads(settings.read_text())['operator_note'], 'retain')
            self.assertEqual(resolve_node(settings_path=settings), '192.168.0.213')

    def test_connected_gateway_for_another_endpoint_is_not_reused(self):
        response = io.BytesIO(json.dumps({'node':'atom-matrix-imu','connected':True,'node_host':'192.168.0.214'}).encode())
        with patch('urllib.request.urlopen', return_value=response):
            self.assertFalse(existing_monitor(8799, '192.168.0.213'))

    def test_current_usb_address_replaces_old_dhcp_assumption(self):
        text = '[SDL-NODE] IMU=PASS WiFi=ONLINE IP=192.168.0.213 peer=0\n'
        with patch('scripts.check_atom_node.observe_serial', return_value=text):
            self.assertEqual(discover_node(), '192.168.0.213')

    def test_offline_node_is_not_given_a_guessed_address(self):
        with patch('scripts.check_atom_node.observe_serial', return_value='WiFi=UNCONFIGURED IP=0.0.0.0'):
            with self.assertRaisesRegex(RuntimeError, 'No online ATOM address'):
                discover_node()

    def test_stale_gateway_is_not_reused_as_a_live_monitor(self):
        for connected in (False, True):
            with self.subTest(connected=connected):
                response = io.BytesIO(json.dumps({'node': 'atom-matrix-imu', 'connected': connected}).encode())
                with patch('urllib.request.urlopen', return_value=response):
                    self.assertEqual(existing_monitor(8799), connected)


if __name__ == '__main__':
    unittest.main()
