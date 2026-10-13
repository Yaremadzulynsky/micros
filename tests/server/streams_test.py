"""Exercise the actual relay streaming scheduler, fan-out and bounded replay."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2] / "src"))
from server.relay import Registry, WIRE
from channel_fixture import make_device
from micros_tooling.communication.protobuf import message_class

DEVICE='0123456789ab'
BOOT='b'*16

class StreamsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.device=make_device()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.registry=Registry(self.tmp.name)
        self.registry.enroll(DEVICE,'fixture','a'*64)
        self.status=copy.deepcopy(self.device['status']);self.binding=self.status['channel_ports'][0]
        self.cls=message_class(self.binding['port']['descriptor'])
        self.hub=self.registry.streams
        self.poll(self.status)
    def tearDown(self):self.registry.db.close();self.tmp.cleanup()
    def poll(self,status):
        with patch('server.relay.POLL_SECONDS',0):return self.registry.poll(DEVICE,BOOT,status)
    def open(self):
        with self.registry.changed:return self.hub.open(DEVICE,BOOT,self.status,self.binding)
    def read(self,reader,cursor=None):
        with self.registry.changed,patch('server.streams.READ_SECONDS',0):
            return self.hub.read(DEVICE,reader['reader'],reader['cursor'] if cursor is None else cursor)
    def packet(self,wire,n=8):
        frame=WIRE.unpack(wire[:WIRE.size])
        self.assertEqual(frame[0],b'MRS1');self.assertTrue(wire[WIRE.size:].startswith(b'IPC DRAIN 0 1 1 '))
        return dict(stream=dict(id=frame[1].hex(),batch=dict(error=0,events=[dict(data=self.cls(
            sequence=i,monotonic_us=2**54+i,value=i,pin=34).SerializeToString().hex()) for i in range(n)])))

    def test_batch_fanout_no_per_sample_commands_or_database_writes(self):
        first=self.open();second=self.open()
        wire=self.poll(self.status)
        before=self.registry.db.total_changes
        packet=self.packet(wire)
        following=self.poll(packet)
        self.assertEqual(self.registry.db.total_changes,before)
        a,b=self.read(first),self.read(second)
        self.assertEqual(a,b);self.assertEqual(len(a['events']),8)
        self.assertEqual(a['events'][0]['sample']['monotonic_us'],str(2**54))
        self.assertEqual(self.registry.db.execute('SELECT count(*) FROM commands').fetchone()[0],0)
        # If the HTTP response was lost, re-deliver the same batch and reissue
        # the pending drain, without advancing any viewer cursor twice.
        self.assertEqual(self.poll(packet),following)
        self.assertEqual(self.read(first),a)
        self.assertEqual(self.read(first,a['cursor'])['events'],[])

    def test_empty_channel_backs_off_and_data_resumes_fast_turns(self):
        self.open();wire=self.poll(self.status)
        self.assertEqual(WIRE.unpack(wire[:64])[6],50)
        for expected in (100,200,400,500,500):
            wire=self.poll(self.packet(wire,0))
            self.assertEqual(WIRE.unpack(wire[:64])[6],expected)
        wire=self.poll(self.packet(wire,1))
        self.assertEqual(WIRE.unpack(wire[:64])[6],50)

    def test_device_gap_order_and_slow_viewer_gap(self):
        slow=self.open();wire=self.poll(self.status)
        packet=self.packet(wire,1)
        packet['stream']['batch']['events'].insert(0,dict(missed=9))
        wire=self.poll(packet)
        self.assertEqual(self.read(slow)['events'][0],dict(state='gap',missed=9,source='device'))
        for _ in range(40):wire=self.poll(self.packet(wire))
        result=self.read(slow)
        self.assertEqual(result['events'][0]['source'],'viewer')
        self.assertGreater(result['events'][0]['missed'],0)
        self.assertLessEqual(len(result['events']),64)
        self.assertEqual(len(next(iter(self.hub.ports.values()))['records']),256)

    def test_readers_close_expire_and_restart(self):
        reader=self.open();wire=self.poll(self.status)
        with self.registry.changed:self.hub.close(DEVICE,reader['reader'])
        self.assertEqual(self.poll(self.packet(wire)),b'')
        self.assertFalse(self.hub.ports)
        reader=self.open()
        self.hub.readers[reader['reader']]['expires']=0
        self.assertEqual(self.poll(self.status),b'')
        self.assertFalse(self.hub.readers)
        reader=self.open();self.status['activation']['sequence']+=1;self.poll(self.status)
        with self.assertRaisesRegex(ValueError,'changed'):self.read(reader)

    def test_invalid_or_conflicting_frame_rejected(self):
        reader=self.open();packet=self.packet(self.poll(self.status))
        invalid=copy.deepcopy(packet);invalid['stream']['batch']['events']*=2
        with self.assertRaises(ValueError):self.poll(invalid)
        self.assertEqual(self.read(reader)['events'],[])
        self.poll(packet)
        packet['stream']['batch']['events']=[]
        with self.assertRaisesRegex(ValueError,'Conflicting'):self.poll(packet)
        self.assertEqual(len(self.read(reader)['events']),8)

    def test_management_priority_and_never_replay_command(self):
        self.open();packet=self.packet(self.poll(self.status))
        result=[]
        worker=threading.Thread(target=lambda:result.append(self.registry.command(DEVICE,6,0,0,0,'',b'')))
        worker.start()
        with self.registry.changed:
            while not self.registry.db.execute("SELECT 1 FROM commands WHERE state='queued'").fetchone():
                self.registry.changed.wait(.1)
        wire=self.poll(packet);header=WIRE.unpack(wire[:WIRE.size])
        self.assertEqual(header[0],b'MRL1');self.assertEqual(header[2],6)
        self.assertEqual(self.poll(packet),b'')  # No drain while reboot is dispatched.
        self.registry.result(DEVICE,header[1].hex(),200,b'{}');worker.join(2)
        self.assertEqual(result,[(200,b'{}')])
        self.assertEqual(WIRE.unpack(self.poll(packet)[:WIRE.size])[0],b'MRS1')

    def test_reader_bound_and_device_isolation(self):
        reader=self.open()
        with self.registry.changed:
            with self.assertRaises(ValueError):self.hub.read('f'*12,reader['reader'],0)
        from server.streams import MAX_READERS
        for _ in range(MAX_READERS-1):self.open()
        with self.assertRaisesRegex(ValueError,'Too many'):self.open()
        with self.registry.changed:
            self.registry.db.execute("UPDATE devices SET token_hash='' WHERE id=?",(DEVICE,));self.registry.db.commit()
        with self.assertRaises(ValueError):self.read(reader)
        with self.assertRaises(ValueError):self.poll(self.status)

if __name__=='__main__':unittest.main()
