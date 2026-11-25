import copy
import json
from pathlib import Path
import sys
import unittest

import numpy as np
from sklearn.svm import SVC
from sklearn.ensemble import GradientBoostingClassifier

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from experiment_model_d import ROOT, fit, predict, raw_predict, training_arrays, evaluate, trial_id
from train_joint_mlp import load_records
from compare_model_d import build_b, evaluate_b, load_old


class ModelDTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan=json.loads((ROOT/'evaluation/model_d_balanced_plan.json').read_bytes())
        cls.records,_=load_records(ROOT/'reports/hover3-20261125-pass2',(1,2))

    def test_svm_export_matches_reference_library(self):
        train=[r for r in self.records if r['row']<=3]
        config=dict(representation='mixed',metric='noise_whitened',bandwidth=8,ridge=10)
        model=fit(train,config,self.plan)
        x,y,_=training_arrays(train,'mixed');transform=np.array(model['transform'])
        ref=SVC(C=10,gamma=1/128,class_weight='balanced').fit(x@transform,y)
        queries=np.array([r['primary'] for r in self.records[::17]])
        np.testing.assert_allclose(raw_predict(model,queries)['score'],ref.decision_function(queries@transform),atol=1e-8)

    def test_tree_export_matches_reference_library(self):
        train=[r for r in self.records if r['row']<=3]
        config=dict(representation='mixed',metric='isotropic',bandwidth=3,ridge=100)
        model=fit(train,config,dict(self.plan,candidateFamily='boost'))
        x,y,_=training_arrays(train,'mixed');weights=np.where(y>0,len(y)/(2*np.sum(y>0)),len(y)/(2*np.sum(y<0)))
        ref=GradientBoostingClassifier(n_estimators=100,max_depth=3,learning_rate=.05,min_samples_leaf=10,random_state=20261125).fit(x,y,sample_weight=weights)
        queries=np.array([r['primary'] for r in self.records[::17]])
        np.testing.assert_allclose(raw_predict(model,queries)['score'],2*ref.predict_proba(queries)[:,1]-1,atol=1e-8)

    def test_prototype_guard_matches_existing_B_predictions(self):
        train=[r for r in self.records if r['contact'] or r['passID']==1]
        test=[r for r in self.records if not r['contact'] and r['passID']==2][::7]
        actual=evaluate_b(train,test)
        refs={trial_id(r):r for r in load_old()['1']['B'] if r['mode']=='primary'}
        for r in actual:
            ref=refs[trial_id(r)]
            self.assertEqual(r['predicted'],ref['predicted'])
            self.assertAlmostEqual(r['airResidualUT'],ref['airResidualUT'],places=8)
            self.assertAlmostEqual(r['contactResidualUT'],ref['contactResidualUT'],places=8)
            np.testing.assert_allclose(r['xy'],ref['xy'],atol=1e-8)

    def test_selected_models_exclude_outer_trial_and_session(self):
        folder=ROOT/'reports/model-d-20261125-hybrid'
        for file in folder.glob('*-model.json'):
            if file.name=='final-model.json':continue
            model=json.loads(file.read_bytes());name=file.name.removesuffix('-model.json')
            report=json.loads((folder/(name+'-summary.json')).read_bytes())
            self.assertFalse(set(model['trainingTrialIDs'])&set(report['testTrials']))
            self.assertFalse({s.rsplit('/',1)[0] for s in model['trainingTrialIDs']}&{s.rsplit('/',1)[0] for s in report['testTrials']})
            if name.startswith('rowfold'):
                tr=[r for r in self.records if trial_id(r) in model['trainingTrialIDs']]
                te=[r for r in self.records if trial_id(r) in report['testTrials']]
                self.assertFalse({r['row'] for r in tr}&{r['row'] for r in te})

    def test_predictions_do_not_depend_on_truth_or_future_queries(self):
        model=json.loads((ROOT/'reports/model-d-20261125-hybrid/final-model.json').read_bytes())
        records=copy.deepcopy(self.records[::101]);original=evaluate(model,records)
        for r in records:
            r['xy']=[1-r['xy'][0],1-r['xy'][1]];r['contact']=not r['contact'];r['state']='air' if r['contact'] else 'contact'
            r['row']=99;r['column']=99;r['passID']=99
        altered=evaluate(model,records)
        for a,b in zip(original,altered):
            self.assertEqual(a['predicted'],b['predicted']);np.testing.assert_allclose(a['xy'],b['xy'])
        q=[r['primary'] for r in records]
        one,decision=predict(model,q[:1]);many,decisions=predict(model,q+[[10000,0,0]])
        self.assertEqual(decision[0],decisions[0]);np.testing.assert_allclose(one['xy'][0],many['xy'][0],atol=1e-8)
        _,invalid=predict(model,[[0,0,0],[10000,0,0]])
        np.testing.assert_array_equal(invalid,[0,0])
        with self.assertRaises(ValueError):predict(model,[[float('nan'),0,0]])


if __name__=='__main__':unittest.main()
