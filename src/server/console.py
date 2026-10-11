"""Browser sessions and bounded console jobs using shared operator management.

The operator's bearer token never becomes a browser cookie. Sessions are random,
short-lived and memory-only; all board operations retain the MCU deployment lease.
"""
import base64
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import re
import ssl
import threading
import time

from server.remote import RegistryRemote

SESSION_SECONDS = 8 * 60 * 60  # One operator workday; restarting the server signs out browsers.
UPLOAD_LIMIT = 24 * 1024 * 1024  # Base ELF (~9 MiB) plus up to four compiled packages, base64 encoded.

class Console:
    def __init__(self, registry):
        self.registry = registry
        self.management = registry.management
        # Local operator setting; absent or malformed configuration requires sign-in.
        try:
            settings = json.loads((registry.directory / "console.json").read_text())
        except (OSError, ValueError):
            settings = {}
        self.authentication_required = not (isinstance(settings, dict) and settings.get("require_token") is False)
        self.lock = threading.Lock()
        self.sessions, self.tickets, self.jobs = {}, {}, {}

    def ticket(self):
        with self.lock:
            self.tickets = {t:expiry for t,expiry in self.tickets.items() if expiry>time.time()}
            if len(self.tickets)>=32: raise ValueError('Too many pending sign-ins')
            ticket=secrets.token_hex(32); self.tickets[ticket]=time.time()+60
            return ticket

    def login(self, payload, admin_token):
        with self.lock:
            valid=False
            if isinstance(payload.get('ticket'), str):
                valid=self.tickets.pop(payload['ticket'],0)>time.time()
            elif isinstance(payload.get('token'), str):
                valid=hmac.compare_digest(payload['token'].encode(),admin_token.encode())
            if not valid: return None
            self.sessions={s:e for s,e in self.sessions.items() if e>time.time()}
            if len(self.sessions)>=32: return None
            session=secrets.token_hex(32); self.sessions[session]=time.time()+SESSION_SECONDS
            return session

    def authenticated(self, cookie):
        if not self.authentication_required:
            return True
        from http.cookies import SimpleCookie, CookieError
        try:
            parsed=SimpleCookie(cookie); session=parsed['micros_console'].value
        except (KeyError,ValueError,CookieError): return False
        with self.lock: return self.sessions.get(session,0)>time.time()

    def logout(self, cookie):
        from http.cookies import SimpleCookie, CookieError
        try:
            session=SimpleCookie(cookie)['micros_console'].value
            with self.lock: self.sessions.pop(session,None)
        except (KeyError,ValueError,CookieError): pass

    def submit(self, device, action, payload):
        allowed={'pause','recover','reboot','preview','deploy'}
        if action not in allowed: raise ValueError('Unknown action')
        with self.lock:
            self.jobs={k:v for k,v in self.jobs.items() if v['state']=='running' or time.time()-v['created']<3600}
            if len(self.jobs)>=128: raise ValueError('Job capacity reached; retry later')
            self.management.begin_operation(device)
            identifier=secrets.token_hex(16)
            self.jobs[identifier]=dict(id=identifier,device=device,action=action,state='running',created=time.time(),progress=[],result=None)
        threading.Thread(target=self.run,args=(identifier,device,action,payload),daemon=True).start()
        return identifier

    def job(self, identifier):
        with self.lock:
            if identifier not in self.jobs: raise ValueError('Job unavailable; inspect current board status before retrying')
            return json.loads(json.dumps(self.jobs[identifier]))

    def run(self, identifier, device, action, payload):
        def progress(phase,message):
            with self.lock:
                self.jobs[identifier]['progress'].append(dict(phase=phase,message=message))
        self.management.event(device,action,'started','Operator requested '+action)
        try:
            remote=RegistryRemote(self.registry,device)
            status=remote.status()
            if status['identity']['device_id']!=device: raise ValueError('Device identity mismatch')
            if action in ('preview','deploy'):
                result=self.release(remote,action,payload,progress)
            elif status.get('platform') in ('samd21','esp8266'):
                from micros_tooling.platforms.embedded.transport import NetworkRemote
                adapter=NetworkRemote(remote)
                adapter.platform=status['platform'];adapter.target=status['target']
                adapter.request({'pause':'STOP','recover':'RECOVER','reboot':'REBOOT'}[action])
                result=dict(message={'pause':'Application paused','recover':'Application recovered','reboot':'Reboot acknowledged; waiting for the next check-in'}[action])
                if action=='recover':
                    recovered=adapter.status()
                    if not recovered['services'] or any(s['state']!='Running' or s['result'] for s in recovered['services']):
                        raise ValueError('Application recovery not confirmed; inspect status and logs')
                    result['status']=recovered
            else:
                with remote.deployment_session(status):
                    if action=='recover':
                        selection=status['activation']
                        if selection['pending'] or selection['good'] not in (0,1): raise ValueError('No confirmed application is available for recovery')
                        remote.request('POST','/v1/activate?bank='+str(selection['good']),bytes.fromhex(selection['good_sha256']))
                        recovered=remote.status()
                        if not recovered['services'] or any(s['state']!='Running' or s['result'] for s in recovered['services']):
                            raise ValueError('Application recovery not confirmed; inspect status and logs')
                        result=dict(message='Application recovered',status=recovered)
                    else:
                        remote.request('POST','/v1/pause' if action=='pause' else '/v1/reboot')
                        result=dict(message='Application paused' if action=='pause' else 'Reboot acknowledged; waiting for the next check-in')
            with self.lock: self.jobs[identifier].update(state='complete',result=result)
            self.management.event(device,action,'complete',result.get('message','Operation completed'))
        except Exception as error:
            # Never include uploaded bytes, credentials or a raw request in job output.
            with self.lock: self.jobs[identifier].update(state='failed',error=str(error)[:1000],outcome=getattr(error,'outcome','not_confirmed'))
            self.management.event(device,action,getattr(error,'outcome','failed'),str(error))
        finally:
            self.management.end_operation(device)

    def release(self, remote, action, payload, progress):
        """Reuse the CLI's package verification, admission and transactional deployment."""
        import tempfile
        from micros_tooling.storage.bundles import release_packages
        from micros_tooling.deployment.deploy import inspect_deployment, deploy
        from micros_tooling.storage.packages import require
        files=payload.get('files',{})
        require(isinstance(files,dict) and 3<=len(files)<=7,'Choose a release folder and its paired base ELF')
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); total=0
            for name,encoded in files.items():
                require(isinstance(name,str) and (name in ('bundle.json','receipt.json','firmware.elf') or re.fullmatch('[0-9a-f]{64}\\.msp',name)), 'Unexpected release file')
                raw=base64.b64decode(encoded,validate=True); total+=len(raw)
                require(total<=16*1024*1024, 'Release upload is too large')
                (root/name).write_bytes(raw)
            firmware=root/'firmware.elf'
            packages=release_packages(root,firmware)
            inspection=inspect_deployment(remote,packages,firmware)
            self.management.remember_release(inspection)
            fingerprint=hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()
            if action=='preview':
                return dict(message='Release verified. Review before deploying.',fingerprint=fingerprint,
                    plan=inspection['plan'],unchanged=inspection['unchanged'],base_sha256=inspection['before']['identity']['base_sha256'])
            require(payload.get('reviewed')==fingerprint,'Review these exact files before deploying')
            from micros_tooling.storage.artifacts import archive_release, confirm_release
            from micros_tooling.storage.workspace import Workspace
            receipt = Workspace(root / 'archive').snapshot(packages, inspection, firmware)
            saved = Workspace(root / 'archive').snapshot_packages(receipt, firmware)
            archive_release(remote, receipt, saved, {'source': 'compiled console release',
                                                   'resolved': inspection['plan']})
            result=deploy(remote,packages,firmware,prepared=inspection,progress=progress)
            try:
                confirm_release(remote, receipt, result['status'])
            except (OSError, ValueError) as error:
                progress('archive', 'Deployment succeeded; server confirmation is pending: ' + str(error))
            result['message']='Already current' if result['unchanged'] else 'Deployment confirmed healthy'
            return result


def handle_console(handler, route):
    """Return True for console routes; never fall through into the agent API."""
    console=handler.server.console
    assets={'/':'index.html','/console':'index.html','/console/':'index.html',
            '/console/sankey.min.js':'sankey.min.js','/console/service-graph.js':'service-graph.js','/console/sankey.LICENSE.txt':'sankey.LICENSE.txt','/console/memory.js':'memory.js','/console/flash.js':'flash.js','/console/app.js':'app.js','/console/wifi.js':'wifi.js','/console/insights.js':'insights.js','/console/style.css':'style.css','/console/micros-logo.png':'micros-logo.png','/console/workbench-board.png':'workbench-board.png'}
    if route.path in assets and handler.command=='GET':
        asset=Path(__file__).parent/'web'/assets[route.path]
        mime={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.png':'image/png','.txt':'text/plain; charset=utf-8'}[asset.suffix]
        handler.send(200,asset.read_bytes(),mime)
        return True
    if not route.path.startswith('/console/'):
        return False
    cookie=handler.headers.get('Cookie','')
    if handler.command not in ('GET','POST'):
        handler.send(405,b'{"error":"method_not_allowed"}'); return True
    payload={}
    if handler.command=='POST':
        # Browser requests require a matching Origin and JSON, including sign-in.
        scheme='https' if isinstance(handler.connection,ssl.SSLSocket) else 'http'
        if handler.headers.get('Origin')!=scheme+'://'+handler.headers.get('Host','') or handler.headers.get('Content-Type','').split(';')[0]!='application/json':
            handler.send(403,b'{"error":"origin_rejected"}'); return True
        if route.path!='/console/session' and not console.authenticated(cookie):
            handler.send(401,b'{"error":"sign_in_required"}'); return True
        limit=UPLOAD_LIMIT if route.path.endswith('/action') else 4096
        length=int(handler.headers.get('Content-Length','0'))
        if not 0<length<=limit or handler.headers.get('Transfer-Encoding'):
            handler.send(413,b'{"error":"request_too_large"}'); return True
        body=handler.rfile.read(length)
        if len(body)!=length: raise ValueError('Incomplete console request')
        payload=json.loads(body)
        if not isinstance(payload,dict): raise ValueError('Expected JSON object')
    if route.path=='/console/session' and handler.command=='POST':
        session=console.login(payload,handler.server.admin_token)
        if not session:
            handler.send(401,b'{"error":"Invalid or expired sign-in"}');return True
        handler.send(200,b'{}','application/json',{'Set-Cookie':f'micros_console={session}; Path=/console; Secure; HttpOnly; SameSite=Strict; Max-Age={SESSION_SECONDS}'})
        return True
    if not console.authenticated(cookie):
        handler.send(401,b'{"error":"sign_in_required"}');return True
    result=None
    if route.path=='/console/logout' and handler.command=='POST':
        console.logout(cookie)
        handler.send(200,b'{}','application/json',{'Set-Cookie':'micros_console=; Path=/console; Secure; HttpOnly; SameSite=Strict; Max-Age=0'})
        return True
    if route.path=='/console/api/devices' and handler.command=='GET':
        result=dict(devices=[dict(device, status=console.management.decorate(device['status'], device['device_id'])) for device in handler.server.registry.devices()],server_time=time.time(),authentication_required=console.authentication_required)
    match=re.fullmatch('/console/api/devices/([0-9a-f]{12})/(history|logs|status|action|rename|revoke|wifi)',route.path)
    if match:
        device,action=match.groups()
        if action=='wifi' and handler.command in ('GET','POST'):
            from server.wifi import settings
            reported = next((entry['status'] for entry in handler.server.registry.devices()
                             if entry['device_id'] == device), None)
            result=settings(RegistryRemote(handler.server.registry,device),
                            payload if handler.command=='POST' else None, reported)
        elif action=='history' and handler.command=='GET': result=console.management.history(device)
        elif action in ('logs','status') and handler.command=='GET':
            remote=RegistryRemote(handler.server.registry,device)
            if action=='status': result=console.management.decorate(remote.status(), device)
            else:
                from urllib.parse import parse_qs
                cursor=int(parse_qs(route.query).get('cursor',['0'])[0])
                if not 0<=cursor<2**64: raise ValueError('Invalid log cursor')
                result=remote.request('GET','/v1/log-stream?cursor='+str(cursor))
        elif action=='action' and handler.command=='POST': result=dict(job=console.submit(device,payload['action'],payload))
        elif action=='rename' and handler.command=='POST':
            name=payload['name']
            if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_. -]{0,79}',name): raise ValueError('Invalid device name')
            with console.registry.changed:
                console.registry.db.execute('UPDATE devices SET name=? WHERE id=?',(name,device));console.registry.db.commit()
            console.management.event(device,'rename','complete',name);result=dict(ok=True)
        elif action=='revoke' and handler.command=='POST':
            with console.registry.changed:
                console.registry.db.execute("UPDATE devices SET token_hash='',last_seen=0,status=NULL WHERE id=?",(device,))
                console.registry.db.execute("UPDATE commands SET state='unknown',wire=NULL WHERE device=? AND state IN ('queued','dispatched')",(device,))
                console.registry.db.commit();console.registry.changed.notify_all()
            console.management.event(device,'revoke','complete','Enrollment revoked');result=dict(ok=True)
    job=re.fullmatch('/console/api/jobs/([0-9a-f]{32})',route.path)
    if job and handler.command=='GET': result=console.job(job[1])
    if route.path=='/console/api/enroll' and handler.command=='POST':
        token=payload.get('token')
        if not isinstance(token,str) or not re.fullmatch('[0-9a-f]{64}',token):
            raise ValueError('Expected a browser-generated enrollment token')
        console.registry.enroll(payload['device_id'],payload['name'],token)
        console.management.event(payload['device_id'],'enroll','complete','Device enrolled')
        result=dict(token=token,certificate=(console.registry.directory/'servercert.pem').read_text())
    if result is None: handler.send(404,b'{"error":"unknown_console_route"}')
    else: handler.send(200,json.dumps(result).encode(),'application/json')
    return True
