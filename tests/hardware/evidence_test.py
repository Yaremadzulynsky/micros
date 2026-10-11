"""A hardware proof must refer to the current admission, not prior retained logs."""
import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parent))
from coordination import current_completion


class EvidenceTest(unittest.TestCase):
    def test_requires_current_generation_and_each_loss_budget(self):
        route = dict(epoch=9, blocked=None, bound=['source', 'target'])
        result = dict(route='ir.operation', side='target', status=2, generation=9, payload='0849')
        status = dict(counts=dict(dropped=999), routes=[
            dict(route, name='ir.target', drops=dict(target=3)),
            dict(route, name='ir.operation', drops=dict(target=3, source=3))], events=[result])
        self.assertEqual(current_completion(status), result)
        for route_index, side in [(0, 'target'), (1, 'target'), (1, 'source')]:
            changed = copy.deepcopy(status)
            changed['routes'][route_index]['drops'][side] = 2
            self.assertIsNone(current_completion(changed))
        for key, value in [('generation', 8), ('status', 1), ('side', 'source')]:
            changed = copy.deepcopy(status)
            changed['events'][0][key] = value
            self.assertIsNone(current_completion(changed))
        changed = copy.deepcopy(status)
        changed['routes'][1]['epoch'] = 0
        self.assertIsNone(current_completion(changed))
        changed = copy.deepcopy(status)
        changed['routes'][1]['blocked'] = 'Endpoint restarted'
        self.assertIsNone(current_completion(changed))


if __name__ == '__main__':
    unittest.main()
