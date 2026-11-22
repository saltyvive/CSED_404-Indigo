import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from fixture_pose import ALPHA_CONVENTION, resolve_pose


class FixturePoseTests(unittest.TestCase):
    def setUp(self):
        self.manifest = dict(id='session', printedGrid=dict(campaignID='campaign', pose=dict(
            phiDegrees=0, thetaDegrees=90, tipHeightMM=0, tipContact=True, tiltDirectionAtPhiZero='')))
        self.raw = json.dumps(self.manifest).encode()
        self.annotations = dict(version=1, annotations=[dict(id='confirmation', campaignID='campaign',
            sessionManifestSHA256={'session': hashlib.sha256(self.raw).hexdigest()},
            expectedPhiDegrees=0, expectedThetaDegrees=90, expectedTipHeightMM=0, expectedTipContact=True,
            alphaDegrees=0, alphaLabelSource='user_confirmed_retrospective')])

    def test_legacy_confirmation_is_scoped_and_does_not_mutate_original(self):
        before = copy.deepcopy(self.manifest)
        pose, source = resolve_pose(self.manifest, self.raw, self.annotations)
        self.assertEqual(pose['alphaDegrees'], 0)
        self.assertEqual(source, 'confirmation')
        self.assertEqual(self.manifest, before)
        self.assertNotIn('alphaDegrees', json.loads(self.raw)['printedGrid']['pose'])
        for mutation in ['session', 'campaign', 'pose']:
            bad = copy.deepcopy(self.manifest)
            if mutation == 'session': bad['id'] = 'different'
            elif mutation == 'campaign': bad['printedGrid']['campaignID'] = 'different'
            else: bad['printedGrid']['pose']['phiDegrees'] = 40
            with self.assertRaisesRegex(ValueError, 'Unknown legacy alpha'):
                resolve_pose(bad, json.dumps(bad).encode(), self.annotations)

    def test_unknown_or_tampered_legacy_data_not_assumed_zero(self):
        with self.assertRaisesRegex(ValueError, 'Unknown legacy alpha'):
            resolve_pose(self.manifest, self.raw, dict(version=1, annotations=[]))
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            resolve_pose(self.manifest, self.raw+b' ', self.annotations)

    def test_signed_alpha_and_reference_without_changing_theta(self):
        for alpha in [-90, -20, 0, 25, 90]:
            m = copy.deepcopy(self.manifest)
            m['printedGrid']['pose'].update(thetaDegrees=70, alphaDegrees=alpha,
                alphaLabelSource='operator_set_fixture_unmeasured', alphaDefinition=ALPHA_CONVENTION,
                tiltDirectionAtPhiZero='toward iPad')
            pose, source = resolve_pose(m, json.dumps(m).encode(), self.annotations)
            self.assertEqual((pose['thetaDegrees'], pose['alphaDegrees'], source), (70, alpha, None))
        for alpha in [-91, 91, float('nan')]:
            m['printedGrid']['pose']['alphaDegrees'] = alpha
            with self.assertRaisesRegex(ValueError, 'Invalid alpha'): resolve_pose(m, b'', self.annotations)
        m['printedGrid']['pose'].update(thetaDegrees=90, alphaDegrees=20, tiltDirectionAtPhiZero='')
        with self.assertRaisesRegex(ValueError, 'hinge reference'): resolve_pose(m, b'', self.annotations)


if __name__ == '__main__':
    unittest.main()
