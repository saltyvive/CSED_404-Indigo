"""Compare frozen B against an unseen whole pass; save before building B's update."""
import argparse
import hashlib
import json
import math
from pathlib import Path

from build_printed_grid_model import extract, require, build as build_grid
from build_knn_model import build, Projector
from evaluate_printed_pass import metrics


def run(model_path, grid_model_path, training_paths, evaluation_paths, test_pass, out, **review):
    require(not out.exists(), 'Use a fresh output directory')
    raw=model_path.read_bytes(); frozen=json.loads(raw); digest=hashlib.sha256(raw).hexdigest()
    grid_raw=grid_model_path.read_bytes(); grid=json.loads(grid_raw); grid_digest=hashlib.sha256(grid_raw).hexdigest()
    training=[extract(p,**review) for p in training_paths]; evaluation=[extract(p,**review) for p in evaluation_paths]
    previous=list(range(1,test_pass)); train_ids={b['session'] for b in training}; eval_ids={b['session'] for b in evaluation}
    require(test_pass in (2,3) and frozen['printedGridContext']['passes']==previous, 'Wrong frozen training passes')
    require(train_ids==set(frozen['sourceSessions'])==set(grid['sourceSessions']) and not train_ids&eval_ids, 'Overlapping/wrong sources')
    require(json.loads(json.dumps(build(training,previous)))==frozen, 'Training does not reproduce frozen B')
    rebuilt_grid=json.loads(json.dumps(build_grid(training,previous)))
    require(all(rebuilt_grid[k]==grid.get(k) for k in rebuilt_grid if k!='trainingTrialIDs') and
            set(rebuilt_grid['trainingTrialIDs'])==set(grid['trainingTrialIDs']), 'Frozen A source mismatch')
    require(len(evaluation)==13 and {(b['repetition'],b['row']) for b in evaluation}=={(test_pass,r) for r in range(1,14)}, 'Complete unseen pass required')
    for b in evaluation:
        require(all(b[k]==training[0][k] for k in ('campaignID','device','setup','pose')), 'Evaluation setup mismatch')
        require(b['evaluationModelSHA256']==grid_digest and b['evaluationTrainingPasses']==previous, 'Recorded A snapshot mismatch')
        if test_pass==3:
            require(b.get('evaluationKNNModelSHA256')==digest, 'Recorded B snapshot mismatch')
    projector=Projector(frozen); primary=[]; causal=[]; offline=[]
    for batch in evaluation:
        for point in batch['points']:
            def predict(field):
                pred=projector.project(field)
                return dict(session=batch['session'],trial=point['trial'],row=point['row'],column=point['column'],
                            targetXY=point['xy'],filteredDeltaUT=field,
                            errorMM=math.hypot(50*(pred['xy'][0]-point['xy'][0]),30*(pred['xy'][1]-point['xy'][1])),**pred)
            primary.append(predict([v-b for v,b in zip(point['raw'],batch['before']['raw'])]))
            causal.extend(predict(f['filteredDeltaUT']) for f in point['causalFrames'])
            offline.append(predict(point['deltaUT']))
    report=dict(protocol='whole_pass_test_then_train_knn_v1',evaluatedPass=test_pass,trainingPasses=previous,
                frozenModelSHA256=digest,comparisonGridModelSHA256=grid_digest,
                evaluationMode='Retrospective held-out replay; B not deployed during pass 2' if test_pass==2 else 'Frozen before collection',
                trainingSessions=sorted(train_ids),evaluationSessions=sorted(eval_ids),primary=metrics(primary),causalReplay=metrics(causal),
                offlineEndBackgroundDiagnostic=metrics(offline),
                perRow={str(r):metrics([p for p in primary if p['row']==r]) for r in range(1,14)},
                perRegion={name:metrics([p for p in primary if (p['row'] in (1,13) or p['column'] in (1,21))==boundary]) for name,boundary in [('boundary',True),('interior',False)]},
                limits=['Known grid positions, unseen repeated placements; not arbitrary pose or handwriting accuracy.',
                        'Whole-hold representatives and correlated 0.12s frames are reported separately.',
                        'Rejected estimates remain in candidate error statistics and count as failures in threshold success.',
                        'No evaluation-score tuning performed. Next combined model has not been independently evaluated.'])
    out.mkdir(parents=True)
    (out/'frozen_model.json').write_bytes(raw)
    (out/'evaluation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False))
    (out/'predictions.json').write_text(json.dumps(dict(primary=primary,causal=causal,offline=offline),indent=2,allow_nan=False))
    inventory=[dict(role=role,session=p.name,file=f.name,sha256=hashlib.sha256(f.read_bytes()).hexdigest())
               for role,paths in [('train',training_paths),('evaluate',evaluation_paths)] for p in paths for f in sorted(p.iterdir()) if f.is_file()]
    (out/'source_inventory.json').write_text(json.dumps(inventory,indent=2))
    updated=build(training+evaluation,list(range(1,test_pass+1)))
    (out/'next_model.json').write_text(json.dumps(updated,ensure_ascii=False,indent=2,allow_nan=False))
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model',type=Path,required=True); p.add_argument('--grid-model',type=Path,required=True)
    p.add_argument('--training-sessions',type=Path,nargs='+',required=True); p.add_argument('--evaluation-sessions',type=Path,nargs='+',required=True)
    p.add_argument('--test-pass',type=int,choices=[2,3],required=True); p.add_argument('--out',type=Path,required=True)
    p.add_argument('--allow-reviewed-transient-motion',action='store_true'); p.add_argument('--review-note')
    a=p.parse_args();run(a.model,a.grid_model,a.training_sessions,a.evaluation_sessions,a.test_pass,a.out,
                        allow_transient_motion=a.allow_reviewed_transient_motion,review_note=a.review_note)
