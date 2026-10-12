"""Bounded HTTPS device registry, outbound command relay and operator console."""

import argparse
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import sqlite3
import ssl
import struct
import threading
import time
from urllib.parse import urlsplit, parse_qs
from server.remote import ROUTES

# One native image plus relay metadata fits below 16 KiB; statuses/logs fit 4 KiB.
BODY_LIMIT = 16384
RESPONSE_LIMIT = 4096
# Allow six normal poll intervals before marking a board unavailable.
ONLINE_SECONDS = 30
# Bound operator waiting across four polls; expiry is uncertain, never a replay.
COMMAND_SECONDS = 20
# Long polls wake immediately for work and otherwise refresh presence every five seconds.
POLL_SECONDS = 5
WIRE = struct.Struct('<4s16sBBBBQ16sI12x')


class Registry:
    """Persist identity, last observation and outcomes; never replay a dispatched mutation."""
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.changed = threading.Condition()
        self.started = time.time()
        from server.streams import Streams
        self.streams = Streams(self)
        self.base_images = {}  # Ephemeral, device-scoped SAMD base downloads (maximum 16).
        self.private_wires = {}  # Wi-Fi passwords are never written to SQLite or its WAL.
        self.db = sqlite3.connect(self.directory / 'registry.sqlite', check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY, name TEXT, token_hash TEXT,
                last_seen REAL DEFAULT 0, boot TEXT, status TEXT);
            CREATE TABLE IF NOT EXISTS commands(id TEXT PRIMARY KEY, device TEXT, created REAL,
                state TEXT, wire BLOB, code INTEGER, response BLOB);
        ''')
        if 'private' not in {row[1] for row in self.db.execute('PRAGMA table_info(commands)')}:
            self.db.execute('ALTER TABLE commands ADD COLUMN private INTEGER NOT NULL DEFAULT 0')
        # In-flight work from the previous process has an unknown outcome, never replay it.
        self.db.execute("UPDATE commands SET state='unknown', wire=NULL WHERE state IN ('queued','dispatched')")
        self.db.commit()
        from server.coordination import Coordinator
        self.coordination = Coordinator(self)
        from server.management import Management
        self.management = Management(self)

    def base_image_limit(self, device):
        with self.changed:
            row = self.db.execute("SELECT status FROM devices WHERE id=? AND token_hash!=''", (device,)).fetchone()
            status = json.loads(row[0]) if row and row[0] else {}
            return 720896 if status.get('platform') == 'esp8266' else 81920

    def base_image(self, device, digest, body=None):
        with self.changed:
            now = time.monotonic()
            self.base_images = {key: value for key, value in self.base_images.items() if value[0] > now}
            if body is not None:
                if not 256 <= len(body) <= self.base_image_limit(device) or len(body) % 4 or hashlib.sha256(body).hexdigest() != digest:
                    raise ValueError('Invalid base image')
                if not self.db.execute("SELECT 1 FROM devices WHERE id=? AND token_hash!=''", (device,)).fetchone():
                    raise ValueError('Device is not enrolled')
                if device not in self.base_images and len(self.base_images) >= 16:
                    raise ValueError('Base image capacity reached')
                self.base_images[device] = (now + 600, digest, body)
                return b'{}'
            value = self.base_images.get(device)
            return value[2] if value and value[1] == digest else None

    def enroll(self, device, name, token):
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_. -]{0,79}', name):
            raise ValueError('Use a printable enrollment name with letters, digits, spaces, dots, underscores or hyphens')
        if not re.fullmatch('[0-9a-f]{12}', device):
            raise ValueError('Device ID must be its 12 lowercase hexadecimal MAC digits')
        with self.changed:
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            existing = self.db.execute("SELECT name,token_hash FROM devices WHERE id=? AND token_hash!=''", (device,)).fetchone()
            if existing:
                if existing == (name, token_hash):
                    return  # An interrupted operator request can safely retry its saved token.
                raise ValueError('Device already enrolled; preserve its token instead of replacing it')
            self.db.execute('INSERT OR REPLACE INTO devices(id,name,token_hash) VALUES(?,?,?)',
                            (device, name, hashlib.sha256(token.encode()).hexdigest()))
            self.db.commit()

    def authorized(self, device, token):
        with self.changed:
            row = self.db.execute('SELECT token_hash FROM devices WHERE id=?', (device,)).fetchone()
        return bool(row and hmac.compare_digest(row[0], hashlib.sha256(token.encode()).hexdigest()))

    def devices(self):
        with self.changed:
            rows = self.db.execute("SELECT id,name,last_seen,status FROM devices WHERE token_hash!='' ORDER BY name,id").fetchall()
        return [dict(device_id=i, name=n, online=seen >= self.started and time.time()-seen < ONLINE_SECONDS,
                     last_seen=seen or None, status=json.loads(status) if status else None)
                for i,n,seen,status in rows]

    def poll(self, device, boot, status):
        packet = None
        if isinstance(status,dict) and 'stream' in status:
            if status.keys() - {'stream','status'}: raise ValueError('Invalid streaming poll')
            packet, status = status['stream'], status.get('status')
        if not re.fullmatch('[0-9a-f]{16}', boot): raise ValueError('Agent boot identity mismatch')
        if status is not None and (not isinstance(status, dict) or len(json.dumps(status).encode()) > RESPONSE_LIMIT
                or not isinstance(status.get('identity'), dict) or status['identity'].get('device_id') != device):
            raise ValueError('Agent identity mismatch')
        if status is None and packet is None: raise ValueError('Missing agent status')
        with self.changed:
            row = self.db.execute("SELECT boot,token_hash FROM devices WHERE id=?", (device,)).fetchone()
            if not row or not row[1]: raise ValueError('Device is not enrolled')
            previous = row[0]
            if status is None and previous != boot: raise ValueError('Send a status heartbeat after reboot')
            if status is not None:
                if previous and previous != boot:
                    self.db.execute("UPDATE commands SET state='unknown',wire=NULL WHERE device=? AND state IN ('queued','dispatched')", (device,))
                self.management.observe(device, boot, status, previous)
                self.db.execute('UPDATE devices SET last_seen=?,boot=?,status=? WHERE id=?',
                                (time.time(), boot, json.dumps(status), device))
                self.db.commit()
                self.streams.observe(device, boot, status)
                self.coordination.observe(device, boot, status)
            if packet is not None:
                self.streams.accept(device, boot, packet)
            self.changed.notify_all()
            deadline = time.monotonic() + POLL_SECONDS
            while True:
                authorized = self.db.execute("SELECT token_hash FROM devices WHERE id=?",(device,)).fetchone()
                if not authorized or not authorized[0]:
                    self.streams.invalidate(device, 'Enrollment revoked')
                    raise ValueError('Device is not enrolled')
                row = self.db.execute("SELECT id,wire FROM commands WHERE device=? AND state='queued' AND created>? ORDER BY created LIMIT 1",
                                      (device, time.time()-COMMAND_SECONDS)).fetchone()
                if row:
                    self.db.execute("UPDATE commands SET state='dispatched' WHERE id=?", (row[0],))
                    self.db.commit()
                    return self.private_wires.pop(row[0], row[1])
                # Never issue a drain concurrently with a dispatched management
                # operation. Ordinary commands always take priority over telemetry.
                busy = self.db.execute("SELECT 1 FROM commands WHERE device=? AND state='dispatched' AND created>?",
                                       (device,time.time()-COMMAND_SECONDS)).fetchone()
                if not busy:
                    frame = self.coordination.next_frame(device)
                    if frame: return frame
                    frame = self.streams.next_frame(device)
                    if frame: return frame
                remaining = deadline-time.monotonic()
                if remaining <= 0: return b''
                self.changed.wait(min(remaining, 0.5))

    def result(self, device, command, code, body):
        with self.changed:
            if self.coordination.accept(device, command, code, body):
                return
            row = self.db.execute('SELECT device,state,code,response,private FROM commands WHERE id=?', (command,)).fetchone()
            if not row or row[0] != device:
                raise ValueError('Unknown command')
            if row[4] == 1:
                body = b'{"ok":true}' if code == 200 else b'{"error":"Wi-Fi settings were not confirmed saved"}'
            if row[1] == 'done':
                if row[2:4] != (code, body):
                    raise ValueError('Conflicting duplicate result')
                return
            if row[1] not in ('dispatched', 'unknown'):
                raise ValueError('Command was not dispatched')
            self.db.execute("UPDATE commands SET state='done',code=?,response=?,wire=NULL WHERE id=?", (code, body, command))
            self.db.commit()
            self.changed.notify_all()

    def command(self, device, operation, bank, slot, cursor, session, body):
        with self.changed:
            row = self.db.execute('SELECT last_seen FROM devices WHERE id=?', (device,)).fetchone()
            if not row or row[0] < self.started or time.time()-row[0] >= ONLINE_SECONDS:
                return 503, b'{"error":"device_offline"}'
            # Timed-out commands become uncertain; admission leases on the MCU remain authoritative.
            self.db.execute("UPDATE commands SET state='unknown',wire=NULL WHERE state IN ('queued','dispatched') AND created<?", (time.time()-COMMAND_SECONDS,))
            deadline = time.monotonic() + COMMAND_SECONDS
            # A log follower must not make an unrelated deployment fail. Serialize
            # callers within the same total request deadline; MCU leases still own writes.
            while self.db.execute("SELECT 1 FROM commands WHERE device=? AND state IN ('queued','dispatched')", (device,)).fetchone():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return 503, b'{"error":"device_busy"}'
                self.changed.wait(remaining)
            command = secrets.token_hex(16)
            wire = WIRE.pack(b'MRL1', bytes.fromhex(command), operation, bank, slot, 0,
                             cursor, bytes.fromhex(session or '0'*32), len(body)) + body
            private = 2 if operation == 18 else int(operation in (12, 14))
            if private: self.private_wires[command] = wire
            self.db.execute('INSERT INTO commands(id,device,created,state,wire,code,response,private) VALUES(?,?,?,?,?,?,?,?)',
                            (command, device, time.time(), 'queued', None if private else wire, None, None, int(private)))
            # Keep recent audit outcomes, not unbounded response bodies or uploaded packages.
            self.db.execute("DELETE FROM commands WHERE created<? AND state IN ('done','unknown')", (time.time()-7*86400,))
            self.db.commit()
            self.changed.notify_all()
            while True:
                state, code, response = self.db.execute('SELECT state,code,response FROM commands WHERE id=?', (command,)).fetchone()
                if state == 'done':
                    self.private_wires.pop(command, None)
                    return code, response
                if state == 'unknown' or time.monotonic() >= deadline:
                    self.private_wires.pop(command, None)
                    self.db.execute("UPDATE commands SET state='unknown',wire=NULL WHERE id=?", (command,))
                    self.db.commit()
                    self.changed.notify_all()
                    return 504, json.dumps(dict(error='outcome_unknown', command_id=command,
                        next_action='Inspect device status; do not blindly retry a mutation')).encode()
                self.changed.wait(deadline-time.monotonic())


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass  # Avoid credential/query/body logging; registry retains command outcomes.

    def send(self, code, body, content_type="application/octet-stream", headers=None):
        # Log failures without tokens, bodies or caller-controlled URLs.
        if code >= 400:
            print(json.dumps(dict(event='request_failed', status=code)), flush=True)
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        for name,value in (headers or {}).items():
            self.send_header(name,value)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        if code >= 400:
            self.send_header('Connection', 'close')
            self.close_connection = True
        self.end_headers()
        self.wfile.write(body)

    def handle_request(self):
        try:
            route = urlsplit(self.path)
            agent = re.fullmatch(r'/agent/([0-9a-f]{12})/(poll|result/([0-9a-f]{32})|base/([0-9a-f]{64}))', route.path)
            # A separate public listener must never expose operator routes, even
            # with an operator token, forged Host header, or console auth disabled.
            agent_method = bool(agent) and self.command == ('GET' if agent[4] else 'POST')
            upload = re.fullmatch(r'/devices/([0-9a-f]{12})/v1/base-image/([0-9a-f]{64})', route.path)
            if self.server.agent_only and (not agent_method
                    or route.query or route.fragment or self.path != route.path):
                return self.send(404, b'{"error":"unknown_route"}')
            from server.console import handle_console
            if not self.server.agent_only and handle_console(self, route):
                return
            authorization = self.headers.get('Authorization', '')
            if not authorization.startswith('Bearer '):
                return self.send(401, b'{"error":"unauthorized"}')
            token = authorization[7:]
            if agent:
                allowed = self.server.registry.authorized(agent[1], token)
            else:
                allowed = hmac.compare_digest(token, self.server.admin_token)
            if not allowed:
                return self.send(401, b'{"error":"unauthorized"}')
            length = int(self.headers.get('Content-Length', '0'))
            from micros_tooling.storage.artifacts import LIMIT as ARTIFACT_LIMIT
            limit = self.server.registry.base_image_limit(upload[1]) if upload and not agent else ARTIFACT_LIMIT if not agent and route.path.startswith('/v1/artifacts/') else 256 * 1024 if not agent and route.path == '/v1/release-labels' else BODY_LIMIT
            if not 0 <= length <= limit or self.headers.get('Transfer-Encoding'):
                return self.send(413, b'{"error":"body_too_large"}')
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError('Incomplete body')
            if not agent and route.path == '/v1/coordination' and not route.query:
                with self.server.registry.changed:
                    if self.command == 'POST':
                        result = self.server.registry.coordination.configure(json.loads(body))
                    elif self.command == 'GET':
                        result = self.server.registry.coordination.status()
                    else:
                        return self.send(405,b'{}')
                return self.send(200,json.dumps(result).encode())
            if agent and agent[4]:
                if not agent_method or length or route.query or route.fragment:
                    return self.send(404, b'{"error":"unknown_route"}')
                image = self.server.registry.base_image(agent[1], agent[4])
                if image is None:
                    return self.send(404, b'{"error":"image_unavailable"}')
                requested = self.headers.get('Range', '')
                if requested:
                    match = re.fullmatch(r'bytes=(\d+)-(\d+)', requested)
                    if not match:
                        return self.send(416, b'{"error":"invalid_range"}')
                    start, end = map(int, match.groups())
                    if not 0 <= start <= end < len(image) or end - start + 1 > 4096:
                        return self.send(416, b'{"error":"invalid_range"}')
                    return self.send(206, image[start:end + 1], headers={
                        'Content-Range': f'bytes {start}-{end}/{len(image)}', 'Accept-Ranges': 'bytes'})
                return self.send(200, image)
            if upload and self.command == 'POST' and not route.query and not route.fragment:
                return self.send(200, self.server.registry.base_image(upload[1], upload[2], body))
            if agent and self.command == 'POST':
                limit = 8192 if agent[2] == 'poll' else RESPONSE_LIMIT
                if len(body) > limit:
                    raise ValueError('Agent response too large')
                if agent[2] == 'poll':
                    from micros_tooling.platforms.embedded.telemetry import expand
                    status = expand(json.loads(body))
                    reply = self.server.registry.poll(agent[1], self.headers.get('X-Micros-Boot', ''), status)
                    return self.send(200 if reply else 204, reply)
                code = int(self.headers.get('X-Micros-Result', '0'))
                if code not in (200, 400, 409, 503):
                    raise ValueError('Invalid result status')
                if body.startswith(b'{'):
                    from micros_tooling.platforms.embedded.telemetry import expand
                    parsed = json.loads(body)
                    if parsed.get("samd_telemetry") == 1 or parsed.get("embedded_telemetry") == 1 or parsed.get("embedded_layout") == 1:
                        body = json.dumps(expand(parsed)).encode()
                self.server.registry.result(agent[1], agent[3], code, body)
                return self.send(200, b'{}')
            if not agent and route.path.startswith('/v1/artifacts/'):
                code, reply = self.server.artifacts.handle(self.command, route.path, body)
                return self.send(code, reply)
            if not agent and self.command == 'POST' and route.path == '/v1/release-labels':
                receipt=json.loads(body)
                self.server.registry.management.accept_release_labels(receipt)
                return self.send(200,b'{}')
            if not agent and self.command == 'POST' and route.path == '/v1/console-ticket':
                return self.send(200, json.dumps(dict(ticket=self.server.console.ticket())).encode())
            if not agent and self.command == 'GET' and route.path == '/v1/devices':
                return self.send(200, json.dumps(dict(devices=self.server.registry.devices())).encode())
            inspection = re.fullmatch(r'/v1/inspect/([0-9a-f]{12})', route.path)
            if not agent and self.command == 'GET' and inspection and not route.query and not body:
                from server.remote import RegistryRemote
                observed = RegistryRemote(self.server.registry, inspection[1]).status()
                result = self.server.registry.management.decorate(observed, inspection[1])
                return self.send(200, json.dumps(result).encode())
            command = re.fullmatch(r'/v1/commands/([0-9a-f]{12})', route.path)
            if not agent and self.command == 'POST' and command and not route.query:
                from server.commands import operate
                result = operate(self.server.registry.management, command[1], json.loads(body))
                return self.send(200, json.dumps(result).encode())
            stream = re.fullmatch(r'/v1/streams/([0-9a-f]{12})', route.path)
            if not agent and self.command == 'POST' and stream and not route.query:
                # Operators and LLM clients share the shared channel drain,
                # leases, generation checks and per-reader loss accounting.
                from server.channel_streams import stream_operation
                result = stream_operation(self.server.registry.management, stream[1], json.loads(body))
                return self.send(200, json.dumps(result).encode())
            if not agent and self.command == 'POST' and route.path == '/v1/enroll':
                enrollment = json.loads(body)
                if not re.fullmatch('[0-9a-f]{64}', enrollment['token']) or not isinstance(enrollment['name'], str) or len(enrollment['name']) > 80:
                    raise ValueError('Invalid enrollment')
                self.server.registry.enroll(enrollment['device_id'], enrollment['name'], enrollment['token'])
                return self.send(200, b'{}')
            if not agent and self.command == 'POST' and route.path == '/v1/revoke':
                device = json.loads(body)['device_id']
                with self.server.registry.changed:
                    self.server.registry.db.execute("UPDATE devices SET token_hash='',last_seen=0,status=NULL WHERE id=?", (device,))
                    self.server.registry.db.execute("UPDATE commands SET state='unknown',wire=NULL WHERE device=? AND state IN ('queued','dispatched')", (device,))
                    self.server.registry.db.commit()
                    self.server.registry.changed.notify_all()
                return self.send(200,b'{}')
            match = re.fullmatch(r'/devices/([0-9a-f]{12})(/v1/[a-z-]+)', route.path)
            if agent or not match or (self.command, match[2]) not in ROUTES:
                return self.send(404, b'{"error":"unknown_route"}')
            operation = ROUTES[self.command, match[2]]
            query = parse_qs(route.query, strict_parsing=True) if route.query else {}
            expected = {'bank','slot'} if operation == 2 else {'bank'} if operation in (3,4) else {'cursor'} if operation in (7,14) else set()
            if set(query) != expected or any(len(v) != 1 for v in query.values()):
                raise ValueError('Invalid query')
            bank, slot, cursor = (int(query.get(key, ['0'])[0]) for key in ('bank','slot','cursor'))
            if not 0 <= bank < 2 or not 0 <= slot < 4 or not 0 <= cursor < 2**64:
                raise ValueError('Invalid bank, slot or cursor')
            maximum = {2:BODY_LIMIT, 3:1456, 4:32, 8:36, 12:404, 13:40, 14:4096, 16:32, 18:599}.get(operation,0)
            if len(body)>maximum:
                raise ValueError('Operation body too large')
            session = self.headers.get('X-Micros-Session', '')
            if session and not re.fullmatch('[0-9a-f]{32}', session):
                raise ValueError('Invalid session')
            code, reply = self.server.registry.command(match[1], operation, bank, slot, cursor, session, body)
            return self.send(code, reply)
        except (ValueError, KeyError, TypeError) as error:
            from micros_tooling.communication.remote import RemoteRejected
            if isinstance(error, RemoteRejected):
                self.send(error.status, json.dumps(dict(error=str(error),outcome=getattr(error,"outcome","not_confirmed"))).encode())
                return
            self.send(400, json.dumps(dict(error=str(error) if route.path.startswith(('/console/', '/v1/artifacts/', '/v1/inspect/', '/v1/commands/')) and isinstance(error, ValueError) else 'invalid_request')).encode())
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            self.close_connection = True

    do_GET = do_POST = do_PUT = do_DELETE = handle_request


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # Bound pending long polls plus operators; suitable for the initial small fleet.
    def __init__(self, address, registry, admin_token, *, agent_only=False):
        if not re.fullmatch('[0-9a-f]{64}', admin_token):
            raise ValueError('Invalid operator token')
        super().__init__(address, Handler)
        self.registry, self.admin_token = registry, admin_token
        self.agent_only = agent_only
        if not agent_only:
            from server.artifacts import Artifacts
            self.artifacts = Artifacts(registry)
            from server.console import Console
            self.console = Console(registry)
        self.slots = threading.BoundedSemaphore(32)

    def process_request(self, request, address):
        if not self.slots.acquire(False):
            request.close()
            return
        request.settimeout(25)
        super().process_request(request, address)

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, default=Path('/state'))
    parser.add_argument('--port', type=int, default=8443)
    parser.add_argument('--agent-port', type=int, help='additional HTTPS port exposing only device poll/result endpoints')
    args = parser.parse_args()
    if args.agent_port is not None and (not 1 <= args.agent_port <= 65535 or args.agent_port == args.port):
        parser.error('--agent-port must be a distinct port from 1 through 65535')
    server = Server(('0.0.0.0', args.port), Registry(args.state), (args.state/'admin.token').read_text().strip())
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(args.state/'servercert.pem', args.state/'prvtkey.pem')
    server.socket = context.wrap_socket(server.socket, server_side=True, do_handshake_on_connect=False)
    if args.agent_port is not None:
        agents = Server(('0.0.0.0', args.agent_port), server.registry, server.admin_token, agent_only=True)
        agents.socket = context.wrap_socket(agents.socket, server_side=True, do_handshake_on_connect=False)
        threading.Thread(target=agents.serve_forever, daemon=True).start()
    server.serve_forever()


if __name__ == '__main__':
    main()
