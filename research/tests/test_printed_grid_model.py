import copy
import csv
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import build_printed_grid_model as printed
from build_grid_model import field, Projector
from evaluate_printed_pass import score, metrics
import build_knn_model as knn


class PrintedModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        plan_path = Path(__file__).resolve().parents[1]/'build/tests/printed-grid-fast-plans.json'
        if not plan_path.exists():
            raise RuntimeError('Run Swift CoreTests first to generate actual collector plans')
        cls.plans = json.loads(plan_path.read_text())
        cls.paths = [cls.fixture(row) for row in range(1, 14)]
        cls.batches = [printed.extract(p) for p in cls.paths]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @classmethod
    def fixture(cls, row, prepare3=False):
        plans = json.loads((Path(__file__).resolve().parents[1]/'build/tests/printed-grid-current-plans.json').read_text()) if prepare3 else cls.plans
        specs = plans[f'sweetspot_21x13_v1_p1_r{row}']
        folder = cls.root/(f'row{row}-prepare3' if prepare3 else f'row{row}'); folder.mkdir()
        time = 100.0; trials = []; samples = []; motions = []
        for spec in specs:
            hold = spec['kind'] == 'mapHold'; duration = 2 if hold else 10; prepare = spec.get('preparationSeconds', 3)
            trial = dict(spec=spec, status='completed', startUptime=time, endUptime=time+prepare+duration, settleSeconds=prepare)
            trials.append(trial)
            for i in range(duration*50):
                t = time+prepare+i/50
                x, y = (spec['point']['x'], spec['point']['y']) if hold else (0, 0)
                b = [30*x, 40*y, 12+8*x*y] if hold else [0, 0, 0]
                sample = dict(timestamp_s=t, trial_id=spec['id'], phase='hold' if hold else 'baseline',
                              label_source='scheduled_static_target_unverified' if hold else 'none',
                              dataset='printed_grid_train' if hold else 'printed_grid_baseline',
                              target_x=x if hold else '', target_y=y if hold else '',
                              fixture_phi_deg=0 if hold else '', fixture_theta_deg=90 if hold else '',
                              fixture_alpha_deg=0 if hold else '', fixture_alpha_source='operator_set_fixture_unmeasured' if hold else '',
                              fixture_tip_state='contact' if hold else '', instructed_tip_height_mm=0 if hold else '',
                              fixture_pose_source='operator_set_fixture_unmeasured' if hold else '')
                sample.update(zip(('bx_uT', 'by_uT', 'bz_uT'), [v+row*10+.001*t for v in b]))
                samples.append(sample)
                motions.append(dict(timestamp_s=t, trial_id=spec['id'], phase=sample['phase'],
                                    gravity_x_g=0, gravity_y_g=0, gravity_z_g=-1,
                                    user_ax_g=0, user_ay_g=0, user_az_g=0, rx_rad_s=0, ry_rad_s=0, rz_rad_s=0))
            time += duration+4
        manifest = dict(schemaVersion=2, id=f'row{row}', status='completed', device='synthetic', warnings=[], trials=trials,
                        setup=dict(widthMM='50', heightMM='30', aspect=5/3),
                        sensorCounts=dict(magnetometer=len(samples), device_motion=len(motions)),
                        printedGrid=dict(protocolID=printed.PROTOCOL, campaignID='SYNTHETIC', batch=dict(row=row, **{'pass': 1}),
                                         timingRevision=printed.PREPARE3 if prepare3 else printed.FAST,
                                         pose=specs[1]['fixturePose'], **printed.GEOMETRY))
        (folder/'manifest.json').write_text(json.dumps(manifest))
        for name, rows in [('magnetometer', samples), ('device_motion', motions)]:
            with (folder/(name+'.csv')).open('w') as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
        return folder

    def test_three_second_preparation_keeps_two_second_capture(self):
        folder = self.fixture(1, prepare3=True)
        batch = printed.extract(folder)
        self.assertEqual(batch['effectiveTimingRevision'], printed.PREPARE3)
        self.assertEqual(len(batch['points']), 21)
        self.assertTrue(all(p['samples'] >= 50 for p in batch['points']))
        path = folder/'manifest.json'; m = json.loads(path.read_text())
        m['printedGrid']['timingRevision'] = printed.FAST
        path.write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError, 'Acquisition timing metadata mismatch'):
            printed.extract(folder)

    def test_knn_retains_placements_and_handles_ambiguity(self):
        model = knn.build(self.batches, [1])
        self.assertEqual(len(model['locations']), 273)
        self.assertTrue(all(len(p['fieldsUT']) == 4 for p in model['locations']))
        anchor = model['locations'][6*21+10]
        result = knn.Projector(model).project(anchor['fieldsUT'][0])
        self.assertLess(math.dist(result['xy'], anchor['xy']), 1e-9)
        self.assertTrue(result['accepted'])
        copies = copy.deepcopy(model)
        copies['locations'][6*21+10]['fieldsUT'] *= 5
        self.assertEqual(knn.Projector(copies).project(anchor['fieldsUT'][0]), result)
        conflict = copy.deepcopy(model)
        conflict['locations'][0]['fieldsUT'] = copy.deepcopy(anchor['fieldsUT'])
        ambiguous = knn.Projector(conflict).project(anchor['fieldsUT'][0])
        self.assertTrue(ambiguous['ambiguous']); self.assertFalse(ambiguous['accepted'])
        self.assertFalse(knn.Projector(model).project([0,0,0])['shown'])
        self.assertFalse(knn.Projector(model).project([1000,1000,1000])['accepted'])
        with self.assertRaises(ValueError): knn.Projector(model).project([math.nan,0,0])
        repeated = copy.deepcopy(self.batches)
        for batch in repeated:
            batch.update(repetition=2, session='repeat-'+batch['session'])
            for point in batch['points']:
                point.update(repetition=2, session=batch['session'])
                point['deltaUT'][2] += 2
        combined = knn.build(self.batches+repeated, [1,2])
        self.assertTrue(all(len(p['fieldsUT']) == 8 for p in combined['locations']))
        self.assertEqual(combined['locations'][0]['fieldsUT'][4][2]-combined['locations'][0]['fieldsUT'][0][2], 2)

    def test_rectangular_single_pass_and_background_drift(self):
        model = printed.build(self.batches, [1])
        self.assertEqual((len(model['xKnots']), len(model['yKnots'])), (21, 13))
        self.assertEqual(len(model['trainingTrialIDs']), 273)
        self.assertEqual(model['printedGridContext']['passes'], [1])
        self.assertEqual(model['printedGridContext']['pose']['alphaDegrees'], 0)
        self.assertIn('Only one placement', model['scope'])
        for x, y in [(0, 0), (1, 1), (.15, 2/12), (.325, .375)]:
            self.assertLess(math.dist(field(model, x, y), [30*x, 40*y, 12+8*x*y]), 1e-9)
        pred = Projector(model).project(field(model, .5, .5))
        self.assertEqual(pred['xy'], [.5, .5])

    def test_frozen_evaluation_then_learning_and_no_display_denominators(self):
        frozen = json.loads(json.dumps(printed.build(self.batches, [1]))); before = copy.deepcopy(frozen)
        evaluation = copy.deepcopy(self.batches)
        for b in evaluation:
            b.update(session='eval-'+b['session'], repetition=2,
                     evaluationModelSHA256='frozen-hash', evaluationTrainingPasses=[1])
            for p in b['points']: p.update(session=b['session'], repetition=2)
        report, _ = score(frozen,self.batches,evaluation,2,'frozen-hash')
        self.assertEqual(report['primary']['count'],273)
        self.assertEqual(report['causalReplay']['count'],819)
        self.assertEqual(frozen,before)
        updated = printed.build(self.batches+evaluation,[1,2])
        self.assertEqual(updated['printedGridContext']['passes'],[1,2])
        with self.assertRaisesRegex(ValueError,'Wrong frozen'):
            score(updated,self.batches+evaluation,evaluation,2,'frozen-hash')
        evaluation[0]['evaluationModelSHA256'] = 'other'
        with self.assertRaisesRegex(ValueError,'record this frozen'):
            score(frozen,self.batches,evaluation,2,'frozen-hash')
        evaluation[0]['session'] = self.batches[0]['session']
        with self.assertRaisesRegex(ValueError,'overlap'):
            score(frozen,self.batches,evaluation,2,'frozen-hash')
        result = metrics([dict(errorMM=1,accepted=False,shown=False),dict(errorMM=2,accepted=True,shown=True)])
        self.assertEqual(result['successWithin2p5MM'],.5)
        self.assertEqual(result['acceptedDisplayRate'],.5)

    def test_reject_missing_rows_duplicate_batches_or_different_conditions(self):
        for batches, passes in [(self.batches[:-1], [1]), (self.batches, [2]),
                                (self.batches[:-1]+[self.batches[0]], [1])]:
            with self.assertRaises(ValueError): printed.build(batches, passes)
        for key, value in [('campaignID', 'DIFFERENT'), ('pose', {'phiDegrees': 15})]:
            batches = copy.deepcopy(self.batches); batches[0][key] = value
            with self.assertRaises(ValueError): printed.build(batches, [1])
        batches = copy.deepcopy(self.batches); batches[0]['pose']['alphaDegrees'] = 15
        with self.assertRaisesRegex(ValueError, 'fixture pose mismatch'): printed.build(batches, [1])

    def test_reject_wrong_csv_alpha(self):
        path = self.paths[0]/'magnetometer.csv'; original = path.read_bytes()
        try:
            with path.open() as f: rows = list(csv.DictReader(f))
            next(r for r in rows if r['phase'] == 'hold')['fixture_alpha_deg'] = '-15'
            with path.open('w') as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
            with self.assertRaisesRegex(ValueError, 'CSV alpha'): printed.extract(self.paths[0])
        finally: path.write_bytes(original)

    def test_reject_wrong_csv_pose_and_incomplete_background(self):
        folder = self.paths[0]; path = folder/'magnetometer.csv'; original = path.read_bytes()
        try:
            with path.open() as f: rows = list(csv.DictReader(f))
            next(r for r in rows if r['phase'] == 'hold')['fixture_phi_deg'] = '45'
            with path.open('w') as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
            with self.assertRaisesRegex(ValueError, 'CSV target/pose'): printed.extract(folder)
        finally: path.write_bytes(original)
        path = folder/'manifest.json'; original = path.read_bytes()
        try:
            manifest = json.loads(original); manifest['trials'][-1]['status'] = 'aborted'
            path.write_text(json.dumps(manifest))
            with self.assertRaises(ValueError): printed.extract(folder)
        finally: path.write_bytes(original)

    def test_motion_review_cannot_override_motion_during_hold(self):
        folder = self.paths[0]; path = folder/'device_motion.csv'; original = path.read_bytes()
        try:
            with path.open() as f: rows = list(csv.DictReader(f))
            first_hold = next(r for r in rows if r['phase'] == 'hold')
            event = dict(first_hold, timestamp_s=float(first_hold['timestamp_s'])-1, phase='settle', user_ax_g=.04)
            def write():
                with path.open('w') as f:
                    writer = csv.DictWriter(f, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows+[event])
            write()
            with self.assertRaisesRegex(ValueError, 'Review non-measurement'): printed.extract(folder)
            reviewed = printed.extract(folder, allow_transient_motion=True, review_note='Synthetic transient test')
            self.assertEqual(len(reviewed['motionEvents']), 1)
            event['timestamp_s'] = first_hold['timestamp_s']; event['phase'] = 'hold'; write()
            with self.assertRaisesRegex(ValueError, 'during completed measurement'):
                printed.extract(folder, allow_transient_motion=True, review_note='Cannot override actual movement')
        finally: path.write_bytes(original)


if __name__ == '__main__':
    unittest.main()
