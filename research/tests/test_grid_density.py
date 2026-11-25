import copy
import json
from pathlib import Path
import sys
import unittest
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from evaluate_grid_density import ROOT, indices, build, FastProjector, summarize
from build_grid_model import field


class GridDensityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan=json.loads((ROOT/'evaluation/grid_density_plan.json').read_bytes())
        cls.batches=json.loads((ROOT/cls.plan['source']).read_bytes())
        cls.reference=json.loads((ROOT/cls.plan['referenceModel']).read_bytes())

    def test_uniform_measured_grid_and_nested_isotropic_sequence(self):
        for total,counts in [(13,self.plan['rowCounts']),(21,self.plan['columnCounts'])]:
            for count in counts:
                ix=indices(total,count)
                self.assertEqual(len(ix),count);self.assertEqual(ix[0],1);self.assertEqual(ix[-1],total)
                self.assertEqual(len(set(np.diff(ix))),1)
        for total,counts in [(13,[4,7,13]),(21,[6,11,21])]:
            self.assertTrue(set(indices(total,counts[0]))<=set(indices(total,counts[1]))<=set(indices(total,counts[2])))
        with self.assertRaises(ValueError):indices(21,8)

    def test_no_unselected_or_test_field_leakage(self):
        before=build(self.reference,self.batches,3,5);modified=copy.deepcopy(self.batches)
        for b in modified:
            for p in b['points']:
                if b['repetition']!=1 or p['row'] not in indices(13,3) or p['column'] not in indices(21,5):
                    p['deltaUT']=[999,999,999]
        after=build(self.reference,modified,3,5)
        self.assertEqual(before,after);self.assertEqual(len(before['trainingTrialIDs']),15)
        self.assertTrue(set(before['sourceSessions']).isdisjoint(b['session'] for b in self.batches if b['repetition'] in (2,3)))

    def test_linear_field_reproduces_exact_surface_at_every_density(self):
        batches=copy.deepcopy(self.batches)
        for b in batches:
            for p in b['points']:
                x,y=p['xy'];p['deltaUT']=[30*x,20*y,10+5*x-3*y]
        for nr,nc in self.plan['presentationGrids']:
            m=build(self.reference,batches,nr,nc)
            for x,y in [(.17,.26),(.73,.49),(.05,.95),(0,0),(1,1)]:
                np.testing.assert_allclose(field(m,x,y),[30*x,20*y,10+5*x-3*y],atol=1e-12)

    def test_accuracy_includes_rejected_candidates_in_denominator(self):
        rows=[dict(errorMM=e,accepted=a,shown=True,fittedPlacement=False) for e,a in [(1,True),(2,False),(4,True),(6,False)]]
        m=summarize(rows)
        self.assertEqual(m['within2p5Rate'],.5)
        self.assertEqual(m['successWithin2p5MM'],.25)
        self.assertEqual(m['count'],4)


if __name__=='__main__':unittest.main()
