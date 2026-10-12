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
from micros_tooling.config.scaffold import create
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


class OnboardingDefaultsTest(unittest.TestCase):
    def test_each_starter_composes_without_target_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            for platform,profile,stack in [('esp32','esp32_d0wd_v3_no_controls',4096),
                                           ('samd21','arduino_mkr_wifi_1010',1024),
                                           ('esp8266','esp8266_4mb',4096)]:
                app=create(Path(directory)/platform,platform)
                unit=read_toml(app/'units/000000000000.toml')
                self.assertEqual(unit['board']['profile'],profile)
                self.assertEqual(unit['services']['hello']['memory']['stack_bytes'],stack)
                self.assertEqual('flash_mb' in unit['board'],platform=='esp32')
                result=subprocess.run([str(app/'micros'),'compose'],env=dict(os.environ,MICROS_SDK=str(ROOT)),capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertIn('example.hello',result.stdout)

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
