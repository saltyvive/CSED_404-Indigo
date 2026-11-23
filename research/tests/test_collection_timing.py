import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from collection_timing import resolve_timing, LEGACY, FAST, PREPARE3


class TimingRecoveryTests(unittest.TestCase):
    def test_exact_annotation_only(self):
        manifest = dict(id='affected', printedGrid=dict(campaignID='campaign', timingRevision=FAST))
        raw = json.dumps(manifest).encode()
        annotation = dict(version=1, annotations=[dict(id='recovery', sessionID='affected', campaignID='campaign',
            manifestSHA256=hashlib.sha256(raw).hexdigest(), declaredTimingRevision=FAST, effectiveTimingRevision=LEGACY)])
        self.assertEqual(resolve_timing(manifest, raw, annotation), (LEGACY, 'recovery'))
        with self.assertRaisesRegex(ValueError, 'hash/revision mismatch'):
            resolve_timing(manifest, raw+b' ', annotation)
        for field, value in [('id', 'unlisted'), ('campaignID', 'different')]:
            other = copy.deepcopy(manifest)
            (other if field == 'id' else other['printedGrid'])[field] = value
            self.assertEqual(resolve_timing(other, json.dumps(other).encode(), annotation), (FAST, None))

    def test_unannotated_timing_stays_strict(self):
        empty = dict(version=1, annotations=[])
        for declared, expected in [(None, LEGACY), (FAST, FAST), (PREPARE3, PREPARE3)]:
            m = dict(id='normal', printedGrid=dict(campaignID='campaign', timingRevision=declared))
            self.assertEqual(resolve_timing(m, b'raw', empty), (expected, None))
        m['printedGrid']['timingRevision'] = 'unknown'
        with self.assertRaisesRegex(ValueError, 'Unknown acquisition timing'):
            resolve_timing(m, b'raw', empty)


if __name__ == '__main__':
    unittest.main()
