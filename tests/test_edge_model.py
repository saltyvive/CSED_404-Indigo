import copy
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_edge_model as e


def session(edge='top', role='edge_train', shift=0):
    holds = []
    for rep in range(1, 3 if role == 'edge_train' else 2):
        for s in e.KNOTS:
            holds.append(dict(edge=edge, purpose=role, repetition=rep, parameter=s,
                              delta=[20*s, 30*s*s, (40 if edge == 'bottom' else 0)+shift],
                              noiseUT=.2, trial=f'{role}-{edge}-{rep}-{s}'))
    return dict(id=role+edge, startedAt='2026-10-15', setup={'aspect': 1.5}, holds=holds,
                baselineDriftUT=.1, sweeps=[], probes=[])


class EdgeModelTests(unittest.TestCase):
    def test_nonlinear_monotone_curve_no_overshoot(self):
        model, _ = e.build([session()])
        curve = model['curves'][0]
        self.assertAlmostEqual(e.field(curve, .5)[1], 7.5)
        # A four-corner straight edge would return 15 here.
        ys = [e.field(curve, i/100)[1] for i in range(101)]
        self.assertTrue(all(a <= b for a, b in zip(ys, ys[1:])))

    def test_test_labels_never_train_and_edge_not_given_to_predictor(self):
        top, bottom = session(), session('bottom')
        wrong_test = session('top', 'edge_test', 40)
        model, report = e.build([top, bottom, wrong_test])
        reference, _ = e.build([top, bottom])
        self.assertEqual(model, reference)
        self.assertEqual(report['edgeClassificationCount'], 3)  # shared corners excluded
        self.assertEqual(report['edgeCorrect'], 0)
        self.assertTrue(all(p['edge'] == 'bottom' for p in report['heldOutPointTests']))

    def test_incomplete_or_wrong_setup_rejected(self):
        damaged = session()
        damaged['holds'].pop()
        with self.assertRaises(ValueError):
            e.build([damaged])
        with self.assertRaises(ValueError):
            e.build([session(role='edge_test')])
        other = session('bottom')
        other['setup']['aspect'] = 2
        with self.assertRaises(ValueError):
            e.build([session(), other])

    def test_session_extraction_background_and_sweep_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            trials, rows = [], []
            def trial(kind, action, start, duration, raw, point=None):
                tid = f't{len(trials)}'
                spec = dict(id=tid, kind=kind, scenarioID='topTrain', edgeAction=action,
                            edge='top' if point else None, purpose='edge_train', repetition=1, point=point)
                trials.append(dict(spec=spec, status='completed', startUptime=start, settleSeconds=3,
                                   endUptime=start+3+duration))
                phase = {'edgeBaseline': 'baseline', 'edgeHold': 'hold', 'edgeSweep': 'move'}[kind]
                for i in range(duration*50):
                    rows.append(dict(timestamp_s=start+3+i/50, trial_id=tid, phase=phase,
                                     label_source='known_edge_only' if kind == 'edgeSweep' else 'manual_static_target',
                                     bx_uT=raw[0], by_uT=raw[1], bz_uT=raw[2], target_x='', target_y=''))
            trial('edgeBaseline', 'before', 0, 10, [100, 200, 300])
            trial('edgeHold', 'hold', 20, 3, [105, 205, 305], {'x': .5, 'y': 0})
            trial('edgeSweep', 'normal', 30, 10, [105, 205, 305])
            trial('edgeBaseline', 'after', 50, 10, [100, 200, 300])
            manifest = dict(schemaVersion=1, id='SYNTHETIC', status='completed', setup={'aspect': 1.5},
                            startedAt='2026', trials=trials)
            def save():
                (path/'manifest.json').write_text(json.dumps(manifest))
                with (path/'magnetometer.csv').open('w') as f:
                    writer = csv.DictWriter(f, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
            save()
            result = e.extract(path)
            self.assertEqual(result['holds'][0]['delta'], [5, 5, 5])
            # Explicit diagnostics must preserve the warning, and cannot feed training.
            manifest['warnings'] = ['iPad movement at uptime 18.0; inspect device_motion.csv']
            save()
            with self.assertRaisesRegex(ValueError, '움직임 경고'):
                e.extract(path)
            diagnostic = e.extract(path, diagnostic_with_movement=True)
            self.assertTrue(diagnostic['diagnosticOnly'])
            self.assertEqual(diagnostic['movementWarningTimes'], [18.0])
            with self.assertRaisesRegex(ValueError, '진단 자료'):
                e.build([session(), diagnostic])
            manifest['warnings'] = []
            next(r for r in rows if r['phase'] == 'move')['target_x'] = '.4'
            save()
            with self.assertRaisesRegex(ValueError, '시간 기반 좌표'):
                e.extract(path)
            manifest['trials'].pop()
            save()
            with self.assertRaisesRegex(ValueError, '배경 측정'):
                e.extract(path)


if __name__ == '__main__':
    unittest.main()
