import csv
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import validate_grid_paths as v


class GridPathTests(unittest.TestCase):
    def fixture(self,path):
        trials=[];rows=[];time=100
        for index in range(1,6):
            guide=f'row{index}';y=(index-1)/4;baseline=[index*100,-30,20]
            for action in ['before','sweep','after']:
                moving=action=='sweep';duration=4 if moving else 10
                spec=dict(id=f'{guide}-{action}',kind='mapSweep' if moving else 'mapBaseline',
                          scenarioID='gridHorizontal',calibrationGroup=guide,guidePathID=guide,
                          edgeAction=action,point=None,purpose='grid_path_test' if moving else 'grid_path_baseline')
                trials.append(dict(spec=spec,status='completed',startUptime=time,settleSeconds=3,endUptime=time+3+duration))
                for i in range(duration*50):
                    x=math.sin(math.pi*(i/50)/duration)**2
                    b=[30*x,40*y,5] if moving else [0,0,0]
                    rows.append(dict(timestamp_s=time+3+i/50,trial_id=spec['id'],phase='move' if moving else 'baseline',
                                     label_source='known_path_only' if moving else 'none',target_x='',target_y='',
                                     **dict(zip(['bx_uT','by_uT','bz_uT'],[a+c for a,c in zip(baseline,b)]))))
                time+=3+duration+1
        m=dict(schemaVersion=1,id='synthetic-path-test',status='completed',trials=trials,warnings=[],
               setup={'aspect':1.5},sensorCounts={'magnetometer':len(rows)})
        (path/'manifest.json').write_text(json.dumps(m))
        with (path/'magnetometer.csv').open('w') as stream:
            w=csv.DictWriter(stream,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
        model=dict(version=1,aspect=1.5,xKnots=[0,.25,.5,.75,1],yKnots=[0,.25,.5,.75,1],
                   fieldsUT=[[[30*x,40*y,5] for x in [0,.25,.5,.75,1]] for y in [0,.25,.5,.75,1]],
                   searchSteps=20,residualLimitUT=3,ambiguityDistance=.2,ambiguityMarginUT=.75,
                   sourceSession='training',trainingTrialIDs=['training-only'])
        modelpath=path/'model.json';modelpath.write_text(json.dumps(model))
        return m,rows,modelpath

    def test_line_geometry_in_physical_aspect(self):
        self.assertAlmostEqual(v.line_metrics([.7,.6],'row3',1.5)['lineDistanceFractionOfHeight'],.1)
        self.assertAlmostEqual(v.line_metrics([.6,.3],'col3',1.5)['lineDistanceFractionOfHeight'],.15)
        for guide,point in [('diagonalDown',[.3,.3]),('diagonalUp',[.3,.7])]:
            self.assertAlmostEqual(v.line_metrics(point,guide,1.5)['lineDistanceFractionOfHeight'],0)
        with self.assertRaises(ValueError):v.endpoints('free')

    def test_free_speed_replay_preserves_model_and_instructed_line(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory);m,rows,model=self.fixture(path);original=model.read_bytes()
            result=v.evaluate(path,model,path/'report')
            self.assertEqual(model.read_bytes(),original)
            self.assertFalse(result['modelFitted'])
            self.assertEqual(len(result['paths']),5)
            for group in result['paths']:
                self.assertAlmostEqual(group['causal']['allCandidates']['maxLineDistanceFractionOfHeight'],0)
                self.assertGreater(group['causal']['frames'],20)
            # A moving target must not be silently interpreted as ground truth.
            rows[500]['target_x']='0.5'
            with (path/'magnetometer.csv').open('w') as stream:
                w=csv.DictWriter(stream,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
            with self.assertRaises(ValueError):v.extract(path)


if __name__=='__main__':unittest.main()
