"""Offline, nested group evaluation of experimental model D. Run from research/.

Only three magnetic components enter predict(). Metadata is used exclusively
for training labels, split membership, provenance and evaluation.
"""
import argparse
import hashlib
import itertools
import json
import os
from pathlib import Path

os.environ.setdefault('VECLIB_MAXIMUM_THREADS', '1')
import numpy as np

from train_joint_mlp import ROOT, load_records, save


def trial_id(r):
    return r['session'] + '/' + r['trial']


def distance2(x, y):
    return np.maximum(np.sum(x*x, axis=1)[:, None] + np.sum(y*y, axis=1)[None, :] - 2*x@y.T, 0)


def training_arrays(records, representation):
    fields, labels, xy = [], [], []
    for r in records:
        fs = ([r['primary']] if representation == 'primary' else
              [r['fields'][0]] if representation == 'corrected' else
              [r['primary'], r['fields'][0]])
        for f in fs:
            fields.append(f); labels.append(1 if r['contact'] else -1); xy.append(r['xy'])
    return np.array(fields), np.array(labels), np.array(xy)


def fit(records, config, plan):
    if plan.get('candidateFamily')=='forward':
        from experiment_forward_height import fit_forward
        return fit_forward(records,config,plan)
    x, y, xy = training_arrays(records, config['representation'])
    weights = np.where(y > 0, len(y)/(2*np.sum(y > 0)), len(y)/(2*np.sum(y < 0)))
    mean = np.average(x, weights=weights, axis=0)
    std = np.sqrt(np.average((x-mean)**2, weights=weights, axis=0))
    scale = np.ones(3) if config['metric'] == 'isotropic' else np.maximum(std, .1)/np.exp(np.log(np.maximum(std,.1)).mean())
    transform=np.diag(1/scale)
    if config['metric']=='noise_whitened':
        shifts=np.array([np.array(r['primary'])-r['fields'][0] for r in records])
        cov=shifts.T@shifts/len(shifts)+np.eye(3)*.25
        values,vectors=np.linalg.eigh(cov)
        transform=(vectors/np.sqrt(values)[None,:])@vectors.T*np.exp(np.log(values).mean()/2)
    intercept=0.
    trees=None
    if plan.get('candidateFamily')=='boost':
        from sklearn.ensemble import GradientBoostingClassifier
        clf=GradientBoostingClassifier(n_estimators=int(config['ridge']),max_depth=int(config['bandwidth']),learning_rate=.05,
            min_samples_leaf=10,random_state=20261125)
        clf.fit(x,y,sample_weight=weights)
        trees=[dict(left=t[0].tree_.children_left.tolist(),right=t[0].tree_.children_right.tolist(),feature=t[0].tree_.feature.tolist(),
            threshold=t[0].tree_.threshold.tolist(),value=t[0].tree_.value[:,0,0].tolist()) for t in clf.estimators_]
        intercept=float(clf._raw_predict_init(x[:1])[0,0]);centers=x;alpha=np.zeros(len(x))
    elif plan.get('candidateFamily')=='svm':
        from sklearn.svm import SVC
        clf=SVC(C=config['ridge'],gamma=1/(2*config['bandwidth']**2),class_weight='balanced',cache_size=256)
        clf.fit(x@transform,y)
        centers=x[clf.support_];alpha=clf.dual_coef_[0];intercept=float(clf.intercept_[0])
    else:
        kernel = np.exp(-distance2(x@transform, x@transform)/(2*config['bandwidth']**2))
        kernel.flat[::len(x)+1] += config['ridge']/weights
        alpha = np.linalg.solve(kernel, y);centers=x
    # XY is its own local regression task; never route by a known target/height.
    loc_x, _, loc_y = training_arrays(records, 'mixed')
    return dict(version=1, method='rbf_height_local_affine_xy', config=config,
        scale=scale.tolist(),transform=transform.tolist(), centers=centers.tolist(), coefficients=alpha.tolist(),intercept=intercept,
        classifierFamily=plan.get('candidateFamily'),trees=trees,
        localFields=loc_x.tolist(), localXY=loc_y.tolist(),
        neighbors=plan['localXYNeighbors'], localRidge=plan['localXYRidge'],
        minimumSignalUT=plan['minimumSignalUT'], supportLimitUT=plan['supportLimitUT'],
        margin=0, trainingTrialIDs=sorted(trial_id(r) for r in records),
        sourceSessions=sorted({r['session'] for r in records}))


def local_xy(model, fields):
    x = np.asarray(model['localFields']); y = np.asarray(model['localXY'])
    ds = distance2(fields,x); k = min(model['neighbors'], len(x))
    ids = np.argpartition(ds, k-1, axis=1)[:,:k]
    local = x[ids]-fields[:,None,:]
    radius = np.maximum(np.sqrt(np.take_along_axis(ds,ids,1).max(axis=1)), .25)
    design = np.concatenate([np.ones((*local.shape[:2],1)),local/radius[:,None,None]], axis=2)
    weight = np.exp(-np.sum(local*local,axis=2)/(2*(radius[:,None]/2)**2))
    normal = np.einsum('nki,nk,nkj->nij',design,weight,design)
    normal += np.diag([1e-8, model['localRidge'], model['localRidge'], model['localRidge']])[None,:,:]
    rhs = np.einsum('nki,nk,nkj->nij',design,weight,y[ids])
    return np.linalg.solve(normal,rhs)[:,0,:], np.sqrt(ds.min(axis=1))


def raw_predict(model, fields, include_xy=True):
    q = np.asarray(fields, dtype=float)
    if q.ndim != 2 or q.shape[1] != 3 or not np.isfinite(q).all():
        raise ValueError('Expected finite N x 3 magnetic fields')
    if model['method']=='smooth_forward_height_local_affine_xy':
        from experiment_forward_height import predict_forward
        return predict_forward(model,q,include_xy)
    x = np.asarray(model['centers']); scale = np.asarray(model['scale'])
    transform=np.array(model.get('transform',np.diag(1/scale)))
    if model.get('trees'):
        scores=np.full(len(q),model['intercept'])
        for tree in model['trees']:
            nodes=np.zeros(len(q),dtype=int);left=np.array(tree['left']);right=np.array(tree['right']);feature=np.array(tree['feature']);threshold=np.array(tree['threshold']);value=np.array(tree['value'])
            while np.any(left[nodes]!=-1):
                mask=left[nodes]!=-1;ix=np.flatnonzero(mask);n=nodes[mask]
                nodes[mask]=np.where(q[ix,feature[n]]<=threshold[n],left[n],right[n])
            scores+=.05*value[nodes]
        scores=2/(1+np.exp(-scores))-1
    else:
        scores = np.exp(-distance2(q@transform,x@transform)/(2*model['config']['bandwidth']**2)) @ np.asarray(model['coefficients'])+model.get('intercept',0.)
    if include_xy:
        xy, support = local_xy(model,q)
    else:
        xy = np.full((len(q),2),.5)
        support = np.sqrt(distance2(q,np.asarray(model['localFields'])).min(axis=1))
    return dict(score=scores, xy=xy, support=support, signal=np.linalg.norm(q,axis=1))


def decisions(raw, margin, plan):
    accepted = ((np.abs(raw['score']) >= margin) & (raw['support'] <= plan['supportLimitUT']) &
                (raw['signal'] >= plan['minimumSignalUT']) & np.all((raw['xy'] >= -.05) & (raw['xy'] <= 1.05),axis=1))
    return np.where(accepted,np.where(raw['score']>=0,1,-1),0)


def predict(model, fields):
    """Public inference boundary: fields only, never records or target metadata."""
    raw=raw_predict(model,fields);pred=decisions(raw,model['margin'],model)
    if model.get('prototypeGuard'):
        from build_knn_model import Projector
        air=Projector(model['prototypeGuard']['air']);contact=Projector(model['prototypeGuard']['contact'])
        for i,f in enumerate(fields):
            a,c=air.project(f),contact.project(f)
            state=-1 if a['residualUT']<c['residualUT'] else 1;best=a if state==-1 else c
            confident=best['accepted'] and abs(a['residualUT']-c['residualUT'])>.75
            if confident and pred[i]==0:
                pred[i]=state;raw['xy'][i]=best['xy']
            elif confident and pred[i]!=state:
                pred[i]=0
    return raw,pred


def metrics(rows):
    def group(rs):
        err = np.array([r['errorMM'] for r in rs]); n = len(rs)
        correct = sum(r['predicted'] == r['truth'] for r in rs)
        wrong = sum(r['predicted'] not in (r['truth'],'uncertain') for r in rs)
        reject = n-correct-wrong
        return dict(count=n,correct=correct,wrong=wrong,abstain=reject,
            correctRate=correct/n, wrongRate=wrong/n, coverage=(correct+wrong)/n,
            selectiveError=wrong/(correct+wrong) if correct+wrong else None,
            medianXY=float(np.median(err)),p95XY=float(np.percentile(err,95)),
            joint2p5=sum(r['predicted']==r['truth'] and r['errorMM']<=2.5 for r in rs),
            joint5=sum(r['predicted']==r['truth'] and r['errorMM']<=5 for r in rs))
    return {s:group([r for r in rows if r['truth']==s]) for s in ('air','contact') if any(r['truth']==s for r in rows)}


def evaluate(model, records, mode='primary'):
    items = [(r,f) for r in records for f in ([r['primary']] if mode=='primary' else r['causal'])]
    raw,pred=predict(model,[f for _,f in items])
    rows=[]
    for i,((r,f),s) in enumerate(zip(items,pred)):
        rows.append(dict(session=r['session'],trial=r['trial'],truth=r['state'],passID=r['passID'],row=r['row'],column=r['column'],
            targetXY=r['xy'],field=f,xy=raw['xy'][i].tolist(),score=float(raw['score'][i]),
            supportUT=float(raw['support'][i]),signalUT=float(raw['signal'][i]),
            predicted={-1:'air',0:'uncertain',1:'contact'}[int(s)],
            errorMM=float(np.linalg.norm((raw['xy'][i]-r['xy'])*[50,30]))))
    return rows


def configs(plan):
    return [dict(representation=r,metric=m,bandwidth=b,ridge=l) for r,m,b,l in itertools.product(
        plan['representations'],plan['metrics'],plan['bandwidthsUT'],plan['ridge'])]


def select(records, plan):
    """Whole rows of BOTH heights/passes stay together; no outer test access."""
    trials=[]
    for config in configs(plan):
        scores=[]; labels=[]; guards=[]
        for fold in range(3):
            tr=[r for r in records if (r['row']-1)%3!=fold]
            va=[r for r in records if (r['row']-1)%3==fold]
            assert set(trial_id(r) for r in tr).isdisjoint(trial_id(r) for r in va)
            assert {r['row'] for r in tr}.isdisjoint(r['row'] for r in va)
            model=fit(tr,config,plan)
            raw=raw_predict(model,[r['primary'] for r in va],include_xy=False)
            scores.extend(raw['score']); labels.extend(1 if r['contact'] else -1 for r in va)
            guards.extend((raw['support']<=plan['supportLimitUT']) & (raw['signal']>=plan['minimumSignalUT']))
        score=np.array(scores); truth=np.array(labels); guard=np.array(guards)
        for margin in plan['scoreRejectMargins']:
            pred=np.where(guard & (np.abs(score)>=margin),np.where(score>=0,1,-1),0)
            losses=[]
            for s in (-1,1):
                p=pred[truth==s]; losses.append(float(np.mean((p!=0)&(p!=s))+.35*np.mean(p==0)))
            trials.append(dict(config=config,margin=margin,balancedCost=float(np.mean(losses)),
                airCost=losses[0],contactCost=losses[1]))
    trials.sort(key=lambda r:(r['balancedCost'],r['margin'],r['config']['bandwidth']))
    choice=trials[0]; model=fit(records,choice['config'],plan);model['margin']=choice['margin']
    model['selection']=choice
    return model,trials


def assert_split(train,test):
    assert set(map(trial_id,train)).isdisjoint(map(trial_id,test))
    assert {r['session'] for r in train}.isdisjoint(r['session'] for r in test)


def save_experiment(out,name,train,test,plan):
    assert_split(train,test)
    model,selection=select(train,plan)
    pred=evaluate(model,test); causal=evaluate(model,test,'causal')
    result=dict(name=name,selection=model['selection'],trainTrials=model['trainingTrialIDs'],
        testTrials=sorted(map(trial_id,test)),primary=metrics(pred),causal=metrics(causal))
    save(out/(name+'-model.json'),model);save(out/(name+'-selection.json'),selection)
    save(out/(name+'-predictions.json'),pred);save(out/(name+'-causal.json'),causal)
    save(out/(name+'-summary.json'),result)
    print(json.dumps(dict(name=name,selection=model['selection'],primary=result['primary'])),flush=True)
    return result


def run(out,plan_path,stage):
    plan=json.loads(plan_path.read_bytes()); records,inventory=load_records(ROOT/plan['source'],(1,2))
    out.mkdir(parents=True,exist_ok=True)
    if not (out/'plan.json').exists():
        save(out/'plan.json',plan);save(out/'inventory.json',inventory)
    assert json.loads((out/'plan.json').read_bytes())==plan
    results={}
    if stage in ('crosspass','all'):
        for a in (1,2):
            train=[r for r in records if r['contact'] or r['passID']==a]
            test=[r for r in records if not r['contact'] and r['passID']!=a]
            name=f'air{a}-to-air{3-a}'
            if not (out/(name+'-summary.json')).exists():
                save_experiment(out,name,train,test,plan)
    if stage in ('paired','all'):
        for c,a in itertools.product((1,3),(1,2)):
            train=[r for r in records if r['passID']==(c if r['contact'] else a)]
            test=[r for r in records if r['passID']!=(c if r['contact'] else a)]
            name=f'paired-contact{c}-air{a}'
            if not (out/(name+'-summary.json')).exists():
                save_experiment(out,name,train,test,plan)
    if stage in ('spatial','all'):
        for fold in range(5):
            train=[r for r in records if (r['row']-1)%5!=fold]
            test=[r for r in records if (r['row']-1)%5==fold]
            name=f'rowfold{fold}'
            if not (out/(name+'-summary.json')).exists():
                save_experiment(out,name,train,test,plan)
    if stage in ('final','all'):
        model,selection=select(records,plan)
        model['planSHA256']=hashlib.sha256(plan_path.read_bytes()).hexdigest();model['sourceInventory']=inventory
        save(out/'final-model.json',model);save(out/'final-selection.json',selection)
        pred=evaluate(model,records);save(out/'final-replay.json',pred)
        save(out/'final-summary.json',dict(role='training_replay_not_independent_validation',selection=model['selection'],metrics=metrics(pred)))
        print(json.dumps(dict(name='final-replay',selection=model['selection'],metrics=metrics(pred))),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--plan',type=Path,default=ROOT/'evaluation/model_d_plan.json')
    p.add_argument('--stage',choices=('crosspass','paired','spatial','final','all'),default='all')
    args=p.parse_args();run(args.out,args.plan,args.stage)
