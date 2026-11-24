import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from analyze_height_condition import prototypes, classify, classification_summary, feature


class HeightConditionTests(unittest.TestCase):
    def test_whole_row_exclusion_and_class_balance(self):
        batches=[]
        for repetition in (1,2,3):
            for row in (1,2):
                session=f'p{repetition}-r{row}'
                batches.append(dict(row=row,repetition=repetition,points=[dict(row=row,column=1,
                    xy=[0,row],session=session,trial='hold',deltaUT=[repetition,row,10])]))
        hover=copy.deepcopy(batches[:2])
        for b in hover:
            for p in b['points']:p.update(session='air-'+p['session'],deltaUT=[0,b['row'],20])
        train=prototypes(batches,hover,[1,3],excluded_row=1)
        self.assertEqual(len(train),2)
        self.assertEqual({p['state'] for p in train},{'contact','air'})
        self.assertTrue(all(p['row']==2 for p in train))
        self.assertTrue(all('r1' not in t and 'p2' not in t for p in train for t in p['trainingTrials']))
        self.assertEqual(next(p['field'] for p in train if p['state']=='contact'),[2,2,10])

    def test_test_feature_never_uses_future_background_or_target(self):
        p=dict(raw=[12,24,36],deltaUT=[0,0,0],xy=[1,1])
        b=dict(before=dict(raw=[2,4,6]),after=dict(raw=[1,2,3]))
        old=feature(p,b,'before')
        p.update(deltaUT=[999,999,999],xy=[0,0]);b['after']['raw']=[999,999,999]
        self.assertEqual(feature(p,b,'before'),old)
        self.assertEqual(old,[10,20,30])

    def test_ties_and_unequal_test_class_counts(self):
        train=[dict(state='air',field=[0,0,0]),dict(state='contact',field=[2,0,0])]
        self.assertEqual(classify([1,0,0],train)['predicted'],'tie')
        self.assertEqual(classify([0,0,0],train)['predicted'],'air')
        rows=[dict(truth='air',predicted='contact')]+[dict(truth='contact',predicted='contact')]*3
        self.assertEqual(classification_summary(rows)['balancedAccuracy'],.5)


if __name__=='__main__':unittest.main()
