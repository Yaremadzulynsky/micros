"""Exercise relay ownership, scoped authentication, uncertain outcomes and persistence."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2] / "src"))
from server.relay import Registry, WIRE, Server
import http.client

DEVICE = '0123456789ab'
TOKEN = 'a'*64
BOOT = 'b'*16
STATUS = {'identity':{'device_id':DEVICE}, 'services':[]}

class RelayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.registry = Registry(self.temp.name)
        self.registry.enroll(DEVICE, 'test', TOKEN)

    def tearDown(self):
        self.registry.db.close()
        self.temp.cleanup()

    def test_minimal_application_keeps_enrolled_server(self):
        from micros_tooling.communication.relay_config import enrolled_server_settings
        from micros_tooling.storage.packages import PackageError
        root = Path(self.temp.name)
        with self.assertRaisesRegex(PackageError, "no server address"):
            enrolled_server_settings({}, root)
        (root / "server.json").write_text(json.dumps(dict(url="https://example.test:8443")))
        self.assertEqual(enrolled_server_settings({}, root), "https://example.test:8443")
        self.assertEqual(enrolled_server_settings(dict(management=dict(server=dict(url="https://other.test"))), root), "https://other.test")
        self.assertEqual(enrolled_server_settings({}), "")

    def ready(self):
        with patch('server.relay.POLL_SECONDS',0):
            self.registry.poll(DEVICE, BOOT, STATUS)

    def test_authentication_scopes_and_offline_presence(self):
        self.registry.enroll(DEVICE, 'test', TOKEN)  # Lost enrollment replies are safe to retry.
        with self.assertRaises(ValueError):
            self.registry.enroll(DEVICE, 'test', 'f'*64)
        self.assertTrue(self.registry.authorized(DEVICE,TOKEN))
        self.assertFalse(self.registry.authorized('a'*12,TOKEN))
        self.assertFalse(self.registry.authorized(DEVICE,'bad'))
        self.assertFalse(self.registry.devices()[0]['online'])
        self.ready()
        self.assertTrue(self.registry.devices()[0]['online'])
        with self.assertRaises(ValueError):
            self.registry.poll(DEVICE,BOOT,{'identity':{'device_id':'f'*12}})

    def test_command_delivered_once_and_result_retries_are_idempotent(self):
        self.ready()
        results = []
        worker = threading.Thread(target=lambda: results.append(self.registry.command(DEVICE,2,1,3,0,'c'*32,b'image')))
        worker.start()
        wire = self.registry.poll(DEVICE,BOOT,STATUS)
        magic, identity, operation, bank, slot, _, cursor, session, size = WIRE.unpack(wire[:64])
        self.assertEqual((magic,operation,bank,slot,size,wire[64:]),(b'MRL1',2,1,3,5,b'image'))
        with patch('server.relay.POLL_SECONDS',0):
            self.assertEqual(self.registry.poll(DEVICE,BOOT,STATUS),b'')
        self.registry.result(DEVICE,identity.hex(),200,b'{"ok":true}')
        self.registry.result(DEVICE,identity.hex(),200,b'{"ok":true}')
        worker.join(2)
        self.assertEqual(results,[(200,b'{"ok":true}')])
        with self.assertRaises(ValueError):
            self.registry.result(DEVICE,identity.hex(),409,b'changed')

    def test_platform_commands_are_delivered_once_without_persisting_secrets(self):
        self.ready()
        body = b'@' + b'c' * 32 + b' WIFI_SET 6e6574 736563726574'
        results = []
        worker = threading.Thread(target=lambda: results.append(
            self.registry.command(DEVICE, 18, 0, 0, 0, '', body)))
        worker.start()
        wire = self.registry.poll(DEVICE, BOOT, STATUS)
        self.assertEqual(WIRE.unpack(wire[:64])[2], 18)
        self.assertEqual(wire[64:], body)
        with self.registry.changed:
            row = self.registry.db.execute('SELECT wire, private FROM commands').fetchone()
        self.assertEqual(row, (None, 2))
        with patch('server.relay.POLL_SECONDS', 0):
            self.assertEqual(self.registry.poll(DEVICE, BOOT, STATUS), b'')
        self.registry.result(DEVICE, WIRE.unpack(wire[:64])[1].hex(), 200, b'{"result":0}')
        worker.join(2)
        self.assertEqual(results, [(200, b'{"result":0}')])

    def test_concurrent_reads_wait_for_the_single_device_channel(self):
        self.ready()
        results = []
        first = threading.Thread(target=lambda: results.append(self.registry.command(DEVICE, 0, 0, 0, 0, '', b'')))
        second = threading.Thread(target=lambda: results.append(self.registry.command(DEVICE, 7, 0, 0, 0, '', b'')))
        first.start()
        wire = self.registry.poll(DEVICE, BOOT, STATUS)
        second.start()
        self.registry.result(DEVICE, WIRE.unpack(wire[:64])[1].hex(), 200, b'{}')
        wire = self.registry.poll(DEVICE, BOOT, STATUS)
        self.assertEqual(WIRE.unpack(wire[:64])[2], 7)
        self.registry.result(DEVICE, WIRE.unpack(wire[:64])[1].hex(), 200, b'{}')
        first.join(2)
        second.join(2)
        self.assertEqual(results, [(200, b'{}'), (200, b'{}')])

    def test_console_requests_use_embedded_rpc_framing(self):
        from server.remote import RegistryRemote
        for platform in ('samd21','esp8266'):
            with patch('server.relay.POLL_SECONDS',0):
                self.registry.poll(DEVICE,BOOT,dict(STATUS,platform=platform))
            remote=RegistryRemote(self.registry,DEVICE)
            with patch.object(self.registry,'command',return_value=(200,b'{"result":0}')) as command:
                remote.request('GET','/v1/log-stream?cursor=1099511627776')
                self.assertEqual(command.call_args.args[1:5],(18,0,0,0))
                self.assertEqual(command.call_args.args[-1],b'RPC 7 0 0 1099511627776 - -')
                remote.session_id='c'*32
                remote.request('POST','/v1/platform-command',b'SERVICE COMMAND')
                self.assertEqual(command.call_args.args[-1],
                    ('RPC 18 0 0 0 '+'c'*32+' '+b'SERVICE COMMAND'.hex()).encode())

    def test_timeout_and_restart_never_replay_work(self):
        self.ready()
        with patch('server.relay.COMMAND_SECONDS',0.02):
            status, body = self.registry.command(DEVICE,5,0,0,0,'c'*32,b'')
        self.assertEqual(status,504)
        self.assertEqual(json.loads(body)['error'],'outcome_unknown')
        self.registry.db.close()
        self.registry = Registry(self.temp.name)
        with patch('server.relay.POLL_SECONDS',0):
            self.assertEqual(self.registry.poll(DEVICE,BOOT,STATUS),b'')
        self.assertEqual(self.registry.devices()[0]['name'],'test')

    def test_boot_change_cancels_pending_command(self):
        self.ready()
        results = []
        worker = threading.Thread(target=lambda: results.append(self.registry.command(DEVICE, 0, 0, 0, 0, '', b'')))
        worker.start()
        wire = self.registry.poll(DEVICE, BOOT, STATUS)
        self.assertTrue(wire)
        with patch('server.relay.POLL_SECONDS', 0):
            self.assertEqual(self.registry.poll(DEVICE, 'c'*16, STATUS), b'')
        worker.join(2)
        self.assertEqual(results[0][0], 504)

    def test_base_download_is_device_scoped_bounded_and_temporary(self):
        import hashlib
        image = b'a'*81920; digest = hashlib.sha256(image).hexdigest()
        operator = Server(('127.0.0.1', 0), self.registry, 'd'*64)
        agent = Server(('127.0.0.1', 0), self.registry, 'd'*64, agent_only=True)
        for server in (operator,agent):
            threading.Thread(target=server.serve_forever,daemon=True).start()
        def request(server,method,path,token,body=b'',extra=None):
            connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
            try:
                connection.request(method,path,body,{'Authorization':'Bearer '+token,**(extra or {})})
                response=connection.getresponse();return response.status,response.read()
            finally:connection.close()
        upload='/devices/'+DEVICE+'/v1/base-image/'+digest
        download='/agent/'+DEVICE+'/base/'+digest
        try:
            self.assertEqual(request(agent,'POST',upload,'d'*64,image)[0],404)
            self.assertEqual(request(operator,'POST',upload,TOKEN,image)[0],401)
            self.assertEqual(request(operator,'POST',upload,'d'*64,image),(200,b'{}'))
            self.assertEqual(request(agent,'GET',download,TOKEN),(200,image))
            self.assertEqual(request(agent,'GET',download,TOKEN,extra={'Range':'bytes=2048-4095'}),(206,image[2048:4096]))
            for value in ('bytes=0-8192','bytes=81920-81921','bytes=-1','bytes=20-10','bytes=0-1,4-5'):
                self.assertEqual(request(agent,'GET',download,TOKEN,extra={'Range':value})[0],416)
            self.assertEqual(request(agent,'GET',download,'d'*64)[0],401)
            self.assertEqual(request(agent,'POST',download,TOKEN)[0],404)
            self.assertEqual(request(agent,'GET',download+'?x=1',TOKEN)[0],404)
            other='f'*12;self.registry.enroll(other,'other','e'*64)
            self.assertEqual(request(agent,'GET',download.replace(DEVICE,other),TOKEN)[0],401)
            self.assertEqual(request(agent,'GET',download.replace(DEVICE,other),'e'*64)[0],404)
            self.assertEqual(request(operator,'POST',upload,'d'*64,image+b'xxxx')[0],413)
            self.assertEqual(request(operator,'POST',upload,'d'*64,b'b'*256)[0],400)
            with patch('server.relay.time.monotonic',return_value=time.monotonic()+601):
                self.assertEqual(request(agent,'GET',download,TOKEN)[0],404)
        finally:
            for server in (operator,agent):server.shutdown();server.server_close()

    def test_http_command_and_agent_result_round_trip(self):
        self.ready()
        server = Server(('127.0.0.1', 0), self.registry, 'd'*64)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        agents = Server(('127.0.0.1', 0), self.registry, 'd'*64, agent_only=True)
        agent_worker = threading.Thread(target=agents.serve_forever, daemon=True)
        agent_worker.start()
        def request(method, path, token, body=b'', extra=None):
            port = agents.server_port if path.startswith('/agent/') else server.server_port
            connection = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
            try:
                connection.request(method, path, body, {'Authorization':'Bearer '+token, **(extra or {})})
                response = connection.getresponse()
                return response.status, response.read()
            finally:
                connection.close()
        results = []
        operator = threading.Thread(target=lambda: results.append(request('GET', '/devices/'+DEVICE+'/v1/status', 'd'*64)))
        try:
            operator.start()
            code, wire = request('POST', '/agent/'+DEVICE+'/poll', TOKEN, json.dumps(STATUS).encode(), {'X-Micros-Boot':BOOT})
            self.assertEqual(code, 200)
            command = WIRE.unpack(wire[:64])[1].hex()
            payload = json.dumps(STATUS).encode()
            self.assertEqual(request('POST', '/agent/'+DEVICE+'/result/'+command, TOKEN, payload, {'X-Micros-Result':'200'})[0], 200)
            operator.join(3)
            self.assertEqual(results, [(200, payload)])
        finally:
            agents.shutdown()
            agents.server_close()
            agent_worker.join()
            server.shutdown()
            server.server_close()
            worker.join()

    def test_device_listener_rejects_operator_routes_and_auth_bypasses(self):
        (Path(self.temp.name)/'console.json').write_text('{"require_token": false}')
        operator = Server(('127.0.0.1', 0), self.registry, 'd'*64)
        server = Server(('127.0.0.1', 0), self.registry, 'd'*64, agent_only=True)
        self.assertIs(self.registry.management, operator.console.management)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        def request(method, path, token='d'*64):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)
            try:
                connection.request(method, path, json.dumps(STATUS), {
                    'Authorization': 'Bearer '+token, 'Host': 'console.example.com',
                    'Origin': 'http://console.example.com', 'Content-Type': 'application/json',
                    'X-Micros-Boot': BOOT, 'Cf-Access-Jwt-Assertion': 'forged'})
                response = connection.getresponse()
                response.read()
                return response.status
            finally:
                connection.close()
        try:
            for path in ('/', '/console/', '/console/session', '/console/api/devices',
                         '/v1/devices', '/v1/console-ticket', '/v1/enroll',
                         '/v1/artifacts/bases/'+'a'*64, '/devices/'+DEVICE+'/v1/reboot',
                         '/agent/'+DEVICE+'/poll/../console/',
                         '/agent/'+DEVICE+'/poll?extra=1',
                         'https://console.example.com/agent/'+DEVICE+'/poll'):
                for method in ('GET', 'POST', 'PUT', 'DELETE'):
                    with self.subTest(path=path, method=method):
                        self.assertEqual(request(method, path), 404)
            path = '/agent/'+DEVICE+'/poll'
            self.assertEqual(request('GET', path, TOKEN), 404)
            self.assertEqual(request('POST', path), 401)
            self.assertEqual(request('POST', path, 'bad'), 401)
            self.assertEqual(request('POST', '/agent/'+'f'*12+'/poll', TOKEN), 401)
            with patch('server.relay.POLL_SECONDS', 0):
                self.assertEqual(request('POST', path, TOKEN), 204)
            self.assertTrue(self.registry.devices()[0]['online'])
        finally:
            server.shutdown()
            server.server_close()
            worker.join()
            operator.server_close()

    def test_http_auth_and_route_allowlist(self):
        server = Server(('127.0.0.1',0),self.registry,'d'*64)
        worker = threading.Thread(target=server.serve_forever,daemon=True)
        worker.start()
        try:
            for path, token, expected in (('/v1/devices',TOKEN,401),('/v1/devices','d'*64,200),
                    ('/devices/'+DEVICE+'/v1/erase-flash','d'*64,404)):
                connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=2)
                connection.request('GET',path,headers={'Authorization':'Bearer '+token})
                response=connection.getresponse()
                response.read()
                self.assertEqual(response.status,expected)
                connection.close()
        finally:
            server.shutdown()
            server.server_close()
            worker.join()

class SelectionTests(unittest.TestCase):
    def test_cloudflare_client_keeps_operator_and_access_auth_separate(self):
        from micros_tooling.fleet.server import RelayRemote
        from micros_tooling.storage.packages import PackageError
        from types import SimpleNamespace
        from unittest.mock import Mock
        remote = object.__new__(RelayRemote)
        remote.access_origin = 'https://console.example.test'
        remote.access_token = None
        remote.host, remote.port, remote.context = 'console.example.test', 443, None
        remote.token, remote.session_id = 'd'*64, ''
        response = Mock(status=200)
        response.read.return_value = b'{}'
        connection = Mock()
        connection.getresponse.return_value = response
        with patch('micros_tooling.fleet.server.shutil.which', return_value='/bin/cloudflared'), \
                patch('micros_tooling.fleet.server.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout='header.payload.signature\n')) as run, \
                patch('http.client.HTTPSConnection', return_value=connection):
            remote.raw('GET', '/v1/devices')
            remote.raw('POST', '/v1/console-ticket')
            self.assertEqual(run.call_count, 1)
            headers = connection.request.call_args.args[3]
            self.assertEqual(headers['Authorization'], 'Bearer '+'d'*64)
            self.assertEqual(headers['Cf-Access-Token'], 'header.payload.signature')
            response.status = 302
            with self.assertRaisesRegex(PackageError, 'Renew your login'):
                remote.raw('GET', '/v1/devices')
            self.assertEqual(connection.request.call_count, 3)  # Never follow redirects with credentials.
        remote.access_token = None
        with patch('micros_tooling.fleet.server.shutil.which', return_value='/bin/cloudflared'), \
                patch('micros_tooling.fleet.server.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout='secret\r\nInjected: value')):
            with self.assertRaisesRegex(PackageError, 'Sign in first'):
                remote.access_headers()
        remote.access_origin = None
        with patch('micros_tooling.fleet.server.subprocess.run') as run:
            self.assertEqual(remote.access_headers(), {})
            run.assert_not_called()

    def test_online_selection_and_interactive_choices(self):
        from micros_tooling.fleet.server import choose_device
        from micros_tooling.storage.packages import PackageError
        first = dict(device_id=DEVICE, name='desk', online=True, last_seen=123)
        second = dict(device_id='f'*12, name='lab', online=True, last_seen=124)
        offline = dict(device_id='e'*12, name='absent', online=False, last_seen=100)
        self.assertEqual(choose_device([offline, first]), first)
        self.assertEqual(choose_device([first, second], 'lab'), second)
        self.assertEqual(choose_device([first, second], interactive=True, ask=lambda _: '2'), second)
        for devices, name in (([first, second], None), ([offline], None), ([offline], 'absent'), ([first], 'missing')):
            with self.assertRaises(PackageError):
                choose_device(devices, name)

    def test_discovery_uses_server_names_and_rebuilds_routing_cache(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock as Mock
        from micros_tooling.fleet.server import discover_for_command
        from micros_tooling.storage.packages import PackageError
        workspace = Mock()
        workspace.profiles.return_value = dict(default='stale', devices={
            'local-alias': dict(device_id=DEVICE), 'stale': dict(device_id='f'*12)})
        remote = Mock()
        remote.raw.return_value = json.dumps(dict(devices=[dict(
            device_id=DEVICE, name='desk', online=True, last_seen=123)])).encode()
        with patch('micros_tooling.fleet.server.configured_remote', return_value=remote):
            args = SimpleNamespace(device=None, command='deploy')
            self.assertTrue(discover_for_command(workspace, args)[2])
            self.assertEqual(args.device, DEVICE)
            args.device = 'local-alias'
            with self.assertRaisesRegex(PackageError, 'unknown or ambiguous'):
                discover_for_command(workspace, args)
            args.device = 'desk'
            self.assertTrue(discover_for_command(workspace, args)[2])
            workspace.profiles.return_value = dict(default=None, devices={})
            args.device = None
            self.assertTrue(discover_for_command(workspace, args)[2])
            self.assertEqual(args.device, DEVICE)
            self.assertEqual(workspace.write.call_args.args[1]['devices'][DEVICE]['device_id'], DEVICE)
            workspace.profiles.return_value = dict(default=None, devices={})
            args.command = 'build'
            self.assertTrue(discover_for_command(workspace, args)[2])
            args.command = 'history'
            self.assertTrue(discover_for_command(workspace, args)[2])
            args.command = 'status'
            self.assertFalse(discover_for_command(workspace, args)[2])

    def test_server_cli_parser_and_private_sqlite_backup(self):
        from micros_tooling.fleet.server import server_main
        from micros_tooling.storage.bundles import export_state, read_bundle
        from micros_tooling.storage.workspace import Workspace
        import sqlite3
        with self.assertRaises(SystemExit) as result:
            server_main(['--help'])
        self.assertEqual(result.exception.code, 0)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = Workspace(root/'state')
            (workspace.root/'server').mkdir(parents=True)
            source = sqlite3.connect(workspace.root/'server/registry.sqlite')
            source.execute('PRAGMA journal_mode=WAL')
            source.execute('CREATE TABLE sample(value TEXT)')
            source.execute("INSERT INTO sample VALUES ('committed')")
            source.commit()
            try:
                export_state(workspace, root/'backup')
                files = read_bundle(root/'backup', 'private-state')
                self.assertNotIn('server/registry.sqlite-wal', files)
                snapshot = sqlite3.connect(root/'backup/server/registry.sqlite')
                self.assertEqual(snapshot.execute('SELECT value FROM sample').fetchone(), ('committed',))
                self.assertEqual(snapshot.execute('PRAGMA integrity_check').fetchone(), ('ok',))
                snapshot.close()
            finally:
                source.close()

if __name__=='__main__':
    unittest.main()
