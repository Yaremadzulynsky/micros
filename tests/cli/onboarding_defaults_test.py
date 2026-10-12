"""Independent server namespaces and usable target-specific starter units."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from micros_tooling.config.scaffold import create, bind_starter
from micros_tooling.config.configuration import read_toml
from micros_tooling.fleet import server


class ServerCertificateTest(unittest.TestCase):
    def test_lan_certificate_supports_modern_ip_and_legacy_exact_name_verifiers(self):
        import ssl
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory)
            server.server_main(['--state', str(root), 'setup', '--host', '192.0.2.21'])
            cert = ssl._ssl._test_decode_cert(str(root / 'servercert.pem'))
            self.assertIn(('IP Address', '192.0.2.21'), cert['subjectAltName'])
            self.assertIn(('DNS', '192.0.2.21'), cert['subjectAltName'])

from micros_tooling.storage.packages import PackageError


class ConsoleHandoffTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='micros console ')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        with contextlib.redirect_stdout(io.StringIO()):
            server.server_main(['--state', str(self.root), 'setup', '--host', 'localhost'])

    def test_browser_failure_is_actionable_and_does_not_leak_ticket(self):
        import shlex
        import webbrowser
        for outcome in (False, webbrowser.Error('No browser'), OSError('Browser missing')):
            output = io.StringIO()
            with patch.object(server, 'RelayRemote') as remote, \
                 patch('webbrowser.open', side_effect=outcome if isinstance(outcome, Exception) else None,
                       return_value=False), contextlib.redirect_stdout(output):
                remote.return_value.raw.return_value = b'{"ticket":"private-test-ticket"}'
                with self.assertRaisesRegex(PackageError, 'Could not open a browser') as caught:
                    server.server_main(['--state', str(self.root), 'console'])
            self.assertIn(shlex.quote(str(self.root.resolve())), str(caught.exception))
            self.assertIn('--no-browser', str(caught.exception))
            self.assertNotIn('private-test-ticket', str(caught.exception) + output.getvalue())

    def test_no_browser_prints_only_link_to_stdout_and_warning_to_stderr(self):
        output, error = io.StringIO(), io.StringIO()
        with patch.object(server, 'RelayRemote') as remote, patch('webbrowser.open') as browser, \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            remote.return_value.raw.return_value = b'{"ticket":"private-test-ticket"}'
            server.server_main(['--state', str(self.root), 'console', '--no-browser'])
        browser.assert_not_called()
        self.assertEqual(output.getvalue(), 'https://localhost:8443/console/#ticket=private-test-ticket\n')
        self.assertIn('60 seconds', error.getvalue())

    def test_trust_info_matches_openssl_and_does_not_connect_or_open_browser(self):
        output = io.StringIO()
        with patch.object(server, 'RelayRemote') as remote, patch('webbrowser.open') as browser, \
             contextlib.redirect_stdout(output):
            server.server_main(['--state', str(self.root), 'console', '--trust-info'])
        expected = subprocess.check_output(['openssl', 'x509', '-in', str(self.root/'servercert.pem'),
                                            '-noout', '-fingerprint', '-sha256'], text=True).strip().split('=')[1]
        self.assertIn(expected, output.getvalue())
        self.assertIn(str(self.root/'servercert.pem'), output.getvalue())
        self.assertNotIn((self.root/'admin.token').read_text(), output.getvalue())
        remote.assert_not_called(); browser.assert_not_called()

    def test_success_opens_one_use_link_without_printing_it(self):
        output = io.StringIO()
        with patch.object(server, 'RelayRemote') as remote, patch('webbrowser.open', return_value=True) as browser, \
             contextlib.redirect_stdout(output):
            remote.return_value.raw.return_value = b'{"ticket":"private-test-ticket"}'
            server.server_main(['--state', str(self.root), 'console'])
        browser.assert_called_once_with('https://localhost:8443/console/#ticket=private-test-ticket')
        self.assertNotIn('private-test-ticket', output.getvalue())
        self.assertIn('--trust-info', output.getvalue())


class OnboardingDefaultsTest(unittest.TestCase):
    def test_each_starter_composes_without_target_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            for platform,profile,stack in [('esp32','esp32_d0wd_v3_no_controls',4096),
                                           ('samd21','arduino_mkr_wifi_1010',1024),
                                           ('esp8266','esp8266_4mb',1536)]:
                app=create(Path(directory)/platform,platform)
                self.assertEqual(sorted(p.name for p in (app / 'units').glob('*.toml')), ['host.toml'])
                path=bind_starter(app,'aabbccddeeff',platform,4 if platform!='samd21' else None)
                unit=read_toml(path)
                self.assertEqual(unit['board']['profile'],profile)
                self.assertEqual(unit['services']['climate_sensor']['memory']['stack_bytes'],stack)
                self.assertEqual('flash_mb' in unit['board'],platform=='esp32')
                result=subprocess.run([str(app/'micros'),'compose'],env=dict(os.environ,MICROS_SDK=str(ROOT)),capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertIn('example.climate-sensor',result.stdout)

    def run_server(self,action,options=(),environment=None):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'client.json').write_text(json.dumps({'url':'https://localhost:8443'}))
            for name in ('servercert.pem', 'admin.token', 'prvtkey.pem'):
                (root/name).write_text('test fixture')
            with patch.dict(os.environ,environment or {},clear=True), \
                 patch.object(server,'RelayRemote',return_value=Mock()), \
                 patch.object(server.shutil,'which',return_value=sys.executable), \
                 patch.object(server.subprocess,'run',return_value=Mock(returncode=0)) as run,contextlib.redirect_stdout(io.StringIO()):
                server.server_main(['--state',str(root),*options,action])
                return run.call_args

    def test_default_namespace_is_backwards_compatible(self):
        self.assertEqual(self.run_server('start').args[0][3],'micros-management')

    def test_start_and_shutdown_use_same_explicit_namespace(self):
        for action in ('start','shutdown'):
            call=self.run_server(action,['--compose-project','micros-consumer-test'])
            self.assertEqual(call.args[0][3],'micros-consumer-test')
            self.assertNotIn('micros-management',call.args[0])

    def test_environment_namespace_and_flag_override(self):
        env={'MICROS_COMPOSE_PROJECT':'micros-from-env'}
        self.assertEqual(self.run_server('shutdown',environment=env).args[0][3],'micros-from-env')
        self.assertEqual(self.run_server('shutdown',['--compose-project','explicit'],env).args[0][3],'explicit')

    def test_invalid_namespace_rejected_before_credentials_or_docker(self):
        for name in ('','UPPER','-prefix','two names','a/b','$(command)'):
            with patch.object(server,'RelayRemote') as remote,patch.object(server.subprocess,'run',return_value=Mock(returncode=0)) as run:
                with self.assertRaisesRegex(PackageError,'Compose project'):
                    server.server_main(['--state','/nonexistent','--compose-project='+name,'start'])
                remote.assert_not_called();run.assert_not_called()

if __name__=='__main__':unittest.main()
