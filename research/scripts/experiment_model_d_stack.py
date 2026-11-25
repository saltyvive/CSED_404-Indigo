"""Out-of-fold magnetic expert stacking, with a held-out row/pass outer test."""
import argparse
import contextlib
import io
import json
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
import joblib

from train_joint_mlp import ROOT, load_records, fit as fit_c, predict as predict_c, save
from experiment_model_d import fit, raw_predict, evaluate, metrics, trial_id, distance2, assert_split


def fit_experts(records,plan):
    cfg=plan['expertSVM']
    d=fit(records,dict(representation=cfg['representation'],metric=cfg['metric'],bandwidth=cfg['bandwidth'],ridge=cfg['C']),dict(plan,candidateFamily='svm'))
    cp=json.loads((ROOT/'evaluation/joint_mlp_air12_plan.json').read_bytes())
    cp['airPasses']=sorted({r['passID'] for r in records if not r['contact']})
    with contextlib.redirect_stdout(io.StringIO()):
        c,_=fit_c(records,cp,'stack C expert')
    c['conditions']=[dict(state=s,passes=sorted({r['passID'] for r in records if r['state']==s})) for s in ('air','contact')]
    b=[]
    for s in ('air','contact'):
        rs=[r for r in records if r['state']==s]
        b.append(dict(fields=[f for r in rs for f in r['fields']],xy=[r['xy'] for r in rs for f in r['fields']],
                      residualLimit=max(3,5*max(r['noiseUT'] for r in rs))))
    return dict(d=d,c=c,b=b)


def features(experts, fields):
    q=np.array(fields);d=raw_predict(experts['d'],q)
    c=predict_c(experts['c'],fields)
    logits=np.array([np.log(max(r['contactScore'],1e-8)/max(1-r['contactScore'],1e-8)) for r in c])
    residuals=[]
    for b in experts['b']:
        residuals.append(np.sqrt(distance2(q,np.array(b['fields'])).min(axis=1)))
    a,b=residuals
    scores=np.column_stack([np.clip(d['score'],-4,4),np.clip(logits,-6,6),np.clip(a-b,-5,5)])
    x,y=d['xy'].T
    feature=np.column_stack([scores,x,y,x*y,x*x,y*y,scores*x[:,None],scores*y[:,None],np.minimum(a,10),np.minimum(b,10)])
    return feature,d,c


def meta_fit(x,y,family,C):
    if family=='logistic':
        m=make_pipeline(StandardScaler(),LogisticRegression(C=C,class_weight='balanced',max_iter=2000))
        m.fit(x,y)
    else:
        m=HistGradientBoostingClassifier(max_iter=120,max_leaf_nodes=int(C),learning_rate=.05,l2_regularization=1,
            min_samples_leaf=20,early_stopping=False,random_state=20261125,class_weight='balanced')
        m.fit(x,y)
    return m


def train(records,plan):
    oo=[]
    for fold in range(3):
        tr=[r for r in records if (r['row']-1)%3!=fold];va=[r for r in records if (r['row']-1)%3==fold]
        assert_split(tr,va)
        expert=fit_experts(tr,plan);f,_,_=features(expert,[r['primary'] for r in va])
        oo.extend((r,ff.tolist()) for r,ff in zip(va,f))
    X=np.array([f for r,f in oo]);y=np.array([r['contact'] for r,f in oo]);groups=np.array([r['row']%3 for r,f in oo])
    options=[]
    for family,cs in [('logistic',[.1,1,10]),('boost',[3,7,15])]:
        for cc in cs:
            probs=np.zeros(len(y))
            for fold in range(3):
                mask=groups!=fold;m=meta_fit(X[mask],y[mask],family,cc);probs[~mask]=m.predict_proba(X[~mask])[:,1]
            pred=probs>=.5;abst=np.abs(probs-.5)<.1
            cost=np.mean([np.mean((pred[y==s]!=s)&~abst[y==s])+.35*np.mean(abst[y==s]) for s in (False,True)])
            options.append(dict(family=family,C=cc,cost=float(cost)))
    choice=min(options,key=lambda z:z['cost']);meta=meta_fit(X,y,choice['family'],choice['C'])
    expert=fit_experts(records,plan)
    return dict(expert=expert,meta=meta,choice=choice,choices=options,trainingTrialIDs=sorted(map(trial_id,records)))


def predict(model,records,mode='primary'):
    items=[(r,f) for r in records for f in ([r['primary']] if mode=='primary' else r['causal'])]
    fs=[f for _,f in items];X,d,c=features(model['expert'],fs);p=model['meta'].predict_proba(X)[:,1]
    out=[];crows=[]
    for i,((r,f),prob) in enumerate(zip(items,p)):
        accepted=abs(prob-.5)>=.1 and d['support'][i]<=6 and d['signal'][i]>=3 and np.all((d['xy'][i]>=-.05)&(d['xy'][i]<=1.05))
        shared=dict(session=r['session'],trial=r['trial'],truth=r['state'],passID=r['passID'],row=r['row'],column=r['column'],targetXY=r['xy'],field=f)
        out.append(dict(**shared,xy=d['xy'][i].tolist(),score=float(prob),predicted=('contact' if prob>=.5 else 'air') if accepted else 'uncertain',
            errorMM=float(np.linalg.norm((d['xy'][i]-r['xy'])*[50,30]))))
        crows.append(dict(**shared,predicted=c[i]['predicted'],xy=c[i]['xy'],errorMM=float(np.linalg.norm((np.array(c[i]['xy'])-r['xy'])*[50,30]))))
    return out,crows


def run(out,stage):
    out.mkdir(parents=True,exist_ok=True)
    plan=json.loads((ROOT/'evaluation/model_d_stack_plan.json').read_bytes())
    if (out/'plan.json').exists():assert json.loads((out/'plan.json').read_bytes())==plan
    else:save(out/'plan.json',plan)
    records,inv=load_records(ROOT/plan['source'],(1,2));save(out/'inventory.json',inv)
    splits=[]
    if stage in ('crosspass','all'):
        for a in (1,2):
            splits.append((f'air{a}-to-air{3-a}',[r for r in records if r['contact'] or r['passID']==a],[r for r in records if not r['contact'] and r['passID']!=a]))
    if stage in ('paired','all'):
        for c in (1,3):
            for a in (1,2):
                splits.append((f'paired-contact{c}-air{a}',[r for r in records if r['passID']==(c if r['contact'] else a)],[r for r in records if r['passID']!=(c if r['contact'] else a)]))
    if stage in ('spatial','all'):
        for fold in range(5):
            splits.append((f'rowfold{fold}',[r for r in records if (r['row']-1)%5!=fold],[r for r in records if (r['row']-1)%5==fold]))
    if stage in ('final','all'):splits.append(('final',records,records))
    for name,tr,te in splits:
        if (out/(name+'-summary.json')).exists():continue
        if name!='final':assert_split(tr,te)
        m=train(tr,plan);pred,cp=predict(m,te);causal,_=predict(m,te,'causal')
        save(out/(name+'-experts.json'),m['expert']);joblib.dump(m['meta'],out/(name+'-meta.joblib'))
        save(out/(name+'-predictions.json'),pred);save(out/(name+'-C.json'),cp);save(out/(name+'-causal.json'),causal)
        summary=dict(name=name,choice=m['choice'],choices=m['choices'],trainTrials=m['trainingTrialIDs'],testTrials=sorted(map(trial_id,te)),primary=metrics(pred),C=metrics(cp),causal=metrics(causal))
        save(out/(name+'-summary.json'),summary);print(json.dumps({k:summary[k] for k in ('name','choice','primary','C')}),flush=True)


if __name__=='__main__':
    from pathlib import Path
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--stage',default='all')
    args=p.parse_args();run(args.out,args.stage)
