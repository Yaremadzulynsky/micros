"""Base-only transfer, rollback observation, layout and relay framing tests."""
import copy
from contextlib import contextmanager
import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch, Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from micros_tooling.deployment.base_ota import update_base, inspect_base, request_when_ready
from micros_tooling.storage.packages import PackageError
from micros_tooling.communication.remote import RemoteRejected
from micros_tooling.config.resources import board_partitions
from server.relay import Registry, WIRE, ROUTES

BEFORE = dict(identity=dict(device_id='0'*12, base_sha256='a'*64),
              activation=dict(pending=0), base_ota=dict(version=1, pending=False,
              uploading=False, slot_bytes=0x180000, trial_seconds=180))
PAYLOAD = bytes(8500)
PREPARED = dict(before=BEFORE, payload=PAYLOAD, base_sha256='b'*64,
                image_sha256=hashlib.sha256(PAYLOAD).hexdigest(), image_bytes=len(PAYLOAD))

class Remote:
    def __init__(self, mode='normal'):
        self.mode, self.calls, self.finished, self.confirmed, self.observations = mode, [], False, False, 0
    @contextmanager
    def deployment_session(self, before):
        yield
    def status(self):
        result = copy.deepcopy(BEFORE)
        if self.finished:
            self.observations += 1
            if self.mode == 'offline' and self.observations == 1:
                raise RemoteRejected(503, b'booting')
            if self.mode == 'rollback' and self.observations > 1:
                return result
            result['identity']['base_sha256'] = 'b'*64
            result['base_ota']['pending'] = not self.confirmed
            result['uptime_us'] = 6_000_000 if self.mode != 'rollback' else 1_000_000
        return result
    def request(self, method, path, body=b''):
        self.calls.append((method, path, body))
        if path.startswith('/v1/base-chunk') and self.mode == 'lost_chunk':
            raise OSError('lost reply')
        if path == '/v1/base-finish':
            self.finished = True
            if self.mode == 'lost_finish':
                raise OSError('reboot before reply')
        if path == '/v1/base-confirm':
            self.confirmed = True
            if self.mode == 'lost_confirm':
                raise OSError('lost confirmation reply')
        return dict(ok=True)

class Tests(unittest.TestCase):
    def run_update(self, remote, **kwargs):
        with patch('micros_tooling.deployment.base_ota.inspect_base', return_value=copy.deepcopy(PREPARED)):
            return update_base(remote, Path('unused'), sleep=lambda _: None, **kwargs)
    def test_preflight_rejects_wrong_binary_and_oversized_image(self):
        with tempfile.TemporaryDirectory() as directory:
            firmware=Path(directory)/'base.elf'
            firmware.write_bytes(b'ELF fixture')
            image=firmware.with_suffix('.bin')
            payload=bytearray(512);payload[0]=0xe9
            payload[32:36]=struct.pack('<I',0xabcd5432)
            payload[176:208]=hashlib.sha256(firmware.read_bytes()).digest()
            image.write_bytes(payload)
            section=Mock();section.__getitem__=Mock(return_value=0)
            section.data.return_value=struct.pack('<I',1)
            table=Mock();table.get_symbol_by_name.return_value=[dict(st_shndx=1,st_value=0)]
            elf=Mock();elf.get_section_by_name.return_value=table;elf.get_section.return_value=section
            remote=Remote();status=remote.status();status['board']=dict(flash_mb=4)
            with patch('elftools.elf.elffile.ELFFile',return_value=elf), patch('micros_tooling.deployment.base_ota.verify_board_firmware') as verify, patch.object(remote,'status',return_value=status):
                self.assertEqual(inspect_base(remote,firmware)['image_bytes'],512)
                verify.assert_called_with(dict(flash_mb=4),firmware)
                payload[176] ^= 1;image.write_bytes(payload)
                with self.assertRaisesRegex(PackageError,'BIN does not match'): inspect_base(remote,firmware)
                status['base_ota']['slot_bytes']=511
                with self.assertRaisesRegex(PackageError,'exceeds'): inspect_base(remote,firmware)
                status['base_ota']['version']=0
                with self.assertRaisesRegex(PackageError,'lacks OTA'): inspect_base(remote,firmware)
            self.assertEqual(remote.calls,[])
    def test_only_explicit_busy_rejection_is_retried(self):
        remote=Mock();remote.request.side_effect=[RemoteRejected(503,b'busy'),dict(ok=True)]
        self.assertTrue(request_when_ready(remote,'PUT','/v1/base-chunk?cursor=0',b'chunk',sleep=lambda _:None)['ok'])
        self.assertEqual(remote.request.call_count,2)
        for error in (RemoteRejected(504,b'unknown'),RemoteRejected(409,b'conflict'),OSError('lost reply')):
            remote=Mock();remote.request.side_effect=error
            with self.assertRaises(type(error)):
                request_when_ready(remote,'PUT','/v1/base-chunk?cursor=0',b'chunk',sleep=lambda _:None)
            self.assertEqual(remote.request.call_count,1)
        remote=Mock();remote.request.side_effect=RemoteRejected(503,b'busy')
        with self.assertRaises(RemoteRejected):
            request_when_ready(remote,'PUT','/v1/base-chunk?cursor=0',b'chunk',sleep=lambda _:None)
        self.assertEqual(remote.request.call_count,8)
    def test_dry_run_never_writes(self):
        remote = Remote()
        self.assertTrue(self.run_update(remote, dry_run=True)['dry_run'])
        self.assertEqual(remote.calls, [])
    def test_stream_and_confirmation_never_write_applications(self):
        for mode in ('normal', 'offline', 'lost_finish', 'lost_confirm'):
            with self.subTest(mode=mode):
                remote = Remote(mode)
                self.assertTrue(self.run_update(remote)['confirmed'])
                chunks = [(p,b) for _,p,b in remote.calls if p.startswith('/v1/base-chunk')]
                self.assertEqual([len(b) for _,b in chunks], [4096,4096,308])
                self.assertEqual([p for p,_ in chunks], ['/v1/base-chunk?cursor=0','/v1/base-chunk?cursor=4096','/v1/base-chunk?cursor=8192'])
                self.assertEqual(b''.join(b for _,b in chunks), PAYLOAD)
                self.assertTrue(all('/v1/base-' in p for _,p,_ in remote.calls))
                confirm = [b for _,p,b in remote.calls if p == '/v1/base-confirm']
                self.assertEqual(confirm, [bytes.fromhex('b'*64)])
    def test_unknown_chunk_never_replays_or_finishes(self):
        remote = Remote('lost_chunk')
        with self.assertRaises(OSError): self.run_update(remote)
        self.assertEqual([p for _,p,_ in remote.calls], ['/v1/base-begin','/v1/base-chunk?cursor=0','/v1/base-abort'])
    def test_rollback_not_reported_as_success(self):
        with self.assertRaisesRegex(PackageError, 'rolled back'):
            self.run_update(Remote('rollback'))
    def test_layout_fits_both_boards_without_extra_application_copies(self):
        for flash in (4,8):
            rows = [line.split(',') for line in board_partitions(dict(flash_mb=flash), ota=True).splitlines() if not line.startswith('#')]
            end = 0x9000
            for name, kind, subtype, offset, size in rows:
                offset,size = int(offset,0),int(size,0)
                self.assertGreaterEqual(offset,end)
                self.assertEqual(offset % (65536 if kind == 'app' else 4096),0)
                end = offset+size
            self.assertLessEqual(end,flash*1024*1024)
            self.assertEqual([r[0] for r in rows if r[1]=='app'], ['ota_0','ota_1'])
            self.assertEqual([r[0] for r in rows if r[2]=='0x41'], ['services'])
            self.assertEqual(next(int(r[4],0) for r in rows if r[0]=='services'),262144)
    def test_relay_encodes_chunk_offset_and_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = Registry(directory)
            worker = None
            try:
                device='0'*12
                registry.enroll(device,'test','a'*64)
                with patch('server.relay.POLL_SECONDS',0): registry.poll(device,'b'*16,BEFORE)
                worker=threading.Thread(target=registry.command, args=(device, ROUTES['PUT','/v1/base-chunk'],0,0,8192,'c'*32,bytes(4096)))
                worker.start()
                wire=registry.poll(device,'b'*16,BEFORE)
                self.assertEqual(WIRE.unpack(wire[:64])[6],8192)
                self.assertEqual(len(wire),64+4096)
                command=WIRE.unpack(wire[:64])[1].hex()
                # Production registry methods serialize access to this connection.
                # The test's inspection must use the same lock as the worker.
                with registry.changed:
                    self.assertIsNone(registry.db.execute('SELECT wire FROM commands WHERE id=?',(command,)).fetchone()[0])
                registry.result(device,command,200,b'{}')
                worker.join(timeout=2)
                self.assertFalse(worker.is_alive())
            finally:
                if worker is not None and worker.is_alive():
                    with registry.changed:
                        registry.db.execute("UPDATE commands SET state='unknown' WHERE state IN ('queued','dispatched')")
                        registry.db.commit()
                        registry.changed.notify_all()
                    worker.join(timeout=2)
                    self.assertFalse(worker.is_alive(), 'Relay test worker did not stop')
                registry.db.close()

if __name__ == '__main__': unittest.main()
