"""Console security boundaries, retained telemetry and deployment reuse."""
import base64
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from server.relay import Registry, Server
from server.console import Console

DEVICE='0123456789ab'
TOKEN='a'*64
class ConsoleTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.registry=Registry(self.directory.name)
        self.registry.enroll(DEVICE,'desk',TOKEN)
        (Path(self.directory.name)/'servercert.pem').write_text('test certificate')
        self.server=Server(('127.0.0.1',0),self.registry,'d'*64)
        self.worker=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.worker.start()
        self.console=self.server.console
        self.cookie='micros_console='+self.console.login({'token':'d'*64},'d'*64)

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.worker.join()
        self.registry.db.close();self.directory.cleanup()

    def request(self,path,payload=None,cookie=None,origin=None,operator=False):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        headers={'Cookie':self.cookie if cookie is None else cookie}
        if operator: headers['Authorization']='Bearer '+'d'*64
        if payload is not None:
            headers.update({'Content-Type':'application/json','Origin':origin or 'http://127.0.0.1:'+str(self.server.server_port)})
        connection.request('GET' if payload is None else 'POST',path,None if payload is None else json.dumps(payload),headers)
        response=connection.getresponse();result=(response.status,dict(response.getheaders()),response.read());connection.close();return result

    def test_static_assets_have_csp_and_api_requires_session(self):
        for path in ('/','/console/sankey.min.js','/console/service-graph.js','/console/sankey.LICENSE.txt','/console/app.js','/console/flash.js','/console/memory.js','/console/style.css','/console/micros-logo.png','/console/workbench-board.png'):
            code,headers,body=self.request(path,cookie='')
            self.assertEqual(code,200);self.assertTrue(body)
            self.assertIn("script-src 'self'",headers['Content-Security-Policy'])
            if path.endswith('.png'):
                self.assertEqual(headers['Content-Type'],'image/png')
                self.assertTrue(body.startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertEqual(self.request('/console/api/devices',cookie='')[0],401)
        self.assertEqual(self.request('/console/../relay.py')[0],404)
        self.assertEqual(self.request('/console/api/devices')[0],200)

    def test_local_console_can_disable_sign_in_without_disabling_api_auth(self):
        settings = Path(self.directory.name) / "console.json"
        settings.write_text(json.dumps(dict(require_token=False)))
        self.console = self.server.console = Console(self.registry)
        self.assertFalse(self.console.authentication_required)
        self.assertEqual(self.request('/console/api/devices', cookie='')[0], 200)
        self.assertEqual(self.request('/v1/devices', cookie='')[0], 401)
        with patch.object(self.console, 'submit', return_value='a'*32) as submit:
            self.assertEqual(self.request('/console/api/devices/'+DEVICE+'/action', {'action':'reboot'}, cookie='')[0], 200)
            submit.assert_called_once()
            self.assertEqual(self.request('/console/api/devices/'+DEVICE+'/action', {'action':'reboot'}, cookie='', origin='https://other.test')[0], 403)
        settings.write_text(json.dumps(dict(require_token=True)))
        self.server.console = Console(self.registry)
        self.assertEqual(self.request('/console/api/devices', cookie='')[0], 401)

    def test_ticket_single_use_cookie_flags_and_logout(self):
        ticket=self.console.ticket()
        code,headers,_=self.request('/console/session',{'ticket':ticket},cookie='')
        self.assertEqual(code,200)
        for flag in ('Secure','HttpOnly','SameSite=Strict','Path=/console'):
            self.assertIn(flag,headers['Set-Cookie'])
        self.assertEqual(self.request('/console/session',{'ticket':ticket},cookie='')[0],401)
        self.request('/console/logout',{})
        self.assertEqual(self.request('/console/api/devices')[0],401)

    def test_cross_origin_mutation_rejected_before_job_creation(self):
        with patch.object(self.console,'submit') as submit:
            code,_,_=self.request('/console/api/devices/'+DEVICE+'/action',{'action':'reboot'},origin='https://attacker.example')
            self.assertEqual(code,403);submit.assert_not_called()
            self.assertEqual(self.request('/console/api/devices/'+DEVICE+'/action',{'action':'reboot'},cookie='')[0],401)
            submit.assert_not_called()

    def test_enrollment_lost_reply_retry_preserves_same_token(self):
        payload=dict(device_id='f'*12,name='new',token='e'*64)
        self.assertEqual(self.request('/console/api/enroll',payload)[0],200)
        self.assertEqual(self.request('/console/api/enroll',payload)[0],200)
        payload['token']='c'*64
        self.assertEqual(self.request('/console/api/enroll',payload)[0],400)
        self.assertTrue(self.registry.authorized('f'*12,'e'*64))

    def test_history_sampling_boot_and_persistence(self):
        status={'identity':{'device_id':DEVICE},'heap':12345,'services':[],'uptime_us':100}
        with patch('server.relay.POLL_SECONDS',0):
            self.registry.poll(DEVICE,'b'*16,status)
            self.registry.poll(DEVICE,'b'*16,status)
            self.assertEqual(len(self.registry.management.history(DEVICE)['samples']),1)
            self.registry.poll(DEVICE,'c'*16,status)
        history=self.registry.management.history(DEVICE)
        self.assertEqual(len(history['samples']),2)
        self.assertEqual(history['events'][0]['action'],'boot')
        restored=Console(self.registry)
        self.assertEqual(restored.management.history(DEVICE),history)
        self.assertFalse(restored.authenticated(self.cookie))

    def test_cli_label_receipt_omits_configuration_and_private_payloads(self):
        from micros_tooling.fleet.server import RelayRemote
        remote=object.__new__(RelayRemote)
        remote.raw=Mock()
        inspection=dict(before={'identity':{'base_sha256':'a'*64},'deployment_session':'private-session'},
            banks={0:{'digest':'b'*64,'images':b'private image'}},
            plan={'services':[{'name':'button','version':'1','config':'private config',
                               'permissions':{'publish_mask':1}}], 'channels':[]})
        remote.register_release(inspection)
        payload=remote.raw.call_args.args[2]
        self.assertNotIn(b'private',payload)
        self.registry.management.accept_release_labels(json.loads(payload))
        invalid=json.loads(payload);invalid['before']['identity']['base_sha256']='not-a-hash'
        with self.assertRaises(ValueError):self.registry.management.accept_release_labels(invalid)

    def test_labels_require_matching_base_graph_and_confirmed_selection(self):
        inspection=dict(before={'identity':{'base_sha256':'base'}},banks={0:{'digest':'graph'}},
            plan={'services':[{'name':'button','version':'1','permissions':{'publish_mask':1}},
                              {'name':'colors','version':'2','permissions':{'publish_mask':0}}],
                  'channels':[{'key':1,'name':'button.state'}]})
        self.registry.management.remember_release(inspection)
        status={'identity':{'base_sha256':'base'},'activation':{'good_sha256':'graph','pending':0},
                'services':[{},{}],'channels':[{'key':1}]}
        decorated=self.registry.management.decorate(status)
        self.assertEqual([s['name'] for s in decorated['services']],['colors','button'])
        self.assertEqual(decorated['channels'][0]['name'],'button.state')
        self.assertNotIn('name',status['services'][0])
        status['activation']['pending']=1
        self.assertNotIn('labels_source',self.registry.management.decorate(status))
        status['activation']['pending']=0
        status['identity']['base_sha256']='different'
        self.assertNotIn('labels_source',self.registry.management.decorate(status))

    def test_removed_view_routes_and_asset_are_unavailable(self):
        for suffix in ('view', 'stream'):
            self.assertEqual(self.request('/console/api/devices/'+DEVICE+'/'+suffix,{})[0],404)
        self.assertEqual(self.request('/console/views.js')[0],404)

    def test_stream_http_open_batch_read_close_and_auth(self):
        from channel_fixture import make_device
        from server.relay import WIRE
        from micros_tooling.communication.protobuf import message_class
        status=make_device()['status']
        binding=status['channel_ports'][0]
        inspection=dict(before={'identity':{'base_sha256':'a'*64}},banks={0:{'digest':'b'*64}},
            plan={'services':[{'name':'board.network-bridge','version':'1','permissions':{'publish_mask':0}},
                              {'name':'board.pin-monitor','version':'1','permissions':{'publish_mask':1}}],
                  'channels':[], 'channel_ports':[binding]})
        self.registry.management.remember_release(inspection)
        with patch('server.relay.POLL_SECONDS',0):self.registry.poll(DEVICE,'b'*16,status)
        path='/v1/streams/'+DEVICE
        opened={'action':'open','base':'a'*64,'graph':'b'*64,'service':'board.pin-monitor','port':'samples'}
        self.assertEqual(self.request(path,opened,cookie='')[0],401)
        # Operator endpoint and shared stream metadata do not need browser state.
        self.server.console = None
        code,_,body=self.request(path,opened,operator=True);self.assertEqual(code,200);reader=json.loads(body)
        wire=self.registry.poll(DEVICE,'b'*16,status)
        cls=message_class(binding['port']['descriptor'])
        packet={'stream':{'id':WIRE.unpack(wire[:64])[1].hex(),'batch':{'error':0,'events':[{'data':cls(value=7).SerializeToString().hex()}]}}}
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        connection.request('POST','/agent/'+DEVICE+'/poll',json.dumps(packet),{'Authorization':'Bearer '+TOKEN,'X-Micros-Boot':'b'*16})
        response=connection.getresponse();self.assertEqual(response.status,200);self.assertTrue(response.read().startswith(b'MRS1'));connection.close()
        code,_,body=self.request(path,{'action':'read',**{k:reader[k] for k in ('reader','cursor')}},operator=True)
        self.assertEqual(code,200);self.assertEqual(json.loads(body)['events'][0]['sample']['value'],7)
        self.assertEqual(self.request(path,{'action':'close','reader':reader['reader']},operator=True)[0],200)
        self.assertFalse(self.registry.streams.readers)
        self.assertEqual(self.registry.db.execute('SELECT count(*) FROM commands').fetchone()[0],0)

    def test_channel_identity_cannot_silently_change_for_same_graph(self):
        inspection=dict(before={'identity':{'base_sha256':'a'*64}},banks={0:{'digest':'b'*64}},
            plan={'services':[], 'channels':[], 'channel_ports':[{'service':'example','version':'1','port':{'name':'samples','descriptor':'Original'}}]})
        self.registry.management.remember_release(inspection)
        inspection['plan']['channel_ports'][0]['port']['descriptor']='Changed'
        with self.assertRaises(ValueError):self.registry.management.remember_release(inspection)
        with self.registry.changed:
            labels=json.loads(self.registry.db.execute('SELECT labels FROM release_labels').fetchone()[0])
        self.assertEqual(labels['channel_ports'][0]['port']['descriptor'],'Original')
        inspection['plan']['channel_ports']=[]
        self.registry.management.remember_release(inspection)
        with self.registry.changed:
            labels=json.loads(self.registry.db.execute('SELECT labels FROM release_labels').fetchone()[0])
        self.assertEqual(labels['channel_ports'][0]['port']['descriptor'],'Original')

    def test_release_rejects_unsafe_paths_before_package_processing(self):
        with patch('micros_tooling.storage.bundles.release_packages') as packages:
            with self.assertRaises(ValueError):
                self.console.release(Mock(),'preview',{'files':{'../../secret':'','bundle.json':'','firmware.elf':''}},Mock())
            packages.assert_not_called()

    def test_deploy_requires_exact_review_and_reuses_transaction(self):
        files={name:base64.b64encode(b'data').decode() for name in ('bundle.json','receipt.json','firmware.elf')}
        inspection=dict(plan={'services':[],'channels':[]},banks={0:{'digest':'graph'}},unchanged=False,before={'identity':{'base_sha256':'base'}})
        with patch('micros_tooling.storage.bundles.release_packages',return_value=['package']), patch('micros_tooling.deployment.deploy.inspect_deployment',return_value=inspection), patch('micros_tooling.deployment.deploy.deploy',return_value={'unchanged':False, 'status': {}}) as deploy, \
                patch('micros_tooling.storage.workspace.Workspace'), \
                patch('micros_tooling.storage.artifacts.archive_release') as archive, \
                patch('micros_tooling.storage.artifacts.confirm_release') as confirm:
            preview=self.console.release(Mock(),'preview',{'files':files},Mock())
            deploy.assert_not_called()
            with self.assertRaises(ValueError):self.console.release(Mock(),'deploy',{'files':files,'reviewed':'wrong'},Mock())
            deploy.assert_not_called()
            self.console.release(Mock(),'deploy',{'files':files,'reviewed':preview['fingerprint']},Mock())
            self.assertIs(deploy.call_args.kwargs['prepared'],inspection)
            archive.assert_called_once()
            confirm.assert_called_once()

if __name__=='__main__':unittest.main()
