import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import numpy as np
from train_joint_mlp import ROOT,arrays,initialize,loss_grad,row_split,load_records


class JointMLPTests(unittest.TestCase):
    def setUp(self):
        self.plan=json.loads((ROOT/'evaluation/joint_mlp_plan.json').read_bytes())

    def test_both_tasks_backpropagate_into_shared_layers(self):
        plan={**self.plan,'layers':[3,4,4,3]}
        params=initialize(plan);rng=np.random.default_rng(1)
        x=rng.normal(size=(6,3));y=rng.normal(size=(6,3));y[:,2]=[0,0,1,1,1,1]
        w=np.array([.25,.25,.125,.125,.125,.125])
        _,grads=loss_grad(x,y,w,params,plan)
        eps=1e-6
        for layer,p in enumerate(params):
            for ix in [tuple(0 for _ in p.shape),tuple(n-1 for n in p.shape)]:
                original=p[ix];p[ix]=original+eps;high=loss_grad(x,y,w,params,plan)[0]
                p[ix]=original-eps;low=loss_grad(x,y,w,params,plan)[0];p[ix]=original
                self.assertAlmostEqual(grads[layer][ix],(high-low)/(2*eps),places=7)
        _,xy_only=loss_grad(x,y,w,params,{**plan,'contactLossWeight':0})
        self.assertGreater(np.linalg.norm(grads[0]-xy_only[0]),1e-6)
        changed=y.copy();changed[:,:2]+=1
        _,other=loss_grad(x,changed,w,params,plan)
        self.assertGreater(np.linalg.norm(grads[0]-other[0]),1e-6)

    def test_real_sources_balance_and_whole_row_split(self):
        records,_=load_records(ROOT/'reports/hover3-20261125-pass1')
        x,y,w=arrays(records)
        self.assertEqual(x.shape,(3276,3))
        self.assertAlmostEqual(w[y[:,2]==0].sum(),.5)
        self.assertAlmostEqual(w[y[:,2]==1].sum(),.5)
        self.assertEqual({r['passID'] for r in records if r['contact']},{1,3})
        seen=[]
        for fold in range(5):
            train,test=row_split(records,fold)
            self.assertFalse({r['session'] for r in train}&{r['session'] for r in test})
            seen += [r['session']+'/'+r['trial'] for r in test]
        self.assertEqual(len(seen),819);self.assertEqual(len(set(seen)),819)


if __name__=='__main__': unittest.main()
