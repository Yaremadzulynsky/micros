"""Bounded live state/action/event router over replaceable management transport.

Configuration pins boot + exact base/graph. Restart/redeployment fences routes;
operator admission is required to reconnect a new application lifetime. No action
is silently restarted after losing the MCU's volatile execution ledger.
"""
from collections import deque
import json
import re
import secrets
import struct
import time

WIRE = struct.Struct('<4s16sBBBBQ16sI12x')
RECORD = struct.Struct('<4sBBHQQIIQQ')
KINDS = {'state': 1, 'action': 2, 'event': 3}


def require(value, reason):
    if not value:
        raise ValueError(reason)


def unpack(payload, kind, epoch, maximum):
    require(48 <= len(payload) <= 112, 'Invalid coordination record size')
    magic, actual, flags, count, generation, revision, status, reserved, ag, ar = RECORD.unpack_from(payload)
    require(magic == b'MCO1' and actual == kind and not flags and not reserved and
            generation == epoch and revision > 0 and count == len(payload)-48 and count <= maximum,
            'Invalid coordination record')
    require(status <= 5 and (kind == 2 or status == 0), 'Invalid coordination status')
    return dict(generation=generation, revision=revision, status=status,
                applied_generation=ag, applied_revision=ar, payload=payload[48:].hex())


class Coordinator:
    def __init__(self, registry):
        self.registry = registry
        self.path = registry.directory / 'coordination.json'
        self.routes = []
        self.inflight = {}
        self.previous = {}
        self.turn = {}
        self.due = {}
        self.events = deque(maxlen=128)
        self.counts = dict(exchanges=0, dropped=0, forwarded=0, rejected=0)
        if self.path.exists():
            self._install(json.loads(self.path.read_text()))

    def _install(self, routes):
        self.routes = [dict(config=r, bound=set(), records={}, deliveries={}, drops={}, blocked=None)
                       for r in routes]
        self.inflight.clear()
        self.previous.clear()
        self.due.clear()

    def configure(self, document):
        require(isinstance(document, dict) and document.keys() == {'routes'}, 'Expected routes')
        require(isinstance(document['routes'], list) and len(document['routes']) <= 8, 'At most eight routes')
        routes, endpoints, names = [], set(), set()
        for route in document['routes']:
            require(isinstance(route, dict) and route.keys() == {'name','kind','source','target','max_payload','schema','drop_first'},
                    'Invalid route fields')
            name, kind = route['name'], route['kind']
            require(isinstance(name,str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', name) and name not in names,
                    'Invalid or duplicate route name')
            names.add(name)
            require(isinstance(kind,str) and kind in KINDS and type(route['max_payload']) is int and
                    1 <= route['max_payload'] <= 64, 'Invalid kind or payload bound')
            require(isinstance(route['schema'],str) and re.fullmatch('[0-9a-f]{64}',route['schema']), 'Invalid schema identity')
            require(type(route['drop_first']) is int and 0 <= route['drop_first'] <= 100, 'Invalid drop budget')
            configured = dict(route, epoch=0)
            for side in ('source','target'):
                endpoint = route[side]
                require(isinstance(endpoint,dict) and endpoint.keys()=={'device','key','base','graph','sequence'}, 'Invalid endpoint')
                device, key = endpoint['device'], endpoint['key']
                require(isinstance(device,str) and re.fullmatch('[0-9a-f]{12}',device) and type(key) is int and
                        1 <= key <= 32 and (device,key) not in endpoints, 'Invalid or duplicate endpoint')
                endpoints.add((device,key))
                row=self.registry.db.execute("SELECT boot,status,last_seen,token_hash FROM devices WHERE id=?",(device,)).fetchone()
                require(row and row[3] and time.time()-row[2]<30, 'Endpoint offline or unenrolled')
                status=json.loads(row[1]); activation=status.get('activation',{})
                require(status.get('identity',{}).get('base_sha256')==endpoint['base'] and
                        activation.get('good_sha256')==endpoint['graph'] and activation.get('sequence')==endpoint['sequence'] and not activation.get('pending') and
                        status.get('identity',{}).get('abi_revision')==7, 'Endpoint selection mismatch or unsupported ABI')
                services=status.get('services',[])
                require(services and all(s.get('state')=='Running' for s in services), 'Endpoint services must be running')
                # Embedded status lacks publish/subscribe masks; the base bind call
                # independently enforces opened, typed, correctly directed ports.
                configured[side]=dict(endpoint, boot=row[0])
            old=next((r['config'] for r in self.routes if r['config']['name']==name),None)
            if old and kind=='action':
                changed=[any(old[side].get(k)!=configured[side].get(k) for k in ('device','boot','base','graph','sequence'))
                         for side in ('source','target')]
                require(not any(changed) or all(changed),
                        'Action recovery requires restarting both endpoint applications; do not replay an old request into a lost ledger')
            require(route['source']['device'] != route['target']['device'], 'Local bindings do not need a router')
            routes.append(configured)
        # Do not partially publish an invalid configuration.
        temporary=self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(routes,indent=2))
        temporary.replace(self.path)
        self._install(routes)
        self.registry.changed.notify_all()
        return self.status()

    def observe(self, device, boot, status):
        for route in self.routes:
            for side in ('source','target'):
                endpoint=route['config'][side]
                if endpoint['device'] != device:
                    continue
                current=status.get('activation',{})
                valid=(boot==endpoint['boot'] and status.get('identity',{}).get('base_sha256')==endpoint['base'] and
                       current.get('good_sha256')==endpoint['graph'] and current.get('sequence')==endpoint['sequence'] and not current.get('pending') and
                       status.get('services') and all(s.get('state')=='Running' for s in status['services']))
                if not valid:
                    route['blocked']='Endpoint restarted, stopped, or changed; explicit re-admission required'
                    route['records'].clear()

    def next_frame(self, device):
        now=time.monotonic()
        if now < self.due.get(device,0):
            return None
        pending=self.inflight.get(device)
        if pending and now-pending['at']<10:
            return None
        self.inflight.pop(device,None) # Never replay an individual transport operation.
        candidates=[]
        for route in self.routes:
            if route['blocked']:
                continue
            cfg=route['config']
            online=True
            for endpoint in (cfg['source'],cfg['target']):
                row=self.registry.db.execute('SELECT last_seen,token_hash FROM devices WHERE id=?',(endpoint['device'],)).fetchone()
                online=online and bool(row and row[1] and time.time()-row[0]<30)
            if not online:
                continue
            for side in ('source','target'):
                if cfg[side]['device']==device and (side=='source' or cfg['epoch']):
                    candidates.append((route,side))
        if not candidates:
            return None
        turn=self.turn.get(device,0);self.turn[device]=turn+1
        route,side=candidates[turn%len(candidates)];cfg=route['config'];key=cfg[side]['key']
        if side not in route['bound']:
            command=f'COORD B {key} {KINDS[cfg["kind"]]} {1 if side=="source" else 2} {(0 if side=="source" else cfg["epoch"]):x}'
            operation='bind'
        else:
            peer='target' if side=='source' else 'source'
            incoming=route['records'].get(peer)
            # Both endpoints must be bound before any cross-device data flows.
            eligible=len(route['bound'])==2 and incoming and time.monotonic()-incoming[1]<10
            if side=='source' and cfg['kind']!='action':
                eligible=False
            payload=incoming[0] if eligible else b''
            if payload and cfg['kind']=='event':
                if route['deliveries'].get(side)==payload:
                    payload=b''
                else:
                    route['deliveries'][side]=payload
            if payload:
                count=route['drops'].get(side,0)
                if count<cfg['drop_first']:
                    route['drops'][side]=count+1;self.counts['dropped']+=1
                    self.events.append(dict(route=cfg['name'],event='drop',to=side))
                    payload=b''
                else:
                    self.counts['forwarded']+=1
            command=f'COORD X {key} {payload.hex() if payload else "-"}'
            operation='exchange'
        body=command.encode();require(len(body)<=255,'Command exceeds platform bound')
        token=secrets.token_hex(16)
        self.inflight[device]=dict(id=token,route=route,side=side,operation=operation,at=now)
        self.due[device]=now+0.5
        return WIRE.pack(b'MRL1',bytes.fromhex(token),18,0,0,0,0,bytes(16),len(body))+body

    def accept(self, device, token, code, body):
        fingerprint=(code,body)
        previous=self.previous.get(device)
        if previous and previous[0]==token:
            require(previous[1]==fingerprint,'Conflicting coordination reply');return True
        frame=self.inflight.get(device)
        if not frame or frame['id']!=token:
            return False
        del self.inflight[device]
        self.previous[device]=(token,fingerprint)
        route,side=frame['route'],frame['side'];cfg=route['config']
        if route['blocked']:
            return True
        try:
            require(code==200,'Transport failure')
            response=json.loads(body);reply=response.get('reply',response.get('message',''))
            if frame['operation']=='bind':
                parts=reply.split()
                require(len(parts)==4 and parts[:3]==['COORD','BOUND','0'],'Base rejected binding: '+reply)
                epoch=int(parts[3],16)
                require(0 < epoch < 2**64,'Invalid source epoch')
                if side=='source':
                    require(not cfg['epoch'] or cfg['epoch']==epoch,'Source epoch changed; re-admission required')
                    cfg['epoch']=epoch
                    temporary=self.path.with_suffix('.tmp')
                    temporary.write_text(json.dumps([r['config'] for r in self.routes],indent=2))
                    temporary.replace(self.path)
                else:
                    require(epoch==cfg['epoch'],'Target epoch differs')
                route['bound'].add(side)
            else:
                require(reply.startswith('COORD DATA '),'Base rejected exchange: '+reply)
                data=bytes.fromhex(reply[11:])
                self.counts['exchanges']+=1
                if data:
                    decoded=unpack(data,KINDS[cfg['kind']],cfg['epoch'],cfg['max_payload'])
                    require((side=='source' and decoded['status']==0) or
                            (side=='target' and cfg['kind']=='action' and decoded['status']>0), 'Wrong direction')
                    old=route['records'].get(side)
                    if not old or old[0]!=data:
                        self.events.append(dict(route=cfg['name'],event='record',side=side,**decoded))
                    route['records'][side]=(data,time.monotonic())
        except (ValueError,TypeError,AttributeError) as error:
            self.counts['rejected']+=1;route['blocked']=str(error)
        self.registry.changed.notify_all()
        return True

    def status(self):
        return dict(counts=self.counts,routes=[dict(name=r['config']['name'],epoch=r['config']['epoch'],
                    bound=sorted(r['bound']),blocked=r['blocked'],drops=r['drops']) for r in self.routes],
                    events=list(self.events))
