"""Demand-driven relay batches and bounded fan-out; sample bytes never enter SQLite.

All state is protected by Registry.changed. A single relay connection drains a
port for all browser readers. Each reader has its own replay cursor and lease.
"""
from collections import deque
import hashlib
import json
import secrets
import struct
import time
from micros_tooling.storage.packages import require

MAX_STREAMS = 16
MAX_READERS = 8  # Leave connection slots available for agents and management.
RING_RECORDS = 256
READER_SECONDS = 30
READ_SECONDS = 10
BATCH_MESSAGES = 8
WIRE = struct.Struct('<4s16sBBBBQ16sI12x')


class Streams:
    def __init__(self, registry):
        self.registry = registry
        self.ports = {}
        self.readers = {}
        self.inflight = {}
        self.acknowledged = {}  # One previous frame/device, for a lost HTTP reply.
        self.round_robin = {}

    def prune(self):
        now = time.monotonic()
        for token in list(self.readers):
            if self.readers[token]['expires'] <= now:
                del self.readers[token]
        used = {r['port'] for r in self.readers.values()}
        self.ports = {key:p for key,p in self.ports.items() if key in used}
        for device, frame in list(self.inflight.items()):
            if frame['port'] not in self.ports:
                del self.inflight[device]
        # Device-scoped retry/demand metadata is bounded along with the streams.
        devices = {key[0] for key in self.ports}
        self.acknowledged = {d:v for d,v in self.acknowledged.items() if d in devices}
        self.round_robin = {d:v for d,v in self.round_robin.items() if d in devices}

    def open(self, device, boot, status, binding):
        self.prune()
        require(len(self.readers) < MAX_READERS, 'Too many stream readers')
        activation = status['activation']
        key = (device, boot, status['identity']['base_sha256'], activation['good_sha256'],
               activation['sequence'], binding['instance'], binding['port']['key'])
        if key not in self.ports:
            require(len(self.ports) < MAX_STREAMS, 'Stream capacity reached')
            self.ports[key] = dict(records=deque(maxlen=RING_RECORDS), cursor=0, error=None, interval_ms=50)
        port = self.ports[key]
        require(not port['error'], port['error'] or '')
        from micros_tooling.communication.protobuf import message_class
        token = secrets.token_hex(16)
        self.readers[token] = dict(device=device, port=key, expires=time.monotonic()+READER_SECONDS,
                                   binding=binding, decoder=message_class(binding['port']['descriptor']), reading=False)
        self.registry.changed.notify_all()
        return dict(reader=token, cursor=port['cursor'], protocol=1)

    def close(self, device, token):
        reader = self.readers.get(token)
        if reader:
            require(reader['device'] == device, 'Stream reader belongs to another board')
            del self.readers[token]
        self.prune()
        self.registry.changed.notify_all()
        return dict(closed=True)

    def observe(self, device, boot, status):
        activation = status.get('activation', {})
        for key, port in self.ports.items():
            if key[0] != device: continue
            valid = (key[1] == boot and key[2] == status.get('identity', {}).get('base_sha256')
                     and key[3] == activation.get('good_sha256') and key[4] == activation.get('sequence')
                     and not activation.get('pending') and status.get('ipc_stream') == 1
                     and key[5] < len(status.get('services', []))
                     and status['services'][key[5]].get('state') == 'Running')
            if not valid: port['error'] = 'Board restarted or application changed; reopen capture'
        self.registry.changed.notify_all()

    def invalidate(self, device, reason):
        for key, port in self.ports.items():
            if key[0] == device: port['error'] = reason
        self.inflight.pop(device, None)
        self.registry.changed.notify_all()

    def next_frame(self, device):
        self.prune()
        if device in self.inflight:
            return self.inflight[device]['wire']
        choices = [key for key,p in self.ports.items() if key[0] == device and not p['error']]
        if not choices: return None
        turn = self.round_robin.get(device, 0)
        key = choices[turn % len(choices)]
        self.round_robin[device] = turn+1
        token = secrets.token_hex(16)
        command = f'IPC DRAIN {key[5]} {key[6]} {key[4]} {key[3]}'.encode()
        wire = WIRE.pack(b'MRS1', bytes.fromhex(token), 18, 0, 0, 0, self.ports[key]['interval_ms'], bytes(16), len(command)) + command
        self.inflight[device] = dict(id=token, port=key, wire=wire)
        return wire

    def accept(self, device, boot, packet):
        require(isinstance(packet, dict) and packet.keys() == {'id','batch'}, 'Invalid stream envelope')
        require(isinstance(packet['id'],str) and len(packet['id']) == 32, 'Invalid stream frame ID')
        fingerprint = hashlib.sha256(json.dumps(packet,sort_keys=True).encode()).digest()
        previous = self.acknowledged.get(device)
        if previous and previous[0] == packet['id']:
            require(previous[1] == fingerprint, 'Conflicting stream retransmission')
            return
        frame = self.inflight.get(device)
        # Expired readers/server restart may leave a last batch in flight. Discard
        # it; never turn an unsolicited agent payload into a new subscription.
        if not frame or frame['id'] != packet['id']: return
        require(frame['port'][1] == boot, 'Stream boot identity mismatch')
        batch = packet['batch']
        require(isinstance(batch,dict) and batch.keys() == {'events','error'}, 'Invalid stream batch')
        require(type(batch['error']) is int and -100 <= batch['error'] <= 0, 'Invalid stream error')
        require(isinstance(batch['events'],list) and len(batch['events']) <= BATCH_MESSAGES, 'Oversized stream batch')
        records = []
        for value in batch['events']:
            require(isinstance(value,dict), 'Invalid stream event')
            if value.keys() == {'missed'}:
                require(type(value['missed']) is int and 0 < value['missed'] < 2**64, 'Invalid loss count')
                records.append(dict(state='gap',missed=value['missed'],source='device'))
            else:
                require(value.keys() == {'data'} and isinstance(value['data'],str)
                        and len(value['data']) <= 512 and len(value['data'])%2 == 0
                        and all(c in '0123456789abcdef' for c in value['data']), 'Invalid stream payload')
                records.append(dict(state='sample',payload=bytes.fromhex(value['data'])))
        port = self.ports.get(frame['port'])
        if port and not port['error']:
            port['interval_ms'] = 50 if records else min(500, port['interval_ms']*2)
            if batch['error']:
                port['error'] = 'Stream interrupted by management or a changed application; reopen capture'
            else:
                for record in records:
                    port['cursor'] += 1
                    port['records'].append((port['cursor'],record))
        self.acknowledged[device] = (packet['id'],fingerprint)
        del self.inflight[device]
        self.registry.changed.notify_all()

    def read(self, device, token, cursor):
        require(type(cursor) is int and cursor >= 0, 'Invalid stream cursor')
        self.prune()
        reader = self.readers.get(token)
        require(reader is not None and reader['device'] == device, 'Stream expired; reopen capture')
        require(not reader['reading'], 'This stream reader already has a pending read')
        reader['reading'] = True
        try:
            deadline = time.monotonic()+READ_SECONDS
            reader['expires'] = time.monotonic()+READER_SECONDS
            while True:
                require(token in self.readers, 'Capture closed')
                port = self.ports[reader['port']]
                require(not port['error'], port['error'] or '')
                require(cursor <= port['cursor'], 'Stream cursor is ahead of this capture')
                row = self.registry.db.execute("SELECT last_seen,token_hash FROM devices WHERE id=?",(device,)).fetchone()
                require(row and row[1] and time.time()-row[0] < 30, 'Board offline; reopen capture after it reconnects')
                if port['cursor'] > cursor or time.monotonic() >= deadline: break
                self.registry.changed.wait(min(1, deadline-time.monotonic()))
            events=[]
            oldest = port['records'][0][0] if port['records'] else port['cursor']+1
            if cursor < oldest-1:
                events.append(dict(state='gap',missed=oldest-1-cursor,source='viewer'))
                cursor=oldest-1
            from google.protobuf.json_format import MessageToDict
            from google.protobuf.message import DecodeError
            for position, record in list(port['records']):
                if position <= cursor: continue
                if record['state']=='sample':
                    raw=record['payload']
                    require(len(raw)<=reader['binding']['max_payload'], 'Stream exceeded the channel payload bound')
                    try: message=reader['decoder'].FromString(raw)
                    except DecodeError as error: raise ValueError('Malformed protobuf in stream') from error
                    events.append(dict(state='sample',sample=MessageToDict(message,preserving_proto_field_name=True,
                                       including_default_value_fields=True)))
                else: events.append(record)
                cursor=position
                if len(events)>=64: break
            return dict(events=events,cursor=cursor)
        finally:
            reader['reading']=False
