import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from compare_pass_combinations import evaluation_role, predict_pass, summarize


class IdentityProjector:
    def project(self,field):
        return dict(xy=field[:2],accepted=True,shown=True,ambiguous=False)


class PassCombinationTests(unittest.TestCase):
    def test_holdout_is_never_training_pass(self):
        for train in ([1],[2],[3],[1,2],[2,3],[1,3],[1,2,3]):
            for test in (1,2,3):
                self.assertEqual(evaluation_role(train,test)=='held_out_pass',test not in train)
        self.assertTrue(all(evaluation_role([1,2,3],p)=='training_replay' for p in (1,2,3)))

    def test_rejected_close_estimate_counts_as_failure(self):
        rows=[dict(errorMM=0,accepted=False,shown=True,ambiguous=True),
              dict(errorMM=2,accepted=True,shown=True,ambiguous=False)]
        result=summarize(rows)
        self.assertEqual(result['successWithin2p5MM'],.5)
        self.assertEqual(result['acceptedDisplayRate'],.5)
        self.assertEqual(result['count'],2)

    def test_primary_does_not_use_end_background_or_training_delta(self):
        # Full geometry makes the same production per-region/per-row aggregation run.
        batches=[]
        for row in range(1,14):
            points=[]
            for col in range(1,22):
                xy=[(col-1)/20,(row-1)/12]
                points.append(dict(trial=f'{row}-{col}',row=row,column=col,xy=xy,raw=xy+[1],deltaUT=xy+[1],
                                   causalFrames=[dict(filteredDeltaUT=xy+[1]) for _ in range(3)]))
            batches.append(dict(session=str(row),before=dict(raw=[0,0,0]),points=points))
        _,before=predict_pass(IdentityProjector(),batches)
        altered=copy.deepcopy(batches)
        for batch in altered:
            batch['after']=dict(raw=[99,99,99])
            for p in batch['points']:p['deltaUT']=[.5,.5,1]
        _,after=predict_pass(IdentityProjector(),altered)
        self.assertEqual(before['primary'],after['primary'])
        self.assertEqual(before['causal'],after['causal'])
        self.assertNotEqual(before['offline'],after['offline'])
        self.assertEqual(len(before['primary']),273)
        self.assertEqual(len(before['causal']),819)


if __name__=='__main__':unittest.main()
