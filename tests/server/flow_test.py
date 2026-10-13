"""Remote graph evidence stays read-only and bound to the deployed application."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from server.relay import Registry

A, B = '000000000001', '000000000002'


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.registry = Registry(self.temp.name)
        self.management = self.registry.management
        self.observed = {}
        for device, key in ((A, 1), (B, 2)):
            self.registry.enroll(device, 'Publisher' if device == A else 'Listener', 'a' * 64)
            self.observed[device] = dict(identity=dict(device_id=device, base_sha256='b' * 64, abi_revision=7),
                activation=dict(good_sha256='c' * 64, pending=False, sequence=1),
                services=[dict(state='Running')], channels=[dict(key=key)])
            with patch('server.relay.POLL_SECONDS', 0):
                self.registry.poll(device, '1' * 16, self.observed[device])
        with self.registry.changed:
            self.registry.coordination.configure(dict(routes=[dict(name='target', kind='state',
                max_payload=32, schema='d' * 64, drop_first=0,
                source=dict(device=A, key=1, base='b' * 64, graph='c' * 64, sequence=1),
                target=dict(device=B, key=2, base='b' * 64, graph='c' * 64, sequence=1))]))
        self.route = self.registry.coordination.routes[0]

    def tearDown(self):
        self.registry.db.close()
        self.temp.cleanup()

    def connections(self, device):
        return self.management.decorate(self.observed[device], device)['remote_connections']

    def test_registry_retains_observations_without_browser_sessions(self):
        self.assertFalse(hasattr(self.registry, 'console'))
        self.assertFalse(hasattr(self.management, 'sessions'))
        self.assertEqual(len(self.management.history(A)['samples']), 1)
        with patch('server.relay.POLL_SECONDS', 0):
            self.registry.poll(A, '2' * 16, self.observed[A])
        history = self.management.history(A)
        self.assertEqual(len(history['samples']), 2)
        self.assertEqual(history['events'][0]['action'], 'boot')

    def test_incoming_and_outgoing_are_read_only(self):
        before = copy.deepcopy(self.route)
        incoming, outgoing = self.connections(B)[0], self.connections(A)[0]
        self.assertEqual((incoming['key'], incoming['direction'], incoming['peer_name']), (2, 'publish', 'Publisher'))
        self.assertEqual((outgoing['key'], outgoing['direction'], outgoing['peer_device']), (1, 'subscribe', B))
        self.assertEqual(incoming['state'], 'Connecting')
        self.assertEqual(self.route, before)
        self.assertNotIn('remote_connections', self.observed[A])
        self.assertEqual(self.registry.db.execute('SELECT count(*) FROM commands').fetchone()[0], 0)
        for private in ('base', 'graph', 'boot', 'payload', 'epoch', 'token'):
            self.assertNotIn(private, incoming)

    def test_ready_requires_both_bindings_and_online_endpoints(self):
        self.route['bound'] = {'source', 'target'}
        self.assertEqual(self.connections(A)[0]['state'], 'Ready')
        self.registry.db.execute('UPDATE devices SET last_seen=? WHERE id=?', (time.time()-60, B))
        self.assertEqual(self.connections(A)[0]['state'], 'Offline')

    def test_changed_peer_is_not_reported_as_connected(self):
        self.route['bound'] = {'source', 'target'}
        self.registry.db.execute('UPDATE devices SET boot=? WHERE id=?', ('2' * 16, B))
        self.assertEqual(self.connections(A)[0]['state'], 'Unavailable')

    def test_revoked_and_stopped_endpoints_remain_unavailable(self):
        changed = copy.deepcopy(self.observed[B])
        changed['services'][0]['state'] = 'Stopped'
        self.registry.db.execute('UPDATE devices SET status=? WHERE id=?', (json.dumps(changed), B))
        self.assertEqual(self.connections(A)[0]['state'], 'Unavailable')
        self.registry.db.execute("UPDATE devices SET token_hash='' WHERE id=?", (B,))
        self.assertEqual(self.connections(A)[0]['state'], 'Unavailable')

    def test_old_local_graph_and_pending_trial_have_no_remote_routes(self):
        for change in (dict(good_sha256='e' * 64), dict(sequence=2), dict(pending=True)):
            status = copy.deepcopy(self.observed[A])
            status['activation'].update(change)
            self.assertEqual(self.management.decorate(status)['remote_connections'], [])
        status = copy.deepcopy(self.observed[A]); status['channels'] = []
        self.assertEqual(self.management.decorate(status)['remote_connections'], [])

    def test_blocked_route_and_empty_or_legacy_router(self):
        self.route['blocked'] = 'Base rejected binding'
        self.assertEqual(self.connections(A)[0]['state'], 'Unavailable')
        self.registry.coordination.routes.clear()
        self.assertEqual(self.connections(A), [])
        del self.registry.coordination
        self.assertEqual(self.connections(A), [])


if __name__ == '__main__':
    unittest.main()
