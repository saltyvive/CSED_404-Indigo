"""Freeze the selected experimental hybrid and retain every failed ablation."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from train_joint_mlp import ROOT, load_records, save
from experiment_model_d import evaluate, metrics, trial_id
from compare_model_d import build_b, load_old, spatial


def run(out,export=False):
    out.mkdir(parents=True,exist_ok=True)
    source=ROOT/'reports/model-d-20261125-balanced'
    plan_path=ROOT/'evaluation/model_d_hybrid_plan.json'
    guard_plan=json.loads(plan_path.read_bytes());save(out/'plan.json',guard_plan)
    records,inventory=load_records(ROOT/'reports/hover3-20261125-pass2',(1,2))
    results={}
    for path in sorted(source.glob('*-model.json')):
        name=path.name.removesuffix('-model.json');model=json.loads(path.read_bytes())
        train_ids=set(model['trainingTrialIDs']);train=[r for r in records if trial_id(r) in train_ids]
        if name=='final':test=records
        elif name.startswith('air'):
            test=[r for r in records if not r['contact'] and trial_id(r) not in train_ids]
        else:test=[r for r in records if trial_id(r) not in train_ids]
        assert len(train)==len(train_ids)
        if name!='final':assert train_ids.isdisjoint(map(trial_id,test))
        model['prototypeGuard']={s:build_b([r for r in train if r['state']==s]) for s in ('air','contact')}
        model['guardPolicy']='If SVM abstains and B accepts, use B height AND B XY. If accepted SVM and accepted B disagree, abstain. Otherwise use SVM height and local affine XY.'
        model['name']='Experimental D: SVM height + multiprototype guard + local affine XY'
        model['hybridPlanSHA256']=hashlib.sha256(plan_path.read_bytes()).hexdigest()
        model['sourceTrainingModelSHA256']=hashlib.sha256(path.read_bytes()).hexdigest()
        model['sourceInventory']=inventory
        model['conditions']=[dict(state=s,passes=sorted({r['passID'] for r in train if r['state']==s}),
            tipHeightMM=0 if s=='contact' else 3,phiDegrees=0,thetaDegrees=90,alphaDegrees=0) for s in ('contact','air')]
        model['inferenceInputs']=['background-subtracted Bx uT','background-subtracted By uT','background-subtracted Bz uT']
        model['scope']='Retrospectively selected on existing fixed-pose campaigns. Not prospectively validated. Row-held-out contact false-air risk remains. No iPad deployment.'
        pred=evaluate(model,test);causal=evaluate(model,test,'causal')
        save(out/(name+'-model.json'),model);save(out/(name+'-predictions.json'),pred);save(out/(name+'-causal.json'),causal)
        result=dict(role='training_replay' if name=='final' else 'retrospective_outer_holdout',selection=model['selection'],primary=metrics(pred),causal=metrics(causal),
            trainingTrials=model['trainingTrialIDs'],testTrials=sorted(map(trial_id,test)))
        save(out/(name+'-summary.json'),result);results[name]=result
    old=load_old()
    cross={f:sum([[r for r in old[c][f] if r['mode']=='primary' and r['truth']=='air' and r['passID']==p] for c,p in [('1',2),('2',1)]],[]) for f in 'ABC'}
    cross['D']=sum([json.loads((out/(n+'-predictions.json')).read_bytes()) for n in ('air1-to-air2','air2-to-air1')],[])
    # Same 13 physical rows sampled as clusters; paired across models and passes.
    # This does not account for two-pass sampling uncertainty or model-search bias.
    c_lookup={trial_id(r):r for r in cross['C']};d=cross['D'];c=[c_lookup[trial_id(r)] for r in d]
    rng=np.random.default_rng(20261125);boot=[]
    for _ in range(3000):
        ids=np.concatenate([np.flatnonzero(np.array([r['row'] for r in d])==row) for row in rng.integers(1,14,13)])
        boot.append([np.mean([int(d[i]['predicted']==state)-int(c[i]['predicted']==state) for i in ids]) for state in ('air','contact','uncertain')])
    interval=np.percentile(np.array(boot),[2.5,97.5],axis=0).T.tolist()
    summary=dict(variants=results,crossPass={f:metrics(rs) for f,rs in cross.items()},regions={f:spatial(rs) for f,rs in cross.items()},
        rowClusterBootstrap=dict(deltaDminusC=['correctAirRate','wrongContactRate','abstainRate'],interval95=interval,
            scope='Conditional exploratory row-cluster intervals; two repeated air passes, not independent 546 experiments; model selection uncertainty excluded.'),inventory=inventory)
    for group,names in [('spatial',[f'rowfold{k}' for k in range(5)]),('paired',[f'paired-contact{c}-air{a}' for c in (1,3) for a in (1,2)])]:
        ds=sum([json.loads((out/(n+'-predictions.json')).read_bytes()) for n in names],[])
        cs=(json.loads((ROOT/'reports/joint-mlp-20261125-air12/row_holdout.json').read_bytes()) if group=='spatial' else
            sum([json.loads((ROOT/'reports/model-d-20261125-baselines'/(n+'-C.json')).read_bytes()) for n in names],[]))
        cs=[dict(r,errorMM=r.get('errorMM',r.get('positionErrorMM'))) for r in cs]
        summary[group]=dict(C=metrics(cs),D=metrics(ds))
    final_c=[r for r in old['12']['C'] if r['mode']=='primary'];summary['finalReplay']=dict(C=metrics(final_c),D=results['final']['primary'])
    save(out/'summary.json',summary)
    if export:
        dest=ROOT/'evaluation/experimental';dest.mkdir(parents=True,exist_ok=True)
        entries=[]
        for combo,name in [('1','air1-to-air2'),('2','air2-to-air1'),('12','final')]:
            data=(out/(name+'-model.json')).read_bytes();target=dest/f'model_D_contact13_air{combo}.json'
            if target.exists():assert target.read_bytes()==data, 'Experimental asset differs: use a new version'
            else:target.write_bytes(data)
            entries.append(dict(airPasses=list(map(int,combo)),contactPasses=[1,3],file=target.name,sha256=hashlib.sha256(data).hexdigest()))
        catalog=dict(version=1,experimental=True,installedOnIPad=False,recommendedDefaultReplacement=False,entries=entries,
            hybridPlanSHA256=hashlib.sha256(plan_path.read_bytes()).hexdigest(),summarySHA256=hashlib.sha256((out/'summary.json').read_bytes()).hexdigest())
        target=dest/'model_d_catalog.json'
        if target.exists():assert json.loads(target.read_bytes())==catalog
        else:save(target,catalog)
    print(json.dumps({k:summary[k] for k in ('crossPass','spatial','paired','finalReplay','rowClusterBootstrap')},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--export',action='store_true');args=p.parse_args();run(args.out,args.export)
