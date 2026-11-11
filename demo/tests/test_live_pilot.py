import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import build_live_pilot as pilot


class LivePilotTests(unittest.TestCase):
    def test_background_interpolation_and_endpoint_clamping(self):
        points = [(10, (1,2,3)), (20, (11,12,13))]
        self.assertEqual(pilot.baseline_at(points, 15), (6,7,8))
        self.assertEqual(pilot.baseline_at(points, 99), (11,12,13))
        self.assertEqual(pilot.baseline_at(points, 0), (1,2,3))

    def test_inverse_projection_and_outside_search(self):
        anchors = [(10,10,0), (40,10,0), (40,30,0), (10,30,0)]
        result = pilot.project(anchors, pilot.field_at(anchors, .365, .785))
        self.assertLess(pilot.a.dist(result['xy'], [.365,.785]), .006)
        self.assertGreater(pilot.project(anchors, [45,20,0])['xy'][0], 1.1)

    def test_moving_targets_and_wrong_height_labels_never_become_anchors(self):
        manifest = {'trials': [{'spec': {'id': 'baseline', 'kind': 'baselineBefore'}, 'status': 'completed'},
                                {'spec': {'id': 'motion', 'kind': 'clockwise'}, 'status': 'completed'},
                                {'spec': {'id': 'air', 'kind': 'clockwiseAir'}, 'status': 'completed'}]}
        rows = [{'trial_id': 'baseline', 'phase': 'baseline', 'timestamp_s': '10', 'bx_uT': '10', 'by_uT': '20', 'bz_uT': '30'},
                {'trial_id': 'motion', 'phase': 'hold', 'label_source': 'manual_static_target', 'target_x': '.4', 'target_y': '.7'},
                {'trial_id': 'air', 'phase': 'air_hold', 'label_source': 'manual_height_instruction'}]
        modes, _ = pilot.observations(manifest, rows)
        self.assertEqual(modes, {'surface': [], 'air': []})


if __name__ == '__main__':
    unittest.main()
