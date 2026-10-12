"""Publish exact-base embedded release labels through the operator connection."""
import http.client
import sys


def publish(workspace, remote, status, report):
    from micros_tooling.fleet.server import configured_remote
    relay = getattr(remote, 'relay', None)
    try:
        if relay is None:
            relay = configured_remote(workspace, status['identity']['device_id'])
        if relay is not None:
            relay.register_release(dict(
                before=dict(identity=dict(base_sha256=report['base_sha256'])),
                plan=report['plan'],
                banks={str(report['bank']): dict(digest=report['graph_sha256'])}))
    except (OSError, ValueError, http.client.HTTPException) as error:
        print('Deployment succeeded; console labels could not be updated: ' + str(error), file=sys.stderr)
