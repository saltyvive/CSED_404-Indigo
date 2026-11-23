"""Replay frozen algorithms across all nonempty pass subsets, without test/train mixing."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import statistics as st

from build_printed_grid_model import build as build_a, extract, require
from build_grid_model import Projector as ProjectorA
from build_knn_model import build as build_b, Projector as ProjectorB
from evaluate_printed_pass import metrics, percentile

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT/'evaluation/combination_plan.json'


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def evaluation_role(train_passes, test_pass):
    return 'training_replay' if test_pass in train_passes else 'held_out_pass'


def summarize(predictions):
    result = metrics(predictions)
    result.update(ambiguousRate=sum(p['ambiguous'] for p in predictions)/len(predictions),
                  rejectedCount=sum(not p['accepted'] for p in predictions))
    return result


def predict_pass(projector, batches):
    primary, causal, offline = [], [], []
    for batch in batches:
        for point in batch['points']:
            def predict(field):
                pred = projector.project(field)
                return dict(session=batch['session'], trial=point['trial'], row=point['row'], column=point['column'],
                            targetXY=point['xy'], filteredDeltaUT=field,
                            errorMM=math.hypot(50*(pred['xy'][0]-point['xy'][0]), 30*(pred['xy'][1]-point['xy'][1])), **pred)
            primary.append(predict([v-b for v,b in zip(point['raw'],batch['before']['raw'])]))
            causal.extend(predict(f['filteredDeltaUT']) for f in point['causalFrames'])
            offline.append(predict(point['deltaUT']))
    scatter = []
    for i in range(0,len(causal),3):
        xy = [p['xy'] for p in causal[i:i+3]]
        center = [st.mean(p[k] for p in xy) for k in range(2)]
        scatter.append(math.sqrt(st.mean((50*(p[0]-center[0]))**2+(30*(p[1]-center[1]))**2 for p in xy)))
    report = dict(primary=summarize(primary), causalReplay=summarize(causal),
                  offlineEndBackgroundDiagnostic=summarize(offline),
                  threeFrameScatterMM=dict(median=st.median(scatter),p95=percentile(scatter,.95)),
                  perRow={str(r):summarize([p for p in primary if p['row']==r]) for r in range(1,14)},
                  perRegion={name:summarize([p for p in primary if (p['row'] in (1,13) or p['column'] in (1,21))==boundary])
                             for name,boundary in [('boundary',True),('interior',False)]})
    return report,dict(primary=primary,causal=causal,offline=offline)


def worker(job):
    family, combo, model_path, observations_path, out = job
    raw=model_path.read_bytes(); model=json.loads(raw); batches=json.loads(observations_path.read_text())
    projector=(ProjectorA if family=='A' else ProjectorB)(model)
    train=model['printedGridContext']['passes']; results=[]; held=[]; held_causal=[]
    for test in (1,2,3):
        evaluation=[b for b in batches if b['repetition']==test]
        role=evaluation_role(train,test)
        if role=='held_out_pass':
            require(not set(model['sourceSessions']) & {b['session'] for b in evaluation}, 'Overlapping held-out sources')
        report,pred=predict_pass(projector,evaluation)
        report.update(family=family,combination=combo,trainingPasses=train,testPass=test,role=role,
                      modelSHA256=hashlib.sha256(raw).hexdigest())
        save(out/f'{family}{combo}-test{test}-predictions.json',pred)
        save(out/f'{family}{combo}-test{test}-evaluation.json',report)
        results.append(report)
        if role=='held_out_pass':held.extend(pred['primary']);held_causal.extend(pred['causal'])
    summary=dict(family=family,combination=combo,trainingPasses=train,placements=273*len(train),
                 modelFile=model_path.name,modelSHA256=hashlib.sha256(raw).hexdigest(),evaluations=results,
                 heldOutPrimary=summarize(held) if held else None,
                 heldOutCausal=summarize(held_causal) if held_causal else None)
    print(f'Completed {family}{combo}: held-out passes {[r["testPass"] for r in results if r["role"]=="held_out_pass"]}',flush=True)
    return summary


def run(sessions_file,out,workers):
    require(not out.exists(),'Use a fresh output directory')
    selected=json.loads(sessions_file.read_text()); batches=[]; inventory=[]
    for pass_id in ('1','2','3'):
        require(len(selected[pass_id])==13,'Exactly 13 sessions per pass required')
        for name in selected[pass_id]:
            path=Path(name)
            if not path.is_absolute():path=ROOT/path
            b=extract(path,allow_transient_motion=pass_id=='1',review_note='Previously reviewed pass-1 non-measurement motion; all completed steady intervals remain required to be still.')
            require(b['repetition']==int(pass_id),'Selected pass mismatch');batches.append(b)
            for f in sorted(path.iterdir()):
                if f.is_file():inventory.append(dict(session=path.name,file=f.name,sha256=hashlib.sha256(f.read_bytes()).hexdigest()))
    plan=json.loads(PLAN.read_text());out.mkdir(parents=True);(out/'models').mkdir()
    save(out/'observations.json',batches);save(out/'source_inventory.json',inventory)
    (out/'plan.json').write_bytes(PLAN.read_bytes())
    jobs=[]
    for passes in plan['combinations']:
        combo=''.join(map(str,passes)); train=[b for b in batches if b['repetition'] in passes]
        for family,builder in [('A',build_a),('B',build_b)]:
            model=builder(train,passes);target=out/'models'/f'model_{family}_{combo}.json'
            # Preserve exact bytes for models already frozen before evaluations.
            old={('A','1'):'pass1.json',('A','12'):'pass1_2.json',('B','1'):'knn_pass1.json',('B','12'):'knn_pass1_2.json'}.get((family,combo))
            if old:
                raw=(ROOT/'evaluation/frozen'/old).read_bytes();frozen=json.loads(raw)
                require(all(json.loads(json.dumps(model[k]))==frozen.get(k) for k in model if k!='trainingTrialIDs') and
                        set(model['trainingTrialIDs'])==set(frozen['trainingTrialIDs']),'Frozen model reproduction mismatch')
                target.write_bytes(raw)
            else:save(target,model)
            jobs.append((family,combo,target,out/'observations.json',out))
    with ProcessPoolExecutor(max_workers=workers) as pool: results=list(pool.map(worker,jobs))
    curves={}
    for family in ('A','B'):
        folds=[];single_predictions=[];pair_predictions=[]
        for test in (1,2,3):
            others=[p for p in (1,2,3) if p!=test];pair=''.join(map(str,others));singles=[str(p) for p in others]
            def predictions(c):return json.loads((out/f'{family}{c}-test{test}-predictions.json').read_text())['primary']
            single=[p for c in singles for p in predictions(c)];paired=predictions(pair)
            single_predictions.extend(single);pair_predictions.extend(paired)
            folds.append(dict(testPass=test,singleCombinations=singles,pairCombination=pair,
                              singlesPooled=summarize(single),pair=summarize(paired)))
        curves[family]=dict(folds=folds,singlePooled=summarize(single_predictions),pairPooled=summarize(pair_predictions),
                            note='Descriptive balanced matched-test comparison; singleton pool repeats each test target twice. Only three test passes, not 1638 independent placements.')
    summary=dict(protocol='all_nonempty_pass_subsets_v1',planSHA256=hashlib.sha256(PLAN.read_bytes()).hexdigest(),models=results,matchedLearningCurves=curves)
    save(out/'summary.json',summary)
    print('Saved',out/'summary.json',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--sessions-file',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--workers',type=int,default=2)
    args=p.parse_args();run(args.sessions_file,args.out,args.workers)
