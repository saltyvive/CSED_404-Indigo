import copy
import json
from pathlib import Path
import statistics as st
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from evaluate_grid_density_combinations import ROOT, build, indices, key, pooled_metrics, role


class CombinationDensityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan=json.loads((ROOT/'evaluation/grid_density_combinations_plan.json').read_bytes())
        cls.batches=json.loads((ROOT/cls.plan['source']).read_bytes())
        cls.refs={key(t):json.loads((ROOT/cls.plan['referenceModels'].format(combination=key(t))).read_bytes()) for t in cls.plan['trainingSets']}

    def test_all_overlap_roles_and_counts(self):
        counts={'held_out_only':0,'same_pass_only':0,'mixed':0}
        for train in self.plan['trainingSets']:
            for test in self.plan['evaluationSets']:
                r=role(train,test);counts[r]+=1
                self.assertEqual(r=='held_out_only',set(train).isdisjoint(test))
                self.assertEqual(r=='same_pass_only',set(test)<=set(train))
        self.assertEqual(counts,{'held_out_only':12,'same_pass_only':19,'mixed':18})
        self.assertEqual(role([1],[1,2]),'mixed')
        self.assertEqual(role([1,2,3],[1,2,3]),'same_pass_only')

    def test_full_density_matches_all_frozen_A_models(self):
        for train in self.plan['trainingSets']:
            ref=self.refs[key(train)];model=build(ref,self.batches,train,13,21)
            self.assertEqual(model['fieldsUT'],ref['fieldsUT'])
            self.assertEqual(set(model['trainingTrialIDs']),set(ref['trainingTrialIDs']))

    def test_selected_passes_and_anchors_are_the_only_field_inputs(self):
        for train in ([2],[3],[1,3]):
            before=build(self.refs[key(train)],self.batches,train,3,5)
            changed=copy.deepcopy(self.batches)
            for b in changed:
                for p in b['points']:
                    if b['repetition'] not in train or p['row'] not in indices(13,3) or p['column'] not in indices(21,5):
                        p['deltaUT']=[999,999,999]
                    # No test feature, target XY or causal sample is used to fit fields.
                    p['raw']=[777,777,777];p['xy']=[999,999];p['causalFrames']=[]
            self.assertEqual(before,build(self.refs[key(train)],changed,train,3,5))
            self.assertEqual(len(before['trainingTrialIDs']),15*len(train))
            excluded={b['session'] for b in self.batches if b['repetition'] not in train}
            self.assertTrue(set(before['sourceSessions']).isdisjoint(excluded))

    def test_repeat_aggregation_is_componentwise_median(self):
        changed=copy.deepcopy(self.batches)
        values={1:[0,5,20],2:[2,100,10],3:[10,6,0]}
        for b in changed:
            for p in b['points']:p['deltaUT']=values[b['repetition']]
        self.assertEqual(build(self.refs['12'],changed,[1,2],3,3)['fieldsUT'][0][0],[1,52.5,15])
        self.assertEqual(build(self.refs['123'],changed,[1,2,3],3,3)['fieldsUT'][0][0],[2,6,10])

    def test_pooled_quantiles_use_individual_predictions(self):
        rows=[dict(passID=p,errorMM=e,accepted=True,shown=True,fittedPlacement=False)
              for p,errors in [(1,[0,0,0]),(2,[1,100,100]),(3,[999])] for e in errors]
        m=pooled_metrics(rows,[1],[1,2])
        self.assertEqual(m['count'],6);self.assertEqual(m['medianRadialErrorMM'],.5)
        self.assertNotEqual(m['medianRadialErrorMM'],st.mean([0,100]))
        self.assertEqual(m['within2p5Rate'],4/6)
        self.assertEqual(m['role'],'mixed');self.assertEqual(m['samePassPlacements'],3);self.assertEqual(m['heldOutPlacements'],3)

    def test_duplicate_or_missing_placements_fail(self):
        changed=copy.deepcopy(self.batches)
        target=next(b for b in changed if b['repetition']==2 and b['row']==1)
        target['points'].append(copy.deepcopy(target['points'][0]))
        with self.assertRaises(ValueError):build(self.refs['2'],changed,[2],3,3)
        with self.assertRaises(ValueError):build(self.refs['2'],self.batches,[2,2],3,3)


if __name__=='__main__':unittest.main()
