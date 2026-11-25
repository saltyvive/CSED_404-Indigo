"""Matched baselines, expert-complementarity and regional diagnostics for D."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import numpy as np
from train_joint_mlp import ROOT, load_records, fit as fit_c, evaluate as evaluate_c, save
from experiment_model_d import metrics, trial_id
from build_knn_model import Projector


def build_b(records):
    plan=json.loads((ROOT/'evaluation/knn_plan.json').read_bytes())
    groups={}
    for r in records:
        p=groups.setdefault(tuple(r['xy']),dict(xy=r['xy'],fieldsUT=[]));p['fieldsUT']+=r['fields']
    locs=sorted(groups.values(),key=lambda p:(p['xy'][1],p['xy'][0]))
    return dict(locations=locs,k=4,distanceFloorUT=1e-6,weightPower=2,localRadiusMM=7.5,
        ambiguityDistance=.2,ambiguityMarginUT=.75,residualLimitUT=max(3,5*max(r['noiseUT'] for r in records)),
        minimumSignalUT=max(3,.2*min(np.linalg.norm(f) for r in records for f in r['fields'])),printedGridContext=dict(widthMM=50,heightMM=30))


def evaluate_b(train,test,mode='primary'):
    projectors=[Projector(build_b([r for r in train if r['state']==s])) for s in ('air','contact')]
    output=[]
    for r in test:
        for f in ([r['primary']] if mode=='primary' else r['causal']):
            a,c=[p.project(f) for p in projectors];candidate='air' if a['residualUT']<c['residualUT'] else 'contact'
            best=a if candidate=='air' else c
            accepted=best['accepted'] and abs(a['residualUT']-c['residualUT'])>.75
            output.append(dict(session=r['session'],trial=r['trial'],truth=r['state'],passID=r['passID'],row=r['row'],column=r['column'],
                targetXY=r['xy'],field=f,xy=best['xy'],predicted=candidate if accepted else 'uncertain',
                airResidualUT=a['residualUT'],contactResidualUT=c['residualUT'],
                errorMM=float(np.linalg.norm((np.array(best['xy'])-r['xy'])*[50,30]))))
    return output


def normalize_c(pred):
    return [dict(r,errorMM=r['positionErrorMM']) for r in pred]


def baseline_pairs(out):
    out.mkdir(parents=True,exist_ok=True)
    records,_=load_records(ROOT/'reports/hover3-20261125-pass2',(1,2))
    plan=json.loads((ROOT/'evaluation/joint_mlp_air12_plan.json').read_bytes())
    for c in (1,3):
        for a in (1,2):
            name=f'paired-contact{c}-air{a}'
            if (out/(name+'-summary.json')).exists():continue
            train=[r for r in records if r['passID']==(c if r['contact'] else a)]
            test=[r for r in records if r['passID']!=(c if r['contact'] else a)]
            plan['airPasses']=[a]
            with contextlib.redirect_stdout(io.StringIO()):model,_=fit_c(train,plan,name)
            model['conditions']=[dict(state=s,passes=sorted({r['passID'] for r in train if r['state']==s})) for s in ('air','contact')]
            cp=normalize_c(evaluate_c(model,test,'primary'));bp=evaluate_b(train,test)
            save(out/(name+'-C-model.json'),model);save(out/(name+'-C.json'),cp);save(out/(name+'-B.json'),bp)
            summary=dict(C=metrics(cp),B=metrics(bp));save(out/(name+'-summary.json'),summary)
            print(json.dumps(dict(name=name,**summary)),flush=True)


def load_old():
    source=ROOT/'reports/hover3-20261125-pass2';output={}
    for key,file in [('1','old-all.json'),('2','air2-joint-all.json'),('12','new-all.json')]:
        raw=json.loads((source/file).read_bytes())['predictions']
        output[key]={f:[dict(session=r['session'],trial=r['trial'],truth=r['truth'],passID=r['passID'],row=r['row'],column=r['column'],targetXY=r['targetXY'],field=r['field'],mode=r['mode'],**r[f]) for r in raw] for f in 'ABC'}
    return output


def spatial(rows):
    result=[]
    for ry,(lo,hi) in enumerate([(1,5),(6,10),(11,13)]):
        for cx in range(3):
            rs=[r for r in rows if lo<=r['row']<=hi and 1+cx*7<=r['column']<=7+cx*7]
            if rs:result.append(dict(rowRange=[lo,hi],columnRange=[1+cx*7,7+cx*7],metrics=metrics(rs)))
    return result


def hybrid(ds,bs):
    assert len(ds)==len(bs)
    out=[]
    for d,b in zip(ds,bs):
        assert trial_id(d)==trial_id(b) and np.allclose(d['field'],b['field'])
        state=d['predicted'];p=b['predicted']
        if state=='uncertain':state=p
        elif p!='uncertain' and state!=p:state='uncertain'
        out.append(dict(d,predicted=state))
    return out


def summarize(out):
    out.mkdir(parents=True,exist_ok=True)
    base=load_old();held={f:sum([[r for r in base[c][f] if r['mode']=='primary' and r['truth']=='air' and r['passID']==p] for c,p in [('1',2),('2',1)]],[]) for f in 'ABC'}
    result=dict(oldCrossPass={f:metrics(r) for f,r in held.items()},oldSpatial={f:spatial(r) for f,r in held.items()})
    aligned=list(zip(*(held[f] for f in 'ABC')))
    assert all(len({trial_id(r) for r in rs})==1 for rs in aligned)
    result['complementarity']=dict(count=len(aligned),anyCorrect=sum(any(r['predicted']=='air' for r in rs) for rs in aligned),
        uniqueCorrect={f:sum(rs[i]['predicted']=='air' and all(r['predicted']!='air' for j,r in enumerate(rs) if j!=i) for rs in aligned) for i,f in enumerate('ABC')},
        forcedAir={f:sum(r.get('closestState')=='air' for r in held[f]) for f in 'ABC'})
    candidates={}
    for tag in ('v1','svm','balanced','forward','stack','boost'):
        folder=ROOT/('reports/model-d-20261125-'+tag)
        files=[folder/(n+'-predictions.json') for n in ('air1-to-air2','air2-to-air1')]
        if all(p.exists() for p in files):
            rows=sum([json.loads(p.read_bytes()) for p in files],[])
            candidates[tag]=dict(metrics=metrics(rows),spatial=spatial(rows))
    result['candidates']=candidates
    save(out/'summary.json',result)
    print(json.dumps({k:result[k] for k in ('oldCrossPass','complementarity','candidates')},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('stage',choices=('paired','summarize'));p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();baseline_pairs(args.out) if args.stage=='paired' else summarize(args.out)
