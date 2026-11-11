import json
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import build_grid_model as g


class GridModelTests(unittest.TestCase):
    def observations(self):
        points=[]
        for row in range(1,6):
            for col in range(1,6):
                x,y=(col-1)/4,(row-1)/4
                points.append(dict(row=row,xy=[x,y],eligible=row!=4,trial=f'{row}-{col}',noiseUT=.5,
                                   deltaUT=[30*x,40*y,10+8*x*y]))
        return dict(purpose='grid_map_train',session='synthetic',points=points,
                    calibrationGroups=[dict(row=i,eligible=i!=4,warnings=['ipad_movement_after_baseline'] if i==4 else []) for i in range(1,6)])

    def test_explicit_movement_inclusion_retains_audit_and_blocks_other_faults(self):
        o=self.observations()
        with self.assertRaises(ValueError):g.build(o,1.5,include_movement_rows=[4])
        model=g.build(o,1.5,include_movement_rows=[4],inclusion_note='Operator requests provisional inclusion')
        self.assertEqual(len(model['trainingTrialIDs']),25)
        self.assertEqual(model['movementIncludedRows'],[4])
        self.assertEqual(model['excludedRows'],[])
        self.assertTrue(all(not p['eligible'] for p in o['points'] if p['row']==4))
        o['calibrationGroups'][3]['warnings'].append('unstable_baseline')
        with self.assertRaises(ValueError):g.build(o,1.5,include_movement_rows=[4],inclusion_note='Request')
        o=self.observations();o['purpose']='grid_map_test'
        with self.assertRaises(ValueError):g.build(o,1.5,include_movement_rows=[4],inclusion_note='Request')

    def test_excludes_flagged_rows_and_validation_sessions(self):
        o=self.observations();m=g.build(o,1.5)
        self.assertEqual(len(m['trainingTrialIDs']),20)
        self.assertEqual(m['yKnots'],[0,.25,.5,1])
        self.assertFalse(any(t.startswith('4-') for t in m['trainingTrialIDs']))
        o['purpose']='grid_map_test'
        with self.assertRaises(ValueError):g.build(o,1.5)

    def test_interior_inversion_and_invalid_inputs(self):
        m=g.build(self.observations(),1.5);p=g.Projector(m)
        # Interior points not in training, including across the excluded row.
        for x,y in [(.13,.17),(.36,.72),(.84,.91),(.5,.75)]:
            b=[30*x,40*y,10+8*x*y]
            self.assertLess(math.dist(g.field(m,x,y),b),1e-12)
            result=p.project(b)
            self.assertLess(math.dist(result['xy'],[x,y]),1e-10)
            self.assertTrue(result['accepted'])
        self.assertFalse(p.project([0,0,0])['shown'])
        self.assertFalse(p.project([100,100,100])['accepted'])
        with self.assertRaises(ValueError):p.project([math.nan,0,0])

    def test_spatial_alias_is_not_confident(self):
        m=g.build(self.observations(),1.5)
        m['fieldsUT']=[[[30*x,0,10] for x in m['xKnots']] for _ in m['yKnots']]
        result=g.Projector(m).project([15,0,10])
        self.assertTrue(result['ambiguous'])
        self.assertFalse(result['accepted'])

    def test_insufficient_boundary_coverage_rejected(self):
        o=self.observations()
        for p in o['points']:
            if p['xy'][1]==1:p['eligible']=False
        with self.assertRaises(ValueError):g.build(o,1.5)


if __name__=='__main__':unittest.main()
