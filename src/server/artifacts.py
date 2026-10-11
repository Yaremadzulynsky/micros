"""Operator-only persistent base and release artifacts, committed atomically in SQLite."""
import json
import re
from datetime import datetime, timezone
from micros_tooling.storage.artifacts import LIMIT, unpack, validate_base, validate_release
from micros_tooling.storage.packages import require, digest, canonical_json


class Artifacts:
    def __init__(self, registry):
        self.registry = registry
        with registry.changed:
            registry.db.executescript('''
                CREATE TABLE IF NOT EXISTS artifacts(kind TEXT, key TEXT, body BLOB,
                    PRIMARY KEY(kind,key));
                CREATE TABLE IF NOT EXISTS artifact_configurations(release TEXT, key TEXT, body BLOB, PRIMARY KEY(release,key));
                CREATE TABLE IF NOT EXISTS artifact_deployments(device TEXT, release TEXT,
                    confirmed TEXT, PRIMARY KEY(device,release));
            ''')

    def handle(self, method, path, body):
        configs = re.fullmatch(r'/v1/artifacts/releases/([0-9a-f]{64})/configurations', path)
        blob = re.fullmatch(r'/v1/artifacts/(bases|releases)/([0-9a-f]{64})', path)
        device = re.fullmatch(r'/v1/artifacts/devices/([0-9a-f]{12})(?:/([0-9a-f]{64}))?', path)
        with self.registry.changed:
            db = self.registry.db
            if configs and method == 'GET':
                rows = db.execute('SELECT key,body FROM artifact_configurations WHERE release=? ORDER BY rowid', (configs[1],)).fetchall()
                result = json.dumps([dict(sha256=k, configuration=json.loads(b)) for k,b in rows]).encode()
                require(len(result) <= LIMIT, 'Configuration history exceeds response limit')
                return 200, result
            if blob:
                kind, key = blob.groups()
                row = db.execute('SELECT body FROM artifacts WHERE kind=? AND key=?', (kind,key)).fetchone()
                if method == 'GET':
                    return (200, row[0]) if row else (404, b'{"error":"artifact_missing"}')
                if method == 'PUT':
                    files = unpack(body)
                    if kind == 'bases':
                        validate_base(key, files)
                    else:
                        receipt = validate_release(key, files)
                        require(db.execute("SELECT 1 FROM artifacts WHERE kind='bases' AND key=?",
                                           (receipt['firmware_sha256'],)).fetchone(), 'Publish the base before its releases')
                    if row:
                        previous = unpack(row[0])
                        # A release can be rebuilt from different source paths/comments; retain
                        # the first archived configuration, never replace its executable content.
                        compared = previous.keys() & files.keys() if kind == 'bases' else [n for n in files if n.endswith('.msp')]
                        require(all(previous[n] == files[n] for n in compared), 'Immutable artifact conflict')
                        if kind == 'bases' and files.keys() - previous.keys():
                            # Enrich old bundles with the original partition table; never replace bytes.
                            from micros_tooling.storage.artifacts import pack
                            db.execute('UPDATE artifacts SET body=? WHERE kind=? AND key=?',
                                       (pack({**previous, **files}), kind, key))
                    else:
                        db.execute('INSERT INTO artifacts VALUES(?,?,?)', (kind,key,body))
                    if kind == 'releases':
                        config = canonical_json(json.loads(files['configuration.json']))
                        db.execute('INSERT OR IGNORE INTO artifact_configurations VALUES(?,?,?)', (key,digest(config),config))
                    db.commit()
                    return 200, b'{}'
            if device:
                identity, release = device.groups()
                require(db.execute("SELECT 1 FROM devices WHERE id=? AND token_hash!=''", (identity,)).fetchone(), 'Unknown device')
                if method == 'GET' and release is None:
                    rows = db.execute('SELECT release,confirmed FROM artifact_deployments WHERE device=? ORDER BY confirmed,rowid', (identity,)).fetchall()
                    return 200, json.dumps([dict(release=r,confirmed=c) for r,c in rows]).encode()
                if method == 'POST' and release:
                    row = db.execute("SELECT body FROM artifacts WHERE kind='releases' AND key=?", (release,)).fetchone()
                    require(row, 'Unknown release')
                    payload = json.loads(body)
                    confirmed = None
                    require(isinstance(payload, dict) and payload.keys() <= {'status', 'recorded_at'}
                            and len(payload) <= 1, 'Invalid confirmation')
                    if 'recorded_at' in payload:
                        at = datetime.fromisoformat(payload['recorded_at'])
                        require(at.tzinfo is not None and at <= datetime.now(timezone.utc), 'Invalid recorded confirmation time')
                        confirmed = at.astimezone(timezone.utc).isoformat()
                    if 'status' in payload:
                        receipt = validate_release(release, unpack(row[0]))
                        status = payload['status']
                        require(status['identity']['device_id'] == identity and
                                status['identity']['base_sha256'] == receipt['firmware_sha256'] and
                                not status['activation']['pending'] and
                                receipt['banks'].get(str(status['activation']['good'])) == status['activation']['good_sha256'],
                                'Status does not confirm this release')
                        from micros_tooling.deployment.deploy import running
                        require(running(status, len(receipt['services'])), 'Release is not running')
                        confirmed = datetime.now(timezone.utc).isoformat()
                    db.execute('INSERT INTO artifact_deployments VALUES(?,?,?) ON CONFLICT(device,release) DO UPDATE SET confirmed=CASE WHEN confirmed IS NULL THEN excluded.confirmed WHEN excluded.confirmed > confirmed THEN excluded.confirmed ELSE confirmed END', (identity,release,confirmed))
                    db.commit()
                    return 200, b'{}'
        return 404, b'{"error":"unknown_artifact_route"}'
