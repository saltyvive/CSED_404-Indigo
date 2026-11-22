import copy
import csv
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import build_dense_grid_model as d
from build_grid_model import field, Projector


def magnetic(x, y):
    return [30*x, 40*y, 10+12*x*y]


class DenseGridTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.paths = []
        for repetition in range(1, 4):
            for letter in 'ABC':
                scenario = f'grid9Train{repetition}{letter}'
                path = cls.root/scenario; path.mkdir()
                cls.fixture(path, scenario)
                cls.paths.append(path)
        cls.batches = [d.extract(p) for p in cls.paths]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @staticmethod
    def fixture(path, scenario):
        repetition, rows_to_collect = d.batch_spec(scenario)
        plans = Path(__file__).resolve().parents[1]/'build/tests/grid9-plans.json'
        # Use actual Swift-generated plans when core tests have run first.
        specs = json.loads(plans.read_text())[scenario] if plans.exists() else []
        if not specs:
            for row in rows_to_collect:
                for action, col in [('before', None)]+[('hold', c) for c in range(1, 10)]+[('after', None)]:
                    specs.append(dict(id=f'{row}-{action}-{col}', kind='mapHold' if col else 'mapBaseline',
                                      scenarioID=scenario, gridSize=9, gridRow=row, gridColumn=col,
                                      repetition=repetition, calibrationGroup=f'pass{repetition}-row{row}',
                                      purpose='grid9_train' if col else 'grid9_baseline', edgeAction=action,
                                      point={'x': (col-1)/8, 'y': (row-1)/8} if col else None))
        trials, samples = [], []; time = 100.0
        for spec in specs:
            point = spec.get('point'); row = spec['gridRow']
            duration = 3 if point else 10
            # Substantial distinct backgrounds, plus linear time drift.
            baseline = [100*row + 10*repetition, -50*row, 30*repetition]
            b = magnetic(point['x'], point['y']) if point else [0, 0, 0]
            trials.append(dict(spec=spec, status='completed', startUptime=time, settleSeconds=3, endUptime=time+3+duration))
            for i in range(duration*50):
                t = time+3+i/50
                samples.append(dict(timestamp_s=t, trial_id=spec['id'], phase='hold' if point else 'baseline',
                                    label_source='manual_static_target' if point else 'none',
                                    target_x=point['x'] if point else '', target_y=point['y'] if point else '',
                                    **dict(zip(('bx_uT', 'by_uT', 'bz_uT'), [v+offset+.002*t for v, offset in zip(b, baseline)]))))
            time += duration+4
        manifest = dict(schemaVersion=1, id='SYNTHETIC-'+scenario, status='completed', device='SyntheticDevice',
                        setup=dict(aspect=1.5, plane='desk'), trials=trials, warnings=[], sensorCounts={'magnetometer':len(samples)})
        (path/'manifest.json').write_text(json.dumps(manifest))
        with (path/'magnetometer.csv').open('w') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(samples[0])); writer.writeheader(); writer.writerows(samples)

    def test_actual_plans_extract_243_placements_and_remove_row_drift(self):
        points, aspect = d.combine(self.batches)
        self.assertEqual(len(points), 243)
        for p in points:
            self.assertLess(math.dist(p['deltaUT'], magnetic(*p['xy'])), 1e-10)
        model, variability = d.build(points, aspect)
        self.assertEqual(len(model['trainingTrialIDs']), 243)
        self.assertTrue(all(p['repeats'] == 3 for p in variability))
        self.assertEqual(model['searchSteps'] % 8, 0)
        for xy in [[.125,.875], [.3,.6], [.9375,.0625]]:
            self.assertLess(math.dist(field(model, *xy), magnetic(*xy)), 1e-10)

    def test_independent_placements_have_equal_weight_and_outlier_is_reported(self):
        points, aspect = d.combine(copy.deepcopy(self.batches))
        point = next(p for p in points if p['xy'] == [.5,.5] and p['repetition'] == 2)
        point['deltaUT'] = [v+9 for v in point['deltaUT']]
        point['samples'] = 100000  # More sensor frames must not give more weight.
        model, variability = d.build(points, aspect)
        self.assertLess(math.dist(field(model, .5,.5), magnetic(.5,.5)), 1e-10)
        spread = next(p for p in variability if p['xy'] == [.5,.5])
        self.assertGreater(spread['maxPairwiseDistanceUT'], 15)

    def test_missing_duplicate_or_different_setup_batches_rejected(self):
        with self.assertRaises(ValueError): d.combine(self.batches[:-1])
        with self.assertRaises(ValueError): d.combine(self.batches[:-1]+[self.batches[0]])
        changed = copy.deepcopy(self.batches); changed[-1]['setup']['aspect'] = 2
        with self.assertRaises(ValueError): d.combine(changed)
        with self.assertRaises(ValueError): d.batch_spec('gridMapTest')

    def test_motion_warning_is_preserved_and_cannot_silently_enter_fit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory); self.fixture(path, 'grid9Train1A')
            manifest = json.loads((path/'manifest.json').read_text())
            hold = next(t for t in manifest['trials'] if t['spec']['kind'] == 'mapHold')
            manifest['warnings'] = [f"iPad movement at uptime {hold['startUptime']}"]
            (path/'manifest.json').write_text(json.dumps(manifest))
            flagged = d.extract(path)
        self.assertEqual(sum(not p['eligible'] for p in flagged['points']), 9)
        batches = copy.deepcopy(self.batches); batches[0] = flagged
        points, aspect = d.combine(batches)
        model, _ = d.build(points, aspect)
        self.assertEqual(len(model['trainingTrialIDs']), 234)
        for p in points:
            if p['row'] == 1 and p['repetition'] == 2: p['eligible'] = False
        with self.assertRaises(ValueError): d.build(points, aspect)

    def test_wrong_coordinate_or_validation_role_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory); self.fixture(path, 'grid9Train1A')
            manifest = json.loads((path/'manifest.json').read_text())
            hold = next(t for t in manifest['trials'] if t['spec']['kind'] == 'mapHold')
            hold['spec']['purpose'] = 'grid9_test'
            (path/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaises(ValueError): d.extract(path)
            hold['spec']['purpose'] = 'grid9_train'; hold['spec']['point']['x'] = .42
            (path/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaises(ValueError): d.extract(path)

    def test_end_to_end_model_provenance_and_whole_pass_diagnostics(self):
        out = self.root/'report'
        d.run(self.paths, out)
        report = json.loads((out/'analysis.json').read_text())
        model = json.loads((out/'grid_model.json').read_text())
        self.assertEqual(report['status'], 'model_ready_for_personal_test')
        self.assertEqual(len(model['sourceSessions']), 9)
        self.assertEqual([p['trainingObservations'] for p in report['internalLeaveOnePassOut']], [162]*3)
        self.assertEqual([p['count'] for p in report['internalLeaveOnePassOut']], [81]*3)
        self.assertEqual(len(model['trainingTrialIDs']), 243)
        with self.assertRaises(ValueError): d.run(self.paths, out)
        # Preserve a clearly synthetic parity fixture for the Swift projector.
        destination = Path(__file__).resolve().parents[1]/'build/tests'
        destination.mkdir(parents=True, exist_ok=True)
        (destination/'grid9-synthetic-model.json').write_text(json.dumps(model))
        projector = Projector(model)
        frames = [dict(filteredDeltaUT=magnetic(x,y), **projector.project(magnetic(x,y)))
                  for x,y in [(0,0),(.125,.875),(.5,.5),(.9,.4),(1,1)]]
        (destination/'grid9-synthetic-replay.json').write_text(json.dumps(frames))


if __name__ == '__main__': unittest.main()
