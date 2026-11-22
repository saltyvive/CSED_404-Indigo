import csv
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import validate_grid_session as v
import test_grid_map as fixtures


class GridValidationTests(unittest.TestCase):
    def fixture(self,path):
        manifest=fixtures.GridMapTests().fixture(path,test=True)
        manifest['setup']={'aspect':1.5}
        with (path/'magnetometer.csv').open() as stream:
            manifest['sensorCounts']={'magnetometer':sum(1 for _ in csv.DictReader(stream))}
        (path/'manifest.json').write_text(json.dumps(manifest))
        model=dict(version=1,method='bilinear_forward_surface_grid_inverse',aspect=1.5,
                   xKnots=[0,.25,.5,.75,1],yKnots=[0,.25,.5,.75,1],
                   fieldsUT=[[[10*x,20*y,5] for x in [0,.25,.5,.75,1]] for y in [0,.25,.5,.75,1]],
                   searchSteps=20,residualLimitUT=3,ambiguityDistance=.2,ambiguityMarginUT=.75,
                   sourceSession='different-training-session',trainingTrialIDs=['training-only'],excludedRows=[])
        model_path=path/'frozen.json';model_path.write_text(json.dumps(model))
        return manifest,model_path,model

    def test_causal_replay_uses_row_background_and_freezes_model(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory);manifest,model_path,model=self.fixture(path)
            before=model_path.read_bytes()
            result=v.evaluate(path,model_path,path/'report')
            self.assertEqual(result['modelSHA256'],hashlib.sha256(before).hexdigest())
            self.assertEqual(model_path.read_bytes(),before)
            self.assertFalse(result['modelFitted'])
            self.assertEqual(result['rowStartStatic']['all']['count'],25)
            self.assertEqual(result['causalReplay']['all']['maximumErrorFractionOfHeight'],0)
            self.assertEqual(result['rowStartStatic']['interior']['count'],9)
            model['sourceSession']=manifest['id'];model_path.write_text(json.dumps(model))
            with self.assertRaises(ValueError):v.evaluate(path,model_path,path/'report2')
            fixtures.GridMapTests().fixture(path,test=False)
            with self.assertRaises(ValueError):v.evaluate(path,model_path,path/'report3')

    def test_flagged_points_are_retained_but_identified(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory);manifest,model_path,_=self.fixture(path)
            trial=next(t for t in manifest['trials'] if t['spec']['id']=='4-hold-1')
            manifest['warnings']=[f"iPad movement at uptime {trial['startUptime']+1}; inspect device_motion.csv"]
            (path/'manifest.json').write_text(json.dumps(manifest))
            result=v.evaluate(path,model_path,path/'report')
            self.assertEqual(result['flaggedRows'],[4])
            self.assertEqual(result['rowStartStatic']['all']['count'],25)
            self.assertEqual(result['rowStartStatic']['unflaggedRows']['count'],20)
            self.assertGreater(result['framesAfterMovementWarning'],0)


if __name__=='__main__':unittest.main()
