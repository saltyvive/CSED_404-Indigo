import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location('analysis', Path(__file__).resolve().parents[1]/'scripts/analyze_session.py')
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


def synthetic_session():
    manifest = {'schemaVersion': 1, 'id': 'SYNTHETIC_TEST_ONLY', 'status': 'completed',
                'setup': {'widthMM': '', 'heightMM': ''}, 'trials': []}
    rows = []
    time = 100.0
    for kind, rounds, n, offset in [('gridTrain', 3, 5, 0), ('gridTest', 2, 4, 0.5)]:
        for rep in range(1, rounds+1):
            for r in range(n):
                for c in range(n):
                    x, y = (c+offset)/4, (r+offset)/4
                    tid = f'{kind}-{rep}-{r}-{c}'
                    manifest['trials'].append({'spec': {'id': tid, 'kind': kind, 'repetition': rep,
                                                      'pointID': f'{r}-{c}', 'point': {'x': x, 'y': y}},
                                               'startUptime': time, 'endUptime': time+6,
                                               'settleSeconds': 3, 'status': 'completed'})
                    for i in range(300):
                        rows.append({'timestamp_s': str(time+i/50), 'trial_id': tid,
                                     'phase': 'settle' if i < 150 else 'hold',
                                     'label_source': 'manual_static_target',
                                     'bx_uT': str(20+70*x+rep*0.01), 'by_uT': str(-30+60*y), 'bz_uT': str(5+15*x+10*y)})
                    time += 7
    return manifest, rows


class AnalysisTests(unittest.TestCase):
    def test_complete_pipeline_and_trial_split(self):
        manifest, rows = synthetic_session()
        report, model = a.analyze(manifest, rows)
        self.assertEqual(report['valid_static_trials'], 107)
        self.assertEqual(report['repeat_holdout']['train_trials'], 50)
        self.assertEqual(report['repeat_holdout']['test_trials'], 25)
        self.assertEqual(report['spatial_holdout']['test_trials'], 32)
        self.assertLess(report['repeat_holdout']['median_normalized_error'], 0.01)
        self.assertLess(report['spatial_holdout']['median_normalized_error'], 0.15)
        self.assertNotIn('median_error_mm', report['spatial_holdout'])
        self.assertEqual(len(model['training_trial_ids']), 75)
        self.assertEqual(len(model['prototypes']), 25)
        with tempfile.TemporaryDirectory() as folder:
            a.write_report(report, model, folder)
            self.assertTrue((Path(folder)/'report.html').exists())
            self.assertEqual(json.loads((Path(folder)/'report.json').read_text())['session'], manifest['id'])

    def test_cancelled_and_guide_samples_never_train(self):
        manifest, rows = synthetic_session()
        manifest['trials'][0]['status'] = 'aborted'
        for row in rows:
            if row['trial_id'] == manifest['trials'][1]['spec']['id']:
                row['label_source'] = 'guide_only'
        holds, excluded = a.collect_holds(manifest, rows)
        self.assertEqual(len(holds), 105)
        self.assertEqual(len(excluded), 1)
        self.assertNotIn(manifest['trials'][0]['spec']['id'], [h['trial'] for h in holds])

    def test_gaps_rejected_and_empty_safe(self):
        manifest, rows = synthetic_session()
        tid = manifest['trials'][0]['spec']['id']
        rows = [r for r in rows if not (r['trial_id'] == tid and 104 < float(r['timestamp_s']) < 105)]
        _, excluded = a.collect_holds(manifest, rows)
        self.assertEqual(excluded[0]['trial'], tid)
        report, model = a.analyze({'status': 'recording', 'id': 'empty', 'setup': {}, 'trials': []}, [])
        self.assertIsNone(model)
        self.assertFalse(report['spatial_holdout']['available'])

        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'model.json').write_text('{"stale": true}')
            a.write_report(report, model, folder)
            self.assertFalse((Path(folder)/'model.json').exists())

    def test_known_mm_only(self):
        train = [{'trial': str(i), 'xy': xy, 'b': (xy[0]*10, xy[1]*10, 2)}
                 for i, xy in enumerate([(0, 0), (0, 1), (1, 0), (1, 1)])]
        test = [{'trial': 'test', 'xy': [0.5, 0.5], 'b': (5, 5, 2)}]
        report = a.evaluate(train, test, dimensions=(40, 60))
        self.assertAlmostEqual(report['median_error_mm'], 0)
        with self.assertRaises(AssertionError):
            a.evaluate(train, train)

    def test_zip_export_interoperability(self):
        archive = Path(__file__).resolve().parents[1]/'build/tests/test.zip'
        if not archive.exists():
            self.skipTest('Run Swift CoreTests first')
        with zipfile.ZipFile(archive) as z:
            self.assertIsNone(z.testzip())
            self.assertEqual(z.read('archive-fixture/empty.txt'), b'')
            self.assertIn('한글', z.read('archive-fixture/test.csv').decode('utf-8'))

    def test_corners_remain_separate_from_coordinate_training(self):
        manifest, rows = synthetic_session()
        manifest['trials'] = [t for t in manifest['trials'] if t['spec']['kind'] == 'gridTrain'
                              and t['spec']['point']['x'] in (0, 1) and t['spec']['point']['y'] in (0, 1)]
        for trial in manifest['trials']:
            trial['spec']['kind'] = 'corners'
        ids = {t['spec']['id'] for t in manifest['trials']}
        rows = [r for r in rows if r['trial_id'] in ids]
        report, model = a.analyze(manifest, rows)
        self.assertEqual(report['corner_check']['correct'], 4)
        self.assertEqual(report['corner_check']['train_trials'], 8)
        self.assertEqual(report['corner_check']['test_trials'], 4)
        self.assertIsNone(model)
        self.assertFalse(report['spatial_holdout']['available'])

    def test_height_pairs_exclude_transitions_and_coordinate_training(self):
        manifest = {'schemaVersion': 1, 'id': 'SYNTHETIC_HEIGHT_ONLY', 'status': 'completed',
                    'setup': {}, 'trials': []}
        rows = []
        for rep in range(1, 4):
            start = 100 + rep * 20
            tid = f'height-{rep}'
            manifest['trials'].append({'spec': {'id': tid, 'kind': 'cornersHeight', 'repetition': rep,
                                               'pointID': 'top_left', 'point': {'x': 0, 'y': 0},
                                               'nominalLiftMM': 10},
                                      'startUptime': start, 'endUptime': start + 16,
                                      'settleSeconds': 3, 'status': 'aborted' if rep == 3 else 'completed'})
            for i in range(650):
                t = i / 50
                phase, bx = ('surface_hold', 10) if t < 3 else (('lift_transition', 9999) if t < 5 else
                            (('air_hold', 14) if t < 8 else (('lower_transition', 9999) if t < 10 else ('surface_return', 12))))
                # The second trial is missing a large part of the air hold.
                if rep == 2 and 5.9 < t < 7:
                    continue
                rows.append({'timestamp_s': str(start + 3 + t), 'trial_id': tid, 'phase': phase,
                             'bx_uT': str(bx), 'by_uT': '20', 'bz_uT': '30',
                             'label_source': 'manual_height_instruction'})
            # A stale phase label in the transition must still fail the time-window check.
            rows.append({'timestamp_s': str(start + 7), 'trial_id': tid, 'phase': 'air_hold',
                         'bx_uT': '9999', 'by_uT': '9999', 'bz_uT': '9999',
                         'label_source': 'manual_height_instruction'})
        report, model = a.analyze(manifest, rows)
        height = report['height_check']
        self.assertEqual(height['completed_trials'], 2)
        self.assertEqual(height['valid_pairs'], 1)
        self.assertEqual(height['pairs'][0]['air_minus_surface_vector_uT'], (3, 0, 0))
        self.assertEqual(height['median_surface_return_distance_uT'], 2)
        self.assertEqual(height['excluded_phases'][0]['phase'], 'air_hold')
        self.assertEqual(report['valid_static_trials'], 0)
        self.assertIsNone(model)
        self.assertFalse(any('75' in w for w in report['warnings']))
        with tempfile.TemporaryDirectory() as folder:
            a.write_report(report, model, folder)
            self.assertIn('접촉 ↔ 약 1cm 공중 비교', (Path(folder)/'report.html').read_text())


if __name__ == '__main__':
    unittest.main()
