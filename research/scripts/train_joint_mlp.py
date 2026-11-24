"""Shared supervised XY/contact network, exported for dependency-free Swift inference."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path

os.environ.setdefault('VECLIB_MAXIMUM_THREADS', '1')
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load_records(source):
    records, inventory = [], []
    for state, name in [('contact', 'contact_observations.json'), ('air', 'hover_observations.json')]:
        raw = (source/name).read_bytes()
        inventory.append(dict(file=name, sha256=sha(raw)))
        for b in json.loads(raw):
            if state == 'contact' and b['repetition'] not in (1, 3):
                continue
            assert b['pose']['tipContact'] == (state == 'contact')
            assert b['pose']['tipHeightMM'] == (0 if state == 'contact' else 3)
            assert [b['pose'][k] for k in ('phiDegrees', 'thetaDegrees', 'alphaDegrees')] == [0, 90, 0]
            assert state == 'contact' or b['repetition'] == 1
            for p in b['points']:
                corrected = [list(p['deltaUT'])]
                for frame in p['causalFrames']:
                    fraction = (frame['time']-b['before']['time'])/(b['after']['time']-b['before']['time'])
                    corrected.append([v-fraction*(e-s) for v,s,e in zip(frame['filteredDeltaUT'],b['before']['raw'],b['after']['raw'])])
                records.append(dict(state=state, contact=state=='contact', passID=b['repetition'], row=p['row'], column=p['column'],
                    xy=p['xy'], fields=corrected, primary=[v-s for v,s in zip(p['raw'],b['before']['raw'])],
                    causal=[f['filteredDeltaUT'] for f in p['causalFrames']], noiseUT=p['noiseUT'],
                    session=p['session'], trial=p['trial'], campaign=b['campaignID']))
    assert len(records) == 819 and len({r['session']+'/'+r['trial'] for r in records}) == 819
    assert sum(r['contact'] for r in records) == 546
    assert all(len(r['fields']) == 4 for r in records)
    for state, passes in [('contact', [1,3]), ('air', [1])]:
        selected = [r for r in records if r['state']==state]
        assert len({r['campaign'] for r in selected}) == 1
        assert {(r['passID'],r['row'],r['column']) for r in selected} == {(p,r,c) for p in passes for r in range(1,14) for c in range(1,22)}
    assert len({r['campaign'] for r in records}) == 2
    return records, inventory


def row_split(records, fold):
    train = [r for r in records if (r['row']-1)%5 != fold]
    test = [r for r in records if (r['row']-1)%5 == fold]
    assert set(r['row'] for r in train).isdisjoint(r['row'] for r in test)
    assert set(r['session']+'/'+r['trial'] for r in train).isdisjoint(r['session']+'/'+r['trial'] for r in test)
    return train, test


def arrays(records):
    x = np.asarray([f for r in records for f in r['fields']], dtype=np.float64)
    y = np.asarray([[(r['xy'][0]-.5)*2, (r['xy'][1]-.5)*1.2, float(r['contact'])] for r in records for _ in r['fields']])
    # Each height receives half the total loss weight, regardless of pass count.
    w = np.where(y[:,2] == 1, .5/np.sum(y[:,2]==1), .5/np.sum(y[:,2]==0))
    return x,y,w


def sigmoid(x):
    return np.exp(-np.logaddexp(0, -x))


def forward(x, params):
    h1 = np.tanh(x@params[0]+params[1])
    h2 = np.tanh(h1@params[2]+params[3])
    return h2@params[4]+params[5], h1,h2


def loss_grad(x, y, w, params, plan):
    out,h1,h2 = forward(x,params)
    error = out[:,:2]-y[:,:2]
    bce = np.logaddexp(0,out[:,2])-y[:,2]*out[:,2]
    loss = np.sum(w*(.5*np.sum(error*error,axis=1)+plan['contactLossWeight']*bce))
    loss += .5*plan['l2']*sum(np.sum(params[i]**2) for i in (0,2,4))
    d = np.column_stack([error, plan['contactLossWeight']*(sigmoid(out[:,2])-y[:,2])])*w[:,None]
    g4 = h2.T@d+plan['l2']*params[4]; g5 = d.sum(axis=0)
    d2 = (d@params[4].T)*(1-h2*h2)
    g2 = h1.T@d2+plan['l2']*params[2]; g3 = d2.sum(axis=0)
    d1 = (d2@params[2].T)*(1-h1*h1)
    g0 = x.T@d1+plan['l2']*params[0]; g1 = d1.sum(axis=0)
    return float(loss), [g0,g1,g2,g3,g4,g5]


def initialize(plan):
    rng = np.random.default_rng(plan['seed']); params=[]
    for nin,nout in zip(plan['layers'],plan['layers'][1:]):
        params.extend([rng.normal(0, math.sqrt(2/(nin+nout)), (nin,nout)), np.zeros(nout)])
    return params


def fit(records, plan, label):
    raw,y,w = arrays(records)
    mean = (raw*w[:,None]).sum(axis=0)
    scale = np.maximum(np.sqrt(((raw-mean)**2*w[:,None]).sum(axis=0)), 1e-6)
    x=(raw-mean)/scale; params=initialize(plan)
    first=[np.zeros_like(p) for p in params]; second=[np.zeros_like(p) for p in params]
    history=[]
    for epoch in range(1,plan['epochs']+1):
        loss,grad=loss_grad(x,y,w,params,plan)
        norm=math.sqrt(sum(np.sum(g*g) for g in grad)); clip=min(1,5/max(norm,1e-12))
        rate=plan['finalLearningRate']+.5*(plan['learningRate']-plan['finalLearningRate'])*(1+math.cos(math.pi*(epoch-1)/max(1,plan['epochs']-1)))
        for i,g in enumerate(grad):
            g=g*clip
            first[i]=.9*first[i]+.1*g; second[i]=.999*second[i]+.001*g*g
            params[i]-=rate*(first[i]/(1-.9**epoch))/(np.sqrt(second[i]/(1-.999**epoch))+1e-8)
        assert math.isfinite(loss)
        if epoch==1 or epoch%250==0:
            history.append(dict(epoch=epoch,loss=loss)); print(f'{label}: epoch {epoch}, loss {loss:.6f}',flush=True)
    model=dict(version=1,method=plan['method'],inputMean=mean.tolist(),inputScale=scale.tolist(),
        layers=[dict(weights=params[i].T.tolist(),bias=params[i+1].tolist()) for i in (0,2,4)],
        widthMM=50,heightMM=30,contactLow=plan['uncertaintyBand'][0],contactHigh=plan['uncertaintyBand'][1],
        minimumSignalUT=max(3,.2*float(np.linalg.norm(raw,axis=1).min())),
        supportLimitUT=max(3,5*max(r['noiseUT'] for r in records)),supportFieldsUT=raw.tolist(),
        trainingTrialIDs=sorted(r['session']+'/'+r['trial'] for r in records),
        sourceSessions=sorted({r['session'] for r in records}),
        conditions=[dict(state=state,passes=passes,campaignID=next(r['campaign'] for r in records if r['state']==state),
                         tipHeightMM=0 if state=='contact' else 3,phiDegrees=0,thetaDegrees=90,alphaDegrees=0)
                    for state,passes in [('contact',[1,3]),('air',[1])]],
        scope=plan['limitations'])
    return model,history


def predict(model, fields):
    raw=np.asarray(fields,dtype=np.float64)
    assert raw.ndim==2 and raw.shape[1]==3 and np.isfinite(raw).all()
    x=(raw-model['inputMean'])/model['inputScale']
    for i,layer in enumerate(model['layers']):
        x=x@np.asarray(layer['weights']).T+layer['bias']
        if i<2: x=np.tanh(x)
    xy=x[:,:2]/[2,1.2]+.5; scores=sigmoid(x[:,2]); support=np.asarray(model['supportFieldsUT'])
    rows=[]
    for f,p,score in zip(raw,xy,scores):
        distance=float(np.linalg.norm(support-f,axis=1).min());signal=float(np.linalg.norm(f))
        shown=signal>=model['minimumSignalUT']; in_support=distance<=model['supportLimitUT']
        in_bounds=bool(np.all((p>=-.05)&(p<=1.05)))
        ambiguous=model['contactLow']<score<model['contactHigh']
        accepted=shown and in_support and in_bounds and not ambiguous
        candidate='contact' if score>=.5 else 'air'
        rows.append(dict(xy=p.tolist(),contactScore=float(score),supportDistanceUT=distance,signalUT=signal,
            shown=shown,inSupport=in_support,inBounds=in_bounds,ambiguous=bool(ambiguous),accepted=bool(accepted),
            closestState=candidate,predicted=candidate if accepted else 'uncertain'))
    return rows


def evaluate(model, records, mode):
    queries=[(r,f) for r in records for f in ([r['primary']] if mode=='primary' else r['causal'])]
    rows=[]
    for (r,f),pred in zip(queries,predict(model,[f for r,f in queries])):
        rows.append(dict(**pred,truth=r['state'],passID=r['passID'],row=r['row'],column=r['column'],
            session=r['session'],trial=r['trial'],field=f,targetXY=r['xy'],
            positionErrorMM=math.hypot(50*(pred['xy'][0]-r['xy'][0]),30*(pred['xy'][1]-r['xy'][1]))))
    return rows


def summarize(rows):
    def stats(samples):
        errors=[r['positionErrorMM'] for r in samples]
        accepted=sum(r['accepted'] for r in samples)
        correct=sum(r['predicted']==r['truth'] for r in samples)
        return dict(count=len(samples),accepted=accepted,correct=correct,wrong=accepted-correct,uncertain=len(samples)-accepted,
            medianXYErrorMM=float(np.median(errors)),p95XYErrorMM=float(np.percentile(errors,95)),
            forcedHeightAccuracy=sum(r['closestState']==r['truth'] for r in samples)/len(samples),
            correctHeightAndXYWithin2p5MM=sum(r['predicted']==r['truth'] and r['positionErrorMM']<=2.5 for r in samples))
    return {state:stats([r for r in rows if r['truth']==state]) for state in ('contact','air')}


def run(source,out):
    assert not out.exists(), 'Use a fresh report directory'
    plan_raw=(ROOT/'evaluation/joint_mlp_plan.json').read_bytes();plan=json.loads(plan_raw)
    records,inventory=load_records(source);out.mkdir(parents=True)
    save(out/'source_inventory.json',inventory);save(out/'plan.json',plan)
    held=[]; folds=[]
    for fold in range(5):
        train,test=row_split(records,fold)
        model,history=fit(train,plan,f'fold {fold+1}/5')
        pred=evaluate(model,test,'primary');held.extend(pred)
        save(out/f'fold{fold+1}_model.json',model);save(out/f'fold{fold+1}_history.json',history)
        folds.append(dict(fold=fold,testRows=sorted({r['row'] for r in test}),trainTrials=model['trainingTrialIDs'],
                          testTrials=sorted(r['session']+'/'+r['trial'] for r in test),summary=summarize(pred)))
    model,history=fit(records,plan,'final all placements')
    model['planSHA256']=sha(plan_raw);model['observationFiles']=inventory
    replay=evaluate(model,records,'primary');causal=evaluate(model,records,'causal')
    save(out/'joint_mlp.json',model);save(out/'final_history.json',history)
    save(out/'row_holdout.json',held);save(out/'folds.json',folds)
    save(out/'training_replay.json',replay);save(out/'training_causal_replay.json',causal)
    parity=[dict(field=r['field'],**{k:r[k] for k in ['xy','contactScore','supportDistanceUT','signalUT','shown','inSupport','inBounds','ambiguous','accepted','closestState','predicted']}) for r in replay+causal]
    for field in [[0,0,0],[1000,-1000,1000]]:
        parity.append(dict(field=field,**predict(model,[field])[0]))
    save(out/'swift_parity.json',parity)
    summary=dict(method=plan['method'],modelSHA256=sha((out/'joint_mlp.json').read_bytes()),planSHA256=sha(plan_raw),
        placements=819,correlatedRepresentatives=3276,independentAirRepeatValidation=False,
        rowHoldout=dict(role='same_campaign_spatial_row_holdout_not_independent_repeat',summary=summarize(held)),
        trainingReplay=dict(role='training_replay',summary=summarize(replay)),
        trainingCausalReplay=dict(role='correlated_training_frame_replay',summary=summarize(causal)))
    save(out/'summary.json',summary);print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=ROOT/'reports/hover3-20261125-pass1')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();run(args.source,args.out)
