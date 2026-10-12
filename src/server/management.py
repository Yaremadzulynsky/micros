"""Shared operator metadata, observations and per-device operation exclusion.

Owned by Registry; CLI/API operations do not require a browser session or Console.
"""
import json
import re
import threading
import time


class Management:
    def __init__(self, registry):
        from server.flash import FlashInventory
        self.registry = registry
        self.flash = FlashInventory(registry)
        self.lock = threading.Lock()
        self.active_devices = set()
        with registry.changed:
            registry.db.executescript('''
                CREATE TABLE IF NOT EXISTS release_labels(base TEXT, graph TEXT, labels TEXT, PRIMARY KEY(base,graph));
                CREATE TABLE IF NOT EXISTS observations(device TEXT, observed REAL, status TEXT);
                CREATE INDEX IF NOT EXISTS observations_device ON observations(device,observed);
                CREATE TABLE IF NOT EXISTS console_events(id INTEGER PRIMARY KEY, device TEXT, created REAL, action TEXT, outcome TEXT, detail TEXT);
            ''')
            registry.db.commit()

    def begin_operation(self, device):
        with self.lock:
            if device in self.active_devices:
                raise ValueError('An operator operation is already running for this board')
            self.active_devices.add(device)

    def end_operation(self, device):
        with self.lock:
            self.active_devices.discard(device)

    def observe(self, device, boot, status, previous_boot):
        """Called under the registry lock. Sample at 30 seconds; retain one day."""
        now = time.time()
        db = self.registry.db
        previous = db.execute('SELECT last_seen,status FROM devices WHERE id=?',(device,)).fetchone()
        if previous and previous[1]:
            old=json.loads(previous[1])
            changes=[]
            if now-(previous[0] or now)>30: changes.append('Contact restored after %.0f seconds' % (now-previous[0]))
            if old.get('activation') != status.get('activation'): changes.append('Application selection changed')
            old_health=[(item.get('state'),item.get('result')) for item in old.get('services',[])]
            new_health=[(item.get('state'),item.get('result')) for item in status.get('services',[])]
            if old_health != new_health: changes.append('Services: '+str(new_health))
            network=status.get('network',{})
            if network.get('disconnects',0)>old.get('network',{}).get('disconnects',0):
                changes.append('Wi-Fi disconnect count %s; reason %s' % (network['disconnects'],network.get('last_disconnect_reason')))
            if changes: self.event(device,'health','observed','; '.join(changes),locked=True)
        last = db.execute('SELECT MAX(observed) FROM observations WHERE device=?', (device,)).fetchone()[0]
        if last is None or now-last >= 30 or previous_boot != boot:
            db.execute('INSERT INTO observations VALUES(?,?,?)', (device, now, json.dumps(status)))
            db.execute('DELETE FROM observations WHERE observed<?', (now-86400,))
        if previous_boot and previous_boot != boot:
            self.event(device, 'boot', 'observed', 'New agent boot identity', locked=True)

    def event(self, device, action, outcome, detail, locked=False):
        def write():
            self.registry.db.execute('INSERT INTO console_events(device,created,action,outcome,detail) VALUES(?,?,?,?,?)',
                (device,time.time(),action,outcome,str(detail)[:1000]))
            self.registry.db.execute('DELETE FROM console_events WHERE id NOT IN (SELECT id FROM console_events ORDER BY id DESC LIMIT 5000)')
            self.registry.db.commit()
        if locked: write()
        else:
            with self.registry.changed: write()

    def accept_release_labels(self, receipt):
        """Accept a bounded label receipt from the authenticated, validating CLI.

        Labels are operator assertions, never device authority or resource grants.
        The board's observed hashes select the receipt; all grants remain board-reported.
        """
        from micros_tooling.storage.packages import require
        require(re.fullmatch('[0-9a-f]{64}',receipt['before']['identity']['base_sha256']), 'Invalid base hash')
        require(isinstance(receipt['banks'],dict) and 1<=len(receipt['banks'])<=2,'Invalid banks')
        for bank in receipt['banks'].values(): require(re.fullmatch('[0-9a-f]{64}',bank['digest']),'Invalid graph hash')
        plan=receipt['plan']
        require(isinstance(plan['services'],list) and len(plan['services'])<=4,'Invalid service labels')
        require(isinstance(plan['channels'],list) and len(plan['channels'])<=4,'Invalid channel labels')
        for service in plan['services']:
            for key in ('name','version'):
                require(isinstance(service[key],str) and 0<len(service[key])<=80,'Invalid service label')
            require(type(service['permissions']['publish_mask']) is int,'Invalid ordering')
        for channel in plan['channels']:
            require(type(channel['key']) is int and 1<=channel['key']<=32,'Invalid channel key')
            require(isinstance(channel['name'],str) and 0<len(channel['name'])<=80,'Invalid channel label')
        from micros_tooling.communication.channel_metadata import validate_bindings
        validate_bindings(plan.get('channel_ports', []))
        from micros_tooling.commands.metadata import validate_bindings as validate_commands
        validate_commands(plan.get('service_commands', []))
        self.remember_release(receipt)

    def remember_release(self, inspection):
        """Keep labels only, bound to the validated base and exact graph hashes.

        Runtime status uses graph record order, which prepare sorts subscribers first.
        No ELF, package bytes or configuration values are retained here.
        """
        ordered=sorted(inspection['plan']['services'],key=lambda service:(bool(service['permissions']['publish_mask']),service['name']))
        labels=dict(services=[dict(name=s['name'],version=s['version']) for s in ordered],
                    channels=[dict(key=c['key'],name=c['name']) for c in inspection['plan']['channels']])
        labels['channel_ports'] = inspection['plan'].get('channel_ports', [])
        labels['service_commands'] = inspection['plan'].get('service_commands', [])
        with self.registry.changed:
            # The board identifies image/graph bytes, not a host package hash.
            # Do not silently change command meaning for an indistinguishable graph.
            from micros_tooling.storage.packages import require
            for bank in inspection['banks'].values():
                previous = self.registry.db.execute('SELECT labels FROM release_labels WHERE base=? AND graph=?',
                    (inspection['before']['identity']['base_sha256'], bank['digest'])).fetchone()
                old_commands = json.loads(previous[0]).get('service_commands', []) if previous else []
                if old_commands and labels['service_commands']:
                    require([{k:v for k,v in b.items() if k!='version'} for b in old_commands] ==
                            [{k:v for k,v in b.items() if k!='version'} for b in labels['service_commands']],
                            'Commands conflict for identical board bytes')
                elif old_commands:
                    labels['service_commands'] = old_commands
                old = json.loads(previous[0]).get('channel_ports', []) if previous else []
                def semantics(ports):
                    return [{k:v for k,v in binding.items() if k != 'version'} for binding in ports]
                if old and labels['channel_ports']:
                    require(semantics(old) == semantics(labels['channel_ports']),
                            'Channel schemas conflict for identical board bytes; change the application graph before changing an existing port')
                elif old:
                    labels['channel_ports'] = old  # Older clients only register labels.
            for bank in inspection['banks'].values():
                self.registry.db.execute('INSERT OR REPLACE INTO release_labels VALUES(?,?,?)',
                    (inspection['before']['identity']['base_sha256'],bank['digest'],json.dumps(labels)))
            self.registry.db.commit()

    def decorate(self, status, device=None):
        if not status: return status
        status=json.loads(json.dumps(status))
        from server.flow import remote_connections
        with self.registry.changed:
            status['remote_connections'] = remote_connections(
                self.registry, device or status.get('identity', {}).get('device_id'), status)
        flash = self.flash.describe(status)
        if flash is not None:
            status['flash'] = flash
        # During a trial, the confirmed hash describes the previous release.
        if status.get('activation',{}).get('pending'): return status
        with self.registry.changed:
            row=self.registry.db.execute('SELECT labels FROM release_labels WHERE base=? AND graph=?',
                (status.get('identity',{}).get('base_sha256'),status.get('activation',{}).get('good_sha256'))).fetchone()
        if row:
            labels=json.loads(row[0])
            if len(labels['services'])==len(status.get('services',[])):
                for service,label in zip(status['services'],labels['services']): service.update(label)
                status['labels_source']='verified_release'
                status['channel_ports']=labels.get('channel_ports', [])
                status['service_commands']=labels.get('service_commands', [])
            for channel in status.get('channels',[]):
                match=next((item for item in labels['channels'] if item['key']==channel['key']),None)
                if match: channel['name']=match['name']
        # Apply newly matched names to the compact embedded flash inventory too.
        from micros_tooling.platforms.embedded.telemetry import expand
        return expand(status)

    def history(self, device):
        with self.registry.changed:
            samples = self.registry.db.execute('SELECT observed,status FROM observations WHERE device=? AND observed>? ORDER BY observed', (device,time.time()-86400)).fetchall()
            events = self.registry.db.execute('SELECT created,action,outcome,detail FROM console_events WHERE device=? ORDER BY id DESC LIMIT 50', (device,)).fetchall()
        return dict(samples=[dict(time=t,heap=s.get('heap'),uptime_us=s.get('uptime_us'),services=len(s.get('services',[])),rssi_dbm=s.get('network',{}).get('rssi_dbm'),internal_min=s.get('memory',{}).get('internal_min')) for t,raw in samples for s in [json.loads(raw)]],
                    events=[dict(time=t,action=a,outcome=o,detail=d) for t,a,o,d in events])
