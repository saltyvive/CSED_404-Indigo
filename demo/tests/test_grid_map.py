import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import extract_grid_map as g


class GridMapTests(unittest.TestCase):
    def fixture(self, path, test=False):
        trials, rows = [], []
        time = 0
        for row in range(1, 6):
            for action, col in [('before', None)]+[('hold', col) for col in range(1, 6)]+[('after', None)]:
                baseline = [100*row, -30*row, 10*row]
                point = {'x': (col-1)/4, 'y': (row-1)/4} if col else None
                delta = [10*point['x'], 20*point['y'], 5] if point else [0,0,0]
                spec = dict(id=f'{row}-{action}-{col}', kind='mapHold' if col else 'mapBaseline',
                            scenarioID='gridMapTest' if test else 'gridMapTrain', calibrationGroup=f'row{row}',
                            gridRow=row, gridColumn=col, point=point, edgeAction=action,
                            purpose=('grid_map_test' if test else 'grid_map_train') if col else 'grid_map_baseline')
                duration = 3 if col else 10
                trials.append(dict(spec=spec,status='completed',startUptime=time,settleSeconds=3,endUptime=time+3+duration))
                for i in range(duration*50):
                    rows.append(dict(timestamp_s=time+3+i/50, trial_id=spec['id'],phase='hold' if col else 'baseline',
                                     label_source='manual_static_target' if col else 'none',
                                     **dict(zip(['bx_uT','by_uT','bz_uT'],[b+d for b,d in zip(baseline,delta)]))))
                time += 3+duration+1
        manifest = dict(schemaVersion=1,id='SYNTHETIC',status='completed',trials=trials,warnings=[])
        (path/'manifest.json').write_text(json.dumps(manifest))
        with (path/'magnetometer.csv').open('w') as f:
            writer=csv.DictWriter(f, fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        return manifest

    def test_each_row_uses_its_own_baseline_and_preserves_test_split(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            for is_test in (False, True):
                self.fixture(path,is_test)
                result=g.extract(path)
                self.assertEqual(result['eligibleForInitialMap'],not is_test)
                self.assertEqual(len(result['points']),25)
                for p in result['points']:
                    self.assertEqual(p['deltaUT'],[10*p['xy'][0],20*p['xy'][1],5])

    def test_movement_flags_only_affected_row_and_bad_coordinates_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory);m=self.fixture(path)
            target=next(t for t in m['trials'] if t['spec']['id']=='3-hold-2')
            m['warnings']=[f"iPad movement at uptime {target['startUptime']}; inspect device_motion.csv"]
            (path/'manifest.json').write_text(json.dumps(m))
            result=g.extract(path)
            self.assertEqual([r['eligible'] for r in result['calibrationGroups']],[True,True,False,True,True])
            self.assertFalse(result['eligibleForInitialMap'])
            target['spec']['point']['x']=.9
            (path/'manifest.json').write_text(json.dumps(m))
            with self.assertRaises(ValueError):g.extract(path)


if __name__ == '__main__': unittest.main()
