"""The SDK patch must not shrink live record allocations or alter error cleanup."""
from pathlib import Path
import sys
import ssl
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from micros_tooling.platforms.build_esp8266 import patch_dynamic_tls_setup, patch_tls_handshake_diagnostics, prepare_relay_ca


class TLSSetupTest(unittest.TestCase):
    def test_handshake_instrumentation_is_opt_in_and_keeps_error_handling(self):
        source = ('#include "esp_log.h"\n'
                  '    ret = mbedtls_ssl_handshake(&tls->ssl);\n'
                  '    if (ret != 0) {\n'
                  'ESP_LOGE(TAG, "mbedtls_ssl_handshake returned -0x%x", -ret);\n'
                  'return -1;\n}\n')
        normal = patch_tls_handshake_diagnostics(source)
        self.assertIn('ret = mbedtls_ssl_handshake(&tls->ssl);', normal)
        self.assertNotIn('esp_timer_get_time', normal)
        detailed = patch_tls_handshake_diagnostics(source, detailed=True)
        self.assertIn('while (tls->ssl.state != MBEDTLS_SSL_HANDSHAKE_OVER)', detailed)
        self.assertIn('ret = mbedtls_ssl_handshake_step(&tls->ssl);', detailed)
        self.assertIn('if (ret != 0) break;', detailed)
        self.assertTrue(detailed.endswith('return -1;\n}\n'))
        self.assertNotIn('mbedtls_ssl_conf_authmode', detailed)
        with self.assertRaises(ValueError):
            patch_tls_handshake_diagnostics(source.replace('ret = mbedtls_ssl_handshake(&tls->ssl);', ''), True)

    def test_relay_trust_is_frozen_and_updates_without_changing_shared_roots(self):
        source = Path(__file__).resolve().parents[2] / 'src/firmware/platforms/esp8266/sdk/certs/relay-roots.pem'
        original = source.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frozen = prepare_relay_ca(source, root)
            self.assertEqual(frozen.read_bytes(), original)
            first = original.split(b'-----END CERTIFICATE-----')[0] + b'-----END CERTIFICATE-----\n'
            custom = root / 'custom.pem'
            custom.write_bytes(first)
            self.assertEqual(prepare_relay_ca(custom, root), frozen)
            self.assertEqual(frozen.read_bytes(), first)
            self.assertEqual(source.read_bytes(), original)

    def test_duplicate_trust_is_removed_without_dropping_unique_roots(self):
        source = Path(__file__).resolve().parents[2] / 'src/firmware/platforms/esp8266/sdk/certs/relay-roots.pem'
        original = source.read_text()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repeated = root / 'repeated.pem'
            repeated.write_text(original + original)
            self.assertEqual(prepare_relay_ca(repeated, root).read_text(), original)

    def test_invalid_trust_and_private_keys_are_rejected_before_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'input.pem'
            for value in ('not a certificate', '-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----',
                          '-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----'):
                source.write_text(value)
                with self.assertRaises((ValueError, ssl.SSLError)):
                    prepare_relay_ca(source, root / 'output')
                self.assertFalse((root / 'output/trust/relay-roots.pem').exists())

    def test_certificate_with_private_key_cannot_replace_frozen_trust(self):
        source = Path(__file__).resolve().parents[2] / 'src/firmware/platforms/esp8266/sdk/certs/relay-roots.pem'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frozen = prepare_relay_ca(source, root)
            original = frozen.read_bytes()
            mixed = root / 'mixed.pem'
            mixed.write_bytes(original + b'\n-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----\n')
            with self.assertRaisesRegex(ValueError, 'only PEM certificates'):
                prepare_relay_ca(mixed, root)
            self.assertEqual(frozen.read_bytes(), original)

    def test_only_initial_setup_allocations_are_reduced(self):
        allocations = '\n'.join(
            f'ssl->{kind.lower()}_buf = mbedtls_calloc( 1, MBEDTLS_SSL_{kind}_BUFFER_LEN );'
            for kind in ('IN', 'OUT'))
        before = 'void read_record() {\n' + allocations + '\n}\n'
        after = '\nerror:\n    mbedtls_free(ssl->in_buf);\n}\n' + allocations
        patched = patch_dynamic_tls_setup(before + 'int mbedtls_ssl_setup( void ) {\n' + allocations + after)
        self.assertTrue(patched.startswith(before))
        self.assertTrue(patched.endswith(after))
        self.assertEqual(patched.count('mbedtls_calloc( 1, MBEDTLS_SSL_HEADER_LEN )'), 2)

    def test_unexpected_upstream_setup_is_rejected(self):
        with self.assertRaises(ValueError):
            patch_dynamic_tls_setup('int mbedtls_ssl_setup( void ) {\nerror:\n}')


if __name__ == '__main__':
    unittest.main()
