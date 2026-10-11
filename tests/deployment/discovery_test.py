import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from micros_tooling.communication import discovery as d


class DiscoveryTest(unittest.TestCase):
    def probe(self, replies):
        connection = Mock()
        connection.read.side_effect = replies
        with patch('serial.Serial', return_value=connection):
            result = d.probe(dict(port='/fake', aliases=['/fake']), .2)
        connection.close.assert_called_once()
        self.assertFalse(connection.dtr)
        self.assertFalse(connection.rts)
        for call in connection.write.call_args_list:
            self.assertEqual(call.args[0], b'RPC 0 0 0 0 - -\n')
        return result

    def test_embedded_fragmented_and_corrupt(self):
        value = dict(result=0, platform='esp8266', target=6, identity=dict(device_id='f4cfa2d08ce3'))
        data = json.dumps(value).encode()
        result = self.probe([b'{"broken log\n', data[:30], data[30:] + b'\n'])
        self.assertEqual(result['device_id'], 'f4cfa2d08ce3')
        self.assertEqual(result['platform'], 'esp8266')

    def test_samd(self):
        result = self.probe([b'{"result":0,"platform":"samd21","target":5,"identity":{"device_id":"ac1da4519140"}}\n'])
        self.assertEqual(result['platform'], 'samd21')

    def test_esp32(self):
        result = self.probe([b'{"result":0,"platform":"esp32","target":2,"identity":{"device_id":"aabbccddeeff"}}\n'])
        self.assertEqual(result['device_id'], 'aabbccddeeff')

    def test_silence_and_arbitrary_json_are_unidentified(self):
        connection = Mock()
        connection.read.return_value = b'WIFI {"mac":"aa:bb:cc:dd:ee:ff"}\n'
        with patch('serial.Serial', return_value=connection):
            result = d.probe(dict(port='/fake'), .01)
        self.assertEqual(result['state'], 'unidentified')
        connection.close.assert_called_once()

    def test_silent_port_deadline(self):
        connection = Mock()
        connection.read.return_value = b''
        with patch('serial.Serial', return_value=connection):
            result = d.probe(dict(port='/fake'), .01)
        self.assertEqual(result['state'], 'unidentified')
        connection.close.assert_called_once()

    def test_picker_shows_identity_and_keeps_unknown(self):
        from micros_tooling.deployment import enrollment as e
        import argparse
        ports = [Mock(device='/one', vid=0x10c4, pid=1, location='1'),
                 Mock(device='/two', vid=0x10c4, pid=1, location='2')]
        results = [dict(port='/one', state='identified', platform='esp8266', device_id='f4cfa2d08ce3'),
                   dict(port='/two', state='unidentified', reason='No micros identity reply')]
        with patch('serial.tools.list_ports.comports', return_value=ports), patch.object(e, 'interactive', return_value=True), patch.object(d, 'discover', return_value=results), patch('builtins.input', return_value='2'), patch.object(e, 'progress') as progress:
            self.assertEqual(e.choose_port(argparse.Namespace(port=None, json=False)), '/two')
        displayed = str(progress.call_args_list)
        self.assertIn('f4cfa2d08ce3', displayed)
        self.assertIn('unidentified', displayed)

    def test_rom_fallback_identifies_blank_controller(self):
        from micros_tooling.deployment import enrollment as e
        candidate = dict(port='/fake')
        output = 'Chip is ESP8266EX\nMAC: aa:bb:cc:dd:ee:ff\nDetected flash size: 4MB'
        with patch.object(d, 'probe', return_value=dict(candidate, state='unidentified')), patch.object(e, 'esptool', return_value=['esptool']), patch.object(e, 'run_tool', return_value=output) as run:
            result = d.probe_controller(candidate)
        self.assertEqual(result['source'], 'rom')
        self.assertEqual(result['device_id'], 'aabbccddeeff')
        self.assertIn('flash_id', run.call_args.args[0])

    def test_picker_excludes_enrolled_controller(self):
        from micros_tooling.deployment import enrollment as e
        import argparse
        ports = [Mock(device='/one', vid=0x10c4, pid=1, location='1'), Mock(device='/two', vid=0x10c4, pid=1, location='2')]
        results = [dict(port='/one', state='identified', platform='esp8266', device_id='f4cfa2d08ce3'), dict(port='/two', state='identified', platform='esp32', device_id='aabbccddeeff')]
        with patch('serial.tools.list_ports.comports', return_value=ports), patch.object(e, 'interactive', return_value=True), patch.object(d, 'discover', return_value=results), patch('builtins.input', return_value='1'), patch.object(e, 'progress') as progress:
            selected = e.choose_port(argparse.Namespace(port=None, json=False), roster=[dict(device_id='f4cfa2d08ce3', name='beta')])
        self.assertEqual(selected, '/two')
        self.assertIn('already enrolled', str(progress.call_args_list))

    def test_arduino_never_uses_esp_rom_probe(self):
        from micros_tooling.deployment import enrollment as e
        candidate = dict(port='/arduino', vid=0x2341, pid=0x8054)
        with patch.object(d, 'probe', return_value=dict(candidate, state='unidentified')), patch.object(e, 'run_tool') as run:
            result = d.probe_controller(candidate)
        run.assert_not_called()
        self.assertEqual(result['platform'], 'samd21')
        self.assertTrue(result['supported'])

    def test_rom_recognizes_unsupported_esp32_variant(self):
        from micros_tooling.deployment import enrollment as e
        candidate = dict(port='/fake')
        output = 'Chip is ESP32-S3\nMAC: aa:bb:cc:dd:ee:ff\nDetected flash size: 8MB'
        with patch.object(d, 'probe', return_value=dict(candidate, state='unidentified')), patch.object(e, 'esptool', return_value=['esptool']), patch.object(e, 'run_tool', return_value=output):
            result = d.probe_controller(candidate)
        self.assertEqual(result['chip'], 'ESP32-S3')
        self.assertFalse(result['supported'])
        self.assertIn('not supported yet', d.describe(result))

    def test_operation_support_and_missing_samd_identity(self):
        for platform in ('esp8266', 'esp32', 'samd21'):
            result = dict(state='identified', platform=platform, device_id='ac1da4519140')
            for operation in ('enroll', 'erase'):
                self.assertIsNone(d.operation_blocker(result, operation))
                self.assertIn(operation + ' supported', d.describe(result, operation))
        blank = dict(state='identified', platform='samd21', source='usb')
        self.assertIsNone(d.operation_blocker(blank, 'enroll'))
        self.assertIn('console identity', d.operation_blocker(blank, 'erase'))
        self.assertIn('not supported yet', d.operation_blocker(dict(platform='samd51'), 'erase'))

    def test_erase_picker_excludes_unavailable_samd_and_uses_command_labels(self):
        from micros_tooling.deployment import enrollment as e
        import argparse
        ports = [Mock(device='/one', vid=0x2341, pid=0x0054, location='1'), Mock(device='/two', vid=0x2341, pid=0x8054, location='2')]
        results = [dict(port='/one', state='identified', platform='samd21', source='usb'), dict(port='/two', state='identified', platform='samd21', device_id='ac1da4519140')]
        with patch('serial.tools.list_ports.comports', return_value=ports), patch.object(e, 'interactive', return_value=True), patch.object(d, 'discover', return_value=results), patch('builtins.input', return_value='1'), patch.object(e, 'progress') as progress:
            self.assertEqual(e.choose_port(argparse.Namespace(command='erase', port=None, json=False)), '/two')
        self.assertIn('erase supported', str(progress.call_args_list))
        self.assertIn('erase unavailable', str(progress.call_args_list))

    def test_busy(self):
        import serial
        connection = Mock()
        connection.open.side_effect = serial.SerialException('busy')
        with patch('serial.Serial', return_value=connection):
            result = d.probe(dict(port='/fake'))
        self.assertEqual(result['state'], 'unavailable')
        connection.write.assert_not_called()
        connection.close.assert_called_once()

    def test_aliases_and_duplicate_serial_numbers(self):
        def port(name, location):
            return Mock(device=name, location=location, vid=0x10c4, pid=1, serial_number='0001', description='bridge')
        with patch('serial.tools.list_ports.comports', return_value=[port('/dev/cu.usbserial-1', '1'), port('/dev/cu.SLAB', '1'), port('/dev/cu.usbserial-2', '2')]):
            found = d.ports()
        self.assertEqual(len(found), 2)
        self.assertEqual(len(found[0]['aliases']), 2)


if __name__ == '__main__':
    unittest.main()
