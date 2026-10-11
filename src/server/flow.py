"""Read-only remote endpoints for the console service flow."""
import json
import time

def remote_connections(registry, device, status):
    """Read-only channel endpoints; caller holds Registry.changed.

    Only attach routes to their exact local application selection. A globe
    describes configured remote access, never inferred traffic or a new grant.
    Return no transport identities, payloads, or private router records.
    """
    def matches(endpoint, observed):
        activation = observed.get('activation', {})
        return (observed.get('identity', {}).get('base_sha256') == endpoint['base']
                and activation.get('good_sha256') == endpoint['graph']
                and activation.get('sequence') == endpoint['sequence']
                and not activation.get('pending'))

    result = []
    for route in getattr(getattr(registry, 'coordination', None), 'routes', []):
        config = route['config']
        for side, direction in (('source', 'subscribe'), ('target', 'publish')):
            local = config[side]
            if local['device'] != device or not matches(local, status):
                continue
            if not any(c.get('key') == local['key'] for c in status.get('channels', [])):
                continue
            peer = config['target' if side == 'source' else 'source']
            rows = [registry.db.execute(
                'SELECT name,boot,status,last_seen,token_hash FROM devices WHERE id=?',
                (endpoint['device'],)).fetchone() for endpoint in (local, peer)]
            state = 'Ready'
            reason = 'Both endpoints bound through the coordination server'
            if route['blocked'] or any(not row or not row[4] or row[1] != endpoint['boot']
                    or not matches(endpoint, json.loads(row[2] or '{}'))
                    for endpoint, row in zip((local, peer), rows)):
                state, reason = 'Unavailable', 'Route needs re-admission after an endpoint changed'
            elif any(time.time() - row[3] >= 30 for row in rows):
                state, reason = 'Offline', 'An endpoint is offline; forwarding is paused'
            elif any(not json.loads(row[2]).get('services') or any(
                    service.get('state') != 'Running' for service in json.loads(row[2])['services'])
                    for row in rows):
                state, reason = 'Unavailable', 'An endpoint application is not running'
            elif len(route['bound']) != 2:
                state, reason = 'Connecting', 'Waiting for both endpoints to bind'
            result.append(dict(key=local['key'], direction=direction, route=config['name'],
                kind=config['kind'], peer_device=peer['device'],
                peer_name=(rows[1][0] if rows[1] else None) or peer['device'],
                state=state, reason=reason))
    return result
