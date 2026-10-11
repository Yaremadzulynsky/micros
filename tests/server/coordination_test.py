"""Actual router scheduling, source fencing, loss injection and journal isolation."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2] / "src"))
from server.relay import Registry
from server.coordination import RECORD, WIRE, Coordinator

A='000000000001'
B='000000000002'

class CoordinationTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.r=Registry(self.temp.name)
        self.status={}
        for d in (A,B):
            self.r.enroll(d,d,'a'*64)
            self.status[d]=dict(identity=dict(device_id=d,base_sha256='b'*64,abi_revision=7),
                                activation=dict(good_sha256='c'*64,pending=False,sequence=1),services=[dict(state='Running')])
            with patch('server.relay.POLL_SECONDS',0):self.r.poll(d,'1'*16,self.status[d])
        self.doc=dict(routes=[dict(name='test',kind='action',max_payload=32,schema='d'*64,drop_first=2,
            source=dict(device=A,key=1,base='b'*64,graph='c'*64,sequence=1),target=dict(device=B,key=1,base='b'*64,graph='c'*64,sequence=1))])
        with self.r.changed:self.r.coordination.configure(self.doc)
        self.h=self.r.coordination
    def tearDown(self):
        self.r.db.close();self.temp.cleanup()
    def exchange(self,device,reply):
        self.h.due[device]=0
        with self.r.changed:
            wire=self.h.next_frame(device)
            self.assertIsNotNone(wire)
            token=WIRE.unpack(wire[:64])[1].hex()
            self.r.result(device,token,200,json.dumps(dict(reply=reply)).encode())
        return wire[64:].decode()
    def bind(self):
        self.assertTrue(self.exchange(A,'COORD BOUND 0 4d').startswith('COORD B'))
        self.exchange(B,'COORD BOUND 0 4d')
    def packet(self,sequence=1,status=0):
        return RECORD.pack(b'MCO1',2,0,1,self.h.routes[0]['config']['epoch'],sequence,status,0,0,0)+b'x'
    def test_faults_drop_advertisements_then_forward_without_journaling(self):
        self.bind();packet=self.packet()
        self.exchange(A,'COORD DATA '+packet.hex())
        self.assertTrue(self.exchange(B,'COORD DATA ').endswith(' -'))
        self.assertTrue(self.exchange(B,'COORD DATA ').endswith(' -'))
        self.assertTrue(self.exchange(B,'COORD DATA ').endswith(packet.hex()))
        self.assertEqual(self.h.counts['dropped'],2)
        self.assertEqual(self.r.db.execute('SELECT count(*) FROM commands').fetchone()[0],0)
    def test_reboot_fences_and_clears_pending_records(self):
        self.bind();self.exchange(A,'COORD DATA '+self.packet().hex())
        with self.r.changed:self.h.observe(A,'2'*16,self.status[A])
        self.h.due[B]=0
        self.assertIsNone(self.h.next_frame(B));self.assertTrue(self.h.routes[0]['blocked'])
        self.assertEqual(self.h.routes[0]['records'],{})
    def test_restarted_server_preserves_pinned_generation(self):
        epoch=self.h.routes[0]['config']['epoch']
        other=Coordinator(self.r)
        self.assertEqual(other.routes[0]['config']['epoch'],epoch)
        self.assertEqual(other.routes[0]['config']['source']['boot'],'1'*16)
    def test_offline_peer_is_not_fed_cached_state(self):
        self.bind();self.exchange(A,'COORD DATA '+self.packet().hex())
        self.r.db.execute('UPDATE devices SET last_seen=? WHERE id=?',(time.time()-60,A))
        self.h.due[B]=0;self.assertIsNone(self.h.next_frame(B))
    def test_invalid_configuration_is_atomic(self):
        before=self.h.path.read_bytes();bad=copy.deepcopy(self.doc)
        bad['routes'][0]['target']['graph']='f'*64
        with self.r.changed,self.assertRaises(ValueError):self.h.configure(bad)
        self.assertEqual(self.h.path.read_bytes(),before)
    def test_malformed_or_wrong_direction_record_blocks_route(self):
        self.bind();self.exchange(A,'COORD DATA '+self.packet(status=2).hex())
        self.assertTrue(self.h.routes[0]['blocked'])
    def test_inflight_frame_is_not_replayed(self):
        self.h.due[A]=0
        with self.r.changed:first=self.h.next_frame(A)
        self.h.due[A]=0
        self.assertIsNone(self.h.next_frame(A))
        self.h.inflight[A]['at']-=11
        with self.r.changed:second=self.h.next_frame(A)
        self.assertNotEqual(first[:20],second[:20])

if __name__=='__main__':unittest.main()
