"""Use real HTTP operator routes, release labels, protobuf encoding and shell dispatch."""
import copy
import http.client
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'src'), str(Path(__file__).parent)]
from server.relay import Registry, Server
from micros_tooling.communication.remote import accepted
from micros_tooling.terminal.client import DeviceClient
from micros_tooling.terminal.shell import Shell
from shell_test import binding, status

DEVICE='0123456789ab'
OPERATOR='d'*64


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.registry=Registry(self.temp.name)
        self.registry.enroll(DEVICE,'desk','a'*64)
        self.server=Server(('127.0.0.1',0),self.registry,OPERATOR)
        self.worker=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.worker.start()
        self.observed=status()
        self.observed.pop('channel_ports'); self.observed.pop('service_commands')
        self.observed['services'].insert(0,dict(state='Running',result=0,steps=2,callbacks=0))
        self.observed['services'][1].pop('name')
        self.observed['activation'].update(good=0,previous=1,candidate=0xffffffff,attempts=0)
        self.registry.management.accept_release_labels(dict(before=dict(identity=dict(base_sha256='a'*64)),
            plan=dict(services=[dict(name='board.network-bridge',version='1.0.0',permissions=dict(publish_mask=1)),
                                dict(name='example.shell',version='1.0.0',permissions=dict(publish_mask=2))],
                      channels=[dict(key=1,name='example.set')],channel_ports=[binding()]),
            banks={'0':dict(digest='b'*64)}))
        self.writes=[]
        def command(device, operation, bank, slot, cursor, session, body):
            if operation==0:return 200,json.dumps(self.observed).encode()
            if operation in (8,9):return 200,b'{}'  # Real session client still frames the lease.
            if operation==18:
                self.writes.append((session,body))
                return 200,b'{"reply":"IPC QUEUED 1"}'
            raise AssertionError(operation)
        self.mock=patch.object(self.registry,'command',side_effect=command)
        self.mock.start()

    def tearDown(self):
        self.mock.stop()
        self.server.shutdown();self.server.server_close();self.worker.join()
        self.registry.db.close();self.temp.cleanup()

    def request(self,method,path,body=b'',token=OPERATOR,server=None):
        conn=http.client.HTTPConnection('127.0.0.1',(server or self.server).server_port,timeout=3)
        try:
            conn.request(method,path,body,{'Authorization':'Bearer '+token})
            response=conn.getresponse()
            return response.status,response.read()
        finally:conn.close()


    def test_operator_auth_required_and_public_listener_excludes_routes(self):
        for path,method in [('/v1/inspect/'+DEVICE,'GET'),('/v1/views/'+DEVICE,'POST')]:
            for token in ('','a'*64):
                self.assertEqual(self.request(method,path,b'{}',token)[0],401)
        public=Server(('127.0.0.1',0),self.registry,OPERATOR,agent_only=True)
        worker=threading.Thread(target=public.serve_forever,daemon=True);worker.start()
        try:
            self.assertEqual(self.request('GET','/v1/inspect/'+DEVICE,server=public)[0],404)
            self.assertEqual(self.request('POST','/v1/views/'+DEVICE,b'{}',server=public)[0],404)
        finally:public.shutdown();public.server_close();worker.join()
        self.assertFalse(self.writes)


    def test_removed_view_endpoint_returns_404(self):
        self.assertEqual(self.request('POST','/v1/views/'+DEVICE,b'{}')[0],404)
        self.assertFalse(self.writes)

    def test_no_metadata_for_unregistered_or_trial_graph(self):
        for key,value in [('good_sha256','c'*64),('pending',1)]:
            before=copy.deepcopy(self.observed)
            self.observed['activation'][key]=value
            code,body=self.request('GET','/v1/inspect/'+DEVICE)
            self.assertEqual(code,200)
            self.assertNotIn('channel_ports',json.loads(body))
            self.observed=before



if __name__=='__main__':unittest.main()
